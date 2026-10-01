# Storico delle Conversazioni "Chiedi all'AI" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user reopen and continue a past `/ask` conversation from a "Conversazioni precedenti" list, and delete conversations they no longer need.

**Architecture:** Zero schema changes — reuses `AskSession`/`AskMessage` fields that already exist. A bugfix makes `AskSession.updated_at` actually advance on each turn (today it's frozen at creation time). Three new pure helper functions in `app/routers/ai_ask.py` build a per-session summary (truncated first message, scope label, formatted date) for every session, newest-first; `_build_ask_chat_context` always includes this list. `GET /ui/ask/panel` gains an optional `session_id` query param to reopen a session (restoring its own stored scope, ignoring any `location_id`/`category_key` in the query string). A new `DELETE /ui/ask/history/{session_id}` removes a session and its messages, resetting the panel only if the deleted session was the one currently open. The history list renders inside the same `ask_chat.html` response (no new htmx target, no out-of-band swap) via a Jinja `{% include %}`.

**Tech Stack:** FastAPI, SQLModel (SQLite), Jinja2, htmx 1.9.12 — no new dependencies.

## Global Constraints

- **Zero DB schema changes.** No new columns, no new tables. This plan only adds new queries over `AskSession`/`AskMessage` fields that already exist (`location_id`, `category_key`, `updated_at`, `content`, `role`). The user has stressed (twice, across two features) that the production SQLite DB on the self-hosted VPS must never lose existing data on a deploy; any future plan that *does* need a new column on an existing table must call that out explicitly before implementation — this one doesn't need to.
- `_build_ask_chat_context`'s existing signature and return keys (`session_id`, `location_id`, `category_key`, `hubs`, `taxonomy`, `history`, `notice`) stay exactly as they are — this plan only *adds* a `"sessions"` key, never removes or renames an existing one, so the Task 4-6 code from the original `/ask` feature keeps working unmodified.
- No `hx-confirm` on the delete button — no other delete button in this app (reels, categories, hubs) uses a confirmation dialog, so this stays consistent with that existing convention rather than introducing a new one.
- The delete button must be a DOM **sibling** of the history-item link, never nested inside it — avoids a click on the 🗑 also triggering the link's `hx-get` via event bubbling, with no JS needed. Mirrors `partials/reel_list.html`'s existing `<li>` structure (info + sibling delete button).
- Opening `/ask` fresh (no `session_id`) always starts an empty conversation — no auto-resume of the last session. This plan does not touch that behavior.

---

### Task 1: `updated_at` bugfix + session-summary helpers

**Files:**
- Modify: `app/routers/ai_ask.py`
- Test: `tests/test_ai_ask.py`

**Interfaces:**
- Consumes: `AskSession`, `AskMessage`, `Location` (existing models); `get_taxonomy` (existing).
- Produces: `_session_message_label(first_message: str, max_len: int = 60) -> str`; `_session_scope_label(location_name: Optional[str], category_label: Optional[str]) -> str`; `_list_ask_sessions(session: Session) -> list[dict]` (each dict: `{"id": str, "message_label": str, "scope_label": str, "date_label": str}`, ordered by `updated_at` descending). `_build_ask_chat_context`'s returned dict gains a `"sessions"` key holding `_list_ask_sessions(session)`. `_run_ask_turn` now bumps `ask_session.updated_at` on every turn. All consumed by Task 2 (the new `GET /panel` session-reopen branch and the `DELETE` endpoint both call `_build_ask_chat_context`, which now always carries `sessions`) and Task 3 (the template renders `sessions`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ai_ask.py`. First, extend the existing import line:

```python
from app.routers.ai_ask import (
    _build_ask_chat_context,
    _list_ask_sessions,
    _run_ask_turn,
    _scoped_reel_context,
    _session_message_label,
    _session_scope_label,
)
```

(replacing the current `from app.routers.ai_ask import _build_ask_chat_context, _run_ask_turn, _scoped_reel_context` line).

Then append these tests at the end of the file:

```python
def test_run_ask_turn_bumps_updated_at_on_each_turn(session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "prima risposta"})
    ask_session = _run_ask_turn(session, None, None, None, "prima domanda")
    first_updated_at = ask_session.updated_at

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "seconda risposta"})
    ask_session = _run_ask_turn(session, ask_session.id, None, None, "seconda domanda")

    assert ask_session.updated_at > first_updated_at


def test_session_message_label_returns_short_text_unchanged():
    assert _session_message_label("Ciao, dove mangio?") == "Ciao, dove mangio?"


def test_session_message_label_truncates_long_text_with_ellipsis():
    long_text = "x" * 80
    label = _session_message_label(long_text)
    assert label == "x" * 60 + "…"
    assert len(label) == 61


def test_session_scope_label_with_both_filters():
    assert _session_scope_label("Tokyo / Kanto", "Cibo") == "Tokyo / Kanto — Cibo"


def test_session_scope_label_with_no_filters():
    assert _session_scope_label(None, None) == "Tutte le città — Tutte le categorie"


def test_list_ask_sessions_orders_by_updated_at_descending(session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "ok"})
    older = _run_ask_turn(session, None, None, None, "prima conversazione")
    newer = _run_ask_turn(session, None, None, None, "seconda conversazione")

    summaries = _list_ask_sessions(session)

    assert [s["id"] for s in summaries] == [newer.id, older.id]


def test_list_ask_sessions_includes_scope_and_message_label(session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "ok"})
    _run_ask_turn(session, None, hub.id, "food", "Dove mangio a Tokyo?")

    summaries = _list_ask_sessions(session)

    assert summaries[0]["message_label"] == "Dove mangio a Tokyo?"
    assert summaries[0]["scope_label"] == "Tokyo / Kanto — Cibo"
    assert summaries[0]["date_label"]


def test_build_ask_chat_context_includes_sessions_list(session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "ok"})
    ask_session = _run_ask_turn(session, None, None, None, "domanda")

    context = _build_ask_chat_context(session, ask_session.id, None, None)

    assert len(context["sessions"]) == 1
    assert context["sessions"][0]["id"] == ask_session.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_ask.py -v -k "updated_at or session_message_label or session_scope_label or list_ask_sessions or includes_sessions_list"`
Expected: FAIL with `ImportError: cannot import name '_list_ask_sessions'` (or similar for `_session_message_label`/`_session_scope_label`)

- [ ] **Step 3: Implement the bugfix and helpers**

In `app/routers/ai_ask.py`, add `datetime` to the imports — change:

```python
import logging
from typing import Optional
```

to:

```python
import logging
from datetime import datetime
from typing import Optional
```

Then, in `_run_ask_turn`, change the final block from:

```python
    session.add(AskMessage(session_id=ask_session.id, role="assistant", content=answer))
    session.commit()

    return ask_session
```

to:

```python
    session.add(AskMessage(session_id=ask_session.id, role="assistant", content=answer))
    ask_session.updated_at = datetime.utcnow()
    session.add(ask_session)
    session.commit()

    return ask_session
```

Then, immediately before `_build_ask_chat_context`, add the three new helper functions:

```python
def _session_message_label(first_message: str, max_len: int = 60) -> str:
    text = (first_message or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "…"


def _session_scope_label(location_name: Optional[str], category_label: Optional[str]) -> str:
    return f"{location_name or 'Tutte le città'} — {category_label or 'Tutte le categorie'}"


def _list_ask_sessions(session: Session) -> list[dict]:
    sessions = session.exec(select(AskSession).order_by(AskSession.updated_at.desc())).all()
    taxonomy = get_taxonomy(session)
    summaries = []
    for s in sessions:
        first_message = session.exec(
            select(AskMessage.content)
            .where(AskMessage.session_id == s.id, AskMessage.role == "user")
            .order_by(AskMessage.created_at)
        ).first()
        location = session.get(Location, s.location_id) if s.location_id else None
        category_label = (
            taxonomy[s.category_key]["label"] if s.category_key and s.category_key in taxonomy else None
        )
        summaries.append({
            "id": s.id,
            "message_label": _session_message_label(first_message or ""),
            "scope_label": _session_scope_label(location.name if location else None, category_label),
            "date_label": s.updated_at.strftime("%d/%m/%Y %H:%M"),
        })
    return summaries
```

Finally, in `_build_ask_chat_context`, add the `"sessions"` key to the returned dict — change:

```python
    hubs = session.exec(select(Location).where(Location.is_hub == True).order_by(Location.name)).all()
    return {
        "session_id": ask_session_id or "",
        "location_id": location_id or "",
        "category_key": category_key or "",
        "hubs": hubs,
        "taxonomy": get_taxonomy(session),
        "history": history,
        "notice": notice,
    }
```

to:

```python
    hubs = session.exec(select(Location).where(Location.is_hub == True).order_by(Location.name)).all()
    return {
        "session_id": ask_session_id or "",
        "location_id": location_id or "",
        "category_key": category_key or "",
        "hubs": hubs,
        "taxonomy": get_taxonomy(session),
        "history": history,
        "notice": notice,
        "sessions": _list_ask_sessions(session),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_ask.py -v -k "updated_at or session_message_label or session_scope_label or list_ask_sessions or includes_sessions_list"`
Expected: 8 passed

- [ ] **Step 5: Run the full test file to check for regressions**

Run: `uv run pytest tests/test_ai_ask.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add app/routers/ai_ask.py tests/test_ai_ask.py
git commit -m "feat: bump AskSession.updated_at per turn and add session-summary helpers"
```

---

### Task 2: Reopen and delete endpoints

**Files:**
- Modify: `app/routers/ai_ask.py`
- Test: `tests/test_ai_ask.py`

**Interfaces:**
- Consumes: `_build_ask_chat_context`, `AskSession`, `AskMessage` (Task 1 / existing).
- Produces: `GET /ui/ask/panel` now accepts an optional `session_id` query param (precedence over `location_id`/`category_key`, same rule `_run_ask_turn` already applies when continuing a session). New `DELETE /ui/ask/history/{session_id}` on `ui_router`. Both consumed by Task 3's templates.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ai_ask.py`:

```python
def test_ui_ask_panel_with_session_id_restores_history_and_scope(client, session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "risposta salvata"})
    client.post(
        "/ui/ask/message", data={"location_id": hub.id, "category_key": "", "message": "domanda salvata"}
    )
    ask_session = session.exec(select(AskSession)).first()

    reopened = client.get(f"/ui/ask/panel?session_id={ask_session.id}")
    assert reopened.status_code == 200
    assert "domanda salvata" in reopened.text
    assert "risposta salvata" in reopened.text
    assert f'value="{hub.id}" selected' in reopened.text


def test_ui_ask_panel_with_session_id_ignores_query_string_filters(client, session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    other_hub = Location(name="Osaka", is_hub=True)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "ok"})
    client.post("/ui/ask/message", data={"location_id": hub.id, "category_key": "", "message": "domanda"})
    ask_session = session.exec(select(AskSession)).first()

    reopened = client.get(f"/ui/ask/panel?session_id={ask_session.id}&location_id={other_hub.id}")
    assert f'value="{hub.id}" selected' in reopened.text
    assert f'value="{other_hub.id}" selected' not in reopened.text


def test_ui_ask_panel_with_unknown_session_id_shows_notice(client):
    response = client.get("/ui/ask/panel?session_id=does-not-exist")
    assert response.status_code == 200
    assert "Conversazione non trovata" in response.text


def test_ui_ask_delete_history_removes_other_session_and_keeps_current(client, session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "risposta uno"})
    client.post("/ui/ask/message", data={"location_id": "", "category_key": "", "message": "conversazione uno"})
    first_id = session.exec(select(AskSession)).first().id

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "risposta due"})
    second = client.post(
        "/ui/ask/message", data={"location_id": "", "category_key": "", "message": "conversazione due"}
    )
    second_id = [s.id for s in session.exec(select(AskSession)).all() if s.id != first_id][0]
    assert "conversazione due" in second.text

    response = client.request(
        "DELETE",
        f"/ui/ask/history/{first_id}",
        data={"current_session_id": second_id, "location_id": "", "category_key": ""},
    )
    assert response.status_code == 200
    assert "conversazione due" in response.text
    assert session.exec(select(AskSession).where(AskSession.id == first_id)).first() is None
    assert session.exec(select(AskSession).where(AskSession.id == second_id)).first() is not None


def test_ui_ask_delete_history_of_currently_open_session_resets_panel(client, session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "risposta"})
    client.post("/ui/ask/message", data={"location_id": "", "category_key": "", "message": "domanda"})
    ask_session_id = session.exec(select(AskSession)).first().id

    response = client.request(
        "DELETE",
        f"/ui/ask/history/{ask_session_id}",
        data={"current_session_id": ask_session_id, "location_id": "", "category_key": ""},
    )
    assert response.status_code == 200
    assert "domanda" not in response.text
    assert 'name="message"' in response.text


def test_ui_ask_delete_history_of_already_deleted_session_is_idempotent(client):
    response = client.request(
        "DELETE",
        "/ui/ask/history/does-not-exist",
        data={"current_session_id": "", "location_id": "", "category_key": ""},
    )
    assert response.status_code == 200
```

Note: `client.delete(url, data=...)` would raise `TypeError` — httpx's `TestClient.delete()` convenience method does not accept a body. Use `client.request("DELETE", url, data=...)` instead, as above — this has been verified to work (FastAPI/Starlette parse `Form()` fields from a DELETE request body with no issue).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_ask.py -v -k "panel_with_session_id or panel_with_unknown_session_id or delete_history"`
Expected: FAIL — `GET /ui/ask/panel?session_id=...` ignores the param (404/wrong content), `DELETE /ui/ask/history/...` returns 405 Method Not Allowed (route doesn't exist yet)

- [ ] **Step 3: Implement the endpoints**

In `app/routers/ai_ask.py`, replace the existing `ui_ask_panel` function:

```python
@ui_router.get("/panel")
def ui_ask_panel(
    request: Request,
    location_id: str = "",
    category_key: str = "",
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "partials/ask_chat.html",
        _build_ask_chat_context(session, None, location_id or None, category_key or None),
    )
```

with:

```python
@ui_router.get("/panel")
def ui_ask_panel(
    request: Request,
    session_id: str = "",
    location_id: str = "",
    category_key: str = "",
    session: Session = Depends(get_session),
):
    if session_id:
        ask_session = session.get(AskSession, session_id)
        if ask_session is None:
            context = _build_ask_chat_context(
                session, None, None, None, notice="Conversazione non trovata, ricomincia pure da qui."
            )
            return templates.TemplateResponse(request, "partials/ask_chat.html", context)
        context = _build_ask_chat_context(
            session, ask_session.id, ask_session.location_id, ask_session.category_key
        )
        return templates.TemplateResponse(request, "partials/ask_chat.html", context)

    return templates.TemplateResponse(
        request,
        "partials/ask_chat.html",
        _build_ask_chat_context(session, None, location_id or None, category_key or None),
    )
```

Then append at the end of the file:

```python
@ui_router.delete("/history/{session_id}")
def ui_ask_delete_history(
    request: Request,
    session_id: str,
    current_session_id: str = Form(""),
    location_id: str = Form(""),
    category_key: str = Form(""),
    session: Session = Depends(get_session),
):
    ask_session = session.get(AskSession, session_id)
    if ask_session is not None:
        for m in session.exec(select(AskMessage).where(AskMessage.session_id == session_id)).all():
            session.delete(m)
        session.delete(ask_session)
        session.commit()

    reopen_session_id = None if current_session_id == session_id else (current_session_id or None)
    context = _build_ask_chat_context(session, reopen_session_id, location_id or None, category_key or None)
    return templates.TemplateResponse(request, "partials/ask_chat.html", context)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_ask.py -v -k "panel_with_session_id or panel_with_unknown_session_id or delete_history"`
Expected: 6 passed

- [ ] **Step 5: Run the full test file to check for regressions**

Run: `uv run pytest tests/test_ai_ask.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add app/routers/ai_ask.py tests/test_ai_ask.py
git commit -m "feat: add session reopen (GET /ui/ask/panel?session_id=) and DELETE /ui/ask/history"
```

---

### Task 3: History list UI (template + CSS)

**Files:**
- Modify: `app/templates/partials/ask_chat.html`
- Create: `app/templates/partials/ask_history_list.html`
- Modify: `app/static/css/style.css`
- Test: `tests/test_ai_ask.py`

**Interfaces:**
- Consumes: the `sessions` context key (Task 1) and the `GET /ui/ask/panel?session_id=` / `DELETE /ui/ask/history/{id}` endpoints (Task 2).
- Produces: a rendered "Conversazioni precedenti" list inside every response that renders `partials/ask_chat.html`; a new `#ask-current-session-id` hidden input that travels with every `hx-include="#ask-filters"` request.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ai_ask.py`:

```python
def test_ui_ask_panel_renders_history_section_with_entries(client, session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "risposta"})
    client.post(
        "/ui/ask/message", data={"location_id": "", "category_key": "", "message": "domanda nello storico"}
    )

    response = client.get("/ui/ask/panel")
    assert "Conversazioni precedenti" in response.text
    assert "domanda nello storico" in response.text
    assert "ask-history-link" in response.text


def test_ui_ask_panel_renders_empty_history_message_when_no_sessions(client):
    response = client.get("/ui/ask/panel")
    assert "Nessuna conversazione salvata." in response.text


def test_ui_ask_panel_includes_current_session_hidden_input(client, session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "ok"})
    client.post("/ui/ask/message", data={"location_id": "", "category_key": "", "message": "ciao"})
    ask_session_id = session.exec(select(AskSession)).first().id

    response = client.get(f"/ui/ask/panel?session_id={ask_session_id}")
    assert f'id="ask-current-session-id" name="current_session_id" value="{ask_session_id}"' in response.text


