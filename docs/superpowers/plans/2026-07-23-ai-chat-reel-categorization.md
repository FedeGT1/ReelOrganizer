# AI Chat Reel Categorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire a chat-style UI onto the existing `/api/ai/categorize` backend so the user can paste a reel link + description, get an AI-proposed place/type, answer clarifying questions, and save the reel (creating a new location if needed) without touching the manual form.

**Architecture:** Extract the existing categorize-turn logic in `app/routers/ai_categorize.py` into a shared helper reused by the existing JSON endpoint and three new HTMX UI endpoints (`GET /ui/ai/panel`, `POST /ui/ai/message`, `POST /ui/ai/confirm`). A new Jinja partial (`partials/ai_chat.html`) renders conversation history, a proposal/confirm card, and the next-input form; state (session id, original link) threads forward via hidden form fields, matching the existing `reels.py`/`map.py` HTMX pattern in this app.

**Tech Stack:** FastAPI, SQLModel/SQLite, Jinja2 + HTMX (no new client-side JS), Anthropic Python SDK (already integrated).

## Global Constraints

- All user-facing text is in Italian (existing convention throughout `app/templates`).
- No new client-side JavaScript for this feature — HTMX-only interactivity, consistent with `reels.py`/`map.py` (the only existing custom JS, `map.js`, is unrelated to this feature).
- No structured/manual edit UI for AI proposals — corrections happen only by sending another chat message (user decision, see spec §7/§9).
- Never auto-save without explicit user confirmation (original design `docs/superpowers/specs/2026-07-21-japan-reel-organizer-design.md` §5.3 step 5).
- Any `link` must pass the existing `_is_safe_link` check (`http`/`https` scheme only) before it enters a conversation or is saved — same bar as the manual add-reel form (`app/routers/reels.py`).
- Reference spec: `docs/superpowers/specs/2026-07-23-ai-chat-reel-categorization-design.md`.

---

## File Structure

- Modify `app/ai/prompts.py` — add `lat`/`lon` to `RESPONSE_SCHEMA`; extend `build_system_prompt`.
- Modify `tests/test_ai_prompts.py` — assert the new schema fields and prompt content.
- Modify `app/routers/ai_categorize.py` — extract shared `_run_turn` helper (with the "force a question when a new location has no coordinates" safety net), add `ui_router` with `GET /panel`, `POST /message`, `POST /confirm`, add `_build_ai_chat_context`, add graceful Anthropic-error and stale-session handling.
- Modify `tests/test_ai_categorize.py` — regression tests for the safety net and the graceful AI-failure fallback at the JSON-endpoint layer.
- Create `tests/test_ai_ui.py` — tests for all three new `/ui/ai/*` routes.
- Create `app/templates/partials/ai_chat.html` — chat history, confirm card, input form.
- Modify `app/templates/index.html` — add the `#ai-chat-panel` section.
- Modify `app/main.py` — register `ai_categorize.ui_router`.
- Modify `app/static/css/style.css` — minimal chat-bubble/notice styling.

---

### Task 1: Extend the AI response schema and prompt with lat/lon

**Files:**
- Modify: `app/ai/prompts.py`
- Test: `tests/test_ai_prompts.py`

**Interfaces:**
- Produces: `RESPONSE_SCHEMA` (dict, now includes `"lat"`/`"lon"` in `properties` and `required`) and `build_system_prompt(hub_names)` (str) — both consumed unchanged in signature by `app/ai/client.py` and by Task 2's `_run_turn`.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_ai_prompts.py` with:

