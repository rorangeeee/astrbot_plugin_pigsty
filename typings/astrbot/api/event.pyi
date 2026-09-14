from collections.abc import Callable
from typing import ClassVar, ParamSpec, TypeVar

_Parameters = ParamSpec("_Parameters")
_ReturnT = TypeVar("_ReturnT")
_MessageComponent = object

class EventMessageType:
    ALL: ClassVar[EventMessageType]
    GROUP: ClassVar[EventMessageType]
    PRIVATE: ClassVar[EventMessageType]

class MessageEventResult: ...

class MessageChain:
    def message(self, text: str) -> MessageChain: ...

class AstrMessageEvent:
    message_str: str
    role: str

    def __init__(
        self,
        sender_id: str = "42",
        platform_id: str = "qq",
        group_id: str | None = None,
        messages: tuple[_MessageComponent, ...] = (),
        message_str: str = "",
        *,
        role: str = "member",
        admin: bool = False,
        self_id: str = "bot",
        is_at_or_wake_command: bool = False,
    ) -> None: ...
    def get_sender_id(self) -> str: ...
    def get_platform_id(self) -> str: ...
    def get_group_id(self) -> str | None: ...
    def get_messages(self) -> tuple[_MessageComponent, ...]: ...
    def get_self_id(self) -> str: ...
    def is_private_chat(self) -> bool: ...
    is_at_or_wake_command: bool
    def is_admin(self) -> bool: ...
    call_llm: bool
    def should_call_llm(self, call_llm: bool) -> None: ...
    def stop_event(self) -> None: ...
    def is_stopped(self) -> bool: ...
    def set_result(self, result: MessageEventResult) -> None: ...
    def get_result(self) -> MessageEventResult | None: ...
    def clear_result(self) -> None: ...
    def set_extra(self, key: str, value: object) -> None: ...
    def get_extra(self, key: str | None = None, default: object = None) -> object: ...
    def plain_result(self, text: str) -> MessageEventResult: ...

class filter:
    EventMessageType: ClassVar[type[EventMessageType]]

    @staticmethod
    def command(
        name: str,
    ) -> Callable[
        [Callable[_Parameters, _ReturnT]],
        Callable[_Parameters, _ReturnT],
    ]: ...
    @staticmethod
    def event_message_type(
        message_type: EventMessageType,
        *,
        priority: int = 0,
    ) -> Callable[
        [Callable[_Parameters, _ReturnT]],
        Callable[_Parameters, _ReturnT],
    ]: ...
