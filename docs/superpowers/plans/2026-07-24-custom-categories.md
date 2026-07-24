# Custom Categories Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed `app/taxonomy.py` constant with a user-editable `Category` table, and update every consumer (manual reel form, map filter chips, reel-list filter, AI schema/prompt) to read categories from the database at request time instead of a static import.

**Architecture:** A new `Category` model (`app/models.py`) with a stable, auto-generated slug `key` as primary key. A new `app/routers/categories.py` owns both the DB-reading helpers (`get_taxonomy`, `get_valid_type_keys`, `slugify`) and the category CRUD routes (JSON `/api/categories` + HTMX `/ui/categories`), following this app's existing pattern of routers exposing helpers that other routers import cross-module (e.g. `ai_categorize.py` already imports from `reels.py`). Every existing call site that imports `TAXONOMY`/`VALID_TYPES` switches to calling `get_taxonomy(session)`/`get_valid_type_keys(session)` with the current request's session. The AI prompt/schema builders stop being module-level constants and become functions parameterized on the current categories, mirroring how `hub_names` is already recomputed fresh on every turn.

**Tech Stack:** FastAPI, SQLModel/SQLite, Jinja2 + HTMX (unchanged from the rest of the app).

## Global Constraints

- All user-facing text is in Italian (existing convention throughout `app/templates`).
- No new client-side JavaScript — HTMX-only interactivity, consistent with the rest of the app.
- A category's `key` is generated once at creation from `label` via `slugify()` and never changes afterward, even when `label`/`icon`/`color` are later edited — this is what keeps existing `ReelType` rows and the AI's historical proposals valid across a rename.
- Deleting a category removes only the matching `ReelType` rows (the tag) from reels that had it; the `Reel` itself and any other type tags it has are untouched (user's explicit decision — no "block if in use" behavior here, unlike `Location` deletion).
- No manual category re-ordering, no icon picker/curated palette, no protection against deleting the last remaining category — out of scope per the approved design (`docs/superpowers/specs/2026-07-24-custom-categories-design.md` §7).
- This project has no DB migrations; schema changes require deleting `data/*.db` to pick up the new `Category` table (existing project policy, unchanged by this plan).
- Reference spec: `docs/superpowers/specs/2026-07-24-custom-categories-design.md`.

---

## File Structure

- Modify `app/models.py` — add `Category`; add `foreign_key="category.key"` to `ReelType.type`.
- Modify `app/seed.py` — add default category seeding (independent guard from location seeding).
- Create `app/routers/categories.py` — `slugify`, `get_taxonomy`, `get_valid_type_keys`, JSON API (`router`), HTMX UI (`ui_router`).
- Create `app/templates/partials/category_list.html`, `app/templates/partials/category_edit_row.html`, `app/templates/categories.html`.
- Modify `app/templates/base.html` — add header nav (Home / Gestisci categorie).
- Modify `app/main.py` — register the new routers, add the `/categories` page route.
- Modify `app/routers/reels.py`, `app/routers/map.py` — swap `TAXONOMY`/`VALID_TYPES` imports for `get_taxonomy`/`get_valid_type_keys` calls.
- Modify `app/ai/prompts.py`, `app/ai/client.py` — schema/prompt become functions parameterized on current categories instead of module-level constants built from a static import.
- Modify `app/routers/ai_categorize.py` — fetch categories per-turn (like `hub_names` already is) and pass them through.
- Delete `app/taxonomy.py`, `tests/test_taxonomy.py` (final task, once nothing imports it).
- New `tests/test_categories_api.py`, `tests/test_categories_ui.py`.
- Modify `tests/test_seed.py`, `tests/test_models.py`, `tests/test_reels_api.py`, `tests/test_ui_fragments.py`, `tests/test_ai_prompts.py`, `tests/test_ai_client.py`, `tests/test_ai_categorize.py`, `tests/test_ai_ui.py`.

---

### Task 1: `Category` model, seed data, and cleanup of the old taxonomy test

**Files:**
- Modify: `app/models.py`
- Modify: `app/seed.py`
- Modify: `tests/test_seed.py`
- Modify: `tests/test_models.py`
- Delete: `tests/test_taxonomy.py`

**Interfaces:**
- Produces: `Category(SQLModel, table=True)` with fields `key: str` (primary key), `label: str`, `icon: str`, `color: str`, `created_at: datetime`. `ReelType.type` now declares `foreign_key="category.key"` (SQLite doesn't enforce this — same as every other FK in this app — but it documents the relationship, matching `Reel.location_id`).
- Produces: `seed_if_empty(session)` also seeds 7 default `Category` rows (same keys/labels/icons/colors as the old `TAXONOMY` constant) the first time it runs, independently of whether locations were already seeded.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py` (after the existing `test_create_ai_session_with_messages`):

```python
def test_create_category():
    from app.models import Category

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        category = Category(key="food", label="Cibo", icon="🍜", color="#A63A2E")
        session.add(category)
        session.commit()
        session.refresh(category)

        assert category.key == "food"
        assert category.label == "Cibo"
        assert isinstance(category.created_at, datetime)
```

Replace the full contents of `tests/test_seed.py` with:

```python
from sqlmodel import SQLModel, Session, create_engine, select

from app.models import Category, Location
from app.seed import seed_if_empty


def test_seed_if_empty_creates_hubs_and_satellites():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_if_empty(session)

        hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
        satellites = session.exec(select(Location).where(Location.is_hub == False)).all()

        assert len(hubs) == 9
        assert len(satellites) == 10
        tokyo = next(h for h in hubs if h.name == "Tokyo / Kanto")
        nikko = next(s for s in satellites if s.name == "Nikko")
        assert nikko.parent_id == tokyo.id


def test_seed_if_empty_is_idempotent():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_if_empty(session)
        seed_if_empty(session)
        all_locations = session.exec(select(Location)).all()
        assert len(all_locations) == 19


def test_seed_if_empty_creates_default_categories():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_if_empty(session)

        categories = session.exec(select(Category)).all()
        assert {c.key for c in categories} == {
            "food", "culture", "nature", "shopping", "stay", "transport", "experience",
        }
        food = next(c for c in categories if c.key == "food")
        assert food.label == "Cibo"
        assert food.icon == "🍜"
        assert food.color == "#A63A2E"


def test_seed_if_empty_categories_are_idempotent():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_if_empty(session)
        seed_if_empty(session)
        categories = session.exec(select(Category)).all()
        assert len(categories) == 7
```

Delete `tests/test_taxonomy.py` (it tests `app/taxonomy.py`, which no longer exists once this feature is complete):

```bash
rm tests/test_taxonomy.py
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py tests/test_seed.py -v`
Expected: FAIL — `Category` doesn't exist yet in `app/models.py`, and `seed_if_empty` doesn't create any.

- [ ] **Step 3: Add the model**

Replace the full contents of `app/models.py` with:

```python
import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


def new_uuid() -> str:
    return str(uuid.uuid4())


class Location(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = Field(default=None, foreign_key="location.id")
    lat: Optional[float] = None
    lon: Optional[float] = None


class Reel(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    link: str
    location_id: str = Field(foreign_key="location.id")
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Category(SQLModel, table=True):
    key: str = Field(primary_key=True)
    label: str
    icon: str
    color: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReelType(SQLModel, table=True):
    reel_id: str = Field(foreign_key="reel.id", primary_key=True)
    type: str = Field(foreign_key="category.key", primary_key=True)


class AiSession(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AiMessage(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    session_id: str = Field(foreign_key="aisession.id")
    role: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: Add category seeding**

Replace the full contents of `app/seed.py` with:

```python
from sqlmodel import Session, select

from app.models import Category, Location

HUBS = [
    ("Sapporo / Hokkaido", 43.0621, 141.3544),
    ("Sendai / Tohoku", 38.2682, 140.8694),
    ("Tokyo / Kanto", 35.6762, 139.6503),
    ("Nagoya / Chubu", 35.1815, 136.9066),
    ("Kyoto - Osaka / Kansai", 34.85, 135.60),
    ("Hiroshima / Chugoku", 34.3853, 132.4553),
    ("Matsuyama / Shikoku", 33.8392, 132.7657),
    ("Fukuoka / Kyushu", 33.5904, 130.4017),
    ("Okinawa", 26.2124, 127.6809),
]

SATELLITES = [
    ("Nikko", "Tokyo / Kanto", 36.7199, 139.6982),
    ("Kamakura", "Tokyo / Kanto", 35.3193, 139.5466),
    ("Hakone", "Tokyo / Kanto", 35.2323, 139.1069),
    ("Kawagoe", "Tokyo / Kanto", 35.9251, 139.4855),
    ("Nara", "Kyoto - Osaka / Kansai", 34.6851, 135.8048),
    ("Uji", "Kyoto - Osaka / Kansai", 34.8845, 135.7996),
    ("Himeji", "Kyoto - Osaka / Kansai", 34.8154, 134.6853),
    ("Miyajima", "Hiroshima / Chugoku", 34.2969, 132.3197),
    ("Otaru", "Sapporo / Hokkaido", 43.1907, 140.9947),
    ("Dazaifu", "Fukuoka / Kyushu", 33.5147, 130.5350),
]

DEFAULT_CATEGORIES = [
    ("food", "Cibo", "🍜", "#A63A2E"),
    ("culture", "Cultura", "⛩️", "#35496B"),
    ("nature", "Natura", "🌸", "#7A8F5E"),
    ("shopping", "Shopping", "🛍️", "#B08D57"),
    ("stay", "Alloggio", "🏨", "#5B4636"),
    ("transport", "Trasporti", "🚄", "#1F2C47"),
    ("experience", "Esperienza", "🎡", "#8E5572"),
]


def seed_if_empty(session: Session) -> None:
    if session.exec(select(Location)).first() is None:
        hub_by_name: dict[str, Location] = {}
        for name, lat, lon in HUBS:
            hub = Location(name=name, is_hub=True, lat=lat, lon=lon)
            session.add(hub)
            session.flush()
            hub_by_name[name] = hub

        for name, hub_name, lat, lon in SATELLITES:
            parent = hub_by_name[hub_name]
            session.add(Location(name=name, is_hub=False, parent_id=parent.id, lat=lat, lon=lon))

        session.commit()

    if session.exec(select(Category)).first() is None:
        for key, label, icon, color in DEFAULT_CATEGORIES:
            session.add(Category(key=key, label=label, icon=icon, color=color))
        session.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py tests/test_seed.py -v`
Expected: PASS (4 + 4 tests)

Run: `uv run pytest -v`
Expected: PASS (full suite minus the deleted `test_taxonomy.py` — `app/taxonomy.py` itself is untouched in this task, so every existing consumer still works unchanged)

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/seed.py tests/test_seed.py tests/test_models.py
git rm tests/test_taxonomy.py
git commit -m "feat: add Category model and seed the default categories"
```

---

### Task 2: `app/routers/categories.py` — helpers + JSON API

**Files:**
- Create: `app/routers/categories.py`
- Modify: `app/main.py`
- Create: `tests/test_categories_api.py`

**Interfaces:**
- Consumes: `Category`, `ReelType` (`app/models.py`, Task 1).
- Produces: `slugify(label: str) -> str`; `get_taxonomy(session: Session) -> dict[str, dict]` (shape `{key: {"label", "icon", "color"}}`, drop-in replacement for the old `TAXONOMY` constant); `get_valid_type_keys(session: Session) -> set[str]` (drop-in replacement for the old `VALID_TYPES` constant). Both take a `Session` and query fresh every call — no caching. Produces `router = APIRouter(prefix="/api/categories", ...)` with list/create/update/delete. These four names (`slugify`, `get_taxonomy`, `get_valid_type_keys`, `router`) are what Tasks 3-7 import.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_categories_api.py`:

```python
from sqlmodel import select

from app.models import Category, Location, Reel, ReelType


def test_list_categories_empty(client):
    response = client.get("/api/categories")
    assert response.status_code == 200
    assert response.json() == []


def test_list_categories_returns_seeded_rows(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/api/categories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["key"] == "food"
    assert data[0]["label"] == "Cibo"


def test_create_category_generates_slug_key(client):
    response = client.post(
        "/api/categories",
        json={"label": "Vita notturna", "icon": "🍿", "color": "#7A4B8A"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["key"] == "vita-notturna"
    assert data["label"] == "Vita notturna"
    assert data["icon"] == "🍿"
    assert data["color"] == "#7A4B8A"


def test_create_category_normalizes_accented_characters(client):
    response = client.post(
        "/api/categories",
        json={"label": "Città storica", "icon": "🏯", "color": "#35496B"},
    )
    assert response.status_code == 201
    assert response.json()["key"] == "citta-storica"


def test_create_category_rejects_duplicate_slug(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.post(
        "/api/categories",
        json={"label": "Food", "icon": "🍔", "color": "#000000"},
    )
    assert response.status_code == 409


def test_create_category_rejects_unslugifiable_label(client):
    response = client.post(
        "/api/categories",
        json={"label": "🎉🎉🎉", "icon": "🎉", "color": "#000000"},
    )
    assert response.status_code == 400


def test_update_category_changes_label_icon_color_not_key(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.put(
        "/api/categories/food",
        json={"label": "Cibo di strada", "icon": "🌭", "color": "#111111"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["key"] == "food"
    assert data["label"] == "Cibo di strada"
    assert data["icon"] == "🌭"
    assert data["color"] == "#111111"


def test_update_unknown_category_returns_404(client):
    response = client.put(
        "/api/categories/does-not-exist",
        json={"label": "X", "icon": "🍜", "color": "#000000"},
    )
    assert response.status_code == 404


def test_delete_category_removes_only_matching_reel_types(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.add(Category(key="culture", label="Cultura", icon="⛩️", color="#35496B"))
    session.commit()

    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    reel = Reel(link="https://instagram.com/reel/x", location_id=hub.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.add(ReelType(reel_id=reel.id, type="culture"))
    session.commit()

    response = client.delete("/api/categories/food")
    assert response.status_code == 204

    assert session.get(Category, "food") is None
    assert session.get(Category, "culture") is not None
    remaining_types = {
        t.type for t in session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    }
    assert remaining_types == {"culture"}
    assert session.get(Reel, reel.id) is not None


def test_delete_unknown_category_returns_404(client):
    response = client.delete("/api/categories/does-not-exist")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_categories_api.py -v`
Expected: FAIL — `/api/categories` doesn't exist yet (404s).

- [ ] **Step 3: Create the router with helpers and JSON API**

Create `app/routers/categories.py`:

```python
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Category, ReelType

router = APIRouter(prefix="/api/categories", tags=["categories"])


def slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def get_taxonomy(session: Session) -> dict[str, dict]:
    categories = session.exec(select(Category).order_by(Category.created_at)).all()
    return {c.key: {"label": c.label, "icon": c.icon, "color": c.color} for c in categories}


def get_valid_type_keys(session: Session) -> set[str]:
    return set(session.exec(select(Category.key)).all())


class CategoryPayload(BaseModel):
    label: str
    icon: str
    color: str


def _create_category(session: Session, label: str, icon: str, color: str) -> Category:
    key = slugify(label)
    if not key:
        raise HTTPException(status_code=400, detail="label must contain at least one letter or digit")
    if session.get(Category, key):
        raise HTTPException(status_code=409, detail=f"a category with key '{key}' already exists")
    category = Category(key=key, label=label, icon=icon, color=color)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _update_category(session: Session, key: str, label: str, icon: str, color: str) -> Category:
    category = session.get(Category, key)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    category.label = label
    category.icon = icon
    category.color = color
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _delete_category(session: Session, key: str) -> None:
    category = session.get(Category, key)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    for rt in session.exec(select(ReelType).where(ReelType.type == key)).all():
        session.delete(rt)
    session.delete(category)
    session.commit()


@router.get("")
def list_categories(session: Session = Depends(get_session)):
    return session.exec(select(Category).order_by(Category.created_at)).all()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryPayload, session: Session = Depends(get_session)):
    return _create_category(session, payload.label, payload.icon, payload.color)


@router.put("/{key}")
def update_category(key: str, payload: CategoryPayload, session: Session = Depends(get_session)):
    return _update_category(session, key, payload.label, payload.icon, payload.color)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(key: str, session: Session = Depends(get_session)):
    _delete_category(session, key)
```

- [ ] **Step 4: Register the router**

Replace the full contents of `app/main.py` with:

```python
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.routers import ai_categorize, categories, locations, map as map_router, reels
from app.seed import seed_if_empty
from app.web import templates

_ai_log_path = os.environ.get("AI_DEBUG_LOG_PATH", "data/ai_debug.log")
os.makedirs(os.path.dirname(_ai_log_path) or ".", exist_ok=True)
_ai_logger = logging.getLogger("app.ai")
_ai_logger.setLevel(logging.DEBUG)
if not _ai_logger.handlers:
    _ai_handler = logging.FileHandler(_ai_log_path)
    _ai_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _ai_logger.addHandler(_ai_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        seed_if_empty(session)
    yield


app = FastAPI(title="Japan Reel Organizer", lifespan=lifespan)
app.include_router(locations.router)
app.include_router(reels.router)
app.include_router(map_router.router)
app.include_router(map_router.ui_router)
app.include_router(reels.ui_router)
app.include_router(ai_categorize.router)
app.include_router(ai_categorize.ui_router)
app.include_router(categories.router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_categories_api.py -v`
Expected: PASS (10 tests)

Run: `uv run pytest -v`
Expected: PASS (full suite, no regressions)

- [ ] **Step 6: Commit**

```bash
git add app/routers/categories.py app/main.py tests/test_categories_api.py
git commit -m "feat: add category CRUD JSON API and taxonomy helpers"
```

---

### Task 3: HTMX UI for category management + page + nav

**Files:**
- Modify: `app/routers/categories.py`
- Create: `app/templates/partials/category_list.html`
- Create: `app/templates/partials/category_edit_row.html`
- Create: `app/templates/categories.html`
- Modify: `app/templates/base.html`
- Modify: `app/main.py`
- Create: `tests/test_categories_ui.py`

**Interfaces:**
- Consumes: `_create_category`, `_update_category`, `_delete_category`, `Category` (Task 2, same file).
- Produces: `ui_router = APIRouter(prefix="/ui/categories", ...)` with `GET ""`, `POST ""`, `GET "/{key}/edit"`, `POST "/{key}"`, `DELETE "/{key}"`. Renders `partials/category_list.html` (list + add form) and `partials/category_edit_row.html` (one inline edit row).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_categories_ui.py`:

```python
from app.models import Category


def test_ui_categories_list_renders_existing_categories(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/ui/categories")
    assert response.status_code == 200
    assert "Cibo" in response.text
    assert "🍜" in response.text
    assert "<form" in response.text


def test_ui_categories_create_and_rerenders_list(client, session):
    response = client.post(
        "/ui/categories",
        data={"label": "Vita notturna", "icon": "🍿", "color": "#7A4B8A"},
    )
    assert response.status_code == 200
    assert "Vita notturna" in response.text
    assert session.get(Category, "vita-notturna") is not None


def test_ui_categories_edit_form_renders_prefilled_row(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/ui/categories/food/edit")
    assert response.status_code == 200
    assert 'value="Cibo"' in response.text
    assert 'value="🍜"' in response.text


def test_ui_categories_edit_form_unknown_key_returns_404(client):
    response = client.get("/ui/categories/does-not-exist/edit")
    assert response.status_code == 404


def test_ui_categories_update_and_rerenders_list(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.post(
        "/ui/categories/food",
        data={"label": "Cibo di strada", "icon": "🌭", "color": "#111111"},
    )
    assert response.status_code == 200
    assert "Cibo di strada" in response.text
    assert session.get(Category, "food").label == "Cibo di strada"


def test_ui_categories_delete_removes_it_and_rerenders_list(client, session):
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.delete("/ui/categories/food")
    assert response.status_code == 200
    assert "Cibo" not in response.text
    assert session.get(Category, "food") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_categories_ui.py -v`
Expected: FAIL — `/ui/categories` routes don't exist yet (404s).

- [ ] **Step 3: Add the UI routes**

Replace the full contents of `app/routers/categories.py` with:

```python
import re
import unicodedata

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Category, ReelType
from app.web import templates

router = APIRouter(prefix="/api/categories", tags=["categories"])
ui_router = APIRouter(prefix="/ui/categories", tags=["categories-ui"])


def slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def get_taxonomy(session: Session) -> dict[str, dict]:
    categories = session.exec(select(Category).order_by(Category.created_at)).all()
    return {c.key: {"label": c.label, "icon": c.icon, "color": c.color} for c in categories}


def get_valid_type_keys(session: Session) -> set[str]:
    return set(session.exec(select(Category.key)).all())


class CategoryPayload(BaseModel):
    label: str
    icon: str
    color: str


def _create_category(session: Session, label: str, icon: str, color: str) -> Category:
    key = slugify(label)
    if not key:
        raise HTTPException(status_code=400, detail="label must contain at least one letter or digit")
    if session.get(Category, key):
        raise HTTPException(status_code=409, detail=f"a category with key '{key}' already exists")
    category = Category(key=key, label=label, icon=icon, color=color)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _update_category(session: Session, key: str, label: str, icon: str, color: str) -> Category:
    category = session.get(Category, key)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    category.label = label
    category.icon = icon
    category.color = color
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


def _delete_category(session: Session, key: str) -> None:
    category = session.get(Category, key)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    for rt in session.exec(select(ReelType).where(ReelType.type == key)).all():
        session.delete(rt)
    session.delete(category)
    session.commit()


@router.get("")
def list_categories(session: Session = Depends(get_session)):
    return session.exec(select(Category).order_by(Category.created_at)).all()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryPayload, session: Session = Depends(get_session)):
    return _create_category(session, payload.label, payload.icon, payload.color)


@router.put("/{key}")
def update_category(key: str, payload: CategoryPayload, session: Session = Depends(get_session)):
    return _update_category(session, key, payload.label, payload.icon, payload.color)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(key: str, session: Session = Depends(get_session)):
    _delete_category(session, key)


def _category_list_context(session: Session) -> dict:
    return {"categories": session.exec(select(Category).order_by(Category.created_at)).all()}


@ui_router.get("")
def ui_list_categories(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/category_list.html", _category_list_context(session))


@ui_router.post("")
def ui_create_category(
    request: Request,
    label: str = Form(...),
    icon: str = Form(...),
    color: str = Form(...),
    session: Session = Depends(get_session),
):
    _create_category(session, label, icon, color)
    return templates.TemplateResponse(request, "partials/category_list.html", _category_list_context(session))


@ui_router.get("/{key}/edit")
def ui_edit_category_form(request: Request, key: str, session: Session = Depends(get_session)):
    category = session.get(Category, key)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return templates.TemplateResponse(request, "partials/category_edit_row.html", {"category": category})


@ui_router.post("/{key}")
def ui_update_category(
    request: Request,
    key: str,
    label: str = Form(...),
    icon: str = Form(...),
    color: str = Form(...),
    session: Session = Depends(get_session),
):
    _update_category(session, key, label, icon, color)
    return templates.TemplateResponse(request, "partials/category_list.html", _category_list_context(session))


@ui_router.delete("/{key}")
def ui_delete_category(request: Request, key: str, session: Session = Depends(get_session)):
    _delete_category(session, key)
    return templates.TemplateResponse(request, "partials/category_list.html", _category_list_context(session))
```

- [ ] **Step 4: Add the templates**

Create `app/templates/partials/category_list.html`:

```html
<ul class="category-list">
    {% for category in categories %}
    <li id="category-{{ category.key }}">
        <span class="chip" style="border-color: {{ category.color }};">{{ category.icon }} {{ category.label }}</span>
        <button hx-get="/ui/categories/{{ category.key }}/edit" hx-target="#category-{{ category.key }}" hx-swap="outerHTML">Modifica</button>
        <button hx-delete="/ui/categories/{{ category.key }}" hx-target="#category-list" hx-swap="innerHTML">Elimina</button>
    </li>
    {% endfor %}
</ul>
<form hx-post="/ui/categories" hx-target="#category-list" hx-swap="innerHTML">
    <input type="text" name="label" placeholder="Nome categoria" required>
    <input type="text" name="icon" placeholder="Emoji" required>
    <input type="color" name="color" value="#A63A2E" required>
    <button type="submit">Aggiungi categoria</button>
</form>
```

Create `app/templates/partials/category_edit_row.html`:

```html
<li id="category-{{ category.key }}">
    <form hx-post="/ui/categories/{{ category.key }}" hx-target="#category-list" hx-swap="innerHTML">
        <input type="text" name="label" value="{{ category.label }}" required>
        <input type="text" name="icon" value="{{ category.icon }}" required>
        <input type="color" name="color" value="{{ category.color }}" required>
        <button type="submit">Salva</button>
        <button type="button" hx-get="/ui/categories" hx-target="#category-list" hx-swap="innerHTML">Annulla</button>
    </form>
</li>
```

Create `app/templates/categories.html`:

```html
{% extends "base.html" %}
{% block content %}
<section id="category-list" hx-get="/ui/categories" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento categorie...</p>
</section>
{% endblock %}
```

- [ ] **Step 5: Add the nav and the page route**

Replace the full contents of `app/templates/base.html` with:

```html
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Japan Reel Organizer</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@400;600&family=Zen+Kaku+Gothic+New:wght@400;500&family=JetBrains+Mono&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
    <link rel="stylesheet" href="/static/css/style.css">
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <script src="https://unpkg.com/htmx.org@1.9.12"></script>
    <script src="/static/js/map.js"></script>
</head>
<body>
    <header>
        <h1>Japan Reel Organizer</h1>
        <nav>
            <a href="/">Home</a>
            <a href="/categories">Gestisci categorie</a>
        </nav>
    </header>
    <main>
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

Replace the full contents of `app/main.py` with:

```python
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.routers import ai_categorize, categories, locations, map as map_router, reels
from app.seed import seed_if_empty
from app.web import templates

_ai_log_path = os.environ.get("AI_DEBUG_LOG_PATH", "data/ai_debug.log")
os.makedirs(os.path.dirname(_ai_log_path) or ".", exist_ok=True)
_ai_logger = logging.getLogger("app.ai")
_ai_logger.setLevel(logging.DEBUG)
if not _ai_logger.handlers:
    _ai_handler = logging.FileHandler(_ai_log_path)
    _ai_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _ai_logger.addHandler(_ai_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        seed_if_empty(session)
    yield


app = FastAPI(title="Japan Reel Organizer", lifespan=lifespan)
app.include_router(locations.router)
app.include_router(reels.router)
app.include_router(map_router.router)
app.include_router(map_router.ui_router)
app.include_router(reels.ui_router)
app.include_router(ai_categorize.router)
app.include_router(ai_categorize.ui_router)
app.include_router(categories.router)
app.include_router(categories.ui_router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/categories")
async def categories_page(request: Request):
    return templates.TemplateResponse(request, "categories.html", {})


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_categories_ui.py -v`
Expected: PASS (6 tests)

Run: `uv run pytest -v`
Expected: PASS (full suite, no regressions)

- [ ] **Step 7: Commit**

```bash
git add app/routers/categories.py app/templates/partials/category_list.html app/templates/partials/category_edit_row.html app/templates/categories.html app/templates/base.html app/main.py tests/test_categories_ui.py
git commit -m "feat: add category management UI page"
```

---

### Task 4: Migrate `app/routers/reels.py` to dynamic categories

**Files:**
- Modify: `app/routers/reels.py`
- Modify: `tests/test_reels_api.py`

**Interfaces:**
- Consumes: `get_taxonomy(session)`, `get_valid_type_keys(session)` from `app.routers.categories` (Task 2).
- No change to `reels.py`'s own exported names (`_is_safe_link`, `_reel_list_context`, routers) — only their internals swap from the static `TAXONOMY`/`VALID_TYPES` import to per-call DB queries.

- [ ] **Step 1: Update the tests ahead of the refactor**

In `tests/test_reels_api.py`, add the import and update the two tests that depend on `"food"` surviving type filtering, so they keep passing once filtering reads from the database. Replace the full contents of `tests/test_reels_api.py` with:

```python
from sqlmodel import select

from app.models import Category, Location, Reel, ReelType


def test_list_reels_with_types(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    reel = Reel(link="https://instagram.com/reel/1", location_id=hub.id, note="Ramen")
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    response = client.get("/api/reels")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["types"] == ["food"]


def test_filter_reels_by_location_id(client, session):
    hub_a = Location(name="Hub A", is_hub=True)
    hub_b = Location(name="Hub B", is_hub=True)
    session.add(hub_a)
    session.add(hub_b)
    session.commit()
    session.refresh(hub_a)
    session.refresh(hub_b)

    session.add(Reel(link="https://instagram.com/reel/a", location_id=hub_a.id))
    session.add(Reel(link="https://instagram.com/reel/b", location_id=hub_b.id))
    session.commit()

    response = client.get(f"/api/reels?location_id={hub_a.id}")
    data = response.json()
    assert len(data) == 1
    assert data[0]["location_id"] == hub_a.id


def test_filter_reels_by_type(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    reel_food = Reel(link="https://instagram.com/reel/food", location_id=hub.id)
    reel_culture = Reel(link="https://instagram.com/reel/culture", location_id=hub.id)
    session.add(reel_food)
    session.add(reel_culture)
    session.commit()
    session.refresh(reel_food)
    session.refresh(reel_culture)
    session.add(ReelType(reel_id=reel_food.id, type="food"))
    session.add(ReelType(reel_id=reel_culture.id, type="culture"))
    session.commit()

    response = client.get("/api/reels?type=food")
    data = response.json()
    assert len(data) == 1
    assert data[0]["link"] == "https://instagram.com/reel/food"


def test_create_reel_filters_invalid_types(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/api/reels",
        json={
            "link": "https://instagram.com/reel/new",
            "location_id": hub.id,
            "note": "Great ramen",
            "types": ["food", "not-a-real-type"],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["types"] == ["food"]
    assert data["note"] == "Great ramen"


def test_delete_reel(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    create_resp = client.post(
        "/api/reels",
        json={"link": "https://instagram.com/reel/gone", "location_id": hub.id, "types": ["food"]},
    )
    reel_id = create_resp.json()["id"]

    response = client.delete(f"/api/reels/{reel_id}")
    assert response.status_code == 204
    assert client.get("/api/reels").json() == []
    assert session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all() == []


def test_delete_missing_reel_returns_404(client):
    response = client.delete("/api/reels/does-not-exist")
    assert response.status_code == 404


def test_create_reel_rejects_javascript_link(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/api/reels",
        json={"link": "javascript:alert(1)", "location_id": hub.id},
    )
    assert response.status_code == 400
    assert session.exec(select(Reel)).all() == []
```

- [ ] **Step 2: Run tests to confirm they still pass before the refactor**

Run: `uv run pytest tests/test_reels_api.py -v`
Expected: PASS (all 7 tests) — this is a refactor, not new behavior: `app/routers/reels.py` still imports the old static `TAXONOMY`/`VALID_TYPES` at this point, which already contains `"food"` regardless of the `Category` row the updated tests now seed, so nothing changes yet. This confirms the test file edits in Step 1 didn't break anything by themselves, before the real change in Step 3.

- [ ] **Step 3: Migrate `reels.py`**

Replace the full contents of `app/routers/reels.py` with:

```python
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models import Location, Reel, ReelType
from app.routers.categories import get_taxonomy, get_valid_type_keys
from app.web import templates

router = APIRouter(prefix="/api/reels", tags=["reels"])
ui_router = APIRouter(prefix="/ui", tags=["reels-ui"])


def _is_safe_link(link: str) -> bool:
    return urlparse(link).scheme.lower() in ("http", "https")


class ReelCreate(BaseModel):
    link: str
    location_id: str
    note: Optional[str] = None
    types: list[str] = []


def _serialize_reel(session: Session, reel: Reel) -> dict:
    types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    return {
        "id": reel.id,
        "link": reel.link,
        "location_id": reel.location_id,
        "note": reel.note,
        "created_at": reel.created_at.isoformat(),
        "types": [t.type for t in types],
    }


@router.get("")
def list_reels(
    location_id: Optional[str] = None,
    type: Optional[str] = None,
    session: Session = Depends(get_session),
):
    query = select(Reel)
    if location_id is not None:
        query = query.where(Reel.location_id == location_id)
    reels = session.exec(query).all()

    if type is not None:
        matching_ids = set(
            session.exec(select(ReelType.reel_id).where(ReelType.type == type)).all()
        )
        reels = [r for r in reels if r.id in matching_ids]

    return [_serialize_reel(session, r) for r in reels]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_reel(payload: ReelCreate, session: Session = Depends(get_session)):
    if not _is_safe_link(payload.link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")
    reel = Reel(link=payload.link, location_id=payload.location_id, note=payload.note)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    valid_type_keys = get_valid_type_keys(session)
    for type_value in payload.types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    return _serialize_reel(session, reel)


@router.delete("/{reel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reel(reel_id: str, session: Session = Depends(get_session)):
    reel = session.get(Reel, reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")

    types = session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all()
    for t in types:
        session.delete(t)
    session.delete(reel)
    session.commit()


def _reel_list_context(session: Session, location_id: Optional[str] = None) -> dict:
    query = select(Reel)
    if location_id is not None:
        query = query.where(Reel.location_id == location_id)
    reels = session.exec(query).all()
    locations = session.exec(select(Location)).all()
    filtered_location = session.get(Location, location_id) if location_id else None
    return {
        "reels": [_serialize_reel(session, r) for r in reels],
        "locations": locations,
        "taxonomy": get_taxonomy(session),
        "filtered_location": filtered_location,
    }


@ui_router.get("/reels")
def ui_list_reels(
    request: Request,
    location_id: Optional[str] = None,
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request, "partials/reel_list.html", _reel_list_context(session, location_id)
    )


@ui_router.post("/reels")
def ui_create_reel(
    request: Request,
    link: str = Form(...),
    location_id: str = Form(...),
    note: Optional[str] = Form(None),
    types: list[str] = Form([]),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")
    reel = Reel(link=link, location_id=location_id, note=note)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    valid_type_keys = get_valid_type_keys(session)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()
    return templates.TemplateResponse(request, "partials/reel_list.html", _reel_list_context(session))


@ui_router.delete("/reels/{reel_id}")
def ui_delete_reel(request: Request, reel_id: str, session: Session = Depends(get_session)):
    reel = session.get(Reel, reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    for t in session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all():
        session.delete(t)
    session.delete(reel)
    session.commit()
    return templates.TemplateResponse(request, "partials/reel_list.html", _reel_list_context(session))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reels_api.py -v`
Expected: PASS (7 tests)

Run: `uv run pytest -v`
Expected: PASS (full suite — `app/routers/map.py` and `app/routers/ai_categorize.py` still import the old `app.taxonomy`, untouched until Tasks 5 and 7, so they keep working as before)

- [ ] **Step 5: Commit**

```bash
git add app/routers/reels.py tests/test_reels_api.py
git commit -m "refactor: read categories from the database in reels.py"
```

---

### Task 5: Migrate `app/routers/map.py` to dynamic categories

**Files:**
- Modify: `app/routers/map.py`
- Modify: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `get_taxonomy(session)` from `app.routers.categories` (Task 2).
- No change to `map.py`'s exported names (`compute_map`, `locations_with_type`, `visible_location_ids`, `router`, `ui_router`) — only `ui_map`'s internals change.

- [ ] **Step 1: Update the test ahead of the refactor**

In `tests/test_ui_fragments.py`, the chip-label test needs a seeded category so it keeps passing once the chips come from the database instead of the static `TAXONOMY` (this step only adds the seed; the test still passes either way until Step 3's migration, since the seed is additive and the old static constant still independently contains `"food"`/`"Cibo"`). Replace just this one test — find and replace:

```python
def test_ui_map_includes_type_filter_chips(client):
    response = client.get("/ui/map")
    assert response.status_code == 200
    assert "Cibo" in response.text
    assert 'hx-get="/ui/map?type=food"' in response.text
```

with:

```python
def test_ui_map_includes_type_filter_chips(client, session):
    from app.models import Category

    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200
    assert "Cibo" in response.text
    assert 'hx-get="/ui/map?type=food"' in response.text
```

- [ ] **Step 2: Run test to confirm it still passes before the refactor**

Run: `uv run pytest tests/test_ui_fragments.py::test_ui_map_includes_type_filter_chips -v`
Expected: PASS — `map.py` hasn't changed yet, so the chip still comes from the old static `TAXONOMY` constant, unaffected by the `Category` row the test now also seeds. This confirms Step 1 didn't break anything by itself, before the real change in Step 3 (which then reads the chip from that seeded row instead).

- [ ] **Step 3: Migrate `map.py`**

Replace the full contents of `app/routers/map.py` with:

```python
import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models import Location, Reel, ReelType
from app.routers.categories import get_taxonomy
from app.web import templates

router = APIRouter(prefix="/api/map", tags=["map"])
ui_router = APIRouter(prefix="/ui", tags=["map-ui"])


def compute_map(session: Session) -> list[dict]:
    locations = session.exec(select(Location)).all()
    counts = dict(
        session.exec(
            select(Reel.location_id, func.count(Reel.id)).group_by(Reel.location_id)
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
def get_map(session: Session = Depends(get_session)):
    return compute_map(session)


def locations_with_type(session: Session, type_value: str) -> set[str]:
    reel_ids = set(
        session.exec(select(ReelType.reel_id).where(ReelType.type == type_value)).all()
    )
    if not reel_ids:
        return set()
    return set(
        session.exec(select(Reel.location_id).where(Reel.id.in_(reel_ids))).all()
    )


def visible_location_ids(
    session: Session,
    locations: list[dict],
    type_value: str | None,
    hide_empty: bool,
) -> tuple[set[str] | None, set[str]]:
    """(visible_ids, anchor_hub_ids). visible_ids is None when hide_empty is
    False (no filtering - show everything). anchor_hub_ids is always a
    subset of visible_ids: hubs that qualify only because a child satellite
    qualifies, not because they have reels of their own."""
    if not hide_empty:
        return None, set()

    if type_value:
        qualifying = locations_with_type(session, type_value)
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


@ui_router.get("/map")
def ui_map(
    request: Request,
    type: str = None,
    hide_empty: bool = False,
    session: Session = Depends(get_session),
):
    locations = compute_map(session)
    hubs_by_id = {loc["id"]: loc for loc in locations if loc["is_hub"]}
    matching_location_ids = locations_with_type(session, type) if type else set()
    visible_ids, anchor_hub_ids = visible_location_ids(session, locations, type, hide_empty)

    map_locations = []
    for loc in locations:
        if visible_ids is not None and loc["id"] not in visible_ids:
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
            "dimmed": bool(type) and loc["id"] not in matching_location_ids,
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

    return templates.TemplateResponse(
        request,
        "partials/map.html",
        {
            "map_locations_json": map_locations_json,
            "active_type": type,
            "taxonomy": get_taxonomy(session),
            "hide_empty": hide_empty,
        },
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ui_fragments.py tests/test_map_api.py -v`
Expected: PASS — `test_ui_map_includes_type_filter_chips` still passes, now sourced from the seeded `Category` row instead of the deleted-later static constant; every other test in both files is unaffected (`test_map_api.py`'s tests exercise `compute_map`/`visible_location_ids`/`locations_with_type`, none of which ever referenced `TAXONOMY`).

Run: `uv run pytest -v`
Expected: PASS (full suite)

- [ ] **Step 5: Commit**

```bash
git add app/routers/map.py tests/test_ui_fragments.py
git commit -m "refactor: read categories from the database in map.py"
```

---

### Task 6: AI schema/prompt become functions of the current categories

**Files:**
- Modify: `app/ai/prompts.py`
- Modify: `app/ai/client.py`
- Modify: `tests/test_ai_prompts.py`
- Modify: `tests/test_ai_client.py`

**Interfaces:**
- Produces: `build_response_schema(valid_type_keys: Iterable[str]) -> dict` (replaces the module-level `RESPONSE_SCHEMA` constant). `build_system_prompt(hub_names: Iterable[str], categories: dict[str, str]) -> str` (gains a second parameter; `categories` maps `key -> label`, e.g. `{"food": "Cibo"}`). `categorize(hub_names: list[str], categories: dict[str, str], messages: list[dict[str, str]]) -> dict[str, Any]` (gains a middle parameter). Task 7 is the only caller of `categorize()` in application code and will be updated to match.
- This task does **not** touch `app.taxonomy` — the goal here is only to make the schema/prompt take categories as data instead of importing the constant. `app/ai/prompts.py` and `app/ai/client.py` have zero DB access (same as before); the caller (Task 7) is responsible for fetching categories and passing them in, exactly like it already does for `hub_names`.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_ai_prompts.py` with:

```python
from app.ai.prompts import build_response_schema, build_system_prompt

VALID_TYPES = {"food", "culture", "nature", "shopping", "stay", "transport", "experience"}
CATEGORIES = {
    "food": "Cibo",
    "culture": "Cultura",
    "nature": "Natura",
    "shopping": "Shopping",
    "stay": "Alloggio",
    "transport": "Trasporti",
    "experience": "Esperienza",
}


def test_response_schema_has_required_fields():
    schema = build_response_schema(VALID_TYPES)
    assert schema["required"] == [
        "place_name", "near_hub", "types", "note", "confidence", "question",
        "lat", "lon",
    ]
    assert schema["additionalProperties"] is False


def test_response_schema_lat_lon_are_nullable_numbers():
    schema = build_response_schema(VALID_TYPES)
    assert schema["properties"]["lat"] == {"type": ["number", "null"]}
    assert schema["properties"]["lon"] == {"type": ["number", "null"]}


def test_response_schema_types_items_are_constrained_to_the_given_types():
    schema = build_response_schema(VALID_TYPES)
    items_schema = schema["properties"]["types"]["items"]
    assert items_schema["type"] == "string"
    assert set(items_schema["enum"]) == VALID_TYPES


def test_build_system_prompt_includes_hub_names():
    prompt = build_system_prompt(["Tokyo / Kanto", "Kyoto - Osaka / Kansai"], CATEGORIES)
    assert "Tokyo / Kanto" in prompt
    assert "Kyoto - Osaka / Kansai" in prompt


def test_build_system_prompt_mentions_lat_lon_estimation():
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    assert "lat" in prompt
    assert "lon" in prompt


def test_build_system_prompt_lists_every_given_category():
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    for key in CATEGORIES:
        assert key in prompt


def test_build_system_prompt_reflects_custom_categories():
    # Regression guard for the whole point of this feature: a category the
    # user just created must show up in the prompt exactly like a built-in
    # one, with no special-casing.
    prompt = build_system_prompt(["Tokyo / Kanto"], {"nightlife": "Vita notturna"})
    assert "nightlife" in prompt
    assert "Vita notturna" in prompt


def test_build_system_prompt_pushes_for_approximate_estimate_over_hedging():
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    assert "approssimativa" in prompt
    assert "quartiere" in prompt
    assert "Asakusa" in prompt
```

Replace the full contents of `tests/test_ai_client.py` with:

```python
import json
from types import SimpleNamespace

from app.ai import client as ai_client


class FakeMessages:
    def __init__(self, response_json: dict):
        self._response_json = response_json
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(self._response_json))]
        )


class FakeAnthropicClient:
    def __init__(self, response_json: dict):
        self.messages = FakeMessages(response_json)


def test_categorize_returns_parsed_json(monkeypatch):
    expected = {
        "place_name": "Ichiran Ramen",
        "near_hub": "Tokyo / Kanto",
        "types": ["food"],
        "note": "Famous ramen chain",
        "confidence": "high",
        "question": None,
    }
    fake_client = FakeAnthropicClient(expected)
    monkeypatch.setattr(ai_client, "get_client", lambda: fake_client)

    result = ai_client.categorize(
        ["Tokyo / Kanto"], {"food": "Cibo"}, [{"role": "user", "content": "Ramen a Tokyo"}]
    )

    assert result == expected
    assert fake_client.messages.last_call_kwargs["model"] == ai_client.MODEL
    assert fake_client.messages.last_call_kwargs["output_config"]["format"]["type"] == "json_schema"
    schema = fake_client.messages.last_call_kwargs["output_config"]["format"]["schema"]
    assert schema["properties"]["types"]["items"]["enum"] == ["food"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_prompts.py tests/test_ai_client.py -v`
Expected: FAIL — `build_response_schema` doesn't exist yet (`RESPONSE_SCHEMA` is still a constant), `build_system_prompt` doesn't accept a second argument, `categorize` doesn't accept a middle argument.

- [ ] **Step 3: Update `app/ai/prompts.py`**

Replace the full contents of `app/ai/prompts.py` with:

```python
from typing import Iterable


def build_response_schema(valid_type_keys: Iterable[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "place_name": {"type": "string"},
            "near_hub": {"type": ["string", "null"]},
            "types": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(valid_type_keys)},
            },
            "note": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "question": {"type": ["string", "null"]},
            "lat": {"type": ["number", "null"]},
            "lon": {"type": ["number", "null"]},
        },
        "required": [
            "place_name", "near_hub", "types", "note", "confidence", "question",
            "lat", "lon",
        ],
        "additionalProperties": False,
    }


def build_system_prompt(hub_names: Iterable[str], categories: dict[str, str]) -> str:
    hubs_list = ", ".join(hub_names) if hub_names else "nessuno ancora"
    types_list = ", ".join(f"{key} ({label})" for key, label in categories.items())
    return (
        "Sei un assistente che aiuta a categorizzare reel Instagram salvati per un viaggio in Giappone. "
        "L'utente ti invia un link e una didascalia (o una descrizione libera) di un reel. "
        "Non puoi aprire il link: lavori solo sul testo fornito. "
        f"Le tappe principali (hub) gia' esistenti sono: {hubs_list}. "
        "Se il testo corrisponde chiaramente a un hub esistente o a una localita' vicina, usa near_hub per indicarlo. "
        f"Per 'types' puoi usare esclusivamente queste chiavi esatte (in inglese, non tradurle): {types_list}. "
        "Scegli una o piu' chiavi tra queste che descrivono il contenuto del reel; non inventare altre categorie. "
        "Se non riesci a capire nemmeno approssimativamente in che citta' o zona del Giappone si trovi il posto, "
        "valorizza 'question' con una domanda di chiarimento e lascia gli altri campi con la tua migliore ipotesi. "
        "Se il luogo proposto non corrisponde a nessun hub o tappa gia' esistente, valorizza SEMPRE anche lat e lon: "
        "basta una stima approssimativa a livello di quartiere o citta' (in gradi decimali), non serve individuare "
        "il punto esatto -- la mappa e' schematica, non geograficamente precisa. Usa la tua conoscenza generale della "
        "geografia giapponese: se nel testo compare un quartiere, un tempio, una via o un altro punto di riferimento "
        "riconoscibile (per esempio 'Asakusa', 'Senso-ji', 'Dotonbori', 'Shinjuku'), stima le coordinate di quella "
        "zona invece di lasciare i campi vuoti. Lascia lat e lon a null solo se il testo non permette di individuare "
        "nemmeno una zona approssimativa. "
        "Se il luogo corrisponde a un hub o tappa gia' esistente, puoi lasciare lat e lon a null: non verranno usate. "
        "Rispondi seguendo esattamente lo schema JSON fornito."
    )
```

- [ ] **Step 4: Update `app/ai/client.py`**

Replace the full contents of `app/ai/client.py` with:

```python
import json
import logging
import os
from typing import Any, Optional

from anthropic import Anthropic

from app.ai.prompts import build_response_schema, build_system_prompt

MODEL = "claude-haiku-4-5"

_client: Optional[Anthropic] = None

logger = logging.getLogger("app.ai")


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def categorize(
    hub_names: list[str], categories: dict[str, str], messages: list[dict[str, str]]
) -> dict[str, Any]:
    client = get_client()
    system = build_system_prompt(hub_names, categories)
    schema = build_response_schema(categories.keys())
    logger.debug("categorize request hub_names=%s categories=%s messages=%s", hub_names, categories, messages)
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = next(block.text for block in response.content if block.type == "text")
    logger.debug("categorize raw response text=%s", text)
    return json.loads(text)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_prompts.py tests/test_ai_client.py -v`
Expected: PASS (8 + 1 tests)

Run: `uv run pytest -v`
Expected: FAIL — `app/routers/ai_categorize.py` still calls `ai_client.categorize(hub_names, api_messages)` (2 args) and imports `RESPONSE_SCHEMA`/`build_system_prompt(hub_names)` indirectly via the old 2-arg call; this is expected and fixed in Task 7. Confirm the *only* failures are in `tests/test_ai_categorize.py` and `tests/test_ai_ui.py` (every fake `categorize` there is still 2-arg) — no other files should fail.

- [ ] **Step 6: Commit**

```bash
git add app/ai/prompts.py app/ai/client.py tests/test_ai_prompts.py tests/test_ai_client.py
git commit -m "refactor: parameterize the AI schema/prompt on the current categories"
```

---

### Task 7: Migrate `app/routers/ai_categorize.py` and fix every dependent test

**Files:**
- Modify: `app/routers/ai_categorize.py`
- Modify: `tests/test_ai_categorize.py`
- Modify: `tests/test_ai_ui.py`

**Interfaces:**
- Consumes: `get_taxonomy(session)`, `get_valid_type_keys(session)` from `app.routers.categories` (Task 2); `ai_client.categorize(hub_names, categories, messages)` (Task 6).
- This is the task that actually breaks every existing `monkeypatch.setattr(ai_client, "categorize", ...)` fake in the test suite (as flagged in the design's ripple section) — every one of them gains a middle `categories` parameter in this task, not before. No new public interface beyond what Tasks 3-6 already established.

- [ ] **Step 1: Write the failing test changes**

Replace the full contents of `tests/test_ai_categorize.py` with:

```python
import json

import anthropic

from app.ai import client as ai_client
from app.models import Category, Location
from app.routers.ai_categorize import _run_turn


def test_categorize_creates_session_and_returns_proposal(client, session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    def fake_categorize(hub_names, categories, messages):
        return {
            "place_name": "Ichiran Ramen",
            "near_hub": "Tokyo / Kanto",
            "types": ["food", "not-a-real-type"],
            "note": "Famous ramen chain",
            "confidence": "high",
            "question": None,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)

    response = client.post("/api/ai/categorize", json={"message": "Ramen a Tokyo, link X"})
    assert response.status_code == 200
    data = response.json()
    assert data["place_name"] == "Ichiran Ramen"
    assert data["types"] == ["food"]
    assert data["session_id"]
    assert data["matched_location_id"] is None


def test_categorize_continues_existing_session(client, session, monkeypatch):
    def fake_categorize(hub_names, categories, messages):
        # Full session history: first user turn, first assistant (question)
        # turn, second user turn — never windowed (spec §5.3: the model must
        # see the entire conversation, not just the last exchange).
        assert len(messages) == 3
        return {
            "place_name": "Nikko",
            "near_hub": "Tokyo / Kanto",
            "types": ["nature"],
            "note": "Shrine town",
            "confidence": "medium",
            "question": None,
        }

    monkeypatch.setattr(ai_client, "categorize", lambda hub_names, categories, messages: {
        "place_name": "?",
        "near_hub": None,
        "types": [],
        "note": "",
        "confidence": "low",
        "question": "Che citta' e'?",
    })
    first = client.post("/api/ai/categorize", json={"message": "Un tempio in montagna"})
    session_id = first.json()["session_id"]

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)
    second = client.post(
        "/api/ai/categorize", json={"session_id": session_id, "message": "E' Nikko"}
    )
    assert second.status_code == 200
    assert second.json()["session_id"] == session_id
    assert second.json()["place_name"] == "Nikko"


def test_categorize_matches_existing_location_case_insensitive(client, session, monkeypatch):
    hub = Location(name="Nikko", is_hub=False, parent_id=None)
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.add(hub)
    session.commit()
    session.refresh(hub)

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "nikko",
            "near_hub": "Tokyo / Kanto",
            "types": ["nature"],
            "note": "Shrine town",
            "confidence": "high",
            "question": None,
        },
    )

    response = client.post("/api/ai/categorize", json={"message": "Tempio a Nikko"})
    assert response.json()["matched_location_id"] == hub.id


def test_categorize_with_unknown_session_id_returns_404(client):
    response = client.post(
        "/api/ai/categorize",
        json={"session_id": "does-not-exist", "message": "Ciao"},
    )
    assert response.status_code == 404


def test_categorize_forces_question_when_new_location_missing_coordinates(client, session, monkeypatch):
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Mystery Alley",
            "near_hub": None,
            "types": ["food"],
            "note": "Some alley",
            "confidence": "medium",
            "question": None,
            "lat": None,
            "lon": None,
        },
    )

    response = client.post("/api/ai/categorize", json={"message": "Un vicolo di street food"})
    assert response.status_code == 200
    assert response.json()["question"] is not None
    assert "coordinate" in response.json()["question"].lower()


def test_categorize_returns_friendly_question_when_ai_call_fails(client, session, monkeypatch):
    def boom(hub_names, categories, messages):
        raise anthropic.AnthropicError("boom")

    monkeypatch.setattr(ai_client, "categorize", boom)

    response = client.post("/api/ai/categorize", json={"message": "Qualcosa"})
    assert response.status_code == 200
    assert "riprova" in response.json()["question"].lower()


def test_empty_place_name_does_not_spuriously_match_location(client, session, monkeypatch):
    # Regression: when AI call fails, place_name is "" (empty string).
    # Before fix: "" in any location name is always True, so it would
    # spuriously match the first location. After fix: returns None.
    location = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(location)
    session.commit()
    session.refresh(location)

    def boom(hub_names, categories, messages):
        raise anthropic.AnthropicError("boom")

    monkeypatch.setattr(ai_client, "categorize", boom)

    response = client.post("/api/ai/categorize", json={"message": "Qualcosa"})
    assert response.status_code == 200
    assert response.json()["matched_location_id"] is None


def test_assistant_history_sent_to_model_is_natural_language_not_json(session, monkeypatch):
    # Regression: the assistant's previous structured turn used to be replayed
    # to the model as a raw json.dumps(...) blob, which can anchor the model
    # into repeating the same (null) lat/lon turn after turn. It should be
    # sent as plain text instead.
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "?",
            "near_hub": None,
            "types": [],
            "note": "",
            "confidence": "low",
            "question": "Che citta' e'?",
            "lat": None,
            "lon": None,
        },
    )
    ai_session, _, _ = _run_turn(session, None, "Un tempio in montagna")

    captured = {}

    def fake_categorize(hub_names, categories, messages):
        captured["messages"] = messages
        return {
            "place_name": "Nikko",
            "near_hub": None,
            "types": ["nature"],
            "note": "Shrine town",
            "confidence": "medium",
            "question": None,
            "lat": 36.7199,
            "lon": 139.6982,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)
    _run_turn(session, ai_session.id, "E' Nikko")

    assistant_messages = [m for m in captured["messages"] if m["role"] == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["content"] == "Che citta' e'?"
    assert not assistant_messages[0]["content"].strip().startswith("{")


def test_assistant_proposal_history_is_summarized_not_raw_json(session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Ichiran Ramen",
            "near_hub": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Famous ramen chain",
            "confidence": "high",
            "question": None,
            "lat": 35.6595,
            "lon": 139.7005,
        },
    )
    ai_session, _, _ = _run_turn(session, None, "Ramen a Tokyo")

    captured = {}

    def fake_categorize(hub_names, categories, messages):
        captured["messages"] = messages
        return {
            "place_name": "Ichiran Ramen",
            "near_hub": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Famous ramen chain",
            "confidence": "high",
            "question": None,
            "lat": 35.6595,
            "lon": 139.7005,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)
    _run_turn(session, ai_session.id, "conferma")

    assistant_text = [m for m in captured["messages"] if m["role"] == "assistant"][0]["content"]
    assert "Ichiran Ramen" in assistant_text
    assert not assistant_text.strip().startswith("{")


def test_safety_net_falls_back_to_hub_coordinates_after_second_consecutive_failure(session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Shinjuku",
            "near_hub": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Street food area",
            "confidence": "medium",
            "question": None,
            "lat": None,
            "lon": None,
        },
    )

    ai_session, first_result, _ = _run_turn(session, None, "Cibo di strada a Shinjuku")
    assert first_result["question"] is not None
    assert first_result["lat"] is None

    ai_session2, second_result, matched = _run_turn(session, ai_session.id, "Shinjuku, Tokyo")
    assert second_result["question"] is None
    assert second_result["lat"] == 35.6762
    assert second_result["lon"] == 139.6503
