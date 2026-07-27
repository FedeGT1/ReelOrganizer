# Mobile-Responsive Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the home page so the default view is just map + reel list, with both "add a reel" methods (AI chat, manual form) moved into a single full-screen-on-mobile popup, and do a general responsive/touch-target pass across the app.

**Architecture:** A native `<dialog>` element holds two tabs (AI chat, manual form) behind a single "+ Aggiungi reel" trigger button. Both existing add-reel success paths (`POST /ui/reels`, `POST /ui/ai/confirm`) keep their current logic untouched but gain a third out-of-band swap (refreshing `#map-container`, alongside the `#reel-list` OOB swap `POST /ui/ai/confirm` already does) and an `HX-Trigger: reel-saved` response header. A few lines of vanilla JS (matching the existing minimal-JS approach used for the Leaflet map) open/close the dialog, switch tabs, and close the dialog when it sees that `reel-saved` event — no client-side re-fetching needed, since OOB swaps already refresh everything server-side.

**Tech Stack:** FastAPI, Jinja2, HTMX (existing `hx-swap-oob` pattern, `HX-Trigger` response header), native HTML `<dialog>` element, vanilla JS.

## Global Constraints

- Presentation-layer restructure only — no change to AI categorization logic, manual-add validation, or the map's filtering logic (hide-empty/type-filter), per `docs/superpowers/specs/2026-07-27-mobile-responsive-design.md`.
- No PWA/installability work (manifest, icons, service worker) — explicitly out of scope.
- `<dialog>` is used with no polyfill — assume a modern browser (Chrome/Firefox/Safari/Edge all support it), consistent with this being a personal app used on the user's own phone.
- `HX-Trigger: reel-saved` is the only signal used to close the popup; all content refresh (the originating tab's own reset, `#reel-list`, `#map-container`) happens via existing/extended `hx-swap-oob` server-rendered fragments, not client-side re-fetching.
- `DELETE /ui/reels/{reel_id}` is not touched by this plan — it already doesn't refresh the map after removing a location's last reel, and that stays as a known, separate, out-of-scope gap.
- The manual form no longer pre-selects whatever location is currently filtered in the reel list (a deliberate, confirmed simplification — the form is loaded independently of the reel list's filter state now).
- Dialog full-screen breakpoint: full-screen below `700px` viewport width, centered card (max-width 600px) at or above it.

---

### Task 1: Extract a reusable map-rendering helper

**Files:**
- Modify: `app/routers/map.py`

**Interfaces:**
- Produces: `render_map_html(session: Session, type_value: str | None = None) -> str` — renders `partials/map.html` to a plain string given a DB session and optional active type filter. Tasks 3 and 4 import this to build the map's out-of-band refresh fragment.

This is a pure refactor — `ui_map`'s externally-observable behavior (response body, status code) does not change. There's nothing new to assert; the existing map test suite is the verification.

- [ ] **Step 1: Extract the helper and make `ui_map` call it**

Replace the current `ui_map` function (and everything from `map_locations = []` through its `return`) with:

```python
def render_map_html(session: Session, type_value: str | None = None) -> str:
    locations = compute_map(session)
    hubs_by_id = {loc["id"]: loc for loc in locations if loc["is_hub"]}
    matching_location_ids = locations_with_type(session, type_value) if type_value else set()
    visible_ids, anchor_hub_ids = visible_location_ids(session, locations, type_value)

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
            "dimmed": bool(type_value) and loc["id"] not in matching_location_ids,
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
        active_type=type_value,
        taxonomy=get_taxonomy(session),
    )


@ui_router.get("/map")
def ui_map(
    request: Request,
    type: str = None,
    session: Session = Depends(get_session),
):
    return HTMLResponse(render_map_html(session, type))
```

Add `HTMLResponse` to the existing `fastapi` imports at the top of the file — change:
```python
from fastapi import APIRouter, Depends, Request
```
to:
```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
```

- [ ] **Step 2: Run the existing map tests to confirm identical behavior**

Run: `uv run pytest tests/test_map_api.py tests/test_ui_fragments.py -v -k map`
Expected: all PASS, unchanged from before this refactor.

- [ ] **Step 3: Commit**

```bash
git add app/routers/map.py
git commit -m "refactor: extract render_map_html for reuse outside the map router"
```

---

### Task 2: Split the manual add-reel form out of the reel list

**Files:**
- Create: `app/templates/partials/reel_add_form.html`
- Modify: `app/templates/partials/reel_list.html`
- Modify: `app/routers/reels.py`
- Test: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `get_taxonomy` (already imported in `reels.py`).
- Produces: `_reel_add_form_context(session: Session) -> dict` and `GET /ui/reels/add-form`, rendering `partials/reel_add_form.html`. Task 3 reuses `_reel_add_form_context` to re-render a fresh form after a successful create.

- [ ] **Step 1: Write the failing tests**

In `tests/test_ui_fragments.py`, replace `test_ui_reels_get_renders_list_and_form` with:

```python
def test_ui_reels_get_renders_list_without_form(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    session.add(Reel(link="https://instagram.com/reel/x", location_id=hub.id, note="Nice spot"))
    session.commit()

    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert "Nice spot" in response.text
    assert "<form" not in response.text


def test_ui_reels_add_form_renders_locations_and_categories(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/ui/reels/add-form")
    assert response.status_code == 200
    assert "<form" in response.text
    assert "Tokyo / Kanto" in response.text
    assert "Cibo" in response.text
```

Add the `Category` import at the top of `tests/test_ui_fragments.py` — change:
```python
from app.models import Location, Reel, ReelType
```
to:
```python
from app.models import Category, Location, Reel, ReelType
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ui_fragments.py -v -k "add_form or renders_list_without_form"`
Expected: `test_ui_reels_add_form_renders_locations_and_categories` FAILS with 404 (route doesn't exist yet); `test_ui_reels_get_renders_list_without_form` FAILS because `<form` is still present in `/ui/reels`.

- [ ] **Step 3: Create `app/templates/partials/reel_add_form.html`**

```html
<form hx-post="/ui/reels" hx-target="#reel-add-form-panel" hx-swap="innerHTML">
    <input type="url" name="link" placeholder="Link Instagram" required>
    <select name="location_id" required>
        {% for loc in locations %}
        <option value="{{ loc.id }}">{{ loc.name }}</option>
        {% endfor %}
    </select>
    <input type="text" name="note" placeholder="Nota (opzionale)">
    {% for key, info in taxonomy.items() %}
    <label class="type-option"><input type="checkbox" name="types" value="{{ key }}"> {{ info.icon }} {{ info.label }}</label>
    {% endfor %}
    <button type="submit">Aggiungi reel</button>
</form>
```

- [ ] **Step 4: Trim `app/templates/partials/reel_list.html`**

Replace the full contents of `app/templates/partials/reel_list.html` with:

```html
{% if filtered_location %}
<div class="reel-filter-banner">
    <strong>Reel — {{ filtered_location.name }}</strong>
    <a href="#" hx-get="/ui/reels" hx-target="#reel-list" hx-swap="innerHTML">✕ Mostra tutti</a>
</div>
{% endif %}
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

- [ ] **Step 5: Add `_reel_add_form_context` and the new route in `app/routers/reels.py`**

Add this function right after `_reel_list_context` (which stays as-is for now — Task 3 modifies it):

```python
def _reel_add_form_context(session: Session) -> dict:
    return {
        "locations": session.exec(select(Location)).all(),
        "taxonomy": get_taxonomy(session),
    }


@ui_router.get("/reels/add-form")
def ui_reel_add_form(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "partials/reel_add_form.html", _reel_add_form_context(session))
```

- [ ] **Step 6: Remove the now-unused `locations` key from `_reel_list_context`**

`reel_list.html` no longer references `locations` (only the form did, and it's gone from this template). In `_reel_list_context`, remove the `"locations": locations,` line and the `locations = session.exec(select(Location)).all()` line above it — the function becomes:

```python
def _reel_list_context(session: Session, location_id: Optional[str] = None) -> dict:
    query = select(Reel)
    if location_id is not None:
        query = query.where(Reel.location_id.in_(_location_and_satellite_ids(session, location_id)))
    reels = session.exec(query).all()
    filtered_location = session.get(Location, location_id) if location_id else None
    return {
        "reels": [_serialize_reel(session, r) for r in reels],
        "taxonomy": get_taxonomy(session),
        "filtered_location": filtered_location,
    }
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_ui_fragments.py -v`
Expected: all PASS, including the two new/renamed tests.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS — nothing else references the removed `locations` key or the old inline form.

- [ ] **Step 9: Commit**

```bash
git add app/templates/partials/reel_add_form.html app/templates/partials/reel_list.html app/routers/reels.py tests/test_ui_fragments.py
git commit -m "refactor: split the manual add-reel form out of the reel list"
```

---

### Task 3: Reset the form and refresh reel-list/map after a manual add

**Files:**
- Modify: `app/routers/reels.py`
- Test: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `render_map_html` (Task 1), `_reel_add_form_context` (Task 2).
- Produces: `POST /ui/reels` now responds with a freshly-rendered empty form (primary swap, resetting the dialog's manual tab) plus two out-of-band fragments (`#reel-list`, `#map-container`) plus an `HX-Trigger: reel-saved` response header.

- [ ] **Step 1: Write the failing test**

In `tests/test_ui_fragments.py`, replace `test_ui_reels_post_creates_and_returns_fragment` with:

```python
def test_ui_reels_post_resets_form_and_refreshes_list_and_map(client, session):
    hub = Location(name="Hub", is_hub=True, lat=35.0, lon=135.0)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.post(
        "/ui/reels",
        data={"link": "https://instagram.com/reel/new", "location_id": hub.id, "note": "New one", "types": ["food"]},
    )
    assert response.status_code == 200
    assert response.headers["hx-trigger"] == "reel-saved"
    assert '<div hx-swap-oob="innerHTML:#reel-list">' in response.text
    assert "New one" in response.text
    assert '<div hx-swap-oob="innerHTML:#map-container">' in response.text
    assert 'id="leaflet-map"' in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_fragments.py -v -k test_ui_reels_post_resets_form_and_refreshes_list_and_map`
Expected: FAIL — no `hx-trigger` header, no OOB blocks (current response is just the reel list).

- [ ] **Step 3: Modify `ui_create_reel` in `app/routers/reels.py`**

Replace the current `ui_create_reel` function body's `return` line — the function becomes:

```python
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

    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session)
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session)
    )
    map_html = render_map_html(session)

    response = HTMLResponse(
        form_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response
```

Add the two new imports needed at the top of `app/routers/reels.py` — change:
```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
```
to:
```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
```
and add, alongside the existing `from app.routers.categories import get_taxonomy, get_valid_type_keys` line:
```python
from app.routers.map import render_map_html
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ui_fragments.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/routers/reels.py tests/test_ui_fragments.py
git commit -m "feat: reset add-reel form and refresh list/map after a manual save"
```

---

### Task 4: Refresh the map after an AI-chat-confirmed add

**Files:**
- Modify: `app/routers/ai_categorize.py`
- Test: `tests/test_ai_ui.py`

**Interfaces:**
- Consumes: `render_map_html` (Task 1).
- Produces: `POST /ui/ai/confirm`'s existing response gains a third out-of-band fragment (`#map-container`) and the `HX-Trigger: reel-saved` header, alongside its existing `#reel-list` OOB swap and self-reset behavior (both untouched).

- [ ] **Step 1: Write the failing assertions**

In `tests/test_ai_ui.py`, in `test_ui_ai_confirm_resets_panel_and_updates_reel_list`, add two lines right after the existing `assert 'hx-swap-oob="innerHTML:#reel-list"' in response.text` line:

```python
    assert 'hx-swap-oob="innerHTML:#map-container">' in response.text
    assert response.headers["hx-trigger"] == "reel-saved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_ui.py -v -k test_ui_ai_confirm_resets_panel_and_updates_reel_list`
Expected: FAIL — no map OOB block, no `hx-trigger` header yet.

- [ ] **Step 3: Modify `ui_ai_confirm` in `app/routers/ai_categorize.py`**

Replace the final block of `ui_ai_confirm` (from `ai_chat_html = ...` to the end of the function) with:

```python
    ai_chat_html = templates.get_template("partials/ai_chat.html").render(
        _build_ai_chat_context(session, None, "")
    )
    reel_list_html = templates.get_template("partials/reel_list.html").render(
        _reel_list_context(session)
    )
    map_html = render_map_html(session)

    response = HTMLResponse(
        ai_chat_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response
```

Add the new import alongside the existing `from app.routers.reels import _is_safe_link, _reel_list_context` line:
```python
from app.routers.map import render_map_html
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_ui.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add app/routers/ai_categorize.py tests/test_ai_ui.py
git commit -m "feat: refresh the map after an AI-chat-confirmed reel save"
```

---

### Task 5: The "Aggiungi reel" dialog — markup and JS

**Files:**
- Create: `app/static/js/reel-dialog.js`
- Modify: `app/templates/index.html`
- Modify: `app/templates/base.html`
- Test: `tests/test_index_page.py`

**Interfaces:**
- Consumes: `#ai-chat-panel` (existing id, its internal forms already target it — must be preserved on whatever element wraps the AI tab's content), `/ui/ai/panel`, `/ui/reels/add-form` (Task 2), the `reel-saved` event (Tasks 3 & 4).
- Produces: `#add-reel-dialog`, `#open-add-reel`, `#close-add-reel`, `#reel-add-form-panel` — stable ids/hooks that Task 6's CSS styles.

- [ ] **Step 1: Write the failing tests**

In `tests/test_index_page.py`, add:

```python
def test_index_page_renders_add_reel_dialog(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="add-reel-dialog"' in response.text
    assert 'id="open-add-reel"' in response.text
    assert 'data-tab="ai"' in response.text
    assert 'data-tab="manual"' in response.text
    assert 'id="ai-chat-panel"' in response.text
    assert 'id="reel-add-form-panel"' in response.text


def test_index_page_loads_reel_dialog_script(client):
    response = client.get("/")
    assert '/static/js/reel-dialog.js' in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_index_page.py -v`
Expected: both new tests FAIL — the dialog markup and script tag don't exist yet.

- [ ] **Step 3: Replace `app/templates/index.html`**

```html
{% extends "base.html" %}
{% block content %}
<section id="map-container" hx-get="/ui/map" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento mappa...</p>
</section>

<button type="button" id="open-add-reel" class="btn-add-reel">+ Aggiungi reel</button>

<dialog id="add-reel-dialog">
    <div class="dialog-header">
        <div class="tabs">
            <button type="button" class="tab-btn active" data-tab="ai">🤖 Assistente AI</button>
            <button type="button" class="tab-btn" data-tab="manual">✏️ Manuale</button>
        </div>
        <button type="button" id="close-add-reel" aria-label="Chiudi">✕</button>
    </div>
    <div class="tab-panel" data-panel="ai" id="ai-chat-panel" hx-get="/ui/ai/panel" hx-trigger="load" hx-swap="innerHTML">
        <p>Caricamento assistente AI...</p>
    </div>
    <div class="tab-panel" data-panel="manual" id="reel-add-form-panel" hidden hx-get="/ui/reels/add-form" hx-trigger="load" hx-swap="innerHTML">
        <p>Caricamento form...</p>
    </div>
</dialog>

<section id="reel-list" hx-get="/ui/reels" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento reel...</p>
</section>
{% endblock %}
```

- [ ] **Step 4: Create `app/static/js/reel-dialog.js`**

```javascript
document.addEventListener("DOMContentLoaded", () => {
    const dialog = document.getElementById("add-reel-dialog");
    if (!dialog) {
        return;
    }

    const openBtn = document.getElementById("open-add-reel");
    const closeBtn = document.getElementById("close-add-reel");
    const tabButtons = dialog.querySelectorAll(".tab-btn");
    const panels = dialog.querySelectorAll(".tab-panel");

    openBtn.addEventListener("click", () => dialog.showModal());
    closeBtn.addEventListener("click", () => dialog.close());

    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) {
            dialog.close();
        }
    });

    tabButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            const target = btn.dataset.tab;
            tabButtons.forEach((b) => b.classList.toggle("active", b === btn));
            panels.forEach((p) => {
                p.hidden = p.dataset.panel !== target;
            });
        });
    });

    document.body.addEventListener("reel-saved", () => {
        dialog.close();
    });
});
```

- [ ] **Step 5: Load the new script in `app/templates/base.html`**

Change:
```html
    <script src="https://unpkg.com/htmx.org@1.9.12"></script>
    <script src="/static/js/map.js"></script>
```
to:
```html
    <script src="https://unpkg.com/htmx.org@1.9.12"></script>
    <script src="/static/js/map.js"></script>
    <script src="/static/js/reel-dialog.js"></script>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_index_page.py -v`
Expected: all PASS.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 8: Manual browser verification**

Start the app (`uv run uvicorn app.main:app --reload`, with `AUTH_USERNAME`/`AUTH_PASSWORD`/`SESSION_SECRET_KEY` set), log in, and confirm in a real browser: the "+ Aggiungi reel" button opens the dialog; both tabs load their content; switching tabs works; the ✕ button and clicking outside the dialog's content both close it; Escape closes it. This step has no automated coverage (pure client-side interaction, consistent with the rest of the plan's testing strategy) — do not skip it.

- [ ] **Step 9: Commit**

```bash
git add app/templates/index.html app/templates/base.html app/static/js/reel-dialog.js tests/test_index_page.py
git commit -m "feat: move add-reel flows into a single dialog with AI/manual tabs"
```

---

### Task 6: Responsive styling pass

**Files:**
- Modify: `app/static/css/style.css`
- Modify: `app/templates/partials/category_list.html`

No new automated tests — this task is pure CSS plus two small class additions, verified by manual browser inspection (same limitation as Task 5).

- [ ] **Step 1: Add a class to the category add form for targeted stacking**

In `app/templates/partials/category_list.html`, change:
```html
<form hx-post="/ui/categories" hx-target="#category-list" hx-swap="innerHTML">
```
to:
```html
<form class="category-form" hx-post="/ui/categories" hx-target="#category-list" hx-swap="innerHTML">
```

- [ ] **Step 2: Append the dialog, touch-target, and layout styles to `app/static/css/style.css`**

Add at the end of the file:

```css
dialog#add-reel-dialog {
    border: none;
    padding: 1rem;
    width: 100vw;
    height: 100vh;
    max-width: 100vw;
    max-height: 100vh;
    margin: 0;
    background: var(--color-paper);
    color: var(--color-ink);
}

dialog#add-reel-dialog::backdrop {
    background: rgba(0, 0, 0, 0.5);
}

@media (min-width: 700px) {
    dialog#add-reel-dialog {
        width: 90vw;
        max-width: 600px;
        height: auto;
        max-height: 85vh;
        margin: auto;
        border-radius: 8px;
    }
}

.dialog-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
    gap: 0.5rem;
}

.tabs {
    display: flex;
    gap: 0.5rem;
}

.tab-btn {
    background: none;
    border: 1px solid var(--color-ink-medium);
    border-radius: 999px;
    padding: 0.4rem 0.8rem;
    min-height: 44px;
    cursor: pointer;
    color: var(--color-ink);
}

.tab-btn.active {
    background: var(--color-ink-medium);
    color: var(--color-paper);
}

.btn-add-reel {
    display: block;
    width: 100%;
    margin: 0.75rem 0;
    min-height: 48px;
}

.type-option {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    min-height: 44px;
    padding: 0.25rem 0.5rem;
    cursor: pointer;
}

.category-form {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    align-items: stretch;
    max-width: 320px;
}

.reel-list li a {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
```

- [ ] **Step 3: Bump shared touch-target sizes**

Change the existing `button, .reel-list button` rule from:
```css
button, .reel-list button {
    background: var(--color-hanko);
    color: var(--color-paper);
    border: none;
    border-radius: 4px;
    padding: 0.4rem 0.8rem;
    cursor: pointer;
}
```
to:
```css
button, .reel-list button {
    background: var(--color-hanko);
    color: var(--color-paper);
    border: none;
    border-radius: 4px;
    padding: 0.5rem 1rem;
    min-height: 44px;
    cursor: pointer;
}
```

Change the existing `.chip` rule from:
```css
.chip {
    display: inline-block;
    padding: 0.25rem 0.6rem;
    margin: 0.15rem;
    border: 1px solid var(--color-ink-medium);
    border-radius: 999px;
    font-size: 0.85rem;
    cursor: pointer;
}
```
to:
```css
.chip {
    display: inline-block;
    padding: 0.4rem 0.8rem;
    margin: 0.15rem;
    border: 1px solid var(--color-ink-medium);
    border-radius: 999px;
    font-size: 0.85rem;
    cursor: pointer;
}
```

- [ ] **Step 4: Run the full suite (sanity check — CSS-only change, no test should be affected)**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 5: Manual browser verification**

With the dev server running and the browser's device toolbar set to a phone-sized viewport (e.g. 375×667): confirm the dialog is full-screen, tabs and the ✕ button are comfortably tappable, the reel list's Elimina button and category list's Modifica/Elimina buttons are comfortably tappable, a long Instagram URL in the reel list truncates with an ellipsis instead of overflowing, and the "add category" form on `/categories` stacks its fields vertically. Then confirm the dialog looks like a centered card (not full-screen) at a desktop-sized viewport. No automated coverage for this step — do not skip it.

- [ ] **Step 6: Commit**

```bash
git add app/static/css/style.css app/templates/partials/category_list.html
git commit -m "style: responsive touch-target and layout pass"
```
