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


def test_get_client_configures_a_request_timeout(monkeypatch):
    # Regression guard: without a bounded timeout, a stalled upstream call
    # hangs the underlying SDK request indefinitely instead of failing into
    # the app's existing AIProviderError fallback (observed live: a
    # multi-place import's synchronous per-place loop blocked for 4+
    # minutes on one categorize() call with no error, no timeout).
    monkeypatch.setattr(anthropic_provider, "_client", None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

    client = anthropic_provider.get_client()

    assert client.timeout == 15.0