```

Replace the full contents of `tests/test_ai_ui.py` with:

```python
import anthropic
from sqlmodel import select

from app.ai import client as ai_client
from app.models import AiMessage, AiSession, Location, Reel


def test_ui_ai_panel_renders_empty_state(client):
    response = client.get("/ui/ai/panel")
    assert response.status_code == 200
    assert 'name="link"' in response.text
    assert 'name="message"' in response.text


def test_ui_ai_message_first_turn_creates_session_and_shows_proposal(client, session, monkeypatch):
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Ichiran Ramen",
            "near_hub": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Famous ramen chain",
            "confidence": "high",
            "question": None,
            "lat": 35.6595,
            "lon": 139.7005,
        },
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/abc", "message": "Ramen a Tokyo"},
    )
    assert response.status_code == 200
    assert "Ichiran Ramen" in response.text
    assert session.exec(select(AiSession)).first() is not None


def test_ui_ai_message_continues_existing_session(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "?",
            "near_hub": None,
            "types": [],
            "note": "",
            "confidence": "low",
            "question": "In che citta si trova?",
            "lat": None,
            "lon": None,
        },
    )
    first = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/abc", "message": "Un tempio"},
    )
    assert "In che citta si trova?" in first.text

    session_id = session.exec(select(AiSession)).first().id

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Nikko",
            "near_hub": None,
            "types": ["nature"],
            "note": "Shrine town",
            "confidence": "medium",
            "question": None,
            "lat": 36.7198,
            "lon": 139.6982,
        },
    )
    second = client.post(
        "/ui/ai/message",
        data={"session_id": session_id, "link": "https://instagram.com/reel/abc", "message": "E' Nikko"},
    )
    assert second.status_code == 200
    assert "Nikko" in second.text


