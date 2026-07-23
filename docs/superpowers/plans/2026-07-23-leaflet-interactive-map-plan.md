# Leaflet Interactive Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static hand-drawn SVG map (real coastline, no interactivity) with a real interactive street/political map built on Leaflet + OpenStreetMap tiles, add click-to-filter-reels on markers, and make `lat`/`lon` required when creating a location so a location can never again silently render off-canvas.

**Architecture:** `app/routers/map.py` keeps its existing shape (`compute_map`, `visible_location_ids`, `ui_map`) but drops all SVG-projection concerns (`app/geo.py`, `app/coastline_data.py`, `Location.map_inset` are deleted entirely). `ui_map` now emits a small JSON blob of already-filtered, already-annotated (`anchor`/`dimmed`) location dicts, embedded in the `partials/map.html` template; a new `app/static/js/map.js` reads that blob and draws Leaflet `circleMarker`s/`polyline`s on a tile map. Clicking a marker calls the existing HTMX machinery (`htmx.ajax`) against a `GET /ui/reels?location_id=` endpoint (extended in this plan) to filter the reel panel.

**Tech Stack:** FastAPI, Jinja2, HTMX, Leaflet 1.9.4 + OpenStreetMap tiles (both via CDN, no new Python dependency), vanilla JS.

## Global Constraints

