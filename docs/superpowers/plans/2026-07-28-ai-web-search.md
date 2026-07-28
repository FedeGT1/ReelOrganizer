# AI Web Search for Location Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the AI reel-categorization assistant use Anthropic's server-side web search tool to locate real-world places named in a reel caption (e.g. "the world's first dedicated Dragon Ball store") when it can't place them from its own knowledge, and present a clickable disambiguation list when search finds more than one plausible match.

**Architecture:** Additive changes to the existing single-call-per-turn categorization flow. `ai_client.categorize()` gains the `web_search` server-side tool alongside the existing `output_config.format` JSON schema (these compose in one API call — no client-side tool-execution loop needed). The response schema gains one new nullable field, `candidates` (array of short strings), populated only when search is ambiguous. The router's existing "ask a clarifying question" fallback gets one new guard so it doesn't fire when `candidates` is present instead. The chat template renders `candidates` as clickable chips that re-enter the exact same `/ui/ai/message` flow already used for typed replies — no new endpoint or state machine.

**Tech Stack:** FastAPI + Jinja2/HTMX (existing), `anthropic` Python SDK (existing `Anthropic().messages.create()` call in `app/ai/client.py`), pytest with `monkeypatch` (existing test pattern — `ai_client.categorize` is mocked at the router boundary in router/UI tests; only `tests/test_ai_client.py` exercises the real Anthropic call shape via a fake SDK client).

## Global Constraints

- All user-facing strings are Italian, matching the existing tone (see `MISSING_COORDINATES_QUESTION` and the system prompt in `app/ai/prompts.py` for style reference).
- The AI response schema keeps every field in `required` (nullable via `["type", "null"]`) with `additionalProperties: False` — the existing strict-schema pattern in `app/ai/prompts.py`. The new `candidates` field follows this exactly: `{"type": ["array", "null"], "items": {"type": "string"}}`.
- Use the `web_search_20250305` (basic) server-side tool type, not the newer `web_search_20260209` dynamic-filtering variant — the app's model is `claude-haiku-4-5`, which is not in `web_search_20260209`'s documented supported-model list (Opus 4.6+, Sonnet 4.6+), while the basic variant is broadly supported.
- Reuse the existing `.chip` CSS class (`app/static/css/style.css`) for candidate buttons — do not invent a new button style.
- Router/UI tests mock `ai_client.categorize` via `monkeypatch.setattr(ai_client, "categorize", ...)`, exactly as every existing test in `tests/test_ai_categorize.py` and `tests/test_ai_ui.py` does. Do not make real Anthropic API calls in tests.

---

### Task 1: Add `candidates` field to the AI response schema and update the system prompt

**Files:**
- Modify: `app/ai/prompts.py`
- Test: `tests/test_ai_prompts.py`

**Interfaces:**
- Produces: `build_response_schema(...)` now includes a `"candidates"` key in both `properties` and `required`. `build_system_prompt(...)` now instructs the model to search the web as a fallback and to use the `candidates` field for ambiguous search results. Both functions keep their existing signatures — no caller changes needed in this task.

- [ ] **Step 1: Write the failing tests**

Replace the existing `test_response_schema_has_required_fields` test and add three new tests to `tests/test_ai_prompts.py` (insert after the existing imports/constants, replacing the function of the same name and adding the new ones after `test_response_schema_types_items_are_constrained_to_the_given_types`):

```python
def test_response_schema_has_required_fields():
    schema = build_response_schema(VALID_TYPES)
    assert schema["required"] == [
        "place_name", "near_hub", "types", "note", "confidence", "question",
        "lat", "lon", "candidates",
    ]
    assert schema["additionalProperties"] is False


def test_response_schema_candidates_is_nullable_array_of_strings():
    schema = build_response_schema(VALID_TYPES)
    assert schema["properties"]["candidates"] == {
        "type": ["array", "null"],
        "items": {"type": "string"},
    }
```