def test_ui_ai_message_rejects_invalid_link_on_first_turn(client, session):
    response = client.post(
        "/ui/ai/message",
        data={"link": "javascript:alert(1)", "message": "Qualcosa"},
    )
    assert response.status_code == 400
    assert session.exec(select(AiSession)).all() == []


def test_ui_ai_message_forces_question_when_new_location_missing_coordinates(client, session, monkeypatch):
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Mystery Alley",
            "near_hub": None,
            "types": ["food"],
            "note": "Some alley",
            "confidence": "medium",
            "question": None,
            "lat": None,
            "lon": None,
        },
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/xyz", "message": "Un vicolo di street food"},
    )
    assert response.status_code == 200
    assert "coordinate" in response.text.lower()
    assert "Conferma e salva" not in response.text


def test_ui_ai_message_shows_confirm_button_when_proposal_is_complete(client, session, monkeypatch):
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Ichiran Ramen",
            "near_hub": "Tokyo / Kanto",
            "types": ["food"],
            "note": "Famous ramen chain",
            "confidence": "high",
            "question": None,
            "lat": 35.6595,
            "lon": 139.7005,
        },
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/abc", "message": "Ramen a Tokyo"},
    )
    assert "Conferma e salva" in response.text


def test_ui_ai_confirm_with_matched_location_creates_reel_on_existing_location(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/abc",
            "place_name": "Tokyo / Kanto",
            "near_hub": "",
            "types": ["food"],
            "note": "Ramen chain",
            "lat": "",
            "lon": "",
            "matched_location_id": hub.id,
        },
    )
    assert response.status_code == 200

    reels = session.exec(select(Reel)).all()
    assert len(reels) == 1
    assert reels[0].location_id == hub.id
    assert session.exec(select(Location)).all() == [hub]


