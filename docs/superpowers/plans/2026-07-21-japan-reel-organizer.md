# Japan Reel Organizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the Japan Reel Organizer prototype as a Python app: FastAPI + SQLModel/SQLite backend, Jinja2+HTMX frontend, AI-assisted reel categorization via the Anthropic API.

**Architecture:** A single FastAPI app with SQLModel-backed SQLite persistence. JSON `/api/*` endpoints provide programmatic CRUD; parallel `/ui/*` endpoints return HTML fragments consumed by HTMX for the server-rendered frontend. AI categorization is a stateful conversation persisted in the DB (`AiSession`/`AiMessage`), calling the Anthropic Messages API with a JSON-schema-constrained response.

**Tech Stack:** Python 3.11+, FastAPI, SQLModel, SQLite, Jinja2, HTMX, `anthropic` Python SDK (model `claude-haiku-4-5`), pytest, Docker.

## Global Constraints

- Python 3.11+ (per spec §2).
- Persistence: SQLite via SQLModel, file at `data/japan_reels.db` (gitignored).
- No authentication, single-user, local-first (per spec §8).
- AI: never auto-save an AI proposal without user confirmation (per spec §5.3 step 5).
- AI: filter model-returned `types` against the fixed taxonomy; drop unrecognized values (per spec §5.3 step 6).
- AI model id: `claude-haiku-4-5` (resolved decision, spec §10).
- Structured AI output via `output_config.format` JSON Schema, not tool-use or plain-text parsing (resolved decision, spec §10).
- Frontend: Jinja2 + HTMX, responsive/mobile-first CSS, no JS framework (resolved decision, spec §10).
- All config (Anthropic API key, DB path) via environment variables (spec §2).
- Every task's tests use `pytest` and FastAPI's `TestClient`.

## Known scope trims (flagged, not silently dropped)

Two things the spec calls for that this plan does **not** build a UI for, to keep the plan to a shippable first slice:

1. **Inline "create new location" from the reel form** (spec §5.2: "creazione di una nuova tappa al volo... sia come nuovo hub sia come satellite"). Task 9 exposes `POST /api/locations` for this, but the HTMX form in Task 18 only offers a dropdown of existing locations — no "+ nuova tappa" toggle. Follow-up task if wanted.
2. **AI proposal → precompiled manual form** (spec §5.3 step 5: the AI suggestion should precompile the add-reel form for the user to review and confirm — never auto-save). Task 22 builds and tests `POST /api/ai/categorize` as a JSON API, but no HTMX chat widget consumes it or precompiles Task 18's form. Follow-up task if wanted.

Both are natural follow-on plans once the core CRUD + map + AI-endpoint slice from this plan is working end-to-end.

---

## File Structure

```
app/
├── __init__.py
├── main.py                    # FastAPI app, lifespan, router includes, "/" route
├── db.py                      # engine + get_session dependency
├── web.py                     # shared Jinja2Templates instance
├── models.py                  # Location, Reel, ReelType, AiSession, AiMessage
├── taxonomy.py                # TAXONOMY, VALID_TYPES
├── seed.py                    # seed_if_empty()
├── layout.py                  # radial_positions()
├── routers/
│   ├── __init__.py
│   ├── locations.py           # /api/locations (JSON CRUD)
│   ├── reels.py                # /api/reels (JSON CRUD) + /ui/reels (HTML fragments)
│   ├── map.py                  # /api/map (JSON) + /ui/map (SVG fragment)
│   └── ai_categorize.py        # /api/ai/categorize
├── ai/
│   ├── __init__.py
│   ├── prompts.py              # RESPONSE_SCHEMA, build_system_prompt()
│   └── client.py                # categorize()
├── templates/
│   ├── base.html
│   ├── index.html
│   └── partials/
│       ├── map.html
│       └── reel_list.html
└── static/
    └── css/
        └── style.css

data/.gitkeep
tests/
├── conftest.py
├── test_models.py
├── test_locations_api.py
├── test_reels_api.py
├── test_layout.py
├── test_map_api.py
├── test_ui_fragments.py
└── test_ai_categorize.py
Dockerfile
.dockerignore
```

---

### Task 1: Project dependencies and test scaffold

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: a `client` pytest fixture (FastAPI `TestClient` with an isolated in-memory DB session) that every later API test depends on.

- [ ] **Step 1: Update `pyproject.toml` with all dependencies needed for the whole plan**

```toml
[project]
name = "reelorganizer"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.128.8",
    "uvicorn>=0.39.0",
    "sqlmodel>=0.0.22",
    "jinja2>=3.1.4",
    "python-multipart>=0.0.9",
    "anthropic>=0.69.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3.0",
    "httpx>=0.27.0",
]
```

- [ ] **Step 2: Install dependencies**

Run: `uv sync`
Expected: dependencies resolve and install without error.

- [ ] **Step 3: Create `tests/__init__.py`** (empty file, makes `tests` a package)

```python
```

- [ ] **Step 4: Create `tests/conftest.py` with the shared `client` fixture**

```python
import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.db import get_session


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
```

Note: `app.main` and `app.db` don't exist yet — this fixture will start working once Task 2 and Task 7 land. That's expected; this task only lays the file down.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py
git commit -m "chore: add project dependencies and shared test fixtures"
```

---

### Task 2: Database engine and session dependency

**Files:**
- Create: `app/__init__.py`
- Create: `app/db.py`

**Interfaces:**
- Produces: `engine` (SQLAlchemy engine), `create_db_and_tables()`, `get_session()` (FastAPI dependency, yields a `Session`).

- [ ] **Step 1: Create `app/__init__.py`** (empty, makes `app` a package)

```python
```

- [ ] **Step 2: Create `app/db.py`**

```python
import os

from sqlmodel import Session, SQLModel, create_engine