Add these two after `test_build_system_prompt_pushes_for_approximate_estimate_over_hedging`:

```python
def test_build_system_prompt_instructs_web_search_before_asking_user():
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    assert "cerca" in prompt.lower()


def test_build_system_prompt_explains_candidates_field_for_ambiguous_search():
    prompt = build_system_prompt(["Tokyo / Kanto"], CATEGORIES)
    assert "candidates" in prompt
    assert "question" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_prompts.py -v`
Expected: `test_response_schema_has_required_fields` FAILs (missing `"candidates"` in the required list), `test_response_schema_candidates_is_nullable_array_of_strings` FAILs with `KeyError: 'candidates'`, and `test_build_system_prompt_instructs_web_search_before_asking_user` FAILs (no "cerca" in prompt).

- [ ] **Step 3: Implement the schema and prompt changes**

Replace the full contents of `app/ai/prompts.py` with:

```python
from typing import Iterable


def build_response_schema(valid_type_keys: Iterable[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "place_name": {"type": "string"},
            "near_hub": {"type": ["string", "null"]},
            "types": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(valid_type_keys)},
            },
            "note": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "question": {"type": ["string", "null"]},
            "lat": {"type": ["number", "null"]},
            "lon": {"type": ["number", "null"]},
            "candidates": {"type": ["array", "null"], "items": {"type": "string"}},
        },
        "required": [
            "place_name", "near_hub", "types", "note", "confidence", "question",
            "lat", "lon", "candidates",
        ],
        "additionalProperties": False,
    }


def build_system_prompt(hub_names: Iterable[str], categories: dict[str, str]) -> str:
    hubs_list = ", ".join(hub_names) if hub_names else "nessuno ancora"
    types_list = ", ".join(f"{key} ({label})" for key, label in categories.items())
    return (
        "Sei un assistente che aiuta a categorizzare reel Instagram salvati per un viaggio in Giappone. "
        "L'utente ti invia un link e una didascalia (o una descrizione libera) di un reel. "
        "Non puoi aprire il link: lavori solo sul testo fornito. "
        f"Le tappe principali (hub) gia' esistenti sono: {hubs_list}. "
        "Se il testo corrisponde chiaramente a un hub esistente o a una localita' vicina, usa near_hub per indicarlo. "
        f"Per 'types' puoi usare esclusivamente queste chiavi esatte (in inglese, non tradurle): {types_list}. "
        "Scegli una o piu' chiavi tra queste che descrivono il contenuto del reel; non inventare altre categorie. "
        "Se non riesci a capire dalla tua sola conoscenza in che citta' o zona del Giappone si trovi il posto, "
        "prova prima a cercarlo sul web (per esempio usando il nome del negozio, locale o punto di riferimento "
        "citato nella didascalia) prima di chiedere chiarimenti all'utente. "
        "Se la ricerca produce un risultato chiaro e univoco, usalo per determinare il luogo e le coordinate "
        "esattamente come faresti con la tua conoscenza diretta. "
        "Se la ricerca produce piu' risultati plausibili e diversi tra loro, valorizza 'candidates' con un elenco "
        "breve (2-4 voci) di etichette leggibili per ciascuna opzione, per esempio 'Tokyo - Ikebukuro' oppure "
        "'Osaka - Namba'; in questo caso lascia 'question' a null e usa la tua migliore ipotesi (il primo "
        "candidato) per gli altri campi, incluse lat e lon. "
        "Se non riesci a capire nemmeno approssimativamente in che citta' o zona del Giappone si trovi il posto, "
        "neanche dopo aver cercato sul web, valorizza 'question' con una domanda di chiarimento e lascia gli altri "
        "campi con la tua migliore ipotesi; in questo caso lascia 'candidates' a null. "
        "Se il luogo proposto non corrisponde a nessun hub o tappa gia' esistente, valorizza SEMPRE anche lat e lon: "
        "basta una stima approssimativa a livello di quartiere o citta' (in gradi decimali), non serve individuare "
        "il punto esatto -- la mappa e' schematica, non geograficamente precisa. Usa la tua conoscenza generale della "
        "geografia giapponese: se nel testo compare un quartiere, un tempio, una via o un altro punto di riferimento "
        "riconoscibile (per esempio 'Asakusa', 'Senso-ji', 'Dotonbori', 'Shinjuku'), stima le coordinate di quella "
        "zona invece di lasciare i campi vuoti. Lascia lat e lon a null solo se il testo non permette di individuare "
        "nemmeno una zona approssimativa. "
        "Se il luogo corrisponde a un hub o tappa gia' esistente, puoi lasciare lat e lon a null: non verranno usate. "
        "Rispondi seguendo esattamente lo schema JSON fornito."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_prompts.py -v`