def test_ui_ai_confirm_creates_satellite_under_matching_hub(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/nikko",
            "place_name": "Nikko",
            "near_hub": "Tokyo / Kanto",
            "types": ["nature"],
            "note": "Shrine town",
            "lat": "36.7198",
            "lon": "139.6982",
            "matched_location_id": "",
        },
    )
    assert response.status_code == 200

    satellite = session.exec(select(Location).where(Location.name == "Nikko")).first()
    assert satellite is not None
    assert satellite.is_hub is False
    assert satellite.parent_id == hub.id
    assert satellite.lat == 36.7198


def test_ui_ai_confirm_creates_new_hub_when_no_hub_matches(client, session):
    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/sapporo",
            "place_name": "Sapporo Ramen Alley",
            "near_hub": "",
            "types": ["food"],
            "note": "Ramen alley",
            "lat": "43.0618",
            "lon": "141.3545",
            "matched_location_id": "",
        },
    )
    assert response.status_code == 200

    location = session.exec(select(Location).where(Location.name == "Sapporo Ramen Alley")).first()
    assert location is not None
    assert location.is_hub is True
    assert location.parent_id is None


def test_ui_ai_confirm_rejects_invalid_link(client, session):
    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "javascript:alert(1)",
            "place_name": "Somewhere",
            "near_hub": "",
            "types": [],
            "note": "",
            "lat": "1.0",
            "lon": "1.0",
            "matched_location_id": "",
        },
    )
    assert response.status_code == 400
    assert session.exec(select(Reel)).all() == []


