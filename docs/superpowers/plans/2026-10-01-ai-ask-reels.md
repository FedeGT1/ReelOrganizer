# AI Ask — Chat di Ricerca sui Reel Salvati Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new "Chiedi all'AI" menu entry with a multi-turn chat that answers questions about the user's saved reels, filtered by city and (optionally) category, using the already-configured AI provider (Anthropic Haiku or OpenAI "Luna").

**Architecture:** Two new DB tables (`AskSession`, `AskMessage`) track this chat independently of the existing reel-categorization chat (`AiSession`/`AiMessage`). A new router (`app/routers/ai_ask.py`) re-fetches the reels matching the session's city/category scope on every turn, builds a system prompt embedding them, and calls the existing `AIProvider.call_json` with a minimal `{"answer": "string"}` schema — no provider protocol changes needed. A new full page (`/ask`) with two `<select>`s (city, category) and an htmx chat panel mirrors the existing `locations.html`/`categories.html` + `ai_chat.html` patterns.

**Tech Stack:** FastAPI, SQLModel (SQLite), Jinja2, htmx 1.9.12 — all already in use, no new dependencies.

## Global Constraints

- `SQLModel.metadata.create_all(engine)` (in `app/db.py`) only creates missing tables; it never alters existing ones. The two new tables must be plain new `SQLModel` classes with `table=True` — never add columns to `AiSession`/`AiMessage`.
- Assistant chat content is plain text, never JSON, in the new `AskMessage` table (unlike `AiMessage`, which stores JSON for assistant turns in the categorization flow).
- No markdown rendering of AI answers — Jinja's default autoescaping is relied upon for XSS safety, same as every other template in this codebase.
- All user-facing strings are in Italian, matching the rest of the app.
- Reuse `AIProvider.call_json` as-is; do not add a new method to `app/ai/providers/base.py` or either provider implementation.
- Reel context passed to the AI is capped at `MAX_REELS_IN_CONTEXT = 150` reels (oldest-first), with an explicit truncation note in the prompt when exceeded.

---

### Task 1: `AskSession` / `AskMessage` models

**Files:**
- Modify: `app/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `AskSession(id: str, location_id: Optional[str], category_key: Optional[str], created_at: datetime, updated_at: datetime)` and `AskMessage(id: str, session_id: str, role: str, content: str, created_at: datetime)`, both `SQLModel` tables, used by every later task.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py` (after `test_create_ai_session_with_messages`):

```python
def test_create_ask_session_with_messages():
    from app.models import AskMessage, AskSession

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
        session.add(hub)
        session.commit()
        session.refresh(hub)

        ask_session = AskSession(location_id=hub.id, category_key="food")
        session.add(ask_session)
        session.commit()
        session.refresh(ask_session)

        session.add(AskMessage(session_id=ask_session.id, role="user", content="Cosa mi consigli?"))
        session.commit()

        messages = session.exec(
            select(AskMessage).where(AskMessage.session_id == ask_session.id)
        ).all()
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert ask_session.location_id == hub.id
        assert ask_session.category_key == "food"


def test_create_ask_session_with_no_scope():
    from app.models import AskSession

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        ask_session = AskSession()
        session.add(ask_session)
        session.commit()
        session.refresh(ask_session)

        assert ask_session.location_id is None
        assert ask_session.category_key is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v -k ask_session`
Expected: FAIL with `ImportError: cannot import name 'AskSession'` (or `AskMessage`)

- [ ] **Step 3: Add the models**

In `app/models.py`, after the `AiMessage` class (currently the last class in the file), add:

```python
class AskSession(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    location_id: Optional[str] = Field(default=None, foreign_key="location.id")
    category_key: Optional[str] = Field(default=None, foreign_key="category.key")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AskMessage(SQLModel, table=True):
    id: str = Field(default_factory=new_uuid, primary_key=True)
    session_id: str = Field(foreign_key="asksession.id")
    role: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v -k ask_session`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: add AskSession/AskMessage models for the reel-search chat"
```

---

### Task 2: Prompt builder for the ask chat

**Files:**
- Modify: `app/ai/prompts.py`
- Test: `tests/test_ai_prompts.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `MAX_REELS_IN_CONTEXT: int`, `build_ask_response_schema() -> dict`, `build_ask_system_prompt(reels: list[dict], location_name: Optional[str], category_label: Optional[str], truncated: bool) -> str`. Each `reels` entry is a dict with keys `place_name: str`, `categories: list[str]`, `note: str`, `link: str`. Used by Task 3 (`ai.client.ask`) and Task 4 (router).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ai_prompts.py`:

```python
from app.ai.prompts import build_ask_response_schema, build_ask_system_prompt

