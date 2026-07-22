import json
import os
from typing import Any, Optional

from anthropic import Anthropic

from app.ai.prompts import RESPONSE_SCHEMA, build_system_prompt

MODEL = "claude-haiku-4-5"

_client: Optional[Anthropic] = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def categorize(hub_names: list[str], messages: list[dict[str, str]]) -> dict[str, Any]:
    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=build_system_prompt(hub_names),
        messages=messages,
        output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)
