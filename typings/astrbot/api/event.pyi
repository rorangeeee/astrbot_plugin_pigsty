from collections.abc import Callable
from typing import ParamSpec, TypeVar

_Parameters = ParamSpec("_Parameters")
_ReturnT = TypeVar("_ReturnT")
_MessageComponent = object

class MessageEventResult: ...

class AstrMessageEvent:
    message_str: str

    def __init__(
        self,
        sender_id: str = "42",
        platform_id: str = "qq",
        group_id: str | None = None,
        messages: tuple[_MessageComponent, ...] = (),
        message_str: str = "",
    ) -> None: ...
    def get_sender_id(self) -> str: ...
    def get_platform_id(self) -> str: ...
    def get_group_id(self) -> str | None: ...
    def get_messages(self) -> tuple[_MessageComponent, ...]: ...
    def plain_result(self, text: str) -> MessageEventResult: ...

class filter:
    @staticmethod
    def command(
        name: str,
    ) -> Callable[
        [Callable[_Parameters, _ReturnT]],
        Callable[_Parameters, _ReturnT],
    ]: ...
