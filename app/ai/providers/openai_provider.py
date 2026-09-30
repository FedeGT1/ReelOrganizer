import json
import logging
import os
from typing import Any, Optional

import openai
from openai import OpenAI

from app.ai.providers.base import AIProviderError

MODEL = "gpt-6-luna"

_client: Optional[OpenAI] = None

logger = logging.getLogger("app.ai")


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=60.0)
    return _client


class OpenAIProvider:
    MODEL = MODEL

    def call_json(
        self, system: str, messages: list[dict], schema: dict, enable_web_search: bool
    ) -> dict[str, Any]:
        client = get_client()
        effort = os.environ.get("AI_REASONING_EFFORT", "medium")
        tools = [{"type": "web_search"}] if enable_web_search else []
        try:
            response = client.responses.create(
                model=MODEL,
                input=[{"role": "system", "content": system}, *messages],
                tools=tools,
                text={"format": {"type": "json_schema", "name": "response", "schema": schema}},
                reasoning={"effort": effort},
            )
        except openai.OpenAIError as e:
            raise AIProviderError(str(e)) from e

        logger.debug("call_json raw response output_text=%s", response.output_text)
        if response.output_text is None:
            raise AIProviderError("openai: empty response (no output_text)")
        return json.loads(response.output_text)
