# Geographic Map + "Nascondi Vuoti" Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the schematic railway-map SVG with a geographically accurate Japan map (real coastline, land/sea coloring, hubs/satellites at true lat/lon), and add a toggle that hides locations without reels, combinable with the existing type filter.

**Architecture:** A new `app/geo.py` module owns a single lat/lon → SVG-coordinate projection (equirectangular with a cosine correction, so the shape isn't stretched) plus a hardcoded, pre-simplified Japan coastline (`app/coastline_data.py`, sourced from the public-domain Natural Earth 1:110m dataset). `Location.x/y` becomes `Location.lat/lon` (+ a `map_inset` flag for Okinawa, rendered in a fixed corner box since it's too far south to share the main map's scale). `app/routers/map.py` projects every location through `app.geo.project()` at request time and adds a `hide_empty` query param, combinable with the existing `type` filter, that removes empty locations from the rendered SVG (an empty hub with a non-empty satellite stays as a visually distinct "anchor").

**Tech Stack:** Python 3.11+, FastAPI, SQLModel, Jinja2 + HTMX (all already in use — no new dependencies).

## Global Constraints

- No new Python dependencies — the projection math is plain `math.cos`/`math.radians` from the standard library.
- No DB migrations exist or are needed: the SQLite DB is recreated fresh at every startup and seeded if empty (see `app/db.py` and README "Persistence") — schema field changes are plain edits to `app/models.py`.
- Keep the existing washi/indigo/hanko CSS palette in `app/static/css/style.css` (`--color-paper`, `--color-ink`, `--color-ink-medium`, `--color-hanko`, `--color-gold`) — only add new `:root` variables, never rename or repurpose existing ones.
- All filtering stays server-rendered via the existing HTMX chip pattern (`hx-get` links targeting `#map-container`) — no client-side JS filtering logic.
- UI copy is in Italian, matching the existing chips ("Cibo", "Cultura", ...).

---

## Task 1: Geographic projection module

**Files:**
- Create: `app/coastline_data.py`
- Create: `app/geo.py`
- Test: `tests/test_geo.py`

**Interfaces:**
- Produces: `app.coastline_data.JAPAN_COASTLINE_RINGS: list[list[tuple[float, float]]]` (raw lat/lon rings). `app.geo.project(lat: float, lon: float) -> tuple[float, float]`. `app.geo.COASTLINE_PATHS: list[str]` (pre-projected SVG path `d` strings, one per ring). `app.geo.VIEW_WIDTH: float`, `app.geo.VIEW_HEIGHT: float` (derived, not hardcoded). `app.geo.INSET_BOX: dict` (`x`, `y`, `width`, `height`), `app.geo.INSET_MARKER: tuple[float, float]`, `app.geo.INSET_LABEL_POS: tuple[float, float]` — geometry for the fixed-position Okinawa inset box.

- [ ] **Step 1: Create the coastline data module**

Create `app/coastline_data.py`:

```python
"""Simplified Japan coastline, as (lat, lon) point rings.

Source: Natural Earth 1:110m Cultural Vectors, "Admin 0 - Countries"
dataset (public domain), the feature where NAME == "Japan", from
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson
At this resolution the country geometry already excludes remote islands
(Okinawa is not present in it at all - it's rendered separately via the
`map_inset` flag/box instead of on the main coastline), so no further
filtering of small islands was needed. Coordinates are rounded to 3
decimal places (~100m precision - plenty for a stylized travel map).

Ring 0: Honshu + Kyushu (merged into one ring at this resolution).
Ring 1: Hokkaido.
Ring 2: Shikoku.
"""

JAPAN_COASTLINE_RINGS: list[list[tuple[float, float]]] = [
    [
        (39.181, 141.885), (38.174, 140.959), (37.142, 140.976), (36.344, 140.6),
        (35.843, 140.774), (35.138, 140.253), (34.668, 138.976), (34.606, 137.218),
        (33.465, 135.793), (33.849, 135.121), (34.597, 135.079), (34.376, 133.34),
        (33.905, 132.157), (33.886, 130.986), (33.15, 132.0), (31.45, 131.333),
        (31.03, 130.686), (31.418, 130.202), (32.319, 130.448), (32.61, 129.815),
        (33.296, 129.408), (33.604, 130.354), (34.233, 130.878), (34.75, 131.884),
        (35.433, 132.618), (35.732, 134.608), (35.527, 135.678), (37.305, 136.724),
        (36.827, 137.391), (37.827, 138.858), (38.216, 139.426), (39.439, 140.055),
        (40.563, 139.883), (41.195, 140.306), (41.379, 141.369), (39.992, 141.914),
        (39.181, 141.885),
    ],
    [
        (43.961, 144.613), (44.385, 145.321), (43.262, 145.543), (42.988, 144.06),
        (41.995, 143.184), (42.679, 141.611), (41.585, 141.067), (41.57, 139.955),
        (42.564, 139.818), (43.333, 140.312), (43.389, 141.381), (44.772, 141.672),
        (45.551, 141.968), (44.51, 143.143), (44.174, 143.91), (43.961, 144.613),
    ],
    [
        (33.464, 132.371), (34.06, 132.924), (33.945, 133.493), (34.365, 133.904),
        (34.149, 134.638), (33.806, 134.766), (33.201, 134.203), (33.522, 133.793),
        (33.29, 133.28), (32.705, 133.015), (32.989, 132.363), (33.464, 132.371),
    ],
]
```

- [ ] **Step 2: Write the failing tests for the projection module**

Create `tests/test_geo.py`:

```python
from app.geo import COASTLINE_PATHS, INSET_BOX, VIEW_HEIGHT, VIEW_WIDTH, project


def test_project_keeps_relative_north_south_ordering():
    _, sapporo_y = project(43.0621, 141.3544)
    _, fukuoka_y = project(33.5904, 130.4017)
    assert sapporo_y < fukuoka_y


def test_project_keeps_relative_east_west_ordering():
    tokyo_x, _ = project(35.6762, 139.6503)
    fukuoka_x, _ = project(33.5904, 130.4017)
    assert tokyo_x > fukuoka_x


def test_project_stays_within_view_bounds():
    for lat, lon in [(45.551, 141.968), (31.03, 130.686), (33.464, 132.371)]:
        x, y = project(lat, lon)
        assert 0 <= x <= VIEW_WIDTH
        assert 0 <= y <= VIEW_HEIGHT


def test_coastline_paths_are_closed_svg_paths():
    assert len(COASTLINE_PATHS) == 3
    for d in COASTLINE_PATHS:
        assert d.startswith("M ")
        assert d.endswith(" Z")


def test_inset_box_sits_below_the_main_map():
    _, fukuoka_y = project(33.5904, 130.4017)
    assert INSET_BOX["y"] > fukuoka_y
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_geo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.geo'`

- [ ] **Step 4: Implement the projection module**

Create `app/geo.py`:

```python
"""Lat/lon -> SVG projection for the Japan map, and the pre-projected coastline.

Equirectangular projection with a cos(latitude) correction on longitude, so
the map isn't stretched east-west. The horizontal scale is fit to
VIEW_WIDTH; VIEW_HEIGHT is derived from that scale (not hand-picked) so
there's no wasted empty margin, plus a reserved strip at the bottom for the
Okinawa inset box - Okinawa sits far enough south that drawing it to true
scale would make the map absurdly tall (see design spec doc, section 3).
"""
import math

from app.coastline_data import JAPAN_COASTLINE_RINGS

VIEW_WIDTH = 440.0
PADDING = 25.0
INSET_HEIGHT = 130.0

_all_points = [pt for ring in JAPAN_COASTLINE_RINGS for pt in ring]
_lat0 = sum(lat for lat, _ in _all_points) / len(_all_points)
_cos_lat0 = math.cos(math.radians(_lat0))


def _equirect(lat: float, lon: float) -> tuple[float, float]:
    return lon * _cos_lat0, lat


_ex_all = [_equirect(lat, lon)[0] for lat, lon in _all_points]
_ey_all = [_equirect(lat, lon)[1] for lat, lon in _all_points]
_EX_MIN, _EX_MAX = min(_ex_all), max(_ex_all)
_EY_MIN, _EY_MAX = min(_ey_all), max(_ey_all)

_SCALE = (VIEW_WIDTH - 2 * PADDING) / (_EX_MAX - _EX_MIN)
_DRAWN_HEIGHT = (_EY_MAX - _EY_MIN) * _SCALE

VIEW_HEIGHT = _DRAWN_HEIGHT + 2 * PADDING + INSET_HEIGHT

INSET_BOX = {
    "x": PADDING,
    "y": PADDING + _DRAWN_HEIGHT + 15.0,
    "width": 110.0,
    "height": INSET_HEIGHT - 30.0,
}
INSET_MARKER = (
    INSET_BOX["x"] + INSET_BOX["width"] / 2,
    INSET_BOX["y"] + INSET_BOX["height"] * 0.65,
)
INSET_LABEL_POS = (INSET_BOX["x"] + INSET_BOX["width"] / 2, INSET_BOX["y"] + 18.0)


def project(lat: float, lon: float) -> tuple[float, float]:
    ex, ey = _equirect(lat, lon)
    x = PADDING + (ex - _EX_MIN) * _SCALE
    y = PADDING + (_EY_MAX - ey) * _SCALE
    return x, y


def _ring_to_path(ring: list[tuple[float, float]]) -> str:
    points = [project(lat, lon) for lat, lon in ring]
    start = f"M {points[0][0]:.2f},{points[0][1]:.2f}"
    rest = " ".join(f"L {x:.2f},{y:.2f}" for x, y in points[1:])
    return f"{start} {rest} Z"


COASTLINE_PATHS: list[str] = [_ring_to_path(ring) for ring in JAPAN_COASTLINE_RINGS]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_geo.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add app/coastline_data.py app/geo.py tests/test_geo.py
git commit -m "$(cat <<'EOF'
feat: add lat/lon-to-SVG projection and Japan coastline data

Introduces app/geo.py (equirectangular projection with a cos-latitude
correction, plus derived viewBox dimensions and Okinawa inset geometry)
and app/coastline_data.py (simplified Japan coastline from the public
domain Natural Earth 1:110m dataset).
EOF
)"
```

---

## Task 2: Migrate Location to real lat/lon coordinates

**Files:**
- Modify: `app/models.py`
- Modify: `app/seed.py`
- Modify: `app/routers/map.py`
- Modify: `app/routers/locations.py`
- Modify: `app/templates/partials/map.html`
- Delete: `app/layout.py`
- Delete: `tests/test_layout.py`
- Modify: `tests/test_models.py`
- Modify: `tests/test_locations_api.py`
- Modify: `tests/test_map_api.py`
- Modify: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `app.geo.project(lat, lon) -> tuple[float, float]` (Task 1).
- Produces: `Location.lat: float | None`, `Location.lon: float | None`, `Location.map_inset: bool` (replaces `Location.x`/`Location.y`, used by Task 3 and Task 4). `compute_map(session) -> list[dict]` entries now carry `lat`, `lon`, `map_inset`, `x`, `y` (the latter two are the projected screen coordinates, `None` for `map_inset` locations).

- [ ] **Step 1: Update the failing model tests**

Edit `tests/test_models.py` — replace the two hub constructions that use `x`/`y`:

```python
# In test_create_hub_and_satellite_location, replace:
        hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
# with:
        hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
```

```python
# In test_create_reel_with_types, replace:
        hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
# with:
        hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `TypeError: 'x' is an invalid keyword argument for Location` (the field doesn't exist yet — SQLModel/Pydantic rejects the unknown kwarg)

- [ ] **Step 3: Update the Location model**

Edit `app/models.py` — replace the `Location` class:

```python
class Location(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = Field(default=None, foreign_key="location.id")
    lat: Optional[float] = None
    lon: Optional[float] = None
    map_inset: bool = False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Update the seed data with real coordinates**

Edit `app/seed.py` — replace the whole file:

```python
from sqlmodel import Session, select

from app.models import Location

HUBS = [
    ("Sapporo / Hokkaido", 43.0621, 141.3544, False),
    ("Sendai / Tohoku", 38.2682, 140.8694, False),
    ("Tokyo / Kanto", 35.6762, 139.6503, False),
    ("Nagoya / Chubu", 35.1815, 136.9066, False),
    ("Kyoto - Osaka / Kansai", 34.85, 135.60, False),
    ("Hiroshima / Chugoku", 34.3853, 132.4553, False),
    ("Matsuyama / Shikoku", 33.8392, 132.7657, False),
    ("Fukuoka / Kyushu", 33.5904, 130.4017, False),
    ("Okinawa", 26.2124, 127.6809, True),
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


def seed_if_empty(session: Session) -> None:
    existing = session.exec(select(Location)).first()
    if existing is not None:
        return

    hub_by_name: dict[str, Location] = {}
    for name, lat, lon, map_inset in HUBS:
        hub = Location(name=name, is_hub=True, lat=lat, lon=lon, map_inset=map_inset)
        session.add(hub)
        session.flush()
        hub_by_name[name] = hub

    for name, hub_name, lat, lon in SATELLITES:
        parent = hub_by_name[hub_name]
        session.add(Location(name=name, is_hub=False, parent_id=parent.id, lat=lat, lon=lon))

    session.commit()
```

- [ ] **Step 6: Run the seed tests to verify they still pass**

Run: `uv run pytest tests/test_seed.py -v`
Expected: PASS (2 tests — this file doesn't assert on coordinates, so it needs no edits)

- [ ] **Step 7: Delete the now-unused radial layout module and its test**

```bash
rm app/layout.py tests/test_layout.py
```

- [ ] **Step 8: Update the failing location-API tests**

Edit `tests/test_locations_api.py`:

```python
# In test_list_locations_includes_reel_counts, replace:
    hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
# with:
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
```

```python
# In test_create_hub_location, replace:
    response = client.post(
        "/api/locations",
        json={"name": "Test Hub", "is_hub": True, "x": 10.0, "y": 20.0},
    )
# with:
    response = client.post(
        "/api/locations",
        json={"name": "Test Hub", "is_hub": True, "lat": 10.0, "lon": 20.0},
    )
```

- [ ] **Step 9: Update `LocationCreate` and the location endpoints**

Edit `app/routers/locations.py` — replace the `LocationCreate` model, `create_location`, and `list_locations`:

```python
class LocationCreate(BaseModel):
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    map_inset: bool = False


@router.post("", status_code=status.HTTP_201_CREATED)
def create_location(payload: LocationCreate, session: Session = Depends(get_session)):
    if not payload.is_hub and not payload.parent_id:
        raise HTTPException(
            status_code=400, detail="A satellite location requires a parent_id"
        )
    location = Location(**payload.model_dump())
    session.add(location)
    session.commit()
    session.refresh(location)
    return {
        "id": location.id,
        "name": location.name,
        "is_hub": location.is_hub,
        "parent_id": location.parent_id,
        "lat": location.lat,
        "lon": location.lon,
        "map_inset": location.map_inset,
        "reel_count": 0,
    }


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
            "lat": loc.lat,
            "lon": loc.lon,
            "map_inset": loc.map_inset,
            "reel_count": counts.get(loc.id, 0),
        }
        for loc in locations
    ]
```

- [ ] **Step 10: Run the location-API tests to verify they pass**

Run: `uv run pytest tests/test_locations_api.py -v`
Expected: PASS (8 tests)

- [ ] **Step 11: Update the failing map-API test**

Edit `tests/test_map_api.py` — replace the whole file:

```python
from app.models import Location


def test_map_returns_projected_coordinates_for_hub_and_satellite(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    satellite = Location(
        name="Nikko", is_hub=False, parent_id=hub.id, lat=36.7199, lon=139.6982
    )
    session.add(satellite)
    session.commit()

    response = client.get("/api/map")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    hub_entry = next(d for d in data if d["is_hub"])
    sat_entry = next(d for d in data if not d["is_hub"])
    assert hub_entry["x"] is not None and hub_entry["y"] is not None
    assert sat_entry["parent_id"] == hub.id
    assert sat_entry["x"] != hub_entry["x"] or sat_entry["y"] != hub_entry["y"]
```

- [ ] **Step 12: Run the test to verify it fails**

Run: `uv run pytest tests/test_map_api.py -v`
Expected: FAIL — `compute_map` still reads `loc.x`/`loc.y` directly (no projection), so the response won't come back at all: `AttributeError` (500 response, `assert response.status_code == 200` fails)

- [ ] **Step 13: Rewrite `compute_map` to project real coordinates**

Edit `app/routers/map.py` — replace the imports and `compute_map`:

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.geo import project
from app.models import Location, Reel, ReelType
from app.taxonomy import TAXONOMY
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

    result = []
    for loc in locations:
        if loc.map_inset:
            x, y = None, None
        else:
            x, y = project(loc.lat or 0.0, loc.lon or 0.0)
        result.append(
            {
                "id": loc.id,
                "name": loc.name,
                "is_hub": loc.is_hub,
                "parent_id": loc.parent_id,
                "lat": loc.lat,
                "lon": loc.lon,
                "map_inset": loc.map_inset,
                "x": x,
                "y": y,
                "reel_count": counts.get(loc.id, 0),
            }
        )
    return result
```

Leave `get_map`, `locations_with_type`, and `ui_map` exactly as they are for now (they don't reference `x`/`y` directly).

- [ ] **Step 14: Run the test to verify it passes**

Run: `uv run pytest tests/test_map_api.py -v`
Expected: PASS (1 test)

- [ ] **Step 15: Update the UI-fragment test fixtures**

`compute_map` and the `Location` model were already fixed in steps 3 and 13,
so this is a plain rename with no red step of its own — the failure it
would otherwise cause was already covered by Steps 2 and 12.

Edit `tests/test_ui_fragments.py`:

```python
# In test_ui_map_renders_svg_with_stations, replace:
    hub = Location(name="Tokyo / Kanto", is_hub=True, x=200.0, y=250.0)
# with:
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
```

```python
# In test_ui_map_dims_stations_without_the_selected_type, replace:
    hub_with_food = Location(name="Has Food", is_hub=True, x=10.0, y=10.0)
    hub_without_food = Location(name="No Food", is_hub=True, x=20.0, y=20.0)
# with:
    hub_with_food = Location(name="Has Food", is_hub=True, lat=35.0, lon=135.0)
    hub_without_food = Location(name="No Food", is_hub=True, lat=36.0, lon=136.0)
```

- [ ] **Step 16: Update the map template's viewBox width**

Edit `app/templates/partials/map.html` — the SVG element currently reads:

```html
<svg viewBox="0 0 400 650" class="japan-map">
```

Replace with:

```html
<svg viewBox="0 0 440 650" class="japan-map">
```

(This is a placeholder fixed size for this task only — Task 3 replaces it with the derived `view_width`/`view_height` from `app.geo`.)

- [ ] **Step 17: Skip rendering `map_inset` locations for now**

Edit `app/templates/partials/map.html` — wrap both location loops with a `map_inset` guard (Task 3 adds the actual inset box; for now these locations are simply not drawn, since their `x`/`y` are `None`):

```html
{% for loc in locations %}
{% if not loc.is_hub and not loc.map_inset %}
<line x1="{{ hubs_by_id[loc.parent_id].x }}" y1="{{ hubs_by_id[loc.parent_id].y }}"
      x2="{{ loc.x }}" y2="{{ loc.y }}" class="satellite-line" />
{% endif %}
{% endfor %}
{% for loc in locations %}
{% if not loc.map_inset %}
<circle cx="{{ loc.x }}" cy="{{ loc.y }}"
        r="{{ 8 if loc.is_hub else 4 }}"
        class="station {{ 'hub' if loc.is_hub else 'satellite' }}{{ ' dimmed' if active_type and loc.id not in matching_location_ids else '' }}" data-location-id="{{ loc.id }}" />
<text x="{{ loc.x }}" y="{{ loc.y - 10 }}" class="station-label">{{ loc.name }}</text>
{% endif %}
{% endfor %}
```

- [ ] **Step 18: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ui_fragments.py -v`
Expected: PASS (7 tests)

- [ ] **Step 19: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS (all tests — this confirms no other file still references `Location.x`/`Location.y` or `app.layout`)

- [ ] **Step 20: Commit**

```bash
git add app/models.py app/seed.py app/routers/map.py app/routers/locations.py \
        app/templates/partials/map.html tests/test_models.py tests/test_locations_api.py \
        tests/test_map_api.py tests/test_ui_fragments.py
git rm app/layout.py tests/test_layout.py
git commit -m "$(cat <<'EOF'
feat: migrate Location to real lat/lon coordinates

Replaces the schematic x/y fields with real-world lat/lon (+ a
map_inset flag for Okinawa) on both hubs and satellites. The map
endpoint now projects coordinates through app.geo.project() instead
of computing a radial layout, so app/layout.py is no longer needed.
EOF
)"
```

---

## Task 3: Render the real coastline, sea/land colors, and the Okinawa inset box

**Files:**
- Modify: `app/routers/map.py`
- Modify: `app/templates/partials/map.html`
- Modify: `app/static/css/style.css`
- Test: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `app.geo.COASTLINE_PATHS`, `app.geo.VIEW_WIDTH`, `app.geo.VIEW_HEIGHT`, `app.geo.INSET_BOX`, `app.geo.INSET_MARKER`, `app.geo.INSET_LABEL_POS` (Task 1). `Location.map_inset` (Task 2).
- Produces: `partials/map.html` template context gains `coastline_paths`, `view_width`, `view_height`, `inset_box`, `inset_marker`, `inset_label_pos` — consumed by Task 4's edits to the same template.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_fragments.py`:

```python
def test_ui_map_renders_coastline_and_sea(client):
    response = client.get("/ui/map")
    assert response.status_code == 200
    assert '<path d="M ' in response.text
    assert 'class="sea"' in response.text


def test_ui_map_renders_okinawa_inset_box(client, session):
    okinawa = Location(name="Okinawa", is_hub=True, lat=26.2124, lon=127.6809, map_inset=True)
    session.add(okinawa)
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200
    assert 'class="inset-box"' in response.text
    assert "Okinawa" in response.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ui_fragments.py -v -k "coastline or inset"`
Expected: FAIL — no `<path d="M ` or `class="sea"` in the current output; `map_inset` locations aren't rendered at all yet

- [ ] **Step 3: Pass the coastline and viewBox geometry into the template context**

Edit `app/routers/map.py` — update the import and `ui_map`:

```python
from app.geo import COASTLINE_PATHS, INSET_BOX, INSET_LABEL_POS, INSET_MARKER, VIEW_HEIGHT, VIEW_WIDTH, project
```

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
            "coastline_paths": COASTLINE_PATHS,
            "view_width": round(VIEW_WIDTH),
            "view_height": round(VIEW_HEIGHT),
            "inset_box": INSET_BOX,
            "inset_marker": INSET_MARKER,
            "inset_label_pos": INSET_LABEL_POS,
        },
    )
```

- [ ] **Step 4: Render the coastline, sea background, and inset box in the template**

Edit `app/templates/partials/map.html` — replace the whole file:

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
<svg viewBox="0 0 {{ view_width }} {{ view_height }}" class="japan-map">
    <rect x="0" y="0" width="{{ view_width }}" height="{{ view_height }}" class="sea" />
    {% for d in coastline_paths %}
    <path d="{{ d }}" class="land" />
    {% endfor %}
    {% for loc in locations %}
    {% if not loc.is_hub and not loc.map_inset %}
    <line x1="{{ hubs_by_id[loc.parent_id].x }}" y1="{{ hubs_by_id[loc.parent_id].y }}"
          x2="{{ loc.x }}" y2="{{ loc.y }}" class="satellite-line" />
    {% endif %}
    {% endfor %}
    {% for loc in locations %}
    {% if not loc.map_inset %}
    <circle cx="{{ loc.x }}" cy="{{ loc.y }}"
            r="{{ 8 if loc.is_hub else 4 }}"
            class="station {{ 'hub' if loc.is_hub else 'satellite' }}{{ ' dimmed' if active_type and loc.id not in matching_location_ids else '' }}" data-location-id="{{ loc.id }}" />
    <text x="{{ loc.x }}" y="{{ loc.y - 10 }}" class="station-label">{{ loc.name }}</text>
    {% endif %}
    {% endfor %}
    {% for loc in locations %}
    {% if loc.map_inset %}
    <rect x="{{ inset_box.x }}" y="{{ inset_box.y }}" width="{{ inset_box.width }}" height="{{ inset_box.height }}" class="inset-box" />
    <text x="{{ inset_label_pos[0] }}" y="{{ inset_label_pos[1] }}" class="inset-label" text-anchor="middle">Okinawa</text>
    <circle cx="{{ inset_marker[0] }}" cy="{{ inset_marker[1] }}" r="7" class="station hub" data-location-id="{{ loc.id }}" />
    <text x="{{ inset_marker[0] }}" y="{{ inset_marker[1] + 18 }}" class="station-label">{{ loc.name }}</text>
    {% endif %}
    {% endfor %}
</svg>
```

- [ ] **Step 5: Add sea/land/inset colors to the stylesheet**

Edit `app/static/css/style.css` — add `--color-sea` to `:root`:

```css
:root {
    --color-paper: #E3E1D4;
    --color-ink: #1F2C47;
    --color-ink-medium: #35496B;
    --color-hanko: #A63A2E;
    --color-gold: #B08D57;
    --color-sea: #8FA8B2;
}
```

Add new rules right after the existing `.satellite-line` rule:

```css
.sea {
    fill: var(--color-sea);
}

.land {
    fill: var(--color-paper);
    stroke: var(--color-ink-medium);
    stroke-width: 1.5;
}

.inset-box {
    fill: none;
    stroke: var(--color-ink);
    stroke-width: 1;
    stroke-dasharray: 3 2;
}

.inset-label {
    font-size: 9px;
    font-style: italic;
    fill: var(--color-ink-medium);
    font-family: "Zen Kaku Gothic New", sans-serif;
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ui_fragments.py -v`
Expected: PASS (9 tests)

- [ ] **Step 7: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add app/routers/map.py app/templates/partials/map.html app/static/css/style.css \
        tests/test_ui_fragments.py
git commit -m "$(cat <<'EOF'
feat: render the real Japan coastline and Okinawa inset box

The map SVG now draws sea/land colors and the actual coastline
(app.geo.COASTLINE_PATHS) behind the hub/satellite markers, with
Okinawa shown in a fixed dashed-border inset box instead of at its
true (very distant) scale.
EOF
)"
```

---

## Task 4: "Nascondi vuoti" toggle

**Files:**
- Modify: `app/routers/map.py`
- Modify: `app/templates/partials/map.html`
- Modify: `app/static/css/style.css`
- Modify: `tests/test_map_api.py`
- Modify: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `compute_map(session) -> list[dict]`, `locations_with_type(session, type_value) -> set[str]` (existing, from Task 2).
- Produces: `visible_location_ids(session, locations, type_value, hide_empty) -> tuple[set[str] | None, set[str]]` — first element is `None` when `hide_empty` is `False` (no filtering), else the set of location ids to render; second element is always the subset of those ids that are "anchor" hubs (empty themselves, kept visible only because a child satellite qualifies).

- [ ] **Step 1: Write the failing unit tests for the filtering logic**

Edit `tests/test_map_api.py` — add the import and the new tests:

```python
from app.models import Location, Reel, ReelType
from app.routers.map import compute_map, visible_location_ids
```

```python
def test_visible_location_ids_returns_none_when_hide_empty_is_false(session):
    locations = compute_map(session)
    visible_ids, anchors = visible_location_ids(session, locations, None, False)
    assert visible_ids is None
    assert anchors == set()


