# Reel Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a saved reel's link, note, location, and categories be edited after creation, by reusing the existing add-reel popup dialog with a pre-filled edit form instead of introducing new UI chrome.

**Architecture:** A new `PUT /api/reels/{id}` mirrors the existing full-CRUD pattern already used for locations. A new `GET /ui/reels/{id}/edit-form` renders a pre-filled edit form into the same `#reel-add-form-panel` DOM node the add-form already lives in; a new `PUT /ui/reels/{id}` saves it, responding with the reset blank add-form (direct body) plus out-of-band `#reel-list`/`#map-container` refreshes and an `HX-Trigger: reel-saved` header — the exact response shape `ui_ai_confirm` already uses today. No changes to `app/static/js/reel-dialog.js`: opening the dialog on the "Manuale" tab for editing is done via a plain inline `onclick` alongside the existing `hx-get`, combining htmx-driven fetch with vanilla DOM calls exactly like this project's existing category-filter-chip pattern.

**Tech Stack:** FastAPI + Jinja2/HTMX (existing), pytest with the existing `client`/`session` fixtures.

## Global Constraints

- The PUT payload shape (API and UI form fields) matches the existing `ReelCreate` model exactly: `link`, `location_id`, `note` (optional), `types` (list, filtered against the current valid taxonomy keys — invalid keys are silently dropped, exactly like `POST /ui/reels` and `POST /api/reels` already do).
- Editing a reel that replaces its categories must **replace**, not merge: delete all existing `ReelType` rows for that reel before inserting the newly-submitted ones.
- The UI update route (`ui_update_reel`) does **not** catch its own `HTTPException`s to render an inline error (unlike `ai_categorize.py`'s routes) — 404/400 propagate directly as plain error responses, matching how `ui_create_reel`/`ui_delete_reel` already behave today.
- New CSS for the edit button (`.reel-list .btn-edit`) mirrors the existing `.reel-list .btn-delete` rule exactly, but uses `--color-ink-medium` instead of `--color-hanko` — do not invent a new visual style.
- No changes to `app/static/js/reel-dialog.js`. The "Modifica" button and the edit form's "Annulla" button use only inline `onclick` handlers (`dialog.showModal()`/`.close()` and forcing the "Manuale" tab via the existing tab button's own `.click()`), combined with `hx-get`/`hx-put` attributes on the same elements — exactly the pattern already used by the category filter chips in `app/templates/partials/map.html`.

---

### Task 1: Add `PUT /api/reels/{id}` and the shared `_update_reel` helper

**Files:**
- Modify: `app/routers/reels.py`
- Test: `tests/test_reels_api.py`

