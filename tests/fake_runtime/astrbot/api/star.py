"""Test-only AstrBot plugin lifecycle types."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

PluginT = TypeVar("PluginT")


class Context:
    """Minimal plugin context."""


class Star:
    """Minimal AstrBot plugin base class."""

    def __init__(self, context: Context) -> None:
        self.context: Context = context

    async def terminate(self) -> None:
        """Provide the lifecycle method expected by the plugin adapter."""


class StarTools:
    """Return the temporary directory selected by the smoke test."""

    @staticmethod
    def get_data_dir(_plugin_name: str) -> Path:
        return Path(os.environ["ASTRBOT_TEST_DATA_DIR"])


def register(
    _name: str,
    _author: str,
    _description: str,
    _version: str,
    _repository: str,
) -> Callable[[PluginT], PluginT]:
    """Preserve a registered plugin class unchanged."""

    def decorate(plugin: PluginT) -> PluginT:
        return plugin

    return decorate