SAMPLE_REELS = [
    {"place_name": "Ichiran Ramen", "categories": ["Cibo"], "note": "Ramen famoso", "link": "https://instagram.com/reel/abc"},
    {"place_name": "Nikko", "categories": ["Natura", "Cultura"], "note": "", "link": "https://instagram.com/reel/def"},
]


def test_ask_response_schema_requires_answer_only():
    schema = build_ask_response_schema()
    assert schema["properties"] == {"answer": {"type": "string"}}
    assert schema["required"] == ["answer"]
    assert schema["additionalProperties"] is False


def test_ask_system_prompt_includes_reel_place_names_and_links():
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", None, False)
    assert "Ichiran Ramen" in prompt
    assert "Nikko" in prompt
    assert "https://instagram.com/reel/abc" in prompt
    assert "https://instagram.com/reel/def" in prompt


def test_ask_system_prompt_mentions_active_city_and_category_filter():
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", "Cibo", False)
    assert "Tokyo / Kanto" in prompt
    assert "Cibo" in prompt


def test_ask_system_prompt_states_no_filter_when_both_are_none():
    prompt = build_ask_system_prompt(SAMPLE_REELS, None, None, False)
    assert "nessun filtro" in prompt.lower()


def test_ask_system_prompt_states_no_reels_when_list_is_empty():
    prompt = build_ask_system_prompt([], "Osaka", None, False)
    assert "nessun reel" in prompt.lower()


def test_ask_system_prompt_warns_about_truncation_when_flagged():
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", None, True)
    assert "parziale" in prompt.lower()


def test_ask_system_prompt_omits_truncation_warning_when_not_flagged():
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", None, False)
    assert "parziale" not in prompt.lower()


def test_ask_system_prompt_prioritizes_saved_reels_over_web_search():
    prompt = build_ask_system_prompt(SAMPLE_REELS, "Tokyo / Kanto", None, False)
    assert "priorita" in prompt.lower()
    assert "web" in prompt.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_prompts.py -v -k ask_`
Expected: FAIL with `ImportError: cannot import name 'build_ask_response_schema'`

- [ ] **Step 3: Implement the prompt builders**

In `app/ai/prompts.py`, add `Optional` to the existing `from typing import Iterable` import line (making it `from typing import Iterable, Optional`), then append at the end of the file:

```python
MAX_REELS_IN_CONTEXT = 150


def build_ask_response_schema() -> dict:
    return {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }


def build_ask_system_prompt(
    reels: list[dict],
    location_name: Optional[str],
    category_label: Optional[str],
    truncated: bool,
) -> str:
    scope_parts = []
    if location_name:
        scope_parts.append(f"citta': {location_name}")
    if category_label:
        scope_parts.append(f"categoria: {category_label}")
    scope = ", ".join(scope_parts) if scope_parts else "nessun filtro (tutte le citta' e tutte le categorie)"

    if reels:
        lines = []
        for r in reels:
            categories = ", ".join(r["categories"]) if r["categories"] else "senza categoria"
            note = r["note"] or "(nessuna nota)"
            lines.append(f"- {r['place_name']} -- {categories} -- {note} ({r['link']})")
        reels_block = "\n".join(lines)
    else:
        reels_block = "Nessun reel salvato corrisponde a questo filtro."

    truncation_note = (
        " L'elenco qui sotto e' parziale: ci sono altri reel salvati che corrispondono al filtro ma non "
        "sono stati inclusi per limiti di spazio; non assumere che sia completo."
        if truncated else ""
    )

    return (
        "Sei un assistente che aiuta l'utente a consultare e progettare un viaggio in Giappone usando "
        "i reel Instagram che ha gia' salvato e categorizzato in questa app. "
        f"Il filtro attivo e': {scope}.{truncation_note} "
        "Questi sono i reel salvati che corrispondono al filtro, uno per riga "
        "(luogo -- categorie -- nota (link)):\n"
        f"{reels_block}\n"
        "Rispondi basandoti PRIORITARIAMENTE su questi reel salvati: sono la fonte di verita' su cosa "
        "l'utente ha gia' trovato e vuole fare. Puoi usare la ricerca web solo per completare informazioni "
        "che non sono nei reel salvati (per esempio orari di apertura aggiornati o novita' recenti), ma "
        "dai sempre priorita' e maggior peso a quanto riportato nei reel salvati rispetto a quanto trovi "
        "sul web, e segnala chiaramente quando un'informazione viene dal web e non dai reel dell'utente. "
        "Se non ci sono reel che corrispondono al filtro, dillo esplicitamente invece di inventare contenuti. "
        "Rispondi in italiano, in prosa semplice, seguendo esattamente lo schema JSON fornito."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_prompts.py -v -k ask_`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add app/ai/prompts.py tests/test_ai_prompts.py
git commit -m "feat: add system prompt and schema builders for the ask chat"
```

---

### Task 3: `ai_client.ask()`

**Files:**
- Modify: `app/ai/client.py`
- Test: `tests/test_ai_client.py`

**Interfaces:**
- Consumes: `build_ask_response_schema`, `build_ask_system_prompt` from Task 2; `get_provider().call_json(system, messages, schema, enable_web_search)` (existing).
- Produces: `ask(reels: list[dict], location_name: Optional[str], category_label: Optional[str], truncated: bool, messages: list[dict[str, str]]) -> dict[str, Any]`, returning `{"answer": "..."}`. Used by Task 4.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ai_client.py`:

```python
def test_ask_delegates_to_provider_with_built_prompt_and_schema(monkeypatch):
    expected = {"answer": "Ti consiglio Ichiran Ramen."}
    fake_provider = FakeProvider(expected)
    monkeypatch.setattr(ai_client, "get_provider", lambda: fake_provider)

    reels = [{"place_name": "Ichiran Ramen", "categories": ["Cibo"], "note": "", "link": "https://instagram.com/reel/abc"}]
    result = ai_client.ask(reels, "Tokyo / Kanto", "Cibo", False, [{"role": "user", "content": "Dove mangio?"}])

    assert result == expected
    call = fake_provider.calls[0]
    assert call["enable_web_search"] is True
    assert call["messages"] == [{"role": "user", "content": "Dove mangio?"}]
    assert "Ichiran Ramen" in call["system"]
    assert call["schema"]["properties"] == {"answer": {"type": "string"}}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_client.py -v -k test_ask_delegates`
Expected: FAIL with `AttributeError: module 'app.ai.client' has no attribute 'ask'`

- [ ] **Step 3: Implement `ask()`**

In `app/ai/client.py`, update the import block at the top to also pull in the new builders and `Optional`:

```python
import logging
import os
from typing import Any, Optional

from app.ai.prompts import (
    build_ask_response_schema,
    build_ask_system_prompt,
    build_places_response_schema,
    build_places_system_prompt,
    build_response_schema,
    build_system_prompt,
)
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.base import AIProvider
from app.ai.providers.openai_provider import OpenAIProvider
```

Then append at the end of the file:

```python
def ask(
    reels: list[dict[str, Any]],
    location_name: Optional[str],
    category_label: Optional[str],
    truncated: bool,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    system = build_ask_system_prompt(reels, location_name, category_label, truncated)
    schema = build_ask_response_schema()
    logger.debug(
        "ask request location_name=%s category_label=%s truncated=%s messages=%s",
        location_name, category_label, truncated, messages,
    )
    return get_provider().call_json(system, messages, schema, enable_web_search=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_client.py -v -k test_ask_delegates`
Expected: 1 passed

- [ ] **Step 5: Run the full client test file to check for regressions**

Run: `uv run pytest tests/test_ai_client.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add app/ai/client.py tests/test_ai_client.py
git commit -m "feat: add ai_client.ask() for the reel-search chat"
```

---

### Task 4: Router core — reel scoping, session turn, GET panel

**Files:**
- Create: `app/routers/ai_ask.py`
- Test: `tests/test_ai_ask.py`

**Interfaces:**
- Consumes: `app.models.AskSession`, `app.models.AskMessage` (Task 1); `app.ai.client.ask` (Task 3); `app.routers.categories.get_taxonomy`; `app.routers.reels._location_and_satellite_ids` (existing, already cross-imported by `ai_categorize.py`); `app.ai.providers.base.AIProviderError`.
- Produces: `ui_router = APIRouter(prefix="/ui/ask", tags=["ask-ui"])` with `GET /panel`; helper functions `_scoped_reel_context(session, location_id, category_key) -> tuple[list[dict], bool]`, `_build_ask_chat_context(session, ask_session_id, location_id, category_key, notice=None) -> dict`, `_run_ask_turn(session, session_id, location_id, category_key, message) -> AskSession` — all consumed by Task 5 (same file) and registered in Task 6 (`main.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ai_ask.py`:

```python
from sqlmodel import select

from app.ai import client as ai_client
from app.ai.providers.base import AIProviderError
from app.models import AskMessage, AskSession, Category, Location, Reel, ReelType
from app.routers.ai_ask import _build_ask_chat_context, _run_ask_turn, _scoped_reel_context


def test_scoped_reel_context_filters_by_city_and_includes_satellites(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    satellite = Location(name="Nikko", is_hub=False, parent_id=hub.id)
    other_hub = Location(name="Osaka", is_hub=True)
    session.add(satellite)
    session.add(other_hub)
    session.commit()
    session.refresh(satellite)
    session.refresh(other_hub)

    session.add(Reel(link="https://instagram.com/reel/1", location_id=hub.id, note="Ramen"))
    session.add(Reel(link="https://instagram.com/reel/2", location_id=satellite.id, note="Shrine"))
    session.add(Reel(link="https://instagram.com/reel/3", location_id=other_hub.id, note="Takoyaki"))
    session.commit()

    entries, truncated = _scoped_reel_context(session, hub.id, None)

    assert truncated is False
    assert {e["place_name"] for e in entries} == {"Tokyo / Kanto", "Nikko"}


def test_scoped_reel_context_filters_by_category(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.add(Category(key="nature", label="Natura", icon="🌸", color="#7A8F5E"))
    session.commit()
    session.refresh(hub)

    food_reel = Reel(link="https://instagram.com/reel/1", location_id=hub.id, note="Ramen")
    nature_reel = Reel(link="https://instagram.com/reel/2", location_id=hub.id, note="Park")
    session.add(food_reel)
    session.add(nature_reel)
    session.commit()
    session.refresh(food_reel)
    session.refresh(nature_reel)
    session.add(ReelType(reel_id=food_reel.id, type="food"))
    session.add(ReelType(reel_id=nature_reel.id, type="nature"))
    session.commit()

    entries, _ = _scoped_reel_context(session, hub.id, "food")

    assert len(entries) == 1
    assert entries[0]["note"] == "Ramen"
    assert entries[0]["categories"] == ["Cibo"]


def test_scoped_reel_context_with_no_filters_returns_all_reels(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    other_hub = Location(name="Osaka", is_hub=True)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    session.add(Reel(link="https://instagram.com/reel/1", location_id=hub.id))
    session.add(Reel(link="https://instagram.com/reel/2", location_id=other_hub.id))
    session.commit()

    entries, truncated = _scoped_reel_context(session, None, None)

    assert len(entries) == 2
    assert truncated is False


def test_scoped_reel_context_truncates_beyond_max_and_flags_it(session, monkeypatch):
    import app.routers.ai_ask as ai_ask_module

    monkeypatch.setattr(ai_ask_module, "MAX_REELS_IN_CONTEXT", 2)
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)
    for i in range(3):
        session.add(Reel(link=f"https://instagram.com/reel/{i}", location_id=hub.id))
    session.commit()

    entries, truncated = _scoped_reel_context(session, hub.id, None)

    assert len(entries) == 2
    assert truncated is True


def test_run_ask_turn_creates_session_with_scope_and_calls_ai(session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    captured = {}

    def fake_ask(reels, location_name, category_label, truncated, messages):
        captured["location_name"] = location_name
        return {"answer": "Ti consiglio di andare a Tokyo."}

    monkeypatch.setattr(ai_client, "ask", fake_ask)

    ask_session = _run_ask_turn(session, None, hub.id, None, "Cosa mi consigli?")

    assert ask_session.location_id == hub.id
    assert captured["location_name"] == "Tokyo / Kanto"
    messages = session.exec(
        select(AskMessage).where(AskMessage.session_id == ask_session.id).order_by(AskMessage.created_at)
    ).all()
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].content == "Ti consiglio di andare a Tokyo."


def test_run_ask_turn_continuing_session_ignores_resubmitted_scope(session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    other_hub = Location(name="Osaka", is_hub=True)
    session.add(hub)
    session.add(other_hub)
    session.commit()
    session.refresh(hub)
    session.refresh(other_hub)

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "ok"})
    ask_session = _run_ask_turn(session, None, hub.id, None, "Prima domanda")

    captured = {}

    def fake_ask(reels, location_name, category_label, truncated, messages):
        captured["location_name"] = location_name
        return {"answer": "seconda risposta"}

    monkeypatch.setattr(ai_client, "ask", fake_ask)
    # location_id passed here (other_hub.id) must be ignored in favor of the
    # session's own stored scope (hub.id), since the reel context must stay
    # consistent with what the first turn's answer was based on.
    _run_ask_turn(session, ask_session.id, other_hub.id, None, "Seconda domanda")

    assert captured["location_name"] == "Tokyo / Kanto"


def test_run_ask_turn_with_unknown_session_id_raises_404(session):
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc_info:
        _run_ask_turn(session, "does-not-exist", None, None, "Ciao")
    assert exc_info.value.status_code == 404


def test_run_ask_turn_falls_back_to_friendly_answer_on_provider_error(session, monkeypatch):
    def boom(*a, **k):
        raise AIProviderError("boom")

    monkeypatch.setattr(ai_client, "ask", boom)

    ask_session = _run_ask_turn(session, None, None, None, "Qualcosa")

    messages = session.exec(
        select(AskMessage).where(AskMessage.session_id == ask_session.id).order_by(AskMessage.created_at)
    ).all()
    assert "riprova" in messages[1].content.lower()


def test_build_ask_chat_context_with_no_session_has_empty_history(session):
    context = _build_ask_chat_context(session, None, None, None)
    assert context["history"] == []
    assert context["session_id"] == ""


def test_build_ask_chat_context_with_session_includes_history(session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "risposta"})
    ask_session = _run_ask_turn(session, None, None, None, "domanda")

    context = _build_ask_chat_context(session, ask_session.id, None, None)

    assert context["session_id"] == ask_session.id
    assert [h["role"] for h in context["history"]] == ["user", "assistant"]
    assert context["history"][0]["text"] == "domanda"
    assert context["history"][1]["text"] == "risposta"


def test_ui_ask_panel_renders_empty_state(client):
    response = client.get("/ui/ask/panel")
    assert response.status_code == 200
    assert 'name="message"' in response.text
    assert 'name="location_id"' in response.text
    assert 'name="category_key"' in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_ask.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.routers.ai_ask'`

- [ ] **Step 3: Implement `app/routers/ai_ask.py`**

Create `app/routers/ai_ask.py`:

```python
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from app.ai import client as ai_client
from app.ai.prompts import MAX_REELS_IN_CONTEXT
from app.ai.providers.base import AIProviderError
from app.db import get_session
from app.models import AskMessage, AskSession, Location, Reel, ReelType
from app.routers.categories import get_taxonomy
from app.routers.reels import _location_and_satellite_ids
from app.web import templates

ui_router = APIRouter(prefix="/ui/ask", tags=["ask-ui"])

logger = logging.getLogger("app.ai")

FALLBACK_ANSWER = "Errore nel contattare l'assistente, riprova."


def _scoped_reel_context(
    session: Session, location_id: Optional[str], category_key: Optional[str]
) -> tuple[list[dict], bool]:
    query = select(Reel)
    if location_id is not None:
        query = query.where(Reel.location_id.in_(_location_and_satellite_ids(session, location_id)))
    reels = session.exec(query.order_by(Reel.created_at)).all()

    if category_key is not None:
        matching_ids = set(
            session.exec(select(ReelType.reel_id).where(ReelType.type == category_key)).all()
        )
        reels = [r for r in reels if r.id in matching_ids]

    taxonomy = get_taxonomy(session)
    entries = []
    for r in reels:
        location = session.get(Location, r.location_id)
        type_keys = session.exec(select(ReelType.type).where(ReelType.reel_id == r.id)).all()
        entries.append({
            "place_name": location.name if location else "?",
            "categories": [taxonomy[t]["label"] for t in type_keys if t in taxonomy],
            "note": r.note or "",
            "link": r.link,
        })

    truncated = len(entries) > MAX_REELS_IN_CONTEXT
    return entries[:MAX_REELS_IN_CONTEXT], truncated


def _run_ask_turn(
    session: Session,
    session_id: Optional[str],
    location_id: Optional[str],
    category_key: Optional[str],
    message: str,
) -> AskSession:
    if session_id:
        ask_session = session.get(AskSession, session_id)
        if ask_session is None:
            raise HTTPException(status_code=404, detail="Ask session not found")
        location_id = ask_session.location_id
        category_key = ask_session.category_key
    else:
        ask_session = AskSession(location_id=location_id, category_key=category_key)
        session.add(ask_session)
        session.commit()
        session.refresh(ask_session)

    session.add(AskMessage(session_id=ask_session.id, role="user", content=message))
    session.commit()

    history = session.exec(
        select(AskMessage).where(AskMessage.session_id == ask_session.id).order_by(AskMessage.created_at)
    ).all()
    api_messages = [{"role": m.role, "content": m.content} for m in history]

    reels, truncated = _scoped_reel_context(session, location_id, category_key)
    location = session.get(Location, location_id) if location_id else None
    location_name = location.name if location else None
    taxonomy = get_taxonomy(session)
    category_label = taxonomy[category_key]["label"] if category_key and category_key in taxonomy else None

    try:
        result = ai_client.ask(reels, location_name, category_label, truncated, api_messages)
        answer = result["answer"]
    except (AIProviderError, RuntimeError):
        logger.exception("ask_session=%s ask call failed", ask_session.id)
        answer = FALLBACK_ANSWER

    session.add(AskMessage(session_id=ask_session.id, role="assistant", content=answer))
    session.commit()

    return ask_session


def _build_ask_chat_context(
    session: Session,
    ask_session_id: Optional[str],
    location_id: Optional[str],
    category_key: Optional[str],
    notice: Optional[str] = None,
) -> dict:
    history: list[dict] = []
    if ask_session_id:
        messages = session.exec(
            select(AskMessage).where(AskMessage.session_id == ask_session_id).order_by(AskMessage.created_at)
        ).all()
        history = [{"role": m.role, "text": m.content} for m in messages]

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

Note: `Location.is_hub == True` matches the exact pattern already used in `app/routers/ai_categorize.py:_find_hub_by_name` — SQLModel/SQLAlchemy requires `== True`, not `is True`, for the generated SQL comparison.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_ask.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add app/routers/ai_ask.py tests/test_ai_ask.py
git commit -m "feat: add ai_ask router core (reel scoping, session turn, GET panel)"
```

---

### Task 5: `POST /ui/ask/message`

**Files:**
- Modify: `app/routers/ai_ask.py`
- Test: `tests/test_ai_ask.py`

**Interfaces:**
- Consumes: `_run_ask_turn`, `_build_ask_chat_context` (Task 4).
- Produces: `POST /ui/ask/message` on `ui_router`, consumed by the template built in Task 6.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ai_ask.py`:

```python
def test_ui_ask_message_first_turn_creates_session_and_shows_answer(client, session, monkeypatch):
    hub = Location(name="Tokyo / Kanto", is_hub=True)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "Ti consiglio Ichiran Ramen."})

    response = client.post(
        "/ui/ask/message",
        data={"location_id": hub.id, "category_key": "", "message": "Dove mangio?"},
    )
    assert response.status_code == 200
    assert "Ti consiglio Ichiran Ramen." in response.text
    assert session.exec(select(AskSession)).first() is not None


def test_ui_ask_message_continues_existing_session(client, session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "prima risposta"})
    first = client.post("/ui/ask/message", data={"location_id": "", "category_key": "", "message": "ciao"})
    assert "prima risposta" in first.text
    session_id = session.exec(select(AskSession)).first().id

    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "seconda risposta"})
    second = client.post(
        "/ui/ask/message",
        data={"session_id": session_id, "location_id": "", "category_key": "", "message": "e poi?"},
    )
    assert second.status_code == 200
    assert "prima risposta" in second.text
    assert "seconda risposta" in second.text