def test_visible_location_ids_hides_hub_with_no_reels_and_no_filled_children(session):
    empty_hub = Location(name="Empty", is_hub=True, lat=35.0, lon=135.0)
    filled_hub = Location(name="Filled", is_hub=True, lat=36.0, lon=136.0)
    session.add(empty_hub)
    session.add(filled_hub)
    session.commit()
    session.refresh(filled_hub)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=filled_hub.id))
    session.commit()

    locations = compute_map(session)
    visible_ids, anchors = visible_location_ids(session, locations, None, True)

    assert filled_hub.id in visible_ids
    assert empty_hub.id not in visible_ids
    assert anchors == set()


def test_visible_location_ids_keeps_empty_hub_as_anchor_for_filled_satellite(session):
    hub = Location(name="Hub", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    satellite = Location(name="Satellite", is_hub=False, parent_id=hub.id, lat=35.1, lon=135.1)
    session.add(satellite)
    session.commit()
    session.refresh(satellite)
    session.add(Reel(link="https://instagram.com/reel/b", location_id=satellite.id))
    session.commit()

    locations = compute_map(session)
    visible_ids, anchors = visible_location_ids(session, locations, None, True)

    assert hub.id in visible_ids
    assert satellite.id in visible_ids
    assert hub.id in anchors


def test_visible_location_ids_uses_type_specific_emptiness_when_type_active(session):
    hub = Location(name="Hub", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/c", location_id=hub.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    locations = compute_map(session)
    visible_ids, _ = visible_location_ids(session, locations, "culture", True)

    assert hub.id not in visible_ids
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_map_api.py -v`
Expected: FAIL with `ImportError: cannot import name 'visible_location_ids' from 'app.routers.map'`

- [ ] **Step 3: Implement `visible_location_ids`**

Edit `app/routers/map.py` — add this function after `locations_with_type`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_map_api.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Write the failing UI tests for the toggle**

Edit `tests/test_ui_fragments.py` — add:

```python
def test_ui_map_hide_empty_removes_empty_hub_from_svg(client, session):
    empty_hub = Location(name="Empty Hub", is_hub=True, lat=35.0, lon=135.0)
    filled_hub = Location(name="Filled Hub", is_hub=True, lat=36.0, lon=136.0)
    session.add(empty_hub)
    session.add(filled_hub)
    session.commit()
    session.refresh(filled_hub)
    session.add(Reel(link="https://instagram.com/reel/d", location_id=filled_hub.id))
    session.commit()

    response = client.get("/ui/map?hide_empty=1")
    assert response.status_code == 200
    assert "Filled Hub" in response.text
    assert "Empty Hub" not in response.text


def test_ui_map_toggle_chip_label_reflects_state(client):
    response = client.get("/ui/map")
    assert "Nascondi vuoti" in response.text

    response = client.get("/ui/map?hide_empty=1")
    assert "Mostra tutti" in response.text
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ui_fragments.py -v -k "hide_empty or toggle_chip"`
Expected: FAIL — `/ui/map` doesn't accept `hide_empty` yet (it's silently ignored by FastAPI, so both hub names render and neither toggle label appears)

- [ ] **Step 7: Wire `hide_empty` through `ui_map` and the template**

Edit `app/routers/map.py` — replace `ui_map`:

```python
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
    return templates.TemplateResponse(
        request,
        "partials/map.html",
        {
            "locations": locations,
            "hubs_by_id": hubs_by_id,
            "taxonomy": TAXONOMY,
            "active_type": type,
            "matching_location_ids": matching_location_ids,
            "visible_ids": visible_ids,
            "anchor_hub_ids": anchor_hub_ids,
            "hide_empty": hide_empty,
            "coastline_paths": COASTLINE_PATHS,
            "view_width": round(VIEW_WIDTH),
            "view_height": round(VIEW_HEIGHT),
            "inset_box": INSET_BOX,
            "inset_marker": INSET_MARKER,
            "inset_label_pos": INSET_LABEL_POS,
        },
    )
```

Edit `app/templates/partials/map.html` — replace the whole file:

```html
<div class="map-filters">
    <a href="#" class="chip {{ 'active' if not active_type else '' }}"
       hx-get="/ui/map{% if hide_empty %}?hide_empty=1{% endif %}" hx-target="#map-container" hx-swap="innerHTML">Tutti</a>
    {% for key, info in taxonomy.items() %}
    <a href="#" class="chip {{ 'active' if active_type == key else '' }}"
       data-type="{{ key }}" style="border-color: {{ info.color }};"
       hx-get="/ui/map?type={{ key }}{% if hide_empty %}&hide_empty=1{% endif %}" hx-target="#map-container" hx-swap="innerHTML">
        {{ info.icon }} {{ info.label }}
    </a>
    {% endfor %}
    <a href="#" class="chip toggle {{ 'active' if hide_empty else '' }}"
       hx-get="/ui/map?{% if active_type %}type={{ active_type }}&{% endif %}hide_empty={{ '0' if hide_empty else '1' }}"
       hx-target="#map-container" hx-swap="innerHTML">
        {{ 'Mostra tutti' if hide_empty else 'Nascondi vuoti' }}
    </a>
</div>
<svg viewBox="0 0 {{ view_width }} {{ view_height }}" class="japan-map">
    <rect x="0" y="0" width="{{ view_width }}" height="{{ view_height }}" class="sea" />
    {% for d in coastline_paths %}
    <path d="{{ d }}" class="land" />
    {% endfor %}
    {% for loc in locations %}
    {% if not loc.is_hub and not loc.map_inset and (visible_ids is none or loc.id in visible_ids) %}
    <line x1="{{ hubs_by_id[loc.parent_id].x }}" y1="{{ hubs_by_id[loc.parent_id].y }}"
          x2="{{ loc.x }}" y2="{{ loc.y }}" class="satellite-line" />
    {% endif %}
    {% endfor %}
    {% for loc in locations %}
    {% if not loc.map_inset and (visible_ids is none or loc.id in visible_ids) %}
    <circle cx="{{ loc.x }}" cy="{{ loc.y }}"
            r="{{ 8 if loc.is_hub else 4 }}"
            class="station {{ 'hub' if loc.is_hub else 'satellite' }}{{ ' anchor' if loc.id in anchor_hub_ids else '' }}{{ ' dimmed' if active_type and loc.id not in matching_location_ids else '' }}" data-location-id="{{ loc.id }}" />
    <text x="{{ loc.x }}" y="{{ loc.y - 10 }}" class="station-label">{{ loc.name }}</text>
    {% endif %}
    {% endfor %}
    {% for loc in locations %}
    {% if loc.map_inset and (visible_ids is none or loc.id in visible_ids) %}
    <rect x="{{ inset_box.x }}" y="{{ inset_box.y }}" width="{{ inset_box.width }}" height="{{ inset_box.height }}" class="inset-box" />
    <text x="{{ inset_label_pos[0] }}" y="{{ inset_label_pos[1] }}" class="inset-label" text-anchor="middle">Okinawa</text>
    <circle cx="{{ inset_marker[0] }}" cy="{{ inset_marker[1] }}" r="7" class="station hub" data-location-id="{{ loc.id }}" />
    <text x="{{ inset_marker[0] }}" y="{{ inset_marker[1] + 18 }}" class="station-label">{{ loc.name }}</text>
    {% endif %}
    {% endfor %}
</svg>
```

- [ ] **Step 8: Style the anchor hub variant**

Edit `app/static/css/style.css` — add after `.station.satellite`:

```css
.station.anchor {
    fill: none;
    stroke: var(--color-ink-medium);
    stroke-width: 2;
}
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/test_ui_fragments.py -v`
Expected: PASS (11 tests)

- [ ] **Step 10: Run the full test suite**

Run: `uv run pytest -v`
Expected: PASS (all tests)

- [ ] **Step 11: Manually verify in the browser**

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # only needed for the AI chat flow, not the map
uv run uvicorn app.main:app --reload
```

Open `http://localhost:8000`, confirm:
- The map shows the real Japan coastline with sea/land colors and hubs at plausible real positions (Tokyo east and south of Sapporo, Okinawa in its own inset box bottom-left).
- Clicking "Nascondi vuoti" hides hubs/satellites with no reels and relabels itself "Mostra tutti"; clicking it again restores everything.
- Clicking a type chip while "Nascondi vuoti" is active keeps both filters combined (URL has both `type=` and `hide_empty=1`).

- [ ] **Step 12: Commit**

```bash
git add app/routers/map.py app/templates/partials/map.html app/static/css/style.css \
        tests/test_map_api.py tests/test_ui_fragments.py
git commit -m "$(cat <<'EOF'
feat: add "nascondi vuoti" toggle to the map

Combinable with the existing type filter: hides hubs/satellites with
no (matching) reels, except a hub kept as a visual "anchor" when it
has no reels itself but a satellite that does.
EOF
)"
```
