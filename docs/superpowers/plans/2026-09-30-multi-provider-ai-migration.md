# Multi-Provider AI Migration (Anthropic + OpenAI GPT-6 Luna) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AI provider behind `app/ai/client.py`'s `categorize()`/`detect_places()` configurable at runtime between Anthropic (Claude Haiku 4.5, default) and OpenAI (GPT-6 Luna), driven by an `AI_PROVIDER` env var, so cost/quality can be compared without a redeploy.

**Architecture:** Extract a small `AIProvider` protocol (`call_json(system, messages, schema, enable_web_search) -> dict`) into `app/ai/providers/base.py`. Move the existing Anthropic logic into `app/ai/providers/anthropic_provider.py` unchanged in behavior. Add a new `app/ai/providers/openai_provider.py` using OpenAI's Responses API. `app/ai/client.py` becomes a thin factory (`get_provider()`) plus the two existing public functions, which build prompts/schema (unchanged, from `app/ai/prompts.py`) and delegate the model call. `app/routers/ai_categorize.py` catches the new provider-agnostic `AIProviderError` instead of `anthropic.AnthropicError`.

**Tech Stack:** Python 3.11+, FastAPI, `anthropic` SDK (existing), `openai` SDK (new, added via `uv add openai`), pytest with `monkeypatch`.

## Global Constraints

- `AI_PROVIDER` env var: `"anthropic"` (default) or `"openai"` — read in `app/ai/client.py:get_provider()`.
- `OPENAI_API_KEY` is required only when `AI_PROVIDER=openai`; read lazily inside `OpenAIProvider`'s client getter, same lazy-fail pattern as the existing `ANTHROPIC_API_KEY` read — must not be required at import time or when the Anthropic provider is active.
- `AI_REASONING_EFFORT` env var: optional, default `"medium"`, read inside `OpenAIProvider.call_json`; ignored by `AnthropicProvider`.
- `ANTHROPIC_API_KEY` requirement is unchanged (still required when `AI_PROVIDER=anthropic`, the default).
- Model identifiers: Anthropic provider uses `"claude-haiku-4-5"` (unchanged). OpenAI provider uses `"gpt-6-luna"`.
- Do not remove the `anthropic` dependency, `AnthropicProvider`, or any Anthropic-specific behavior — both providers must remain available indefinitely (out of scope: hard cutover).
- Do not change the categorization/place-detection prompts or JSON schemas in `app/ai/prompts.py` — both providers must produce the same output contract.
- New OpenAI dependency added via `uv add openai` (let `uv` resolve the version, not a hand-picked pin).

---

### Task 1: Provider interface and shared error type

**Files:**
- Create: `app/ai/providers/__init__.py`
- Create: `app/ai/providers/base.py`
- Test: `tests/test_ai_provider_base.py`

**Interfaces:**
- Consumes: nothing (this is the foundational contract).
- Produces: `AIProvider` (a `typing.Protocol` with method `call_json(self, system: str, messages: list[dict], schema: dict, enable_web_search: bool) -> dict[str, Any]`) and `AIProviderError(Exception)`, both importable from `app.ai.providers.base`. Tasks 2, 3, 4, and 5 all import from here.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ai_provider_base.py`:

```python
from app.ai.providers.base import AIProviderError


def test_ai_provider_error_is_an_exception_with_message():
    err = AIProviderError("boom")
    assert isinstance(err, Exception)
    assert str(err) == "boom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_provider_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ai.providers'`

- [ ] **Step 3: Create the providers package and base module**

Create `app/ai/providers/__init__.py` (empty file).

Create `app/ai/providers/base.py`:

```python
from typing import Any, Protocol


class AIProvider(Protocol):
    def call_json(
        self, system: str, messages: list[dict], schema: dict, enable_web_search: bool
    ) -> dict[str, Any]: ...


class AIProviderError(Exception):
    """Raised for any provider-specific SDK/API failure, wrapping the original error."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_provider_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ai/providers/__init__.py app/ai/providers/base.py tests/test_ai_provider_base.py
git commit -m "feat: add AIProvider protocol and AIProviderError"
```

---

### Task 2: Anthropic provider (move existing logic)

This task is purely additive: it creates a new module that duplicates the current `app/ai/client.py` logic behind the `AIProvider` interface. `app/ai/client.py` itself is untouched here (it still works exactly as before) — Task 4 swaps it over to delegate to this new module. This keeps every task independently green.