def test_ui_ask_history_delete_button_present_for_each_entry(client, session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "ok"})
    client.post("/ui/ask/message", data={"location_id": "", "category_key": "", "message": "ciao"})
    ask_session_id = session.exec(select(AskSession)).first().id

    response = client.get("/ui/ask/panel")
    assert f'hx-delete="/ui/ask/history/{ask_session_id}"' in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_ask.py -v -k "renders_history_section or empty_history_message or current_session_hidden_input or history_delete_button"`
Expected: FAIL — "Conversazioni precedenti" / "ask-current-session-id" / `hx-delete="/ui/ask/history/..."` not found in the rendered output yet

- [ ] **Step 3: Create `app/templates/partials/ask_history_list.html`**

```html
<details class="ask-history">
    <summary>Conversazioni precedenti</summary>
    <ul class="ask-history-list">
        {% for s in sessions %}
        <li>
            <a href="#" class="ask-history-link" hx-get="/ui/ask/panel?session_id={{ s.id }}"
               hx-target="#ask-chat-panel" hx-swap="innerHTML">
                {{ s.message_label }} — {{ s.scope_label }} — {{ s.date_label }}
            </a>
            <button type="button" class="btn-delete" hx-delete="/ui/ask/history/{{ s.id }}"
                    hx-include="#ask-filters" hx-target="#ask-chat-panel" hx-swap="innerHTML"
                    aria-label="Elimina conversazione">🗑</button>
        </li>
        {% endfor %}
        {% if not sessions %}
        <li class="ask-history-empty">Nessuna conversazione salvata.</li>
        {% endif %}
    </ul>
