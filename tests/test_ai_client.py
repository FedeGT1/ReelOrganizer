import json
from types import SimpleNamespace

from app.ai import client as ai_client


class FakeMessages:
    def __init__(self, response_json: dict):
        self._response_json = response_json
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(self._response_json))]
        )


class FakeAnthropicClient:
    def __init__(self, response_json: dict):
        self.messages = FakeMessages(response_json)


def test_categorize_returns_parsed_json(monkeypatch):
    expected = {
        "place_name": "Ichiran Ramen",
        "near_hub": "Tokyo / Kanto",
        "types": ["food"],
        "note": "Famous ramen chain",
        "confidence": "high",
        "question": None,
    }
    fake_client = FakeAnthropicClient(expected)
    monkeypatch.setattr(ai_client, "get_client", lambda: fake_client)

    result = ai_client.categorize(["Tokyo / Kanto"], [{"role": "user", "content": "Ramen a Tokyo"}])

    assert result == expected
    assert fake_client.messages.last_call_kwargs["model"] == ai_client.MODEL
    assert fake_client.messages.last_call_kwargs["output_config"]["format"]["type"] == "json_schema"