**Files:**
- Create: `app/ai/providers/anthropic_provider.py`
- Test: `tests/test_anthropic_provider.py`

**Interfaces:**
- Consumes: `AIProviderError` from `app.ai.providers.base` (Task 1).
- Produces: `AnthropicProvider` class with `call_json(self, system, messages, schema, enable_web_search) -> dict[str, Any]`, plus module-level `MODEL = "claude-haiku-4-5"`, `WEB_SEARCH_TOOL`, `get_client()` — all importable from `app.ai.providers.anthropic_provider`. Task 4 imports `AnthropicProvider` from here.

- [ ] **Step 1: Write the failing test**

Create `tests/test_anthropic_provider.py`:

```python
import json
from types import SimpleNamespace

import anthropic
import pytest

from app.ai.providers import anthropic_provider
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.base import AIProviderError


class FakeMessages:
    """Test double for `client.messages`. Accepts either a single
    `response_json` (single-turn) or a list of `{"json": ..., "stop_reason": ...}`
    dicts for multi-call (pause_turn resume) scenarios. `json: None` simulates
    a response with no text block (e.g. a paused turn that only did tool
    work). If `error` is set, `create()` raises it instead of returning."""

    def __init__(self, responses=None, response_json=None, error=None):
        if responses is None:
            responses = [{"json": response_json, "stop_reason": "end_turn"}]
        self._responses = responses
        self._error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
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
    def __init__(self, responses=None, response_json=None, error=None):
        self.messages = FakeMessages(responses=responses, response_json=response_json, error=error)


def test_call_json_returns_parsed_json(monkeypatch):
    expected = {"place_name": "Ichiran Ramen", "near_hub": "Tokyo / Kanto"}
    fake_client = FakeAnthropicClient(response_json=expected)
    monkeypatch.setattr(anthropic_provider, "get_client", lambda: fake_client)

    result = AnthropicProvider().call_json(
        system="sys",
        messages=[{"role": "user", "content": "Ramen a Tokyo"}],
        schema={"type": "object"},
        enable_web_search=True,
    )

    assert result == expected
    assert fake_client.messages.last_call_kwargs["model"] == anthropic_provider.MODEL
    assert fake_client.messages.last_call_kwargs["output_config"]["format"]["type"] == "json_schema"


def test_call_json_includes_web_search_tool_when_enabled(monkeypatch):
    fake_client = FakeAnthropicClient(response_json={"ok": True})
    monkeypatch.setattr(anthropic_provider, "get_client", lambda: fake_client)

    AnthropicProvider().call_json(
        system="sys", messages=[{"role": "user", "content": "x"}], schema={}, enable_web_search=True
    )

    assert fake_client.messages.last_call_kwargs["tools"] == [anthropic_provider.WEB_SEARCH_TOOL]


def test_call_json_omits_web_search_tool_when_disabled(monkeypatch):
    fake_client = FakeAnthropicClient(response_json={"ok": True})
    monkeypatch.setattr(anthropic_provider, "get_client", lambda: fake_client)

    AnthropicProvider().call_json(
        system="sys", messages=[{"role": "user", "content": "x"}], schema={}, enable_web_search=False
    )

    assert fake_client.messages.last_call_kwargs["tools"] == []


def test_call_json_resumes_once_after_pause_turn(monkeypatch):
    final_json = {"place_name": "Dragon Ball Store"}
    fake_client = FakeAnthropicClient(responses=[
        {"json": None, "stop_reason": "pause_turn"},
        {"json": final_json, "stop_reason": "end_turn"},
    ])
    monkeypatch.setattr(anthropic_provider, "get_client", lambda: fake_client)

    result = AnthropicProvider().call_json(
        system="sys",
        messages=[{"role": "user", "content": "Dragon Ball store a Tokyo"}],
        schema={},
        enable_web_search=True,
    )

    assert result == final_json
    assert len(fake_client.messages.calls) == 2
    assert fake_client.messages.calls[1]["messages"][-1]["role"] == "assistant"


def test_call_json_raises_after_second_consecutive_pause_turn(monkeypatch):
    fake_client = FakeAnthropicClient(responses=[
        {"json": None, "stop_reason": "pause_turn"},
        {"json": None, "stop_reason": "pause_turn"},
    ])
    monkeypatch.setattr(anthropic_provider, "get_client", lambda: fake_client)

    with pytest.raises(RuntimeError):
        AnthropicProvider().call_json(
            system="sys", messages=[{"role": "user", "content": "x"}], schema={}, enable_web_search=True
        )


def test_call_json_wraps_anthropic_error(monkeypatch):
    fake_client = FakeAnthropicClient(error=anthropic.AnthropicError("boom"))
    monkeypatch.setattr(anthropic_provider, "get_client", lambda: fake_client)

    with pytest.raises(AIProviderError):
        AnthropicProvider().call_json(
            system="sys", messages=[{"role": "user", "content": "x"}], schema={}, enable_web_search=True
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_anthropic_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ai.providers.anthropic_provider'`

