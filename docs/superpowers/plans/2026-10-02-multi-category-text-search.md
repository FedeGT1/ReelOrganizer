# Multi-category filter + text search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users filter reels by multiple categories at once (AND semantics, affecting both map and reel list) and search reels by free text (note or location name, reel-list only).

**Architecture:** A new shared helper `reel_ids_matching_types` (AND-intersection across categories) lives in `app/routers/categories.py` and is reused by `app/routers/reels.py` and `app/routers/map.py`, replacing their single-category logic. Text search is a Python-side substring filter applied after the existing reel fetch, consistent with how category filtering already works in this codebase. On the frontend, `map.js` becomes the single source of truth for the active filter state (location, categories, search text) and exposes centralized `refreshMap()`/`refreshReelList()` builders, replacing the ad-hoc per-template URL building that exists today.

**Tech Stack:** FastAPI + SQLModel (SQLite) backend, Jinja2 server-rendered templates, htmx for partial swaps, vanilla JS (no framework) + Leaflet for the map.

## Global Constraints

- Category matching is AND across selected categories (a reel must have every selected category) — per `docs/superpowers/specs/2026-10-02-multi-category-text-search-design.md`.
- The category filter affects both the map (pin dimming) and the reel list.
- Text search matches case-insensitive substrings of the reel's `note` or its location's `name`; it affects the reel list only, never the map.
- All active filters (location, categories, text) combine with AND and are preserved independently when any one of them changes.
- Existing routes keep their query param names: `location_id`, `type` (now repeatable), and the new `q`.
- Follow existing code style: Python-side list filtering after an initial `select(Reel)` fetch (this codebase does not push category/text matching into SQL joins — see `reels.py`'s current type filter).

---

### Task 1: Shared AND-matching helper for categories

**Files:**
- Modify: `app/routers/categories.py`
- Test: `tests/test_reel_type_matching.py` (new)

**Interfaces:**
- Produces: `reel_ids_matching_types(session: Session, types: list[str]) -> set[str] | None` — importable from `app.routers.categories`. Returns `None` when `types` is empty (meaning "no filter"). Otherwise returns the set of reel ids tagged with **every** type in `types` (AND intersection); this set may be empty if nothing matches.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reel_type_matching.py`:

```python
from app.models import Reel, ReelType
from app.routers.categories import reel_ids_matching_types


def test_reel_ids_matching_types_returns_none_when_no_types_given(session):
    assert reel_ids_matching_types(session, []) is None


def test_reel_ids_matching_types_matches_reels_with_all_given_types(session):
    reel_both = Reel(link="https://instagram.com/reel/both", location_id="loc-1")
    reel_food_only = Reel(link="https://instagram.com/reel/food", location_id="loc-1")
    session.add(reel_both)
    session.add(reel_food_only)
    session.commit()
    session.refresh(reel_both)
    session.refresh(reel_food_only)
    session.add(ReelType(reel_id=reel_both.id, type="food"))
    session.add(ReelType(reel_id=reel_both.id, type="shopping"))
    session.add(ReelType(reel_id=reel_food_only.id, type="food"))
    session.commit()

    result = reel_ids_matching_types(session, ["food", "shopping"])

    assert result == {reel_both.id}


def test_reel_ids_matching_types_returns_empty_set_when_nothing_matches_all(session):
    reel = Reel(link="https://instagram.com/reel/x", location_id="loc-1")
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    result = reel_ids_matching_types(session, ["food", "culture"])

    assert result == set()
```

Note: `Reel.location_id` has a foreign key to `location.id`, but SQLite with the test engine does not enforce FK constraints by default, so a literal `"loc-1"` string is fine here and keeps the test focused on type matching only.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reel_type_matching.py -v`
Expected: FAIL with `ImportError: cannot import name 'reel_ids_matching_types'`

- [ ] **Step 3: Implement the helper**

In `app/routers/categories.py`, add after `get_valid_type_keys` (around line 27):

```python
def reel_ids_matching_types(session: Session, types: list[str]) -> set[str] | None:
    """None means "no filter". Otherwise the set of reel ids tagged with
    every type in `types` (AND across types)."""
    if not types:
        return None
    result: set[str] | None = None
    for type_value in types:
        ids = set(session.exec(select(ReelType.reel_id).where(ReelType.type == type_value)).all())
        result = ids if result is None else result & ids
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reel_type_matching.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/routers/categories.py tests/test_reel_type_matching.py
git commit -m "feat: add AND-intersection helper for multi-category reel matching"
```

---

### Task 2: Multi-category AND filtering + text search in the reels router

**Files:**
- Modify: `app/routers/reels.py`
- Test: `tests/test_reels_api.py`

**Interfaces:**
- Consumes: `reel_ids_matching_types(session, types) -> set[str] | None` from Task 1 (`app.routers.categories`).
- Produces:
  - `_filter_reels_by_text(session: Session, reels: list[Reel], q: Optional[str]) -> list[Reel]` — new private helper, reused by both the API and UI routes.
  - `_reel_list_context(session, location_id=None, type_values: Optional[list[str]] = None, q: Optional[str] = None) -> dict` — signature change (previously `type_value: Optional[str]`). Returned dict drops the old `active_type` key (no longer consumed by any template after Task 5) and no longer includes it.
  - `GET /api/reels` and `GET /ui/reels` both accept repeatable `?type=` and an optional `?q=`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_reels_api.py`:

```python
def test_filter_reels_by_multiple_types_requires_all(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    reel_both = Reel(link="https://instagram.com/reel/both", location_id=hub.id)
    reel_food_only = Reel(link="https://instagram.com/reel/food", location_id=hub.id)
    session.add(reel_both)
    session.add(reel_food_only)
    session.commit()
    session.refresh(reel_both)
    session.refresh(reel_food_only)
    session.add(ReelType(reel_id=reel_both.id, type="food"))
    session.add(ReelType(reel_id=reel_both.id, type="shopping"))
    session.add(ReelType(reel_id=reel_food_only.id, type="food"))
    session.commit()

    response = client.get("/api/reels?type=food&type=shopping")
    data = response.json()

    assert len(data) == 1
    assert data[0]["link"] == "https://instagram.com/reel/both"


def test_search_reels_matches_note(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    session.add(Reel(link="https://instagram.com/reel/a", location_id=hub.id, note="Best ramen ever"))
    session.add(Reel(link="https://instagram.com/reel/b", location_id=hub.id, note="Shrine visit"))
    session.commit()

    response = client.get("/api/reels?q=ramen")
    data = response.json()

    assert len(data) == 1
    assert data[0]["note"] == "Best ramen ever"


def test_search_reels_matches_location_name_case_insensitively(client, session):
    hub = Location(name="Shibuya Crossing", is_hub=True)
    other_hub = Location(name="Hub B", is_hub=True)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    session.add(Reel(link="https://instagram.com/reel/a", location_id=hub.id))
    session.add(Reel(link="https://instagram.com/reel/b", location_id=other_hub.id))
    session.commit()

    response = client.get("/api/reels?q=SHIBUYA")
    data = response.json()

    assert len(data) == 1
    assert data[0]["location_id"] == hub.id


def test_search_reels_combines_with_type_filter(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    reel_match = Reel(link="https://instagram.com/reel/match", location_id=hub.id, note="Great ramen")
    reel_wrong_type = Reel(link="https://instagram.com/reel/other", location_id=hub.id, note="Great ramen too")
    session.add(reel_match)
    session.add(reel_wrong_type)
    session.commit()
    session.refresh(reel_match)
    session.refresh(reel_wrong_type)
    session.add(ReelType(reel_id=reel_match.id, type="food"))
    session.add(ReelType(reel_id=reel_wrong_type.id, type="culture"))
    session.commit()

    response = client.get("/api/reels?type=food&q=ramen")
    data = response.json()

    assert len(data) == 1
    assert data[0]["link"] == "https://instagram.com/reel/match"


def test_ui_reels_search_filters_by_note_or_location_name(client, session):
    hub = Location(name="Shibuya", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    session.add(Reel(link="https://instagram.com/reel/a", location_id=hub.id, note="Great ramen"))
    session.add(Reel(link="https://instagram.com/reel/b", location_id=hub.id, note="Shrine visit"))
    session.commit()

    response = client.get("/ui/reels?q=ramen")
    assert response.status_code == 200
    assert "Great ramen" in response.text
    assert "Shrine visit" not in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reels_api.py -v -k "multiple_types or search_reels or ui_reels_search"`
Expected: FAIL — `test_filter_reels_by_multiple_types_requires_all` fails because today's `type` param is a single `Optional[str]`, not a repeatable list, so it cannot express "both food and shopping" at all; and the `q`-based tests fail because `/api/reels` and `/ui/reels` don't recognize `q` (it's simply ignored, so all reels come back unfiltered).

- [ ] **Step 3: Implement the changes**

In `app/routers/reels.py`, update the import line (line 4) to add `Query`:

```python
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
```

Update the import from `categories` (line 11):

```python
from app.routers.categories import get_taxonomy, get_valid_type_keys, reel_ids_matching_types
```

Add a new helper after `_location_and_satellite_ids` (around line 27):

```python
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
```

Replace the `list_reels` API route (lines 91-108):

```python
@router.get("")
def list_reels(
    location_id: Optional[str] = None,
    type: list[str] = Query([]),
    q: Optional[str] = None,
    session: Session = Depends(get_session),
):
    query = select(Reel)
    if location_id is not None:
        query = query.where(Reel.location_id.in_(_location_and_satellite_ids(session, location_id)))
    reels = session.exec(query).all()

    type_ids = reel_ids_matching_types(session, type)
    if type_ids is not None:
        reels = [r for r in reels if r.id in type_ids]

    reels = _filter_reels_by_text(session, reels, q)

    return [_serialize_reel(session, r) for r in reels]
```

Replace `_reel_list_context` (lines 148-168):

```python
def _reel_list_context(
    session: Session,
    location_id: Optional[str] = None,
    type_values: Optional[list[str]] = None,
    q: Optional[str] = None,
) -> dict:
    type_values = type_values or []
    query = select(Reel)
    if location_id is not None:
        query = query.where(Reel.location_id.in_(_location_and_satellite_ids(session, location_id)))
    reels = session.exec(query).all()

    type_ids = reel_ids_matching_types(session, type_values)
    if type_ids is not None:
        reels = [r for r in reels if r.id in type_ids]

    reels = _filter_reels_by_text(session, reels, q)

    filtered_location = session.get(Location, location_id) if location_id else None
    return {
        "reels": [_serialize_reel(session, r) for r in reels],
        "taxonomy": get_taxonomy(session),
        "filtered_location": filtered_location,
    }
```

Replace the `ui_list_reels` route (lines 232-241):

```python
@ui_router.get("/reels")
def ui_list_reels(
    request: Request,
    location_id: Optional[str] = None,
    type: list[str] = Query([]),
    q: Optional[str] = None,
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request, "partials/reel_list.html", _reel_list_context(session, location_id, type, q)
    )
```

- [ ] **Step 4: Run the full reels test suite**

Run: `pytest tests/test_reels_api.py tests/test_ui_fragments.py -v`
Expected: all pass. (`test_ui_fragments.py`'s `test_ui_reels_get_filters_by_type` still passes unchanged — a single `?type=food` value still works through the new list-based param.)

- [ ] **Step 5: Commit**

```bash
git add app/routers/reels.py tests/test_reels_api.py
git commit -m "feat: support multi-category AND filtering and text search on reels"
```

---

### Task 3: Multi-category AND filtering on the map

**Files:**
- Modify: `app/routers/map.py`
- Test: `tests/test_map_api.py`

**Interfaces:**
- Consumes: `reel_ids_matching_types(session, types) -> set[str] | None` from Task 1.
- Produces:
  - `locations_with_types(session: Session, type_values: list[str]) -> set[str]` — replaces `locations_with_type`.
  - `visible_location_ids(session, locations, type_values: list[str] | None) -> tuple[set[str], set[str]]` — third param renamed/retyped from `type_value: str | None` to `type_values: list[str] | None`.
  - `render_map_html(session, type_values: list[str] | None = None) -> str` — param renamed/retyped from `type_value: str | None`.
  - `GET /ui/map` accepts repeatable `?type=`.

- [ ] **Step 1: Update existing call sites in tests (these must change before the signature change, so step 2 below fails for the right reason)**

In `tests/test_map_api.py`, update the three calls to `visible_location_ids`:

```python
    locations = compute_map(session)
    visible_ids, anchors = visible_location_ids(session, locations, [])
```

(applies to `test_visible_location_ids_hides_hub_with_no_reels_and_no_filled_children` and `test_visible_location_ids_keeps_empty_hub_as_anchor_for_filled_satellite`, both currently passing `None`)

```python
    locations = compute_map(session)
    visible_ids, _ = visible_location_ids(session, locations, ["culture"])
```

(applies to `test_visible_location_ids_uses_type_specific_emptiness_when_type_active`, currently passing `"culture"`)

- [ ] **Step 2: Write the new failing test for AND semantics**

Add to `tests/test_map_api.py`:

```python
def test_visible_location_ids_requires_all_selected_types(session):
    hub_both = Location(name="Both", is_hub=True, lat=35.0, lon=135.0)
    hub_food_only = Location(name="FoodOnly", is_hub=True, lat=36.0, lon=136.0)
    session.add(hub_both)
    session.add(hub_food_only)
    session.commit()
    session.refresh(hub_both)
    session.refresh(hub_food_only)

    reel_both = Reel(link="https://instagram.com/reel/both", location_id=hub_both.id)
    reel_food = Reel(link="https://instagram.com/reel/food", location_id=hub_food_only.id)
    session.add(reel_both)
    session.add(reel_food)
    session.commit()
    session.refresh(reel_both)
    session.refresh(reel_food)
    session.add(ReelType(reel_id=reel_both.id, type="food"))
    session.add(ReelType(reel_id=reel_both.id, type="shopping"))
    session.add(ReelType(reel_id=reel_food.id, type="food"))
    session.commit()

    locations = compute_map(session)
    visible_ids, _ = visible_location_ids(session, locations, ["food", "shopping"])

    assert hub_both.id in visible_ids
    assert hub_food_only.id not in visible_ids


def test_ui_map_filters_by_multiple_types(client, session):
    hub_both = Location(name="Both", is_hub=True, lat=35.0, lon=135.0)
    hub_food_only = Location(name="FoodOnly", is_hub=True, lat=36.0, lon=136.0)
    session.add(hub_both)
    session.add(hub_food_only)
    session.commit()
    session.refresh(hub_both)
    session.refresh(hub_food_only)

    reel_both = Reel(link="https://instagram.com/reel/both", location_id=hub_both.id)
    reel_food = Reel(link="https://instagram.com/reel/food", location_id=hub_food_only.id)
    session.add(reel_both)
    session.add(reel_food)
    session.commit()
    session.refresh(reel_both)
    session.refresh(reel_food)
    session.add(ReelType(reel_id=reel_both.id, type="food"))
    session.add(ReelType(reel_id=reel_both.id, type="shopping"))
    session.add(ReelType(reel_id=reel_food.id, type="food"))
    session.commit()

    response = client.get("/ui/map?type=food&type=shopping")
    assert response.status_code == 200

    from tests.test_ui_fragments import _map_data

    locations = {loc["id"]: loc for loc in _map_data(response.text)}
    assert hub_both.id in locations
    assert hub_food_only.id not in locations
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_map_api.py -v`
Expected: FAIL — `test_visible_location_ids_requires_all_selected_types` fails because today's `locations_with_type` does a single-type lookup and crashes or misbehaves on a list; the other two updated calls raise a `TypeError` because `visible_location_ids` still expects a `str | None` third arg being iterated as a single type.

- [ ] **Step 4: Implement the changes**

In `app/routers/map.py`, replace `locations_with_type` (lines 44-52):

```python
def locations_with_types(session: Session, type_values: list[str]) -> set[str]:
    reel_ids = reel_ids_matching_types(session, type_values)
    if not reel_ids:
        return set()
    return set(
        session.exec(select(Reel.location_id).where(Reel.id.in_(reel_ids))).all()
    )
```

Update the import from `categories` (line 10):

```python
from app.routers.categories import get_taxonomy, reel_ids_matching_types
```

Replace `visible_location_ids` (lines 55-79):

```python
def visible_location_ids(
    session: Session,
    locations: list[dict],
    type_values: list[str] | None,
) -> tuple[set[str], set[str]]:
    """(visible_ids, anchor_hub_ids). Locations with no qualifying reel are
    always excluded. anchor_hub_ids is always a subset of visible_ids: hubs
    that qualify only because a child satellite qualifies, not because they
    have reels of their own."""
    type_values = type_values or []
    if type_values:
        qualifying = locations_with_types(session, type_values)
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

Replace `render_map_html` (lines 82-119):

```python
def render_map_html(session: Session, type_values: list[str] | None = None) -> str:
    type_values = type_values or []
    locations = compute_map(session)
    hubs_by_id = {loc["id"]: loc for loc in locations if loc["is_hub"]}
    matching_location_ids = locations_with_types(session, type_values) if type_values else set()
    visible_ids, anchor_hub_ids = visible_location_ids(session, locations, type_values)

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
        taxonomy=get_taxonomy(session),
    )
```

Replace the `/ui/map` route (lines 122-128):

```python
@ui_router.get("/map")
def ui_map(
    request: Request,
    type: list[str] = Query([]),
    session: Session = Depends(get_session),
):
    return HTMLResponse(render_map_html(session, type))
```

Add `Query` to the fastapi import (line 3):

```python
from fastapi import APIRouter, Depends, Query, Request
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_map_api.py -v`
Expected: all pass, including `test_ui_map_filters_by_multiple_types`. That test only inspects the `map-data` JSON blob (driven purely by Python-side `map_locations_json`), so it already passes even though `map.html` still references the old `active_type` template variable at this point — Jinja's default (non-strict) `Undefined` makes that reference silently falsy rather than erroring. The chip highlighting itself stays visually stale until Task 4 fixes the template; that's expected and harmless for this task.

- [ ] **Step 6: Commit**

```bash
git add app/routers/map.py tests/test_map_api.py
git commit -m "feat: support multi-category AND filtering on the map"
```

---

### Task 4: Multi-select category chips (map.js + map.html)

**Files:**
- Modify: `app/static/js/map.js`
- Modify: `app/templates/partials/map.html`
- Test: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `/ui/map?type=...&type=...` and `/ui/reels?location_id=...&type=...&type=...&q=...` from Tasks 2-3.
- Produces (all on `window`, called from template attributes):
  - `window.getCurrentLocationId()` / `window.setCurrentLocationId(id)` — unchanged signatures (kept from before).
  - `window.getCurrentTypes()` — returns `string[]`, replaces the old `window.getCurrentType()`.
  - `window.toggleType(key)` — adds/removes `key` from the active types, then refreshes both map and reel list.
  - `window.clearTypes()` — empties active types, then refreshes both.
  - Internal (not called from templates, used by Task 5 and by this task's own pin-click handler): `refreshMap()`, `refreshReelList()`.

- [ ] **Step 1: Write the failing test for the new chip markup**

Replace `test_ui_map_includes_type_filter_chips` in `tests/test_ui_fragments.py` (lines 38-48):

```python
def test_ui_map_includes_type_filter_chips(client, session):
    from app.models import Category

    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/ui/map")
    assert response.status_code == 200
    assert "Cibo" in response.text
    assert 'data-type="food"' in response.text
    assert "window.toggleType('food')" in response.text
    assert "window.clearTypes()" in response.text


def test_ui_map_marks_multiple_active_chips(client, session):
    from app.models import Category

    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.add(Category(key="shopping", label="Shopping", icon="🛍️", color="#35496B"))
    session.commit()

    response = client.get("/ui/map?type=food&type=shopping")
    assert response.status_code == 200

    import re

    food_chip = re.search(r'<a[^>]*data-type="food"[^>]*>', response.text).group(0)
    shopping_chip = re.search(r'<a[^>]*data-type="shopping"[^>]*>', response.text).group(0)
    assert "active" in food_chip
    assert "active" in shopping_chip
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_fragments.py -v -k "chip"`
Expected: FAIL — the old markup still renders `hx-get`/`htmx.ajax` attributes, not `data-type`/`window.toggleType(...)`/`window.clearTypes()`, so the new assertions don't find their expected substrings. (The template's stale `active_type` reference from Task 3 doesn't raise — Jinja's default non-strict `Undefined` just makes it falsy — so the failure here is a plain assertion mismatch, not an exception.)

- [ ] **Step 3: Rewrite `app/templates/partials/map.html`**

```html
<div class="map-filters">
    <a href="#" class="chip {{ 'active' if not active_types else '' }}"
       onclick="window.clearTypes(); return false;">Tutti</a>
    {% for key, info in taxonomy.items() %}
    <a href="#" class="chip {{ 'active' if key in active_types else '' }}"
       data-type="{{ key }}" style="background-color: {{ info.color }}; border-color: {{ info.color }};"
       onclick="window.toggleType('{{ key }}'); return false;">
        {{ info.icon }} {{ info.label }}
    </a>
    {% endfor %}
</div>
<div id="leaflet-map" class="leaflet-map"></div>
<script type="application/json" id="map-data">{{ map_locations_json | safe }}</script>
<script>
    initReelMap("leaflet-map", "map-data", {{ active_types | tojson }});
</script>
```

- [ ] **Step 4: Rewrite the filter-state section of `app/static/js/map.js`**

Replace lines 9-16 (`let currentLocationId = null; ... window.getCurrentType = ...`):

```javascript
let currentLocationId = null;
let currentTypes = [];

window.getCurrentLocationId = () => currentLocationId;
window.setCurrentLocationId = (id) => {
    currentLocationId = id;
};
window.getCurrentTypes = () => currentTypes;

function buildTypeQuery(types) {
    return types.map((t) => "type=" + encodeURIComponent(t)).join("&");
}

function refreshMap() {
    const typeQuery = buildTypeQuery(currentTypes);
    const url = "/ui/map" + (typeQuery ? "?" + typeQuery : "");
    htmx.ajax("GET", url, { target: "#map-container", swap: "innerHTML" });
}

function refreshReelList() {
    const params = [];
    if (currentLocationId) {
        params.push("location_id=" + encodeURIComponent(currentLocationId));
    }
    const typeQuery = buildTypeQuery(currentTypes);
    if (typeQuery) {
        params.push(typeQuery);
    }
    const searchInput = document.getElementById("reel-search-input");
    const q = searchInput ? searchInput.value.trim() : "";
    if (q) {
        params.push("q=" + encodeURIComponent(q));
    }
    const url = "/ui/reels" + (params.length ? "?" + params.join("&") : "");
    htmx.ajax("GET", url, { target: "#reel-list", swap: "innerHTML" });
}

window.toggleType = (key) => {
    const index = currentTypes.indexOf(key);
    if (index === -1) {
        currentTypes.push(key);
    } else {
        currentTypes.splice(index, 1);
    }
    refreshMap();
    refreshReelList();
};

window.clearTypes = () => {
    currentTypes = [];
    refreshMap();
    refreshReelList();
};

window.clearLocationFilter = () => {
    currentLocationId = null;
    refreshReelList();
};
```

Update `initReelMap`'s signature and first line (around what was line 18-19) to accept an array instead of a single string:

```javascript
function initReelMap(containerId, dataId, typeValues) {
    currentTypes = typeValues || [];
```

Update the pin click handler (previously lines 58-66) to use the centralized refresh instead of building its own URL:

```javascript
        hitArea.on("click", () => {
            currentLocationId = loc.id;
            refreshReelList();
        });
```

- [ ] **Step 5: Run the map/reel-list test files**

Run: `pytest tests/test_ui_fragments.py tests/test_map_api.py tests/test_index_page.py -v`
Expected: all pass, including `test_ui_map_filters_by_multiple_types` from Task 3.

- [ ] **Step 6: Commit**

```bash
git add app/static/js/map.js app/templates/partials/map.html tests/test_ui_fragments.py
git commit -m "feat: multi-select category chips with centralized filter refresh"
```

---

### Task 5: Text search input and location-banner wiring

**Files:**
- Modify: `app/templates/index.html`
- Modify: `app/templates/partials/reel_list.html`
- Modify: `app/static/css/style.css`
- Test: `tests/test_index_page.py`, `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `window.clearLocationFilter()`, internal `refreshReelList()` (already debounce-free; debouncing happens at the call site) from Task 4.
- Produces: `window.handleSearchInput(value)` — debounces 400ms, then triggers `refreshReelList()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_index_page.py`:

```python
def test_index_page_renders_search_input(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="reel-search-input"' in response.text
    assert "window.handleSearchInput(this.value)" in response.text
```

Add to `tests/test_ui_fragments.py` (near the other `Mostra tutti` tests):

```python
def test_ui_reels_mostra_tutti_banner_uses_clear_location_filter(client, session):
    hub_a = Location(name="Hub A", is_hub=True)
    session.add(hub_a)
    session.commit()
    session.refresh(hub_a)
    session.add(Reel(link="https://instagram.com/reel/a", location_id=hub_a.id))
    session.commit()

    response = client.get(f"/ui/reels?location_id={hub_a.id}")
    assert response.status_code == 200
    assert "window.clearLocationFilter()" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_index_page.py tests/test_ui_fragments.py -v -k "search_input or clear_location_filter"`
Expected: FAIL — neither the search input nor the new banner button exist yet.

- [ ] **Step 3: Add the search input to `app/templates/index.html`**

Insert before the `<section id="reel-list" ...>` line:

```html
<input type="search" id="reel-search-input" class="reel-search-input"
       placeholder="Cerca per nota o location..." autocomplete="off"
       oninput="window.handleSearchInput(this.value)">
```

- [ ] **Step 4: Add the debounce handler to `app/static/js/map.js`**

Append at the end of the file:

```javascript
let searchDebounceTimer = null;

window.handleSearchInput = (value) => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
        refreshReelList();
    }, 400);
};
```

- [ ] **Step 5: Update the "Mostra tutti" banner in `app/templates/partials/reel_list.html`**

Replace lines 1-7:

```html
{% if filtered_location %}
<div class="reel-filter-banner">
    <strong>Reel — {{ filtered_location.name }}</strong>
    <a href="#" onclick="window.clearLocationFilter(); return false;">✕ Mostra tutti</a>
</div>
{% endif %}
```

- [ ] **Step 6: Add input styling to `app/static/css/style.css`**

Add after the `.chip` rules (after line 85):

```css
.reel-search-input {
    display: block;
    width: 100%;
    max-width: 100%;
    margin: 0.75rem 0;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--color-ink-medium);
    border-radius: 6px;
    background: var(--color-paper);
    color: var(--color-ink);
    font-family: inherit;
    font-size: 1rem;
    box-sizing: border-box;
}
```

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add app/templates/index.html app/templates/partials/reel_list.html app/static/css/style.css app/static/js/map.js tests/test_index_page.py tests/test_ui_fragments.py
git commit -m "feat: add live text search input and wire up clear-location-filter button"
```

---

### Task 6: Manual browser verification

**Files:** none (manual QA pass only, no code changes expected unless a bug is found)

- [ ] **Step 1: Start the dev server**

Run: `uvicorn app.main:app --reload` (check `README.md` or existing run scripts if the command differs)

- [ ] **Step 2: Verify multi-category AND filtering**

In the browser: create or use seed data with at least one reel tagged with two categories and another tagged with only one of them. Click both category chips — confirm only the double-tagged reel's location stays un-dimmed on the map, and only that reel shows in the list. Click "Tutti" — confirm both chips deactivate and everything reappears.

- [ ] **Step 3: Verify text search**

Type a substring of a reel's note — confirm the list narrows after ~400ms without the input losing focus or its cursor jumping. Clear the box — confirm the full list (respecting any active category filter) returns.

- [ ] **Step 4: Verify combined filters persist independently**

Select a location pin, then a category chip, then type a search term. Confirm all three narrow the list together (AND), and clearing any one (via "Mostra tutti", "Tutti", or clearing the search box) leaves the other two active.

- [ ] **Step 5: Report results to the user**

Summarize what was verified and flag anything that didn't behave as expected before considering this plan complete.
