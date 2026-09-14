"""Test-only AstrBot event and command decorator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

Parameters = ParamSpec("Parameters")
ReturnT = TypeVar("ReturnT")


@dataclass(frozen=True, slots=True)
class MessageEventResult:
    """Minimal message result exposed through AstrBot's public event API."""

    text: str


class MessageChain:
    """Minimal message chain builder for proactive sends."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def message(self, text: str) -> MessageChain:
        """Append one plain-text part and return the chain for chaining."""
        self.parts.append(text)
        return self


class AstrMessageEvent:
    """Minimal event exposing the public identity and message accessors."""

    def __init__(
        self,
        sender_id: str = "42",
        platform_id: str = "qq",
        group_id: str | None = None,
        messages: tuple[object, ...] = (),
        message_str: str = "",
        *,
        role: str = "member",
        admin: bool = False,
        self_id: str = "bot",
        is_at_or_wake_command: bool = False,
    ) -> None:
        self._sender_id: str = sender_id
        self._platform_id: str = platform_id
        self._group_id: str | None = group_id
        self._messages: tuple[object, ...] = messages
        self.message_str: str = message_str
        self.role: str = role
        self._admin: bool = admin
        self._self_id: str = self_id
        self.is_at_or_wake_command: bool = is_at_or_wake_command
        self.call_llm: bool = False
        self._stopped: bool = False
        self._result: MessageEventResult | None = None
        self._extras: dict[str, object] = {}

    def get_sender_id(self) -> str:
        """Return the event sender identifier."""
        return self._sender_id

    def get_platform_id(self) -> str:
        """Return the event platform identifier."""
        return self._platform_id

    def get_group_id(self) -> str | None:
        """Return the optional event group identifier."""
        return self._group_id

    def get_messages(self) -> tuple[object, ...]:
        """Return the event message components."""
        return self._messages

    def get_self_id(self) -> str:
        """Return the bot identifier associated with the event."""
        return self._self_id

    def is_private_chat(self) -> bool:
        """Return whether this fake event represents a private message."""
        return self._group_id is None or not self._group_id.strip()

    def is_admin(self) -> bool:
        """Return the test event's platform administrator flag."""
        return self._admin

    def plain_result(self, text: str) -> MessageEventResult:
        """Wrap command text in the public result type for smoke tests."""
        return MessageEventResult(text)

    def should_call_llm(self, call_llm: bool) -> None:
        """Record whether the default LLM should be skipped."""
        self.call_llm = call_llm

    def stop_event(self) -> None:
        """Stop propagation to later handlers and pipeline stages."""
        self._stopped = True

    def is_stopped(self) -> bool:
        """Return whether this fake event has been stopped."""
        return self._stopped

    def set_result(self, result: MessageEventResult) -> None:
        """Store a result for pipeline-style tests."""
        self._result = result

    def get_result(self) -> MessageEventResult | None:
        """Return the stored pipeline result."""
        return self._result

    def clear_result(self) -> None:
        """Clear the stored pipeline result."""
        self._result = None

    def set_extra(self, key: str, value: object) -> None:
        """Store one plugin-scoped event extra."""
        self._extras[key] = value

    def get_extra(self, key: str | None = None, default: object = None) -> object:
        """Read one plugin-scoped event extra or the complete mapping."""
        if key is None:
            return self._extras
        return self._extras.get(key, default)


class EventMessageType(StrEnum):
    """Mirror of AstrBot's public message-type filter values."""

    ALL = "all"
    GROUP = "group"
    PRIVATE = "private"


class filter:
    """Minimal command and message-listener decorator namespace."""

    EventMessageType: type[EventMessageType] = EventMessageType

    @staticmethod
    def command(
        _name: str,
    ) -> Callable[
        [Callable[Parameters, ReturnT]],
        Callable[Parameters, ReturnT],
    ]:
        """Preserve the decorated handler unchanged."""

        def decorate(
            handler: Callable[Parameters, ReturnT],
        ) -> Callable[Parameters, ReturnT]:
            return handler

        return decorate

    @staticmethod
    def event_message_type(
        _message_type: EventMessageType,
        *,
        priority: int = 0,
    ) -> Callable[
        [Callable[Parameters, ReturnT]],
        Callable[Parameters, ReturnT],
    ]:
        """Preserve the decorated message listener unchanged."""

        def decorate(
            handler: Callable[Parameters, ReturnT],
        ) -> Callable[Parameters, ReturnT]:
            _ = priority
            return handler

        return decorate