```python
from app.ai.prompts import RESPONSE_SCHEMA, build_system_prompt


def test_response_schema_has_required_fields():
    assert RESPONSE_SCHEMA["required"] == [
        "place_name", "near_hub", "types", "note", "confidence", "question",
        "lat", "lon",
    ]
    assert RESPONSE_SCHEMA["additionalProperties"] is False


def test_response_schema_lat_lon_are_nullable_numbers():
    assert RESPONSE_SCHEMA["properties"]["lat"] == {"type": ["number", "null"]}
    assert RESPONSE_SCHEMA["properties"]["lon"] == {"type": ["number", "null"]}


def test_build_system_prompt_includes_hub_names():
    prompt = build_system_prompt(["Tokyo / Kanto", "Kyoto - Osaka / Kansai"])
    assert "Tokyo / Kanto" in prompt
    assert "Kyoto - Osaka / Kansai" in prompt


def test_build_system_prompt_mentions_lat_lon_estimation():
    prompt = build_system_prompt(["Tokyo / Kanto"])
    assert "lat" in prompt
    assert "lon" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_prompts.py -v`
Expected: `test_response_schema_has_required_fields` and `test_response_schema_lat_lon_are_nullable_numbers` and `test_build_system_prompt_mentions_lat_lon_estimation` FAIL (current schema/prompt has no `lat`/`lon`).

- [ ] **Step 3: Update the schema and prompt**

Replace the full contents of `app/ai/prompts.py` with:

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
        "lat": {"type": ["number", "null"]},
        "lon": {"type": ["number", "null"]},
    },
    "required": [
        "place_name", "near_hub", "types", "note", "confidence", "question",
        "lat", "lon",
    ],
    "additionalProperties": False,
}