**Interfaces:**
- Produces: `_update_reel(session, reel_id, link, location_id, note, types) -> Reel` — raises `HTTPException(404)` if the reel doesn't exist, `HTTPException(400)` if the link is unsafe; otherwise updates the reel's fields, replaces its `ReelType` rows, and returns the updated `Reel`. `PUT /api/reels/{reel_id}` (accepts the existing `ReelCreate` model as its JSON body) returns the same serialized shape `POST /api/reels` already returns.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_reels_api.py` (after the existing `test_create_reel_rejects_javascript_link` test):

```python
def test_update_reel_changes_fields(client, session):
    hub = Location(name="Hub", is_hub=True)
    other_hub = Location(name="Other Hub", is_hub=True)
    session.add(hub)
    session.add(other_hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.add(Category(key="culture", label="Cultura", icon="⛩️", color="#8FA8B2"))
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    create_resp = client.post(
        "/api/reels",
        json={
            "link": "https://instagram.com/reel/old",
            "location_id": hub.id,
            "note": "Old note",
            "types": ["food"],
        },
    )
    reel_id = create_resp.json()["id"]

    response = client.put(
        f"/api/reels/{reel_id}",
        json={
            "link": "https://instagram.com/reel/new",
            "location_id": other_hub.id,
            "note": "New note",
            "types": ["culture"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["link"] == "https://instagram.com/reel/new"
    assert data["location_id"] == other_hub.id
    assert data["note"] == "New note"
    assert data["types"] == ["culture"]

    # The old "food" ReelType row must actually be gone, not just superseded.
    remaining_types = session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all()
    assert [t.type for t in remaining_types] == ["culture"]


def test_update_missing_reel_returns_404(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    response = client.put(
        "/api/reels/does-not-exist",
        json={"link": "https://instagram.com/reel/x", "location_id": hub.id},
    )
    assert response.status_code == 404


def test_update_reel_rejects_javascript_link(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    create_resp = client.post(
        "/api/reels",
        json={"link": "https://instagram.com/reel/keep", "location_id": hub.id, "types": ["food"]},
    )
    reel_id = create_resp.json()["id"]

    response = client.put(
        f"/api/reels/{reel_id}",
        json={"link": "javascript:alert(1)", "location_id": hub.id},
    )
    assert response.status_code == 400
    assert client.get("/api/reels").json()[0]["link"] == "https://instagram.com/reel/keep"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reels_api.py -v`
Expected: FAIL — `test_update_reel_changes_fields`, `test_update_missing_reel_returns_404`, and `test_update_reel_rejects_javascript_link` all fail with a 405 Method Not Allowed (no `PUT /api/reels/{id}` route exists yet).

- [ ] **Step 3: Implement `_update_reel` and the PUT route**

In `app/routers/reels.py`, add this function right after `_serialize_reel` (before `list_reels`):

```python
def _update_reel(
    session: Session, reel_id: str, link: str, location_id: str, note: Optional[str], types: list[str]
) -> Reel:
    reel = session.get(Reel, reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    reel.link = link
    reel.location_id = location_id
    reel.note = note
    session.add(reel)

    for t in session.exec(select(ReelType).where(ReelType.reel_id == reel_id)).all():
        session.delete(t)
    session.commit()

    valid_type_keys = get_valid_type_keys(session)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel_id, type=type_value))
    session.commit()
    session.refresh(reel)
    return reel
```

Add this route right after `create_reel`:

```python
@router.put("/{reel_id}")
def update_reel(reel_id: str, payload: ReelCreate, session: Session = Depends(get_session)):
    reel = _update_reel(session, reel_id, payload.link, payload.location_id, payload.note, payload.types)
    return _serialize_reel(session, reel)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reels_api.py -v`
Expected: All tests PASS, including every pre-existing test in the file (no regressions).

- [ ] **Step 5: Commit**

```bash
git add app/routers/reels.py tests/test_reels_api.py
git commit -m "feat: add PUT /api/reels/{id} to support editing reels"
```

---

### Task 2: Add the edit-form UI route, the pre-filled template, and the "Modifica" button

**Files:**
- Create: `app/templates/partials/reel_edit_form.html`
- Modify: `app/routers/reels.py`
- Modify: `app/templates/partials/reel_list.html`
- Modify: `app/static/css/style.css`
- Test: `tests/test_ui_fragments.py`

**Interfaces:**
- Consumes: `_update_reel` from Task 1 (already implemented; the UI route calls it with form-decoded values instead of a parsed JSON payload).
- Produces: `GET /ui/reels/{reel_id}/edit-form` (404 if missing) and `PUT /ui/reels/{reel_id}` (same response shape as `ui_create_reel`: reset add-form as the direct body, OOB `#reel-list` and `#map-container` fragments, `HX-Trigger: reel-saved` header). `reel_list.html`'s `<li>` gains a "Modifica" button before the existing delete button.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_fragments.py` (anywhere after the existing reel-related tests, e.g. after `test_ui_reels_delete_returns_updated_fragment`):

```python
def test_ui_reels_edit_form_renders_prefilled_data(client, session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/x", location_id=hub.id, note="Nice spot")
    session.add(reel)
    session.commit()
    session.refresh(reel)
    session.add(ReelType(reel_id=reel.id, type="food"))
    session.commit()

    response = client.get(f"/ui/reels/{reel.id}/edit-form")
    assert response.status_code == 200
    assert 'value="https://instagram.com/reel/x"' in response.text
    assert 'value="Nice spot"' in response.text
    assert f'value="{hub.id}" selected' in response.text
    assert 'value="food" checked' in response.text


def test_ui_reels_edit_form_missing_reel_returns_404(client):
    response = client.get("/ui/reels/does-not-exist/edit-form")
    assert response.status_code == 404


def test_ui_reels_put_resets_form_and_refreshes_list_and_map(client, session):
    hub = Location(name="Hub", is_hub=True, lat=35.0, lon=135.0)
    other_hub = Location(name="Other Hub", is_hub=True, lat=36.0, lon=136.0)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)
    reel = Reel(link="https://instagram.com/reel/old", location_id=hub.id, note="Old note")
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.put(
        f"/ui/reels/{reel.id}",
        data={"link": "https://instagram.com/reel/new", "location_id": other_hub.id, "note": "New note"},
    )
    assert response.status_code == 200
    assert response.headers["hx-trigger"] == "reel-saved"
    assert '<div hx-swap-oob="innerHTML:#reel-list">' in response.text
    assert "New note" in response.text
    assert '<div hx-swap-oob="innerHTML:#map-container">' in response.text
    assert 'id="leaflet-map"' in response.text


def test_ui_reels_put_rejects_javascript_link(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/keep", location_id=hub.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.put(
        f"/ui/reels/{reel.id}",
        data={"link": "javascript:alert(1)", "location_id": hub.id},
    )
    assert response.status_code == 400


def test_ui_reels_list_includes_edit_button(client, session):
    hub = Location(name="Hub", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    reel = Reel(link="https://instagram.com/reel/x", location_id=hub.id)
    session.add(reel)
    session.commit()
    session.refresh(reel)

    response = client.get("/ui/reels")
    assert response.status_code == 200
    assert f"/ui/reels/{reel.id}/edit-form" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_fragments.py -v`
Expected: `test_ui_reels_edit_form_renders_prefilled_data` and `test_ui_reels_edit_form_missing_reel_returns_404` FAIL with 404 (no route exists yet). `test_ui_reels_put_resets_form_and_refreshes_list_and_map` and `test_ui_reels_put_rejects_javascript_link` FAIL with 405 (no `PUT /ui/reels/{id}` route yet). `test_ui_reels_list_includes_edit_button` FAILs (no edit link in the rendered list yet).

- [ ] **Step 3: Create the edit-form template**

Create `app/templates/partials/reel_edit_form.html`:

```html
<form class="reel-add-form" hx-put="/ui/reels/{{ reel.id }}" hx-target="#reel-add-form-panel" hx-swap="innerHTML">
    <input type="url" name="link" value="{{ reel.link }}" placeholder="Link Instagram" required>
    <select name="location_id" required>
        {% for loc in locations %}
        <option value="{{ loc.id }}" {% if loc.id == reel.location_id %}selected{% endif %}>{{ loc.name }}</option>
        {% endfor %}
    </select>
    <input type="text" name="note" value="{{ reel.note or '' }}" placeholder="Nota (opzionale)">
    <div class="type-options">
        {% for key, info in taxonomy.items() %}
        <label class="type-option"><input type="checkbox" name="types" value="{{ key }}" {% if key in reel_type_keys %}checked{% endif %}> {{ info.icon }} {{ info.label }}</label>
        {% endfor %}
    </div>
    <button type="submit">Salva</button>
    <button type="button" hx-get="/ui/reels/add-form" hx-target="#reel-add-form-panel" hx-swap="innerHTML"
            onclick="document.getElementById('add-reel-dialog').close()">Annulla</button>
</form>
```

- [ ] **Step 4: Add the context helper and both routes**

In `app/routers/reels.py`, add this function right after `_reel_add_form_context`:

```python
def _reel_edit_form_context(session: Session, reel: Reel) -> dict:
    types = session.exec(select(ReelType).where(ReelType.reel_id == reel.id)).all()
    return {
        "reel": reel,
        "locations": session.exec(select(Location)).all(),
        "taxonomy": get_taxonomy(session),
        "reel_type_keys": {t.type for t in types},
    }
```

Add these two routes right after `ui_reel_add_form`:

```python
@ui_router.get("/reels/{reel_id}/edit-form")
def ui_reel_edit_form(request: Request, reel_id: str, session: Session = Depends(get_session)):
    reel = session.get(Reel, reel_id)
    if reel is None:
        raise HTTPException(status_code=404, detail="Reel not found")
    return templates.TemplateResponse(
        request, "partials/reel_edit_form.html", _reel_edit_form_context(session, reel)
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
):
    _update_reel(session, reel_id, link, location_id, note, types)

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

- [ ] **Step 5: Add the "Modifica" button to the reel list**

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
        <div class="reel-info">
            <a href="{{ reel.link }}" target="_blank" rel="noopener noreferrer">{{ reel.link }}</a>
            <div class="reel-meta">
                {% if reel.note %}<span class="note">{{ reel.note }}</span>{% endif %}
                <span class="types">{% for t in reel.types %}{{ taxonomy[t].icon }}{% endfor %}</span>
            </div>
        </div>
        <button class="btn-edit" hx-get="/ui/reels/{{ reel.id }}/edit-form" hx-target="#reel-add-form-panel" hx-swap="innerHTML"
                onclick="document.getElementById('add-reel-dialog').showModal(); document.querySelector('.tab-btn[data-tab=manual]').click();"
                aria-label="Modifica">✏️</button>
        <button class="btn-delete" hx-delete="/ui/reels/{{ reel.id }}" hx-target="#reel-list" hx-swap="innerHTML" aria-label="Elimina">🗑</button>
    </li>
    {% endfor %}
</ul>
```

- [ ] **Step 6: Add the edit-button CSS**

In `app/static/css/style.css`, right after the existing `.reel-list .btn-delete:hover { ... }` rule, add:

```css
.reel-list .btn-edit {
    flex-shrink: 0;
    background: transparent;
    color: var(--color-ink-medium);
    border: 1px solid var(--color-ink-medium);
    border-radius: 999px;
    min-height: 40px;
    min-width: 40px;
    padding: 0;
    font-size: 1rem;
}

.reel-list .btn-edit:hover {
    background: var(--color-ink-medium);
    color: var(--color-paper);
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_ui_fragments.py -v`
Expected: All tests PASS, including every pre-existing test in the file (no regressions).

- [ ] **Step 8: Run the full test suite**

Run: `pytest`
Expected: All tests PASS (no regressions anywhere in the project).

- [ ] **Step 9: Commit**

```bash
git add app/templates/partials/reel_edit_form.html app/routers/reels.py app/templates/partials/reel_list.html app/static/css/style.css tests/test_ui_fragments.py
git commit -m "feat: add reel editing via the add-reel popup (edit-form route, Modifica button)"
```
