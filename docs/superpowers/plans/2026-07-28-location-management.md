# Location Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user add, edit, and delete locations (hubs and satellites) from a new "Gestisci città" page, the same way categories are already managed.

**Architecture:** `app/routers/locations.py` gains shared private helper functions (`_create_location`, `_update_location`, `_delete_location`, mirroring `categories.py`'s `_create_category`/`_update_category`/`_delete_category` pattern exactly) consumed by both the existing JSON API and a new HTMX UI router. A new `/locations` page, structurally identical to `/categories`, hosts the list + inline edit/delete + add form.

**Tech Stack:** FastAPI, SQLModel, Jinja2, HTMX — no new dependencies.

## Global Constraints

- No change to how the manual add-reel form or AI chat flow select locations — they keep reading `Location` rows the same way they already do.
- No map-based coordinate picker — plain numeric `lat`/`lon` inputs, per the existing "the map is schematic" design decision.
- A location with child locations cannot be turned into a satellite (same integrity rule the existing delete endpoint already enforces) — reject with a 409, both from the JSON API and, as a visible inline error (not a silently-failed request), from the UI.
- When `is_hub` is true, `parent_id` is ignored and forced to `None` server-side regardless of what's submitted.
- No JavaScript is added to show/hide the parent-hub dropdown based on the hub/satellite radio choice — both are always visible; the backend ignores `parent_id` when `is_hub` is true.
- HTTPException `detail` strings stay in English (matching this codebase's existing convention for every other router) — but the UI routes must show italian-language error text to the user, translating the specific 400/409 cases rather than displaying `exc.detail` verbatim.

---

### Task 1: Backend — shared helpers + update endpoint

**Files:**
- Modify: `app/routers/locations.py`
- Modify: `tests/test_locations_api.py`

**Interfaces:**
- Produces: `_has_children(session, location_id) -> bool`, `_reel_counts(session) -> dict`, `_serialize_location(location, reel_count) -> dict`, `_create_location(session, name, is_hub, parent_id, lat, lon) -> Location`, `_update_location(session, location_id, name, is_hub, parent_id, lat, lon) -> Location`, `_delete_location(session, location_id) -> None` — all raising `HTTPException` on validation failure. Task 2's UI routes import and call these directly.
- `PUT /api/locations/{location_id}` — new endpoint, same request/response shape as `POST /api/locations`.

This task rewrites `create_location`/`delete_location` to call the new shared helpers instead of inlining their logic — their external request/response behavior is unchanged (verified by the existing, un-modified tests in `test_locations_api.py` continuing to pass).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_locations_api.py`:

```python
def test_update_location_changes_fields(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Old Name", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]

    response = client.put(
        f"/api/locations/{hub_id}",
        json={"name": "New Name", "is_hub": True, "lat": 36.0, "lon": 136.0},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["lat"] == 36.0
    assert data["lon"] == 136.0


def test_update_missing_location_returns_404(client):
    response = client.put(
        "/api/locations/does-not-exist",
        json={"name": "X", "is_hub": True, "lat": 0.0, "lon": 0.0},
    )
    assert response.status_code == 404


def test_update_satellite_without_parent_id_returns_400(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Hub", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]

    response = client.put(
        f"/api/locations/{hub_id}",
        json={"name": "Hub", "is_hub": False, "lat": 35.0, "lon": 135.0},
    )
    assert response.status_code == 400


def test_update_hub_with_children_to_satellite_returns_409(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Parent Hub", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]
    other_hub_resp = client.post(
        "/api/locations", json={"name": "Other Hub", "is_hub": True, "lat": 30.0, "lon": 130.0}
    )
    other_hub_id = other_hub_resp.json()["id"]
    client.post(
        "/api/locations",
        json={"name": "Satellite Kid", "is_hub": False, "parent_id": hub_id, "lat": 35.1, "lon": 135.1},
    )

    response = client.put(
        f"/api/locations/{hub_id}",
        json={"name": "Parent Hub", "is_hub": False, "parent_id": other_hub_id, "lat": 35.0, "lon": 135.0},
    )
    assert response.status_code == 409


def test_update_hub_ignores_submitted_parent_id(client):
    hub_resp = client.post(
        "/api/locations", json={"name": "Hub A", "is_hub": True, "lat": 35.0, "lon": 135.0}
    )
    hub_id = hub_resp.json()["id"]
    other_hub_resp = client.post(
        "/api/locations", json={"name": "Hub B", "is_hub": True, "lat": 30.0, "lon": 130.0}
    )
    other_hub_id = other_hub_resp.json()["id"]

    response = client.put(
        f"/api/locations/{hub_id}",
        json={"name": "Hub A", "is_hub": True, "parent_id": other_hub_id, "lat": 35.0, "lon": 135.0},
    )
    assert response.status_code == 200
    assert response.json()["parent_id"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_locations_api.py -v`
Expected: the 5 new tests FAIL (404 — no `PUT` route exists yet); all pre-existing tests in this file still PASS.

- [ ] **Step 3: Replace the full contents of `app/routers/locations.py`**

```python
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models import Location, Reel, ReelType

router = APIRouter(prefix="/api/locations", tags=["locations"])


class LocationPayload(BaseModel):
    name: str
    is_hub: bool = True
    parent_id: Optional[str] = None
    lat: float
    lon: float


def _has_children(session: Session, location_id: str) -> bool:
    return (
        session.exec(select(Location).where(Location.parent_id == location_id)).first()
        is not None
    )


def _reel_counts(session: Session) -> dict:
    return dict(
        session.exec(
            select(Reel.location_id, func.count(Reel.id)).group_by(Reel.location_id)
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
    session: Session, name: str, is_hub: bool, parent_id: Optional[str], lat: float, lon: float
) -> Location:
    if not is_hub and not parent_id:
        raise HTTPException(status_code=400, detail="A satellite location requires a parent_id")
    location = Location(
        name=name, is_hub=is_hub, parent_id=None if is_hub else parent_id, lat=lat, lon=lon
    )
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


def _update_location(
    session: Session,
    location_id: str,
    name: str,
    is_hub: bool,
    parent_id: Optional[str],
    lat: float,
    lon: float,
) -> Location:
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if not is_hub and not parent_id:
        raise HTTPException(status_code=400, detail="A satellite location requires a parent_id")
    if not is_hub and _has_children(session, location_id):
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


def _delete_location(session: Session, location_id: str) -> None:
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    if _has_children(session, location_id):
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a location that still has child locations; reassign or delete them first",
        )
    reels = session.exec(select(Reel).where(Reel.location_id == location_id)).all()
    for reel in reels:
        types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
        for t in types:
            session.delete(t)
        session.delete(reel)
    session.delete(location)
    session.commit()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_location(payload: LocationPayload, session: Session = Depends(get_session)):
    location = _create_location(
        session, payload.name, payload.is_hub, payload.parent_id, payload.lat, payload.lon
    )
    return _serialize_location(location, 0)


@router.get("")
def list_locations(session: Session = Depends(get_session)):
    locations = session.exec(select(Location)).all()
    counts = _reel_counts(session)
    return [_serialize_location(loc, counts.get(loc.id, 0)) for loc in locations]


@router.put("/{location_id}")
def update_location(
    location_id: str, payload: LocationPayload, session: Session = Depends(get_session)
):
    location = _update_location(
        session,
        location_id,
        payload.name,
        payload.is_hub,
        payload.parent_id,
        payload.lat,
        payload.lon,
    )
    counts = _reel_counts(session)
    return _serialize_location(location, counts.get(location.id, 0))


@router.delete("/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: str, session: Session = Depends(get_session)):
    _delete_location(session, location_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_locations_api.py -v`
Expected: all PASS — the 5 new tests, and all pre-existing ones (`test_delete_location_cascades_reels`, `test_delete_missing_location_returns_404`, `test_list_locations_includes_reel_counts`, `test_list_locations_empty`, `test_create_hub_location`, `test_create_location_without_lat_lon_returns_422`, `test_create_satellite_location`, `test_create_satellite_location_without_parent_id_returns_400`, `test_delete_location_with_children_returns_409`), unchanged in behavior despite the internal rewrite.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/routers/locations.py tests/test_locations_api.py
git commit -m "refactor: extract shared location helpers and add PUT /api/locations/{id}"
```

---

### Task 2: UI routes + templates

**Files:**
- Modify: `app/routers/locations.py`
- Create: `app/templates/partials/location_list.html`
- Create: `app/templates/partials/location_edit_row.html`
- Modify: `app/static/css/style.css`
- Create: `tests/test_locations_ui.py`

**Interfaces:**
- Consumes: `_create_location`, `_update_location`, `_delete_location`, `_has_children` (Task 1).
- Produces: `locations.ui_router` (`APIRouter(prefix="/ui/locations", ...)`) with `GET`/`POST` (list/create), `GET /{id}/edit`, `POST /{id}` (update), `DELETE /{id}`. Task 3 registers this router and points a new page at it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_locations_ui.py`:

```python
from app.models import Location


def test_ui_locations_list_renders_existing_locations(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()

    response = client.get("/ui/locations")
    assert response.status_code == 200
    assert "Tokyo / Kanto" in response.text
    assert "<form" in response.text


def test_ui_locations_list_shows_satellite_parent_name(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    satellite = Location(name="Kamakura", is_hub=False, parent_id=hub.id, lat=35.3, lon=139.5)
    session.add(satellite)
    session.commit()

    response = client.get("/ui/locations")
    assert response.status_code == 200
    assert "Kamakura" in response.text
    assert "Tokyo / Kanto" in response.text


def test_ui_locations_create_hub_and_rerenders_list(client):
    response = client.post(
        "/ui/locations",
        data={"name": "New Hub", "is_hub": "true", "lat": "10.0", "lon": "20.0"},
    )
    assert response.status_code == 200
    assert "New Hub" in response.text


def test_ui_locations_create_satellite_without_parent_shows_inline_error(client):
    response = client.post(
        "/ui/locations",
        data={"name": "Orphan", "is_hub": "false", "lat": "10.0", "lon": "20.0"},
    )
    assert response.status_code == 200
    assert "richiede" in response.text.lower()


def test_ui_locations_edit_form_renders_prefilled_row(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.get(f"/ui/locations/{hub.id}/edit")
    assert response.status_code == 200
    assert 'value="Tokyo / Kanto"' in response.text


def test_ui_locations_edit_form_unknown_id_returns_404(client):
    response = client.get("/ui/locations/does-not-exist/edit")
    assert response.status_code == 404


def test_ui_locations_update_and_rerenders_list(client, session):
    hub = Location(name="Old Name", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        f"/ui/locations/{hub.id}",
        data={"name": "New Name", "is_hub": "true", "lat": "36.0", "lon": "136.0"},
    )
    assert response.status_code == 200
    assert "New Name" in response.text


def test_ui_locations_delete_removes_it_and_rerenders_list(client, session):
    hub = Location(name="Doomed", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.delete(f"/ui/locations/{hub.id}")
    assert response.status_code == 200
    assert "Doomed" not in response.text


def test_ui_locations_delete_with_children_shows_inline_error(client, session):
    hub = Location(name="Parent Hub", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    satellite = Location(name="Child Satellite", is_hub=False, parent_id=hub.id, lat=35.1, lon=135.1)
    session.add(satellite)
    session.commit()

    response = client.delete(f"/ui/locations/{hub.id}")
    assert response.status_code == 200
    assert "Parent Hub" in response.text
    assert "riassegn" in response.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_locations_ui.py -v`
Expected: all FAIL (404s — no `/ui/locations` routes exist yet).

- [ ] **Step 3: Create `app/templates/partials/location_list.html`**

```html
{% if error %}
<p class="ai-notice">{{ error }}</p>
{% endif %}
<ul class="location-list">
    {% for loc in locations %}
    <li id="location-{{ loc.id }}">
        <span class="chip">{{ loc.name }}{% if loc.parent_name %} · satellite di {{ loc.parent_name }}{% else %} · hub{% endif %}</span>
        <button hx-get="/ui/locations/{{ loc.id }}/edit" hx-target="#location-{{ loc.id }}" hx-swap="outerHTML">Modifica</button>
        <button hx-delete="/ui/locations/{{ loc.id }}" hx-target="#location-list" hx-swap="innerHTML">Elimina</button>
    </li>
    {% endfor %}
</ul>
<form class="location-form" hx-post="/ui/locations" hx-target="#location-list" hx-swap="innerHTML">
    <input type="text" name="name" placeholder="Nome città" required>
    <label><input type="radio" name="is_hub" value="true" checked> È un hub</label>
    <label>
        <input type="radio" name="is_hub" value="false"> È un satellite di:
        <select name="parent_id">
            {% for hub in hubs %}
            <option value="{{ hub.id }}">{{ hub.name }}</option>
            {% endfor %}
        </select>
    </label>
    <input type="number" step="any" name="lat" placeholder="Latitudine" required>
    <input type="number" step="any" name="lon" placeholder="Longitudine" required>
    <button type="submit">Aggiungi città</button>
</form>
```

- [ ] **Step 4: Create `app/templates/partials/location_edit_row.html`**

```html
<li id="location-{{ location.id }}">
    <form hx-post="/ui/locations/{{ location.id }}" hx-target="#location-list" hx-swap="innerHTML">
        <input type="text" name="name" value="{{ location.name }}" required>
        <label><input type="radio" name="is_hub" value="true" {{ 'checked' if location.is_hub else '' }}> È un hub</label>
        <label>
            <input type="radio" name="is_hub" value="false" {{ 'checked' if not location.is_hub else '' }}> È un satellite di:
            <select name="parent_id">
                {% for hub in hubs %}
                <option value="{{ hub.id }}" {{ 'selected' if hub.id == location.parent_id else '' }}>{{ hub.name }}</option>
                {% endfor %}
            </select>
        </label>
        <input type="number" step="any" name="lat" value="{{ location.lat }}" required>
        <input type="number" step="any" name="lon" value="{{ location.lon }}" required>
        <button type="submit">Salva</button>
        <button type="button" hx-get="/ui/locations" hx-target="#location-list" hx-swap="innerHTML">Annulla</button>
    </form>
</li>
```

- [ ] **Step 5: Share the category-list/category-form styling with the new location classes**

In `app/static/css/style.css`, extend the four existing category-list selectors and the one category-form selector to also match the new location classes — change:

```css
.category-list {
```
to:
```css
.category-list, .location-list {
```

Change:
```css
.category-list li {
```
to:
```css
.category-list li, .location-list li {
```

Change:
```css
.category-list button {
```
to:
```css
.category-list button, .location-list button {
```

Change:
```css
.category-list button:first-of-type {
```
to:
```css
.category-list button:first-of-type, .location-list button:first-of-type {
```

Change:
```css
.category-form {
```
to:
```css
.category-form, .location-form {
```

- [ ] **Step 6: Add the UI router and its routes to `app/routers/locations.py`**

Add these imports — change:
```python
from fastapi import APIRouter, Depends, HTTPException, status
```
to:
```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
```

and add, right after the existing `from app.models import Location, Reel, ReelType` line:
```python
from app.web import templates
```

Add the second router declaration right after the existing `router = APIRouter(prefix="/api/locations", tags=["locations"])` line:
```python
ui_router = APIRouter(prefix="/ui/locations", tags=["locations-ui"])
```

Add this context builder and the five UI routes at the end of the file:

```python
def _location_list_context(session: Session, error: Optional[str] = None) -> dict:
    locations = session.exec(select(Location)).all()
    counts = _reel_counts(session)
    hubs_by_id = {loc.id: loc for loc in locations if loc.is_hub}
    entries = [
        {
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
        for loc in locations
    ]
    return {
        "locations": entries,
        "hubs": [loc for loc in locations if loc.is_hub],
        "error": error,
    }


@ui_router.get("")
def ui_list_locations(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session)
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
):
    try:
        _create_location(session, name, is_hub == "true", parent_id or None, lat, lon)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "partials/location_list.html",
            _location_list_context(session, error="Un satellite richiede una città padre."),
        )
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session)
    )


@ui_router.get("/{location_id}/edit")
def ui_edit_location_form(
    request: Request, location_id: str, session: Session = Depends(get_session)
):
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Location not found")
    hubs = session.exec(
        select(Location).where(Location.is_hub == True, Location.id != location_id)
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
):
    try:
        _update_location(session, location_id, name, is_hub == "true", parent_id or None, lat, lon)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        error = (
            "Un satellite richiede una città padre."
            if exc.status_code == 400
            else "Questa città ha satelliti o reel collegati: riassegnali o eliminali prima."
        )
        return templates.TemplateResponse(
            request,
            "partials/location_list.html",
            _location_list_context(session, error=error),
        )
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session)
    )


@ui_router.delete("/{location_id}")
def ui_delete_location(
    request: Request, location_id: str, session: Session = Depends(get_session)
):
    try:
        _delete_location(session, location_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise
        return templates.TemplateResponse(
            request,
            "partials/location_list.html",
            _location_list_context(
                session, error="Questa città ha satelliti o reel collegati: riassegnali o eliminali prima."
            ),
        )
    return templates.TemplateResponse(
        request, "partials/location_list.html", _location_list_context(session)
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_locations_ui.py -v`
Expected: all PASS.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add app/routers/locations.py app/templates/partials/location_list.html \
  app/templates/partials/location_edit_row.html app/static/css/style.css tests/test_locations_ui.py
git commit -m "feat: add location management UI routes"
```

---

### Task 3: Page, nav link, and app wiring

**Files:**
- Create: `app/templates/locations.html`
- Modify: `app/templates/base.html`
- Modify: `app/main.py`
- Create: `tests/test_locations_page.py`

**Interfaces:**
- Consumes: `locations.ui_router` (Task 2).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_locations_page.py`:

```python
def test_locations_page_renders(client):
    response = client.get("/locations")
    assert response.status_code == 200
    assert 'id="location-list"' in response.text


def test_nav_includes_locations_link(client):
    response = client.get("/")
    assert 'href="/locations"' in response.text
    assert "Gestisci città" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_locations_page.py -v`
Expected: both FAIL (404 for the page; no nav link yet).

- [ ] **Step 3: Create `app/templates/locations.html`**

```html
{% extends "base.html" %}
{% block content %}
<section id="location-list" hx-get="/ui/locations" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento città...</p>
</section>
{% endblock %}
```

- [ ] **Step 4: Add the nav link in `app/templates/base.html`**

Change:
```html
        <nav>
            <a href="/">Home</a>
            <a href="/categories">Gestisci categorie</a>
            <a href="/logout">Logout</a>
        </nav>
```
to:
```html
        <nav>
            <a href="/">Home</a>
            <a href="/categories">Gestisci categorie</a>
            <a href="/locations">Gestisci città</a>
            <a href="/logout">Logout</a>
        </nav>
```

- [ ] **Step 5: Register the router and page route in `app/main.py`**

Add, right after the existing `app.include_router(categories.ui_router)` line:
```python
app.include_router(locations.ui_router)
```

Add, right after the existing `categories_page` route function:
```python
@app.get("/locations")
async def locations_page(request: Request):
    return templates.TemplateResponse(request, "locations.html", {})
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_locations_page.py -v`
Expected: both PASS.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 8: Manual browser verification**

Log in and confirm in a real browser: the "Gestisci città" nav button appears and opens `/locations`; the list shows seeded hubs/satellites with correct "hub"/"satellite di X" labeling; adding a hub and a satellite both work; editing a location's name/coordinates works; trying to turn a hub with a satellite into a satellite itself shows the inline Italian error message instead of silently failing; deleting a childless location works; deleting a hub with a satellite shows the inline error instead of silently failing.

- [ ] **Step 9: Commit**

```bash
git add app/templates/locations.html app/templates/base.html app/main.py tests/test_locations_page.py
git commit -m "feat: add the Gestisci città page and nav link"
```