def test_ui_ai_confirm_resets_panel_and_updates_reel_list(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": "irrelevant",
            "link": "https://instagram.com/reel/abc",
            "place_name": "Tokyo / Kanto",
            "near_hub": "",
            "types": ["food"],
            "note": "Ramen chain",
            "lat": "",
            "lon": "",
            "matched_location_id": hub.id,
        },
    )
    assert response.status_code == 200
    assert 'name="message"' in response.text
    assert "Conferma e salva" not in response.text
    assert 'hx-swap-oob="innerHTML:#reel-list"' in response.text
    assert "https://instagram.com/reel/abc" in response.text


def test_ui_ai_confirm_cleans_up_the_ai_session(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Sapporo Ramen Alley",
            "near_hub": None,
            "types": ["food"],
            "note": "Ramen alley",
            "confidence": "high",
            "question": None,
            "lat": 43.0618,
            "lon": 141.3545,
        },
    )
    client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/sapporo", "message": "Ramen alley a Sapporo"},
    )
    ai_session_id = session.exec(select(AiSession)).first().id

    response = client.post(
        "/ui/ai/confirm",
        data={
            "session_id": ai_session_id,
            "link": "https://instagram.com/reel/sapporo",
            "place_name": "Sapporo Ramen Alley",
            "near_hub": "",
            "types": ["food"],
            "note": "Ramen alley",
            "lat": "43.0618",
            "lon": "141.3545",
            "matched_location_id": "",
        },
    )
    assert response.status_code == 200
    assert session.exec(select(AiSession).where(AiSession.id == ai_session_id)).first() is None
    assert session.exec(select(AiMessage).where(AiMessage.session_id == ai_session_id)).all() == []


