"""Test-only AstrBot plugin lifecycle types."""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from astrbot.core.platform.message_session import MessageSession

from .event import MessageChain
from .provider import Provider

PluginT = TypeVar("PluginT")


class Context:
    """Minimal plugin context with LLM and proactive-send surfaces."""

    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, MessageChain]] = []
        self.provider: Provider | None = None
        self.providers: dict[str, Provider] = {}

    async def get_using_provider_async(self, umo: str | None = None) -> Provider | None:
        """Return the canned provider, if any."""
        return self.provider

    def get_provider_by_id(self, provider_id: str) -> Provider | None:
        """Return a configured provider by its test id."""
        return self.providers.get(provider_id)

    async def send_message(self, umo: str, chain: MessageChain) -> None:
        """Record the proactive message for smoke tests."""
        _ = MessageSession.from_str(umo)
        self.sent_messages.append((umo, chain))


class Star:
    """Minimal AstrBot plugin base class."""

    def __init__(self, context: Context) -> None:
        self.context: Context = context
        self.logger: logging.Logger = logging.getLogger("pigsty-test")

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