- No new Python dependencies — Leaflet and its tiles are pure frontend (CDN `<link>`/`<script>` tags), matching the project's existing "no heavy JS framework" stance (`docs/japan-reel-organizer-specifiche.md` line 17).
- No DB migrations — this app recreates its schema via `SQLModel.metadata.create_all` with no migration tooling (README §Persistence); dropping the `Location.map_inset` column is a clean field removal, not an additive/backward-compatible change. Any existing local `data/*.db` file with the old schema should be deleted by hand after this lands (mentioned in Task 1's manual verification, not automated).
- Follow the design doc exactly: `docs/superpowers/specs/2026-07-23-leaflet-interactive-map-design.md`.

---

## Task 1: Replace SVG map rendering with an interactive Leaflet map

**Files:**
- Delete: `app/geo.py`
- Delete: `app/coastline_data.py`
- Delete: `tests/test_geo.py`
- Modify: `app/models.py`
- Modify: `app/seed.py`
- Modify: `app/routers/locations.py`
- Modify: `app/routers/map.py`
- Modify: `app/templates/partials/map.html`
- Modify: `app/templates/base.html`
- Create: `app/static/js/map.js`
- Modify: `app/static/css/style.css`
- Modify: `tests/test_map_api.py`
- Modify: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: nothing from other tasks (this is the foundation task).
- Produces:
  - `compute_map(session) -> list[dict]`, each dict now exactly
    `{"id": str, "name": str, "is_hub": bool, "parent_id": str | None, "lat": float | None, "lon": float | None, "reel_count": int}` — no `x`, `y`, or `map_inset` keys.
  - `visible_location_ids(session, locations, type_value, hide_empty) -> tuple[set[str] | None, set[str]]` — signature and behavior unchanged from before.
  - `partials/map.html` renders a `<div id="leaflet-map">` and a `<script type="application/json" id="map-data">` blob of location dicts shaped `{"id", "name", "is_hub", "lat", "lon", "anchor", "dimmed", "parent_lat", "parent_lon"}`.
  - Global JS function `initReelMap(containerId: string, dataId: string)` defined in `app/static/js/map.js`, called once per `map.html` render.
  - `Location` (`app/models.py`) has no `map_inset` field; `lat`/`lon` remain `Optional[float]` at the model/DB level (Task 2 tightens the *API request* schema, not the DB column).

- [ ] **Step 1: Rewrite the coordinate test in `tests/test_map_api.py`**

Replace the first test (lines 1-26) with a version that checks `lat`/`lon` instead of projected `x`/`y`, and asserts the removed keys are gone:

```python
from app.models import Location, Reel, ReelType
from app.routers.map import compute_map, visible_location_ids


def test_map_returns_lat_lon_for_hub_and_satellite(client, session):
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
    assert hub_entry["lat"] == 35.6762
    assert hub_entry["lon"] == 139.6503
    assert sat_entry["parent_id"] == hub.id
    assert "x" not in hub_entry and "y" not in hub_entry
    assert "map_inset" not in hub_entry
```

Leave the four `visible_location_ids` tests below it (`test_visible_location_ids_returns_none_when_hide_empty_is_false` through `test_visible_location_ids_uses_type_specific_emptiness_when_type_active`) exactly as they are — that logic doesn't change in this task.

- [ ] **Step 2: Rewrite `tests/test_ui_fragments.py` for JSON-blob rendering**

The current file asserts against raw SVG markup (`<svg`, `class="sea"`, `class="inset-box"`, regex over `data-location-id`). Replace the whole file with:

```python
import json
import re

from sqlmodel import select

from app.models import Location, Reel, ReelType


def _map_data(response_text: str) -> list[dict]:
    match = re.search(
        r'<script type="application/json" id="map-data">(.*?)</script>',
        response_text,
        re.DOTALL,
    )
    assert match, "map-data JSON blob not found in response"
    return json.loads(match.group(1))


def test_ui_map_renders_leaflet_container_and_location_data(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200
    assert 'id="leaflet-map"' in response.text

    locations = _map_data(response.text)
    assert len(locations) == 1
    assert locations[0]["name"] == "Tokyo / Kanto"
    assert locations[0]["lat"] == 35.6762
    assert locations[0]["lon"] == 139.6503


def test_ui_map_includes_type_filter_chips(client):
    response = client.get("/ui/map")
    assert response.status_code == 200
    assert "Cibo" in response.text
    assert 'hx-get="/ui/map?type=food"' in response.text


def test_ui_map_dims_stations_without_the_selected_type(client, session):
    hub_with_food = Location(name="Has Food", is_hub=True, lat=35.0, lon=135.0)
    hub_without_food = Location(name="No Food", is_hub=True, lat=36.0, lon=136.0)
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

    locations = {loc["id"]: loc for loc in _map_data(response.text)}
    assert locations[hub_with_food.id]["dimmed"] is False
    assert locations[hub_without_food.id]["dimmed"] is True


def test_ui_map_okinawa_renders_at_its_real_coordinates(client, session):
    okinawa = Location(name="Okinawa", is_hub=True, lat=26.2124, lon=127.6809)
    session.add(okinawa)
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200

    locations = _map_data(response.text)
    assert len(locations) == 1
    assert locations[0]["name"] == "Okinawa"
    assert locations[0]["lat"] == 26.2124
    assert locations[0]["lon"] == 127.6809


def test_ui_map_hide_empty_removes_empty_hub(client, session):
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

    ids = {loc["id"] for loc in _map_data(response.text)}
    assert filled_hub.id in ids
    assert empty_hub.id not in ids


def test_ui_map_toggle_chip_label_reflects_state(client):
    response = client.get("/ui/map")
    assert "Nascondi vuoti" in response.text

    response = client.get("/ui/map?hide_empty=1")
    assert "Mostra tutti" in response.text


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


def test_ui_reels_post_rejects_javascript_link(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/reels",
        data={"link": "javascript:alert(1)", "location_id": hub.id},
    )
    assert response.status_code == 400
    assert session.exec(select(Reel)).all() == []


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

- [ ] **Step 3: Run the updated tests to confirm they fail against the current (SVG) implementation**

Run: `uv run pytest tests/test_map_api.py tests/test_ui_fragments.py -v`
Expected: FAIL — `test_map_returns_lat_lon_for_hub_and_satellite` fails because the API still returns `x`/`y`/`map_inset`; every `_map_data`-based test fails with `AssertionError: map-data JSON blob not found in response` because `map.html` still renders raw SVG.

- [ ] **Step 4: Delete the projection/coastline modules and the old geo test**

```bash
rm app/geo.py app/coastline_data.py tests/test_geo.py
```

- [ ] **Step 5: Remove `map_inset` from the `Location` model**

Edit `app/models.py`:

```python
class Location(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = Field(default=None, foreign_key="location.id")
    lat: Optional[float] = None
    lon: Optional[float] = None
```

(Remove the `map_inset: bool = False` line that followed `lon`.)

- [ ] **Step 6: Drop `map_inset` from seed data**

Edit `app/seed.py`:

```python
from sqlmodel import Session, select

from app.models import Location

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


def seed_if_empty(session: Session) -> None:
    existing = session.exec(select(Location)).first()
    if existing is not None:
        return

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
```

- [ ] **Step 7: Remove `map_inset` from the locations API**

Edit `app/routers/locations.py` — three spots:

```python
class LocationCreate(BaseModel):
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
```

(drop the `map_inset: bool = False` line)

```python
    return {
        "id": location.id,
        "name": location.name,
        "is_hub": location.is_hub,
        "parent_id": location.parent_id,
        "lat": location.lat,
        "lon": location.lon,
        "reel_count": 0,
    }
```

(drop the `"map_inset": location.map_inset,` line from `create_location`'s return dict)

```python
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
```

(drop the `"map_inset": loc.map_inset,` line from `list_locations`)

- [ ] **Step 8: Rewrite `app/routers/map.py`**

```python
import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
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
            "taxonomy": TAXONOMY,
            "hide_empty": hide_empty,
        },
    )
