# Location Audit & Merge Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tool that scans all existing `Location` rows for likely duplicates (reusing the already-shipped `resolve_place` tiers), and lets the user merge a confirmed pair directly from a new `/strumenti` nav section, without any new matching logic or AI calls.

**Architecture:** `resolve_place` gains one additive, optional parameter so it can be asked "if this location were a fresh proposal, what would it match?" excluding itself. A new `app/routers/audit.py` runs that question against every location, buckets results into "certain duplicate" vs "worth reviewing", and renders them with merge buttons that call a new `_merge_locations` primitive in `app/routers/locations.py`. Four nav links collapse into one "Strumenti" page.

**Tech Stack:** Python 3.11, FastAPI, SQLModel/SQLite, Jinja2/htmx — same stack, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-06-location-audit-tool-design.md`

## Global Constraints

- No database schema changes.
- `resolve_place`'s new `exclude_location_id` parameter is optional, defaults to `None`, and must not change behavior for any existing caller that doesn't pass it (`ai_categorize.py`, `ai_multi_categorize.py`).
- Merging never modifies the "keep" location's own `name`/`lat`/`lon`/`geocode_confidence` — only the "drop" location's reels get reassigned, then the drop location is deleted.
- Merge is blocked (409) when the "drop" location has child locations (`parent_id == drop_id`) — same guard already used by `_delete_location`.
- Detection is deterministic only — no AI calls, reuses `resolve_place` as-is.
- No persisted "ignore this pair" state in v1 — every scan recomputes live.
- Nav becomes: Home, Strumenti, Chiedi all'AI, Logout. "Strumenti" page lists: Gestisci categorie, Gestisci hub, Esporta reel, Cookie Instagram, Audit pregresso.

## Review Focus

- A location must never match itself in its own scan (the whole point of `exclude_location_id`) — without this, every single location would trivially "duplicate" itself and flood the certain-pairs list.
- A pair must never appear in both the "certain" and "da verificare" sections — `resolve_place`'s tiers are directional (hub-containment only checks one way), so the same pair can come back `auto` from one location's scan and merely a `candidate` from the other's.
- Merging a location that still has child locations must 409, not silently orphan the children (same risk class as the existing `_delete_location` guard).
- The surviving ("keep") location's own row must come out of a merge byte-identical to how it went in — only the dropped location's reels change `location_id`.
- The existing test `tests/test_locations_page.py::test_nav_includes_locations_link` asserts the current flat nav (`"Gestisci hub"` directly on `/`) — this plan's nav change breaks it, and it must be updated, not left red or silently skipped.

---

## File Structure

**Create:**
- `app/routers/audit.py` — detection scan + merge-triggering UI endpoints.
- `app/templates/strumenti.html` — tool links page.
- `app/templates/audit.html` — audit page shell (scan button + results container).
- `app/templates/partials/audit_results.html` — scan results (certain/review pairs + merge buttons).
- `tests/test_audit.py` — tests for the above.

**Modify:**
- `app/location_matching.py` — `resolve_place` gains `exclude_location_id`.
- `app/routers/locations.py` — new `_merge_locations` + `POST /api/locations/{keep_id}/merge/{drop_id}`.
- `app/templates/base.html` — nav collapses 4 links into "Strumenti".
- `app/main.py` — new `/strumenti` and `/strumenti/audit` page routes, register `audit.ui_router`.
- `tests/test_location_matching.py`, `tests/test_locations_api.py`, `tests/test_locations_page.py` — new/updated tests.

---

### Task 1: `resolve_place` gains `exclude_location_id`

**Files:**
- Modify: `app/location_matching.py:92-100`
- Test: `tests/test_location_matching.py`

**Interfaces:**
- Produces: `resolve_place(session, place_name, near_hub, lat, lon, exclude_location_id: Optional[str] = None) -> PlaceResolution` — used by Task 3's `_find_anomalies`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_location_matching.py (append)
def test_resolve_place_excludes_specified_location_from_matching(session):
    loc = _add(session, name="Nishiki Market", is_hub=False, lat=35.005, lon=135.765)

    resolution = resolve_place(session, "Nishiki Market", None, None, None, exclude_location_id=loc.id)

    assert resolution.place_tier == "ambiguous"
    assert resolution.place_location_id is None


def test_resolve_place_excluded_location_never_appears_as_candidate(session):
    excluded = _add(session, name="Some Shop", is_hub=False, lat=35.0, lon=135.0)
    other = _add(session, name="Other Shop", is_hub=False, lat=35.0001, lon=135.0001)

    resolution = resolve_place(session, "New Shop", None, 35.0, 135.0, exclude_location_id=excluded.id)

    candidate_ids = {c.id for c in resolution.place_candidates}
    assert excluded.id not in candidate_ids
    assert other.id in candidate_ids


def test_resolve_place_exclude_location_id_defaults_to_none(session):
    loc = _add(session, name="Nishiki Market", is_hub=False, lat=35.005, lon=135.765)

    resolution = resolve_place(session, "Nishiki Market", None, None, None)

    assert resolution.place_tier == "auto"
    assert resolution.place_location_id == loc.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_location_matching.py -v -k exclude`
