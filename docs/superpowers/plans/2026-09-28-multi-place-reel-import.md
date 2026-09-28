# Multi-Place Reel Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a reel's caption/transcript explicitly lists multiple distinct places (e.g. "10 luoghi imperdibili a Kyoto"), let the user pick which of the detected places to save as separate pins, instead of forcing exactly one place per reel.

**Architecture:** A small, separate Claude classification call (`detect_places`) decides whether the combined text lists multiple places; if not (the common case), the existing single-place flow runs completely unchanged. If so, the existing single-place resolution machinery (`_run_turn`, the hub-coordinate fallback, the web-search-assisted lookup, the per-place clarifying question) is invoked once per detected place name, each in its own independent `AiSession`. A new checklist view lets the user confirm a subset; confirming creates one `Reel` per selected place, all sharing the same link (no schema change — `Reel.link` has no uniqueness constraint).

**Tech Stack:** Same as the rest of the app — FastAPI, Jinja2 + HTMX, SQLModel, Anthropic Python SDK.

## Global Constraints

- No database schema changes — multiple `Reel` rows share one `link`, each with its own `location_id`.
- The existing single-place flow (`_run_turn`, `ai_client.categorize`, `app/ai/prompts.py`'s existing schema/prompt) is not modified in behavior — only reused by calling it multiple times.
- Any failure in the new `detect_places` classification call (API error, malformed response) falls back to today's single-place flow — never a visible error for this step.
- The classifier is capped at 15 place names per reel (enforced via prompt instruction).
- A place that never resolves (user ignores/never answers its clarifying question) never blocks confirming the other, already-resolved places in the same batch.
- Confirming with zero rows checked creates nothing — consistent with "never save without an explicit selection."
- No real Anthropic API calls in automated tests — everything is mocked, consistent with the rest of the project's test suite.

---

## Task 1: `detect_places()` classification call

**Files:**
- Modify: `app/ai/prompts.py` (add `build_places_response_schema`, `build_places_system_prompt`)
- Modify: `app/ai/client.py` (add `detect_places`)
- Test: `tests/test_ai_client.py`

**Interfaces:**
- Produces: `detect_places(message: str) -> dict` returning `{"is_multi_place": bool, "place_names": list[str] | None}`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ai_client.py` (the file already defines `FakeAnthropicClient`/`FakeMessages` near its top — reuse them, no new test doubles needed):

```python
def test_detect_places_returns_single_place_result(monkeypatch):
    expected = {"is_multi_place": False, "place_names": None}
    fake_client = FakeAnthropicClient(response_json=expected)
    monkeypatch.setattr(ai_client, "get_client", lambda: fake_client)

    result = ai_client.detect_places("Un tempio bellissimo a Kyoto")

    assert result == expected
    assert fake_client.messages.last_call_kwargs["model"] == ai_client.MODEL
    assert fake_client.messages.last_call_kwargs["output_config"]["format"]["type"] == "json_schema"


def test_detect_places_returns_multi_place_list(monkeypatch):
    expected = {
        "is_multi_place": True,
        "place_names": ["Fushimi Inari Taisha", "Kiyomizu-dera", "Kinkaku-ji"],
    }
    fake_client = FakeAnthropicClient(response_json=expected)
    monkeypatch.setattr(ai_client, "get_client", lambda: fake_client)

    result = ai_client.detect_places("10 luoghi imperdibili a Kyoto: ...")

    assert result == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `ANTHROPIC_API_KEY=test uv run pytest tests/test_ai_client.py -v`
Expected: the two new tests FAIL with `AttributeError: module 'app.ai.client' has no attribute 'detect_places'`.

- [ ] **Step 3: Add the new prompt builders**

Append to `app/ai/prompts.py`:

```python
def build_places_response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "is_multi_place": {"type": "boolean"},
            "place_names": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
        },
        "required": ["is_multi_place", "place_names"],
        "additionalProperties": False,
    }


def build_places_system_prompt() -> str:
    return (
        "Analizzi un testo (link, didascalia e/o trascrizione audio) di un reel Instagram su viaggi in "
        "Giappone. Il tuo unico compito e' capire se il testo elenca ESPLICITAMENTE piu' luoghi distinti "
        "da visitare (per esempio una lista tipo '10 posti da vedere a Kyoto', con nomi di luoghi diversi "
        "elencati uno per uno), oppure se descrive un solo luogo (anche se in modo molto dettagliato). "
        "Se il testo elenca chiaramente piu' luoghi distinti, valorizza 'is_multi_place' a true e "
        "'place_names' con i nomi dei luoghi esattamente come appaiono nel testo (massimo 15 nomi; se ce "
        "ne sono di piu', scegli i primi 15). Se il testo descrive un solo luogo, o non elenca luoghi "
        "specifici, valorizza 'is_multi_place' a false e 'place_names' a null. Nel dubbio, se non sei "
        "sicuro che si tratti di un vero elenco di luoghi diversi, preferisci rispondere false. Rispondi "
        "seguendo esattamente lo schema JSON fornito."
    )
```

- [ ] **Step 4: Add `detect_places` to `app/ai/client.py`**

Change the existing import line:

```python
from app.ai.prompts import build_response_schema, build_system_prompt
```

to:

```python
from app.ai.prompts import (
    build_places_response_schema,
    build_places_system_prompt,
    build_response_schema,
    build_system_prompt,
)
```

Then append this function to the end of the file:

```python
def detect_places(message: str) -> dict[str, Any]:
    client = get_client()
    system = build_places_system_prompt()
    schema = build_places_response_schema()
    logger.debug("detect_places request message=%s", message)

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": message}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )

    text_block = next((block for block in response.content if block.type == "text"), None)
    if text_block is None:
        raise RuntimeError(
            f"detect_places: no text block in response (stop_reason={response.stop_reason!r})"
        )
    logger.debug("detect_places raw response text=%s", text_block.text)
    return json.loads(text_block.text)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `ANTHROPIC_API_KEY=test uv run pytest tests/test_ai_client.py -v`
Expected: PASS (all tests in the file, including the 2 new ones).

- [ ] **Step 6: Commit**

```bash
git add app/ai/prompts.py app/ai/client.py tests/test_ai_client.py
git commit -m "feat: add detect_places classification call for multi-place reels"
```

---

## Task 2: Extract shared location-resolution + Reel-creation helper

**Files:**
- Modify: `app/routers/ai_categorize.py` (extract `_resolve_location_and_create_reel`, use it in `ui_ai_confirm`)
- Test: `tests/test_ai_categorize.py`

**Interfaces:**
- Consumes: nothing new (pure refactor of existing, already-imported symbols: `Location`, `Reel`, `ReelType`, `get_valid_type_keys`, `_find_hub_by_name`, all already imported in this file).
- Produces: `_resolve_location_and_create_reel(session, link, place_name, near_hub, types, note, lat, lon, matched_location_id) -> Reel` — used by both `ui_ai_confirm` (this task) and the new multi-confirm endpoint (Task 4).

This task is a behavior-preserving refactor: `ui_ai_confirm`'s existing tests in `tests/test_ai_ui.py` must all still pass unchanged, proving nothing changed externally.

- [ ] **Step 1: Write the failing tests for the extracted helper**

Add to `tests/test_ai_categorize.py`. First add these imports at the top of the file (alongside the existing ones):

```python
from sqlmodel import select

from app.models import Category, Location, Reel
from app.routers.ai_categorize import _resolve_location_and_create_reel, _run_turn
```

(`Category`, `Location` are likely already imported — only add names that aren't already there; `_run_turn` is already imported too, this just adds `Reel`, `select`, and `_resolve_location_and_create_reel` to the existing import lines.)

Then add:

```python
def test_resolve_location_and_create_reel_uses_matched_location(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="food", label="Cibo", icon="🍜", color="#A63A2E"))
    session.commit()
    session.refresh(hub)

    reel = _resolve_location_and_create_reel(
        session,
        "https://instagram.com/reel/abc",
        "Tokyo / Kanto",
        "",
        ["food"],
        "Ramen chain",
        "",
        "",
        hub.id,
    )

    assert reel.location_id == hub.id
    assert session.exec(select(Location)).all() == [hub]