- [ ] **Step 3: Implement the Anthropic provider**

Create `app/ai/providers/anthropic_provider.py`:

```python
import json
import logging
import os
from typing import Any, Optional

import anthropic
from anthropic import Anthropic

from app.ai.providers.base import AIProviderError

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


class AnthropicProvider:
    MODEL = MODEL

    def call_json(
        self, system: str, messages: list[dict], schema: dict, enable_web_search: bool
    ) -> dict[str, Any]:
        client = get_client()
        tools = [WEB_SEARCH_TOOL] if enable_web_search else []
        current_messages = list(messages)
        resumes = 0
        try:
            while True:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    system=system,
                    messages=current_messages,
                    tools=tools,
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                )
                if response.stop_reason == "pause_turn" and resumes < MAX_PAUSE_TURN_RESUMES:
                    logger.debug("call_json search loop paused, resuming once")
                    current_messages = current_messages + [
                        {"role": "assistant", "content": response.content}
                    ]
                    resumes += 1
                    continue
                break
        except anthropic.AnthropicError as e:
            raise AIProviderError(str(e)) from e

        text_block = next((block for block in response.content if block.type == "text"), None)
        if text_block is None:
            raise RuntimeError(
                f"call_json: no text block in final response (stop_reason={response.stop_reason!r})"
            )
        logger.debug("call_json raw response text=%s", text_block.text)
        return json.loads(text_block.text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_anthropic_provider.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add app/ai/providers/anthropic_provider.py tests/test_anthropic_provider.py
git commit -m "feat: add AnthropicProvider implementing AIProvider"
```

---

### Task 3: OpenAI provider (GPT-6 Luna)

**Files:**
- Modify: `pyproject.toml` (add `openai` dependency via `uv add`)
- Create: `app/ai/providers/openai_provider.py`
- Test: `tests/test_openai_provider.py`

**Interfaces:**
- Consumes: `AIProviderError` from `app.ai.providers.base` (Task 1).
- Produces: `OpenAIProvider` class with `call_json(self, system, messages, schema, enable_web_search) -> dict[str, Any]`, plus module-level `MODEL = "gpt-6-luna"`, `get_client()` — all importable from `app.ai.providers.openai_provider`. Task 4 imports `OpenAIProvider` from here.

- [ ] **Step 1: Add the openai dependency**

Run: `uv add openai`
Expected: `pyproject.toml` gains an `"openai>=..."` line under `dependencies`, `uv.lock` is updated.

- [ ] **Step 2: Commit the dependency bump**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add openai dependency"
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_openai_provider.py`:

```python
import json
from types import SimpleNamespace

import openai
import pytest

from app.ai.providers import openai_provider
from app.ai.providers.base import AIProviderError
from app.ai.providers.openai_provider import OpenAIProvider


class FakeResponses:
    """Test double for `client.responses`. Returns a response with the given
    `output_text` (a JSON string), or raises `error` if set instead."""

    def __init__(self, output_text=None, error=None):
        self._output_text = output_text
        self._error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return SimpleNamespace(output_text=self._output_text)

    @property
    def last_call_kwargs(self):
        return self.calls[-1] if self.calls else None


class FakeOpenAIClient:
    def __init__(self, output_text=None, error=None):
        self.responses = FakeResponses(output_text=output_text, error=error)


def test_call_json_returns_parsed_json(monkeypatch):
    expected = {"place_name": "Ichiran Ramen", "near_hub": "Tokyo / Kanto"}
    fake_client = FakeOpenAIClient(output_text=json.dumps(expected))
    monkeypatch.setattr(openai_provider, "get_client", lambda: fake_client)
    monkeypatch.delenv("AI_REASONING_EFFORT", raising=False)

    result = OpenAIProvider().call_json(
        system="sys",
        messages=[{"role": "user", "content": "Ramen a Tokyo"}],
        schema={"type": "object"},
        enable_web_search=True,
    )

    assert result == expected
    call = fake_client.responses.last_call_kwargs
    assert call["model"] == openai_provider.MODEL
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["input"][0] == {"role": "system", "content": "sys"}
    assert call["input"][1:] == [{"role": "user", "content": "Ramen a Tokyo"}]


