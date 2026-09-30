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


def test_call_json_raises_ai_provider_error_when_output_text_is_none(monkeypatch):
    fake_client = FakeOpenAIClient(output_text=None)
    monkeypatch.setattr(openai_provider, "get_client", lambda: fake_client)

    with pytest.raises(AIProviderError):
        OpenAIProvider().call_json(
            system="sys", messages=[{"role": "user", "content": "x"}], schema={}, enable_web_search=False
        )