def test_ui_ask_message_with_unknown_session_id_resets_panel_with_notice(client, session):
    response = client.post(
        "/ui/ask/message",
        data={"session_id": "does-not-exist", "location_id": "", "category_key": "", "message": "Ciao"},
    )
    assert response.status_code == 200
    assert 'name="message"' in response.text
    assert "Sessione scaduta" in response.text


def test_ui_ask_message_shows_friendly_error_when_ai_call_fails(client, session, monkeypatch):
    def boom(*a, **k):
        raise AIProviderError("boom")

    monkeypatch.setattr(ai_client, "ask", boom)

    response = client.post(
        "/ui/ask/message", data={"location_id": "", "category_key": "", "message": "Qualcosa"}
    )
    assert response.status_code == 200
    assert "riprova" in response.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ai_ask.py -v -k ui_ask_message`
Expected: FAIL (404 Not Found — route doesn't exist yet) since the template from Task 6 doesn't exist either; at this point it's fine for it to fail on a missing-template error too — the goal here is `POST /ui/ask/message` being unrouted (405/404)

- [ ] **Step 3: Implement the endpoint**

In `app/routers/ai_ask.py`, change the top import line from:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
```

to:

```python
from fastapi import APIRouter, Depends, Form, HTTPException, Request
```

Then append at the end of the file:

```python
@ui_router.post("/message")
def ui_ask_message(
    request: Request,
    session_id: str = Form(""),
    location_id: str = Form(""),
    category_key: str = Form(""),
    message: str = Form(...),
    session: Session = Depends(get_session),
):
    try:
        ask_session = _run_ask_turn(
            session, session_id or None, location_id or None, category_key or None, message
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            context = _build_ask_chat_context(
                session, None, location_id or None, category_key or None,
                notice="Sessione scaduta, ricomincia pure da qui.",
            )
            return templates.TemplateResponse(request, "partials/ask_chat.html", context)
        raise

    return templates.TemplateResponse(
        request,
        "partials/ask_chat.html",
        _build_ask_chat_context(session, ask_session.id, ask_session.location_id, ask_session.category_key),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ai_ask.py -v`
Expected: all passed (this exercises the real `partials/ask_chat.html` template, which doesn't exist until Task 6 — if these fail with a `TemplateNotFound` error, that is expected and will be resolved by Task 6; re-run after Task 6's Step 4 to confirm green)

- [ ] **Step 5: Commit**

```bash
git add app/routers/ai_ask.py tests/test_ai_ask.py
git commit -m "feat: add POST /ui/ask/message endpoint"
```

---

### Task 6: Templates, page route, nav entry, CSS

