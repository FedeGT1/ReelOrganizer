import json
import logging
import os
from typing import Any, Optional

import anthropic
from anthropic import Anthropic

from app.ai.providers.base import AIProviderError

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


class AnthropicProvider:
    MODEL = MODEL

    def call_json(
        self, system: str, messages: list[dict], schema: dict, enable_web_search: bool
    ) -> dict[str, Any]:
        client = get_client()
        tools = [WEB_SEARCH_TOOL] if enable_web_search else []
        current_messages = list(messages)
        resumes = 0
        try:
            while True:
                response = client.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    system=system,
                    messages=current_messages,
                    tools=tools,
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                )
                if response.stop_reason == "pause_turn" and resumes < MAX_PAUSE_TURN_RESUMES:
                    logger.debug("call_json search loop paused, resuming once")
                    current_messages = current_messages + [
                        {"role": "assistant", "content": response.content}
                    ]
                    resumes += 1
                    continue
                break
        except anthropic.AnthropicError as e:
            raise AIProviderError(str(e)) from e

        text_block = next((block for block in response.content if block.type == "text"), None)
        if text_block is None:
            raise RuntimeError(
                f"call_json: no text block in final response (stop_reason={response.stop_reason!r})"
            )
        logger.debug("call_json raw response text=%s", text_block.text)
        return json.loads(text_block.text)
