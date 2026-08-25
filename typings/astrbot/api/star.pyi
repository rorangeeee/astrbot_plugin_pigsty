from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

from .event import MessageChain
from .provider import Provider

class Context:
    providers: dict[str, Provider]
    provider: Provider | None
    def get_using_provider_async(
        self, umo: str | None = None
    ) -> Awaitable[Provider | None]: ...
    def get_provider_by_id(self, provider_id: str) -> Provider | None: ...
    def send_message(self, umo: str, chain: MessageChain) -> Awaitable[None]: ...

class Star:
    def __init__(self, context: Context) -> None: ...
    async def terminate(self) -> None: ...

class StarTools:
    @staticmethod
    def get_data_dir(plugin_name: str) -> Path: ...

_PluginT = TypeVar("_PluginT")

def register(
    name: str,
    author: str,
    desc: str,
    version: str,
    repo: str,
) -> Callable[[_PluginT], _PluginT]: ...