</details>
```

- [ ] **Step 4: Update `app/templates/partials/ask_chat.html`**

Change:

```html
    <button type="button" hx-get="/ui/ask/panel" hx-target="#ask-chat-panel" hx-swap="innerHTML" hx-include="#ask-filters">Nuova conversazione</button>
</div>

<div id="ask-chat-messages">
```

to:

```html
    <button type="button" hx-get="/ui/ask/panel" hx-target="#ask-chat-panel" hx-swap="innerHTML" hx-include="#ask-filters">Nuova conversazione</button>
    <input type="hidden" id="ask-current-session-id" name="current_session_id" value="{{ session_id }}">
</div>

{% include "partials/ask_history_list.html" %}

<div id="ask-chat-messages">
```

- [ ] **Step 5: Add CSS**

In `app/static/css/style.css`, insert this block right after the existing `.ai-notice { ... }` rule (i.e. immediately before the `@media (max-width: 480px)` block):

```css
.ask-history {
    margin-bottom: 0.75rem;
}

.ask-history-list {
    list-style: none;
    padding: 0;
    margin: 0.5rem 0 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
}

.ask-history-list li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
}

.ask-history-link {
    color: var(--color-ink);
    text-decoration: none;
    font-size: 0.9rem;
}

.ask-history-link:hover {
    text-decoration: underline;
}