def test_call_json_includes_web_search_tool_when_enabled(monkeypatch):
    fake_client = FakeOpenAIClient(output_text=json.dumps({"ok": True}))
    monkeypatch.setattr(openai_provider, "get_client", lambda: fake_client)

    OpenAIProvider().call_json(
        system="sys", messages=[{"role": "user", "content": "x"}], schema={}, enable_web_search=True
    )

    assert fake_client.responses.last_call_kwargs["tools"] == [{"type": "web_search"}]


def test_call_json_omits_web_search_tool_when_disabled(monkeypatch):
    fake_client = FakeOpenAIClient(output_text=json.dumps({"ok": True}))
    monkeypatch.setattr(openai_provider, "get_client", lambda: fake_client)

    OpenAIProvider().call_json(
        system="sys", messages=[{"role": "user", "content": "x"}], schema={}, enable_web_search=False
    )

    assert fake_client.responses.last_call_kwargs["tools"] == []


def test_call_json_defaults_reasoning_effort_to_medium(monkeypatch):
    fake_client = FakeOpenAIClient(output_text=json.dumps({"ok": True}))
    monkeypatch.setattr(openai_provider, "get_client", lambda: fake_client)
    monkeypatch.delenv("AI_REASONING_EFFORT", raising=False)

    OpenAIProvider().call_json(
        system="sys", messages=[{"role": "user", "content": "x"}], schema={}, enable_web_search=False
    )

    assert fake_client.responses.last_call_kwargs["reasoning"] == {"effort": "medium"}


def test_call_json_uses_reasoning_effort_env_var_when_set(monkeypatch):
    fake_client = FakeOpenAIClient(output_text=json.dumps({"ok": True}))
    monkeypatch.setattr(openai_provider, "get_client", lambda: fake_client)
    monkeypatch.setenv("AI_REASONING_EFFORT", "low")

    OpenAIProvider().call_json(
        system="sys", messages=[{"role": "user", "content": "x"}], schema={}, enable_web_search=False
    )

    assert fake_client.responses.last_call_kwargs["reasoning"] == {"effort": "low"}


def test_call_json_wraps_openai_error(monkeypatch):
    fake_client = FakeOpenAIClient(error=openai.OpenAIError("boom"))
    monkeypatch.setattr(openai_provider, "get_client", lambda: fake_client)

    with pytest.raises(AIProviderError):
        OpenAIProvider().call_json(
            system="sys", messages=[{"role": "user", "content": "x"}], schema={}, enable_web_search=False
        )
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_openai_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ai.providers.openai_provider'`

- [ ] **Step 5: Implement the OpenAI provider**

Create `app/ai/providers/openai_provider.py`:

```python
import json
import logging
import os
from typing import Any, Optional

import openai
from openai import OpenAI

from app.ai.providers.base import AIProviderError

MODEL = "gpt-6-luna"

_client: Optional[OpenAI] = None

logger = logging.getLogger("app.ai")


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


class OpenAIProvider:
    MODEL = MODEL

    def call_json(
        self, system: str, messages: list[dict], schema: dict, enable_web_search: bool
    ) -> dict[str, Any]:
        client = get_client()
        effort = os.environ.get("AI_REASONING_EFFORT", "medium")
        tools = [{"type": "web_search"}] if enable_web_search else []
        try:
            response = client.responses.create(
                model=MODEL,
                input=[{"role": "system", "content": system}, *messages],
                tools=tools,
                text={"format": {"type": "json_schema", "schema": schema}},
                reasoning={"effort": effort},
            )
        except openai.OpenAIError as e:
            raise AIProviderError(str(e)) from e

        logger.debug("call_json raw response output_text=%s", response.output_text)
        return json.loads(response.output_text)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_openai_provider.py -v`
Expected: PASS (6 tests)