Expected: All tests PASS, including the pre-existing `test_build_system_prompt_pushes_for_approximate_estimate_over_hedging` (the "approssimativa"/"quartiere"/"Asakusa" text is preserved unchanged).

- [ ] **Step 5: Commit**

```bash
git add app/ai/prompts.py tests/test_ai_prompts.py
git commit -m "feat: add candidates field and web-search fallback instructions to AI prompt"
```

---

### Task 2: Add the web search tool and `pause_turn` resume handling to `ai_client.categorize()`

**Files:**
- Modify: `app/ai/client.py`
- Test: `tests/test_ai_client.py`

**Interfaces:**
- Consumes: `build_response_schema`/`build_system_prompt` from Task 1 (already updated; `categorize()`'s calls to them are unchanged).
- Produces: `categorize(hub_names, categories, messages) -> dict` — same public signature and return type as before. Internally now passes `tools=[{"type": "web_search_20250305", "name": "web_search"}]` to `messages.create()` and resends once if the response's `stop_reason` is `"pause_turn"`.

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_ai_client.py` with:

```python
import json
from types import SimpleNamespace

import pytest

from app.ai import client as ai_client


class FakeMessages:
    """Test double for `client.messages`. Accepts either a single
    `response_json` (existing single-turn tests) or a list of
    `{"json": ..., "stop_reason": ...}` dicts for multi-call (pause_turn
    resume) scenarios. `json: None` simulates a response with no text
    block (e.g. a paused turn that only did tool work)."""

    def __init__(self, responses=None, response_json=None):
        if responses is None:
            responses = [{"json": response_json, "stop_reason": "end_turn"}]
        self._responses = responses
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self._responses[min(len(self.calls) - 1, len(self._responses) - 1)]
        if response["json"] is None:
            content = [SimpleNamespace(type="server_tool_use", name="web_search")]
        else:
            content = [SimpleNamespace(type="text", text=json.dumps(response["json"]))]
        return SimpleNamespace(content=content, stop_reason=response["stop_reason"])

    @property
    def last_call_kwargs(self):
        return self.calls[-1] if self.calls else None


class FakeAnthropicClient:
    def __init__(self, responses=None, response_json=None):
        self.messages = FakeMessages(responses=responses, response_json=response_json)


def test_categorize_returns_parsed_json(monkeypatch):
    expected = {
        "place_name": "Ichiran Ramen",
        "near_hub": "Tokyo / Kanto",
        "types": ["food"],
        "note": "Famous ramen chain",
        "confidence": "high",
        "question": None,
    }
    fake_client = FakeAnthropicClient(response_json=expected)
    monkeypatch.setattr(ai_client, "get_client", lambda: fake_client)

    result = ai_client.categorize(
        ["Tokyo / Kanto"], {"food": "Cibo"}, [{"role": "user", "content": "Ramen a Tokyo"}]
    )

    assert result == expected
    assert fake_client.messages.last_call_kwargs["model"] == ai_client.MODEL
    assert fake_client.messages.last_call_kwargs["output_config"]["format"]["type"] == "json_schema"
    schema = fake_client.messages.last_call_kwargs["output_config"]["format"]["schema"]
    assert schema["properties"]["types"]["items"]["enum"] == ["food"]


def test_categorize_includes_web_search_tool(monkeypatch):
    fake_client = FakeAnthropicClient(response_json={
        "place_name": "Ichiran Ramen",
        "near_hub": None,
        "types": [],
        "note": "",
        "confidence": "high",
        "question": None,
    })
    monkeypatch.setattr(ai_client, "get_client", lambda: fake_client)

    ai_client.categorize(["Tokyo / Kanto"], {"food": "Cibo"}, [{"role": "user", "content": "Ramen"}])

    tools = fake_client.messages.last_call_kwargs["tools"]
    assert {"type": "web_search_20250305", "name": "web_search"} in tools


def test_categorize_resumes_once_after_pause_turn(monkeypatch):
    final_json = {
        "place_name": "Dragon Ball Store",
        "near_hub": None,
        "types": [],
        "note": "",
        "confidence": "high",
        "question": None,
    }
    fake_client = FakeAnthropicClient(responses=[
        {"json": None, "stop_reason": "pause_turn"},
        {"json": final_json, "stop_reason": "end_turn"},
    ])
    monkeypatch.setattr(ai_client, "get_client", lambda: fake_client)

    result = ai_client.categorize(
        [], {"shopping": "Shopping"}, [{"role": "user", "content": "Dragon Ball store a Tokyo"}]
    )

    assert result == final_json
    assert len(fake_client.messages.calls) == 2
    second_call_messages = fake_client.messages.calls[1]["messages"]
    assert second_call_messages[-1]["role"] == "assistant"


def test_categorize_raises_after_second_consecutive_pause_turn(monkeypatch):
    fake_client = FakeAnthropicClient(responses=[
        {"json": None, "stop_reason": "pause_turn"},
        {"json": None, "stop_reason": "pause_turn"},
    ])
    monkeypatch.setattr(ai_client, "get_client", lambda: fake_client)

    with pytest.raises(RuntimeError):
        ai_client.categorize([], {}, [{"role": "user", "content": "x"}])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_client.py -v`
Expected: `test_categorize_includes_web_search_tool` FAILs with `KeyError: 'tools'`; `test_categorize_resumes_once_after_pause_turn` and `test_categorize_raises_after_second_consecutive_pause_turn` FAIL (current code calls `next(...)` unconditionally and raises `StopIteration`, or accesses `.stop_reason` which doesn't exist yet on the code side — the current implementation doesn't loop at all).

- [ ] **Step 3: Implement the tool wiring and resume loop**

Replace the full contents of `app/ai/client.py` with:

```python
import json
import logging
import os
from typing import Any, Optional

from anthropic import Anthropic

from app.ai.prompts import build_response_schema, build_system_prompt

MODEL = "claude-haiku-4-5"
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search"}
MAX_PAUSE_TURN_RESUMES = 1

_client: Optional[Anthropic] = None

logger = logging.getLogger("app.ai")


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def categorize(
    hub_names: list[str], categories: dict[str, str], messages: list[dict[str, str]]
) -> dict[str, Any]:
    client = get_client()
    system = build_system_prompt(hub_names, categories)
    schema = build_response_schema(categories.keys())
    logger.debug("categorize request hub_names=%s categories=%s messages=%s", hub_names, categories, messages)

    current_messages = list(messages)
    resumes = 0
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            messages=current_messages,
            tools=[WEB_SEARCH_TOOL],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if response.stop_reason == "pause_turn" and resumes < MAX_PAUSE_TURN_RESUMES:
            logger.debug("categorize search loop paused, resuming once")
            current_messages = current_messages + [{"role": "assistant", "content": response.content}]
            resumes += 1
            continue
        break

    text_block = next((block for block in response.content if block.type == "text"), None)
    if text_block is None:
        raise RuntimeError(
            f"categorize: no text block in final response (stop_reason={response.stop_reason!r})"
        )
    logger.debug("categorize raw response text=%s", text_block.text)
    return json.loads(text_block.text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_client.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ai/client.py tests/test_ai_client.py
git commit -m "feat: add web search tool and pause_turn resume to AI categorize call"
```

---

### Task 3: Handle `candidates` in the categorization router (safety net, history text, response model)

**Files:**
- Modify: `app/routers/ai_categorize.py`
- Test: `tests/test_ai_categorize.py`, `tests/test_ai_ui.py`

**Interfaces:**
- Consumes: the `candidates` key in the dict returned by `ai_client.categorize()` (Task 1's schema; tests in this task mock `categorize()` directly, so this task has no runtime dependency on Task 1/2's actual implementation).
- Produces: `CategorizeResponse.candidates: Optional[list[str]]` (new field, default `None`); `_build_ai_chat_context(...)`'s `can_confirm` is now `False` whenever `candidates` is present, for templates (including Task 4) to consume.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ai_categorize.py` (after the existing imports, anywhere after the other test functions):

```python
def test_categorize_returns_candidates_without_triggering_missing_coordinates_question(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "Anime merchandise store",
            "confidence": "medium",
            "question": None,
            "lat": 35.7295,
            "lon": 139.7109,
            "candidates": ["Tokyo - Ikebukuro", "Osaka - Namba"],
        },
    )

    response = client.post(
        "/api/ai/categorize", json={"message": "The world's first dedicated Dragon Ball store"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["question"] is None
    assert data["candidates"] == ["Tokyo - Ikebukuro", "Osaka - Namba"]


def test_categorize_response_omits_candidates_by_default(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Ichiran Ramen",
            "near_hub": None,
            "types": ["food"],
            "note": "",
            "confidence": "high",
            "question": None,
            "lat": 35.0,
            "lon": 135.0,
        },
    )

    response = client.post("/api/ai/categorize", json={"message": "Ramen"})
    assert response.json()["candidates"] is None


def test_safety_net_does_not_trigger_when_candidates_present(session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "",
            "confidence": "medium",
            "question": None,
            "lat": None,
            "lon": None,
            "candidates": ["Tokyo - Ikebukuro", "Osaka - Namba"],
        },
    )

    _, result, _ = _run_turn(session, None, "Dragon Ball store")
    assert result["question"] is None
    assert result["candidates"] == ["Tokyo - Ikebukuro", "Osaka - Namba"]


def test_assistant_candidates_history_is_summarized_not_raw_json(session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "",
            "confidence": "medium",
            "question": None,
            "lat": 35.7295,
            "lon": 139.7109,
            "candidates": ["Tokyo - Ikebukuro", "Osaka - Namba"],
        },
    )
    ai_session, _, _ = _run_turn(session, None, "Dragon Ball store")

    captured = {}

    def fake_categorize(hub_names, categories, messages):
        captured["messages"] = messages
        return {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "",
            "confidence": "high",
            "question": None,
            "lat": 35.7295,
            "lon": 139.7109,
        }

    monkeypatch.setattr(ai_client, "categorize", fake_categorize)
    _run_turn(session, ai_session.id, "Tokyo - Ikebukuro")

    assistant_text = [m for m in captured["messages"] if m["role"] == "assistant"][0]["content"]
    assert "Tokyo - Ikebukuro" in assistant_text
    assert "Osaka - Namba" in assistant_text
    assert not assistant_text.strip().startswith("{")
```

Add to `tests/test_ai_ui.py` (anywhere after the other test functions):

```python
def test_ui_ai_message_does_not_show_confirm_button_when_candidates_present(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "",
            "confidence": "medium",
            "question": None,
            "lat": 35.7295,
            "lon": 139.7109,
            "candidates": ["Tokyo - Ikebukuro", "Osaka - Namba"],
        },
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/dbz", "message": "Dragon Ball store"},
    )
    assert response.status_code == 200
    assert "Conferma e salva" not in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_categorize.py tests/test_ai_ui.py -v`
Expected: All 5 new tests FAIL — `test_categorize_returns_candidates_without_triggering_missing_coordinates_question` and `test_categorize_response_omits_candidates_by_default` fail because `CategorizeResponse` has no `candidates` field (`KeyError`/`AttributeError` from Pydantic); `test_safety_net_does_not_trigger_when_candidates_present` fails because the safety net currently ignores `candidates` and sets `question` to `MISSING_COORDINATES_QUESTION`; `test_assistant_candidates_history_is_summarized_not_raw_json` fails because `_assistant_turn_text` has no candidates branch (it currently falls into the normal proposal-text branch, which won't mention "Tokyo - Ikebukuro"/"Osaka - Namba"); `test_ui_ai_message_does_not_show_confirm_button_when_candidates_present` fails because `can_confirm` doesn't yet check for `candidates`.

- [ ] **Step 3: Implement the router changes**

In `app/routers/ai_categorize.py`, make these four edits:

1. Add `candidates` to `CategorizeResponse`:

```python
class CategorizeResponse(BaseModel):
    session_id: str
    place_name: str
    near_hub: Optional[str]
    types: list[str]
    note: str
    confidence: str
    question: Optional[str]
    candidates: Optional[list[str]] = None
    matched_location_id: Optional[str] = None
```

2. Add a candidates branch to `_assistant_turn_text`, before the existing `parts = [...]` fallback:

```python
def _assistant_turn_text(result: dict) -> str:
    if result.get("question"):
        return result["question"]
    if result.get("candidates"):
        return "Ho trovato piu' posti possibili: " + ", ".join(result["candidates"]) + ". Quale?"

    parts = [f"Luogo proposto: {result.get('place_name', '')}."]
    if result.get("near_hub"):
        parts.append(f"Vicino a: {result['near_hub']}.")
    if result.get("types"):
        parts.append(f"Tipo: {', '.join(result['types'])}.")
    if result.get("note"):
        parts.append(f"Nota: {result['note']}.")
    parts.append(f"Confidenza: {result.get('confidence', '')}.")
    return " ".join(parts)
```

3. In `_run_turn`, add the `candidates` guard to the safety-net condition:

```python
    if (
        matched_location_id is None
        and result.get("question") is None
        and not result.get("candidates")
        and (result.get("lat") is None or result.get("lon") is None)
    ):
```

(The rest of that `if` block — the hub-fallback logic and `result["question"] = MISSING_COORDINATES_QUESTION` line — stays exactly as-is.)

4. In `_build_ai_chat_context`, add the `candidates` guard to `can_confirm`:

```python
    can_confirm = (
        latest_result is not None
        and latest_result.get("question") is None
        and not latest_result.get("candidates")
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_categorize.py tests/test_ai_ui.py -v`
Expected: All tests PASS, including every pre-existing test in both files (no regressions).

- [ ] **Step 5: Commit**

```bash
git add app/routers/ai_categorize.py tests/test_ai_categorize.py tests/test_ai_ui.py
git commit -m "feat: suppress missing-coordinates question and confirm button when AI returns candidates"
```

---

### Task 4: Render candidate chips in the AI chat template

**Files:**
- Modify: `app/templates/partials/ai_chat.html`
- Modify: `app/static/css/style.css`
- Test: `tests/test_ai_ui.py`

**Interfaces:**
- Consumes: `latest_result.candidates`, `session_id`, `link` from the template context produced by `_build_ai_chat_context` (Task 3, unchanged shape — `candidates` is just a new optional key inside the existing `latest_result` dict, and `turn.result` dicts in `history`).
- Produces: clickable chip buttons that POST to the existing `/ui/ai/message` endpoint with `message` set to the clicked candidate's text — reusing that endpoint's existing contract exactly (`session_id`, `link`, `message` form fields).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ai_ui.py` (anywhere after the other test functions):

```python
def test_ui_ai_message_renders_candidate_chips(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "",
            "confidence": "medium",
            "question": None,
            "lat": 35.7295,
            "lon": 139.7109,
            "candidates": ["Tokyo - Ikebukuro", "Osaka - Namba"],
        },
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/dbz", "message": "Dragon Ball store"},
    )
    assert response.status_code == 200
    assert "Tokyo - Ikebukuro" in response.text
    assert "Osaka - Namba" in response.text
    assert response.text.count('name="message" value="Tokyo - Ikebukuro"') == 1


def test_ui_ai_candidate_chip_click_continues_session_and_shows_confirm(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Dragon Ball Store",
            "near_hub": None,
            "types": ["shopping"],
            "note": "",
            "confidence": "medium",
            "question": None,
            "lat": 35.7295,
            "lon": 139.7109,
            "candidates": ["Tokyo - Ikebukuro", "Osaka - Namba"],
        },
    )
    client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/dbz", "message": "Dragon Ball store"},
    )
    session_id = session.exec(select(AiSession)).first().id

    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Dragon Ball Store, Ikebukuro",
            "near_hub": None,
            "types": ["shopping"],
            "note": "",
            "confidence": "high",
            "question": None,
            "lat": 35.7295,
            "lon": 139.7109,
        },
    )
    second = client.post(
        "/ui/ai/message",
        data={"session_id": session_id, "link": "https://instagram.com/reel/dbz", "message": "Tokyo - Ikebukuro"},
    )
    assert second.status_code == 200
    assert "Conferma e salva" in second.text