.ask-history-empty {
    color: var(--color-ink-medium);
    font-size: 0.9rem;
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_ask.py -v -k "renders_history_section or empty_history_message or current_session_hidden_input or history_delete_button"`
Expected: 4 passed

- [ ] **Step 7: Run the full test suite to check for regressions**

Run: `uv run pytest -q`
Expected: all passed (274 existing + 18 new from this plan = 292)

- [ ] **Step 8: Manually verify in the browser (optional — skip if running unattended)**

With the dev server running (`uv run uvicorn app.main:app --reload`):
1. Open `/ask`, have a short conversation, then click "Nuova conversazione".
2. Open the "Conversazioni precedenti" `<details>` — the previous conversation should be listed with its first question, scope, and timestamp.
3. Click it — the chat history and the city/category selects should restore to what that conversation had.
4. Send a new message in the reopened conversation — it should append to that same conversation (check the history list afterward: its timestamp should have moved to the top).
5. Click the 🗑 next to a *different* conversation than the one open — it should disappear from the list without disturbing the open conversation.
6. Click the 🗑 next to the *currently open* conversation — the chat panel should reset to empty.

- [ ] **Step 9: Commit**

```bash
git add app/templates/partials/ask_chat.html app/templates/partials/ask_history_list.html app/static/css/style.css tests/test_ai_ask.py
git commit -m "feat: add conversation history list to the ask chat panel"
```

---

## Self-review notes

- Spec coverage: `updated_at` bugfix, session summaries (label truncation, scope label, ordering) and their inclusion in `_build_ask_chat_context` (Task 1); reopening a session via `GET /panel?session_id=` with correct precedence over query-string filters, and `DELETE /ui/ask/history/{id}` with both its branches (deleting the open session vs. a different one, and idempotency on an already-deleted id) (Task 2); the `<details>` list, delete-button sibling structure, hidden `current_session_id` input, and CSS (Task 3) — all covered.
- No placeholders: every step has concrete code and exact assertions.
- Type/name consistency checked: `_session_message_label`, `_session_scope_label`, `_list_ask_sessions` signatures match between their Task 1 definition and Task 1's own tests; `_build_ask_chat_context`'s new `"sessions"` key name matches what Task 3's template reads (`{% for s in sessions %}`); the `current_session_id`/`location_id`/`category_key` Form field names on the new `DELETE` endpoint (Task 2) match the `name=` attributes the hidden input and selects already carry inside `#ask-filters` (Task 3), which is what `hx-include="#ask-filters"` on the delete button submits.
- Verified empirically (not just assumed) that `TestClient`'s `.delete()` convenience method rejects a `data=` body, but `.request("DELETE", url, data=...)` works, and that FastAPI parses `Form()` fields from a DELETE request body — Task 2's tests use the verified form.
