from collections.abc import Awaitable

class LLMResponse:
    completion_text: str

class Provider:
    def text_chat(
        self,
        prompt: str,
        context: list[dict[str, str]],
        system_prompt: str,
    ) -> Awaitable[LLMResponse]: ...
