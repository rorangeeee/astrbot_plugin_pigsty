"""Test-only AstrBot LLM provider surface."""


class LLMResponse:
    """Minimal LLM response exposing the completion text."""

    def __init__(self, completion_text: str = "") -> None:
        self.completion_text: str = completion_text


class Provider:
    """Minimal provider returning a canned completion."""

    def __init__(self, completion_text: str = "") -> None:
        self._completion_text: str = completion_text

    async def text_chat(
        self,
        prompt: str,
        context: list[dict[str, str]] | None = None,
        system_prompt: str = "",
    ) -> LLMResponse:
        """Return the canned completion without touching the network."""
        _ = (prompt, context, system_prompt)
        return LLMResponse(self._completion_text)

