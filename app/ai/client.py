import json
import logging
import os
from typing import Any, Optional

from anthropic import Anthropic

from app.ai.prompts import (
    build_places_response_schema,
    build_places_system_prompt,
    build_response_schema,
    build_system_prompt,
)

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


def categorize(
    hub_names: list[str], categories: dict[str, str], messages: list[dict[str, str]]
) -> dict[str, Any]:
    client = get_client()
    system = build_system_prompt(hub_names, categories)
    schema = build_response_schema(categories.keys())
    logger.debug("categorize request hub_names=%s categories=%s messages=%s", hub_names, categories, messages)

    current_messages = list(messages)
    resumes = 0
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            messages=current_messages,
            tools=[WEB_SEARCH_TOOL],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if response.stop_reason == "pause_turn" and resumes < MAX_PAUSE_TURN_RESUMES:
            logger.debug("categorize search loop paused, resuming once")
            current_messages = current_messages + [{"role": "assistant", "content": response.content}]
            resumes += 1
            continue
        break

    text_block = next((block for block in response.content if block.type == "text"), None)
    if text_block is None:
        raise RuntimeError(
            f"categorize: no text block in final response (stop_reason={response.stop_reason!r})"
        )
    logger.debug("categorize raw response text=%s", text_block.text)
    return json.loads(text_block.text)


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