Expected: FAIL with `TypeError: resolve_place() got an unexpected keyword argument 'exclude_location_id'`

- [ ] **Step 3: Write the implementation**

In `app/location_matching.py`, change `resolve_place`'s signature and the start of its body:

```python
def resolve_place(
    session: Session,
    place_name: str,
    near_hub: Optional[str],
    lat: Optional[float],
    lon: Optional[float],
    exclude_location_id: Optional[str] = None,
) -> PlaceResolution:
    normalized_place = normalize_place_name(place_name)
    locations = session.exec(select(Location)).all()
    if exclude_location_id:
        locations = [loc for loc in locations if loc.id != exclude_location_id]
```

(The rest of the function body is unchanged — every reference below this point already uses the local `locations` variable.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_location_matching.py -v`
Expected: PASS (all tests, including every pre-existing one — this change is purely additive)

- [ ] **Step 5: Commit**

```bash
git add app/location_matching.py tests/test_location_matching.py
git commit -m "feat: let resolve_place exclude one location from its own matching pool"
```

---

### Task 2: `_merge_locations`

**Files:**
- Modify: `app/routers/locations.py`
- Test: `tests/test_locations_api.py`

**Interfaces:**
- Consumes: `_has_children` (already defined in this file).
- Produces: `_merge_locations(session, keep_id: str, drop_id: str) -> None` — used by Task 3's `audit.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_locations_api.py (append)
def test_merge_locations_reassigns_reels_and_deletes_drop(client, session):
    keep = Location(name="Shibuya", is_hub=False, lat=35.6590, lon=139.7005)
    drop = Location(name="Shibuya Crossing", is_hub=False, lat=35.6591, lon=139.7006)
    session.add(keep)
    session.add(drop)
    session.commit()
    session.refresh(keep)
    session.refresh(drop)

    reel = Reel(link="https://instagram.com/reel/x", location_id=drop.id, note="nota")
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.post(f"/api/locations/{keep.id}/merge/{drop.id}")
    assert response.status_code == 204

    session.refresh(reel)
    assert reel.location_id == keep.id
    assert session.get(Location, drop.id) is None
    kept = session.get(Location, keep.id)
    assert kept.name == "Shibuya"
    assert kept.lat == 35.6590


def test_merge_locations_blocks_when_drop_has_children(client, session):
    hub = Location(name="Hub A", is_hub=True)
    other_hub = Location(name="Hub B", is_hub=True)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    satellite = Location(name="Satellite", is_hub=False, parent_id=hub.id)
    session.add(satellite)
    session.commit()

    response = client.post(f"/api/locations/{other_hub.id}/merge/{hub.id}")
    assert response.status_code == 409
    assert session.get(Location, hub.id) is not None


def test_merge_locations_returns_404_for_missing_ids(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(f"/api/locations/{hub.id}/merge/does-not-exist")
    assert response.status_code == 404
```

(`Reel` must be imported in this test file — check the existing `from app.models import ...` line at the top and add it if not already present; `tests/test_locations_api.py` currently imports `Location, Reel, ReelType` already, so no change needed there.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_locations_api.py -v -k merge`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Write the implementation**

In `app/routers/locations.py`, add after `_delete_location`:

```python
def _merge_locations(session: Session, keep_id: str, drop_id: str) -> None:
    keep = session.get(Location, keep_id)
    drop = session.get(Location, drop_id)
    if keep is None or drop is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if _has_children(session, drop_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot merge a location that still has child locations; reassign or delete them first",
        )
    for reel in session.exec(select(Reel).where(Reel.location_id == drop_id)).all():
        reel.location_id = keep_id
        session.add(reel)
    session.commit()
    session.delete(drop)
    session.commit()
```

Add after `delete_location`'s route:

```python
@router.post("/{keep_id}/merge/{drop_id}", status_code=status.HTTP_204_NO_CONTENT)
def merge_locations(keep_id: str, drop_id: str, session: Session = Depends(get_session)):
    _merge_locations(session, keep_id, drop_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_locations_api.py -v`
Expected: PASS (all tests, including every pre-existing one)

- [ ] **Step 5: Commit**

```bash
git add app/routers/locations.py tests/test_locations_api.py
git commit -m "feat: add location merge (reassign reels, delete the redundant one)"
```

---

### Task 3: Audit scan, UI, and nav restructuring

**Files:**
- Create: `app/routers/audit.py`, `app/templates/strumenti.html`, `app/templates/audit.html`, `app/templates/partials/audit_results.html`
- Modify: `app/templates/base.html:21-32`, `app/main.py`
- Test: `tests/test_audit.py` (new), `tests/test_locations_page.py` (update)

**Interfaces:**
- Consumes: `resolve_place(..., exclude_location_id=...)` (Task 1), `_merge_locations`, `_reel_counts` (Task 2 and pre-existing, both in `app/routers/locations.py`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_audit.py (new file)
from app.models import Location, Reel


def test_audit_scan_flags_certain_duplicate(client, session):
    loc_a = Location(name="Surugaya - Akihabara", is_hub=False, lat=35.7, lon=139.77)
    loc_b = Location(name="Surugaya Akihabara (駿河屋秋葉原)", is_hub=False, lat=35.7001, lon=139.7701)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Surugaya" in response.text
    assert "Nessun duplicato quasi certo trovato." not in response.text


def test_audit_scan_flags_review_pair_for_nearby_different_names(client, session):
    loc_a = Location(name="Starbucks Shibuya", is_hub=False, lat=35.6590, lon=139.7005)
    loc_b = Location(name="Pokémon Center Shibuya", is_hub=False, lat=35.6590, lon=139.7005)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessun duplicato quasi certo trovato." in response.text
    assert "Starbucks Shibuya" in response.text
    assert "Pokémon Center Shibuya" in response.text


def test_audit_scan_shows_empty_state_when_no_anomalies(client, session):
    session.add(Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503))
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert "Nessun duplicato quasi certo trovato." in response.text
    assert "Nessun caso da verificare." in response.text


def test_audit_scan_does_not_list_the_same_pair_twice(client, session):
    loc_a = Location(name="Nishiki Market", is_hub=False, lat=35.005, lon=135.765)
    loc_b = Location(name="nishiki market", is_hub=False, lat=35.0051, lon=135.7651)
    session.add(loc_a)
    session.add(loc_b)
    session.commit()

    response = client.get("/ui/audit/scan")
    # Each name appears exactly once (its one row in the pair list) -- if the
    # pair were listed twice (once per direction the scan visits it from),
    # these counts would be 2 each instead of 1.
    assert response.text.count("Nishiki Market") == 1
    assert response.text.count("nishiki market") == 1


def test_audit_scan_does_not_duplicate_pair_across_sections_for_directional_match(client, session):
    # "Tokyo" (satellite) auto-matches the hub "Tokyo / Kanto" via the
    # short-name-contained-in-hub-label rule (tier 1), but the hub's own
    # scan only finds "Tokyo" as a distance-based candidate (the
    # containment check only fires one direction) -- without fully
    # processing every `auto` match before any `candidate` match, this
    # pair would show up in both the certain and the review section.
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    satellite = Location(name="Tokyo", is_hub=False, parent_id=hub.id, lat=35.685, lon=139.655)
    session.add(hub)
    session.add(satellite)
    session.commit()

    response = client.get("/ui/audit/scan")
    assert response.status_code == 200
    assert response.text.count("Tokyo / Kanto") == 1


def test_ui_audit_merge_removes_pair_and_reassigns_reel(client, session):
    keep = Location(name="Shibuya Crossing", is_hub=False, lat=35.6590, lon=139.7005)
    drop = Location(name="Shibuya Crossing ", is_hub=False, lat=35.6591, lon=139.7006)
    session.add(keep)
    session.add(drop)
    session.commit()
    session.refresh(keep)
    session.refresh(drop)

    reel = Reel(link="https://instagram.com/reel/x", location_id=drop.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.post(f"/ui/audit/merge/{keep.id}/{drop.id}")
    assert response.status_code == 200
    assert "Nessun duplicato quasi certo trovato." in response.text

    session.refresh(reel)
    assert reel.location_id == keep.id
    assert session.get(Location, drop.id) is None


def test_ui_audit_merge_renders_error_when_drop_has_children(client, session):
    hub = Location(name="Hub A", is_hub=True, lat=35.0, lon=135.0)
    other_hub = Location(name="Hub B", is_hub=True, lat=36.0, lon=136.0)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    satellite = Location(name="Satellite", is_hub=False, parent_id=hub.id, lat=35.001, lon=135.001)
    session.add(satellite)
    session.commit()

    response = client.post(f"/ui/audit/merge/{other_hub.id}/{hub.id}")
    assert response.status_code == 200
    assert "Impossibile unire" in response.text
    assert session.get(Location, hub.id) is not None


def test_strumenti_page_lists_tool_links(client):
    response = client.get("/strumenti")
    assert response.status_code == 200
    assert 'href="/categories"' in response.text
    assert 'href="/locations"' in response.text
    assert 'href="/export"' in response.text
    assert 'href="/instagram-cookies"' in response.text
    assert 'href="/strumenti/audit"' in response.text


def test_audit_page_renders(client):
    response = client.get("/strumenti/audit")
    assert response.status_code == 200
    assert 'hx-get="/ui/audit/scan"' in response.text
```

```python
# tests/test_locations_page.py — replace test_nav_includes_locations_link with:
def test_nav_includes_strumenti_link(client):
    response = client.get("/")
    assert 'href="/strumenti"' in response.text
    assert "Strumenti" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_audit.py tests/test_locations_page.py -v`
Expected: FAIL — `tests/test_audit.py` fails on 404s (routes don't exist); `test_nav_includes_strumenti_link` fails because the nav doesn't have the link yet (and the old `test_nav_includes_locations_link` you just replaced no longer exists to fail).

- [ ] **Step 3: Write `app/routers/audit.py`**

```python
from dataclasses import dataclass
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.db import get_session
from app.location_matching import resolve_place
from app.models import Location
from app.routers.locations import _merge_locations, _reel_counts
from app.web import templates

ui_router = APIRouter(prefix="/ui/audit", tags=["audit-ui"])


@dataclass
class AuditPair:
    a: Location
    b: Location
    a_count: int
    b_count: int
    distance_m: Optional[float] = None


def _find_anomalies(session: Session) -> dict:
    locations = session.exec(select(Location)).all()
    reel_counts = _reel_counts(session)
    by_id = {loc.id: loc for loc in locations}

    certain_keys: set = set()
    certain_pairs: list[AuditPair] = []
    for loc in locations:
        resolution = resolve_place(session, loc.name, None, loc.lat, loc.lon, exclude_location_id=loc.id)
        if resolution.place_tier == "auto":
            key = frozenset((loc.id, resolution.place_location_id))
            if key not in certain_keys:
                certain_keys.add(key)
                other = by_id[resolution.place_location_id]
                certain_pairs.append(AuditPair(
                    a=loc, b=other,
                    a_count=reel_counts.get(loc.id, 0), b_count=reel_counts.get(other.id, 0),
                ))

    # Second pass, after every `auto` pair is known, so a pair already
    # classified as certain from one location's scan never also shows up
    # here just because the other location's scan only found it as a
    # candidate (resolve_place's tiers are directional).
    review_keys: set = set()
    review_pairs: list[AuditPair] = []
    for loc in locations:
        resolution = resolve_place(session, loc.name, None, loc.lat, loc.lon, exclude_location_id=loc.id)
        for candidate in resolution.place_candidates:
            key = frozenset((loc.id, candidate.id))
            if key in certain_keys or key in review_keys:
                continue
            review_keys.add(key)
            other = by_id[candidate.id]
            review_pairs.append(AuditPair(
                a=loc, b=other,
                a_count=reel_counts.get(loc.id, 0), b_count=reel_counts.get(other.id, 0),
                distance_m=candidate.distance_m,
            ))

    return {"certain_pairs": certain_pairs, "review_pairs": review_pairs, "error": None}


@ui_router.get("/scan")
def ui_audit_scan(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/audit_results.html", _find_anomalies(session))


@ui_router.post("/merge/{keep_id}/{drop_id}")
def ui_audit_merge(request: Request, keep_id: str, drop_id: str, session: Session = Depends(get_session)):
    try:
        _merge_locations(session, keep_id, drop_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        context = _find_anomalies(session)
        context["error"] = "Impossibile unire: la location da eliminare ha ancora città satellite collegate."
        return templates.TemplateResponse(request, "partials/audit_results.html", context)
    return templates.TemplateResponse(request, "partials/audit_results.html", _find_anomalies(session))
```

- [ ] **Step 4: Write the templates**

```html
<!-- app/templates/strumenti.html -->
{% extends "base.html" %}
{% block content %}
<ul class="tools-list">
    <li><a href="/categories">Gestisci categorie</a></li>
    <li><a href="/locations">Gestisci hub</a></li>
    <li><a href="/export">Esporta reel</a></li>
    <li><a href="/instagram-cookies">Cookie Instagram</a></li>
    <li><a href="/strumenti/audit">Audit pregresso</a></li>
</ul>
{% endblock %}
```

```html
<!-- app/templates/audit.html -->
{% extends "base.html" %}
{% block content %}
<button type="button" hx-get="/ui/audit/scan" hx-target="#audit-results" hx-swap="innerHTML" hx-indicator="#audit-scan-indicator">Esegui scansione</button>
<span id="audit-scan-indicator" class="htmx-indicator">Scansione in corso…</span>
<div id="audit-results"></div>
{% endblock %}
```

```html
<!-- app/templates/partials/audit_results.html -->
{% if error %}
<p class="audit-error">{{ error }}</p>
{% endif %}

<h2>Duplicati quasi certi</h2>
{% if certain_pairs %}
<ul class="audit-pair-list">
    {% for pair in certain_pairs %}
    <li>
        <span>{{ pair.a.name }} ({{ pair.a_count }} reel)</span>
        <button hx-post="/ui/audit/merge/{{ pair.a.id }}/{{ pair.b.id }}" hx-target="#audit-results" hx-swap="innerHTML"
                hx-confirm="Tenere '{{ pair.a.name }}' e spostare qui i reel di '{{ pair.b.name }}'? '{{ pair.b.name }}' verrà eliminata.">Tieni questa →</button>
        <span>{{ pair.b.name }} ({{ pair.b_count }} reel)</span>
        <button hx-post="/ui/audit/merge/{{ pair.b.id }}/{{ pair.a.id }}" hx-target="#audit-results" hx-swap="innerHTML"
                hx-confirm="Tenere '{{ pair.b.name }}' e spostare qui i reel di '{{ pair.a.name }}'? '{{ pair.a.name }}' verrà eliminata.">← Tieni questa</button>
    </li>
    {% endfor %}
</ul>
{% else %}
<p>Nessun duplicato quasi certo trovato.</p>
{% endif %}

<h2>Da verificare</h2>
{% if review_pairs %}
<ul class="audit-pair-list">
    {% for pair in review_pairs %}
    <li>
        <span>{{ pair.a.name }} ({{ pair.a_count }} reel)</span>
        <span class="distance">{{ pair.distance_m }}m</span>
        <span>{{ pair.b.name }} ({{ pair.b_count }} reel)</span>
        <button hx-post="/ui/audit/merge/{{ pair.a.id }}/{{ pair.b.id }}" hx-target="#audit-results" hx-swap="innerHTML"
                hx-confirm="Tenere '{{ pair.a.name }}' e spostare qui i reel di '{{ pair.b.name }}'? '{{ pair.b.name }}' verrà eliminata.">Tieni {{ pair.a.name }}</button>
        <button hx-post="/ui/audit/merge/{{ pair.b.id }}/{{ pair.a.id }}" hx-target="#audit-results" hx-swap="innerHTML"
                hx-confirm="Tenere '{{ pair.b.name }}' e spostare qui i reel di '{{ pair.a.name }}'? '{{ pair.a.name }}' verrà eliminata.">Tieni {{ pair.b.name }}</button>
    </li>
    {% endfor %}
</ul>
{% else %}
<p>Nessun caso da verificare.</p>
{% endif %}
```

- [ ] **Step 5: Update the nav in `app/templates/base.html`**

Replace the `<nav>` block (lines 23-31):

```html
        <nav>
            <a href="/">Home</a>
            <a href="/strumenti">Strumenti</a>
            <a href="/ask">Chiedi all'AI</a>
            <a href="/logout">Logout</a>
        </nav>
```

- [ ] **Step 6: Register the new pages and router in `app/main.py`**

Update the router import line to add `audit`:

```python
from app.routers import ai_ask, ai_categorize, ai_multi_categorize, audit, auth, categories, export, instagram_cookies, instagram_import, locations, map as map_router, reels
```

Add the include, next to the other `ui_router` includes:

```python
app.include_router(audit.ui_router)
```

Add the two page routes, next to the other simple page routes (e.g. after `instagram_cookies_page`):

```python
@app.get("/strumenti")
async def strumenti_page(request: Request):
    return templates.TemplateResponse(request, "strumenti.html", {})


@app.get("/strumenti/audit")
async def audit_page(request: Request):
    return templates.TemplateResponse(request, "audit.html", {})
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_audit.py tests/test_locations_page.py tests/test_index_page.py -v`
Expected: PASS (all tests — including `test_index_page.py`, to catch any assumption it might have about the old nav; if it does assert on one of the moved links, update it the same way `test_locations_page.py` was updated)

- [ ] **Step 8: Commit**

```bash
git add app/routers/audit.py app/templates/strumenti.html app/templates/audit.html app/templates/partials/audit_results.html app/templates/base.html app/main.py tests/test_audit.py tests/test_locations_page.py
git commit -m "feat: add location audit/merge tool under a new Strumenti nav section"
```

---

### Task 4: Full regression pass

**Files:** none new — verification only.

- [ ] **Step 1: Run the entire test suite**

Run: `uv run pytest`
Expected: all tests pass, zero errors/warnings.

- [ ] **Step 2: Grep for any remaining direct nav references to the moved links**

Run: `grep -rn 'href="/categories"\|href="/locations"\|href="/export"\|href="/instagram-cookies"' app/templates/base.html`
Expected: no output (`base.html`'s nav itself no longer links any of these directly — they only appear inside `strumenti.html` now).

- [ ] **Step 3: Manually smoke-test the merge action with the dev server**

Start the app locally, go to `/strumenti/audit`, run a scan against some real or seeded duplicate-looking data, and click through a merge end-to-end (including the `hx-confirm` dialog) to confirm it behaves as expected in a real browser — this is UI interaction the automated tests exercise at the HTTP level but not as an actual click-through. Flag to the user if this can't be run in this environment and ask them to verify it live instead.

- [ ] **Step 4: Final commit (only if Steps 1-3 required fixes)**

```bash
git add -A
git commit -m "chore: fix regressions found in final verification pass"
```

(Skip this step entirely if nothing needed fixing.)
