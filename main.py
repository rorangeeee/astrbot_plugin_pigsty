"""AstrBot adapter for the phase-one Pigsty foundation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from astrbot.api.event import filter
from astrbot.api.star import Star, StarTools, register
from typing_extensions import override

from .core.identity import IdentityError, PigstyScope
from .core.repository import JsonPigstyRepository

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from astrbot.api import AstrBotConfig
    from astrbot.api.event import AstrMessageEvent, MessageEventResult
    from astrbot.api.star import Context

PLUGIN_NAME: Final = "astrbot_plugin_pigsty"


@register(
    PLUGIN_NAME,
    "wkc20",
    "严格类型化的群友小猪圈基础插件",
    "0.1.0",
    "https://github.com/wkc20/astrbot_plugin_pigsty",
)
class PigstyPlugin(Star):
    """AstrBot lifecycle adapter for Pigsty's core services."""

    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        """Initialize the plugin and its persistent Pigsty repository."""
        super().__init__(context)
        self.scope: PigstyScope = self._read_scope(config)
        self.data_dir: Path = StarTools.get_data_dir(PLUGIN_NAME)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.repository: JsonPigstyRepository = JsonPigstyRepository(self.data_dir)

    @staticmethod
    def _read_scope(config: AstrBotConfig | None) -> PigstyScope:
        """Parse the WebUI scope setting at the AstrBot boundary."""
        scope_field = "pigsty_scope"
        if config is None:
            return PigstyScope.GLOBAL

        raw_scope = config.get(scope_field, PigstyScope.GLOBAL.value)
        if not isinstance(raw_scope, str):
            raise IdentityError(
                scope_field,
                repr(raw_scope),
                "must be the string 'global' or 'group'",
            )
        try:
            return PigstyScope(raw_scope)
        except ValueError as error:
            raise IdentityError(
                scope_field,
                raw_scope,
                "must be the string 'global' or 'group'",
            ) from error

    @filter.command("pig")
    async def pig_command(
        self,
        event: AstrMessageEvent,
        action: str = "status",
    ) -> AsyncIterator[MessageEventResult]:
        """Report foundation readiness without exposing internal Pig UUIDs."""
        if action.strip().lower() != "status":
            yield event.plain_result("用法：pig status")
            return
        yield event.plain_result(f"Pigsty 数据层已就绪\n作用域：{self.scope.value}")

    @override
    async def terminate(self) -> None:
        """Complete the AstrBot async lifecycle; no background work exists yet."""
