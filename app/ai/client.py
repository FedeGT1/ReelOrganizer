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