def test_ui_ai_message_shows_friendly_error_when_ai_call_fails(client, session, monkeypatch):
    def boom(hub_names, categories, messages):
        raise anthropic.AnthropicError("boom")

    monkeypatch.setattr(ai_client, "categorize", boom)

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/abc", "message": "Qualcosa"},
    )
    assert response.status_code == 200
    assert "riprova" in response.text.lower()


def test_ui_ai_message_with_unknown_session_id_resets_panel_with_notice(client, session):
    response = client.post(
        "/ui/ai/message",
        data={"session_id": "does-not-exist", "link": "https://instagram.com/reel/abc", "message": "Ciao"},
    )
    assert response.status_code == 200
    assert 'name="link"' in response.text
    assert "Sessione scaduta" in response.text
```

- [ ] **Step 2: Run tests to verify they still fail**

Run: `uv run pytest tests/test_ai_categorize.py tests/test_ai_ui.py -v`
Expected: FAIL — every fake now takes 3 params, but `_run_turn` still calls `ai_client.categorize(hub_names, api_messages)` with 2 args and still filters with the old `VALID_TYPES` import — proceed to Step 3.

- [ ] **Step 3: Migrate `ai_categorize.py`**

Replace the full contents of `app/routers/ai_categorize.py` with:

```python
import json
import logging
from typing import Optional

