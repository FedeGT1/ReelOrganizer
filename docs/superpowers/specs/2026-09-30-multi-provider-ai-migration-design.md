# Multi-Provider AI Migration (Anthropic + OpenAI GPT-6 Luna) — Design

## Goal

Today the AI categorization/place-detection flow (`app/ai/client.py`) calls Claude Haiku 4.5 exclusively via the Anthropic SDK. The motivation for this change is cost: OpenAI's GPT-6 Luna (released 2026-09-22) prices at $0.10/1M input and $0.50/1M output tokens, materially cheaper than Haiku. Rather than a hard swap, the project wants the AI provider to be configurable at runtime via an environment variable, so cost/quality can be A/B tested and rolled back without a code change or redeploy.

This design introduces a thin provider abstraction so `categorize()` and `detect_places()` stay provider-agnostic, while provider-specific request/response handling (SDK shape, tool wiring, error types) is isolated per provider.

## Architecture

```
app/ai/
  client.py                    unchanged public surface: categorize(), detect_places()
  providers/
    __init__.py
    base.py                    Protocol AIProvider + AIProviderError
    anthropic_provider.py      existing Anthropic logic, moved here
    openai_provider.py         new: OpenAI Responses API, GPT-6 Luna
```

`app/ai/prompts.py` (prompt/schema building) is unchanged and shared by both providers — it doesn't know about the provider abstraction.

### `app/ai/providers/base.py`

```python
class AIProvider(Protocol):
    def call_json(
        self, system: str, messages: list[dict], schema: dict, enable_web_search: bool
    ) -> dict[str, Any]: ...

class AIProviderError(Exception):
    """Raised for any provider-specific SDK/API failure, wrapping the original error."""
```

### `app/ai/client.py`

Becomes a thin factory plus the two existing public functions, unchanged in signature:

```python
def get_provider() -> AIProvider:
    provider = os.environ.get("AI_PROVIDER", "anthropic")
    if provider == "openai":
        return OpenAIProvider()
    return AnthropicProvider()

def categorize(hub_names, categories, messages) -> dict[str, Any]:
    system = build_system_prompt(hub_names, categories)
    schema = build_response_schema(categories.keys())
    return get_provider().call_json(system, messages, schema, enable_web_search=True)

def detect_places(message) -> dict[str, Any]:
    system = build_places_system_prompt()
    schema = build_places_response_schema()
    return get_provider().call_json(
        system, [{"role": "user", "content": message}], schema, enable_web_search=False
    )
```

`categorize`/`detect_places` no longer know which provider is active — they build prompts/schema (identical today) and delegate the model call.

### `app/ai/providers/anthropic_provider.py`

Moves the current `client.py` implementation as-is: `MODEL = "claude-haiku-4-5"`, `WEB_SEARCH_TOOL`, the `pause_turn`/resume loop (`MAX_PAUSE_TURN_RESUMES`), text-block extraction, `json.loads`. Wraps `anthropic.AnthropicError` into `AIProviderError`:

```python
class AnthropicProvider:
    def call_json(self, system, messages, schema, enable_web_search):
        client = get_client()
        tools = [WEB_SEARCH_TOOL] if enable_web_search else []
        try:
            # existing pause_turn/resume loop, using `tools` and
            # output_config={"format": {"type": "json_schema", "schema": schema}}
            ...
        except anthropic.AnthropicError as e:
            raise AIProviderError(str(e)) from e
        return json.loads(text_block.text)
```

### `app/ai/providers/openai_provider.py`

Uses the OpenAI Responses API, which composes `web_search` tool use and `json_schema` structured output in a single call — the tool loop is handled server-side, so (unlike Anthropic) no client-side resume logic is needed:

```python
class OpenAIProvider:
    MODEL = "gpt-6-luna"

    def call_json(self, system, messages, schema, enable_web_search):
        client = get_client()  # OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        effort = os.environ.get("AI_REASONING_EFFORT", "medium")
        tools = [{"type": "web_search"}] if enable_web_search else []
        try:
            response = client.responses.create(
                model=self.MODEL,
                input=[{"role": "system", "content": system}, *messages],
                tools=tools,
                text={"format": {"type": "json_schema", "schema": schema}},
                reasoning={"effort": effort},
            )
        except openai.OpenAIError as e:
            raise AIProviderError(str(e)) from e
        return json.loads(response.output_text)
```