DB_PATH = os.environ.get("REEL_DB_PATH", "data/japan_reels.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def create_db_and_tables() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
```

- [ ] **Step 3: Verify it imports cleanly**

Run: `python -c "from app.db import engine, create_db_and_tables, get_session; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add app/__init__.py app/db.py
git commit -m "feat: add SQLite engine and session dependency"
```

---

### Task 3: Taxonomy constants

**Files:**
- Create: `app/taxonomy.py`
- Test: `tests/test_taxonomy.py`

**Interfaces:**
- Produces: `TAXONOMY: dict[str, dict]` (keys: `label`, `icon`, `color`), `VALID_TYPES: set[str]`.

- [ ] **Step 1: Write the failing test**

```python
from app.taxonomy import TAXONOMY, VALID_TYPES


def test_taxonomy_has_seven_fixed_types():
    assert VALID_TYPES == {
        "food", "culture", "nature", "shopping", "stay", "transport", "experience",
    }


def test_every_type_has_label_icon_and_color():
    for type_key, info in TAXONOMY.items():
        assert "label" in info
        assert "icon" in info
        assert "color" in info
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_taxonomy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.taxonomy'`

- [ ] **Step 3: Create `app/taxonomy.py`**

```python
TAXONOMY = {
    "food": {"label": "Cibo", "icon": "🍜", "color": "#A63A2E"},
    "culture": {"label": "Cultura", "icon": "⛩️", "color": "#35496B"},
    "nature": {"label": "Natura", "icon": "🌸", "color": "#7A8F5E"},
    "shopping": {"label": "Shopping", "icon": "🛍️", "color": "#B08D57"},
    "stay": {"label": "Alloggio", "icon": "🏨", "color": "#5B4636"},
    "transport": {"label": "Trasporti", "icon": "🚄", "color": "#1F2C47"},
    "experience": {"label": "Esperienza", "icon": "🎡", "color": "#8E5572"},
}

VALID_TYPES = set(TAXONOMY.keys())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_taxonomy.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/taxonomy.py tests/test_taxonomy.py
git commit -m "feat: add fixed reel-type taxonomy"
```

---

### Task 4: Location model

**Files:**
- Create: `app/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `new_uuid() -> str`, `Location` SQLModel table (`id`, `name`, `is_hub`, `parent_id`, `x`, `y`).

- [ ] **Step 1: Write the failing test**

```python
from sqlmodel import SQLModel, Session, create_engine

from app.models import Location


def test_create_hub_and_satellite_location():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
        session.add(hub)
        session.commit()
        session.refresh(hub)

        satellite = Location(name="Nikko", is_hub=False, parent_id=hub.id)
        session.add(satellite)
        session.commit()
        session.refresh(satellite)

        assert hub.id is not None
        assert satellite.parent_id == hub.id
        assert satellite.is_hub is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Create `app/models.py` with `Location` only**

```python
import uuid
from typing import Optional

from sqlmodel import Field, SQLModel


def new_uuid() -> str:
    return str(uuid.uuid4())


class Location(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = Field(default=None, foreign_key="location.id")
    x: Optional[float] = None
    y: Optional[float] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: add Location model"
```

---

### Task 5: Reel and ReelType models

**Files:**
- Modify: `app/models.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Consumes: `Location`, `new_uuid()` (Task 4).
- Produces: `Reel` SQLModel table (`id`, `link`, `location_id`, `note`, `created_at`), `ReelType` SQLModel table (`reel_id`, `type`, composite PK).

- [ ] **Step 1: Add the failing test to `tests/test_models.py`**

```python
from datetime import datetime

from app.models import Location, Reel, ReelType


def test_create_reel_with_types():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
        session.add(hub)
        session.commit()
        session.refresh(hub)

        reel = Reel(link="https://instagram.com/reel/abc", location_id=hub.id, note="Ramen spot")
        session.add(reel)
        session.commit()
        session.refresh(reel)

        session.add(ReelType(reel_id=reel.id, type="food"))
        session.add(ReelType(reel_id=reel.id, type="culture"))
        session.commit()

        assert isinstance(reel.created_at, datetime)
        types = session.exec(
            select(ReelType).where(ReelType.reel_id == reel.id)
        ).all()
        assert {t.type for t in types} == {"food", "culture"}
```

Add the missing import at the top of the file: `from sqlmodel import select`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'Reel' from 'app.models'`

- [ ] **Step 3: Add `Reel` and `ReelType` to `app/models.py`**

```python
from datetime import datetime


class Reel(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    link: str
    location_id: str = Field(foreign_key="location.id")
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReelType(SQLModel, table=True):
    reel_id: str = Field(foreign_key="reel.id", primary_key=True)
    type: str = Field(primary_key=True)
```

(Add the `datetime` import at the top alongside the existing `uuid`/`typing` imports.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: add Reel and ReelType models"
```

---

### Task 6: Seed data

**Files:**
- Create: `app/seed.py`
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: `Location` (Task 4).
- Produces: `seed_if_empty(session: Session) -> None`.

- [ ] **Step 1: Write the failing test**

```python
from sqlmodel import SQLModel, Session, create_engine, select

from app.models import Location
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.seed'`

- [ ] **Step 3: Create `app/seed.py`**

```python
from sqlmodel import Session, select

from app.models import Location

HUBS = [
    ("Sapporo / Hokkaido", 100.0, 50.0),
    ("Sendai / Tohoku", 150.0, 150.0),
    ("Tokyo / Kanto", 200.0, 250.0),
    ("Nagoya / Chubu", 180.0, 320.0),
    ("Kyoto - Osaka / Kansai", 150.0, 380.0),
    ("Hiroshima / Chugoku", 100.0, 420.0),
    ("Matsuyama / Shikoku", 120.0, 460.0),
    ("Fukuoka / Kyushu", 80.0, 480.0),
    ("Okinawa", 60.0, 560.0),
]

SATELLITES = [
    ("Nikko", "Tokyo / Kanto"),
    ("Kamakura", "Tokyo / Kanto"),
    ("Hakone", "Tokyo / Kanto"),
    ("Kawagoe", "Tokyo / Kanto"),
    ("Nara", "Kyoto - Osaka / Kansai"),
    ("Uji", "Kyoto - Osaka / Kansai"),
    ("Himeji", "Kyoto - Osaka / Kansai"),
    ("Miyajima", "Hiroshima / Chugoku"),
    ("Otaru", "Sapporo / Hokkaido"),
    ("Dazaifu", "Fukuoka / Kyushu"),
]


def seed_if_empty(session: Session) -> None:
    existing = session.exec(select(Location)).first()
    if existing is not None:
        return

    hub_by_name: dict[str, Location] = {}
    for name, x, y in HUBS:
        hub = Location(name=name, is_hub=True, x=x, y=y)
        session.add(hub)
        session.flush()
        hub_by_name[name] = hub

    for name, hub_name in SATELLITES:
        parent = hub_by_name[hub_name]
        session.add(Location(name=name, is_hub=False, parent_id=parent.id))

    session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_seed.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/seed.py tests/test_seed.py
git commit -m "feat: add default hub and satellite seed data"
```

---

### Task 7: FastAPI app bootstrap with lifespan

**Files:**
- Create: `app/main.py`
- Create: `data/.gitkeep`
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: `create_db_and_tables`, `engine` (Task 2), `seed_if_empty` (Task 6).
- Produces: `app` (the FastAPI instance) — every later task imports and extends this. A `GET /health` route.

- [ ] **Step 1: Write the failing test**

```python
def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Create `app/main.py`**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.seed import seed_if_empty


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        seed_if_empty(session)
    yield


app = FastAPI(title="Japan Reel Organizer", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Create `data/.gitkeep`** (empty file, keeps the directory in git even though `data/*.db` is ignored)

```
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_health.py -v`
Expected: PASS

- [ ] **Step 6: Run the full test suite to confirm nothing regressed**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add app/main.py data/.gitkeep tests/test_health.py
git commit -m "feat: bootstrap FastAPI app with lifespan DB setup"
```

---

### Task 8: `GET /api/locations` — list with reel counts

**Files:**
- Create: `app/routers/__init__.py`
- Create: `app/routers/locations.py`
- Modify: `app/main.py`
- Test: `tests/test_locations_api.py`

**Interfaces:**
- Consumes: `get_session` (Task 2), `Location`, `Reel` (Tasks 4–5), `app` (Task 7).
- Produces: `router` (APIRouter, included as `locations.router` in `app.main`). Response shape: `[{"id", "name", "is_hub", "parent_id", "x", "y", "reel_count"}]`.

- [ ] **Step 1: Create `app/routers/__init__.py`** (empty)

```python
```

- [ ] **Step 2: Write the failing test**

```python
from app.models import Location, Reel


def test_list_locations_includes_reel_counts(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    session.add(Reel(link="https://instagram.com/reel/1", location_id=hub.id))
    session.add(Reel(link="https://instagram.com/reel/2", location_id=hub.id))
    session.commit()

    response = client.get("/api/locations")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Tokyo / Kanto"
    assert data[0]["reel_count"] == 2


def test_list_locations_empty(client):
    response = client.get("/api/locations")
    assert response.status_code == 200
    assert response.json() == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_locations_api.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 4: Create `app/routers/locations.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models import Location, Reel

router = APIRouter(prefix="/api/locations", tags=["locations"])


@router.get("")
def list_locations(session: Session = Depends(get_session)):
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
            "x": loc.x,
            "y": loc.y,
            "reel_count": counts.get(loc.id, 0),
        }
        for loc in locations
    ]
```

- [ ] **Step 5: Wire the router into `app/main.py`**

Add near the top:
```python
from app.routers import locations
```

Add after `app = FastAPI(...)`:
```python
app.include_router(locations.router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_locations_api.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add app/routers/__init__.py app/routers/locations.py app/main.py tests/test_locations_api.py
git commit -m "feat: add GET /api/locations with reel counts"
```

---

### Task 9: `POST /api/locations` — create hub or satellite

**Files:**
- Modify: `app/routers/locations.py`
- Modify: `tests/test_locations_api.py`

**Interfaces:**
- Produces: `POST /api/locations` accepting `{"name": str, "is_hub": bool, "parent_id": str | None, "x": float | None, "y": float | None}`, returns the created location (201).

- [ ] **Step 1: Add the failing test**

```python
def test_create_hub_location(client):
    response = client.post(
        "/api/locations",
        json={"name": "Test Hub", "is_hub": True, "x": 10.0, "y": 20.0},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Hub"
    assert data["id"]


def test_create_satellite_location(client):
    hub_resp = client.post("/api/locations", json={"name": "Parent Hub", "is_hub": True})
    hub_id = hub_resp.json()["id"]

    response = client.post(
        "/api/locations",
        json={"name": "Satellite Town", "is_hub": False, "parent_id": hub_id},
    )
    assert response.status_code == 201
    assert response.json()["parent_id"] == hub_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_locations_api.py -v`
Expected: FAIL with 405 Method Not Allowed

- [ ] **Step 3: Add the create endpoint to `app/routers/locations.py`**

Add imports:
```python
from typing import Optional

from fastapi import status
from pydantic import BaseModel
```

Add the request model and endpoint:
```python
class LocationCreate(BaseModel):
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None


@router.post("", status_code=status.HTTP_201_CREATED)
def create_location(payload: LocationCreate, session: Session = Depends(get_session)):
    location = Location(**payload.model_dump())
    session.add(location)
    session.commit()
    session.refresh(location)
    return {
        "id": location.id,
        "name": location.name,
        "is_hub": location.is_hub,
        "parent_id": location.parent_id,
        "x": location.x,
        "y": location.y,
        "reel_count": 0,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_locations_api.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/routers/locations.py tests/test_locations_api.py
git commit -m "feat: add POST /api/locations"
```

---

### Task 10: `DELETE /api/locations/{id}`

**Files:**
- Modify: `app/routers/locations.py`
- Modify: `tests/test_locations_api.py`

**Interfaces:**
- Produces: `DELETE /api/locations/{location_id}` — cascades: deletes the location's reels (and their `ReelType` rows) first, then the location. 404 if not found.

- [ ] **Step 1: Add the failing test**

```python
from app.models import Reel, ReelType


def test_delete_location_cascades_reels(client, session):
    hub_resp = client.post("/api/locations", json={"name": "Doomed Hub", "is_hub": True})
    hub_id = hub_resp.json()["id"]

    reel = Reel(link="https://instagram.com/reel/x", location_id=hub_id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    response = client.delete(f"/api/locations/{hub_id}")
    assert response.status_code == 204

    assert client.get("/api/locations").json() == []


def test_delete_missing_location_returns_404(client):
    response = client.delete("/api/locations/does-not-exist")
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_locations_api.py -v`
Expected: FAIL with 405 Method Not Allowed

- [ ] **Step 3: Add the delete endpoint to `app/routers/locations.py`**

Add import: `from fastapi import HTTPException` (alongside the existing `fastapi` import), and `from app.models import ReelType` (alongside `Location, Reel`).

```python
@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: str, session: Session = Depends(get_session)):
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")

    reels = session.exec(select(Reel).where(Reel.location_id == location_id)).all()
    for reel in reels:
        types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
        for t in types:
            session.delete(t)
        session.delete(reel)

    session.delete(location)
    session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_locations_api.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/routers/locations.py tests/test_locations_api.py
git commit -m "feat: add DELETE /api/locations/{id} with cascade"
```

---

### Task 11: `GET /api/reels` — list with filters

**Files:**
- Create: `app/routers/reels.py`
- Modify: `app/main.py`
- Test: `tests/test_reels_api.py`

**Interfaces:**
- Consumes: `get_session`, `Location`, `Reel`, `ReelType` (earlier tasks).
- Produces: `router` (`reels.router`), `GET /api/reels?location_id=&type=`. Response: `[{"id", "link", "location_id", "note", "created_at", "types": [str]}]`.

- [ ] **Step 1: Write the failing test**

```python
from app.models import Location, Reel, ReelType


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reels_api.py -v`
Expected: FAIL with 404 (route doesn't exist)

- [ ] **Step 3: Create `app/routers/reels.py`**

```python
from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models import Reel, ReelType

router = APIRouter(prefix="/api/reels", tags=["reels"])


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
```

- [ ] **Step 4: Wire the router into `app/main.py`**

Modify the import line: `from app.routers import locations, reels`

Add after `app.include_router(locations.router)`:
```python
app.include_router(reels.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_reels_api.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add app/routers/reels.py app/main.py tests/test_reels_api.py
git commit -m "feat: add GET /api/reels with location and type filters"
```

---

### Task 12: `POST /api/reels`

**Files:**
- Modify: `app/routers/reels.py`
- Modify: `tests/test_reels_api.py`

**Interfaces:**
- Produces: `POST /api/reels` accepting `{"link": str, "location_id": str, "note": str | None, "types": [str]}`. Filters `types` against `VALID_TYPES` (Task 3) before saving. Returns the created reel (201).

- [ ] **Step 1: Add the failing test**

```python
def test_create_reel_filters_invalid_types(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reels_api.py -v`
Expected: FAIL with 405 Method Not Allowed

- [ ] **Step 3: Add the create endpoint to `app/routers/reels.py`**

Add imports:
```python
from fastapi import status
from pydantic import BaseModel

from app.taxonomy import VALID_TYPES
```

```python
class ReelCreate(BaseModel):
    link: str
    location_id: str
    note: Optional[str] = None
    types: list[str] = []


@router.post("", status_code=status.HTTP_201_CREATED)
def create_reel(payload: ReelCreate, session: Session = Depends(get_session)):
    reel = Reel(link=payload.link, location_id=payload.location_id, note=payload.note)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    for type_value in payload.types:
        if type_value in VALID_TYPES:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    return _serialize_reel(session, reel)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reels_api.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/routers/reels.py tests/test_reels_api.py
git commit -m "feat: add POST /api/reels with taxonomy validation"
```

---

### Task 13: `DELETE /api/reels/{id}`

**Files:**
- Modify: `app/routers/reels.py`
- Modify: `tests/test_reels_api.py`

**Interfaces:**
- Produces: `DELETE /api/reels/{reel_id}` — deletes `ReelType` rows then the reel. 404 if not found.

- [ ] **Step 1: Add the failing test**

```python
def test_delete_reel(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
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


def test_delete_missing_reel_returns_404(client):
    response = client.delete("/api/reels/does-not-exist")
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reels_api.py -v`
Expected: FAIL with 405 Method Not Allowed

- [ ] **Step 3: Add the delete endpoint to `app/routers/reels.py`**

Add import: `from fastapi import HTTPException` (alongside existing `fastapi` import).

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_reels_api.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/routers/reels.py tests/test_reels_api.py
git commit -m "feat: add DELETE /api/reels/{id}"
```

---

### Task 14: Base Jinja2 template and index route

**Files:**
- Create: `app/web.py`
- Create: `app/templates/base.html`
- Create: `app/templates/index.html`
- Create: `app/static/css/style.css`
- Modify: `app/main.py`
- Test: `tests/test_index_page.py`

**Interfaces:**
- Produces: `templates` (shared `Jinja2Templates` instance in `app/web.py`, imported by every later template-rendering task). `GET /` renders `index.html`.

- [ ] **Step 1: Write the failing test**

```python
def test_index_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Japan Reel Organizer" in response.text
    assert 'id="map-container"' in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_index_page.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Create `app/web.py`**

```python
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
```

- [ ] **Step 4: Create `app/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Japan Reel Organizer</title>
    <link rel="stylesheet" href="/static/css/style.css">
    <script src="https://unpkg.com/htmx.org@1.9.12"></script>
</head>
<body>
    <header>
        <h1>Japan Reel Organizer</h1>
    </header>
    <main>
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

- [ ] **Step 5: Create `app/templates/index.html`**

```html
{% extends "base.html" %}
{% block content %}
<section id="map-container" hx-get="/ui/map" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento mappa...</p>
</section>
<section id="reel-list" hx-get="/ui/reels" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento reel...</p>
</section>
{% endblock %}
```

- [ ] **Step 6: Create a minimal `app/static/css/style.css`** (real polish comes in Task 24)

```css
body {
    margin: 0;
    font-family: sans-serif;
}
```

- [ ] **Step 7: Wire templates and static files into `app/main.py`**

Add imports:
```python
from fastapi import Request
from fastapi.staticfiles import StaticFiles

from app.web import templates
```

Add after `app.include_router(reels.router)`:
```python
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})
```

- [ ] **Step 8: Run test to verify it passes**

Run: `pytest tests/test_index_page.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add app/web.py app/templates app/static app/main.py tests/test_index_page.py
git commit -m "feat: add base Jinja2 template and index route"
```

---

### Task 15: Radial layout calculation

**Files:**
- Create: `app/layout.py`
- Test: `tests/test_layout.py`

**Interfaces:**
- Produces: `radial_positions(hub_x: float, hub_y: float, count: int, radius: float = 60.0) -> list[tuple[float, float]]`.

- [ ] **Step 1: Write the failing test**

```python
import math

from app.layout import radial_positions


def test_radial_positions_empty_when_no_satellites():
    assert radial_positions(0.0, 0.0, 0) == []


def test_radial_positions_returns_one_point_per_satellite():
    positions = radial_positions(100.0, 100.0, 4, radius=50.0)
    assert len(positions) == 4


def test_radial_positions_first_point_is_at_angle_zero():
    positions = radial_positions(100.0, 100.0, 4, radius=50.0)
    x, y = positions[0]
    assert math.isclose(x, 150.0, abs_tol=1e-6)
    assert math.isclose(y, 100.0, abs_tol=1e-6)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_layout.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.layout'`

- [ ] **Step 3: Create `app/layout.py`**

```python
import math


def radial_positions(
    hub_x: float, hub_y: float, count: int, radius: float = 60.0
) -> list[tuple[float, float]]:
    if count == 0:
        return []
    positions = []
    for i in range(count):
        angle = (2 * math.pi * i) / count
        x = hub_x + radius * math.cos(angle)
        y = hub_y + radius * math.sin(angle)
        positions.append((x, y))
    return positions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_layout.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/layout.py tests/test_layout.py
git commit -m "feat: add radial layout calculation for satellite stations"
```

---

### Task 16: `GET /api/map` — locations with computed positions

**Files:**
- Create: `app/routers/map.py`
- Modify: `app/main.py`
- Test: `tests/test_map_api.py`

**Interfaces:**
- Consumes: `radial_positions` (Task 15), `Location`, `Reel` (Tasks 4–5).
- Produces: `router` (`map.router`), `GET /api/map`. Response: `[{"id", "name", "is_hub", "parent_id", "x", "y", "reel_count"}]` with satellite `x`/`y` computed radially around their hub.

- [ ] **Step 1: Write the failing test**

```python
from app.models import Location


def test_map_computes_satellite_positions(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    satellite = Location(name="Nikko", is_hub=False, parent_id=hub.id)
    session.add(satellite)
    session.commit()

    response = client.get("/api/map")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    hub_entry = next(d for d in data if d["is_hub"])
    sat_entry = next(d for d in data if not d["is_hub"])
    assert hub_entry["x"] == 200.0
    assert sat_entry["parent_id"] == hub.id
    assert sat_entry["x"] != hub_entry["x"] or sat_entry["y"] != hub_entry["y"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_map_api.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Create `app/routers/map.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.layout import radial_positions
from app.models import Location, Reel

router = APIRouter(prefix="/api/map", tags=["map"])


def compute_map(session: Session) -> list[dict]:
    locations = session.exec(select(Location)).all()
    counts = dict(
        session.exec(
            select(Reel.location_id, func.count(Reel.id)).group_by(Reel.location_id)
        ).all()
    )

    hubs = [loc for loc in locations if loc.is_hub]
    satellites_by_hub: dict[str, list[Location]] = {}
    for loc in locations:
        if not loc.is_hub and loc.parent_id is not None:
            satellites_by_hub.setdefault(loc.parent_id, []).append(loc)

    result = []
    for hub in hubs:
        result.append(
            {
                "id": hub.id,
                "name": hub.name,
                "is_hub": True,
                "parent_id": None,
                "x": hub.x,
                "y": hub.y,
                "reel_count": counts.get(hub.id, 0),
            }
        )
        satellites = satellites_by_hub.get(hub.id, [])
        positions = radial_positions(hub.x or 0.0, hub.y or 0.0, len(satellites))
        for satellite, (sx, sy) in zip(satellites, positions):
            result.append(
                {
                    "id": satellite.id,
                    "name": satellite.name,
                    "is_hub": False,
                    "parent_id": hub.id,
                    "x": sx,
                    "y": sy,
                    "reel_count": counts.get(satellite.id, 0),
                }
            )
    return result


@router.get("")
def get_map(session: Session = Depends(get_session)):
    return compute_map(session)
```

- [ ] **Step 4: Wire the router into `app/main.py`**

Modify the import line: `from app.routers import locations, map as map_router, reels`

Add after `app.include_router(reels.router)`:
```python
app.include_router(map_router.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_map_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/routers/map.py app/main.py tests/test_map_api.py
git commit -m "feat: add GET /api/map with computed radial satellite positions"
```

---

### Task 17: `GET /ui/map` — SVG fragment with type filter

**Files:**
- Create: `app/templates/partials/map.html`
- Modify: `app/routers/map.py`
- Test: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `compute_map` (Task 16), `templates` (Task 14), `TAXONOMY` (Task 3).
- Produces: `GET /ui/map?type=` returning an HTML fragment with an inline SVG and type-filter chips.

- [ ] **Step 1: Write the failing test**

```python
import re

from app.models import Location, Reel, ReelType


def test_ui_map_renders_svg_with_stations(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
    session.add(hub)
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200
    assert "<svg" in response.text
    assert "Tokyo / Kanto" in response.text


def test_ui_map_includes_type_filter_chips(client):
    response = client.get("/ui/map")
    assert response.status_code == 200
    assert "Cibo" in response.text
    assert 'hx-get="/ui/map?type=food"' in response.text


def test_ui_map_dims_stations_without_the_selected_type(client, session):
    hub_with_food = Location(name="Has Food", is_hub=True, x=10.0, y=10.0)
    hub_without_food = Location(name="No Food", is_hub=True, x=20.0, y=20.0)
    session.add(hub_with_food)
    session.add(hub_without_food)
    session.commit()
    session.refresh(hub_with_food)
    session.refresh(hub_without_food)

    reel = Reel(link="https://instagram.com/reel/f", location_id=hub_with_food.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    response = client.get("/ui/map?type=food")
    assert response.status_code == 200

    with_food_class = re.search(
        rf'class="([^"]*)" data-location-id="{hub_with_food.id}"', response.text
    ).group(1)
    without_food_class = re.search(
        rf'class="([^"]*)" data-location-id="{hub_without_food.id}"', response.text
    ).group(1)

    assert "dimmed" not in with_food_class
    assert "dimmed" in without_food_class
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_fragments.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Create `app/templates/partials/map.html`**

```html
<div class="map-filters">
    <a href="#" class="chip {{ 'active' if not active_type else '' }}"
       hx-get="/ui/map" hx-target="#map-container" hx-swap="innerHTML">Tutti</a>
    {% for key, info in taxonomy.items() %}
    <a href="#" class="chip {{ 'active' if active_type == key else '' }}"
       data-type="{{ key }}" style="border-color: {{ info.color }};"
       hx-get="/ui/map?type={{ key }}" hx-target="#map-container" hx-swap="innerHTML">
        {{ info.icon }} {{ info.label }}
    </a>
    {% endfor %}
</div>
<svg viewBox="0 0 400 650" class="japan-map">
    {% for loc in locations %}
    {% if not loc.is_hub %}
    <line x1="{{ hubs_by_id[loc.parent_id].x }}" y1="{{ hubs_by_id[loc.parent_id].y }}"
          x2="{{ loc.x }}" y2="{{ loc.y }}" class="satellite-line" />
    {% endif %}
    {% endfor %}
    {% for loc in locations %}
    <circle cx="{{ loc.x }}" cy="{{ loc.y }}"
            r="{{ 8 if loc.is_hub else 4 }}"
            class="station {{ 'hub' if loc.is_hub else 'satellite' }}{{ ' dimmed' if active_type and loc.id not in matching_location_ids else '' }}"
            data-location-id="{{ loc.id }}" />
    <text x="{{ loc.x }}" y="{{ loc.y - 10 }}" class="station-label">{{ loc.name }}</text>
    {% endfor %}
</svg>
```

- [ ] **Step 4: Add a `locations_with_type` helper and the `/ui/map` endpoint to `app/routers/map.py`**

Add imports:
```python
from fastapi import Request

from app.models import ReelType
from app.taxonomy import TAXONOMY
from app.web import templates
```

The `/ui/map` route needs a different path prefix than `/api/map`, so it goes on a **second router in the same file**. Replace the router declaration at the top of the file:

```python
router = APIRouter(prefix="/api/map", tags=["map"])
ui_router = APIRouter(prefix="/ui", tags=["map-ui"])
```

Add a helper that finds which locations have at least one reel of the given type:

```python
def locations_with_type(session: Session, type_value: str) -> set[str]:
    reel_ids = set(
        session.exec(select(ReelType.reel_id).where(ReelType.type == type_value)).all()
    )
    if not reel_ids:
        return set()
    return set(
        session.exec(select(Reel.location_id).where(Reel.id.in_(reel_ids))).all()
    )
```

Then add the UI endpoint using `ui_router`:

```python
@ui_router.get("/map")
def ui_map(request: Request, type: str = None, session: Session = Depends(get_session)):
    locations = compute_map(session)
    hubs_by_id = {loc["id"]: loc for loc in locations if loc["is_hub"]}
    matching_location_ids = locations_with_type(session, type) if type else set()
    return templates.TemplateResponse(
        request,
        "partials/map.html",
        {
            "locations": locations,
            "hubs_by_id": hubs_by_id,
            "taxonomy": TAXONOMY,
            "active_type": type,
            "matching_location_ids": matching_location_ids,
        },
    )
```

- [ ] **Step 5: Include `ui_router` in `app/main.py`**

Modify the import: `from app.routers import locations, map as map_router, reels`

Add after `app.include_router(map_router.router)`:
```python
app.include_router(map_router.ui_router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_ui_fragments.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add app/templates/partials/map.html app/routers/map.py app/main.py tests/test_ui_fragments.py
git commit -m "feat: add GET /ui/map SVG fragment with type filter chips"
```

---

### Task 18: `GET/POST/DELETE /ui/reels` — HTML fragments for the reel list and form

**Files:**
- Create: `app/templates/partials/reel_list.html`
- Modify: `app/routers/reels.py`
- Modify: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `_serialize_reel`, `Reel`, `ReelType`, `VALID_TYPES` (Task 3, 11–13), `templates` (Task 14).
- Produces: `GET /ui/reels` (list + add form fragment), `POST /ui/reels` (create, returns updated fragment), `DELETE /ui/reels/{id}` (delete, returns updated fragment).

- [ ] **Step 1: Add the failing tests**

```python
from app.models import Location, Reel


def test_ui_reels_get_renders_list_and_form(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/x", location_id=hub.id, note="Nice spot"))
    session.commit()

    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert "Nice spot" in response.text
    assert "<form" in response.text


def test_ui_reels_post_creates_and_returns_fragment(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/reels",
        data={"link": "https://instagram.com/reel/new", "location_id": hub.id, "note": "New one", "types": ["food"]},
    )
    assert response.status_code == 200
    assert "New one" in response.text


def test_ui_reels_delete_returns_updated_fragment(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/gone", location_id=hub.id, note="Bye")
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.delete(f"/ui/reels/{reel.id}")
    assert response.status_code == 200
    assert "Bye" not in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_fragments.py -v`
Expected: FAIL with 404 on `/ui/reels`

- [ ] **Step 3: Create `app/templates/partials/reel_list.html`**

```html
<form hx-post="/ui/reels" hx-target="#reel-list" hx-swap="innerHTML">
    <input type="url" name="link" placeholder="Link Instagram" required>
    <select name="location_id" required>
        {% for loc in locations %}
        <option value="{{ loc.id }}">{{ loc.name }}</option>
        {% endfor %}
    </select>
    <input type="text" name="note" placeholder="Nota (opzionale)">
    {% for key, info in taxonomy.items() %}
    <label><input type="checkbox" name="types" value="{{ key }}"> {{ info.icon }} {{ info.label }}</label>
    {% endfor %}
    <button type="submit">Aggiungi reel</button>
</form>
<ul class="reel-list">
    {% for reel in reels %}
    <li>
        <a href="{{ reel.link }}" target="_blank">{{ reel.link }}</a>
        {% if reel.note %}<span class="note">{{ reel.note }}</span>{% endif %}
        <span class="types">{% for t in reel.types %}{{ taxonomy[t].icon }}{% endfor %}</span>
        <button hx-delete="/ui/reels/{{ reel.id }}" hx-target="#reel-list" hx-swap="innerHTML">Elimina</button>
    </li>
    {% endfor %}
</ul>
```

- [ ] **Step 4: Add `/ui/reels` endpoints to `app/routers/reels.py`**

Add imports at the top:
```python
from fastapi import HTTPException, Request

from app.models import Location
from app.taxonomy import TAXONOMY
from app.web import templates

ui_router = APIRouter(prefix="/ui", tags=["reels-ui"])
```

Add a shared context helper and the three endpoints at the end of the file:

```python
def _reel_list_context(session: Session) -> dict:
    reels = session.exec(select(Reel)).all()
    locations = session.exec(select(Location)).all()
    return {
        "reels": [_serialize_reel(session, r) for r in reels],
        "locations": locations,
        "taxonomy": TAXONOMY,
    }


@ui_router.get("/reels")
def ui_list_reels(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/reel_list.html", _reel_list_context(session))


@ui_router.post("/reels")
def ui_create_reel(
    request: Request,
    link: str = Form(...),
    location_id: str = Form(...),
    note: Optional[str] = Form(None),
    types: list[str] = Form([]),
    session: Session = Depends(get_session),
):
    reel = Reel(link=link, location_id=location_id, note=note)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    for type_value in types:
        if type_value in VALID_TYPES:
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

Add `Form` to the `fastapi` import at the top of the file (`from fastapi import APIRouter, Depends, Form, HTTPException, Request, status`).

- [ ] **Step 5: Include `ui_router` in `app/main.py`**

Modify the import: `from app.routers import locations, map as map_router, reels`

Add after `app.include_router(map_router.ui_router)`:
```python
app.include_router(reels.ui_router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_ui_fragments.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Run the full suite**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add app/templates/partials/reel_list.html app/routers/reels.py app/main.py tests/test_ui_fragments.py
git commit -m "feat: add HTMX-driven reel list and add/delete form fragments"
```

---

### Task 19: AiSession and AiMessage models

**Files:**
- Modify: `app/models.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Produces: `AiSession` (`id`, `created_at`, `updated_at`), `AiMessage` (`id`, `session_id`, `role`, `content`, `created_at`).

- [ ] **Step 1: Add the failing test to `tests/test_models.py`**

```python
from app.models import AiMessage, AiSession


def test_create_ai_session_with_messages():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        ai_session = AiSession()
        session.add(ai_session)
        session.commit()
        session.refresh(ai_session)

        session.add(AiMessage(session_id=ai_session.id, role="user", content="Un reel di ramen a Tokyo"))
        session.commit()

        messages = session.exec(
            select(AiMessage).where(AiMessage.session_id == ai_session.id)
        ).all()
        assert len(messages) == 1
        assert messages[0].role == "user"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'AiSession' from 'app.models'`

- [ ] **Step 3: Add `AiSession` and `AiMessage` to `app/models.py`**

```python
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: add AiSession and AiMessage models for persisted AI conversations"
```

---

### Task 20: AI prompts module — JSON schema and system prompt

**Files:**
- Create: `app/ai/__init__.py`
- Create: `app/ai/prompts.py`
- Test: `tests/test_ai_prompts.py`

**Interfaces:**
- Produces: `RESPONSE_SCHEMA: dict` (JSON Schema matching spec §5.3 step 3), `build_system_prompt(hub_names: list[str]) -> str`.

- [ ] **Step 1: Create `app/ai/__init__.py`** (empty)

```python
```

- [ ] **Step 2: Write the failing test**

```python
from app.ai.prompts import RESPONSE_SCHEMA, build_system_prompt


def test_response_schema_has_required_fields():
    assert RESPONSE_SCHEMA["required"] == [
        "place_name", "near_hub", "types", "note", "confidence", "question",
    ]
    assert RESPONSE_SCHEMA["additionalProperties"] is False


def test_build_system_prompt_includes_hub_names():
    prompt = build_system_prompt(["Tokyo / Kanto", "Kyoto - Osaka / Kansai"])
    assert "Tokyo / Kanto" in prompt
    assert "Kyoto - Osaka / Kansai" in prompt
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_ai_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ai.prompts'`

- [ ] **Step 4: Create `app/ai/prompts.py`**

```python
from typing import Iterable

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "place_name": {"type": "string"},
        "near_hub": {"type": ["string", "null"]},
        "types": {"type": "array", "items": {"type": "string"}},
        "note": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "question": {"type": ["string", "null"]},
    },
    "required": ["place_name", "near_hub", "types", "note", "confidence", "question"],
    "additionalProperties": False,
}


def build_system_prompt(hub_names: Iterable[str]) -> str:
    hubs_list = ", ".join(hub_names) if hub_names else "nessuno ancora"
    return (
        "Sei un assistente che aiuta a categorizzare reel Instagram salvati per un viaggio in Giappone. "
        "L'utente ti invia un link e una didascalia (o una descrizione libera) di un reel. "
        "Non puoi aprire il link: lavora solo sul testo fornito. "
        f"Le tappe principali (hub) gia' esistenti sono: {hubs_list}. "
        "Se il testo corrisponde chiaramente a un hub esistente o a una localita' vicina, usa near_hub per indicarlo. "
        "Se non hai abbastanza informazioni per proporre un luogo con sicurezza, valorizza 'question' con una domanda "
        "di chiarimento e lascia gli altri campi con la tua migliore ipotesi. "
        "Rispondi seguendo esattamente lo schema JSON fornito."
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_ai_prompts.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add app/ai/__init__.py app/ai/prompts.py tests/test_ai_prompts.py
git commit -m "feat: add AI response JSON schema and system prompt builder"
```

---

### Task 21: AI client wrapper

**Files:**
- Create: `app/ai/client.py`
- Test: `tests/test_ai_client.py`

**Interfaces:**
- Consumes: `RESPONSE_SCHEMA`, `build_system_prompt` (Task 20).
- Produces: `MODEL = "claude-haiku-4-5"`, `get_client() -> Anthropic`, `categorize(hub_names: list[str], messages: list[dict]) -> dict`.

- [ ] **Step 1: Write the failing test**

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

    result = ai_client.categorize(["Tokyo / Kanto"], [{"role": "user", "content": "Ramen a Tokyo"}])

    assert result == expected
    assert fake_client.messages.last_call_kwargs["model"] == ai_client.MODEL
    assert fake_client.messages.last_call_kwargs["output_config"]["format"]["type"] == "json_schema"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ai.client'`

- [ ] **Step 3: Create `app/ai/client.py`**

```python
import json
import os
from typing import Any, Optional

from anthropic import Anthropic

from app.ai.prompts import RESPONSE_SCHEMA, build_system_prompt

MODEL = "claude-haiku-4-5"

_client: Optional[Anthropic] = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def categorize(hub_names: list[str], messages: list[dict[str, str]]) -> dict[str, Any]:
    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=build_system_prompt(hub_names),
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ai_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ai/client.py tests/test_ai_client.py
git commit -m "feat: add Anthropic client wrapper with structured JSON output"
```

---

### Task 22: `POST /api/ai/categorize`

**Files:**
- Create: `app/routers/ai_categorize.py`
- Modify: `app/main.py`
- Test: `tests/test_ai_categorize.py`

**Interfaces:**
- Consumes: `categorize` (Task 21), `AiSession`, `AiMessage`, `Location` (Tasks 4, 19), `VALID_TYPES` (Task 3).
- Produces: `router` (`ai_categorize.router`), `POST /api/ai/categorize` accepting `{"session_id": str | None, "message": str}`, returning the AI proposal plus `session_id` and an optional `matched_location_id`.

- [ ] **Step 1: Write the failing test**

```python
import json

from app.ai import client as ai_client
from app.models import Location


def test_categorize_creates_session_and_returns_proposal(client, session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()

    def fake_categorize(hub_names, messages):
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
    def fake_categorize(hub_names, messages):
        assert len(messages) == 2
        return {
            "place_name": "Nikko",
            "near_hub": "Tokyo / Kanto",
            "types": ["nature"],
            "note": "Shrine town",
            "confidence": "medium",
            "question": None,
        }

    monkeypatch.setattr(ai_client, "categorize", lambda hub_names, messages: {
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
        lambda hub_names, messages: {
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ai_categorize.py -v`
Expected: FAIL with 404

- [ ] **Step 3: Create `app/routers/ai_categorize.py`**

```python
import json
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.db import get_session
from app.models import AiMessage, AiSession, Location
from app.taxonomy import VALID_TYPES

router = APIRouter(prefix="/api/ai", tags=["ai"])


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
    for loc in session.exec(select(Location)).all():
        loc_name_lower = loc.name.lower()
        if place_name_lower in loc_name_lower or loc_name_lower in place_name_lower:
            return loc.id
    return None


@router.post("/categorize", response_model=CategorizeResponse)
def categorize_reel(payload: CategorizeRequest, session: Session = Depends(get_session)):
    if payload.session_id:
        ai_session = session.get(AiSession, payload.session_id)
    else:
        ai_session = AiSession()
        session.add(ai_session)
        session.commit()
        session.refresh(ai_session)

    session.add(AiMessage(session_id=ai_session.id, role="user", content=payload.message))
    session.commit()

    history = session.exec(
        select(AiMessage)
        .where(AiMessage.session_id == ai_session.id)
        .order_by(AiMessage.created_at)
    ).all()
    api_messages = [{"role": m.role, "content": m.content} for m in history]

    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]

    result = ai_client.categorize(hub_names, api_messages)
    result["types"] = [t for t in result.get("types", []) if t in VALID_TYPES]

    session.add(AiMessage(session_id=ai_session.id, role="assistant", content=json.dumps(result)))
    session.commit()

    matched_location_id = _find_matching_location(session, result["place_name"])

    return CategorizeResponse(session_id=ai_session.id, matched_location_id=matched_location_id, **result)
```

- [ ] **Step 4: Wire the router into `app/main.py`**

Modify the import: `from app.routers import ai_categorize, locations, map as map_router, reels`

Add after `app.include_router(reels.ui_router)`:
```python
app.include_router(ai_categorize.router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_ai_categorize.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full suite**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add app/routers/ai_categorize.py app/main.py tests/test_ai_categorize.py
git commit -m "feat: add POST /api/ai/categorize with persisted conversation and location matching"
```

---

### Task 23: Dockerize

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Test: manual verification (Docker build/run — no pytest coverage for infra files)

**Interfaces:**
- Produces: a container image that runs `uvicorn app.main:app` on port 8000, with `data/` as a mountable volume.

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY app ./app

ENV REEL_DB_PATH=/data/japan_reels.db
VOLUME ["/data"]

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `.dockerignore`**

```
.venv/
.git/
.idea/
__pycache__/
*.pyc
data/*.db
tests/
docs/
.claude/
```

- [ ] **Step 3: Build the image**

Run: `docker build -t japan-reel-organizer .`
Expected: build completes without error.

- [ ] **Step 4: Run the container and verify the health endpoint**

Run:
```bash
docker run --rm -d -p 8000:8000 -v "$(pwd)/data:/data" -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" --name reel-organizer-test japan-reel-organizer
sleep 2
curl -s http://localhost:8000/health
docker stop reel-organizer-test
```
Expected: `curl` prints `{"status":"ok"}`.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat: dockerize the app with a mountable data volume"
```

---

### Task 24: Visual polish — washi/indigo/hanko palette and typography

**Files:**
- Modify: `app/static/css/style.css`
- Modify: `app/templates/base.html`
- Test: `tests/test_index_page.py` (extend)

**Interfaces:**
- Consumes: nothing new — pure styling pass per spec §7.

- [ ] **Step 1: Add the failing test**

```python
def test_index_page_loads_custom_fonts(client):
    response = client.get("/")
    assert "Shippori+Mincho" in response.text
    assert "Zen+Kaku+Gothic+New" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_index_page.py -v`
Expected: FAIL — font links not present yet

- [ ] **Step 3: Add Google Fonts links to `app/templates/base.html`**

Add inside `<head>`, before the `link rel="stylesheet"` line:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@400;600&family=Zen+Kaku+Gothic+New:wght@400;500&family=JetBrains+Mono&display=swap" rel="stylesheet">
```

- [ ] **Step 4: Replace `app/static/css/style.css` with the full palette and typography**

```css
:root {
    --color-paper: #E3E1D4;
    --color-ink: #1F2C47;
    --color-ink-medium: #35496B;
    --color-hanko: #A63A2E;
    --color-gold: #B08D57;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: var(--color-paper);
    color: var(--color-ink);
    font-family: "Zen Kaku Gothic New", sans-serif;
}

h1, h2, h3 {
    font-family: "Shippori Mincho", serif;
    color: var(--color-ink);
}

header {
    padding: 1rem 1.5rem;
    border-bottom: 2px solid var(--color-ink-medium);
}

main {
    padding: 1rem 1.5rem;
    max-width: 900px;
    margin: 0 auto;
}

.chip {
    display: inline-block;
    padding: 0.25rem 0.6rem;
    margin: 0.15rem;
    border: 1px solid var(--color-ink-medium);
    border-radius: 999px;
    font-size: 0.85rem;
    cursor: pointer;
}

.japan-map {
    width: 100%;
    max-width: 400px;
    display: block;
    margin: 0 auto;
}

.station.hub {
    fill: var(--color-ink-medium);
}

.station.satellite {
    fill: var(--color-gold);
}

.satellite-line {
    stroke: var(--color-ink-medium);
    stroke-dasharray: 4 3;
}

.station-label {
    font-size: 10px;
    font-family: "Zen Kaku Gothic New", sans-serif;
    fill: var(--color-ink);
    text-anchor: middle;
}

button, .reel-list button {
    background: var(--color-hanko);
    color: var(--color-paper);
    border: none;
    border-radius: 4px;
    padding: 0.4rem 0.8rem;
    cursor: pointer;
}

.reel-list {
    list-style: none;
    padding: 0;
}

.reel-list li {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--color-ink-medium);
}

.types, .reel-list .note {
    font-family: "JetBrains Mono", monospace;
    font-size: 0.8rem;
    color: var(--color-ink-medium);
}

@media (max-width: 480px) {
    main {
        padding: 0.5rem;
    }
    .japan-map {
        max-width: 100%;
    }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_index_page.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite one final time**

Run: `pytest -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add app/static/css/style.css app/templates/base.html tests/test_index_page.py
git commit -m "style: apply washi/indigo/hanko palette and Japanese-influenced typography"
```

---

## Post-plan manual check

After Task 24, run the app locally and click through the golden path before considering the feature done:

```bash
export ANTHROPIC_API_KEY=...
uv run uvicorn app.main:app --reload
```

Open `http://localhost:8000`, verify: the map renders with seeded hubs, adding a reel via the form updates both the list and (after a page reload) the map station size, deleting a reel works, and `/api/ai/categorize` returns a real proposal for a test caption (needs a real `ANTHROPIC_API_KEY`).
