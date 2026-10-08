import os
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.models import new_uuid

DB_PATH = os.environ.get("REEL_DB_PATH", "data/japan_reels.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Columns added to tables that already shipped on existing deployments.
# create_all() only creates missing tables, never alters existing ones, so
# any column added to a SQLModel class after its table first shipped needs
# an entry here or it will silently never exist on an upgraded DB.
_ADDITIVE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "location": [("geocode_confidence", "TEXT"), ("user_id", "TEXT")],
    "reel": [("caption", "TEXT"), ("transcript", "TEXT"), ("user_id", "TEXT")],
    "aisession": [("user_id", "TEXT")],
    "asksession": [("user_id", "TEXT")],
}


def _ensure_columns(target_engine: Engine) -> None:
    with target_engine.begin() as conn:
        for table, columns in _ADDITIVE_COLUMNS.items():
            table_exists = conn.execute(
                text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :name"),
                {"name": table},
            ).first()
            if not table_exists:
                continue
            existing = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
            }
            for name, col_type in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"))


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
    # Deferred: app.auth now imports app.db.get_session (Task 5), so a
    # module-level `from app.auth import hash_password` here would create an
    # import cycle. Importing at call time, where it's actually used, avoids it.
    from app.auth import hash_password

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


def get_session():
    with Session(engine) as session:
        yield session