import anthropic
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.db import get_session
from app.models import AiMessage, AiSession, Location, Reel, ReelType
from app.routers.categories import get_taxonomy, get_valid_type_keys
from app.routers.reels import _is_safe_link, _reel_list_context
from app.web import templates

router = APIRouter(prefix="/api/ai", tags=["ai"])
ui_router = APIRouter(prefix="/ui/ai", tags=["ai-ui"])

logger = logging.getLogger("app.ai")

MISSING_COORDINATES_QUESTION = (
    "Non riesco a stimare le coordinate di questo posto: "
    "qual e' la citta' o zona piu' vicina?"
)


class CategorizeRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class CategorizeResponse(BaseModel):
    session_id: str
    place_name: str
    near_hub: Optional[str]
    types: list[str]
    note: str
    confidence: str
    question: Optional[str]
    matched_location_id: Optional[str] = None


def _find_matching_location(session: Session, place_name: str) -> Optional[str]:
    place_name_lower = place_name.lower()
    if not place_name_lower:
        return None
    for loc in session.exec(select(Location)).all():
        loc_name_lower = loc.name.lower()
        if place_name_lower in loc_name_lower or loc_name_lower in place_name_lower:
            return loc.id
    return None


def _find_hub_by_name(session: Session, name: str) -> Optional[Location]:
    if not name:
        return None
    return session.exec(
        select(Location).where(Location.is_hub == True, func.lower(Location.name) == name.lower())
    ).first()


