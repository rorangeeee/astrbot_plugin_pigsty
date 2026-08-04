from collections.abc import Callable
from typing import ParamSpec, TypeVar

_Parameters = ParamSpec("_Parameters")
_ReturnT = TypeVar("_ReturnT")

class MessageEventResult: ...

class AstrMessageEvent:
    def plain_result(self, text: str) -> MessageEventResult: ...

class filter:
    @staticmethod
    def command(
        name: str,
    ) -> Callable[
        [Callable[_Parameters, _ReturnT]],
        Callable[_Parameters, _ReturnT],
    ]: ...
