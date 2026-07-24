import json
import logging
import os
from typing import Any, Optional

from anthropic import Anthropic

from app.ai.prompts import build_response_schema, build_system_prompt

MODEL = "claude-haiku-4-5"

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
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = next(block.text for block in response.content if block.type == "text")
    logger.debug("categorize raw response text=%s", text)
    return json.loads(text)