**Files:**
- Create: `app/templates/ask.html`
- Create: `app/templates/partials/ask_chat.html`
- Modify: `app/templates/base.html`
- Modify: `app/main.py`
- Modify: `app/static/css/style.css`
- Test: `tests/test_ai_ask.py`, new `tests/test_ask_page.py`

**Interfaces:**
- Consumes: `ui_router` from `app/routers/ai_ask.py` (Tasks 4-5); context keys produced by `_build_ask_chat_context`: `session_id`, `location_id`, `category_key`, `hubs` (list of `Location`), `taxonomy` (dict), `history` (list of `{role, text}`), `notice`.
- Produces: `GET /ask` page; nav link `<a href="/ask">Chiedi all'AI</a>` in every page via `base.html`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ask_page.py`:

```python
def test_ask_page_renders(client):
    response = client.get("/ask")
    assert response.status_code == 200
    assert 'id="ask-chat-panel"' in response.text


def test_nav_includes_ask_link(client):
    response = client.get("/")
    assert 'href="/ask"' in response.text
```

Add to `tests/test_ai_ask.py` (now that the template will exist, these pin its actual rendered shape):

```python
def test_ui_ask_panel_lists_hubs_and_categories(client, session):
    session.add(Location(name="Tokyo / Kanto", is_hub=True))
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()

    response = client.get("/ui/ask/panel")
    assert "Tokyo / Kanto" in response.text
    assert "Cibo" in response.text
    assert "Tutte le citt" in response.text
    assert "Tutte le categorie" in response.text


