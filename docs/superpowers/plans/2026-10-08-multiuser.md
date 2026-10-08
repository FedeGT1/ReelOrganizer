# Multiutente Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate hubs, categories, and reels per user account, replacing the single fixed env-var login with a `User` table, admin-created accounts, and per-user data scoping across every router.

**Architecture:** A new `User` table backs login (scrypt-hashed passwords); `user_id` is added to `Location`, `Reel`, `AiSession`, `AskSession`, and `Category`'s primary key becomes `(user_id, key)`. A centralized `app/scoping.py` helper is the only way routers query these five models, so every query site is auditable in one place. A one-shot, idempotent startup migration backfills existing VPS data onto a bootstrap user created from today's `AUTH_USERNAME`/`AUTH_PASSWORD`. Functions that do *global* lookups across these models (`resolve_place`, `find_duplicate_reel`, `get_taxonomy`) take an explicit `user_id` parameter; functions that reach a child row only through an already-ownership-checked parent (e.g. `ReelType` via a verified `Reel`) do not need their own `user_id` column — ownership is inherited transitively.

**Tech Stack:** FastAPI, SQLModel/SQLAlchemy, SQLite, Starlette `SessionMiddleware`, Python stdlib `hashlib.scrypt` (no new dependency), pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-multiuser-design.md`

## Global Constraints

- No new third-party dependency for password hashing — use stdlib `hashlib.scrypt` (VPS is EOL Ubuntu 20.10 with limited room to compile native extensions like bcrypt/argon2-cffi).
- Every schema change must be additive or migrated in-place with existing rows preserved — never drop/recreate a table without copying its data first (real data on the user's self-hosted VPS, no backups infra).
- SQLite does not enforce FK constraints in this project (no `PRAGMA foreign_keys=ON` anywhere) — `ReelType.type` keeps referencing `Category.key` as a plain string, no composite FK needed.
- No public registration page — accounts are created only via the `scripts/create_user.py` CLI.
- `AUTH_USERNAME`/`AUTH_PASSWORD` remain required env vars at startup (bootstrap-only after the first migration), per the existing `require_env` fail-closed pattern in `app/main.py`.

## Review Focus

- **Category key collisions across users**: two users both creating a category with key `"food"` must not collide, overwrite each other's label/icon, or let deleting one user's `"food"` category delete `ReelType` rows belonging to the other user's reels tagged `"food"`.
- **Cross-user location/reel matching**: `resolve_place` (AI categorization) and `find_duplicate_reel` must never match, merge, or surface another user's location/reel — both query `Location`/`Reel` globally today.
- **Stale/foreign id in a request payload**: a crafted `location_id`, `parent_id`, or session id belonging to another user must 404, not silently operate on or leak that other user's row.
- **Migration idempotency**: running the startup migration twice (e.g. container restart) must not create a second bootstrap user, re-run the `Category` table rebuild, or re-backfill already-migrated rows.
- **Fresh install vs. upgrade**: a brand-new empty DB must still get a seeded bootstrap user with default hubs/categories (today's first-run behavior), while an upgraded VPS with real data must have that exact data attached to the bootstrap user, not re-seeded alongside it.

---

## Task 1: `User` model and password hashing

**Files:**
- Modify: `app/models.py` (add `User` class)
- Modify: `app/auth.py` (add `hash_password`, `verify_password`)
- Modify: `tests/test_auth_helpers.py` (replace env-var-based `verify_credentials` tests)
- Test: `tests/test_auth_helpers.py`

**Interfaces:**
- Produces: `app.models.User(id: str, username: str, password_hash: str, created_at: datetime)`; `app.auth.hash_password(password: str) -> str`; `app.auth.verify_password(password: str, password_hash: str) -> bool`.

- [ ] **Step 1: Write the failing tests for password hashing**

```python
# tests/test_auth_helpers.py -- add these, keep the existing RateLimiter/get_client_ip tests
from app.auth import hash_password, verify_password


def test_hash_password_verifies_correct_password():
    password_hash = hash_password("s3cret")
    assert verify_password("s3cret", password_hash) is True


def test_hash_password_rejects_wrong_password():
    password_hash = hash_password("s3cret")
    assert verify_password("wrong", password_hash) is False


def test_hash_password_produces_different_hashes_for_same_password():
    # Different random salt each call -- defends against rainbow tables.
    assert hash_password("s3cret") != hash_password("s3cret")


def test_verify_password_rejects_malformed_hash():
    assert verify_password("s3cret", "not-a-valid-hash") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_auth_helpers.py -v`
Expected: FAIL with `ImportError: cannot import name 'hash_password'`

- [ ] **Step 3: Add the `User` model**

In `app/models.py`, add after the `new_uuid` helper (before `Location`):

```python
class User(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: Implement `hash_password`/`verify_password`**

In `app/auth.py`, add near the top (after the imports, before `require_env`):

```python
import hashlib

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    salt_hex, _, digest_hex = password_hash.partition("$")
    if not digest_hex:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    candidate = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN
    )
    return secrets.compare_digest(candidate, expected)
```

(`secrets` is already imported at the top of `app/auth.py`.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_auth_helpers.py -v`
Expected: PASS (including the pre-existing `verify_credentials`/`RateLimiter` tests — they are rewritten in Task 5, not this one; leave them as-is for now, they still pass since `verify_credentials`'s old signature is untouched in this task).

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/auth.py tests/test_auth_helpers.py
git commit -m "feat: add User model and scrypt password hashing"
```

---

## Task 2: `app/scoping.py` centralized query helpers

**Files:**
- Create: `app/scoping.py`
- Test: `tests/test_scoping.py`

**Interfaces:**
- Consumes: `app.models.{Location,Reel,Category,AiSession,AskSession}` (from Task 1/3).
- Produces: `user_query(Model, user_id) -> SelectOfScalar`; `get_owned(session, Model, id_, user_id) -> Optional[Model]`; `get_owned_category(session, key, user_id) -> Optional[Category]`. Every later router task imports these.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scoping.py
from sqlmodel import SQLModel, Session, create_engine

from app.models import Category, Location
from app.scoping import get_owned, get_owned_category, user_query


def _engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return engine


def test_user_query_returns_only_rows_for_that_user():
    engine = _engine()
    with Session(engine) as session:
        session.add(Location(name="A", is_hub=True, user_id="user-1"))
        session.add(Location(name="B", is_hub=True, user_id="user-2"))
        session.commit()

        results = session.exec(user_query(Location, "user-1")).all()

        assert [loc.name for loc in results] == ["A"]


def test_get_owned_returns_row_when_owned():
    engine = _engine()
    with Session(engine) as session:
        loc = Location(name="A", is_hub=True, user_id="user-1")
        session.add(loc)
        session.commit()
        session.refresh(loc)

        result = get_owned(session, Location, loc.id, "user-1")

        assert result is not None
        assert result.id == loc.id


def test_get_owned_returns_none_when_owned_by_another_user():
    engine = _engine()
    with Session(engine) as session:
        loc = Location(name="A", is_hub=True, user_id="user-1")
        session.add(loc)
        session.commit()
        session.refresh(loc)

        assert get_owned(session, Location, loc.id, "user-2") is None


def test_get_owned_returns_none_when_missing():
    engine = _engine()
    with Session(engine) as session:
        assert get_owned(session, Location, "does-not-exist", "user-1") is None


def test_get_owned_category_scopes_by_composite_key():
    engine = _engine()
    with Session(engine) as session:
        session.add(Category(user_id="user-1", key="food", label="Cibo", icon="🍜"))
        session.add(Category(user_id="user-2", key="food", label="Food", icon="🍔"))
        session.commit()

        own = get_owned_category(session, "food", "user-1")
        other = get_owned_category(session, "food", "user-3")

        assert own is not None and own.label == "Cibo"
        assert other is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_scoping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scoping'`

- [ ] **Step 3: Implement `app/scoping.py`**

```python
from typing import Optional, Type, TypeVar

from sqlmodel import Session, SQLModel, select

from app.models import Category

ModelT = TypeVar("ModelT", bound=SQLModel)


def user_query(Model: Type[ModelT], user_id: str):
    return select(Model).where(Model.user_id == user_id)


def get_owned(session: Session, Model: Type[ModelT], id_: str, user_id: str) -> Optional[ModelT]:
    row = session.get(Model, id_)
    if row is None or row.user_id != user_id:
        return None
    return row


def get_owned_category(session: Session, key: str, user_id: str) -> Optional[Category]:
    return session.get(Category, (user_id, key))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_scoping.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/scoping.py tests/test_scoping.py
git commit -m "feat: add centralized per-user query scoping helpers"
```

---

## Task 3: `user_id` columns and `Category` composite key in models

**Files:**
- Modify: `app/models.py:12-42` (the `Location`, `Reel`, `Category` classes; `AiSession`/`AskSession` further down)
- Modify: `tests/test_models.py:124` (the one test that constructs a bare `Category`)
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Location.user_id: Optional[str]`, `Reel.user_id: Optional[str]`, `AiSession.user_id: Optional[str]`, `AskSession.user_id: Optional[str]`, `Category.user_id: str` (part of its primary key, alongside `key`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py -- replace the existing test_create_category body
def test_create_category():
    from app.models import Category

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        category = Category(user_id="user-1", key="food", label="Cibo", icon="🍜")
        session.add(category)
        session.commit()
        session.refresh(category)

        assert category.key == "food"
        assert category.user_id == "user-1"
        assert category.label == "Cibo"
        assert isinstance(category.created_at, datetime)


def test_two_users_can_have_a_category_with_the_same_key():
    from app.models import Category

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Category(user_id="user-1", key="food", label="Cibo", icon="🍜"))
        session.add(Category(user_id="user-2", key="food", label="Food", icon="🍔"))
        session.commit()  # must not raise a primary key collision
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_create_category -v`
Expected: FAIL with `TypeError: Category() got an unexpected keyword argument 'user_id'`

- [ ] **Step 3: Update the models**

In `app/models.py`, replace the `Location`, `Reel`, and `Category` classes:

```python
class Location(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    user_id: Optional[str] = Field(default=None, foreign_key="user.id")
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = Field(default=None, foreign_key="location.id")
    lat: Optional[float] = None
    lon: Optional[float] = None
    geocode_confidence: Optional[str] = None


class Reel(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    user_id: Optional[str] = Field(default=None, foreign_key="user.id")
    link: str
    location_id: str = Field(foreign_key="location.id")
    note: Optional[str] = None
    caption: Optional[str] = None
    transcript: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Category(SQLModel, table=True):
    user_id: str = Field(foreign_key="user.id", primary_key=True)
    key: str = Field(primary_key=True)
    label: str
    icon: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

And add `user_id: Optional[str] = Field(default=None, foreign_key="user.id")` as the second field (right after `id`) in both `AiSession` and `AskSession`:

```python
class AiSession(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    user_id: Optional[str] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

```python
class AskSession(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    user_id: Optional[str] = Field(default=None, foreign_key="user.id")
    location_id: Optional[str] = Field(default=None, foreign_key="location.id")
    category_key: Optional[str] = Field(default=None, foreign_key="category.key")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

(`User` must appear before these classes in the file, as already placed in Task 1 — SQLModel resolves `foreign_key="user.id"` by table name at metadata-creation time, not import order, so placement doesn't actually matter, but keep `User` first for readability.)

- [ ] **Step 4: Run the full model test file**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS — including the untouched `Location`/`Reel`/`AiSession`/`AskSession` tests, since their `user_id` is optional and defaults to `None`.

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: add user_id to Location/Reel/AiSession/AskSession, make Category key per-user"
```

---

## Task 4: Startup migration — additive columns, `Category` rebuild, bootstrap user

**Files:**
- Modify: `app/db.py` (whole file — `_ADDITIVE_COLUMNS`, new migration functions, `create_db_and_tables`)
- Modify: `tests/test_db_migration.py` (add new tests, keep the existing `_ensure_columns` ones)
- Test: `tests/test_db_migration.py`

**Interfaces:**
- Consumes: `app.auth.hash_password` (Task 1), `app.seed.seed_user_if_empty` (Task 6 — see note in Step 6 about ordering).
- Produces: `app.db.create_db_and_tables() -> None` (unchanged signature, now also runs the one-shot migration internally).

This task is implemented before Task 6 (`seed.py` rename) exists, so Step 6 below stubs the seed call and Task 6 fills it in — note this explicitly in that step.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db_migration.py -- add below the existing _ensure_columns tests
from datetime import datetime

from app.db import _get_or_create_bootstrap_user, _migrate_category_table_if_needed, _needs_user_migration


def _make_pre_multiuser_engine(tmp_path):
    db_path = tmp_path / "pre_multiuser.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE user (id TEXT PRIMARY KEY, username TEXT UNIQUE, "
            "password_hash TEXT, created_at TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE location (id TEXT PRIMARY KEY, name TEXT, is_hub BOOLEAN, "
            "parent_id TEXT, lat REAL, lon REAL, geocode_confidence TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE reel (id TEXT PRIMARY KEY, link TEXT, location_id TEXT, "
            "note TEXT, caption TEXT, transcript TEXT, created_at TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE aisession (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE asksession (id TEXT PRIMARY KEY, location_id TEXT, "
            "category_key TEXT, created_at TEXT, updated_at TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE category (key TEXT PRIMARY KEY, label TEXT, icon TEXT, created_at TEXT)"
        ))
        conn.execute(text(
            "INSERT INTO location (id, name, is_hub) VALUES ('loc1', 'Tokyo', 1)"
        ))
        conn.execute(text(
            "INSERT INTO reel (id, link, location_id, created_at) "
            "VALUES ('r1', 'https://instagram.com/reel/x', 'loc1', '2026-01-01')"
        ))
        conn.execute(text(
            "INSERT INTO category (key, label, icon, created_at) "
            "VALUES ('food', 'Cibo', '🍜', '2026-01-01')"
        ))
    return engine


def test_needs_user_migration_true_for_pre_multiuser_db(tmp_path, monkeypatch):
    engine = _make_pre_multiuser_engine(tmp_path)
    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")
    # location/reel/asksession don't have user_id yet -- add it as _ensure_columns would
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE location ADD COLUMN user_id TEXT"))
        conn.execute(text("ALTER TABLE reel ADD COLUMN user_id TEXT"))
        conn.execute(text("ALTER TABLE aisession ADD COLUMN user_id TEXT"))
        conn.execute(text("ALTER TABLE asksession ADD COLUMN user_id TEXT"))

    with engine.connect() as conn:
        assert _needs_user_migration(conn) is True


def test_get_or_create_bootstrap_user_creates_one_from_env_vars(tmp_path, monkeypatch):
    engine = _make_pre_multiuser_engine(tmp_path)
    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")

    with engine.begin() as conn:
        user_id = _get_or_create_bootstrap_user(conn)
        row = conn.execute(text("SELECT username FROM user WHERE id = :id"), {"id": user_id}).first()
        assert row.username == "owner"


def test_get_or_create_bootstrap_user_is_idempotent(tmp_path, monkeypatch):
    engine = _make_pre_multiuser_engine(tmp_path)
    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")

    with engine.begin() as conn:
        first_id = _get_or_create_bootstrap_user(conn)
        second_id = _get_or_create_bootstrap_user(conn)
        assert first_id == second_id
        count = conn.execute(text("SELECT COUNT(*) FROM user")).scalar()
        assert count == 1


def test_migrate_category_table_rebuilds_with_composite_key(tmp_path, monkeypatch):
    engine = _make_pre_multiuser_engine(tmp_path)
    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")

    with engine.begin() as conn:
        bootstrap_id = _get_or_create_bootstrap_user(conn)
        _migrate_category_table_if_needed(conn, bootstrap_id)

        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(category)"))}
        assert "user_id" in columns
        row = conn.execute(
            text("SELECT user_id, label FROM category WHERE key = 'food'")
        ).first()
        assert row.user_id == bootstrap_id
        assert row.label == "Cibo"


def test_migrate_category_table_is_idempotent(tmp_path, monkeypatch):
    engine = _make_pre_multiuser_engine(tmp_path)
    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")

    with engine.begin() as conn:
        bootstrap_id = _get_or_create_bootstrap_user(conn)
        _migrate_category_table_if_needed(conn, bootstrap_id)
        _migrate_category_table_if_needed(conn, bootstrap_id)  # must not raise

        count = conn.execute(text("SELECT COUNT(*) FROM category")).scalar()
        assert count == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_db_migration.py -v`
Expected: FAIL with `ImportError: cannot import name '_get_or_create_bootstrap_user'`

- [ ] **Step 3: Add `user_id` to `_ADDITIVE_COLUMNS`**

In `app/db.py`, replace `_ADDITIVE_COLUMNS`:

```python
_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "location": [("geocode_confidence", "TEXT"), ("user_id", "TEXT")],
    "reel": [("caption", "TEXT"), ("transcript", "TEXT"), ("user_id", "TEXT")],
    "aisession": [("user_id", "TEXT")],
    "asksession": [("user_id", "TEXT")],
}
```

- [ ] **Step 4: Implement the migration functions**

In `app/db.py`, add after `_ensure_columns` (needs `from datetime import datetime`, `from app.auth import hash_password` added to the imports at the top of the file):

```python
def _needs_user_migration(conn) -> bool:
    category_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(category)"))}
    if "user_id" not in category_cols:
        return True
    for table in ("location", "reel", "aisession", "asksession"):
        null_row = conn.execute(text(f"SELECT 1 FROM {table} WHERE user_id IS NULL LIMIT 1")).first()
        if null_row is not None:
            return True
    return False


def _get_or_create_bootstrap_user(conn) -> str:
    row = conn.execute(text("SELECT id FROM user ORDER BY created_at LIMIT 1")).first()
    if row is not None:
        return row[0]
    user_id = new_uuid()
    username = os.environ.get("AUTH_USERNAME", "")
    password = os.environ.get("AUTH_PASSWORD", "")
    conn.execute(
        text(
            "INSERT INTO user (id, username, password_hash, created_at) "
            "VALUES (:id, :username, :password_hash, :created_at)"
        ),
        {
            "id": user_id,
            "username": username,
            "password_hash": hash_password(password),
            "created_at": datetime.utcnow().isoformat(),
        },
    )
    return user_id


def _migrate_category_table_if_needed(conn, bootstrap_user_id: str) -> None:
    columns = {row[1] for row in conn.execute(text("PRAGMA table_info(category)"))}
    if "user_id" in columns:
        return
    conn.execute(text(
        "CREATE TABLE category_new ("
        "user_id TEXT NOT NULL, key TEXT NOT NULL, label TEXT NOT NULL, "
        "icon TEXT NOT NULL, created_at TEXT NOT NULL, "
        "PRIMARY KEY (user_id, key))"
    ))
    conn.execute(
        text(
            "INSERT INTO category_new (user_id, key, label, icon, created_at) "
            "SELECT :uid, key, label, icon, created_at FROM category"
        ),
        {"uid": bootstrap_user_id},
    )
    conn.execute(text("DROP TABLE category"))
    conn.execute(text("ALTER TABLE category_new RENAME TO category"))


