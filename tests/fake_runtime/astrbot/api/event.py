"""Test-only AstrBot event and command decorator."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import ParamSpec, TypeVar

Parameters = ParamSpec("Parameters")
ReturnT = TypeVar("ReturnT")


@dataclass(frozen=True, slots=True)
class MessageEventResult:
    """Minimal message result exposed through AstrBot's public event API."""

    text: str


class AstrMessageEvent:
    """Minimal event exposing the public identity and message accessors."""

    def __init__(
        self,
        sender_id: str = "42",
        platform_id: str = "qq",
        group_id: str | None = None,
        messages: tuple[object, ...] = (),
    ) -> None:
        self._sender_id: str = sender_id
        self._platform_id: str = platform_id
        self._group_id: str | None = group_id
        self._messages: tuple[object, ...] = messages

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

    def plain_result(self, text: str) -> MessageEventResult:
        """Wrap command text in the public result type for smoke tests."""
        return MessageEventResult(text)


class filter:
    """Minimal command decorator namespace."""

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