If this fails because the installed `openai` SDK's `responses.create()` signature or response shape differs from what's assumed here (e.g. a different field name than `output_text`, or `text`/`reasoning` nested differently), check the installed version's docs (`python -c "import openai; print(openai.__version__)"` then consult that version's Responses API reference) and adjust `openai_provider.py` and the test doubles' shape to match — the contract in this task is the intended design, not yet verified against a live response.

- [ ] **Step 7: Commit**

```bash
git add app/ai/providers/openai_provider.py tests/test_openai_provider.py
git commit -m "feat: add OpenAIProvider implementing AIProvider (GPT-6 Luna)"
```

---

### Task 4: Refactor `app/ai/client.py` into a provider dispatcher

This task deletes the old inline Anthropic implementation from `client.py` (now duplicated in `AnthropicProvider`, Task 2) and replaces it with delegation. It also replaces `tests/test_ai_client.py` entirely — the old tests assert on `ai_client.MODEL`/`ai_client.get_client`, which no longer exist on this module after this change (they moved to `anthropic_provider.py` in Task 2).

**Files:**
- Modify: `app/ai/client.py` (full rewrite)
- Modify: `tests/test_ai_client.py` (full rewrite)

**Interfaces:**
- Consumes: `AnthropicProvider` (Task 2), `OpenAIProvider` (Task 3), `AIProvider` (Task 1), `build_system_prompt`/`build_response_schema`/`build_places_system_prompt`/`build_places_response_schema` (existing, `app/ai/prompts.py`).
- Produces: `get_provider() -> AIProvider`, `categorize(hub_names, categories, messages) -> dict[str, Any]`, `detect_places(message) -> dict[str, Any]` — unchanged public signatures, consumed by `app/routers/ai_categorize.py` (Task 5) and `app/routers/ai_multi_categorize.py` (unchanged, not touched by this plan).

- [ ] **Step 1: Write the failing test**

Replace the entire contents of `tests/test_ai_client.py`:

```python
import pytest

from app.ai import client as ai_client


class FakeProvider:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def call_json(self, system, messages, schema, enable_web_search):
        self.calls.append(
            {"system": system, "messages": messages, "schema": schema, "enable_web_search": enable_web_search}
        )
        return self._result


def test_categorize_delegates_to_provider_with_built_prompt_and_schema(monkeypatch):
    expected = {
        "place_name": "Ichiran Ramen",
        "near_hub": "Tokyo / Kanto",
        "types": ["food"],
        "note": "Famous ramen chain",
        "confidence": "high",
        "question": None,
    }
    fake_provider = FakeProvider(expected)
    monkeypatch.setattr(ai_client, "get_provider", lambda: fake_provider)

    result = ai_client.categorize(
        ["Tokyo / Kanto"], {"food": "Cibo"}, [{"role": "user", "content": "Ramen a Tokyo"}]
    )

    assert result == expected
    call = fake_provider.calls[0]
    assert call["enable_web_search"] is True
    assert call["messages"] == [{"role": "user", "content": "Ramen a Tokyo"}]
    assert "Tokyo / Kanto" in call["system"]
    assert call["schema"]["properties"]["types"]["items"]["enum"] == ["food"]


def test_detect_places_delegates_to_provider_without_web_search(monkeypatch):
    expected = {"is_multi_place": False, "place_names": None}
    fake_provider = FakeProvider(expected)
    monkeypatch.setattr(ai_client, "get_provider", lambda: fake_provider)

    result = ai_client.detect_places("Un tempio bellissimo a Kyoto")

    assert result == expected
    call = fake_provider.calls[0]
    assert call["enable_web_search"] is False
    assert call["messages"] == [{"role": "user", "content": "Un tempio bellissimo a Kyoto"}]


def test_detect_places_returns_multi_place_result(monkeypatch):
    expected = {
        "is_multi_place": True,
        "place_names": ["Fushimi Inari Taisha", "Kiyomizu-dera", "Kinkaku-ji"],
    }
    fake_provider = FakeProvider(expected)
    monkeypatch.setattr(ai_client, "get_provider", lambda: fake_provider)

    result = ai_client.detect_places("10 luoghi imperdibili a Kyoto: ...")

    assert result == expected


def test_get_provider_defaults_to_anthropic(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    from app.ai.providers.anthropic_provider import AnthropicProvider

    assert isinstance(ai_client.get_provider(), AnthropicProvider)


def test_get_provider_returns_openai_when_env_set(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    from app.ai.providers.openai_provider import OpenAIProvider

    assert isinstance(ai_client.get_provider(), OpenAIProvider)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_client.py -v`
