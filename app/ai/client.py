import logging
import os
from typing import Any, Optional

from app.ai.prompts import (
    build_ask_response_schema,
    build_ask_system_prompt,
    build_compare_response_schema,
    build_compare_system_prompt,
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


def compare_places(
    place_a_name: str, place_a_notes: list[str], place_b_name: str, place_b_notes: list[str]
) -> dict[str, Any]:
    system = build_compare_system_prompt(place_a_name, place_a_notes, place_b_name, place_b_notes)
    schema = build_compare_response_schema()
    logger.debug(
        "compare_places request place_a_name=%s place_b_name=%s", place_a_name, place_b_name
    )
    return get_provider().call_json(
        system, [{"role": "user", "content": "Confronta i due posti."}], schema, enable_web_search=True
    )


def ask(
    reels: list[dict[str, Any]],
    location_name: Optional[str],
    category_label: Optional[str],
    truncated: bool,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    system = build_ask_system_prompt(reels, location_name, category_label, truncated)
    schema = build_ask_response_schema()
    logger.debug(
        "ask request location_name=%s category_label=%s truncated=%s messages=%s",
        location_name, category_label, truncated, messages,
    )
    return get_provider().call_json(system, messages, schema, enable_web_search=True)
