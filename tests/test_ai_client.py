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