```

(`select` and `AiSession` are already imported at the top of `tests/test_ai_ui.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_ui.py -v`
Expected: `test_ui_ai_message_renders_candidate_chips` FAILs (no `name="message" value="Tokyo - Ikebukuro"` markup exists yet — the template doesn't render chips). `test_ui_ai_candidate_chip_click_continues_session_and_shows_confirm` passes or fails depending on Task 3 alone (the underlying flow already works via `_run_turn`), but rendering assertions in the first test confirm the template gap either way.

- [ ] **Step 3: Implement the template changes**

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
            {% elif turn.result.candidates %}
            Ho trovato più posti possibili: {{ turn.result.candidates | join(', ') }}
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

{% if latest_result and latest_result.candidates %}
<div class="candidate-chips">
    {% for candidate in latest_result.candidates %}
    <form hx-post="/ui/ai/message" hx-target="#ai-chat-panel" hx-swap="innerHTML">
        <input type="hidden" name="session_id" value="{{ session_id }}">
        <input type="hidden" name="link" value="{{ link }}">
        <input type="hidden" name="message" value="{{ candidate }}">
        <button type="submit" class="chip">{{ candidate }}</button>
    </form>
    {% endfor %}
</div>
{% endif %}

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

Add this rule to `app/static/css/style.css`, right after the existing `.category-form, .location-form { ... }` rule at the end of the file:

```css
.candidate-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin: 0.5rem 0;
}

.candidate-chips form {
    display: inline;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_ui.py -v`
Expected: All tests PASS, including every pre-existing test in the file (no regressions — in particular `test_ui_ai_message_shows_confirm_button_when_proposal_is_complete` and `test_ui_ai_message_forces_question_when_new_location_missing_coordinates` still pass unchanged, since neither of those fakes includes a `candidates` key).

- [ ] **Step 5: Run the full test suite**

Run: `pytest`
Expected: All tests PASS (no regressions anywhere in the project).

- [ ] **Step 6: Commit**

```bash
git add app/templates/partials/ai_chat.html app/static/css/style.css tests/test_ai_ui.py
git commit -m "feat: render clickable candidate chips in AI chat for location disambiguation"
```