Expected: FAIL — `AttributeError: module 'app.ai.client' has no attribute 'get_provider'` (the old `client.py` doesn't define it yet)

- [ ] **Step 3: Rewrite `app/ai/client.py`**

Replace the entire contents of `app/ai/client.py`:

```python
import logging
import os
from typing import Any

from app.ai.prompts import (
    build_places_response_schema,
    build_places_system_prompt,
    build_response_schema,
    build_system_prompt,
)
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.base import AIProvider
from app.ai.providers.openai_provider import OpenAIProvider

logger = logging.getLogger("app.ai")


def get_provider() -> AIProvider:
    provider = os.environ.get("AI_PROVIDER", "anthropic")
    if provider == "openai":
        return OpenAIProvider()
    return AnthropicProvider()


def categorize(
    hub_names: list[str], categories: dict[str, str], messages: list[dict[str, str]]
) -> dict[str, Any]:
    system = build_system_prompt(hub_names, categories)
    schema = build_response_schema(categories.keys())
    logger.debug(
        "categorize request hub_names=%s categories=%s messages=%s", hub_names, categories, messages
    )
    return get_provider().call_json(system, messages, schema, enable_web_search=True)


def detect_places(message: str) -> dict[str, Any]:
    system = build_places_system_prompt()
    schema = build_places_response_schema()
    logger.debug("detect_places request message=%s", message)
    return get_provider().call_json(
        system, [{"role": "user", "content": message}], schema, enable_web_search=False
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_client.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `uv run pytest -v`
Expected: All tests pass except (at most) the ones this plan hasn't reached yet — specifically `tests/test_ai_categorize.py` and `tests/test_ai_ui.py` should still be green here, since they monkeypatch `ai_client.categorize`/`ai_client.detect_places` directly (unaffected by this internal refactor) and the router still imports `anthropic` (untouched until Task 5).

- [ ] **Step 6: Commit**

```bash
git add app/ai/client.py tests/test_ai_client.py
git commit -m "refactor: dispatch app/ai/client.py to a configurable AIProvider"
```

---

### Task 5: Provider-agnostic error handling in the router

**Files:**
- Modify: `app/routers/ai_categorize.py:5` (import), `:133` (except), `:256` (except)
- Modify: `tests/test_ai_categorize.py:3` (import), `:192`, `:225` (raise sites)
- Modify: `tests/test_ai_ui.py:3` (import), `:442` (raise site)

**Interfaces:**
- Consumes: `AIProviderError` from `app.ai.providers.base` (Task 1).
- Produces: no new symbols; the router's failure-handling behavior (falling back to a friendly "riprova" question) becomes provider-agnostic.

- [ ] **Step 1: Update the failing-behavior tests to use `AIProviderError`**

In `tests/test_ai_categorize.py`, replace the import block at the top:

```python
import json

import anthropic
from sqlmodel import select

from app.ai import client as ai_client
```

with:

```python
import json

from sqlmodel import select

from app.ai import client as ai_client
from app.ai.providers.base import AIProviderError
```

Then replace both occurrences of:

```python
    def boom(hub_names, categories, messages):
        raise anthropic.AnthropicError("boom")
```

with:

```python
    def boom(hub_names, categories, messages):
        raise AIProviderError("boom")
```

(these are the `boom` helpers inside `test_categorize_returns_friendly_question_when_ai_call_fails` and `test_empty_place_name_does_not_spuriously_match_location`).

In `tests/test_ai_ui.py`, replace the import block at the top:

```python
import json

import anthropic
from sqlmodel import select
```

with:

```python
import json

from sqlmodel import select
```

and add the new import alongside the existing `from app.ai import client as ai_client` line:

```python
from app.ai import client as ai_client
from app.ai.providers.base import AIProviderError
```

Then in `test_ui_ai_message_shows_friendly_error_when_ai_call_fails`, replace:

```python
    def boom(hub_names, categories, messages):
        raise anthropic.AnthropicError("boom")
```

with:

```python
    def boom(hub_names, categories, messages):
        raise AIProviderError("boom")
```

- [ ] **Step 2: Run the affected tests to verify they fail**

Run: `uv run pytest tests/test_ai_categorize.py tests/test_ai_ui.py -v`
Expected: FAIL — the three updated tests now raise `AIProviderError`, which the router doesn't catch yet (it still only catches `anthropic.AnthropicError`), so these requests will 500 instead of returning the friendly fallback.

- [ ] **Step 3: Update `app/routers/ai_categorize.py`**

Replace the import at line 5:

```python
import anthropic
```

with:

```python
from app.ai.providers.base import AIProviderError
```

(keep it in the same alphabetical position among the existing imports — right before the `fastapi` import block, matching where `import anthropic` currently sits).

Replace line 133:

```python
    except (anthropic.AnthropicError, RuntimeError):
```

with:

```python
    except (AIProviderError, RuntimeError):
```

Replace line 256:

```python
        except (anthropic.AnthropicError, RuntimeError, json.JSONDecodeError):
```

with:

```python
        except (AIProviderError, RuntimeError, json.JSONDecodeError):
```

- [ ] **Step 4: Run the affected tests to verify they pass**

Run: `uv run pytest tests/test_ai_categorize.py tests/test_ai_ui.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/routers/ai_categorize.py tests/test_ai_categorize.py tests/test_ai_ui.py
git commit -m "refactor: catch provider-agnostic AIProviderError in ai_categorize router"
```

---

### Task 6: Document the provider configuration

**Files:**
- Modify: `README.md:10` (stack description), `:15-22` (local run env vars), `:47-56` (docker run example)

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing consumed by other tasks; this is the last task.

- [ ] **Step 1: Update the stack description**

In `README.md`, replace line 10:

```markdown
- **AI**: Anthropic Python SDK (`claude-haiku-4-5`) with structured JSON output and a web-search tool for categorization
```

with:

```markdown
- **AI**: configurable provider via `AI_PROVIDER` env var — Anthropic Python SDK (`claude-haiku-4-5`, default) or OpenAI Python SDK (`gpt-6-luna`); both use structured JSON output and a web-search tool for categorization
```

- [ ] **Step 2: Document the new env vars in "Running locally"**

In `README.md`, after the existing paragraph that ends `...The app refuses to start if any of the three is missing.` (currently line 24), insert a new paragraph:

```markdown
By default the app uses Anthropic (`ANTHROPIC_API_KEY` required, as above). To use OpenAI's `gpt-6-luna` instead, set `AI_PROVIDER=openai` and `OPENAI_API_KEY=sk-...`; `AI_REASONING_EFFORT` (`none`/`low`/`medium`/`high`/`xhigh`/`max`, default `medium`) tunes its cost/latency/quality trade-off and is ignored when using Anthropic.
```

- [ ] **Step 3: Update the Docker run example**

In `README.md`, replace the `docker run` block (currently lines 47-56):

```bash
docker run -d \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v "/absolute/path/to/reelorganizer/data:/data" \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e AUTH_USERNAME="$AUTH_USERNAME" \
  -e AUTH_PASSWORD="$AUTH_PASSWORD" \
  -e SESSION_SECRET_KEY="$SESSION_SECRET_KEY" \
  --name reel-organizer japan-reel-organizer
```

with:

```bash
docker run -d \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v "/absolute/path/to/reelorganizer/data:/data" \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e AUTH_USERNAME="$AUTH_USERNAME" \
  -e AUTH_PASSWORD="$AUTH_PASSWORD" \
  -e SESSION_SECRET_KEY="$SESSION_SECRET_KEY" \
  --name reel-organizer japan-reel-organizer
```

(unchanged — omit the optional `AI_PROVIDER`/`OPENAI_API_KEY`/`AI_REASONING_EFFORT` vars from the base example, since the default Anthropic setup needs no new flags) and add a new sentence directly below the block, after the existing "Binding to 127.0.0.1:8000..." paragraph:

```markdown
To run with the OpenAI provider instead, add `-e AI_PROVIDER="$AI_PROVIDER" -e OPENAI_API_KEY="$OPENAI_API_KEY"` (and optionally `-e AI_REASONING_EFFORT="$AI_REASONING_EFFORT"`) to the `docker run` command above.
```

- [ ] **Step 4: Verify the new env vars are documented**

Run: `grep -n "AI_PROVIDER\|OPENAI_API_KEY\|AI_REASONING_EFFORT" README.md`
Expected: at least 3 matching lines (the stack description, the local-run paragraph, and the Docker note).

- [ ] **Step 5: Run the full suite one last time**

Run: `uv run pytest -v`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: document AI_PROVIDER/OPENAI_API_KEY/AI_REASONING_EFFORT env vars"
```
