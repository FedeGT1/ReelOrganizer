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