```

Note the `.replace("<", "\\u003c")` on the JSON string: it neutralizes a `</script>` sequence inside a user-supplied location name from prematurely closing the embedding `<script>` tag. `<` is a valid JSON/JS escape for `<`, so `JSON.parse` in `map.js` decodes it back correctly.

- [ ] **Step 9: Rewrite `app/templates/partials/map.html`**

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
<div id="leaflet-map" class="leaflet-map"></div>
<script type="application/json" id="map-data">{{ map_locations_json | safe }}</script>
<script>
    initReelMap("leaflet-map", "map-data");
</script>
```

- [ ] **Step 10: Add Leaflet and the new map script to `app/templates/base.html`**

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
    </header>
    <main>
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

- [ ] **Step 11: Create `app/static/js/map.js`**

```javascript
function initReelMap(containerId, dataId) {
    const dataEl = document.getElementById(dataId);
    const locations = JSON.parse(dataEl.textContent);

    const map = L.map(containerId).setView([36.5, 138.0], 5);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
        maxZoom: 18,
    }).addTo(map);

    locations.forEach((loc) => {
        const classes = ["station", loc.is_hub ? "hub" : "satellite"];
        if (loc.anchor) classes.push("anchor");
        if (loc.dimmed) classes.push("dimmed");

        const marker = L.circleMarker([loc.lat, loc.lon], {
            radius: loc.is_hub ? 10 : 6,
            className: classes.join(" "),
        }).addTo(map);

        marker.bindTooltip(loc.name, {
            permanent: true,
            direction: "top",
            className: "station-label",
        });

        marker.on("click", () => {
            htmx.ajax("GET", "/ui/reels?location_id=" + loc.id, {
                target: "#reel-list",
                swap: "innerHTML",
            });
        });

        if (!loc.is_hub && loc.parent_lat !== null && loc.parent_lon !== null) {
            L.polyline(
                [
                    [loc.parent_lat, loc.parent_lon],
                    [loc.lat, loc.lon],
                ],
                { className: "satellite-line" }
            ).addTo(map);
        }
    });
}
```

- [ ] **Step 12: Update `app/static/css/style.css`**

Replace this block (from `.japan-map` through the closing brace of `.station-label`):

```css
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

.station.anchor {
    fill: none;
    stroke: var(--color-ink-medium);
    stroke-width: 2;
}

.satellite-line {
    stroke: var(--color-ink-medium);
    stroke-dasharray: 4 3;
}

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

.station-label {
    font-size: 10px;
    font-family: "Zen Kaku Gothic New", sans-serif;
    fill: var(--color-ink);
    text-anchor: middle;
}
```

with:

```css
.leaflet-map {
    width: 100%;
    height: 420px;
    margin: 0 auto;
    border: 1px solid var(--color-ink-medium);
}

.station.hub {
    fill: var(--color-ink-medium);
    stroke: var(--color-ink-medium);
}

.station.satellite {
    fill: var(--color-gold);
    stroke: var(--color-gold);
}

.station.anchor {
    fill: none;
    stroke: var(--color-ink-medium);
    stroke-width: 2;
}

.station.dimmed {
    opacity: 0.35;
}

.satellite-line {
    stroke: var(--color-ink-medium);
    stroke-dasharray: 4 3;
}

.station-label {
    font-size: 0.7rem;
    font-family: "Zen Kaku Gothic New", sans-serif;
    color: var(--color-ink);
}
```

Then, in the `@media (max-width: 480px)` block at the bottom of the file, replace:

```css
    .japan-map {
        max-width: 100%;
    }
```

with:

```css
    .leaflet-map {
        height: 320px;
    }
```

- [ ] **Step 13: Run the full test suite to confirm everything passes**

