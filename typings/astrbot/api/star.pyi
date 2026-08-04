from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

class Context: ...

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