**Verification note:** the exact Responses API field names (`output_text`, the shape of `input`/`text.format`/`reasoning`) must be confirmed against the installed `openai` SDK version during implementation — this is the expected contract based on public docs, not yet exercised against a real response.

## Data Flow

1. `categorize()`/`detect_places()` build `system`/`schema` exactly as today (no change).
2. `get_provider()` reads `AI_PROVIDER` (default `"anthropic"`) and returns the matching provider instance.
3. The provider's `call_json()` makes the actual model call:
   - **Anthropic**: may loop once on `pause_turn` before returning, extracts the final `text` content block, `json.loads`s it.
   - **OpenAI**: single `responses.create()` call (server-side tool loop), `json.loads`s `output_text`.
4. Both paths return a plain `dict[str, Any]` — callers in `app/routers/ai_categorize.py` are unaffected by which provider ran.

## Error Handling

`app/routers/ai_categorize.py` currently catches `anthropic.AnthropicError` in two places (lines 133, 256). Both become:

```python
# from: except (anthropic.AnthropicError, RuntimeError):
except (AIProviderError, RuntimeError):
    ...
# from: except (anthropic.AnthropicError, RuntimeError, json.JSONDecodeError):
except (AIProviderError, RuntimeError, json.JSONDecodeError):
    ...
```

`import anthropic` in this file is replaced with `from app.ai.providers.base import AIProviderError`. The router no longer needs to know which SDK is active — any provider failure surfaces uniformly.

## Configuration

- `AI_PROVIDER` — `"anthropic"` (default, preserves current behavior) or `"openai"`.
- `OPENAI_API_KEY` — required only when `AI_PROVIDER=openai`; read lazily inside `OpenAIProvider`'s client getter (same lazy-fail pattern as the existing `ANTHROPIC_API_KEY` read), so it's not required when the OpenAI provider isn't selected.
- `AI_REASONING_EFFORT` — optional, default `"medium"`, ignored by the Anthropic provider.
- `ANTHROPIC_API_KEY` — unchanged, still required when `AI_PROVIDER=anthropic` (the default).

`pyproject.toml`: add `"openai>=1.0.0"` alongside the existing `"anthropic>=0.69.0"` (exact minimum version to be confirmed against the SDK version that supports the Responses API shape used here, at implementation time). Neither dependency is removed.

**Deploy**: README and the VM deployment docs/scripts gain the two new optional env vars (`-e AI_PROVIDER=... -e OPENAI_API_KEY=...` in the `docker run` examples), alongside the existing `ANTHROPIC_API_KEY` flag. No change to volume mounts or other deployment mechanics.

## Testing

- `tests/test_ai_client.py` — refocused to test `get_provider()` dispatch and that `categorize()`/`detect_places()` build the correct `system`/`schema` and call `provider.call_json(...)` with the right arguments, mocking the `AIProvider` protocol directly (provider-agnostic).
- `tests/providers/test_anthropic_provider.py` (new location) — the existing mocking style (`SimpleNamespace(content=..., stop_reason=...)`, `pause_turn` resume loop) moves here unchanged, now exercising `AnthropicProvider.call_json` directly.
- `tests/providers/test_openai_provider.py` (new) — mocks `client.responses.create` to exercise `OpenAIProvider.call_json`, including the `AI_REASONING_EFFORT` env var being forwarded and `openai.OpenAIError` being wrapped into `AIProviderError`.
- `tests/test_ai_categorize.py` (lines ~192, ~225) and `tests/test_ai_ui.py` (line ~442) — these directly `raise anthropic.AnthropicError("boom")` when mocking `ai_client.categorize`/`detect_places` to test the router's error-fallback path. Update these three call sites to `raise AIProviderError("boom")`, importing from `app.ai.providers.base`. No other changes needed in these files — they mock `ai_client.categorize`/`detect_places` at the function boundary, not the SDK, so they're otherwise provider-agnostic already.

## Out of Scope

- Removing the Anthropic provider or `anthropic` dependency — both providers stay available indefinitely per the "configurable, not replaced" decision.
- Any change to the actual categorization/place-detection prompts or JSON schemas — identical output contract expected from both providers.
- Automated cost/quality comparison tooling between providers — provider choice is a manual env var flip for now.
