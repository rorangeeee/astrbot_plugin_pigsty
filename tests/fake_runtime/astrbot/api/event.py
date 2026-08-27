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
    ) -> None:
        self._sender_id: str = sender_id
        self._platform_id: str = platform_id
        self._group_id: str | None = group_id
        self._messages: tuple[object, ...] = messages
        self.message_str: str = message_str
        self.role: str = role
        self._admin: bool = admin

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

    def is_admin(self) -> bool:
        """Return the test event's platform administrator flag."""
        return self._admin

    def plain_result(self, text: str) -> MessageEventResult:
        """Wrap command text in the public result type for smoke tests."""
        return MessageEventResult(text)


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
    ) -> Callable[
        [Callable[Parameters, ReturnT]],
        Callable[Parameters, ReturnT],
    ]:
        """Preserve the decorated message listener unchanged."""

        def decorate(
            handler: Callable[Parameters, ReturnT],
        ) -> Callable[Parameters, ReturnT]:
            return handler

        return decorate
