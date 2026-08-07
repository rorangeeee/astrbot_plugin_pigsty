"""AstrBot adapter for the phase-one Pigsty foundation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from astrbot.api.event import filter
from astrbot.api.message_components import At
from astrbot.api.star import Star, StarTools, register
from typing_extensions import override

from .core.identity import (
    IdentityError,
    PigstyScope,
    SessionIdentity,
    resolve_session_identity,
)
from .core.repository import JsonPigstyRepository
from .core.service import DuplicateMemberPigError, PigstyService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from astrbot.api import AstrBotConfig
    from astrbot.api.event import AstrMessageEvent, MessageEventResult
    from astrbot.api.star import Context

    from .core.models import Pig

PLUGIN_NAME: Final = "astrbot_plugin_pigsty"


class InvalidMemberTargetError(Exception):
    """Raised when a pig add command has an invalid mention target."""


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
        self.service: PigstyService = PigstyService(self.repository)

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

    def _identity_for_event(self, event: AstrMessageEvent) -> SessionIdentity:
        """Resolve the event caller into the configured Pigsty identity."""
        group_id = event.get_group_id()
        if group_id is not None and not group_id.strip():
            group_id = None
        return resolve_session_identity(
            self.scope,
            event.get_platform_id(),
            event.get_sender_id(),
            group_id,
        )

    @staticmethod
    def _member_target_for_event(event: AstrMessageEvent) -> str | None:
        """Return one concrete At target, or reject invalid target input."""
        targets = tuple(
            segment.qq for segment in event.get_messages() if isinstance(segment, At)
        )
        if not targets:
            return None
        if len(targets) != 1:
            raise InvalidMemberTargetError
        target = str(targets[0]).strip()
        if not target or target == "all":
            raise InvalidMemberTargetError
        return target

    @staticmethod
    def _render_pigsty(pigs: tuple[Pig, ...]) -> str:
        """Render persisted pigs without exposing their UUIDs."""
        if not pigs:
            return "你的猪圈还是空的，使用 pig add 添加一只小猪吧。"

        lines = [f"你的猪圈共有 {len(pigs)} 只小猪："]
        for index, pig in enumerate(pigs, start=1):
            member = (
                "独立小猪"
                if pig.member_user_id is None
                else f"关联用户 {pig.member_user_id}"
            )
            line = (
                f"{index}. {pig.name}（{member}）"
                f"体重：{pig.weight_kg:.1f}kg，健康：{pig.health}，"
                f"心情：{pig.mood}，体力：{pig.energy}"
            )
            lines.append(line)
        return "\n".join(lines)

    @filter.command("pig")
    async def pig_command(
        self,
        event: AstrMessageEvent,
        action: str = "status",
    ) -> AsyncIterator[MessageEventResult]:
        """Report foundation readiness without exposing internal Pig UUIDs."""
        normalized_action = action.strip().lower()
        if normalized_action == "status":
            yield event.plain_result(f"Pigsty 数据层已就绪\n作用域：{self.scope.value}")
            return
        if normalized_action == "add":
            try:
                target = self._member_target_for_event(event)
            except InvalidMemberTargetError:
                yield event.plain_result("用法：pig add [@用户]")
                return

            identity = self._identity_for_event(event)
            if target is None:
                pig = await self.service.add_random(identity)
                yield event.plain_result(f"已添加独立小猪：{pig.name}")
                return

            try:
                pig = await self.service.add_member(
                    identity, identity.platform_id, target
                )
            except DuplicateMemberPigError:
                yield event.plain_result("该用户已经在你的猪圈中。")
                return
            yield event.plain_result(f"已将用户 {target} 添加为小猪：{pig.name}")
            return
        if normalized_action == "show":
            identity = self._identity_for_event(event)
            pigs = await self.service.list_pigs(identity)
            yield event.plain_result(self._render_pigsty(pigs))
            return
        yield event.plain_result("用法：pig status | pig add [@用户] | pig show")

    @override
    async def terminate(self) -> None:
        """Complete the AstrBot async lifecycle; no background work exists yet."""
