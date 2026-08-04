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
    """Minimal event that turns plain text into event results."""

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