def build_system_prompt(hub_names: Iterable[str]) -> str:
    hubs_list = ", ".join(hub_names) if hub_names else "nessuno ancora"
    return (
        "Sei un assistente che aiuta a categorizzare reel Instagram salvati per un viaggio in Giappone. "
        "L'utente ti invia un link e una didascalia (o una descrizione libera) di un reel. "
        "Non puoi aprire il link: lavori solo sul testo fornito. "
        f"Le tappe principali (hub) gia' esistenti sono: {hubs_list}. "
        "Se il testo corrisponde chiaramente a un hub esistente o a una localita' vicina, usa near_hub per indicarlo. "
        "Se non hai abbastanza informazioni per proporre un luogo con sicurezza, valorizza 'question' con una domanda "
        "di chiarimento e lascia gli altri campi con la tua migliore ipotesi. "
        "Se il luogo proposto non corrisponde a nessun hub o tappa gia' esistente, valorizza anche lat e lon con una "
        "stima approssimativa (in gradi decimali) della sua posizione reale in Giappone; se non riesci a stimarle con "
        "sufficiente sicurezza, lascia lat e lon a null e usa 'question' per chiedere la citta' o zona piu' vicina. "
        "Se il luogo corrisponde a un hub o tappa gia' esistente, puoi lasciare lat e lon a null: non verranno usate. "
        "Rispondi seguendo esattamente lo schema JSON fornito."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_prompts.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/ai/prompts.py tests/test_ai_prompts.py
git commit -m "feat: add lat/lon estimation to AI categorization schema"
```

---

### Task 2: Extract shared turn helper with the missing-coordinates safety net

**Files:**
- Modify: `app/routers/ai_categorize.py`
- Test: `tests/test_ai_categorize.py`

**Interfaces:**
- Consumes: `RESPONSE_SCHEMA`/`build_system_prompt` (Task 1, unchanged call sites), `ai_client.categorize(hub_names, messages) -> dict` (unchanged).
- Produces: `_run_turn(session: Session, session_id: Optional[str], message: str) -> tuple[AiSession, dict, Optional[str]]` — returns `(ai_session, result, matched_location_id)`. `result` always has `lat`/`lon` keys accessed via `.get(...)` (never raises `KeyError` if a caller/test provides a dict missing those keys). This is the function Task 3's UI routes will call.
- `POST /api/ai/categorize`'s request/response contract is unchanged (extra `lat`/`lon` keys on the internal `result` dict are silently dropped by `CategorizeResponse`'s default pydantic `extra="ignore"` behavior).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ai_categorize.py` (keep all 4 existing tests, add this one at the end of the file):

```python
def test_categorize_forces_question_when_new_location_missing_coordinates(client, session, monkeypatch):
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, messages: {
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_categorize.py::test_categorize_forces_question_when_new_location_missing_coordinates -v`
Expected: FAIL — `response.json()["question"]` is `None` (no safety net yet).

- [ ] **Step 3: Refactor the router with the shared helper and safety net**

Replace the full contents of `app/routers/ai_categorize.py` with:

```python
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
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
    api_messages = [{"role": m.role, "content": m.content} for m in history]

    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]

    result = ai_client.categorize(hub_names, api_messages)
    result["types"] = [t for t in result.get("types", []) if t in VALID_TYPES]

    matched_location_id = _find_matching_location(session, result["place_name"])

    if (
        matched_location_id is None
        and result.get("question") is None
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        result["question"] = (
            "Non riesco a stimare le coordinate di questo posto: "
            "qual e' la citta' o zona piu' vicina?"
        )

    session.add(AiMessage(session_id=ai_session.id, role="assistant", content=json.dumps(result)))
    session.commit()

    return ai_session, result, matched_location_id


@router.post("/categorize", response_model=CategorizeResponse)
def categorize_reel(payload: CategorizeRequest, session: Session = Depends(get_session)):
    ai_session, result, matched_location_id = _run_turn(session, payload.session_id, payload.message)
    return CategorizeResponse(session_id=ai_session.id, matched_location_id=matched_location_id, **result)
```

- [ ] **Step 4: Run all AI tests to verify nothing regressed and the new test passes**

Run: `uv run pytest tests/test_ai_categorize.py tests/test_ai_client.py tests/test_ai_prompts.py -v`
Expected: PASS (all tests, including the 5 in `test_ai_categorize.py`)

- [ ] **Step 5: Commit**

```bash
git add app/routers/ai_categorize.py tests/test_ai_categorize.py
git commit -m "refactor: extract shared AI turn helper with missing-coordinates safety net"
```

---

### Task 3: Add the chat panel UI (`GET /ui/ai/panel`, `POST /ui/ai/message`)

**Files:**
- Modify: `app/routers/ai_categorize.py`
- Modify: `app/main.py`
- Modify: `app/templates/index.html`
- Modify: `app/static/css/style.css`
- Create: `app/templates/partials/ai_chat.html`
- Create: `tests/test_ai_ui.py`

**Interfaces:**
- Consumes: `_run_turn` (Task 2), `_find_matching_location` (existing), `TAXONOMY` (`app/taxonomy.py`), `_is_safe_link` (`app/routers/reels.py`), `templates` (`app/web.py`).
- Produces: `_build_ai_chat_context(session: Session, ai_session_id: Optional[str], link: str) -> dict` with keys `session_id: str`, `link: str`, `history: list[dict]` (each item `{"role": "user", "text": str}` or `{"role": "assistant", "result": dict}`), `latest_result: Optional[dict]`, `can_confirm: bool`, `matched_location_id: str` (empty string if none), `taxonomy: dict`. This context shape is consumed as-is by Task 4's confirm route and template additions — do not rename these keys.
- Produces: `ui_router = APIRouter(prefix="/ui/ai", tags=["ai-ui"])` with `GET /panel` and `POST /message`, registered in `app/main.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ai_ui.py`:

```python
from sqlmodel import select

from app.ai import client as ai_client
from app.models import AiSession, Location


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
        lambda hub_names, messages: {
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
        lambda hub_names, messages: {
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
        lambda hub_names, messages: {
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
        lambda hub_names, messages: {
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_ui.py -v`
Expected: FAIL — `/ui/ai/panel` and `/ui/ai/message` don't exist yet (404s).

- [ ] **Step 3: Add the UI routes and context builder**

Replace the full contents of `app/routers/ai_categorize.py` with:

```python
import json
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.db import get_session
from app.models import AiMessage, AiSession, Location
from app.routers.reels import _is_safe_link
from app.taxonomy import TAXONOMY, VALID_TYPES
from app.web import templates

router = APIRouter(prefix="/api/ai", tags=["ai"])
ui_router = APIRouter(prefix="/ui/ai", tags=["ai-ui"])


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
    api_messages = [{"role": m.role, "content": m.content} for m in history]

    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]

    result = ai_client.categorize(hub_names, api_messages)
    result["types"] = [t for t in result.get("types", []) if t in VALID_TYPES]

    matched_location_id = _find_matching_location(session, result["place_name"])

    if (
        matched_location_id is None
        and result.get("question") is None
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        result["question"] = (
            "Non riesco a stimare le coordinate di questo posto: "
            "qual e' la citta' o zona piu' vicina?"
        )

    session.add(AiMessage(session_id=ai_session.id, role="assistant", content=json.dumps(result)))
    session.commit()

    return ai_session, result, matched_location_id


@router.post("/categorize", response_model=CategorizeResponse)
def categorize_reel(payload: CategorizeRequest, session: Session = Depends(get_session)):
    ai_session, result, matched_location_id = _run_turn(session, payload.session_id, payload.message)
    return CategorizeResponse(session_id=ai_session.id, matched_location_id=matched_location_id, **result)


def _build_ai_chat_context(session: Session, ai_session_id: Optional[str], link: str) -> dict:
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
        "taxonomy": TAXONOMY,
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

    ai_session, _, _ = _run_turn(session, session_id or None, combined_message)

    return templates.TemplateResponse(
        request, "partials/ai_chat.html", _build_ai_chat_context(session, ai_session.id, link)
    )
```

- [ ] **Step 4: Create the chat partial template**

Create `app/templates/partials/ai_chat.html`:

```html
<div id="ai-chat-messages">
    {% for turn in history %}
        {% if turn.role == 'user' %}
        <div class="chat-bubble user">{{ turn.text }}</div>
        {% else %}
        <div class="chat-bubble assistant">
            {% if turn.result.question %}
            {{ turn.result.question }}
            {% else %}
            <strong>{{ turn.result.place_name }}</strong>{% if turn.result.near_hub %} (vicino a {{ turn.result.near_hub }}){% endif %}<br>
            <span class="types">{% for t in turn.result.types %}{{ taxonomy[t].icon }} {{ taxonomy[t].label }} {% endfor %}</span><br>
            {% if turn.result.note %}<span class="note">{{ turn.result.note }}</span><br>{% endif %}
            <span class="confidence">Confidenza: {{ turn.result.confidence }}</span>
            {% endif %}
        </div>
        {% endif %}
    {% endfor %}
</div>

<form hx-post="/ui/ai/message" hx-target="#ai-chat-panel" hx-swap="innerHTML" class="ai-input-form">
    <input type="hidden" name="session_id" value="{{ session_id }}">
    {% if not session_id %}
    <input type="url" name="link" placeholder="Link Instagram" required>
    <textarea name="message" placeholder="Descrizione o didascalia del reel" required></textarea>
    {% else %}
    <input type="hidden" name="link" value="{{ link }}">
    <textarea name="message" placeholder="Scrivi..." required></textarea>
    {% endif %}
    <button type="submit">Invia</button>
</form>
```

- [ ] **Step 5: Wire the section into the page and register the router**

Replace the full contents of `app/templates/index.html` with:

```html
{% extends "base.html" %}
{% block content %}
<section id="map-container" hx-get="/ui/map" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento mappa...</p>
</section>
<section id="ai-chat-panel" hx-get="/ui/ai/panel" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento assistente AI...</p>
</section>
<section id="reel-list" hx-get="/ui/reels" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento reel...</p>
</section>
{% endblock %}
```

Replace the full contents of `app/main.py` with:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.db import create_db_and_tables, engine
from app.routers import ai_categorize, locations, map as map_router, reels
from app.seed import seed_if_empty
from app.web import templates


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

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Add minimal chat styling**

In `app/static/css/style.css`, insert the following block right before the final `@media (max-width: 480px) { ... }` block (so the mobile override stays last):

```css
.chat-bubble {
    padding: 0.5rem 0.75rem;
    margin: 0.35rem 0;
    border-radius: 8px;
    max-width: 80%;
}

.chat-bubble.user {
    background: var(--color-sea);
    color: var(--color-ink);
    margin-left: auto;
}

.chat-bubble.assistant {
    background: var(--color-paper);
    border: 1px solid var(--color-ink-medium);
}

.ai-input-form textarea,
.ai-input-form input[type="url"] {
    width: 100%;
    margin-bottom: 0.4rem;
    font-family: inherit;
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_ui.py -v`
Expected: PASS (5 tests)

Run: `uv run pytest -v`
Expected: PASS (full suite, no regressions in `test_index_page.py`, `test_ui_fragments.py`, etc.)

- [ ] **Step 8: Commit**

```bash
git add app/routers/ai_categorize.py app/main.py app/templates/index.html app/templates/partials/ai_chat.html app/static/css/style.css tests/test_ai_ui.py
git commit -m "feat: add AI chat panel UI for reel categorization"
```

---

### Task 4: Add save/confirm (`POST /ui/ai/confirm`)

**Files:**
- Modify: `app/routers/ai_categorize.py`
- Modify: `app/templates/partials/ai_chat.html`
- Modify: `tests/test_ai_ui.py`

**Interfaces:**
- Consumes: `_build_ai_chat_context` (Task 3, unchanged), `_is_safe_link`, `_reel_list_context` (`app/routers/reels.py`), `templates.get_template(name).render(dict)` (Jinja2 `Template.render`, no `request` key needed since these partials don't reference `request`).
- Produces: `POST /ui/ai/confirm` — on success, creates a `Reel` (and a `Location` if the proposal didn't match one), deletes the `AiSession`/`AiMessage` rows for the submitted `session_id` (a no-op if it doesn't correspond to an existing session, e.g. in tests that pass a placeholder id), and returns an `HTMLResponse` whose body is the reset `ai_chat.html` content followed by `<div hx-swap-oob="innerHTML:#reel-list">...</div>` wrapping the refreshed `partials/reel_list.html`.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_ai_ui.py` with (existing 5 tests plus new confirm-related tests):

```python
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
        lambda hub_names, messages: {
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
        lambda hub_names, messages: {
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
        lambda hub_names, messages: {
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
        lambda hub_names, messages: {
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
        lambda hub_names, messages: {
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
        lambda hub_names, messages: {
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
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/test_ai_ui.py -v`
Expected: the 7 new tests (confirm-button visibility + 5 confirm-route tests + session-cleanup test) FAIL — `POST /ui/ai/confirm` doesn't exist yet (404), and the confirm form isn't in the template yet.

- [ ] **Step 3: Add the confirm form block to the template**

Replace the full contents of `app/templates/partials/ai_chat.html` with:

```html
<div id="ai-chat-messages">
    {% for turn in history %}
        {% if turn.role == 'user' %}
        <div class="chat-bubble user">{{ turn.text }}</div>
        {% else %}
        <div class="chat-bubble assistant">
            {% if turn.result.question %}
            {{ turn.result.question }}
            {% else %}
            <strong>{{ turn.result.place_name }}</strong>{% if turn.result.near_hub %} (vicino a {{ turn.result.near_hub }}){% endif %}<br>
            <span class="types">{% for t in turn.result.types %}{{ taxonomy[t].icon }} {{ taxonomy[t].label }} {% endfor %}</span><br>
            {% if turn.result.note %}<span class="note">{{ turn.result.note }}</span><br>{% endif %}
            <span class="confidence">Confidenza: {{ turn.result.confidence }}</span>
            {% endif %}
        </div>
        {% endif %}
    {% endfor %}
</div>

{% if can_confirm %}
<form hx-post="/ui/ai/confirm" hx-target="#ai-chat-panel" hx-swap="innerHTML" class="ai-confirm-form">
    <input type="hidden" name="session_id" value="{{ session_id }}">
    <input type="hidden" name="link" value="{{ link }}">
    <input type="hidden" name="place_name" value="{{ latest_result.place_name }}">
    <input type="hidden" name="near_hub" value="{{ latest_result.near_hub or '' }}">
    {% for t in latest_result.types %}<input type="hidden" name="types" value="{{ t }}">{% endfor %}
    <input type="hidden" name="note" value="{{ latest_result.note }}">
    <input type="hidden" name="lat" value="{{ latest_result.lat if latest_result.lat is not none else '' }}">
    <input type="hidden" name="lon" value="{{ latest_result.lon if latest_result.lon is not none else '' }}">
    <input type="hidden" name="matched_location_id" value="{{ matched_location_id }}">
    <button type="submit">Conferma e salva</button>
</form>
{% endif %}

<form hx-post="/ui/ai/message" hx-target="#ai-chat-panel" hx-swap="innerHTML" class="ai-input-form">
    <input type="hidden" name="session_id" value="{{ session_id }}">
    {% if not session_id %}
    <input type="url" name="link" placeholder="Link Instagram" required>
    <textarea name="message" placeholder="Descrizione o didascalia del reel" required></textarea>
    {% else %}
    <input type="hidden" name="link" value="{{ link }}">
    <textarea name="message" placeholder="Scrivi..." required></textarea>
    {% endif %}
    <button type="submit">Invia</button>
</form>
```

- [ ] **Step 4: Add the confirm route**

Replace the full contents of `app/routers/ai_categorize.py` with:

```python
import json
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.db import get_session
from app.models import AiMessage, AiSession, Location, Reel, ReelType
from app.routers.reels import _is_safe_link, _reel_list_context
from app.taxonomy import TAXONOMY, VALID_TYPES
from app.web import templates

router = APIRouter(prefix="/api/ai", tags=["ai"])
ui_router = APIRouter(prefix="/ui/ai", tags=["ai-ui"])


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
    api_messages = [{"role": m.role, "content": m.content} for m in history]

    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]

    result = ai_client.categorize(hub_names, api_messages)
    result["types"] = [t for t in result.get("types", []) if t in VALID_TYPES]

    matched_location_id = _find_matching_location(session, result["place_name"])

    if (
        matched_location_id is None
        and result.get("question") is None
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        result["question"] = (
            "Non riesco a stimare le coordinate di questo posto: "
            "qual e' la citta' o zona piu' vicina?"
        )

    session.add(AiMessage(session_id=ai_session.id, role="assistant", content=json.dumps(result)))
    session.commit()

    return ai_session, result, matched_location_id


@router.post("/categorize", response_model=CategorizeResponse)
def categorize_reel(payload: CategorizeRequest, session: Session = Depends(get_session)):
    ai_session, result, matched_location_id = _run_turn(session, payload.session_id, payload.message)
    return CategorizeResponse(session_id=ai_session.id, matched_location_id=matched_location_id, **result)


def _build_ai_chat_context(session: Session, ai_session_id: Optional[str], link: str) -> dict:
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
        "taxonomy": TAXONOMY,
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

    ai_session, _, _ = _run_turn(session, session_id or None, combined_message)

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
        hub = None
        if near_hub:
            hub = session.exec(
                select(Location).where(
                    Location.is_hub == True, func.lower(Location.name) == near_hub.lower()
                )
            ).first()

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

    for type_value in types:
        if type_value in VALID_TYPES:
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

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_ui.py -v`
Expected: PASS (12 tests)

Run: `uv run pytest -v`
Expected: PASS (full suite)

- [ ] **Step 6: Commit**

```bash
git add app/routers/ai_categorize.py app/templates/partials/ai_chat.html tests/test_ai_ui.py
git commit -m "feat: save AI-categorized reels, creating a location when needed"
```

---

### Task 5: Graceful error handling (Anthropic failures, stale session id)

**Files:**
- Modify: `app/routers/ai_categorize.py`
- Modify: `app/templates/partials/ai_chat.html`
- Modify: `tests/test_ai_categorize.py`
- Modify: `tests/test_ai_ui.py`
- Modify: `app/static/css/style.css`

**Interfaces:**
- Consumes: `anthropic.AnthropicError` (base exception class from the `anthropic` package already a project dependency).
- Produces: `_build_ai_chat_context(session, ai_session_id, link, notice=None)` — gains an optional 4th parameter (all Task 3/4 call sites keep working unchanged since it defaults to `None`); adds a `"notice"` key to the returned dict.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ai_categorize.py` (add `import anthropic` near the top with the other imports, then add this test at the end of the file):

```python
def test_categorize_returns_friendly_question_when_ai_call_fails(client, session, monkeypatch):
    def boom(hub_names, messages):
        raise anthropic.AnthropicError("boom")

    monkeypatch.setattr(ai_client, "categorize", boom)

    response = client.post("/api/ai/categorize", json={"message": "Qualcosa"})
    assert response.status_code == 200
    assert "riprova" in response.json()["question"].lower()
```

Append to `tests/test_ai_ui.py` (add `import anthropic` near the top with the other imports, then add these two tests at the end of the file):

```python
def test_ui_ai_message_shows_friendly_error_when_ai_call_fails(client, session, monkeypatch):
    def boom(hub_names, messages):
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

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_categorize.py::test_categorize_returns_friendly_question_when_ai_call_fails tests/test_ai_ui.py::test_ui_ai_message_shows_friendly_error_when_ai_call_fails tests/test_ai_ui.py::test_ui_ai_message_with_unknown_session_id_resets_panel_with_notice -v`
Expected: FAIL — the `anthropic.AnthropicError` currently propagates as an unhandled 500, and an unknown `session_id` currently returns a raw 404 instead of a reset panel.

- [ ] **Step 3: Add error handling to the router**

Replace the full contents of `app/routers/ai_categorize.py` with:

```python
import json
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
from app.routers.reels import _is_safe_link, _reel_list_context
from app.taxonomy import TAXONOMY, VALID_TYPES
from app.web import templates

router = APIRouter(prefix="/api/ai", tags=["ai"])
ui_router = APIRouter(prefix="/ui/ai", tags=["ai-ui"])


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
    api_messages = [{"role": m.role, "content": m.content} for m in history]

    hubs = session.exec(select(Location).where(Location.is_hub == True)).all()
    hub_names = [h.name for h in hubs]

    try:
        result = ai_client.categorize(hub_names, api_messages)
    except anthropic.AnthropicError:
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

    result["types"] = [t for t in result.get("types", []) if t in VALID_TYPES]

    matched_location_id = _find_matching_location(session, result["place_name"])

    if (
        matched_location_id is None
        and result.get("question") is None
        and (result.get("lat") is None or result.get("lon") is None)
    ):
        result["question"] = (
            "Non riesco a stimare le coordinate di questo posto: "
            "qual e' la citta' o zona piu' vicina?"
        )

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
        "taxonomy": TAXONOMY,
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
        hub = None
        if near_hub:
            hub = session.exec(
                select(Location).where(
                    Location.is_hub == True, func.lower(Location.name) == near_hub.lower()
                )
            ).first()

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

    for type_value in types:
        if type_value in VALID_TYPES:
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

- [ ] **Step 4: Render the notice in the template**

Replace the full contents of `app/templates/partials/ai_chat.html` with:

```html
{% if notice %}
<p class="ai-notice">{{ notice }}</p>
{% endif %}
<div id="ai-chat-messages">
    {% for turn in history %}
        {% if turn.role == 'user' %}
        <div class="chat-bubble user">{{ turn.text }}</div>
        {% else %}
        <div class="chat-bubble assistant">
            {% if turn.result.question %}
            {{ turn.result.question }}
            {% else %}
            <strong>{{ turn.result.place_name }}</strong>{% if turn.result.near_hub %} (vicino a {{ turn.result.near_hub }}){% endif %}<br>
            <span class="types">{% for t in turn.result.types %}{{ taxonomy[t].icon }} {{ taxonomy[t].label }} {% endfor %}</span><br>
            {% if turn.result.note %}<span class="note">{{ turn.result.note }}</span><br>{% endif %}
            <span class="confidence">Confidenza: {{ turn.result.confidence }}</span>
            {% endif %}
        </div>
        {% endif %}
    {% endfor %}
</div>

{% if can_confirm %}
<form hx-post="/ui/ai/confirm" hx-target="#ai-chat-panel" hx-swap="innerHTML" class="ai-confirm-form">
    <input type="hidden" name="session_id" value="{{ session_id }}">
    <input type="hidden" name="link" value="{{ link }}">
    <input type="hidden" name="place_name" value="{{ latest_result.place_name }}">
    <input type="hidden" name="near_hub" value="{{ latest_result.near_hub or '' }}">
    {% for t in latest_result.types %}<input type="hidden" name="types" value="{{ t }}">{% endfor %}
    <input type="hidden" name="note" value="{{ latest_result.note }}">
    <input type="hidden" name="lat" value="{{ latest_result.lat if latest_result.lat is not none else '' }}">
    <input type="hidden" name="lon" value="{{ latest_result.lon if latest_result.lon is not none else '' }}">
    <input type="hidden" name="matched_location_id" value="{{ matched_location_id }}">
    <button type="submit">Conferma e salva</button>
</form>
{% endif %}

<form hx-post="/ui/ai/message" hx-target="#ai-chat-panel" hx-swap="innerHTML" class="ai-input-form">
    <input type="hidden" name="session_id" value="{{ session_id }}">
    {% if not session_id %}
    <input type="url" name="link" placeholder="Link Instagram" required>
    <textarea name="message" placeholder="Descrizione o didascalia del reel" required></textarea>
    {% else %}
    <input type="hidden" name="link" value="{{ link }}">
    <textarea name="message" placeholder="Scrivi..." required></textarea>
    {% endif %}
    <button type="submit">Invia</button>
</form>
```

- [ ] **Step 5: Add notice styling**

In `app/static/css/style.css`, insert this block right after the `.ai-input-form` rule added in Task 3 (still before the final `@media` block):

```css
.ai-notice {
    color: var(--color-hanko);
    font-family: "JetBrains Mono", monospace;
    font-size: 0.85rem;
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_categorize.py tests/test_ai_ui.py -v`
Expected: PASS (6 + 14 tests)

Run: `uv run pytest -v`
Expected: PASS (full suite, no regressions)

- [ ] **Step 7: Commit**

```bash
git add app/routers/ai_categorize.py app/templates/partials/ai_chat.html app/static/css/style.css tests/test_ai_categorize.py tests/test_ai_ui.py
git commit -m "feat: handle AI call failures and stale sessions gracefully in the chat UI"
```

---

## Manual verification (after all tasks)

Automated tests cover routing/DB logic but not the real Anthropic call or the rendered page. Before considering this done:

1. Ensure `ANTHROPIC_API_KEY` is set in the environment (the existing `/api/ai/categorize` endpoint already requires this — see `app/ai/client.py`).
2. Run `uv run uvicorn app.main:app --reload` and open `http://127.0.0.1:8000/`.
3. In the new "assistente AI" section: submit a real Instagram link + a description of a known place (e.g. an existing seeded hub) — confirm a proposal card with type icons appears and "Conferma e salva" works, and the reel shows up in the list below without a page reload.
4. Submit a vague description that should trigger a clarifying question — confirm the question appears and no confirm button is shown; reply and confirm the conversation continues correctly.
5. Submit a description of a clearly new, real place not near any existing hub — confirm the AI estimates coordinates and, after saving, the new location shows up correctly placed on the Leaflet map (`/ui/map`).