Run: `uv run pytest -v`
Expected: PASS — all tests green, including the rewritten ones from Steps 1-2. (`tests/test_geo.py` no longer exists so it won't run.)

- [ ] **Step 14: Manual verification**

```bash
rm -f data/japan_reels.db   # old schema had the now-removed map_inset column
uv run uvicorn app.main:app --reload
```

Open `http://localhost:8000/ui/map` and confirm:
- Real OpenStreetMap street tiles load, centered on Japan
- Scroll-wheel zoom and drag-to-pan both work
- All 9 hubs and 10 satellites appear as markers with name tooltips, dashed lines connecting satellites to their hub
- Okinawa appears at its true position in the south (no inset box)
- Clicking "Nascondi vuoti" removes empty markers and the map resets to the default Japan-wide view
- Clicking a marker requests `/ui/reels?location_id=...` (visible in the Network tab) — the reel panel will show the unfiltered list until Task 3 lands, that's expected at this point

- [ ] **Step 15: Commit**

```bash
git add app/models.py app/seed.py app/routers/locations.py app/routers/map.py \
  app/templates/partials/map.html app/templates/base.html app/static/js/map.js \
  app/static/css/style.css tests/test_map_api.py tests/test_ui_fragments.py
git rm app/geo.py app/coastline_data.py tests/test_geo.py
git commit -m "$(cat <<'EOF'
feat: replace static SVG map with interactive Leaflet map

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Require lat/lon when creating a location

**Files:**
- Modify: `app/routers/locations.py`
- Modify: `tests/test_locations_api.py`

**Interfaces:**
- Consumes: `LocationCreate` as left by Task 1 (no `map_inset`, `lat`/`lon` still `Optional[float] = None`).
- Produces: `LocationCreate` with `lat: float` and `lon: float` required (no default). `POST /api/locations` returns `422` if either is missing from the request body.

- [ ] **Step 1: Add the failing test for required lat/lon**

Add to `tests/test_locations_api.py` (anywhere after the imports, e.g. right after `test_create_hub_location`):

```python
def test_create_location_without_lat_lon_returns_422(client):
    response = client.post("/api/locations", json={"name": "No Coords", "is_hub": True})
    assert response.status_code == 422
```

- [ ] **Step 2: Fix the three existing tests that post without lat/lon**

These currently pass because `lat`/`lon` are optional; once Step 4 makes them required they'd start failing for the wrong reason (422 instead of the behavior each test is actually checking). Update them in `tests/test_locations_api.py`:

`test_delete_location_cascades_reels` — change:
```python
    hub_resp = client.post("/api/locations", json={"name": "Doomed Hub", "is_hub": True})
```
to:
```python
    hub_resp = client.post(
        "/api/locations", json={"name": "Doomed Hub", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
```

`test_create_satellite_location` — change:
```python
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
to:
```python
def test_create_satellite_location(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Parent Hub", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]

    response = client.post(
        "/api/locations",
        json={"name": "Satellite Town", "is_hub": False, "parent_id": hub_id, "lat": 35.1, "lon": 135.1},
    )
    assert response.status_code == 201
    assert response.json()["parent_id"] == hub_id
```

`test_create_satellite_location_without_parent_id_returns_400` — change:
```python
def test_create_satellite_location_without_parent_id_returns_400(client):
    response = client.post(
        "/api/locations",
        json={"name": "Orphan", "is_hub": False},
    )
    assert response.status_code == 400
```
to:
```python
def test_create_satellite_location_without_parent_id_returns_400(client):
    response = client.post(
        "/api/locations",
        json={"name": "Orphan", "is_hub": False, "lat": 35.0, "lon": 135.0},
    )
    assert response.status_code == 400
```

`test_delete_location_with_children_returns_409` — change:
```python
def test_delete_location_with_children_returns_409(client):
    hub_resp = client.post("/api/locations", json={"name": "Hub With Kids", "is_hub": True})
    hub_id = hub_resp.json()["id"]

    satellite_resp = client.post(
        "/api/locations",
        json={"name": "Satellite Kid", "is_hub": False, "parent_id": hub_id},
    )
```
to:
```python
def test_delete_location_with_children_returns_409(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Hub With Kids", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]

    satellite_resp = client.post(
        "/api/locations",
        json={"name": "Satellite Kid", "is_hub": False, "parent_id": hub_id, "lat": 35.1, "lon": 135.1},
    )
```

- [ ] **Step 3: Run the tests to confirm the new test fails and the others are consistent**

Run: `uv run pytest tests/test_locations_api.py -v`
Expected: `test_create_location_without_lat_lon_returns_422` FAILS (currently returns `201` since lat/lon are optional); the four tests just edited still PASS (they already send lat/lon or don't hit the create endpoint at all).

- [ ] **Step 4: Make lat/lon required in `LocationCreate`**

Edit `app/routers/locations.py`:

```python
class LocationCreate(BaseModel):
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = None
    lat: float
    lon: float
```

- [ ] **Step 5: Run the full test suite to confirm everything passes**

Run: `uv run pytest -v`
Expected: PASS — all tests green.

- [ ] **Step 6: Commit**

```bash
git add app/routers/locations.py tests/test_locations_api.py
git commit -m "$(cat <<'EOF'
fix: require lat/lon when creating a location via the API

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Click-to-filter reels by location

**Files:**
- Modify: `app/routers/reels.py`
- Modify: `app/templates/partials/reel_list.html`
- Modify: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `app/static/js/map.js`'s marker click handler (Task 1), which already calls `htmx.ajax('GET', '/ui/reels?location_id=' + loc.id, {target: '#reel-list', swap: 'innerHTML'})` — this task makes that call actually filter instead of being silently ignored.
- Produces: `GET /ui/reels` accepts an optional `location_id: str | None` query param. `_reel_list_context(session, location_id=None) -> dict` gains a `filtered_location: Location | None` key in its returned context, consumed by `reel_list.html`.

- [ ] **Step 1: Add the failing tests**

Add to `tests/test_ui_fragments.py`:

```python
def test_ui_reels_get_filters_by_location_id(client, session):
    hub_a = Location(name="Hub A", is_hub=True, lat=35.0, lon=135.0)
    hub_b = Location(name="Hub B", is_hub=True, lat=36.0, lon=136.0)
    session.add(hub_a)
    session.add(hub_b)
    session.commit()
    session.refresh(hub_a)
    session.refresh(hub_b)

    session.add(Reel(link="https://instagram.com/reel/a", location_id=hub_a.id, note="A spot"))
    session.add(Reel(link="https://instagram.com/reel/b", location_id=hub_b.id, note="B spot"))
    session.commit()

    response = client.get(f"/ui/reels?location_id={hub_a.id}")
    assert response.status_code == 200
    assert "A spot" in response.text
    assert "B spot" not in response.text
    assert "Hub A" in response.text
    assert "Mostra tutti" in response.text


def test_ui_reels_get_without_filter_shows_no_banner(client):
    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert "Mostra tutti" not in response.text
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `uv run pytest tests/test_ui_fragments.py -v -k "filters_by_location_id or without_filter_shows_no_banner"`
Expected: FAIL — `GET /ui/reels` doesn't accept `location_id` yet, and `reel_list.html` never renders a "Mostra tutti" banner.

- [ ] **Step 3: Extend `_reel_list_context` and `ui_list_reels` in `app/routers/reels.py`**

Replace:

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
```

with:

```python
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
        "taxonomy": TAXONOMY,
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
```

`ui_create_reel` and `ui_delete_reel` keep calling `_reel_list_context(session)` unchanged — they intentionally reset to the unfiltered list after an add/delete, since `location_id` now defaults to `None`.

- [ ] **Step 4: Update `app/templates/partials/reel_list.html`**

```html
{% if filtered_location %}
<div class="reel-filter-banner">
    <strong>Reel — {{ filtered_location.name }}</strong>
    <a href="#" hx-get="/ui/reels" hx-target="#reel-list" hx-swap="innerHTML">✕ Mostra tutti</a>
</div>
{% endif %}
<form hx-post="/ui/reels" hx-target="#reel-list" hx-swap="innerHTML">
    <input type="url" name="link" placeholder="Link Instagram" required>
    <select name="location_id" required>
        {% for loc in locations %}
        <option value="{{ loc.id }}" {{ 'selected' if filtered_location and loc.id == filtered_location.id else '' }}>{{ loc.name }}</option>
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
        <a href="{{ reel.link }}" target="_blank" rel="noopener noreferrer">{{ reel.link }}</a>
        {% if reel.note %}<span class="note">{{ reel.note }}</span>{% endif %}
        <span class="types">{% for t in reel.types %}{{ taxonomy[t].icon }}{% endfor %}</span>
        <button hx-delete="/ui/reels/{{ reel.id }}" hx-target="#reel-list" hx-swap="innerHTML">Elimina</button>
    </li>
    {% endfor %}
</ul>
```

- [ ] **Step 5: Run the full test suite to confirm everything passes**

Run: `uv run pytest -v`
Expected: PASS — all tests green.

- [ ] **Step 6: Manual verification**

```bash
uv run uvicorn app.main:app --reload
```

Open `http://localhost:8000/ui/map`, click a hub or satellite marker, and confirm:
- The reel panel below filters to that location's reels only
- A "Reel — <nome>" banner with "✕ Mostra tutti" appears
- The "aggiungi reel" dropdown has that location preselected
- Clicking "✕ Mostra tutti" restores the full reel list and hides the banner

- [ ] **Step 7: Commit**

```bash
git add app/routers/reels.py app/templates/partials/reel_list.html tests/test_ui_fragments.py
git commit -m "$(cat <<'EOF'
feat: filter reel panel by location on marker click

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