def _migrate_to_multiuser(target_engine: Engine) -> Optional[str]:
    with target_engine.begin() as conn:
        if not _needs_user_migration(conn):
            return None
        bootstrap_user_id = _get_or_create_bootstrap_user(conn)
        _migrate_category_table_if_needed(conn, bootstrap_user_id)
        for table in ("location", "reel", "aisession", "asksession"):
            conn.execute(
                text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL"),
                {"uid": bootstrap_user_id},
            )
        return bootstrap_user_id
```

Add `from typing import Optional` and `from app.models import new_uuid` to the top-of-file imports (`new_uuid` already lives in `app/models.py` from Task 1/3; `app/db.py` currently imports `SQLModel` etc. from `sqlmodel`, not `app.models` — add this new import line).

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_db_migration.py -v`
Expected: PASS

- [ ] **Step 6: Wire the migration into `create_db_and_tables`**

Replace `create_db_and_tables`:

```python
def create_db_and_tables() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    _ensure_columns(engine)
    bootstrap_user_id = _migrate_to_multiuser(engine)
    if bootstrap_user_id is not None:
        from app.seed import seed_user_if_empty  # deferred: avoids a module-load-order issue, app.seed imports app.models only

        with Session(engine) as session:
            seed_user_if_empty(session, bootstrap_user_id)
```