def test_ui_ask_message_response_includes_filter_selects_for_next_turn(client, session, monkeypatch):
    monkeypatch.setattr(ai_client, "ask", lambda *a, **k: {"answer": "ok"})

    response = client.post(
        "/ui/ask/message", data={"location_id": "", "category_key": "", "message": "ciao"}
    )
    assert 'name="location_id"' in response.text
    assert 'name="category_key"' in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ask_page.py tests/test_ai_ask.py -v`
Expected: FAIL — `/ask` returns 404, `/ui/ask/panel` raises `TemplateNotFound: partials/ask_chat.html`

- [ ] **Step 3: Create `app/templates/partials/ask_chat.html`**

```html
{% if notice %}
<p class="ai-notice">{{ notice }}</p>
{% endif %}
<div class="ask-filters" id="ask-filters">
    <select name="location_id" hx-get="/ui/ask/panel" hx-target="#ask-chat-panel" hx-swap="innerHTML" hx-include="#ask-filters">
        <option value="" {% if not location_id %}selected{% endif %}>Tutte le città</option>
        {% for hub in hubs %}
        <option value="{{ hub.id }}" {% if location_id == hub.id %}selected{% endif %}>{{ hub.name }}</option>
        {% endfor %}
    </select>
    <select name="category_key" hx-get="/ui/ask/panel" hx-target="#ask-chat-panel" hx-swap="innerHTML" hx-include="#ask-filters">
        <option value="" {% if not category_key %}selected{% endif %}>Tutte le categorie</option>
        {% for key, info in taxonomy.items() %}
        <option value="{{ key }}" {% if category_key == key %}selected{% endif %}>{{ info.icon }} {{ info.label }}</option>
        {% endfor %}
    </select>
    <button type="button" hx-get="/ui/ask/panel" hx-target="#ask-chat-panel" hx-swap="innerHTML" hx-include="#ask-filters">Nuova conversazione</button>
