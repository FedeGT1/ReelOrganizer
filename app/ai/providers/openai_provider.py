import json
import logging
import os
import socket
import sys
from typing import Any, Optional, Union

import httpx2
import openai
from openai import OpenAI

from app.ai.providers.base import AIProviderError

MODEL = "gpt-6-luna"

_client: Optional[OpenAI] = None

logger = logging.getLogger("app.ai")


def _keepalive_http_client() -> httpx2.Client:
    # Unlike the Anthropic SDK, the OpenAI SDK's default transport doesn't
    # enable TCP keepalive. Without it, a NAT gateway or load balancer that
    # silently drops an idle pooled connection leaves the client blocked
    # with no way to detect it until the outer request timeout fires,
    # minutes later (known upstream issue: openai/openai-python#3269;
    # observed live here during rapid sequential multi-place-import calls).
    # Mirrors the socket options the Anthropic SDK already enables by
    # default (see `anthropic._base_client._DefaultHttpxClient`).
    socket_options: list[tuple[int, int, Union[int, bool]]] = [
        (socket.SOL_SOCKET, socket.SO_KEEPALIVE, True)
    ]
    tcp_keepintvl = getattr(socket, "TCP_KEEPINTVL", None)
    if tcp_keepintvl is not None:
        socket_options.append((socket.IPPROTO_TCP, tcp_keepintvl, 60))
    elif sys.platform == "darwin":
        tcp_keepalive = getattr(socket, "TCP_KEEPALIVE", 0x10)
        socket_options.append((socket.IPPROTO_TCP, tcp_keepalive, 60))
    tcp_keepcnt = getattr(socket, "TCP_KEEPCNT", None)
    if tcp_keepcnt is not None:
        socket_options.append((socket.IPPROTO_TCP, tcp_keepcnt, 5))
    tcp_keepidle = getattr(socket, "TCP_KEEPIDLE", None)
    if tcp_keepidle is not None:
        socket_options.append((socket.IPPROTO_TCP, tcp_keepidle, 60))
    transport = httpx2.HTTPTransport(socket_options=socket_options)
    return httpx2.Client(transport=transport)


def get_client() -> OpenAI:
    global _client
    if _client is None:
        # 15s per attempt, not a generous ceiling: the SDK's own max_retries
        # (default 2) already retries on a plain timeout, so a stalled
        # attempt gets cut and re-sent automatically rather than making the
        # caller wait a long time for one slow attempt to maybe recover.
        # This is the baseline for ordinary (non-web-search) calls, which
        # empirically finish in well under 10s ~90% of the time -- don't
        # raise it to accommodate web search; that's handled per-call below
        # instead, since blanket-raising this would undo the fast-retry
        # behavior for every stalled/dead-connection call, not just slow
        # web-search ones.
        _client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"], timeout=15.0, http_client=_keepalive_http_client()
        )
    return _client


class OpenAIProvider:
    MODEL = MODEL

    def call_json(
        self, system: str, messages: list[dict], schema: dict, enable_web_search: bool
    ) -> dict[str, Any]:
        client = get_client()
        effort = os.environ.get("AI_REASONING_EFFORT", "medium")
        tools = [{"type": "web_search"}] if enable_web_search else []
        # With web search, OpenAI only responds once the search-and-synthesis
        # work is done, which routinely exceeds the client's 15s baseline --
        # that caused every attempt (and the SDK's automatic retries) to
        # time out before a response ever came back. Override the timeout
        # for just this call rather than raising the client-wide baseline.
        call_kwargs = {}
        if enable_web_search:
            call_kwargs["timeout"] = float(os.environ.get("OPENAI_TIMEOUT", "30"))
        try:
            response = client.responses.create(
                model=MODEL,
                input=[{"role": "system", "content": system}, *messages],
                tools=tools,
                text={"format": {"type": "json_schema", "name": "response", "schema": schema}},
                reasoning={"effort": effort},
                **call_kwargs,
            )
        except openai.OpenAIError as e:
            raise AIProviderError(str(e)) from e

        logger.debug("call_json raw response output_text=%s", response.output_text)
        if response.output_text is None:
            raise AIProviderError("openai: empty response (no output_text)")
        return json.loads(response.output_text)