def _assistant_turn_text(result: dict) -> str:
    if result.get("question"):
        return result["question"]

    parts = [f"Luogo proposto: {result.get('place_name', '')}."]
    if result.get("near_hub"):
        parts.append(f"Vicino a: {result['near_hub']}.")
    if result.get("types"):
        parts.append(f"Tipo: {', '.join(result['types'])}.")
    if result.get("note"):
        parts.append(f"Nota: {result['note']}.")
    parts.append(f"Confidenza: {result.get('confidence', '')}.")
    return " ".join(parts)


def _run_turn(
    session: Session, session_id: Optional[str], message: str
) -> tuple[AiSession, dict, Optional[str]]:
    if session_id:
        ai_session = session.get(AiSession, session_id)
        if ai_session is None:
            raise HTTPException(status_code=404, detail="AI session not found")
    else:
        ai_session = AiSession()
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

    previous_result = None
    for m in reversed(history[:-1]):
        if m.role == "assistant":
            previous_result = json.loads(m.content)
            break
    previous_safety_net_triggered = (
        previous_result is not None and previous_result.get("question") == MISSING_COORDINATES_QUESTION
    )
    logger.debug(
        "session=%s previous_safety_net_triggered=%s",
        ai_session.id, previous_safety_net_triggered,
    )

    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]

    taxonomy = get_taxonomy(session)
    category_labels = {key: info["label"] for key, info in taxonomy.items()}

    try:
        result = ai_client.categorize(hub_names, category_labels, api_messages)
    except anthropic.AnthropicError:
        logger.exception("session=%s Anthropic call failed", ai_session.id)
        result = {
            "place_name": "",
            "near_hub": None,
            "types": [],
            "note": "",
            "confidence": "low",
            "question": "Errore nel contattare l'assistente, riprova.",
            "lat": None,
            "lon": None,
        }

    logger.debug("session=%s parsed model result=%s", ai_session.id, result)

    valid_type_keys = get_valid_type_keys(session)
    result["types"] = [t for t in result.get("types", []) if t in valid_type_keys]

    matched_location_id = _find_matching_location(session, result["place_name"])
    logger.debug("session=%s matched_location_id=%s", ai_session.id, matched_location_id)

    if (
        matched_location_id is None
        and result.get("question") is None
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        logger.debug(
            "session=%s safety net condition met (unmatched place, no question, missing lat/lon)",
            ai_session.id,
        )
        if previous_safety_net_triggered and result.get("near_hub"):
            hub = _find_hub_by_name(session, result["near_hub"])
            logger.debug(
                "session=%s attempting hub fallback for near_hub=%r -> hub=%s",
                ai_session.id, result["near_hub"], hub.name if hub else None,
            )
            if hub is not None:
                result["lat"] = hub.lat
                result["lon"] = hub.lon

        if result.get("lat") is None or result.get("lon") is None:
            result["question"] = MISSING_COORDINATES_QUESTION

    logger.debug("session=%s final result=%s", ai_session.id, result)

    session.add(AiMessage(session_id=ai_session.id, role="assistant", content=json.dumps(result)))
    session.commit()

    return ai_session, result, matched_location_id


@router.post("/categorize", response_model=CategorizeResponse)
def categorize_reel(payload: CategorizeRequest, session: Session = Depends(get_session)):
    ai_session, result, matched_location_id = _run_turn(session, payload.session_id, payload.message)
    return CategorizeResponse(session_id=ai_session.id, matched_location_id=matched_location_id, **result)


def _build_ai_chat_context(
    session: Session, ai_session_id: Optional[str], link: str, notice: Optional[str] = None
) -> dict:
    history: list[dict] = []
    latest_result: Optional[dict] = None

    if ai_session_id:
        messages = session.exec(
            select(AiMessage)
            .where(AiMessage.session_id == ai_session_id)
            .order_by(AiMessage.created_at)
        ).all()
        for m in messages:
            if m.role == "user":
                history.append({"role": "user", "text": m.content})
            else:
                result = json.loads(m.content)
                history.append({"role": "assistant", "result": result})
                latest_result = result

    matched_location_id = (
        _find_matching_location(session, latest_result["place_name"])
        if latest_result is not None
        else None
    )
    can_confirm = latest_result is not None and latest_result.get("question") is None

    return {
        "session_id": ai_session_id or "",
        "link": link or "",
        "history": history,
        "latest_result": latest_result,
        "can_confirm": can_confirm,
        "matched_location_id": matched_location_id or "",
        "taxonomy": get_taxonomy(session),
        "notice": notice,
    }


@ui_router.get("/panel")
def ui_ai_panel(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request, "partials/ai_chat.html", _build_ai_chat_context(session, None, "")
    )


@ui_router.post("/message")
def ui_ai_message(
    request: Request,
    session_id: str = Form(""),
    link: str = Form(""),
    message: str = Form(...),
    session: Session = Depends(get_session),
):
    if not session_id:
        if not _is_safe_link(link):
            raise HTTPException(status_code=400, detail="link must be an http(s) URL")
        combined_message = f"Link: {link}\nDescrizione: {message}"
    else:
        combined_message = message

    try:
        ai_session, _, _ = _run_turn(session, session_id or None, combined_message)
    except HTTPException as exc:
        if exc.status_code == 404:
            context = _build_ai_chat_context(
                session, None, "", notice="Sessione scaduta, ricomincia pure da qui."
            )
            return templates.TemplateResponse(request, "partials/ai_chat.html", context)
        raise

    return templates.TemplateResponse(
        request, "partials/ai_chat.html", _build_ai_chat_context(session, ai_session.id, link)
    )


@ui_router.post("/confirm")
def ui_ai_confirm(
    request: Request,
    session_id: str = Form(...),
    link: str = Form(...),
    place_name: str = Form(...),
    near_hub: str = Form(""),
    types: list[str] = Form([]),
    note: str = Form(""),
    lat: str = Form(""),
    lon: str = Form(""),
    matched_location_id: str = Form(""),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if matched_location_id:
        location_id = matched_location_id
    else:
        hub = _find_hub_by_name(session, near_hub)

        if not lat or not lon:
            raise HTTPException(
                status_code=400, detail="lat/lon are required to create a new location"
            )

        new_location = Location(
            name=place_name,
            is_hub=hub is None,
            parent_id=hub.id if hub else None,
            lat=float(lat),
            lon=float(lon),
        )
        session.add(new_location)
        session.commit()
        session.refresh(new_location)
        location_id = new_location.id

    reel = Reel(link=link, location_id=location_id, note=note or None)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    valid_type_keys = get_valid_type_keys(session)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    stale_ai_session = session.get(AiSession, session_id)
    if stale_ai_session is not None:
        for msg in session.exec(select(AiMessage).where(AiMessage.session_id == session_id)).all():
            session.delete(msg)
        session.delete(stale_ai_session)
        session.commit()

    ai_chat_html = templates.get_template("partials/ai_chat.html").render(
        _build_ai_chat_context(session, None, "")
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session)
    )

    return HTMLResponse(
        ai_chat_html + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_categorize.py tests/test_ai_ui.py -v`
Expected: PASS (10 + 14 tests)

Run: `uv run pytest -v`
Expected: PASS (full suite — `app/taxonomy.py` still exists on disk at this point but nothing except itself references it anymore; Task 8 removes it)

- [ ] **Step 5: Commit**

```bash
git add app/routers/ai_categorize.py tests/test_ai_categorize.py tests/test_ai_ui.py
git commit -m "refactor: read categories from the database in ai_categorize.py"
```

---

### Task 8: Delete the old `app/taxonomy.py`

**Files:**
- Delete: `app/taxonomy.py`

**Interfaces:**
- None — this is pure removal. By this point (after Tasks 4, 5, 7), nothing in `app/` imports `app.taxonomy` anymore; grep confirms it.

- [ ] **Step 1: Confirm nothing still imports it**

Run: `grep -rn "app.taxonomy\|from app import taxonomy" app/ tests/`
Expected: no output (only `app/taxonomy.py` itself would match if it still existed — after this step's check, delete it).

- [ ] **Step 2: Delete the file**

```bash
git rm app/taxonomy.py
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (full suite, no import errors, no regressions)

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: remove the now-unused static taxonomy module"
```