This calls `app.seed.seed_user_if_empty`, which does not exist with this signature until Task 6. Leave this as-is — Task 6 renames `seed_if_empty` to `seed_user_if_empty(session, user_id)`, and nothing exercises this startup path in the test suite (confirmed in Task 4/6: `TestClient` in `tests/conftest.py` is built without a `with` block, so FastAPI's `lifespan` — and therefore `create_db_and_tables` — never actually runs during the test suite; router tests build their own in-memory engine directly). Running `uv run pytest` at the end of this task still passes with the old `seed_if_empty` name in place, since this code path is untested until Task 6's own tests exercise it directly via `create_db_and_tables`.

- [ ] **Step 7: Run the full test suite to confirm nothing else broke**

Run: `uv run pytest -v`
Expected: PASS (the `seed_if_empty` reference inside `create_db_and_tables` is dead code from the test suite's point of view until Task 6, per Step 6's note — it will raise `ImportError` only if something actually calls `create_db_and_tables()` with a freshly-created `user` table and zero existing users, which no current test does).

- [ ] **Step 8: Commit**

```bash
git add app/db.py tests/test_db_migration.py
git commit -m "feat: migrate existing single-tenant data onto a bootstrap user"
```

---

## Task 5: DB-backed login, session carries `user_id`, `get_current_user` dependency

**Files:**
- Modify: `app/auth.py` (replace `verify_credentials`, add `get_current_user`)
- Modify: `app/auth_middleware.py:15` (check `user_id` instead of `authenticated`)
- Modify: `app/routers/auth.py` (login sets `user_id`, needs a `Session`)
- Modify: `tests/test_auth_helpers.py` (remove the old env-var `verify_credentials` tests, add DB-backed ones)
- Modify: `tests/conftest.py` (seed a real `User` row, log in against it)
- Test: `tests/test_auth.py`, `tests/test_auth_helpers.py`

**Interfaces:**
- Consumes: `app.models.User` (Task 1), `app.auth.verify_password` (Task 1), `app.db.get_session`.
- Produces: `app.auth.verify_credentials(session, username, password) -> Optional[User]` (signature change — was `(username, password) -> bool`); `app.auth.get_current_user(request, session) -> User`, a FastAPI dependency every router task from Task 10 onward uses as `current_user: User = Depends(get_current_user)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_auth_helpers.py -- DELETE these five existing tests (env-var based,
# no longer how verify_credentials works): test_verify_credentials_correct,
# test_verify_credentials_wrong_password, test_verify_credentials_wrong_username,
# test_verify_credentials_non_ascii_username_returns_false, and the `monkeypatch.setenv`
# lines that only existed for them. Replace with:

from sqlmodel import SQLModel, Session, create_engine

from app.auth import hash_password, verify_credentials
from app.models import User


def _session_with_user(username: str, password: str) -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(User(username=username, password_hash=hash_password(password)))
    session.commit()
    return session


def test_verify_credentials_correct():
    session = _session_with_user("alice", "s3cret")
    user = verify_credentials(session, "alice", "s3cret")
    assert user is not None
    assert user.username == "alice"


def test_verify_credentials_wrong_password():
    session = _session_with_user("alice", "s3cret")
    assert verify_credentials(session, "alice", "wrong") is None


def test_verify_credentials_wrong_username():
    session = _session_with_user("alice", "s3cret")
    assert verify_credentials(session, "bob", "s3cret") is None


def test_verify_credentials_non_ascii_username_returns_none():
    session = _session_with_user("alice", "s3cret")
    assert verify_credentials(session, "café", "s3cret") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_auth_helpers.py -v`
Expected: FAIL — `verify_credentials` still takes no `session` argument.

- [ ] **Step 3: Rewrite `verify_credentials`, add `get_current_user`**

In `app/auth.py`, replace the existing `verify_credentials` function and add imports:

```python
from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, select

from app.db import get_session
from app.models import User


def verify_credentials(session: Session, username: str, password: str) -> Optional[User]:
    user = session.exec(select(User).where(User.username == username)).first()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    user_id = request.session.get("user_id")
    user = session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
```

Add `from typing import Optional` to the top of `app/auth.py` if not already present (it is not, today).

- [ ] **Step 4: Update `app/auth_middleware.py`**

Replace line 15 (`if request.session.get("authenticated"):`) with:

```python
        if request.session.get("user_id"):
```

- [ ] **Step 5: Update `app/routers/auth.py`**

Replace the whole file's `login_submit` function and imports:

```python
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from app.auth import get_client_ip, rate_limiter, verify_credentials
from app.db import get_session
from app.web import templates

router = APIRouter(tags=["auth"])


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    client_ip = get_client_ip(request)

    if rate_limiter.is_locked_out(client_ip):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Troppi tentativi falliti. Riprova tra qualche minuto."},
            status_code=429,
        )

    user = verify_credentials(session, username, password)
    if user is not None:
        rate_limiter.reset(client_ip)
        request.session["user_id"] = user.id
        return RedirectResponse(url="/", status_code=303)

    rate_limiter.record_failure(client_ip)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Credenziali non valide."},
        status_code=401,
    )


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
```

- [ ] **Step 6: Update `tests/conftest.py` to seed a real `User` and log in against it**

Replace the `session_fixture` and keep everything else:

```python
@pytest.fixture(name="session")
def session_fixture():
    from app.auth import hash_password
    from app.models import User

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(username="testuser", password_hash=hash_password("testpass")))
        session.commit()
        yield session
```

`client_fixture`/`anon_client_fixture`/`_build_client` stay exactly as they are — `client.post("/login", data={"username": "testuser", "password": "testpass"})` now authenticates against this seeded `User` row instead of env vars.

- [ ] **Step 7: Run the auth test suites**

Run: `uv run pytest tests/test_auth.py tests/test_auth_helpers.py -v`
Expected: PASS

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -v`
Expected: Many *other* test files will now fail or error (routers in later tasks don't yet use `current_user`/scoping, but some may already reference `Category`'s new composite key, etc.) — this is expected churn that later tasks fix file-by-file. Confirm specifically that `tests/test_auth.py`, `tests/test_auth_helpers.py`, `tests/test_scoping.py`, `tests/test_models.py`, and `tests/test_db_migration.py` are green before moving on; do not try to fix every other failure in this task.

- [ ] **Step 9: Commit**

```bash
git add app/auth.py app/auth_middleware.py app/routers/auth.py tests/test_auth_helpers.py tests/conftest.py
git commit -m "feat: back login with the User table, store user_id in session"
```

---

## Task 6: Per-user seeding

**Files:**
- Modify: `app/seed.py` (rename `seed_if_empty` → `seed_user_if_empty(session, user_id)`)
- Modify: `app/main.py` (remove the global seed call from `lifespan` — seeding now happens inside `create_db_and_tables`, Task 4, or via `create_user.py`, Task 7)
- Modify: `tests/test_seed.py` (pass `user_id`, assert scoping)
- Modify: `tests/test_db_migration.py` (add the fresh-install integration test, Step 6 below)
- Test: `tests/test_seed.py`, `tests/test_db_migration.py`

**Interfaces:**
- Produces: `app.seed.seed_user_if_empty(session: Session, user_id: str) -> None` (replaces `seed_if_empty(session) -> None`). Consumed by `app.db._migrate_to_multiuser`'s caller in `create_db_and_tables` (Task 4) and by `scripts/create_user.py` (Task 7).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_seed.py -- full replacement
from sqlmodel import SQLModel, Session, create_engine, select

from app.models import Category, Location
from app.seed import seed_user_if_empty


def test_seed_user_if_empty_creates_hubs_and_satellites():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_user_if_empty(session, "user-1")

        hubs = session.exec(
            select(Location).where(Location.is_hub == True, Location.user_id == "user-1")
        ).all()
        satellites = session.exec(
            select(Location).where(Location.is_hub == False, Location.user_id == "user-1")
        ).all()

        assert len(hubs) == 10
        assert len(satellites) == 10
        tokyo = next(h for h in hubs if h.name == "Tokyo / Kanto")
        nikko = next(s for s in satellites if s.name == "Nikko")
        assert nikko.parent_id == tokyo.id


def test_seed_user_if_empty_is_idempotent_per_user():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_user_if_empty(session, "user-1")
        seed_user_if_empty(session, "user-1")
        locations = session.exec(select(Location).where(Location.user_id == "user-1")).all()
        assert len(locations) == 20


def test_seed_user_if_empty_creates_default_categories_scoped_to_user():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_user_if_empty(session, "user-1")

        categories = session.exec(select(Category).where(Category.user_id == "user-1")).all()
        assert {c.key for c in categories} == {
            "food", "culture", "nature", "shopping", "stay", "transport", "experience",
        }
        food = next(c for c in categories if c.key == "food")
        assert food.label == "Cibo"
        assert food.icon == "🍜"


def test_seed_user_if_empty_does_not_touch_another_users_data():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_user_if_empty(session, "user-1")
        seed_user_if_empty(session, "user-2")

        user_1_locations = session.exec(select(Location).where(Location.user_id == "user-1")).all()
        user_2_locations = session.exec(select(Location).where(Location.user_id == "user-2")).all()
        assert len(user_1_locations) == 20
        assert len(user_2_locations) == 20
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_seed.py -v`
Expected: FAIL with `ImportError: cannot import name 'seed_user_if_empty'`

- [ ] **Step 3: Rewrite `app/seed.py`**

Replace `seed_if_empty`:

```python
def seed_user_if_empty(session: Session, user_id: str) -> None:
    if session.exec(select(Location).where(Location.user_id == user_id)).first() is None:
        hub_by_name: dict[str, Location] = {}
        for name, lat, lon in HUBS:
            hub = Location(name=name, is_hub=True, lat=lat, lon=lon, user_id=user_id)
            session.add(hub)
            session.flush()
            hub_by_name[name] = hub

        for name, hub_name, lat, lon in SATELLITES:
            parent = hub_by_name[hub_name]
            session.add(
                Location(name=name, is_hub=False, parent_id=parent.id, lat=lat, lon=lon, user_id=user_id)
            )

        session.commit()

    if session.exec(select(Category).where(Category.user_id == user_id)).first() is None:
        for key, label, icon in DEFAULT_CATEGORIES:
            session.add(Category(user_id=user_id, key=key, label=label, icon=icon))
        session.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_seed.py -v`
Expected: PASS

- [ ] **Step 5: Remove the now-dead global seed call from `app/main.py`**

In `app/main.py`, remove the `from app.seed import seed_if_empty` import line and replace the `lifespan` function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield
```

(`create_db_and_tables()` already seeds the bootstrap user as of Task 4, Step 6.)

- [ ] **Step 6: Add the fresh-install integration test**

This is the one scenario no earlier test exercises end-to-end: a brand-new, completely empty DB file, run through the real `create_db_and_tables()` entrypoint (not a hand-built in-memory engine), confirming it ends up with exactly one bootstrap user plus that user's seeded default hubs/categories — the exact state a reinstall of the app on a fresh VPS would produce.

```python
# tests/test_db_migration.py -- add
def test_create_db_and_tables_seeds_bootstrap_user_on_a_fresh_install(tmp_path, monkeypatch):
    from sqlmodel import Session, create_engine, select

    from app import db
    from app.models import Category, Location, User

    monkeypatch.setenv("AUTH_USERNAME", "owner")
    monkeypatch.setenv("AUTH_PASSWORD", "ownerpass")
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(db, "DB_PATH", str(db_path))
    monkeypatch.setattr(db, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(
        db, "engine", create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    )

    db.create_db_and_tables()

    with Session(db.engine) as session:
        users = session.exec(select(User)).all()
        assert [u.username for u in users] == ["owner"]
        locations = session.exec(select(Location).where(Location.user_id == users[0].id)).all()
        categories = session.exec(select(Category).where(Category.user_id == users[0].id)).all()
        assert len(locations) == 20
        assert len(categories) == 7

    # Idempotent: running it again on the same file must not create a second user.
    db.create_db_and_tables()
    with Session(db.engine) as session:
        assert len(session.exec(select(User)).all()) == 1
```

Run: `uv run pytest tests/test_db_migration.py::test_create_db_and_tables_seeds_bootstrap_user_on_a_fresh_install -v`
Expected: PASS

- [ ] **Step 7: Run the full test suite**

Run: `uv run pytest -v`
Expected: Same expected-failures as Task 5 Step 8 (routers not yet converted); `tests/test_seed.py`, `tests/test_db_migration.py`, and anything touched so far stays green.

- [ ] **Step 8: Commit**

```bash
git add app/seed.py app/main.py tests/test_seed.py tests/test_db_migration.py
git commit -m "feat: seed default hubs/categories per-user instead of once globally"
```

---

## Task 7: `scripts/create_user.py` — admin CLI for new accounts

**Files:**
- Create: `scripts/create_user.py`
- Create: `scripts/__init__.py` (empty, makes `scripts` importable as a package for `python -m`)
- Test: `tests/test_create_user_script.py`

**Interfaces:**
- Consumes: `app.auth.hash_password` (Task 1), `app.seed.seed_user_if_empty` (Task 6), `app.db.engine`/`get_session`.
- Produces: `scripts.create_user.create_user(session, username, password) -> User`, used directly by the test and wrapped by a `main()` that handles argv/getpass — later tasks don't depend on this module.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_create_user_script.py
import pytest
from sqlmodel import SQLModel, Session, create_engine, select

from app.auth import verify_password
from app.models import Category, Location, User
from scripts.create_user import UsernameTakenError, create_user


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_user_persists_hashed_password(session):
    user = create_user(session, "alice", "s3cret")

    stored = session.get(User, user.id)
    assert stored.username == "alice"
    assert verify_password("s3cret", stored.password_hash) is True


def test_create_user_seeds_default_hubs_and_categories(session):
    user = create_user(session, "alice", "s3cret")

    locations = session.exec(select(Location).where(Location.user_id == user.id)).all()
    categories = session.exec(select(Category).where(Category.user_id == user.id)).all()
    assert len(locations) == 20
    assert len(categories) == 7


def test_create_user_rejects_duplicate_username(session):
    create_user(session, "alice", "s3cret")

    with pytest.raises(UsernameTakenError):
        create_user(session, "alice", "different-password")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_create_user_script.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts'`

- [ ] **Step 3: Implement `scripts/create_user.py`**

```python
import getpass
import sys

from sqlmodel import Session, select

from app.auth import hash_password
from app.db import engine
from app.models import User
from app.seed import seed_user_if_empty


class UsernameTakenError(Exception):
    pass


def create_user(session: Session, username: str, password: str) -> User:
    existing = session.exec(select(User).where(User.username == username)).first()
    if existing is not None:
        raise UsernameTakenError(f"username '{username}' already exists")

    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)

    seed_user_if_empty(session, user.id)
    return user


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.create_user <username>", file=sys.stderr)
        sys.exit(1)

    username = sys.argv[1]
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        sys.exit(1)

    with Session(engine) as session:
        try:
            user = create_user(session, username, password)
        except UsernameTakenError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

    print(f"Created user '{user.username}' ({user.id}).")


if __name__ == "__main__":
    main()
```

Create `scripts/__init__.py` as an empty file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_create_user_script.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/create_user.py scripts/__init__.py tests/test_create_user_script.py
git commit -m "feat: add admin CLI script to create new user accounts"
```

---

## Task 8: Scope `resolve_place` (AI location matching) to the current user

**Files:**
- Modify: `app/location_matching.py` (`_resolve_hub`, `_hub_options`, `_auto_place_resolution`, `resolve_place`)
- Modify: `tests/test_location_matching.py` (thread `user_id` through every call)
- Test: `tests/test_location_matching.py`

**Interfaces:**
- Produces: `resolve_place(session, place_name, near_hub, lat, lon, user_id, exclude_location_id=None) -> PlaceResolution` (added required positional `user_id` before the existing keyword-only `exclude_location_id`). Consumed by Task 13 (`audit.py`) and Task 14 (`ai_categorize.py`/`ai_multi_categorize.py`).

Without this, a reel imported by one user could get auto-matched or merged onto a location that belongs to a completely different user — `resolve_place` queries `select(Location)` with no filter today.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_location_matching.py -- add near the other resolve_place tests
def test_resolve_place_does_not_match_another_users_location(session):
    _add(session, name="Nishiki Market", is_hub=False, lat=35.005, lon=135.765, user_id="user-2")

    resolution = resolve_place(session, "nishiki market", None, None, None, user_id="user-1")

    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_location_matching.py::test_resolve_place_does_not_match_another_users_location -v`
Expected: FAIL with `TypeError: resolve_place() missing 1 required positional argument: 'user_id'`

- [ ] **Step 3: Thread `user_id` through `app/location_matching.py`**

```python
def _resolve_hub(session: Session, near_hub: Optional[str], user_id: str) -> tuple:
    normalized_near_hub = normalize_place_name(near_hub or "")
    hubs = session.exec(
        select(Location).where(Location.is_hub == True, Location.user_id == user_id)
    ).all()
    if normalized_near_hub:
        for hub in hubs:
            if normalize_place_name(hub.name) == normalized_near_hub:
                return "auto", hub.id, hub.name
    return "ambiguous", None, None


def _hub_options(session: Session, user_id: str) -> list[HubOption]:
    hubs = session.exec(
        select(Location).where(Location.is_hub == True, Location.user_id == user_id)
    ).all()
    return [HubOption(id=h.id, name=h.name) for h in hubs]


def _auto_place_resolution(
    session: Session, loc: Location, near_hub: Optional[str], user_id: str
) -> PlaceResolution:
    hub_tier, hub_id, hub_name = _resolve_hub(session, near_hub, user_id)
    return PlaceResolution(
        place_tier="auto",
        place_location_id=loc.id,
        place_location_name=loc.name,
        hub_tier=hub_tier,
        hub_id=hub_id,
        hub_name=hub_name,
        requires_confirmation=False,
    )


def resolve_place(
    session: Session,
    place_name: str,
    near_hub: Optional[str],
    lat: Optional[float],
    lon: Optional[float],
    user_id: str,
    exclude_location_id: Optional[str] = None,
) -> PlaceResolution:
    normalized_place = normalize_place_name(place_name)
    locations = session.exec(select(Location).where(Location.user_id == user_id)).all()
    if exclude_location_id:
        locations = [loc for loc in locations if loc.id != exclude_location_id]

    if normalized_place:
        for loc in locations:
            normalized_loc = normalize_place_name(loc.name)
            if normalized_place == normalized_loc:
                return _auto_place_resolution(session, loc, near_hub, user_id)
            if loc.is_hub and normalized_place in normalized_loc:
                return _auto_place_resolution(session, loc, near_hub, user_id)

        if lat is not None and lon is not None:
            for loc in locations:
                if loc.lat is None or loc.lon is None:
                    continue
                distance = haversine_distance_m(float(lat), float(lon), loc.lat, loc.lon)
                ratio = SequenceMatcher(None, normalized_place, normalize_place_name(loc.name)).ratio()
                if distance <= AUTO_MATCH_DISTANCE_METERS and ratio >= NAME_SIMILARITY_THRESHOLD:
                    return _auto_place_resolution(session, loc, near_hub, user_id)

    candidates: list[PlaceCandidate] = []
    if lat is not None and lon is not None:
        scored = []
        for loc in locations:
            if loc.lat is None or loc.lon is None:
                continue
            distance = haversine_distance_m(float(lat), float(lon), loc.lat, loc.lon)
            if distance <= CANDIDATE_SEARCH_RADIUS_METERS:
                scored.append((distance, loc))
        scored.sort(key=lambda pair: pair[0])
        candidates = [
            PlaceCandidate(id=loc.id, name=loc.name, distance_m=round(distance, 1))
            for distance, loc in scored[:MAX_CANDIDATES]
        ]

    hub_tier, hub_id, hub_name = _resolve_hub(session, near_hub, user_id)

    return PlaceResolution(
        place_tier="ambiguous",
        place_location_id=None,
        place_location_name=None,
        place_candidates=candidates,
        hub_tier=hub_tier,
        hub_id=hub_id,
        hub_name=hub_name,
        hub_options=_hub_options(session, user_id),
        requires_confirmation=bool(candidates) or hub_tier == "ambiguous",
    )
```

- [ ] **Step 4: Fix the rest of `tests/test_location_matching.py`**

The helper at line 64 (`_add(session, **kwargs)`) stays as-is — it just forwards `**kwargs`, so tests now pass `user_id=...` through it. Every existing call to `resolve_place(session, ...)` in this file needs `user_id="user-1"` added as the 5th positional/keyword argument (before `exclude_location_id` where present), and every `_add(session, ...)` call that backs a test needing to be matched needs `user_id="user-1"` added to its kwargs so it belongs to the same user the test resolves against. Grep the file for the exact call sites:

Run: `grep -n "resolve_place(session\|_add(session" tests/test_location_matching.py`

For every `resolve_place(session, <args>)` call, change to `resolve_place(session, <args>, user_id="user-1")` (or insert `"user-1"` as the positional 5th arg if the call doesn't use keywords — match the existing style at each site). For every `_add(session, name=..., ...)` call, add `user_id="user-1"` to the kwargs. Tests that deliberately check "a differently-scoped location is NOT found" (if any already exist) should use a different `user_id` for that location instead of `"user-1"` — the new test from Step 1 is the only one doing that here; all pre-existing tests in this file use a single consistent user throughout, so `"user-1"` everywhere is correct for them.

- [ ] **Step 5: Run the full file**

Run: `uv run pytest tests/test_location_matching.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/location_matching.py tests/test_location_matching.py
git commit -m "feat: scope AI location matching to the current user"
```

---

## Task 9: Scope `find_duplicate_reel` to the current user

**Files:**
- Modify: `app/reel_links.py:25-30`
- Modify: `tests/test_reel_links.py`
- Test: `tests/test_reel_links.py`

**Interfaces:**
- Produces: `find_duplicate_reel(session, link, user_id) -> Optional[Reel]` (added required `user_id`). Consumed by Task 12 (`reels.py`), Task 14 (`ai_categorize.py`/`ai_multi_categorize.py`), Task 17 (`instagram_import.py`).

Without this, pasting a link another user already saved would surface *that other user's* note and location name in the "already seen" warning — a direct data leak, not just a UX glitch.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reel_links.py -- add
def test_find_duplicate_reel_ignores_another_users_reel(session):
    hub = Location(name="Hub", is_hub=True, user_id="user-2")
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/ABC123/", location_id=hub.id, user_id="user-2"))
    session.commit()

    result = find_duplicate_reel(session, "https://instagram.com/reel/ABC123/", user_id="user-1")

    assert result is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_reel_links.py::test_find_duplicate_reel_ignores_another_users_reel -v`
Expected: FAIL with `TypeError: find_duplicate_reel() missing 1 required positional argument: 'user_id'`

- [ ] **Step 3: Update `find_duplicate_reel`**

```python
def find_duplicate_reel(session: Session, link: str, user_id: str) -> Optional[Reel]:
    key = reel_link_key(link)
    for reel in session.exec(select(Reel).where(Reel.user_id == user_id)).all():
        if reel_link_key(reel.link) == key:
            return reel
    return None
```

- [ ] **Step 4: Fix the existing tests in `tests/test_reel_links.py`**

The two pre-existing `test_find_duplicate_reel_*` tests each construct a `Location`/`Reel` and call `find_duplicate_reel(session, link)`. Add `user_id="user-1"` to both the `Location(...)` and `Reel(...)` constructors, and add `user_id="user-1"` as the third argument to both `find_duplicate_reel(session, ...)` calls.

- [ ] **Step 5: Run the full file**

Run: `uv run pytest tests/test_reel_links.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/reel_links.py tests/test_reel_links.py
git commit -m "feat: scope duplicate-reel detection to the current user"
```

---

## Task 10: Scope `app/routers/categories.py` — `get_taxonomy`, CRUD, and the `ReelType` cross-user delete bug

**Files:**
- Modify: `app/routers/categories.py` (whole file)
- Modify: `tests/test_categories_api.py`, `tests/test_categories_ui.py`
- Test: `tests/test_categories_api.py`, `tests/test_categories_ui.py`

**Interfaces:**
- Consumes: `app.auth.get_current_user` (Task 5), `app.scoping.user_query`/`get_owned_category` (Task 2).
- Produces: `get_taxonomy(session, user_id) -> dict`, `get_valid_type_keys(session, user_id) -> set[str]` (both gain a required `user_id` — every caller in Tasks 11-17 passes `current_user.id`). `reel_ids_matching_types` is **unchanged** — it matches `ReelType.type` strings against an already user-scoped `reels` list supplied by the caller, so it never needs its own `user_id` (the caller's existing scoping makes any cross-user `ReelType` rows it might touch irrelevant, since they get intersected away).

This task also fixes a real bug introduced by `Category`'s new composite key: `_delete_category` deletes every `ReelType` row with `type == key` — once two users can both have a category keyed `"food"`, deleting user A's `"food"` category would delete `ReelType` rows tagging user B's reels too.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_categories_api.py -- add
def test_list_categories_only_returns_current_users_categories(client, session):
    from app.models import Category

    session.add(Category(user_id="other-user", key="other", label="Other", icon="❓"))
    session.commit()

    response = client.get("/api/categories")

    assert response.status_code == 200
    assert "other" not in {c["key"] for c in response.json()}


def test_delete_category_does_not_delete_another_users_reeltype_with_same_key(client, session):
    from app.models import Category, Location, Reel, ReelType

    client.post("/api/categories", json={"label": "Cibo", "icon": "🍜"})

    other_hub = Location(name="Other Hub", is_hub=True, user_id="other-user")
    session.add(other_hub)
    session.commit()
    session.refresh(other_hub)
    other_reel = Reel(link="https://instagram.com/reel/x", location_id=other_hub.id, user_id="other-user")
    session.add(other_reel)
    session.commit()
    session.refresh(other_reel)
    session.add(Category(user_id="other-user", key="cibo", label="Food", icon="🍔"))
    session.add(ReelType(reel_id=other_reel.id, type="cibo"))
    session.commit()

    response = client.delete("/api/categories/cibo")
    assert response.status_code == 204

    remaining = session.exec(select(ReelType).where(ReelType.reel_id == other_reel.id)).all()
    assert len(remaining) == 1
```

(Add `from sqlmodel import select` to the top of `tests/test_categories_api.py` if not already imported.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_categories_api.py -v`
Expected: FAIL — `test_list_categories_only_returns_current_users_categories` fails because the route isn't scoped yet; the delete test currently passes "by luck" (single global key today) but will start from a broken baseline once the model change lands, so treat both as the task's target.

- [ ] **Step 3: Rewrite `app/routers/categories.py`**

```python
import re
import unicodedata

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import get_current_user
from app.db import get_session
from app.models import Category, Reel, ReelType, User
from app.scoping import get_owned_category, user_query
from app.web import templates

router = APIRouter(prefix="/api/categories", tags=["categories"])
ui_router = APIRouter(prefix="/ui/categories", tags=["categories-ui"])


def slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def get_taxonomy(session: Session, user_id: str) -> dict[str, dict]:
    categories = session.exec(user_query(Category, user_id).order_by(Category.created_at)).all()
    return {c.key: {"label": c.label, "icon": c.icon} for c in categories}


def get_valid_type_keys(session: Session, user_id: str) -> set[str]:
    return {c.key for c in session.exec(user_query(Category, user_id)).all()}


def reel_ids_matching_types(session: Session, types: list[str]) -> set[str] | None:
    """None means "no filter". Otherwise the set of reel ids tagged with
    every type in `types` (AND across types). Callers must already have
    scoped the reel list they intersect this against -- this function
    itself does not filter by user."""
    if not types:
        return None
    result: set[str] | None = None
    for type_value in types:
        ids = set(session.exec(select(ReelType.reel_id).where(ReelType.type == type_value)).all())
        result = ids if result is None else result & ids
    return result


class CategoryPayload(BaseModel):
    label: str
    icon: str


def _create_category(session: Session, user_id: str, label: str, icon: str) -> Category:
    key = slugify(label)
    if not key:
        raise HTTPException(status_code=400, detail="label must contain at least one letter or digit")
    if get_owned_category(session, key, user_id):
        raise HTTPException(status_code=409, detail=f"a category with key '{key}' already exists")
    category = Category(user_id=user_id, key=key, label=label, icon=icon)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _update_category(session: Session, user_id: str, key: str, label: str, icon: str) -> Category:
    category = get_owned_category(session, key, user_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    category.label = label
    category.icon = icon
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _delete_category(session: Session, user_id: str, key: str) -> None:
    category = get_owned_category(session, key, user_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")

    owned_reel_ids = set(session.exec(user_query(Reel, user_id).with_only_columns(Reel.id)).all())
    for rt in session.exec(select(ReelType).where(ReelType.type == key)).all():
        if rt.reel_id in owned_reel_ids:
            session.delete(rt)
    session.delete(category)
    session.commit()


@router.get("")
def list_categories(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    return session.exec(user_query(Category, current_user.id).order_by(Category.created_at)).all()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return _create_category(session, current_user.id, payload.label, payload.icon)


@router.put("/{key}")
def update_category(
    key: str,
    payload: CategoryPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return _update_category(session, current_user.id, key, payload.label, payload.icon)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    key: str, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    _delete_category(session, current_user.id, key)


def _category_list_context(session: Session, user_id: str) -> dict:
    return {"categories": session.exec(user_query(Category, user_id).order_by(Category.created_at)).all()}


@ui_router.get("")
def ui_list_categories(
    request: Request, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    return templates.TemplateResponse(
        request, "partials/category_list.html", _category_list_context(session, current_user.id)
    )


@ui_router.post("")
def ui_create_category(
    request: Request,
    label: str = Form(...),
    icon: str = Form(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _create_category(session, current_user.id, label, icon)
    return templates.TemplateResponse(
        request, "partials/category_list.html", _category_list_context(session, current_user.id)
    )


@ui_router.get("/{key}/edit")
def ui_edit_category_form(
    request: Request,
    key: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    category = get_owned_category(session, key, current_user.id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return templates.TemplateResponse(request, "partials/category_edit_row.html", {"category": category})


@ui_router.post("/{key}")
def ui_update_category(
    request: Request,
    key: str,
    label: str = Form(...),
    icon: str = Form(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _update_category(session, current_user.id, key, label, icon)
    return templates.TemplateResponse(
        request, "partials/category_list.html", _category_list_context(session, current_user.id)
    )


@ui_router.delete("/{key}")
def ui_delete_category(
    request: Request,
    key: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _delete_category(session, current_user.id, key)
    return templates.TemplateResponse(
        request, "partials/category_list.html", _category_list_context(session, current_user.id)
    )
```

- [ ] **Step 4: Fix the remaining fixtures in `tests/test_categories_api.py` and `tests/test_categories_ui.py`**

Every `Category(key=..., label=..., icon=...)` constructor call in both files needs `user_id=` added. Since both files use the shared `client`/`session` fixtures (Task 5), and `client` is already logged in as the seeded `testuser`, add `user_id=session.exec(select(User).where(User.username == "testuser")).first().id` is unnecessarily roundabout — instead add a `test_user_id` fixture to `tests/conftest.py` now (pulled forward from Task 19) that both files can take as a parameter:

```python
# tests/conftest.py -- add alongside the other fixtures
@pytest.fixture(name="test_user_id")
def test_user_id_fixture(session: Session) -> str:
    from app.models import User

    return session.exec(select(User).where(User.username == "testuser")).first().id
```

(Add `from sqlmodel import select` to `conftest.py`'s imports if not already present from Step 6 of Task 5 — it already imports `SQLModel, Session, create_engine`, add `select` to that line.)

Then in `tests/test_categories_api.py` and `tests/test_categories_ui.py`: add `test_user_id` as a parameter to every test function that currently has a bare `Category(key=..., label=..., icon=...)` call, and add `user_id=test_user_id` to each of those constructor calls. Example transformation:

```python
# before
def test_list_categories_returns_seeded_categories(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜"))
    session.commit()

# after
def test_list_categories_returns_seeded_categories(client, session, test_user_id):
    session.add(Category(key="food", label="Cibo", icon="🍜", user_id=test_user_id))
    session.commit()
```

Apply this to every `Category(` and `Location(`/`Reel(` construction in both files (the full line lists were gathered by grepping `tests/test_categories_api.py` and `tests/test_categories_ui.py` for `Location(\|Reel(\|Category(` — every matched line gets `user_id=test_user_id` added and `test_user_id` added to its enclosing test function's parameters).

- [ ] **Step 5: Run the category test files**

Run: `uv run pytest tests/test_categories_api.py tests/test_categories_ui.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/routers/categories.py tests/test_categories_api.py tests/test_categories_ui.py tests/conftest.py
git commit -m "feat: scope category CRUD and taxonomy lookups to the current user"
```

---

## Task 11: Scope `app/routers/locations.py`

**Files:**
- Modify: `app/routers/locations.py` (whole file)
- Modify: `tests/test_locations_api.py`, `tests/test_locations_ui.py`
- Test: `tests/test_locations_api.py`, `tests/test_locations_ui.py`

**Interfaces:**
- Consumes: `app.auth.get_current_user`, `app.scoping.{user_query,get_owned}`.
- Produces: `_create_location(session, user_id, name, is_hub, parent_id, lat, lon) -> Location` and `_update_location(...)` gain a `user_id` parameter inserted right after `session` — Task 12/14 import `_create_location` from this module and must be updated to pass it too (cross-referenced there).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_locations_api.py -- add
def test_list_locations_only_returns_current_users_locations(client, session):
    from app.models import Location

    session.add(Location(name="Someone Else's Hub", is_hub=True, user_id="other-user"))
    session.commit()

    response = client.get("/api/locations")

    assert response.status_code == 200
    assert "Someone Else's Hub" not in {loc["name"] for loc in response.json()}


def test_create_location_with_another_users_parent_id_returns_404(client, session):
    from app.models import Location

    other_hub = Location(name="Other Hub", is_hub=True, user_id="other-user")
    session.add(other_hub)
    session.commit()
    session.refresh(other_hub)

    response = client.post(
        "/api/locations",
        json={"name": "Satellite", "is_hub": False, "parent_id": other_hub.id, "lat": 1.0, "lon": 2.0},
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_locations_api.py -v`
Expected: FAIL — routes aren't scoped yet, and `parent_id` isn't ownership-checked yet.

- [ ] **Step 3: Rewrite `app/routers/locations.py`**

```python
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.auth import get_current_user
from app.db import get_session
from app.models import Location, Reel, User
from app.scoping import get_owned, user_query
from app.web import templates

router = APIRouter(prefix="/api/locations", tags=["locations"])
ui_router = APIRouter(prefix="/ui/locations", tags=["locations-ui"])


class LocationPayload(BaseModel):
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = None
    lat: float
    lon: float


def _has_children(session: Session, location_id: str, user_id: str) -> bool:
    return (
        session.exec(
            user_query(Location, user_id).where(Location.parent_id == location_id)
        ).first()
        is not None
    )


def _has_reels(session: Session, location_id: str, user_id: str) -> bool:
    return (
        session.exec(user_query(Reel, user_id).where(Reel.location_id == location_id)).first()
        is not None
    )


def _reel_counts(session: Session, user_id: str) -> dict:
    return dict(
        session.exec(
            user_query(Reel, user_id)
            .with_only_columns(Reel.location_id, func.count(Reel.id))
            .group_by(Reel.location_id)
        ).all()
    )


def _serialize_location(location: Location, reel_count: int) -> dict:
    return {
        "id": location.id,
        "name": location.name,
        "is_hub": location.is_hub,
        "parent_id": location.parent_id,
        "lat": location.lat,
        "lon": location.lon,
        "reel_count": reel_count,
    }


def _create_location(
    session: Session,
    user_id: str,
    name: str,
    is_hub: bool,
    parent_id: Optional[str],
    lat: float,
    lon: float,
) -> Location:
    if not is_hub and not parent_id:
        raise HTTPException(status_code=400, detail="A satellite location requires a parent_id")
    if parent_id and get_owned(session, Location, parent_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Location not found")
    location = Location(
        name=name, is_hub=is_hub, parent_id=None if is_hub else parent_id, lat=lat, lon=lon, user_id=user_id
    )
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


def _update_location(
    session: Session,
    user_id: str,
    location_id: str,
    name: str,
    is_hub: bool,
    parent_id: Optional[str],
    lat: float,
    lon: float,
) -> Location:
    location = get_owned(session, Location, location_id, user_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if not is_hub and not parent_id:
        raise HTTPException(status_code=400, detail="A satellite location requires a parent_id")
    if parent_id and get_owned(session, Location, parent_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if not is_hub and _has_children(session, location_id, user_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot turn a location with child locations into a satellite; reassign or delete them first",
        )
    location.name = name
    location.is_hub = is_hub
    location.parent_id = None if is_hub else parent_id
    location.lat = lat
    location.lon = lon
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


def _delete_location(session: Session, user_id: str, location_id: str) -> None:
    location = get_owned(session, Location, location_id, user_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if _has_children(session, location_id, user_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a location that still has child locations; reassign or delete them first",
        )
    if _has_reels(session, location_id, user_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a location that still has reels attached; move or delete them first",
        )
    session.delete(location)
    session.commit()


def _merge_locations(session: Session, user_id: str, keep_id: str, drop_id: str) -> None:
    keep = get_owned(session, Location, keep_id, user_id)
    drop = get_owned(session, Location, drop_id, user_id)
    if keep is None or drop is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if _has_children(session, drop_id, user_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot merge a location that still has child locations; reassign or delete them first",
        )
    for reel in session.exec(user_query(Reel, user_id).where(Reel.location_id == drop_id)).all():
        reel.location_id = keep_id
        session.add(reel)
    session.commit()
    session.delete(drop)
    session.commit()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_location(
    payload: LocationPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    location = _create_location(
        session, current_user.id, payload.name, payload.is_hub, payload.parent_id, payload.lat, payload.lon
    )
    return _serialize_location(location, 0)


@router.get("")
def list_locations(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    locations = session.exec(user_query(Location, current_user.id)).all()
    counts = _reel_counts(session, current_user.id)
    return [_serialize_location(loc, counts.get(loc.id, 0)) for loc in locations]


@router.put("/{location_id}")
def update_location(
    location_id: str,
    payload: LocationPayload,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    location = _update_location(
        session,
        current_user.id,
        location_id,
        payload.name,
        payload.is_hub,
        payload.parent_id,
        payload.lat,
        payload.lon,
    )
    counts = _reel_counts(session, current_user.id)
    return _serialize_location(location, counts.get(location.id, 0))


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(
    location_id: str, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    _delete_location(session, current_user.id, location_id)


@router.post("/{keep_id}/merge/{drop_id}", status_code=status.HTTP_204_NO_CONTENT)
def merge_locations(
    keep_id: str,
    drop_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _merge_locations(session, current_user.id, keep_id, drop_id)


def _location_list_context(session: Session, user_id: str, error: Optional[str] = None) -> dict:
    locations = session.exec(user_query(Location, user_id)).all()
    counts = _reel_counts(session, user_id)
    hubs = sorted((loc for loc in locations if loc.is_hub), key=lambda loc: loc.name)
    hubs_by_id = {loc.id: loc for loc in hubs}

    satellites_by_parent: dict = {}
    for loc in locations:
        if not loc.is_hub:
            satellites_by_parent.setdefault(loc.parent_id, []).append(loc)
    for satellites in satellites_by_parent.values():
        satellites.sort(key=lambda loc: loc.name)

    def _entry(loc: Location) -> dict:
        return {
            "id": loc.id,
            "name": loc.name,
            "is_hub": loc.is_hub,
            "parent_name": hubs_by_id[loc.parent_id].name
            if loc.parent_id in hubs_by_id
            else None,
            "lat": loc.lat,
            "lon": loc.lon,
            "reel_count": counts.get(loc.id, 0),
        }

    entries = []
    placed_ids = set()
    for hub in hubs:
        entries.append(_entry(hub))
        placed_ids.add(hub.id)
        for satellite in satellites_by_parent.get(hub.id, []):
            entries.append(_entry(satellite))
            placed_ids.add(satellite.id)

    for loc in locations:
        if loc.id not in placed_ids:
            entries.append(_entry(loc))

    return {
        "locations": entries,
        "hubs": hubs,
        "error": error,
    }


@ui_router.get("")
def ui_list_locations(
    request: Request, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session, current_user.id)
    )


@ui_router.post("")
def ui_create_location(
    request: Request,
    name: str = Form(...),
    is_hub: str = Form(...),
    parent_id: str = Form(""),
    lat: float = Form(...),
    lon: float = Form(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        _create_location(session, current_user.id, name, is_hub == "true", parent_id or None, lat, lon)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        return templates.TemplateResponse(
            request,
            "partials/location_list.html",
            _location_list_context(session, current_user.id, error="Un satellite richiede una città padre."),
        )
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session, current_user.id)
    )


@ui_router.get("/{location_id}/edit")
def ui_edit_location_form(
    request: Request,
    location_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    location = get_owned(session, Location, location_id, current_user.id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    hubs = session.exec(
        user_query(Location, current_user.id).where(Location.is_hub == True, Location.id != location_id)
    ).all()
    return templates.TemplateResponse(
        request, "partials/location_edit_row.html", {"location": location, "hubs": hubs}
    )


@ui_router.post("/{location_id}")
def ui_update_location(
    request: Request,
    location_id: str,
    name: str = Form(...),
    is_hub: str = Form(...),
    parent_id: str = Form(""),
    lat: float = Form(...),
    lon: float = Form(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        _update_location(
            session, current_user.id, location_id, name, is_hub == "true", parent_id or None, lat, lon
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        error = (
            "Un satellite richiede una città padre."
            if exc.status_code == 400
            else "Questa città ha città satellite collegate: riassegnale o eliminale prima."
        )
        return templates.TemplateResponse(
            request,
            "partials/location_list.html",
            _location_list_context(session, current_user.id, error=error),
        )
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session, current_user.id)
    )


@ui_router.delete("/{location_id}")
def ui_delete_location(
    request: Request,
    location_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        _delete_location(session, current_user.id, location_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        if _has_children(session, location_id, current_user.id):
            error = "Questa città ha città satellite collegate: riassegnale o eliminale prima."
        else:
            error = "Questa città ha reel collegati: spostali o eliminali prima dalla lista reel."
        return templates.TemplateResponse(
            request,
            "partials/location_list.html",
            _location_list_context(session, current_user.id, error=error),
        )
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session, current_user.id)
    )
```

- [ ] **Step 4: Fix the remaining fixtures in `tests/test_locations_api.py` and `tests/test_locations_ui.py`**

Add `test_user_id` as a parameter to every test with a direct `Location(`/`Reel(` construction, and add `user_id=test_user_id` to each constructor call. Example transformation:

```python
# before
def test_delete_location_blocked_when_it_has_reels(client, session):
    hub = Location(name="Hub A", is_hub=True)
    session.add(hub)
    session.commit()

# after
def test_delete_location_blocked_when_it_has_reels(client, session, test_user_id):
    hub = Location(name="Hub A", is_hub=True, user_id=test_user_id)
    session.add(hub)
    session.commit()
```

Run `grep -n "Location(\|Reel(" tests/test_locations_api.py tests/test_locations_ui.py` to get the exact line list for these two files and apply the transformation to each.

- [ ] **Step 5: Run the location test files**

Run: `uv run pytest tests/test_locations_api.py tests/test_locations_ui.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/routers/locations.py tests/test_locations_api.py tests/test_locations_ui.py
git commit -m "feat: scope location CRUD/merge to the current user, validate parent_id ownership"
```

---

## Task 12: Scope `app/routers/map.py` and `app/routers/export.py`

**Files:**
- Modify: `app/routers/map.py` (whole file)
- Modify: `app/routers/export.py` (whole file)
- Modify: `tests/test_map_api.py`, `tests/test_export_api.py`
- Test: `tests/test_map_api.py`, `tests/test_export_api.py`

**Interfaces:**
- Produces: `compute_map(session, user_id) -> list[dict]`, `render_map_html(session, user_id, type_values=None) -> str` (consumed by Task 13's `reels.py`, and by Task 15's `ai_categorize.py`/`ai_multi_categorize.py`), `build_export_markdown(session, user_id, hub_id=None) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_map_api.py -- add
def test_get_map_only_returns_current_users_locations(client, session):
    from app.models import Location

    session.add(Location(name="Other Hub", is_hub=True, lat=1.0, lon=2.0, user_id="other-user"))
    session.commit()

    response = client.get("/api/map")

    assert response.status_code == 200
    assert "Other Hub" not in {loc["name"] for loc in response.json()}
```

```python
# tests/test_export_api.py -- add
def test_export_markdown_only_includes_current_users_reels(client, session):
    from app.models import Location, Reel

    other_hub = Location(name="Other Hub", is_hub=True, user_id="other-user")
    session.add(other_hub)
    session.commit()
    session.refresh(other_hub)
    session.add(
        Reel(link="https://instagram.com/reel/x", location_id=other_hub.id, note="segreto", user_id="other-user")
    )
    session.commit()

    response = client.get("/api/export/markdown")

    assert "segreto" not in response.text
    assert "Other Hub" not in response.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_map_api.py tests/test_export_api.py -v`
Expected: FAIL — routes aren't scoped yet.

- [ ] **Step 3: Rewrite `app/routers/map.py`**

```python
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlmodel import Session

from app.auth import get_current_user
from app.db import get_session
from app.models import Location, Reel, User
from app.routers.categories import get_taxonomy, reel_ids_matching_types
from app.scoping import user_query
from app.web import templates

router = APIRouter(prefix="/api/map", tags=["map"])
ui_router = APIRouter(prefix="/ui", tags=["map-ui"])


def compute_map(session: Session, user_id: str) -> list[dict]:
    locations = session.exec(user_query(Location, user_id)).all()
    counts = dict(
        session.exec(
            user_query(Reel, user_id)
            .with_only_columns(Reel.location_id, func.count(Reel.id))
            .group_by(Reel.location_id)
        ).all()
    )

    return [
        {
            "id": loc.id,
            "name": loc.name,
            "is_hub": loc.is_hub,
            "parent_id": loc.parent_id,
            "lat": loc.lat,
            "lon": loc.lon,
            "reel_count": counts.get(loc.id, 0),
        }
        for loc in locations
    ]


@router.get("")
def get_map(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    return compute_map(session, current_user.id)


def locations_with_types(session: Session, user_id: str, type_values: list[str]) -> set[str]:
    reel_ids = reel_ids_matching_types(session, type_values)
    if not reel_ids:
        return set()
    return set(
        session.exec(user_query(Reel, user_id).with_only_columns(Reel.location_id).where(Reel.id.in_(reel_ids))).all()
    )


def visible_location_ids(
    session: Session,
    locations: list[dict],
    user_id: str,
    type_values: list[str] | None,
) -> tuple[set[str], set[str]]:
    """(visible_ids, anchor_hub_ids). Locations with no qualifying reel are
    always excluded. anchor_hub_ids is always a subset of visible_ids: hubs
    that qualify only because a child satellite qualifies, not because they
    have reels of their own."""
    type_values = type_values or []
    if type_values:
        qualifying = locations_with_types(session, user_id, type_values)
    else:
        qualifying = {loc["id"] for loc in locations if loc["reel_count"] > 0}

    anchor_hubs = {
        loc["id"]
        for loc in locations
        if loc["is_hub"]
        and loc["id"] not in qualifying
        and any(
            sat["parent_id"] == loc["id"] and sat["id"] in qualifying
            for sat in locations
        )
    }
    return qualifying | anchor_hubs, anchor_hubs


def render_map_html(session: Session, user_id: str, type_values: list[str] | None = None) -> str:
    type_values = type_values or []
    locations = compute_map(session, user_id)
    hubs_by_id = {loc["id"]: loc for loc in locations if loc["is_hub"]}
    matching_location_ids = locations_with_types(session, user_id, type_values) if type_values else set()
    visible_ids, anchor_hub_ids = visible_location_ids(session, locations, user_id, type_values)

    map_locations = []
    for loc in locations:
        if loc["id"] not in visible_ids:
            continue
        if loc["lat"] is None or loc["lon"] is None:
            continue

        entry = {
            "id": loc["id"],
            "name": loc["name"],
            "is_hub": loc["is_hub"],
            "lat": loc["lat"],
            "lon": loc["lon"],
            "anchor": loc["id"] in anchor_hub_ids,
            "dimmed": bool(type_values) and loc["id"] not in matching_location_ids,
            "parent_lat": None,
            "parent_lon": None,
        }
        if not loc["is_hub"]:
            parent = hubs_by_id.get(loc["parent_id"])
            if parent is not None and parent["lat"] is not None and parent["lon"] is not None:
                entry["parent_lat"] = parent["lat"]
                entry["parent_lon"] = parent["lon"]
        map_locations.append(entry)

    map_locations_json = json.dumps(map_locations).replace("<", "\\u003c")

    return templates.get_template("partials/map.html").render(
        map_locations_json=map_locations_json,
        active_types=type_values,
        taxonomy=get_taxonomy(session, user_id),
    )


@ui_router.get("/map")
def ui_map(
    request: Request,
    type: list[str] = Query([]),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return HTMLResponse(render_map_html(session, current_user.id, type))
```

- [ ] **Step 4: Rewrite `app/routers/export.py`**

```python
import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select

from app.auth import get_current_user
from app.db import get_session
from app.models import Location, Reel, ReelType, User
from app.routers.categories import get_taxonomy
from app.scoping import get_owned, user_query
from app.web import templates

router = APIRouter(prefix="/api/export", tags=["export"])
ui_router = APIRouter(prefix="/ui", tags=["export-ui"])


def _slugify_filename(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def _hub_locations(session: Session, user_id: str, hub: Location) -> list[Location]:
    satellites = session.exec(user_query(Location, user_id).where(Location.parent_id == hub.id)).all()
    return sorted([hub, *satellites], key=lambda loc: loc.name)


def _reel_line(note: Optional[str], category_labels: list[str]) -> Optional[str]:
    categories_part = f"**{', '.join(category_labels)}**" if category_labels else None
    if categories_part and note:
        return f"- {categories_part} — {note}"
    if categories_part:
        return f"- {categories_part}"
    if note:
        return f"- {note}"
    return None


def build_export_markdown(session: Session, user_id: str, hub_id: Optional[str] = None) -> str:
    taxonomy = get_taxonomy(session, user_id)

    hub_query = user_query(Location, user_id).where(Location.is_hub == True)
    if hub_id is not None:
        hub_query = hub_query.where(Location.id == hub_id)
    hubs = sorted(session.exec(hub_query).all(), key=lambda loc: loc.name)

    sections = []
    for hub in hubs:
        location_blocks = []
        for location in _hub_locations(session, user_id, hub):
            reels = session.exec(user_query(Reel, user_id).where(Reel.location_id == location.id)).all()
            lines = []
            for reel in reels:
                types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
                labels = [taxonomy[t.type]["label"] for t in types if t.type in taxonomy]
                line = _reel_line(reel.note, labels)
                if line:
                    lines.append(line)
            if lines:
                location_blocks.append(f"### {location.name}\n" + "\n".join(lines))
        if location_blocks:
            sections.append(f"## {hub.name}\n\n" + "\n\n".join(location_blocks))

    return "\n\n".join(sections)


@router.get("/markdown")
def export_markdown(
    hub_id: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    hub = None
    if hub_id is not None:
        hub = get_owned(session, Location, hub_id, current_user.id)
        if hub is None or not hub.is_hub:
            raise HTTPException(status_code=404, detail="Hub not found")

    content = build_export_markdown(session, current_user.id, hub_id)
    filename = f"export-{_slugify_filename(hub.name)}.md" if hub else "export.md"

    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@ui_router.get("/export")
def ui_export_panel(
    request: Request, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    hubs = sorted(
        session.exec(user_query(Location, current_user.id).where(Location.is_hub == True)).all(),
        key=lambda loc: loc.name,
    )
    return templates.TemplateResponse(request, "partials/export_panel.html", {"hubs": hubs})
```

- [ ] **Step 5: Fix the remaining fixtures in `tests/test_map_api.py` and `tests/test_export_api.py`**

Same mechanical rule: every `Location(`/`Reel(`/`ReelType(` call — `ReelType` excluded, no `user_id` column — gets `user_id=test_user_id` added (and `test_user_id` added as a test-function parameter). Run `grep -n "Location(\|Reel(" tests/test_map_api.py tests/test_export_api.py` for the exact line list.

- [ ] **Step 6: Run both test files**

Run: `uv run pytest tests/test_map_api.py tests/test_export_api.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/routers/map.py app/routers/export.py tests/test_map_api.py tests/test_export_api.py
git commit -m "feat: scope map and export views to the current user"
```

---

## Task 13: Scope `app/routers/reels.py`

**Files:**
- Modify: `app/routers/reels.py` (whole file)
- Modify: `tests/test_reels_api.py`
- Test: `tests/test_reels_api.py`

**Interfaces:**
- Consumes: `_create_location` from Task 11 (now takes `user_id` as 2nd positional arg), `get_taxonomy`/`get_valid_type_keys` from Task 10 (now take `user_id`), `find_duplicate_reel` from Task 9 (now takes `user_id`).
- Produces: `_serialize_reel(session, reel) -> dict` (unchanged signature — `reel` is always already ownership-checked by its caller before serialization); `_update_reel(session, user_id, reel_id, ...)`, `_reel_list_context(session, user_id, ...)`, `_reel_add_form_context(session, user_id, ...)`, `_reel_edit_form_context(session, user_id, reel)`, and `_location_and_satellite_ids(session, user_id, location_id)` all gain `user_id` as a parameter. Task 15 (`ai_categorize.py`/`ai_multi_categorize.py`) imports `_is_safe_link`, `_reel_add_form_context`, `_reel_list_context`; Task 16 (`ai_ask.py`) imports `_location_and_satellite_ids`; Task 17 (`note_regeneration.py`) imports `_serialize_reel` — all three tasks must pass `current_user.id` at every call site.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_reels_api.py -- add
def test_list_reels_only_returns_current_users_reels(client, session, test_user_id):
    from app.models import Location, Reel

    other_hub = Location(name="Other Hub", is_hub=True, user_id="other-user")
    session.add(other_hub)
    session.commit()
    session.refresh(other_hub)
    session.add(Reel(link="https://instagram.com/reel/other", location_id=other_hub.id, user_id="other-user"))
    session.commit()

    response = client.get("/api/reels")

    assert response.status_code == 200
    assert "https://instagram.com/reel/other" not in {r["link"] for r in response.json()}


def test_get_reel_belonging_to_another_user_returns_404(client, session):
    from app.models import Location, Reel

    other_hub = Location(name="Other Hub", is_hub=True, user_id="other-user")
    session.add(other_hub)
    session.commit()
    session.refresh(other_hub)
    other_reel = Reel(link="https://instagram.com/reel/other", location_id=other_hub.id, user_id="other-user")
    session.add(other_reel)
    session.commit()
    session.refresh(other_reel)

    response = client.put(
        f"/api/reels/{other_reel.id}",
        json={"link": "https://instagram.com/reel/x", "location_id": other_hub.id, "types": []},
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_reels_api.py -v`
Expected: FAIL — routes aren't scoped yet.

- [ ] **Step 3: Rewrite `app/routers/reels.py`**

```python
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth import get_current_user
from app.db import get_session
from app.models import Location, Reel, ReelType, User
from app.reel_links import find_duplicate_reel
from app.routers.categories import get_taxonomy, get_valid_type_keys, reel_ids_matching_types
from app.routers.locations import _create_location
from app.routers.map import render_map_html
from app.scoping import get_owned, user_query
from app.web import templates

router = APIRouter(prefix="/api/reels", tags=["reels"])
ui_router = APIRouter(prefix="/ui", tags=["reels-ui"])

NEW_LOCATION_SENTINEL = "__new__"


def _is_safe_link(link: str) -> bool:
    return urlparse(link).scheme.lower() in ("http", "https")


def _location_and_satellite_ids(session: Session, user_id: str, location_id: str) -> list[str]:
    satellite_ids = session.exec(
        user_query(Location, user_id).with_only_columns(Location.id).where(Location.parent_id == location_id)
    ).all()
    return [location_id, *satellite_ids]


def _filter_reels_by_types(session: Session, reels: list[Reel], type_values: list[str]) -> list[Reel]:
    type_ids = reel_ids_matching_types(session, type_values)
    if type_ids is None:
        return reels
    return [r for r in reels if r.id in type_ids]


def _filter_reels_by_text(session: Session, reels: list[Reel], q: Optional[str]) -> list[Reel]:
    if not q:
        return reels
    needle = q.strip().lower()
    if not needle:
        return reels

    location_names: dict[str, str] = {}

    def location_name(location_id: str) -> str:
        if location_id not in location_names:
            loc = session.get(Location, location_id)
            location_names[location_id] = loc.name if loc else ""
        return location_names[location_id]

    return [
        r
        for r in reels
        if needle in (r.note or "").lower() or needle in location_name(r.location_id).lower()
    ]


class ReelCreate(BaseModel):
    link: str
    location_id: str
    note: Optional[str] = None
    types: list[str] = []


def _maps_query(location: Optional[Location]) -> Optional[str]:
    if location is None:
        return None
    if location.geocode_confidence != "low" and location.name:
        return location.name
    if location.lat is not None and location.lon is not None:
        return f"{location.lat},{location.lon}"
    return None


def _serialize_reel(session: Session, reel: Reel) -> dict:
    types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    location = session.get(Location, reel.location_id)
    return {
        "id": reel.id,
        "link": reel.link,
        "location_id": reel.location_id,
        "location_name": location.name if location else None,
        "note": reel.note,
        "created_at": reel.created_at.isoformat(),
        "types": [t.type for t in types],
        "lat": location.lat if location else None,
        "lon": location.lon if location else None,
        "maps_query": _maps_query(location),
        "can_regenerate": bool(reel.caption or reel.transcript or reel.note),
    }


def _update_reel(
    session: Session,
    user_id: str,
    reel_id: str,
    link: str,
    location_id: str,
    note: Optional[str],
    types: list[str],
) -> Reel:
    reel = get_owned(session, Reel, reel_id, user_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")
    if get_owned(session, Location, location_id, user_id) is None:
        raise HTTPException(status_code=404, detail="Location not found")

    reel.link = link
    reel.location_id = location_id
    reel.note = note
    session.add(reel)

    for t in session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all():
        session.delete(t)
    session.commit()

    valid_type_keys = get_valid_type_keys(session, user_id)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel_id, type=type_value))
    session.commit()
    session.refresh(reel)
    return reel


@router.get("")
def list_reels(
    location_id: Optional[str] = None,
    type: list[str] = Query([]),
    q: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = user_query(Reel, current_user.id)
    if location_id is not None:
        query = query.where(
            Reel.location_id.in_(_location_and_satellite_ids(session, current_user.id, location_id))
        )
    reels = session.exec(query).all()

    reels = _filter_reels_by_types(session, reels, type)
    reels = _filter_reels_by_text(session, reels, q)

    return [_serialize_reel(session, r) for r in reels]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_reel(
    payload: ReelCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not _is_safe_link(payload.link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")
    if get_owned(session, Location, payload.location_id, current_user.id) is None:
        raise HTTPException(status_code=404, detail="Location not found")
    reel = Reel(
        link=payload.link, location_id=payload.location_id, note=payload.note, user_id=current_user.id
    )
    session.add(reel)
    session.commit()
    session.refresh(reel)

    valid_type_keys = get_valid_type_keys(session, current_user.id)
    for type_value in payload.types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    return _serialize_reel(session, reel)


@router.put("/{reel_id}")
def update_reel(
    reel_id: str,
    payload: ReelCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    reel = _update_reel(
        session, current_user.id, reel_id, payload.link, payload.location_id, payload.note, payload.types
    )
    return _serialize_reel(session, reel)


@router.delete("/{reel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reel(
    reel_id: str, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    reel = get_owned(session, Reel, reel_id, current_user.id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    types = session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all()
    for t in types:
        session.delete(t)
    session.delete(reel)
    session.commit()


def _reel_list_context(
    session: Session,
    user_id: str,
    location_id: Optional[str] = None,
    type_values: Optional[list[str]] = None,
    q: Optional[str] = None,
) -> dict:
    type_values = type_values or []
    query = user_query(Reel, user_id)
    if location_id is not None:
        query = query.where(Reel.location_id.in_(_location_and_satellite_ids(session, user_id, location_id)))
    reels = session.exec(query).all()

    reels = _filter_reels_by_types(session, reels, type_values)
    reels = _filter_reels_by_text(session, reels, q)

    filtered_location = get_owned(session, Location, location_id, user_id) if location_id else None
    return {
        "reels": [_serialize_reel(session, r) for r in reels],
        "taxonomy": get_taxonomy(session, user_id),
        "filtered_location": filtered_location,
    }


def _reel_add_form_context(
    session: Session,
    user_id: str,
    error: Optional[str] = None,
    duplicate_warning: Optional[dict] = None,
) -> dict:
    locations = session.exec(user_query(Location, user_id)).all()
    return {
        "locations": locations,
        "hubs": [loc for loc in locations if loc.is_hub],
        "taxonomy": get_taxonomy(session, user_id),
        "error": error,
        "duplicate_warning": duplicate_warning,
    }


def _reel_edit_form_context(session: Session, user_id: str, reel: Reel) -> dict:
    types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    return {
        "reel": reel,
        "locations": session.exec(user_query(Location, user_id)).all(),
        "taxonomy": get_taxonomy(session, user_id),
        "reel_type_keys": {t.type for t in types},
    }


@ui_router.get("/reels/add-form")
def ui_reel_add_form(
    request: Request, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    return templates.TemplateResponse(
        request, "partials/reel_add_form.html", _reel_add_form_context(session, current_user.id)
    )


@ui_router.get("/reels/{reel_id}/edit-form")
def ui_reel_edit_form(
    request: Request,
    reel_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    reel = get_owned(session, Reel, reel_id, current_user.id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    return templates.TemplateResponse(
        request, "partials/reel_edit_form.html", _reel_edit_form_context(session, current_user.id, reel)
    )


@ui_router.put("/reels/{reel_id}")
def ui_update_reel(
    request: Request,
    reel_id: str,
    link: str = Form(...),
    location_id: str = Form(...),
    note: Optional[str] = Form(None),
    types: list[str] = Form([]),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _update_reel(session, current_user.id, reel_id, link, location_id, note, types)

    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session, current_user.id)
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session, current_user.id)
    )
    map_html = render_map_html(session, current_user.id)

    response = HTMLResponse(
        form_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response


@ui_router.get("/reels")
def ui_list_reels(
    request: Request,
    location_id: Optional[str] = None,
    type: list[str] = Query([]),
    q: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        request, "partials/reel_list.html", _reel_list_context(session, current_user.id, location_id, type, q)
    )


@ui_router.post("/reels")
def ui_create_reel(
    request: Request,
    link: str = Form(...),
    location_id: str = Form(...),
    note: Optional[str] = Form(None),
    types: list[str] = Form([]),
    new_location_name: str = Form(""),
    new_location_is_hub: str = Form("true"),
    new_location_parent_id: str = Form(""),
    new_location_lat: Optional[float] = Form(None),
    new_location_lon: Optional[float] = Form(None),
    confirm_duplicate: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if confirm_duplicate != "true":
        duplicate = find_duplicate_reel(session, link, current_user.id)
        if duplicate is not None:
            existing_location = session.get(Location, duplicate.location_id)
            form_html = templates.get_template("partials/reel_add_form.html").render(
                _reel_add_form_context(
                    session,
                    current_user.id,
                    duplicate_warning={
                        "existing_location_name": existing_location.name if existing_location else "?",
                        "existing_note": duplicate.note,
                        "link": link,
                        "location_id": location_id,
                        "note": note or "",
                        "types": types,
                        "new_location_name": new_location_name,
                        "new_location_is_hub": new_location_is_hub,
                        "new_location_parent_id": new_location_parent_id,
                        "new_location_lat": new_location_lat if new_location_lat is not None else "",
                        "new_location_lon": new_location_lon if new_location_lon is not None else "",
                    },
                )
            )
            return HTMLResponse(form_html)

    if location_id == NEW_LOCATION_SENTINEL:
        try:
            new_location = _create_location(
                session,
                current_user.id,
                new_location_name,
                new_location_is_hub == "true",
                new_location_parent_id or None,
                new_location_lat,
                new_location_lon,
            )
        except HTTPException as exc:
            if exc.status_code != 400:
                raise
            form_html = templates.get_template("partials/reel_add_form.html").render(
                _reel_add_form_context(session, current_user.id, error="Un satellite richiede una città padre.")
            )
            return HTMLResponse(form_html)
        location_id = new_location.id
    elif get_owned(session, Location, location_id, current_user.id) is None:
        raise HTTPException(status_code=404, detail="Location not found")

    reel = Reel(link=link, location_id=location_id, note=note, user_id=current_user.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    valid_type_keys = get_valid_type_keys(session, current_user.id)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session, current_user.id)
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session, current_user.id)
    )
    map_html = render_map_html(session, current_user.id)

    response = HTMLResponse(
        form_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response


@ui_router.delete("/reels/{reel_id}")
def ui_delete_reel(
    request: Request,
    reel_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    reel = get_owned(session, Reel, reel_id, current_user.id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    for t in session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all():
        session.delete(t)
    session.delete(reel)
    session.commit()
    return templates.TemplateResponse(
        request, "partials/reel_list.html", _reel_list_context(session, current_user.id)
    )
```

Note: `render_map_html` here is called as `render_map_html(session, current_user.id)` — Task 12 (next) gives it that signature and runs *before* this task, so by the time this file is edited, `render_map_html` already takes `user_id`.

- [ ] **Step 4: Fix the remaining fixtures in `tests/test_reels_api.py`**

Every `Location(`/`Reel(`/`ReelType(` call — `ReelType` needs no `user_id` (no such column), only `Location(` and `Reel(` do — gets `user_id=test_user_id` added, and every test function gets `test_user_id` added as a parameter. Example transformation:

```python
# before
def test_create_reel_returns_serialized_payload(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/1", location_id=hub.id, note="Ramen")

# after
def test_create_reel_returns_serialized_payload(client, session, test_user_id):
    hub = Location(name="Tokyo / Kanto", is_hub=True, user_id=test_user_id)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/1", location_id=hub.id, note="Ramen", user_id=test_user_id)
```

Run `grep -n "Location(\|Reel(" tests/test_reels_api.py` for the exact line list.

- [ ] **Step 5: Run the reels test file**

Run: `uv run pytest tests/test_reels_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/routers/reels.py tests/test_reels_api.py
git commit -m "feat: scope reel CRUD and listing to the current user"
```

---

## Task 14: Scope `app/routers/audit.py`

**Files:**
- Modify: `app/routers/audit.py` (whole file)
- Modify: `tests/test_audit.py`
- Test: `tests/test_audit.py`

**Interfaces:**
- Consumes: `resolve_place` (Task 8, now takes `user_id`), `get_taxonomy`/`get_valid_type_keys` (Task 10), `_merge_locations` (Task 11, now takes `user_id` as 2nd positional arg).
- Produces: every private helper in this file gains a `user_id` parameter; no other task imports from `audit.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audit.py -- add
def test_audit_scan_does_not_surface_another_users_anomalies(client, session, test_user_id):
    from app.models import Location

    session.add(Location(name="Surugaya - Akihabara", is_hub=False, lat=35.7, lon=139.77, user_id="other-user"))
    session.add(
        Location(
            name="Surugaya Akihabara (駿河屋秋葉原)", is_hub=False, lat=35.7001, lon=139.7701, user_id="other-user"
        )
    )
    session.commit()

    response = client.get("/ui/audit/scan")

    assert response.status_code == 200
    assert "Surugaya" not in response.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_audit.py::test_audit_scan_does_not_surface_another_users_anomalies -v`
Expected: FAIL — the route doesn't scope by user yet (it will likely error since `client` needs `current_user`, or wrongly show the other user's pair).

- [ ] **Step 3: Rewrite `app/routers/audit.py`**

Replace the imports and every function (dataclasses are unchanged, omitted here for brevity — keep `AuditPair`, `GeocodeProposal`, `ImpreciseLocation`, `LowConfidenceLocation`, `SplitCandidate`, `SplitProposal`, `REVIEW_NAME_SIMILARITY_THRESHOLD` exactly as they are today):

```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app.auth import get_current_user
from app.db import get_session
from app.models import Location, Reel, ReelType, User
from app.scoping import get_owned, user_query
# ... keep the existing `import json`, `import logging`, `from dataclasses import ...`,
# `from difflib import SequenceMatcher`, `from typing import Optional`, `from sqlmodel import Session, select`,
# `from app.ai import client as ai_client`, `from app.ai.providers.base import AIProviderError`,
# `from app.location_matching import NEW_HUB_SENTINEL, normalize_place_name, resolve_place`,
# `from app.routers.categories import get_taxonomy, get_valid_type_keys`,
# `from app.routers.locations import _merge_locations`, `from app.routers.reels import _serialize_reel`,
# `from app.web import templates` lines exactly as today.
```

Then, each function:

```python
def _reels_for_location(session: Session, user_id: str, location_id: str) -> list:
    reels = session.exec(user_query(Reel, user_id).where(Reel.location_id == location_id)).all()
    return [_serialize_reel(session, r) for r in reels]
```

`_effective_coords` and `_worth_reviewing` are unchanged (pure functions, no DB access).

```python
def _find_imprecise_coordinates(session: Session, user_id: str, locations: list, by_id: dict) -> list:
    result = []
    for loc in locations:
        if loc.lat == 0 and loc.lon == 0:
            result.append(ImpreciseLocation(
                location=loc,
                reason="coordinate a 0,0 -- quasi certamente un errore, nessun posto in Giappone è lì",
                reels=_reels_for_location(session, user_id, loc.id),
            ))
            continue

        if loc.is_hub or not loc.parent_id:
            continue
        parent = by_id.get(loc.parent_id)
        if parent is not None and loc.lat == parent.lat and loc.lon == parent.lon:
            result.append(ImpreciseLocation(
                location=loc,
                reason=f"coordinate ereditate da {parent.name}",
                reels=_reels_for_location(session, user_id, loc.id),
            ))
    return result


def _find_low_confidence(session: Session, user_id: str, locations: list) -> list:
    return [
        LowConfidenceLocation(location=loc, reels=_reels_for_location(session, user_id, loc.id))
        for loc in locations
        if loc.geocode_confidence == "low"
    ]


def _find_split_candidates(session: Session, user_id: str, by_id: dict) -> list:
    reels = session.exec(user_query(Reel, user_id)).all()
    groups: dict = {}
    for r in reels:
        groups.setdefault((r.link, r.location_id), []).append(r)

    result = []
    for (link, location_id), group in groups.items():
        if len(group) > 1:
            result.append(SplitCandidate(
                link=link,
                location=by_id[location_id],
                reels=[_serialize_reel(session, r) for r in group],
            ))
    return result


def _propose_split(session: Session, user_id: str, candidate: SplitCandidate) -> list:
    hubs = session.exec(user_query(Location, user_id).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]
    taxonomy = get_taxonomy(session, user_id)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}
    valid_type_keys = get_valid_type_keys(session, user_id)

    proposals = []
    for reel in candidate.reels:
        try:
            result = ai_client.categorize(
                hub_names, category_labels, [{"role": "user", "content": reel["note"] or ""}]
            )
        except (AIProviderError, RuntimeError):
            logger.exception("categorize call failed during split proposal for reel=%s", reel["id"])
            proposals.append(SplitProposal(
                reel_id=reel["id"], place_name="", note=reel["note"] or "",
                resolution=None, place_json="",
                error="Errore nel contattare l'assistente, riprova.",
            ))
            continue

        types = [t for t in result.get("types", []) if t in valid_type_keys]
        place_name = result.get("place_name", "")
        resolution = resolve_place(
            session, place_name, result.get("near_hub"), result.get("lat"), result.get("lon"), user_id
        )

        place_payload = {
            "reel_id": reel["id"],
            "place_name": place_name,
            "note": reel["note"] or "",
            "types": types,
            "lat": result.get("lat"),
            "lon": result.get("lon"),
            "confidence": result.get("confidence"),
            "resolution_location_id": resolution.place_location_id if resolution.place_tier == "auto" else "",
            "resolution_hub_id": resolution.hub_id if resolution.hub_tier == "auto" else "",
        }
        proposals.append(SplitProposal(
            reel_id=reel["id"], place_name=place_name, note=reel["note"] or "",
            resolution=resolution, place_json=json.dumps(place_payload),
        ))
    return proposals


def _reassign_reel_location(
    session: Session,
    user_id: str,
    reel_id: str,
    place_name: str,
    types: list,
    lat,
    lon,
    resolution_location_id: str,
    resolution_hub_id: str = "",
    confidence: Optional[str] = None,
) -> Reel:
    reel = get_owned(session, Reel, reel_id, user_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    if resolution_location_id:
        location_id = resolution_location_id
    else:
        if not lat or not lon:
            raise HTTPException(status_code=400, detail="lat/lon are required to create a new location")
        if not resolution_hub_id:
            raise HTTPException(status_code=400, detail="a hub choice is required to create a new location")

        is_hub = resolution_hub_id == NEW_HUB_SENTINEL
        new_location = Location(
            name=place_name,
            is_hub=is_hub,
            parent_id=None if is_hub else resolution_hub_id,
            lat=float(lat),
            lon=float(lon),
            geocode_confidence=confidence or None,
            user_id=user_id,
        )
        session.add(new_location)
        session.commit()
        session.refresh(new_location)
        location_id = new_location.id

    reel.location_id = location_id
    session.add(reel)

    valid_type_keys = get_valid_type_keys(session, user_id)
    for existing in session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all():
        session.delete(existing)
    session.commit()
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel_id, type=type_value))
    session.commit()
    session.refresh(reel)
    return reel


def _propose_geocode(session: Session, user_id: str, location: Location) -> GeocodeProposal:
    hubs = session.exec(user_query(Location, user_id).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]
    taxonomy = get_taxonomy(session, user_id)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}

    notes = [r["note"] for r in _reels_for_location(session, user_id, location.id) if r["note"]]
    message = location.name if not notes else f"{location.name}. {' '.join(notes)}"

    try:
        result = ai_client.categorize(hub_names, category_labels, [{"role": "user", "content": message}])
    except (AIProviderError, RuntimeError):
        logger.exception("categorize call failed during geocode proposal for location=%s", location.id)
        return GeocodeProposal(
            lat=None, lon=None, confidence=None,
            error="Errore nel contattare l'assistente, riprova.",
        )

    return GeocodeProposal(lat=result.get("lat"), lon=result.get("lon"), confidence=result.get("confidence"))


def _find_anomalies(session: Session, user_id: str) -> dict:
    locations = session.exec(user_query(Location, user_id)).all()
    by_id = {loc.id: loc for loc in locations}

    certain_keys: set = set()
    certain_pairs: list[AuditPair] = []
    for loc in locations:
        lat, lon = _effective_coords(loc, by_id)
        resolution = resolve_place(session, loc.name, None, lat, lon, user_id, exclude_location_id=loc.id)
        if resolution.place_tier == "auto":
            other = by_id[resolution.place_location_id]
            if other.is_hub != loc.is_hub:
                continue
            key = frozenset((loc.id, other.id))
            if key not in certain_keys:
                certain_keys.add(key)
                certain_pairs.append(AuditPair(
                    a=loc, b=other,
                    a_reels=_reels_for_location(session, user_id, loc.id),
                    b_reels=_reels_for_location(session, user_id, other.id),
                ))

    review_keys: set = set()
    review_pairs: list[AuditPair] = []
    for loc in locations:
        lat, lon = _effective_coords(loc, by_id)
        resolution = resolve_place(session, loc.name, None, lat, lon, user_id, exclude_location_id=loc.id)
        for candidate in resolution.place_candidates:
            other = by_id[candidate.id]
            if other.is_hub != loc.is_hub:
                continue
            if not _worth_reviewing(loc.name, other.name):
                continue
            key = frozenset((loc.id, other.id))
            if key in certain_keys or key in review_keys:
                continue
            review_keys.add(key)
            review_pairs.append(AuditPair(
                a=loc, b=other,
                a_reels=_reels_for_location(session, user_id, loc.id),
                b_reels=_reels_for_location(session, user_id, other.id),
                distance_m=candidate.distance_m,
            ))

    return {
        "certain_pairs": certain_pairs,
        "review_pairs": review_pairs,
        "imprecise_locations": _find_imprecise_coordinates(session, user_id, locations, by_id),
        "low_confidence_locations": _find_low_confidence(session, user_id, locations),
        "split_candidates": _find_split_candidates(session, user_id, by_id),
        "taxonomy": get_taxonomy(session, user_id),
        "error": None,
    }


@ui_router.get("/scan")
def ui_audit_scan(
    request: Request, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    return templates.TemplateResponse(request, "partials/audit_results.html", _find_anomalies(session, current_user.id))


@ui_router.post("/ai/compare/{location_a_id}/{location_b_id}")
def ui_audit_ai_compare(
    request: Request,
    location_a_id: str,
    location_b_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    loc_a = get_owned(session, Location, location_a_id, current_user.id)
    loc_b = get_owned(session, Location, location_b_id, current_user.id)
    if loc_a is None or loc_b is None:
        raise HTTPException(status_code=404, detail="Location not found")

    notes_a = [r["note"] for r in _reels_for_location(session, current_user.id, loc_a.id) if r["note"]]
    notes_b = [r["note"] for r in _reels_for_location(session, current_user.id, loc_b.id) if r["note"]]

    try:
        verdict = ai_client.compare_places(loc_a.name, notes_a, loc_b.name, notes_b)
    except (AIProviderError, RuntimeError):
        logger.exception("compare_places call failed for %s vs %s", loc_a.id, loc_b.id)
        verdict = {"same_place": None, "reasoning": "Errore nel contattare l'assistente, riprova."}

    context = _find_anomalies(session, current_user.id)
    target_key = frozenset((loc_a.id, loc_b.id))
    for pair in context["certain_pairs"] + context["review_pairs"]:
        if frozenset((pair.a.id, pair.b.id)) == target_key:
            pair.ai_verdict = verdict
            break

    return templates.TemplateResponse(request, "partials/audit_results.html", context)


@ui_router.post("/ai/split/apply")
def ui_audit_ai_split_apply(
    request: Request,
    place_json: list[str] = Form([]),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    parsed_places = []
    for raw in place_json:
        try:
            parsed_places.append(json.loads(raw))
        except json.JSONDecodeError:
            logger.exception("skipping malformed place_json entry in split apply")

    for place in parsed_places:
        if not place.get("resolution_location_id"):
            if not place.get("lat") or not place.get("lon"):
                raise HTTPException(status_code=400, detail="lat/lon are required to create a new location")
            if not place.get("resolution_hub_id"):
                raise HTTPException(status_code=400, detail="a hub choice is required to create a new location")

    for place in parsed_places:
        _reassign_reel_location(
            session,
            current_user.id,
            place["reel_id"],
            place.get("place_name", ""),
            place.get("types", []),
            place.get("lat"),
            place.get("lon"),
            place.get("resolution_location_id", ""),
            place.get("resolution_hub_id", ""),
            place.get("confidence"),
        )

    return templates.TemplateResponse(
        request, "partials/audit_results.html", _find_anomalies(session, current_user.id)
    )


@ui_router.post("/ai/split/{location_id}")
def ui_audit_ai_split(
    request: Request,
    location_id: str,
    link: str = Form(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    context = _find_anomalies(session, current_user.id)
    for candidate in context["split_candidates"]:
        if candidate.location.id == location_id and candidate.link == link:
            candidate.proposals = _propose_split(session, current_user.id, candidate)
            break
    return templates.TemplateResponse(request, "partials/audit_results.html", context)


@ui_router.post("/ai/geocode/apply/{location_id}")
def ui_audit_ai_geocode_apply(
    request: Request,
    location_id: str,
    lat: float = Form(...),
    lon: float = Form(...),
    confidence: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    location = get_owned(session, Location, location_id, current_user.id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    location.lat = lat
    location.lon = lon
    location.geocode_confidence = confidence or None
    session.add(location)
    session.commit()
    return templates.TemplateResponse(
        request, "partials/audit_results.html", _find_anomalies(session, current_user.id)
    )


@ui_router.post("/ai/geocode/{location_id}")
def ui_audit_ai_geocode(
    request: Request,
    location_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    location = get_owned(session, Location, location_id, current_user.id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")

    proposal = _propose_geocode(session, current_user.id, location)

    context = _find_anomalies(session, current_user.id)
    for item in context["imprecise_locations"] + context["low_confidence_locations"]:
        if item.location.id == location_id:
            item.proposal = proposal

    return templates.TemplateResponse(request, "partials/audit_results.html", context)


@ui_router.post("/merge/{keep_id}/{drop_id}")
def ui_audit_merge(
    request: Request,
    keep_id: str,
    drop_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        _merge_locations(session, current_user.id, keep_id, drop_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        context = _find_anomalies(session, current_user.id)
        context["error"] = "Impossibile unire: la location da eliminare ha ancora città satellite collegate."
        return templates.TemplateResponse(request, "partials/audit_results.html", context)
    return templates.TemplateResponse(
        request, "partials/audit_results.html", _find_anomalies(session, current_user.id)
    )
```

- [ ] **Step 4: Fix the remaining fixtures in `tests/test_audit.py`**

Same mechanical rule: every `Location(`/`Reel(` call (there are ~60 in this file, all building up the various audit scenarios) gets `user_id=test_user_id` added, and every test function gets `test_user_id` added as a parameter. Run `grep -n "Location(\|Reel(" tests/test_audit.py` for the exact line list. Several of these also call `audit.py`'s now-`user_id`-scoped private helpers directly in test bodies (e.g. `_find_anomalies(session)`, `resolve_place(session, ...)`) — add `test_user_id` to those calls too, matching each function's new signature from Step 3/Task 8.

- [ ] **Step 5: Run the audit test file**

Run: `uv run pytest tests/test_audit.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/routers/audit.py tests/test_audit.py
git commit -m "feat: scope location audit tool to the current user"
```

---

## Task 15: Scope `app/routers/ai_categorize.py` and `app/routers/ai_multi_categorize.py`

**Files:**
- Modify: `app/routers/ai_categorize.py` (whole file)
- Modify: `app/routers/ai_multi_categorize.py` (whole file)
- Modify: `tests/test_ai_categorize.py`, `tests/test_ai_multi_categorize.py`, `tests/test_ai_ui.py`
- Test: `tests/test_ai_categorize.py`, `tests/test_ai_multi_categorize.py`, `tests/test_ai_ui.py`

**Interfaces:**
- Consumes: `get_taxonomy`/`get_valid_type_keys` (Task 10), `resolve_place` (Task 8), `find_duplicate_reel` (Task 9), `render_map_html` (Task 12), `_is_safe_link`/`_reel_add_form_context`/`_reel_list_context` (Task 13).
- Produces: `_run_turn(session, user_id, session_id, message)`, `_apply_result_post_processing(session, user_id, ai_session, result)`, `_categorize_new_session_message` (unchanged — DB-free, no `user_id` needed), `_persist_categorize_result(session, user_id, message, result)`, `_build_ai_chat_context(session, user_id, ...)`, `_resolve_location_and_create_reel(session, user_id, ...)`. `ai_multi_categorize.py`'s `start_multi_place_batch(request, session, user_id, ...)` and `_build_multi_context(session, user_id, ...)` gain `user_id` too.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_categorize.py -- add
def test_categorize_ai_session_belonging_to_another_user_returns_404(client, session):
    from app.models import AiSession

    other_session = AiSession(user_id="other-user")
    session.add(other_session)
    session.commit()
    session.refresh(other_session)

    response = client.post(
        "/api/ai/categorize", json={"session_id": other_session.id, "message": "test"}
    )

    assert response.status_code == 404
```

```python
# tests/test_ai_multi_categorize.py -- add
def test_multi_message_clarify_on_another_users_session_returns_404(client, session):
    from app.models import AiSession

    other_session = AiSession(user_id="other-user")
    session.add(other_session)
    session.commit()
    session.refresh(other_session)

    response = client.post(
        "/ui/ai/multi/message",
        data={"link": "https://instagram.com/reel/x", "clarify_session_id": other_session.id, "clarify_text": "Tokyo"},
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ai_categorize.py tests/test_ai_multi_categorize.py -v`
Expected: FAIL — routes aren't scoped yet.

- [ ] **Step 3: Rewrite `app/routers/ai_categorize.py`**

Keep `CategorizeRequest`, `CategorizeResponse`, `_assistant_turn_text`, and `MISSING_COORDINATES_QUESTION` exactly as they are. Update imports and the rest:

```python
from app.auth import get_current_user
from app.models import AiMessage, AiSession, Location, Reel, ReelType, User
from app.scoping import get_owned, user_query
# keep: import json, import logging, from typing import Optional,
# from app.ai.providers.base import AIProviderError, from fastapi import APIRouter, Depends, Form, HTTPException, Request,
# from fastapi.responses import HTMLResponse, from pydantic import BaseModel, from sqlmodel import Session, select,
# from app.ai import client as ai_client, from app.db import get_session,
# from app.location_matching import NEW_HUB_SENTINEL, resolve_place, from app.reel_links import find_duplicate_reel,
# from app.routers.categories import get_taxonomy, get_valid_type_keys, from app.routers.map import render_map_html,
# from app.routers.reels import _is_safe_link, _reel_add_form_context, _reel_list_context, from app.web import templates
```

```python
def _apply_result_post_processing(
    session: Session, user_id: str, ai_session: AiSession, result: dict
) -> Optional[str]:
    logger.debug("session=%s parsed model result=%s", ai_session.id, result)

    valid_type_keys = get_valid_type_keys(session, user_id)
    result["types"] = [t for t in result.get("types", []) if t in valid_type_keys]

    resolution = resolve_place(
        session, result["place_name"], result.get("near_hub"), result.get("lat"), result.get("lon"), user_id
    )
    logger.debug("session=%s resolution=%s", ai_session.id, resolution)

    if (
        resolution.place_tier == "ambiguous"
        and result.get("question") is None
        and not result.get("candidates")
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        if resolution.hub_tier == "auto":
            hub = session.get(Location, resolution.hub_id)
            result["lat"] = hub.lat
            result["lon"] = hub.lon

        if result.get("lat") is None or result.get("lon") is None:
            result["question"] = MISSING_COORDINATES_QUESTION

    logger.debug("session=%s final result=%s", ai_session.id, result)
    return resolution.place_location_id


def _run_turn(
    session: Session, user_id: str, session_id: Optional[str], message: str
) -> tuple[AiSession, dict, Optional[str]]:
    if session_id:
        ai_session = get_owned(session, AiSession, session_id, user_id)
        if ai_session is None:
            raise HTTPException(status_code=404, detail="AI session not found")
    else:
        ai_session = AiSession(user_id=user_id)
        session.add(ai_session)
        session.commit()
        session.refresh(ai_session)

    session.add(AiMessage(session_id=ai_session.id, role="user", content=message))
    session.commit()

    history = session.exec(
        select(AiMessage)
        .where(AiMessage.session_id == ai_session.id)
        .order_by(AiMessage.created_at)
    ).all()
    api_messages = [
        {
            "role": m.role,
            "content": _assistant_turn_text(json.loads(m.content)) if m.role == "assistant" else m.content,
        }
        for m in history
    ]

    hubs = session.exec(user_query(Location, user_id).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]

    taxonomy = get_taxonomy(session, user_id)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}

    try:
        result = ai_client.categorize(hub_names, category_labels, api_messages)
    except (AIProviderError, RuntimeError):
        logger.exception("session=%s Anthropic call failed", ai_session.id)
        result = {
            "place_name": "", "near_hub": None, "types": [], "note": "",
            "confidence": "low", "question": "Errore nel contattare l'assistente, riprova.",
            "lat": None, "lon": None,
        }

    matched_location_id = _apply_result_post_processing(session, user_id, ai_session, result)

    session.add(AiMessage(session_id=ai_session.id, role="assistant", content=json.dumps(result)))
    session.commit()

    return ai_session, result, matched_location_id


def _categorize_new_session_message(
    message: str, hub_names: list[str], category_labels: dict[str, str]
) -> dict:
    """Unchanged -- DB-free, no user_id needed; safe to call concurrently."""
    try:
        return ai_client.categorize(hub_names, category_labels, [{"role": "user", "content": message}])
    except (AIProviderError, RuntimeError):
        logger.exception("categorize call failed for new-session message")
        return {
            "place_name": "", "near_hub": None, "types": [], "note": "",
            "confidence": "low", "question": "Errore nel contattare l'assistente, riprova.",
            "lat": None, "lon": None,
        }


def _persist_categorize_result(
    session: Session, user_id: str, message: str, result: dict
) -> tuple[AiSession, dict, Optional[str]]:
    ai_session = AiSession(user_id=user_id)
    session.add(ai_session)
    session.commit()
    session.refresh(ai_session)

    session.add(AiMessage(session_id=ai_session.id, role="user", content=message))

    matched_location_id = _apply_result_post_processing(session, user_id, ai_session, result)

    session.add(AiMessage(session_id=ai_session.id, role="assistant", content=json.dumps(result)))
    session.commit()

    return ai_session, result, matched_location_id


@router.post("/categorize", response_model=CategorizeResponse)
def categorize_reel(
    payload: CategorizeRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ai_session, result, matched_location_id = _run_turn(session, current_user.id, payload.session_id, payload.message)
    return CategorizeResponse(session_id=ai_session.id, matched_location_id=matched_location_id, **result)


def _build_ai_chat_context(
    session: Session,
    user_id: str,
    ai_session_id: Optional[str],
    link: str,
    notice: Optional[str] = None,
    caption: str = "",
    transcript: str = "",
    duplicate_warning: Optional[dict] = None,
) -> dict:
    history: list[dict] = []
    latest_result: Optional[dict] = None

    if ai_session_id:
        messages = session.exec(
            select(AiMessage).where(AiMessage.session_id == ai_session_id).order_by(AiMessage.created_at)
        ).all()
        for m in messages:
            if m.role == "user":
                history.append({"role": "user", "text": m.content})
            else:
                result = json.loads(m.content)
                history.append({"role": "assistant", "result": result})
                latest_result = result

    resolution = (
        resolve_place(
            session,
            latest_result["place_name"],
            latest_result.get("near_hub"),
            latest_result.get("lat"),
            latest_result.get("lon"),
            user_id,
        )
        if latest_result is not None
        else None
    )
    can_confirm = (
        latest_result is not None
        and latest_result.get("question") is None
        and not latest_result.get("candidates")
    )

    return {
        "session_id": ai_session_id or "",
        "link": link or "",
        "caption": caption or "",
        "transcript": transcript or "",
        "history": history,
        "latest_result": latest_result,
        "can_confirm": can_confirm,
        "resolution": resolution,
        "taxonomy": get_taxonomy(session, user_id),
        "notice": notice,
        "duplicate_warning": duplicate_warning,
    }


@ui_router.get("/panel")
def ui_ai_panel(
    request: Request, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    return templates.TemplateResponse(
        request, "partials/ai_chat.html", _build_ai_chat_context(session, current_user.id, None, "")
    )


@ui_router.post("/message")
def ui_ai_message(
    request: Request,
    session_id: str = Form(""),
    link: str = Form(""),
    message: str = Form(...),
    caption: str = Form(""),
    transcript: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not session_id:
        if not _is_safe_link(link):
            raise HTTPException(status_code=400, detail="link must be an http(s) URL")
        combined_message = f"Link: {link}\nDescrizione: {message}"

        try:
            detection = ai_client.detect_places(combined_message)
        except (AIProviderError, RuntimeError, json.JSONDecodeError):
            logger.exception("detect_places call failed, treating as single-place")
            detection = {"is_multi_place": False, "place_names": None}

        place_names = detection.get("place_names") or []
        if detection.get("is_multi_place") and len(place_names) >= 2:
            from app.routers.ai_multi_categorize import start_multi_place_batch

            return start_multi_place_batch(
                request, session, current_user.id, combined_message, link, place_names, caption, transcript
            )
    else:
        combined_message = message

    try:
        ai_session, _, _ = _run_turn(session, current_user.id, session_id or None, combined_message)
    except HTTPException as exc:
        if exc.status_code == 404:
            context = _build_ai_chat_context(
                session, current_user.id, None, "", notice="Sessione scaduta, ricomincia pure da qui."
            )
            return templates.TemplateResponse(request, "partials/ai_chat.html", context)
        raise

    return templates.TemplateResponse(
        request,
        "partials/ai_chat.html",
        _build_ai_chat_context(session, current_user.id, ai_session.id, link, caption=caption, transcript=transcript),
    )


def _resolve_location_and_create_reel(
    session: Session,
    user_id: str,
    link: str,
    place_name: str,
    types: list[str],
    note: str,
    lat,
    lon,
    resolution_location_id: str,
    resolution_hub_id: str = "",
    confidence: Optional[str] = None,
    caption: str = "",
    transcript: str = "",
) -> Reel:
    if resolution_location_id:
        location_id = resolution_location_id
    else:
        if not lat or not lon:
            raise HTTPException(status_code=400, detail="lat/lon are required to create a new location")
        if not resolution_hub_id:
            raise HTTPException(status_code=400, detail="a hub choice is required to create a new location")

        is_hub = resolution_hub_id == NEW_HUB_SENTINEL
        new_location = Location(
            name=place_name,
            is_hub=is_hub,
            parent_id=None if is_hub else resolution_hub_id,
            lat=float(lat),
            lon=float(lon),
            geocode_confidence=confidence or None,
            user_id=user_id,
        )
        session.add(new_location)
        session.commit()
        session.refresh(new_location)
        location_id = new_location.id

    reel = Reel(
        link=link,
        location_id=location_id,
        note=note or None,
        caption=caption or None,
        transcript=transcript or None,
        user_id=user_id,
    )
    session.add(reel)
    session.commit()
    session.refresh(reel)

    valid_type_keys = get_valid_type_keys(session, user_id)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    return reel


@ui_router.post("/confirm")
def ui_ai_confirm(
    request: Request,
    session_id: str = Form(...),
    link: str = Form(...),
    place_name: str = Form(...),
    types: list[str] = Form([]),
    note: str = Form(""),
    lat: str = Form(""),
    lon: str = Form(""),
    resolution_location_id: str = Form(""),
    resolution_hub_id: str = Form(""),
    confidence: str = Form(""),
    confirm_duplicate: str = Form(""),
    caption: str = Form(""),
    transcript: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if confirm_duplicate != "true":
        duplicate = find_duplicate_reel(session, link, current_user.id)
        if duplicate is not None:
            existing_location = session.get(Location, duplicate.location_id)
            warning_html = templates.get_template("partials/_ai_confirm_duplicate_warning.html").render(
                existing_location_name=existing_location.name if existing_location else "?",
                existing_note=duplicate.note,
                session_id=session_id, link=link, place_name=place_name, types=types, note=note,
                lat=lat, lon=lon, resolution_location_id=resolution_location_id,
                resolution_hub_id=resolution_hub_id, confidence=confidence, caption=caption, transcript=transcript,
            )
            return HTMLResponse(warning_html)

    _resolve_location_and_create_reel(
        session, current_user.id, link, place_name, types, note, lat, lon,
        resolution_location_id, resolution_hub_id, confidence, caption, transcript,
    )

    stale_ai_session = get_owned(session, AiSession, session_id, current_user.id)
    if stale_ai_session is not None:
        for msg in session.exec(select(AiMessage).where(AiMessage.session_id == session_id)).all():
            session.delete(msg)
        session.delete(stale_ai_session)
        session.commit()

    ai_chat_html = templates.get_template("partials/ai_chat.html").render(
        _build_ai_chat_context(session, current_user.id, None, "")
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session, current_user.id)
    )
    map_html = render_map_html(session, current_user.id)
    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session, current_user.id)
    )

    response = HTMLResponse(
        ai_chat_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#reel-add-form-panel">{form_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response
```

- [ ] **Step 4: Rewrite `app/routers/ai_multi_categorize.py`**

Keep `MAX_PLACES`, `MAX_CONCURRENT_CATEGORIZE_CALLS`, `_seed_message` exactly as they are. Update everything else:

```python
from app.auth import get_current_user
from app.models import AiMessage, AiSession, Location, User
from app.scoping import get_owned, user_query
# keep: import json, import logging, from concurrent.futures import ThreadPoolExecutor,
# from typing import Optional, from fastapi import APIRouter, Depends, Form, HTTPException, Request,
# from fastapi.responses import HTMLResponse, from sqlmodel import Session, select, from app.db import get_session,
# from app.location_matching import resolve_place, from app.reel_links import find_duplicate_reel,
# from app.routers.ai_categorize import (_build_ai_chat_context, _categorize_new_session_message,
# _persist_categorize_result, _resolve_location_and_create_reel, _run_turn),
# from app.routers.categories import get_taxonomy, from app.routers.map import render_map_html,
# from app.routers.reels import _is_safe_link, _reel_add_form_context, _reel_list_context, from app.web import templates
```

```python
def _read_latest_result(session: Session, user_id: str, session_id: str) -> Optional[dict]:
    ai_session = get_owned(session, AiSession, session_id, user_id)
    if ai_session is None:
        return None
    messages = session.exec(
        select(AiMessage)
        .where(AiMessage.session_id == session_id, AiMessage.role == "assistant")
        .order_by(AiMessage.created_at)
    ).all()
    if not messages:
        return None
    return json.loads(messages[-1].content)


def _build_multi_context(
    session: Session, user_id: str, session_ids: list[str], link: str, caption: str = "", transcript: str = ""
) -> dict:
    seen: set[str] = set()
    session_ids = [sid for sid in session_ids if not (sid in seen or seen.add(sid))]

    rows = []
    for session_id in session_ids:
        result = _read_latest_result(session, user_id, session_id)
        if result is None:
            continue
        resolution = resolve_place(
            session, result.get("place_name", ""), result.get("near_hub"), result.get("lat"), result.get("lon"), user_id
        )
        resolved = result.get("question") is None
        place_payload = {
            "place_name": result.get("place_name", ""),
            "types": result.get("types", []),
            "note": result.get("note", ""),
            "lat": result.get("lat"),
            "lon": result.get("lon"),
            "resolution_location_id": resolution.place_location_id or "",
            "resolution_hub_id": resolution.hub_id or "",
            "confidence": result.get("confidence"),
        }
        rows.append({
            "session_id": session_id, "result": result, "resolved": resolved,
            "resolution": resolution, "place_json": json.dumps(place_payload),
        })

    return {
        "link": link or "", "caption": caption or "", "transcript": transcript or "",
        "session_ids": session_ids, "rows": rows, "taxonomy": get_taxonomy(session, user_id),
    }


def start_multi_place_batch(
    request: Request,
    session: Session,
    user_id: str,
    original_message: str,
    link: str,
    place_names: list[str],
    caption: str = "",
    transcript: str = "",
):
    hubs = session.exec(user_query(Location, user_id).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]
    taxonomy = get_taxonomy(session, user_id)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}

    seeded_messages = [
        _seed_message(original_message, place_name) for place_name in place_names[:MAX_PLACES]
    ]

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CATEGORIZE_CALLS) as executor:
        results = list(
            executor.map(
                lambda m: _categorize_new_session_message(m, hub_names, category_labels),
                seeded_messages,
            )
        )

    session_ids = []
    for message, result in zip(seeded_messages, results):
        ai_session, _, _ = _persist_categorize_result(session, user_id, message, result)
        session_ids.append(ai_session.id)

    context = _build_multi_context(session, user_id, session_ids, link, caption, transcript)
    return templates.TemplateResponse(request, "partials/ai_chat_multi.html", context)


@router.post("/message")
def ui_ai_multi_message(
    request: Request,
    link: str = Form(""),
    session_ids: list[str] = Form([]),
    clarify_session_id: str = Form(""),
    clarify_text: str = Form(""),
    caption: str = Form(""),
    transcript: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if clarify_session_id and clarify_text:
        if get_owned(session, AiSession, clarify_session_id, current_user.id) is None:
            raise HTTPException(status_code=404, detail="AI session not found")
        _run_turn(session, current_user.id, clarify_session_id, clarify_text)

    context = _build_multi_context(session, current_user.id, session_ids, link, caption, transcript)
    return templates.TemplateResponse(request, "partials/ai_chat_multi.html", context)


@router.post("/confirm")
def ui_ai_multi_confirm(
    request: Request,
    link: str = Form(...),
    session_ids: list[str] = Form([]),
    place_json: list[str] = Form([]),
    confirm_duplicate: str = Form(""),
    caption: str = Form(""),
    transcript: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if confirm_duplicate != "true":
        duplicate = find_duplicate_reel(session, link, current_user.id)
        if duplicate is not None:
            existing_location = session.get(Location, duplicate.location_id)
            warning_html = templates.get_template("partials/_ai_multi_confirm_duplicate_warning.html").render(
                existing_location_name=existing_location.name if existing_location else "?",
                existing_note=duplicate.note, link=link, session_ids=session_ids,
                place_json=place_json, caption=caption, transcript=transcript,
            )
            return HTMLResponse(warning_html)

    places = []
    for raw in place_json:
        try:
            places.append(json.loads(raw))
        except json.JSONDecodeError:
            logger.exception("skipping malformed place_json entry")
            continue

    for place in places:
        if not place.get("resolution_location_id", ""):
            if not place.get("lat") or not place.get("lon"):
                raise HTTPException(status_code=400, detail="lat/lon are required to create a new location")
            if not place.get("resolution_hub_id", ""):
                raise HTTPException(status_code=400, detail="a hub choice is required to create a new location")

    for place in places:
        _resolve_location_and_create_reel(
            session, current_user.id, link, place["place_name"], place.get("types", []), place.get("note", ""),
            place.get("lat"), place.get("lon"), place.get("resolution_location_id", ""),
            place.get("resolution_hub_id", ""), place.get("confidence"), caption, transcript,
        )

    for session_id in session_ids:
        stale_ai_session = get_owned(session, AiSession, session_id, current_user.id)
        if stale_ai_session is not None:
            for msg in session.exec(select(AiMessage).where(AiMessage.session_id == session_id)).all():
                session.delete(msg)
            session.delete(stale_ai_session)
            session.commit()

    ai_chat_html = templates.get_template("partials/ai_chat.html").render(
        _build_ai_chat_context(session, current_user.id, None, "")
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session, current_user.id)
    )
    map_html = render_map_html(session, current_user.id)
    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session, current_user.id)
    )

    response = HTMLResponse(
        ai_chat_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#reel-add-form-panel">{form_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response
```

- [ ] **Step 5: Fix the remaining fixtures in `tests/test_ai_categorize.py`, `tests/test_ai_multi_categorize.py`, `tests/test_ai_ui.py`**

Same mechanical rule: every `Location(`/`Reel(`/`Category(`/`AiSession(` call gets `user_id=test_user_id` added, every enclosing test function gets `test_user_id` added as a parameter. Run `grep -n "Location(\|Reel(\|Category(\|AiSession(" tests/test_ai_categorize.py tests/test_ai_multi_categorize.py tests/test_ai_ui.py` for the exact line lists.

- [ ] **Step 6: Run the three test files**

Run: `uv run pytest tests/test_ai_categorize.py tests/test_ai_multi_categorize.py tests/test_ai_ui.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/routers/ai_categorize.py app/routers/ai_multi_categorize.py tests/test_ai_categorize.py tests/test_ai_multi_categorize.py tests/test_ai_ui.py
git commit -m "feat: scope AI categorize/multi-place chat flows to the current user"
```

---

## Task 16: Scope `app/routers/ai_ask.py`

**Files:**
- Modify: `app/routers/ai_ask.py` (whole file)
- Modify: `tests/test_ai_ask.py`
- Test: `tests/test_ai_ask.py`

**Interfaces:**
- Consumes: `get_taxonomy` (Task 10), `_location_and_satellite_ids` (Task 13).
- Produces: every private helper in this file gains a `user_id` parameter; no other task imports from `ai_ask.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_ask.py -- add
def test_ask_panel_for_another_users_session_id_shows_not_found_notice(client, session):
    from app.models import AskSession

    other_session = AskSession(user_id="other-user")
    session.add(other_session)
    session.commit()
    session.refresh(other_session)

    response = client.get(f"/ui/ask/panel?session_id={other_session.id}")

    assert response.status_code == 200
    assert "non trovata" in response.text.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_ai_ask.py::test_ask_panel_for_another_users_session_id_shows_not_found_notice -v`
Expected: FAIL — the route isn't scoped yet (no `current_user` dependency, so it 401s or 500s, or worse, actually renders the other user's session).

- [ ] **Step 3: Rewrite `app/routers/ai_ask.py`**

```python
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.ai.prompts import MAX_REELS_IN_CONTEXT
from app.ai.providers.base import AIProviderError
from app.auth import get_current_user
from app.db import get_session
from app.models import AskMessage, AskSession, Location, Reel, ReelType, User
from app.routers.categories import get_taxonomy
from app.routers.reels import _location_and_satellite_ids
from app.scoping import get_owned, user_query
from app.web import templates

ui_router = APIRouter(prefix="/ui/ask", tags=["ask-ui"])

logger = logging.getLogger("app.ai")

FALLBACK_ANSWER = "Errore nel contattare l'assistente, riprova."


def _scoped_reel_context(
    session: Session, user_id: str, location_id: Optional[str], category_key: Optional[str]
) -> tuple[list[dict], bool]:
    query = user_query(Reel, user_id)
    if location_id is not None:
        query = query.where(Reel.location_id.in_(_location_and_satellite_ids(session, user_id, location_id)))
    reels = session.exec(query.order_by(Reel.created_at)).all()

    if category_key is not None:
        matching_ids = set(
            session.exec(select(ReelType.reel_id).where(ReelType.type == category_key)).all()
        )
        reels = [r for r in reels if r.id in matching_ids]

    taxonomy = get_taxonomy(session, user_id)
    entries = []
    for r in reels:
        location = session.get(Location, r.location_id)
        type_keys = session.exec(select(ReelType.type).where(ReelType.reel_id == r.id)).all()
        entries.append({
            "place_name": location.name if location else "?",
            "categories": [taxonomy[t]["label"] for t in type_keys if t in taxonomy],
            "note": r.note or "",
            "link": r.link,
        })

    truncated = len(entries) > MAX_REELS_IN_CONTEXT
    return entries[:MAX_REELS_IN_CONTEXT], truncated


def _run_ask_turn(
    session: Session,
    user_id: str,
    session_id: Optional[str],
    location_id: Optional[str],
    category_key: Optional[str],
    message: str,
) -> AskSession:
    if session_id:
        ask_session = get_owned(session, AskSession, session_id, user_id)
        if ask_session is None:
            raise HTTPException(status_code=404, detail="Ask session not found")
        location_id = ask_session.location_id
        category_key = ask_session.category_key
    else:
        ask_session = AskSession(location_id=location_id, category_key=category_key, user_id=user_id)
        session.add(ask_session)
        session.commit()
        session.refresh(ask_session)

    session.add(AskMessage(session_id=ask_session.id, role="user", content=message))
    session.commit()

    history = session.exec(
        select(AskMessage).where(AskMessage.session_id == ask_session.id).order_by(AskMessage.created_at)
    ).all()
    api_messages = [{"role": m.role, "content": m.content} for m in history]

    reels, truncated = _scoped_reel_context(session, user_id, location_id, category_key)
    location = session.get(Location, location_id) if location_id else None
    location_name = location.name if location else None
    taxonomy = get_taxonomy(session, user_id)
    category_label = taxonomy[category_key]["label"] if category_key and category_key in taxonomy else None

    try:
        result = ai_client.ask(reels, location_name, category_label, truncated, api_messages)
        answer = result["answer"]
    except (AIProviderError, RuntimeError):
        logger.exception("ask_session=%s ask call failed", ask_session.id)
        answer = FALLBACK_ANSWER

    session.add(AskMessage(session_id=ask_session.id, role="assistant", content=answer))
    ask_session.updated_at = datetime.utcnow()
    session.add(ask_session)
    session.commit()

    return ask_session


def _session_message_label(first_message: str, max_len: int = 60) -> str:
    text = (first_message or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


def _session_scope_label(location_name: Optional[str], category_label: Optional[str]) -> str:
    return f"{location_name or 'Tutte le città'} — {category_label or 'Tutte le categorie'}"


def _list_ask_sessions(session: Session, user_id: str) -> list[dict]:
    sessions = session.exec(user_query(AskSession, user_id).order_by(AskSession.updated_at.desc())).all()
    taxonomy = get_taxonomy(session, user_id)
    summaries = []
    for s in sessions:
        first_message = session.exec(
            select(AskMessage.content)
            .where(AskMessage.session_id == s.id, AskMessage.role == "user")
            .order_by(AskMessage.created_at)
        ).first()
        location = session.get(Location, s.location_id) if s.location_id else None
        category_label = (
            taxonomy[s.category_key]["label"] if s.category_key and s.category_key in taxonomy else None
        )
        summaries.append({
            "id": s.id,
            "message_label": _session_message_label(first_message or ""),
            "scope_label": _session_scope_label(location.name if location else None, category_label),
            "date_label": s.updated_at.strftime("%d/%m/%Y %H:%M"),
        })
    return summaries


def _build_ask_chat_context(
    session: Session,
    user_id: str,
    ask_session_id: Optional[str],
    location_id: Optional[str],
    category_key: Optional[str],
    notice: Optional[str] = None,
) -> dict:
    history: list[dict] = []
    if ask_session_id:
        messages = session.exec(
            select(AskMessage).where(AskMessage.session_id == ask_session_id).order_by(AskMessage.created_at)
        ).all()
        history = [{"role": m.role, "text": m.content} for m in messages]

    hubs = session.exec(
        user_query(Location, user_id).where(Location.is_hub == True).order_by(Location.name)
    ).all()
    return {
        "session_id": ask_session_id or "",
        "location_id": location_id or "",
        "category_key": category_key or "",
        "hubs": hubs,
        "taxonomy": get_taxonomy(session, user_id),
        "history": history,
        "notice": notice,
        "sessions": _list_ask_sessions(session, user_id),
    }


@ui_router.get("/panel")
def ui_ask_panel(
    request: Request,
    session_id: str = "",
    location_id: str = "",
    category_key: str = "",
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if session_id:
        ask_session = get_owned(session, AskSession, session_id, current_user.id)
        if ask_session is None:
            context = _build_ask_chat_context(
                session, current_user.id, None, None, None,
                notice="Conversazione non trovata, ricomincia pure da qui.",
            )
            return templates.TemplateResponse(request, "partials/ask_chat.html", context)
        context = _build_ask_chat_context(
            session, current_user.id, ask_session.id, ask_session.location_id, ask_session.category_key
        )
        return templates.TemplateResponse(request, "partials/ask_chat.html", context)

    return templates.TemplateResponse(
        request,
        "partials/ask_chat.html",
        _build_ask_chat_context(session, current_user.id, None, location_id or None, category_key or None),
    )


@ui_router.post("/message")
def ui_ask_message(
    request: Request,
    session_id: str = Form(""),
    location_id: str = Form(""),
    category_key: str = Form(""),
    message: str = Form(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        ask_session = _run_ask_turn(
            session, current_user.id, session_id or None, location_id or None, category_key or None, message
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            context = _build_ask_chat_context(
                session, current_user.id, None, location_id or None, category_key or None,
                notice="Sessione scaduta, ricomincia pure da qui.",
            )
            return templates.TemplateResponse(request, "partials/ask_chat.html", context)
        raise

    return templates.TemplateResponse(
        request,
        "partials/ask_chat.html",
        _build_ask_chat_context(
            session, current_user.id, ask_session.id, ask_session.location_id, ask_session.category_key
        ),
    )


@ui_router.delete("/history/{session_id}")
def ui_ask_delete_history(
    request: Request,
    session_id: str,
    current_session_id: str = Form(""),
    location_id: str = Form(""),
    category_key: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ask_session = get_owned(session, AskSession, session_id, current_user.id)
    if ask_session is not None:
        for m in session.exec(select(AskMessage).where(AskMessage.session_id == session_id)).all():
            session.delete(m)
        session.delete(ask_session)
        session.commit()

    if current_session_id == session_id:
        context = _build_ask_chat_context(session, current_user.id, None, location_id or None, category_key or None)
    elif current_session_id:
        still_open = get_owned(session, AskSession, current_session_id, current_user.id)
        if still_open is not None:
            context = _build_ask_chat_context(
                session, current_user.id, still_open.id, still_open.location_id, still_open.category_key
            )
        else:
            context = _build_ask_chat_context(session, current_user.id, None, location_id or None, category_key or None)
    else:
        context = _build_ask_chat_context(session, current_user.id, None, location_id or None, category_key or None)

    return templates.TemplateResponse(request, "partials/ask_chat.html", context)
```

- [ ] **Step 4: Fix the remaining fixtures in `tests/test_ai_ask.py`**

Same mechanical rule: every `Location(`/`Reel(`/`Category(` call gets `user_id=test_user_id` added, every enclosing test function gets `test_user_id` added as a parameter. Run `grep -n "Location(\|Reel(\|Category(" tests/test_ai_ask.py` for the exact line list (gathered earlier: lines 17, 21-22, 29-31, 41, 43-44, 48-49, 67-68, 75-76, 89, 94, 104, 129-130, 205, 261-262, 351, 353, 378, 397-398, 471).

- [ ] **Step 5: Run the test file**

Run: `uv run pytest tests/test_ai_ask.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/routers/ai_ask.py tests/test_ai_ask.py
git commit -m "feat: scope AI ask chat sessions to the current user"
```

---

## Task 17: Scope `app/routers/note_regeneration.py` and `app/routers/instagram_import.py`

**Files:**
- Modify: `app/routers/note_regeneration.py` (whole file)
- Modify: `app/routers/instagram_import.py` (`ui_ai_import` only — the rest of the file is pure yt-dlp/transcription plumbing, no DB access)
- Modify: `tests/test_note_regeneration.py`, `tests/test_instagram_import_ui.py`
- Test: `tests/test_note_regeneration.py`, `tests/test_instagram_import_ui.py`

**Interfaces:**
- Consumes: `get_taxonomy` (Task 10), `_serialize_reel` (Task 13), `_build_ai_chat_context` (Task 15).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_note_regeneration.py -- add
def test_regenerate_note_for_another_users_reel_returns_404(client, session):
    from app.models import Location, Reel

    other_hub = Location(name="Other Hub", is_hub=True, user_id="other-user")
    session.add(other_hub)
    session.commit()
    session.refresh(other_hub)
    other_reel = Reel(
        link="x", location_id=other_hub.id, caption="test", user_id="other-user"
    )
    session.add(other_reel)
    session.commit()
    session.refresh(other_reel)

    response = client.put(f"/ui/reels/{other_reel.id}/regenerate-note")

    assert response.status_code == 404
```

```python
# tests/test_instagram_import_ui.py -- add
def test_import_duplicate_warning_does_not_use_another_users_reel(client, session, monkeypatch):
    from app.models import Location, Reel

    other_hub = Location(name="Other Hub", is_hub=True, user_id="other-user")
    session.add(other_hub)
    session.commit()
    session.refresh(other_hub)
    session.add(
        Reel(link="https://instagram.com/reel/abc", location_id=other_hub.id, note="segreto", user_id="other-user")
    )
    session.commit()

    response = client.post("/ui/ai/import", data={"link": "https://instagram.com/reel/abc"})

    assert "segreto" not in response.text
    assert "Other Hub" not in response.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_note_regeneration.py tests/test_instagram_import_ui.py -v`
Expected: FAIL — routes aren't scoped yet.

- [ ] **Step 3: Rewrite `app/routers/note_regeneration.py`**

Keep `MAX_CONCURRENT_REGENERATE_CALLS`, `_regen_source_message`, `_regenerate_note` exactly as they are. Update the rest:

```python
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.auth import get_current_user
from app.db import get_session
from app.models import Location, Reel, User
from app.routers.ai_categorize import _categorize_new_session_message
from app.routers.categories import get_taxonomy
from app.routers.reels import _serialize_reel
from app.scoping import get_owned, user_query
from app.web import templates

ui_router = APIRouter(prefix="/ui/reels", tags=["note-regeneration"])

logger = logging.getLogger("app.ai")

MAX_CONCURRENT_REGENERATE_CALLS = 5


def _regen_source_message(reel: Reel) -> Optional[str]:
    parts = []
    if reel.caption:
        parts.append(f"Didascalia: {reel.caption}")
    if reel.transcript:
        parts.append(f"Trascrizione audio: {reel.transcript}")
    if parts:
        return "\n\n".join(parts)
    if reel.note:
        return f"Nota attuale: {reel.note}"
    return None


def _hub_names_and_category_labels(session: Session, user_id: str) -> tuple[list[str], dict[str, str]]:
    hubs = session.exec(user_query(Location, user_id).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]
    taxonomy = get_taxonomy(session, user_id)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}
    return hub_names, category_labels


def _regenerate_note(
    reel: Reel, hub_names: list[str], category_labels: dict[str, str]
) -> bool:
    source = _regen_source_message(reel)
    if source is None:
        return False
    message = f"Link: {reel.link}\nDescrizione: {source}"
    result = _categorize_new_session_message(message, hub_names, category_labels)
    if result.get("question") or not result.get("note"):
        return False
    reel.note = result["note"]
    return True


@ui_router.put("/{reel_id}/regenerate-note")
def ui_regenerate_reel_note(
    request: Request,
    reel_id: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    reel = get_owned(session, Reel, reel_id, current_user.id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    hub_names, category_labels = _hub_names_and_category_labels(session, current_user.id)
    updated = _regenerate_note(reel, hub_names, category_labels)
    if updated:
        session.add(reel)
    session.commit()
    session.refresh(reel)

    card_html = templates.get_template("partials/_reel_card.html").render(
        reel=_serialize_reel(session, reel),
        taxonomy=get_taxonomy(session, current_user.id),
        regen_error=None if updated else "Non sono riuscito a rigenerare la nota, riprova.",
    )
    return HTMLResponse(card_html)


@ui_router.post("/regenerate-notes")
def ui_regenerate_all_notes(
    request: Request, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)
):
    reels = session.exec(user_query(Reel, current_user.id)).all()
    hub_names, category_labels = _hub_names_and_category_labels(session, current_user.id)

    regenerable = [r for r in reels if _regen_source_message(r) is not None]
    skipped = len(reels) - len(regenerable)
    messages = [
        f"Link: {r.link}\nDescrizione: {_regen_source_message(r)}" for r in regenerable
    ]

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REGENERATE_CALLS) as executor:
        results = list(
            executor.map(
                lambda m: _categorize_new_session_message(m, hub_names, category_labels),
                messages,
            )
        )

    updated = 0
    failed = 0
    for reel, result in zip(regenerable, results):
        if result.get("question") or not result.get("note"):
            failed += 1
            continue
        reel.note = result["note"]
        session.add(reel)
        updated += 1
    session.commit()

    summary = (
        f"{updated} nota/e aggiornata/e, {skipped} saltata/e (nessun testo disponibile), "
        f"{failed} fallita/e."
    )
    return HTMLResponse(f'<p class="ai-notice">{summary}</p>')
```

- [ ] **Step 4: Update `app/routers/instagram_import.py`**

Add `get_current_user`/`get_session`/`User`/`Session` to the imports and the `current_user`/`session` dependencies to `ui_ai_import`, then pass `current_user.id` to `find_duplicate_reel` and `_build_ai_chat_context`:

```python
from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session

from app.auth import get_current_user
from app.db import get_session
from app.ingest import instagram, transcribe
from app.models import Location, User
from app.reel_links import find_duplicate_reel
from app.routers.ai_categorize import _build_ai_chat_context
from app.web import templates
```

```python
@router.post("/import")
def ui_ai_import(
    request: Request,
    link: str = Form(...),
    confirm_duplicate: str = Form(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not _is_instagram_link(link):
        context = _build_ai_chat_context(session, current_user.id, None, link, notice=NOT_INSTAGRAM_NOTICE)
        return templates.TemplateResponse(request, "partials/ai_chat.html", context)

    if confirm_duplicate != "true":
        duplicate = find_duplicate_reel(session, link, current_user.id)
        if duplicate is not None:
            existing_location = session.get(Location, duplicate.location_id)
            context = _build_ai_chat_context(
                session,
                current_user.id,
                None,
                link,
                duplicate_warning={
                    "existing_location_name": existing_location.name if existing_location else "?",
                    "existing_note": duplicate.note,
                    "link": link,
                },
            )
            return templates.TemplateResponse(request, "partials/ai_chat.html", context)

    prefill_message = ""
    import_caption = ""
    import_transcript = ""
    notice = None
    try:
        result = _run_import_with_timeout(link, IMPORT_TIMEOUT_SECONDS)
        prefill_message = _build_prefill_message(result)
        import_caption = result.caption or ""
        import_transcript = result.transcript or ""
    except instagram.InstagramFetchError:
        logger.exception("instagram fetch failed for link=%s", link)
        notice = FETCH_FAILED_NOTICE
    except _ImportTimeout:
        logger.warning("instagram import timed out for link=%s", link)
        notice = TIMEOUT_NOTICE
    except Exception:
        logger.exception("unexpected error during instagram import for link=%s", link)
        notice = FETCH_FAILED_NOTICE

    context = _build_ai_chat_context(session, current_user.id, None, link, notice=notice)
    context["prefill_message"] = prefill_message
    context["caption"] = import_caption
    context["transcript"] = import_transcript
    return templates.TemplateResponse(request, "partials/ai_chat.html", context)
```

Everything above this function in the file (`_is_instagram_link`, `ImportResult`, `_build_prefill_message`, `_run_import`, `_run_import_with_timeout`, `_ImportTimeout`, the module constants) stays exactly as it is — none of it touches the database.

- [ ] **Step 5: Fix the remaining fixtures in `tests/test_note_regeneration.py` and `tests/test_instagram_import_ui.py`**

Same mechanical rule: every `Location(`/`Reel(` call gets `user_id=test_user_id` added, every enclosing test function gets `test_user_id` added as a parameter. Run `grep -n "Location(\|Reel(" tests/test_note_regeneration.py tests/test_instagram_import_ui.py` for the exact line lists.

- [ ] **Step 6: Run both test files**

Run: `uv run pytest tests/test_note_regeneration.py tests/test_instagram_import_ui.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/routers/note_regeneration.py app/routers/instagram_import.py tests/test_note_regeneration.py tests/test_instagram_import_ui.py
git commit -m "feat: scope note regeneration and Instagram import to the current user"
```

---

## Task 18: Fix the last cross-cutting UI fragment test file

**Files:**
- Modify: `tests/test_ui_fragments.py`
- Test: `tests/test_ui_fragments.py`

**Interfaces:**
- None — this task only touches test fixtures. By this point every route `tests/test_ui_fragments.py` exercises (`/ui/map`, `/ui/reels`, `/ui/categories`, etc.) is already scoped by Tasks 11-17; this task just updates the one remaining file's direct model construction so its fixtures land in the logged-in test user's data.

- [ ] **Step 1: Apply the mechanical fix**

Same rule as every prior test-fixture task: every `Location(`/`Reel(`/`Category(` call in `tests/test_ui_fragments.py` gets `user_id=test_user_id` added, every enclosing test function gets `test_user_id` added as a parameter (alongside its existing `client`/`session` parameters). Run `grep -n "Location(\|Reel(\|Category(" tests/test_ui_fragments.py` for the exact line list (gathered earlier while writing this plan — lines 20, 24, 41, 55-56, 71-72, 79, 95, 99, 113-114, 119, 131, 135, 145, 147, 158, 176, 190, 194, 205-206, 213-214, 226, 231, 236, 238, 255, 259, 268, 270, 273, 277, 294-295, 301, 319, 323, 336, 340, 358, 362, 370, 374, 383, 389, 398, 402, 411, 413-414, 418-419, 425-426).

- [ ] **Step 2: Run the test file to verify it fails first, as a sanity check that the fixtures were actually exercising scoped routes**

Run: `git stash -- tests/test_ui_fragments.py && uv run pytest tests/test_ui_fragments.py -v; git stash pop`
Expected: FAIL (confirms the routes do reject/empty-out unscoped fixture data before the fix — if everything already passed without `user_id`, something upstream silently stopped scoping, which would be a real bug to chase down rather than paper over here).

- [ ] **Step 3: Run the test file after the fix**

Run: `uv run pytest tests/test_ui_fragments.py -v`
Expected: PASS

- [ ] **Step 4: Confirm `tests/test_reel_type_matching.py`, `tests/test_location_matching.py`'s helper tests outside Task 8's additions, and `tests/test_models.py` need no further changes**

These three files were checked during this plan's design: `test_reel_type_matching.py` exercises `reel_ids_matching_types` directly against bare `Reel`/`ReelType` rows with no `user_id` set — that function was deliberately left unscoped (Task 10's note) since callers already scope the reel list they intersect against, so these tests need no change. `test_models.py` only needed the one `Category` fix already made in Task 3. Run them now purely as a confirmation, not expecting any edits:

Run: `uv run pytest tests/test_reel_type_matching.py tests/test_location_matching.py tests/test_models.py -v`
Expected: PASS, with zero diffs needed in this task.

- [ ] **Step 5: Commit**

```bash
git add tests/test_ui_fragments.py
git commit -m "test: scope the remaining UI fragment fixtures to the test user"
```

---

## Task 19: End-to-end isolation tests and full-suite verification

**Files:**
- Create: `tests/test_multiuser_isolation.py`
- Modify: `tests/conftest.py` (add a second logged-in client fixture for a second user)
- Test: `tests/test_multiuser_isolation.py`, then the entire suite

**Interfaces:**
- Consumes: everything built in Tasks 1-18.
- Produces: `tests/conftest.py` gains a `second_user_client` fixture — a `TestClient` logged in as a second, independently-seeded user — used only by this task's isolation tests.

This is the test the whole plan has been building toward: two real user accounts, created the same way `scripts/create_user.py` creates them, each exercising the app end-to-end through its actual HTTP routes (not direct DB manipulation), confirming neither ever sees the other's data.

- [ ] **Step 1: Add the second-user fixture to `tests/conftest.py`**

```python
@pytest.fixture(name="second_user_client")
def second_user_client_fixture(session: Session):
    from app.auth import hash_password
    from app.models import User

    session.add(User(username="seconduser", password_hash=hash_password("secondpass")))
    session.commit()

    client = _build_client(session)
    client.post("/login", data={"username": "seconduser", "password": "secondpass"})
    yield client
    from app.main import app

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Write the isolation tests**

```python
# tests/test_multiuser_isolation.py
def test_locations_created_by_one_user_are_invisible_to_another(client, second_user_client):
    client.post(
        "/api/locations",
        json={"name": "User A's Secret Hub", "is_hub": True, "lat": 1.0, "lon": 2.0},
    )

    response = second_user_client.get("/api/locations")

    assert "User A's Secret Hub" not in {loc["name"] for loc in response.json()}


def test_reels_created_by_one_user_are_invisible_to_another(client, second_user_client):
    hub_response = client.post(
        "/api/locations", json={"name": "A's Hub", "is_hub": True, "lat": 1.0, "lon": 2.0}
    )
    hub_id = hub_response.json()["id"]
    client.post(
        "/api/reels",
        json={"link": "https://instagram.com/reel/secret", "location_id": hub_id, "note": "segreto di A"},
    )

    response = second_user_client.get("/api/reels")

    assert "segreto di A" not in {r.get("note") for r in response.json()}


def test_categories_created_by_one_user_are_invisible_to_another_even_with_same_label(
    client, second_user_client
):
    client.post("/api/categories", json={"label": "Cibo", "icon": "🍜"})
    second_user_client.post("/api/categories", json={"label": "Cibo", "icon": "🍔"})

    a_categories = {c["icon"] for c in client.get("/api/categories").json() if c["key"] == "cibo"}
    b_categories = {c["icon"] for c in second_user_client.get("/api/categories").json() if c["key"] == "cibo"}

    assert a_categories == {"🍜"}
    assert b_categories == {"🍔"}


def test_fetching_another_users_reel_by_id_returns_404_not_403(client, second_user_client):
    hub_response = client.post(
        "/api/locations", json={"name": "A's Hub", "is_hub": True, "lat": 1.0, "lon": 2.0}
    )
    hub_id = hub_response.json()["id"]
    reel_response = client.post(
        "/api/reels", json={"link": "https://instagram.com/reel/x", "location_id": hub_id}
    )
    reel_id = reel_response.json()["id"]

    response = second_user_client.put(
        f"/api/reels/{reel_id}",
        json={"link": "https://instagram.com/reel/y", "location_id": hub_id, "types": []},
    )

    assert response.status_code == 404


def test_map_export_and_audit_views_do_not_leak_across_users(client, second_user_client):
    client.post("/api/locations", json={"name": "A's Secret Place", "is_hub": True, "lat": 1.0, "lon": 2.0})

    map_response = second_user_client.get("/api/map")
    export_response = second_user_client.get("/api/export/markdown")
    audit_response = second_user_client.get("/ui/audit/scan")

    assert "A's Secret Place" not in {loc["name"] for loc in map_response.json()}
    assert "A's Secret Place" not in export_response.text
    assert "A's Secret Place" not in audit_response.text


def test_each_new_user_gets_their_own_seeded_hubs_and_categories(client, second_user_client):
    a_locations = client.get("/api/locations").json()
    b_locations = second_user_client.get("/api/locations").json()

    assert len(a_locations) == 20
    assert len(b_locations) == 20
    # Different rows (different ids), not the same 20 shared between both users.
    assert {loc["id"] for loc in a_locations}.isdisjoint({loc["id"] for loc in b_locations})
```

- [ ] **Step 3: Run the new isolation test file**

Run: `uv run pytest tests/test_multiuser_isolation.py -v`
Expected: PASS — if anything fails here, it means a query site was missed in Tasks 10-17; go back and find the unscoped `select(...)` or `session.get(...)` call responsible (grep `app/` for `select(Location\|select(Reel\|select(Category\|select(AiSession\|select(AskSession\|session.get(Location\|session.get(Reel\|session.get(Category\|session.get(AiSession\|session.get(AskSession` and confirm every remaining hit is either inside `app/scoping.py` itself, or reaches a row only through an already-ownership-checked parent per this plan's Global Constraints/Review Focus reasoning).

- [ ] **Step 4: Run the entire test suite**

Run: `uv run pytest -v`
Expected: PASS, all files green — every test file in the repository has now been touched by one of Tasks 1-19.

- [ ] **Step 5: Manual smoke test of the migration path against a throwaway copy of real data**

This step is not automated — it exercises the actual startup path (`create_db_and_tables()` via `app.main`'s `lifespan`), which the test suite deliberately never runs (Task 4, Step 6's note). Run, from the project root:

```bash
cp data/japan_reels.db /tmp/migration-smoke-test.db
REEL_DB_PATH=/tmp/migration-smoke-test.db AUTH_USERNAME=owner AUTH_PASSWORD=ownerpass SESSION_SECRET_KEY=smoke-test uv run python -c "
from app import db
db.DB_PATH = '/tmp/migration-smoke-test.db'
db.DATABASE_URL = f'sqlite:////tmp/migration-smoke-test.db'
db.engine = db.create_engine(db.DATABASE_URL, connect_args={'check_same_thread': False})
db.create_db_and_tables()
from sqlmodel import Session, select
from app.models import Location, User
with Session(db.engine) as session:
    users = session.exec(select(User)).all()
    print('users:', [u.username for u in users])
    print('locations with user_id set:', len(session.exec(select(Location).where(Location.user_id != None)).all()))
    print('locations with user_id still NULL:', len(session.exec(select(Location).where(Location.user_id == None)).all()))
"
rm /tmp/migration-smoke-test.db
```

Expected output: exactly one user named `owner`, every existing `Location` row has `user_id` set (none `NULL`), and running the same command a second time (before deleting the temp file) produces identical output with no new user created. **This operates on a throwaway copy — never point `REEL_DB_PATH` at `data/japan_reels.db` itself for this check.**

- [ ] **Step 6: Final commit**

```bash
git add tests/conftest.py tests/test_multiuser_isolation.py
git commit -m "test: add end-to-end cross-user isolation coverage"
```

---