def test_resolve_location_and_create_reel_creates_new_satellite_under_hub(session):
    hub = Location(name="Tokyo / Kanto", is_hub=True, lat=35.6762, lon=139.6503)
    session.add(hub)
    session.add(Category(key="nature", label="Natura", icon="🌸", color="#7A8F5E"))
    session.commit()
    session.refresh(hub)

    reel = _resolve_location_and_create_reel(
        session,
        "https://instagram.com/reel/nikko",
        "Nikko",
        "Tokyo / Kanto",
        ["nature"],
        "Shrine town",
        "36.7198",
        "139.6982",
        "",
    )

    satellite = session.exec(select(Location).where(Location.name == "Nikko")).first()
    assert satellite is not None
    assert satellite.is_hub is False
    assert satellite.parent_id == hub.id
    assert reel.location_id == satellite.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `ANTHROPIC_API_KEY=test uv run pytest tests/test_ai_categorize.py -v`
Expected: the 2 new tests FAIL with `ImportError`/`AttributeError` (`_resolve_location_and_create_reel` doesn't exist yet).

- [ ] **Step 3: Extract the helper in `app/routers/ai_categorize.py`**

Insert this new function directly above the `@ui_router.post("/confirm")` line:

```python
def _resolve_location_and_create_reel(
    session: Session,
    link: str,
    place_name: str,
    near_hub: str,
    types: list[str],
    note: str,
    lat,
    lon,
    matched_location_id: str,
) -> Reel:
    if matched_location_id:
        location_id = matched_location_id
    else:
        hub = _find_hub_by_name(session, near_hub)

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

    valid_type_keys = get_valid_type_keys(session)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    return reel
```

(`lat`/`lon` are intentionally left untyped — the single-confirm form passes them as `str`, the new multi-confirm endpoint in Task 4 passes them as `float | None` straight from parsed JSON; both work identically against `not lat`/`float(lat)`.)

Then replace `ui_ai_confirm`'s body (everything between the `_is_safe_link` check and the `stale_ai_session = session.get(...)` line) — currently:

```python
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    if matched_location_id:
        location_id = matched_location_id
    else:
        hub = _find_hub_by_name(session, near_hub)

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

    valid_type_keys = get_valid_type_keys(session)
    for type_value in types:
        if type_value in valid_type_keys:
            session.add(ReelType(reel_id=reel.id, type=type_value))
    session.commit()

    stale_ai_session = session.get(AiSession, session_id)
```

with:

```python
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    _resolve_location_and_create_reel(
        session, link, place_name, near_hub, types, note, lat, lon, matched_location_id
    )

    stale_ai_session = session.get(AiSession, session_id)
```

Everything after that line (the session cleanup and the OOB-refresh response construction) stays exactly as-is, untouched.

- [ ] **Step 4: Run tests to verify they pass**

Run: `ANTHROPIC_API_KEY=test uv run pytest tests/test_ai_categorize.py tests/test_ai_ui.py -v`
Expected: PASS, including every pre-existing `ui_ai_confirm`-related test in `tests/test_ai_ui.py` (proving the refactor didn't change behavior) plus the 2 new tests.

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `ANTHROPIC_API_KEY=test uv run pytest -v`
Expected: all tests passing, zero failures.

- [ ] **Step 6: Commit**

```bash
git add app/routers/ai_categorize.py tests/test_ai_categorize.py
git commit -m "refactor: extract shared location-resolution helper from ui_ai_confirm"
```

---

## Task 3: Multi-place batch — detection, per-place resolution, checklist view

**Files:**
- Create: `app/routers/ai_multi_categorize.py`
- Create: `app/templates/partials/ai_chat_multi.html`
- Modify: `app/static/css/style.css` (append minimal layout rules)
- Modify: `app/routers/ai_categorize.py` (`ui_ai_message` calls `detect_places` on the first turn)
- Modify: `app/main.py` (register the new router)
- Test: `tests/test_ai_multi_categorize.py`

**Interfaces:**
- Consumes: `ai_client.detect_places` (Task 1); `app.routers.ai_categorize._run_turn`, `_find_matching_location` (existing, unmodified); `app.routers.categories.get_taxonomy` (existing).
- Produces: `app.routers.ai_multi_categorize.router: APIRouter` with `POST /ui/ai/multi/message`; `start_multi_place_batch(request, session, original_message, link, place_names) -> TemplateResponse`, called from `ai_categorize.ui_ai_message` via a deferred import.

- [ ] **Step 1: Create the new template**

Create `app/templates/partials/ai_chat_multi.html`:

```html
{% if rows %}
<form hx-post="/ui/ai/multi/confirm" hx-target="#ai-chat-panel" hx-swap="innerHTML" class="ai-confirm-form multi-place-form">
    <input type="hidden" name="link" value="{{ link }}">
    {% for sid in session_ids %}<input type="hidden" name="session_ids" value="{{ sid }}">{% endfor %}

    {% for row in rows %}
        {% if row.resolved %}
        <label class="multi-place-row">
            <input type="checkbox" name="place_json" value='{{ row.place_json }}' checked>
            <strong>{{ row.result.place_name }}</strong>{% if row.result.near_hub %} (vicino a {{ row.result.near_hub }}){% endif %}
            <span class="types">{% for t in row.result.types %}{{ taxonomy[t].icon }} {{ taxonomy[t].label }} {% endfor %}</span>
            {% if row.result.note %}<span class="note">{{ row.result.note }}</span>{% endif %}
        </label>
        {% endif %}
    {% endfor %}

    <button type="submit">Aggiungi selezionati</button>
    <button type="button" hx-get="/ui/ai/panel" hx-target="#ai-chat-panel" hx-swap="innerHTML">Annulla</button>
</form>

{% for row in rows %}
    {% if not row.resolved %}
    <div class="multi-place-clarify">
        <span>{{ row.result.question }}</span>
        <form hx-post="/ui/ai/multi/message" hx-target="#ai-chat-panel" hx-swap="innerHTML">
            <input type="hidden" name="link" value="{{ link }}">
            {% for sid in session_ids %}<input type="hidden" name="session_ids" value="{{ sid }}">{% endfor %}
            <input type="hidden" name="clarify_session_id" value="{{ row.session_id }}">
            <input type="text" name="clarify_text" placeholder="Es. vicino ad Arashiyama" required>
            <button type="submit">Chiarisci</button>
        </form>
    </div>
    {% endif %}
{% endfor %}
{% else %}
<p class="ai-notice">Non ho trovato luoghi da elencare.</p>
<button type="button" hx-get="/ui/ai/panel" hx-target="#ai-chat-panel" hx-swap="innerHTML">Torna indietro</button>
{% endif %}
```

- [ ] **Step 2: Append CSS for the new template's classes**

Append to `app/static/css/style.css`:

```css
.multi-place-row {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    margin: 0.4rem 0;
}

.multi-place-clarify {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    margin: 0.5rem 0;
    padding: 0.5rem;
    border: 1px dashed #999;
}
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_ai_multi_categorize.py`:

```python
import re

from sqlmodel import select

from app.ai import client as ai_client
from app.models import AiSession, Location


def test_ui_ai_message_routes_to_multi_place_batch_when_detected(client, session, monkeypatch):
    session.add(Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681))
    session.commit()

    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {
            "is_multi_place": True,
            "place_names": ["Fushimi Inari Taisha", "Kiyomizu-dera"],
        },
    )

    results = iter(
        [
            {
                "place_name": "Fushimi Inari Taisha",
                "near_hub": "Kyoto - Osaka / Kansai",
                "types": ["culture"],
                "note": "Famous torii gates",
                "confidence": "high",
                "question": None,
                "lat": None,
                "lon": None,
            },
            {
                "place_name": "Kiyomizu-dera",
                "near_hub": "Kyoto - Osaka / Kansai",
                "types": ["culture"],
                "note": "Historic wooden temple",
                "confidence": "high",
                "question": None,
                "lat": None,
                "lon": None,
            },
        ]
    )
    monkeypatch.setattr(
        ai_client, "categorize", lambda hub_names, categories, messages: next(results)
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/kyoto10", "message": "10 posti a Kyoto"},
    )

    assert response.status_code == 200
    assert "Fushimi Inari Taisha" in response.text
    assert "Kiyomizu-dera" in response.text
    assert response.text.count('name="place_json"') == 2
    assert len(session.exec(select(AiSession)).all()) == 2


def test_ui_ai_message_falls_back_to_single_place_when_detect_places_fails(client, session, monkeypatch):
    def boom(message):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai_client, "detect_places", boom)
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Ichiran Ramen",
            "near_hub": None,
            "types": ["food"],
            "note": "Ramen chain",
            "confidence": "high",
            "question": None,
            "lat": 35.0,
            "lon": 135.0,
        },
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/abc", "message": "Ramen a Tokyo"},
    )

    assert response.status_code == 200
    assert "Ichiran Ramen" in response.text
    assert len(session.exec(select(AiSession)).all()) == 1


def test_multi_place_row_shows_clarify_form_for_unresolved_place(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {"is_multi_place": True, "place_names": ["Posto Misterioso", "Nishiki Market"]},
    )

    results = iter(
        [
            {
                "place_name": "Posto Misterioso",
                "near_hub": None,
                "types": [],
                "note": "",
                "confidence": "low",
                "question": None,
                "lat": None,
                "lon": None,
            },
            {
                "place_name": "Nishiki Market",
                "near_hub": None,
                "types": ["food"],
                "note": "Historic market",
                "confidence": "high",
                "question": None,
                "lat": 35.005,
                "lon": 135.765,
            },
        ]
    )
    monkeypatch.setattr(
        ai_client, "categorize", lambda hub_names, categories, messages: next(results)
    )

    response = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/kyoto2", "message": "2 posti a Kyoto"},
    )

    assert response.status_code == 200
    assert "coordinate" in response.text.lower()
    assert 'name="clarify_session_id"' in response.text
    assert response.text.count('name="place_json"') == 1


def test_ui_ai_multi_message_advances_only_the_clarified_session(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {"is_multi_place": True, "place_names": ["Posto Misterioso", "Nishiki Market"]},
    )
    results = iter(
        [
            {
                "place_name": "Posto Misterioso", "near_hub": None, "types": [], "note": "",
                "confidence": "low", "question": None, "lat": None, "lon": None,
            },
            {
                "place_name": "Nishiki Market", "near_hub": None, "types": ["food"], "note": "Historic market",
                "confidence": "high", "question": None, "lat": 35.005, "lon": 135.765,
            },
        ]
    )
    monkeypatch.setattr(ai_client, "categorize", lambda hub_names, categories, messages: next(results))

    first = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/kyoto2", "message": "2 posti a Kyoto"},
    )
    assert len(session.exec(select(AiSession)).all()) == 2

    clarify_session_id = re.search(r'name="clarify_session_id" value="([^"]+)"', first.text).group(1)
    all_session_ids = re.findall(r'name="session_ids" value="([^"]+)"', first.text)

    session.add(Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681))
    session.commit()
    monkeypatch.setattr(
        ai_client,
        "categorize",
        lambda hub_names, categories, messages: {
            "place_name": "Posto Misterioso", "near_hub": "Kyoto - Osaka / Kansai", "types": ["culture"],
            "note": "Ora chiaro", "confidence": "medium", "question": None, "lat": None, "lon": None,
        },
    )

    second = client.post(
        "/ui/ai/multi/message",
        data={
            "link": "https://instagram.com/reel/kyoto2",
            "session_ids": all_session_ids,
            "clarify_session_id": clarify_session_id,
            "clarify_text": "e' vicino ad Arashiyama",
        },
    )

    assert second.status_code == 200
    assert second.text.count('name="place_json"') == 2
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `ANTHROPIC_API_KEY=test uv run pytest tests/test_ai_multi_categorize.py -v`
Expected: FAIL — `ModuleNotFoundError`/404s, since `ai_client.detect_places` isn't called anywhere yet and `/ui/ai/multi/message` doesn't exist. (`ai_client.detect_places` itself already exists from Task 1, so these failures are specifically about the router wiring, not a missing function.)

- [ ] **Step 5: Implement `app/routers/ai_multi_categorize.py`**

```python
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from sqlmodel import Session, select

from app.db import get_session
from app.models import AiMessage
from app.routers.ai_categorize import _find_matching_location, _run_turn
from app.routers.categories import get_taxonomy
from app.web import templates

router = APIRouter(prefix="/ui/ai/multi", tags=["ai-multi"])

logger = logging.getLogger("app.ai")

MAX_PLACES = 15


def _seed_message(original_message: str, place_name: str) -> str:
    return (
        f"{original_message}\n\n"
        f"Concentrati SOLO su questo luogo specifico menzionato nel testo, ignorando gli altri: {place_name}"
    )


def _read_latest_result(session: Session, session_id: str) -> Optional[dict]:
    messages = session.exec(
        select(AiMessage)
        .where(AiMessage.session_id == session_id, AiMessage.role == "assistant")
        .order_by(AiMessage.created_at)
    ).all()
    if not messages:
        return None
    return json.loads(messages[-1].content)


def _build_multi_context(session: Session, session_ids: list[str], link: str) -> dict:
    rows = []
    for session_id in session_ids:
        result = _read_latest_result(session, session_id)
        if result is None:
            continue
        matched_location_id = _find_matching_location(session, result.get("place_name", ""))
        resolved = result.get("question") is None
        place_payload = {
            "place_name": result.get("place_name", ""),
            "near_hub": result.get("near_hub") or "",
            "types": result.get("types", []),
            "note": result.get("note", ""),
            "lat": result.get("lat"),
            "lon": result.get("lon"),
            "matched_location_id": matched_location_id or "",
        }
        rows.append(
            {
                "session_id": session_id,
                "result": result,
                "resolved": resolved,
                "place_json": json.dumps(place_payload),
            }
        )

    return {
        "link": link or "",
        "session_ids": session_ids,
        "rows": rows,
        "taxonomy": get_taxonomy(session),
    }


def start_multi_place_batch(
    request: Request, session: Session, original_message: str, link: str, place_names: list[str]
):
    session_ids = []
    for place_name in place_names[:MAX_PLACES]:
        ai_session, _, _ = _run_turn(session, None, _seed_message(original_message, place_name))
        session_ids.append(ai_session.id)

    context = _build_multi_context(session, session_ids, link)
    return templates.TemplateResponse(request, "partials/ai_chat_multi.html", context)


@router.post("/message")
def ui_ai_multi_message(
    request: Request,
    link: str = Form(""),
    session_ids: list[str] = Form([]),
    clarify_session_id: str = Form(""),
    clarify_text: str = Form(""),
    session: Session = Depends(get_session),
):
    if clarify_session_id and clarify_text:
        _run_turn(session, clarify_session_id, clarify_text)

    context = _build_multi_context(session, session_ids, link)
    return templates.TemplateResponse(request, "partials/ai_chat_multi.html", context)
```

- [ ] **Step 6: Wire the classifier into `ui_ai_message`**

In `app/routers/ai_categorize.py`, replace `ui_ai_message`'s current body:

```python
    if not session_id:
        if not _is_safe_link(link):
            raise HTTPException(status_code=400, detail="link must be an http(s) URL")
        combined_message = f"Link: {link}\nDescrizione: {message}"
    else:
        combined_message = message
```

with:

```python
    if not session_id:
        if not _is_safe_link(link):
            raise HTTPException(status_code=400, detail="link must be an http(s) URL")
        combined_message = f"Link: {link}\nDescrizione: {message}"

        try:
            detection = ai_client.detect_places(combined_message)
        except (anthropic.AnthropicError, RuntimeError):
            logger.exception("detect_places call failed, treating as single-place")
            detection = {"is_multi_place": False, "place_names": None}

        place_names = detection.get("place_names") or []
        if detection.get("is_multi_place") and len(place_names) >= 2:
            # Deferred import: ai_multi_categorize imports helpers from this module,
            # so importing it at module load time would create a circular import.
            from app.routers.ai_multi_categorize import start_multi_place_batch

            return start_multi_place_batch(request, session, combined_message, link, place_names)
    else:
        combined_message = message
```

The rest of the function (the `_run_turn` call and its `try/except HTTPException` wrapper, and the final `TemplateResponse`) stays exactly as-is.

- [ ] **Step 7: Register the new router in `app/main.py`**

Change the router import line:

```python
from app.routers import ai_categorize, auth, categories, instagram_import, locations, map as map_router, reels
```

to:

```python
from app.routers import ai_categorize, ai_multi_categorize, auth, categories, instagram_import, locations, map as map_router, reels
```

Add, alongside the other `ai_categorize` includes:

```python
app.include_router(ai_multi_categorize.router)
```

- [ ] **Step 8: Mock `detect_places` in existing first-turn tests**

`ui_ai_message` now calls `ai_client.detect_places` on every first turn (no `session_id`), before it used to only call `ai_client.categorize`. Without a mock, these calls would hit the real Anthropic API during the test run (slow, network-dependent, and liable to hang or fail in a sandboxed/offline CI environment) before falling back to single-place mode via the `except` clause added in Step 6 — functionally harmless, but real network calls in the test suite must be avoided regardless of whether they'd "still pass."

Exactly 10 existing tests in `tests/test_ai_ui.py` post to `/ui/ai/message` on a first turn (no `session_id` in the form data) and need one new line added — `monkeypatch.setattr(ai_client, "detect_places", lambda message: {"is_multi_place": False, "place_names": None})` — right next to their existing `monkeypatch.setattr(ai_client, "categorize", ...)` call (add it just before or after, order between the two doesn't matter). These are the only ones affected (verified by grepping every `/ui/ai/message` call site in the file); do not add the mock anywhere else:

- `test_ui_ai_message_first_turn_creates_session_and_shows_proposal`
- `test_ui_ai_message_backfills_missing_coordinates_from_matching_hub_on_first_turn`
- `test_ui_ai_message_continues_existing_session` (only needs it once — this test's first `client.post` call has no `session_id`; its second call already has one and is unaffected)
- `test_ui_ai_message_forces_question_when_new_location_missing_coordinates`
- `test_ui_ai_message_shows_confirm_button_when_proposal_is_complete`
- `test_ui_ai_confirm_cleans_up_the_ai_session` (its `/ui/ai/message` call, not its later `/ui/ai/confirm` call)
- `test_ui_ai_message_shows_friendly_error_when_ai_call_fails`
- `test_ui_ai_message_does_not_show_confirm_button_when_candidates_present`
- `test_ui_ai_message_renders_candidate_chips`
- `test_ui_ai_candidate_chip_click_continues_session_and_shows_confirm` (only its first `client.post` call, before a `session_id` exists)

Do **not** add this mock to `test_ui_ai_message_rejects_invalid_link_on_first_turn` (the invalid link is rejected before `detect_places` is ever called) or to `test_ui_ai_message_with_unknown_session_id_resets_panel_with_notice` (it already sends a non-empty `session_id`, so the `not session_id` branch — and `detect_places` — never runs). Nothing in `tests/test_ai_categorize.py` needs this mock: that file only exercises `/api/ai/categorize` and `_run_turn` directly, never `/ui/ai/message`.

- [ ] **Step 9: Run tests to verify they pass**

Run: `ANTHROPIC_API_KEY=test uv run pytest tests/test_ai_multi_categorize.py tests/test_ai_ui.py -v`
Expected: PASS — the 4 new tests in `tests/test_ai_multi_categorize.py`, plus every test in `tests/test_ai_ui.py` (the 10 updated ones and everything else, unchanged).

- [ ] **Step 10: Run the full suite to check for regressions**

Run: `ANTHROPIC_API_KEY=test uv run pytest -v`
Expected: all tests passing, zero failures, no new warnings, and no test taking noticeably longer than before (a lingering unmocked `detect_places` call would show up as a slow/hanging test here, not just a failure).

- [ ] **Step 11: Commit**

```bash
git add app/routers/ai_multi_categorize.py app/templates/partials/ai_chat_multi.html app/static/css/style.css app/routers/ai_categorize.py app/main.py tests/test_ai_multi_categorize.py tests/test_ai_ui.py
git commit -m "feat: detect multi-place reels and resolve each place independently"
```

---

## Task 4: Multi-place confirm endpoint

**Files:**
- Modify: `app/routers/ai_multi_categorize.py` (add `POST /ui/ai/multi/confirm`)
- Test: `tests/test_ai_multi_categorize.py`

**Interfaces:**
- Consumes: `app.routers.ai_categorize._resolve_location_and_create_reel` (Task 2), `_build_ai_chat_context` (existing); `app.routers.reels._is_safe_link`, `_reel_add_form_context`, `_reel_list_context` (existing); `app.routers.map.render_map_html` (existing).
- Produces: `POST /ui/ai/multi/confirm` — same response shape (OOB refresh + `HX-Trigger: reel-saved`) as the existing `POST /ui/ai/confirm`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ai_multi_categorize.py`. First add these imports at the top of the file (alongside the existing ones):

```python
import html
import json

from app.models import Category, Reel
```

Then add:

```python
def test_ui_ai_multi_confirm_creates_reel_per_checked_place_sharing_the_link(client, session):
    hub = Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.add(Category(key="culture", label="Cultura", icon="⛩️", color="#35496B"))
    session.commit()
    session.refresh(hub)

    place_one = json.dumps({
        "place_name": "Fushimi Inari Taisha", "near_hub": "", "types": ["culture"],
        "note": "Torii gates", "lat": None, "lon": None, "matched_location_id": hub.id,
    })
    place_two = json.dumps({
        "place_name": "Kiyomizu-dera", "near_hub": "Kyoto - Osaka / Kansai", "types": ["culture"],
        "note": "Historic temple", "lat": 34.9949, "lon": 135.785, "matched_location_id": "",
    })

    response = client.post(
        "/ui/ai/multi/confirm",
        data={
            "link": "https://instagram.com/reel/kyoto10",
            "session_ids": ["s1", "s2"],
            "place_json": [place_one, place_two],
        },
    )

    assert response.status_code == 200
    reels = session.exec(select(Reel)).all()
    assert len(reels) == 2
    assert {r.link for r in reels} == {"https://instagram.com/reel/kyoto10"}
    kiyomizu = session.exec(select(Location).where(Location.name == "Kiyomizu-dera")).first()
    assert {r.location_id for r in reels} == {hub.id, kiyomizu.id}


def test_ui_ai_multi_confirm_only_creates_reels_for_checked_places(client, session):
    hub = Location(name="Kyoto - Osaka / Kansai", is_hub=True, lat=35.0116, lon=135.7681)
    session.add(hub)
    session.commit()
    session.refresh(hub)

    place_one = json.dumps({
        "place_name": "Fushimi Inari Taisha", "near_hub": "", "types": [],
        "note": "", "lat": None, "lon": None, "matched_location_id": hub.id,
    })

    response = client.post(
        "/ui/ai/multi/confirm",
        data={
            "link": "https://instagram.com/reel/kyoto10",
            "session_ids": ["s1", "s2"],
            "place_json": [place_one],
        },
    )

    assert response.status_code == 200
    assert len(session.exec(select(Reel)).all()) == 1


def test_ui_ai_multi_confirm_cleans_up_all_sessions_in_the_batch(client, session, monkeypatch):
    monkeypatch.setattr(
        ai_client,
        "detect_places",
        lambda message: {"is_multi_place": True, "place_names": ["Fushimi Inari Taisha", "Kiyomizu-dera"]},
    )
    results = iter([
        {"place_name": "Fushimi Inari Taisha", "near_hub": None, "types": [], "note": "",
         "confidence": "high", "question": None, "lat": 34.967, "lon": 135.772},
        {"place_name": "Kiyomizu-dera", "near_hub": None, "types": [], "note": "",
         "confidence": "high", "question": None, "lat": 34.9949, "lon": 135.785},
    ])
    monkeypatch.setattr(ai_client, "categorize", lambda hub_names, categories, messages: next(results))

    first = client.post(
        "/ui/ai/message",
        data={"link": "https://instagram.com/reel/kyoto10", "message": "2 posti a Kyoto"},
    )
    session_ids = re.findall(r'name="session_ids" value="([^"]+)"', first.text)
    place_jsons = [
        html.unescape(m) for m in re.findall(r"name=\"place_json\" value='([^']+)'", first.text)
    ]
    assert len(session_ids) == 2
    assert len(place_jsons) == 2

    response = client.post(
        "/ui/ai/multi/confirm",
        data={"link": "https://instagram.com/reel/kyoto10", "session_ids": session_ids, "place_json": place_jsons},
    )

    assert response.status_code == 200
    assert session.exec(select(AiSession)).all() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `ANTHROPIC_API_KEY=test uv run pytest tests/test_ai_multi_categorize.py -v`
Expected: the 3 new tests FAIL with 404 (`/ui/ai/multi/confirm` doesn't exist yet).

- [ ] **Step 3: Implement the confirm endpoint**

In `app/routers/ai_multi_categorize.py`, change the imports at the top to:

```python
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import AiMessage, AiSession
from app.routers.ai_categorize import (
    _build_ai_chat_context,
    _find_matching_location,
    _resolve_location_and_create_reel,
    _run_turn,
)
from app.routers.categories import get_taxonomy
from app.routers.map import render_map_html
from app.routers.reels import _is_safe_link, _reel_add_form_context, _reel_list_context
from app.web import templates
```

Then append this endpoint at the end of the file:

```python
@router.post("/confirm")
def ui_ai_multi_confirm(
    request: Request,
    link: str = Form(...),
    session_ids: list[str] = Form([]),
    place_json: list[str] = Form([]),
    session: Session = Depends(get_session),
):
    if not _is_safe_link(link):
        raise HTTPException(status_code=400, detail="link must be an http(s) URL")

    for raw in place_json:
        place = json.loads(raw)
        _resolve_location_and_create_reel(
            session,
            link,
            place["place_name"],
            place.get("near_hub", ""),
            place.get("types", []),
            place.get("note", ""),
            place.get("lat"),
            place.get("lon"),
            place.get("matched_location_id", ""),
        )

    for session_id in session_ids:
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
    map_html = render_map_html(session)
    form_html = templates.get_template("partials/reel_add_form.html").render(
        _reel_add_form_context(session)
    )

    response = HTMLResponse(
        ai_chat_html
        + f'<div hx-swap-oob="innerHTML:#reel-list">{reel_list_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#map-container">{map_html}</div>'
        + f'<div hx-swap-oob="innerHTML:#reel-add-form-panel">{form_html}</div>'
    )
    response.headers["HX-Trigger"] = "reel-saved"
    return response
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `ANTHROPIC_API_KEY=test uv run pytest tests/test_ai_multi_categorize.py -v`
Expected: PASS (all 7 tests in the file).

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `ANTHROPIC_API_KEY=test uv run pytest -v`
Expected: all tests passing, zero failures.

- [ ] **Step 6: Commit**

```bash
git add app/routers/ai_multi_categorize.py tests/test_ai_multi_categorize.py
git commit -m "feat: add multi-place confirm endpoint, creating one Reel per selected place"
```

---

## Manual Verification (not covered by automated tests)

The automated tests all mock `ai_client.detect_places`/`ai_client.categorize`, so none of them exercise a real multi-place classification or real per-place web-search resolution end-to-end. Before considering this feature done, manually verify against the running app:

1. Submit a real "top 10 places" reel caption (e.g. the Kyoto example that motivated this feature) and confirm it's detected as multi-place, each landmark resolves correctly (most should match or create satellites under the existing Kyoto hub), and the checklist renders with all of them pre-checked.
2. Uncheck a couple of rows, confirm, and verify only the checked ones become `Reel`s on the map/list — all sharing the same link.
3. Submit an ordinary single-place reel (e.g. one already tested manually for the Instagram-import feature) and confirm the flow is completely unchanged (no checklist, straight to the normal single-place confirm screen).
4. If possible, contrive a caption naming an obscure/fictional place among real ones, to see the per-row clarifying-question path render, answer it, and confirm that place joins the checklist alongside the others.
