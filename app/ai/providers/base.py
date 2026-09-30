from typing import Any, Protocol


class AIProvider(Protocol):
    def call_json(
        self, system: str, messages: list[dict], schema: dict, enable_web_search: bool
    ) -> dict[str, Any]: ...


class AIProviderError(Exception):
    """Raised for any provider-specific SDK/API failure, wrapping the original error."""