</div>

<div id="ask-chat-messages">
    {% for turn in history %}
    <div class="chat-bubble {{ turn.role }}">{{ turn.text }}</div>
    {% endfor %}
</div>

<form hx-post="/ui/ask/message" hx-target="#ask-chat-panel" hx-swap="innerHTML" hx-include="#ask-filters" hx-indicator="#ask-send-indicator" class="ai-input-form">
    <input type="hidden" name="session_id" value="{{ session_id }}">
    <textarea name="message" placeholder="Scrivi..." required></textarea>
    <button type="submit">Invia</button>
    <span id="ask-send-indicator" class="htmx-indicator">Invio in corso…</span>
</form>
```

- [ ] **Step 4: Create `app/templates/ask.html`**

```html
{% extends "base.html" %}
{% block content %}
<section id="ask-chat-panel" hx-get="/ui/ask/panel" hx-trigger="load" hx-swap="innerHTML">
    <p>Caricamento assistente...</p>
</section>
{% endblock %}
```

- [ ] **Step 5: Wire the `/ask` page route and router registration in `app/main.py`**

In `app/main.py`, update the router import line:

```python
from app.routers import ai_ask, ai_categorize, ai_multi_categorize, auth, categories, instagram_import, locations, map as map_router, reels
```

Add the router registration next to the other `ai_categorize` ones (after `app.include_router(ai_categorize.ui_router)`):

```python
app.include_router(ai_ask.ui_router)
```

Add the page route next to `locations_page`:

```python
@app.get("/ask")
async def ask_page(request: Request):
    return templates.TemplateResponse(request, "ask.html", {})
```

- [ ] **Step 6: Add the nav link in `app/templates/base.html`**

Change:

```html
            <a href="/locations">Gestisci hub</a>
            <a href="/logout">Logout</a>
```

to:

```html
            <a href="/locations">Gestisci hub</a>
            <a href="/ask">Chiedi all'AI</a>
            <a href="/logout">Logout</a>
```

- [ ] **Step 7: Preserve line breaks in chat bubbles — `app/static/css/style.css`**

Change the existing `.chat-bubble` rule:

```css
.chat-bubble {
    padding: 0.5rem 0.75rem;
    border-radius: 14px;
    max-width: 80%;
    line-height: 1.4;
}
```

to:

```css
.chat-bubble {
    padding: 0.5rem 0.75rem;
    border-radius: 14px;
    max-width: 80%;
    line-height: 1.4;
    white-space: pre-wrap;
}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_ask_page.py tests/test_ai_ask.py -v`
Expected: all passed

- [ ] **Step 9: Run the full test suite to check for regressions**

Run: `uv run pytest -v`
Expected: all passed (in particular `tests/test_ai_ui.py`, `tests/test_index_page.py`, `tests/test_ai_categorize.py` must be unaffected)

- [ ] **Step 10: Manually verify in the browser**

Run: `uv run uvicorn app.main:app --reload` (or the project's usual dev-server command), then in a browser:
1. Log in, click "Chiedi all'AI" in the nav.
2. Confirm the page loads with "Tutte le città" / "Tutte le categorie" selected and an empty chat.
3. Pick a city that has reels, ask a question, confirm an answer appears as a chat bubble.
4. Ask a follow-up question, confirm both turns remain visible.
5. Change the city select, confirm the chat resets to empty.
6. Click "Nuova conversazione", confirm the chat resets without changing the selects.

- [ ] **Step 11: Commit**

```bash
git add app/templates/ask.html app/templates/partials/ask_chat.html app/templates/base.html app/main.py app/static/css/style.css tests/test_ask_page.py tests/test_ai_ask.py
git commit -m "feat: add /ask page, nav entry, and chat template for the reel-search chat"
```

---

## Self-review notes

- Spec coverage: data model (Task 1), reel retrieval + prompt/schema (Tasks 2, 4), `ask()` client call reusing `call_json` (Task 3), routing incl. session-expired/empty-reel/provider-error handling (Tasks 4-5), page/nav/UI incl. filter-change-resets-conversation behavior (Task 6) — all covered.
- No placeholders: every step has concrete code and exact assertions.
- Type/name consistency checked: `_scoped_reel_context`, `_run_ask_turn`, `_build_ask_chat_context` signatures match across Tasks 4-6; `ai_client.ask(reels, location_name, category_label, truncated, messages)` parameter order matches between Task 3's definition and Task 4's call site.
