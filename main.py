"""AstrBot adapter for the phase-one Pigsty foundation."""

from __future__ import annotations

import re
from collections.abc import (
    AsyncIterator,  # noqa: TC003 - AstrBot evaluates command annotations at runtime.
)
from typing import TYPE_CHECKING, Final

from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.message_components import At
from astrbot.api.star import Star, StarTools, register
from pydantic import ValidationError
from typing_extensions import override

from .core.identity import (
    IdentityError,
    PigstyScope,
    SessionIdentity,
    resolve_session_identity,
)
from .core.repository import JsonPigstyRepository
from .core.service import (
    DuplicateMemberPigError,
    PigPositionNotFoundError,
    PigstyService,
)

if TYPE_CHECKING:
    from pathlib import Path

    from astrbot.api import AstrBotConfig
    from astrbot.api.star import Context

    from .core.models import Pig
    from .core.randomizer import InitialStatsRoll

PLUGIN_NAME: Final = "astrbot_plugin_pigsty"
ADD_USAGE: Final = "pig add [@用户] [名字]"
RENAME_USAGE: Final = "pig rename <序号> <新名字>"
UNKNOWN_COMMAND_USAGE: Final = (
    f"用法：pig status | {ADD_USAGE} | {RENAME_USAGE} | pig show"
)
STAT_LABELS: Final = {
    "weight_kg": "体重",
    "health": "健康",
    "mood": "心情",
    "energy": "体力",
}


class InvalidMemberTargetError(Exception):
    """Raised when a pig add command has an invalid mention target."""


@register(
    PLUGIN_NAME,
    "when",
    "群友小猪圈基础插件",
    "v0.1.0",
    "https://github.com/rorangeeee/astrbot_plugin_pigsty",
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
    def _command_tail(event: AstrMessageEvent, action: str) -> str:
        """Return trimmed raw text after one command action token."""
        pattern = re.compile(rf"(?:^|\s){re.escape(action)}(?:\s+|$)", re.IGNORECASE)
        match = pattern.search(event.message_str)
        return "" if match is None else event.message_str[match.end() :].strip()

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

    @staticmethod
    def _render_stat_anomalies(roll: InitialStatsRoll) -> str:
        """Render the anomaly marker for stats outside the normal tier."""
        anomalies = roll.anomalies
        if not anomalies:
            return ""
        parts: list[str] = []
        for stat in anomalies:
            label = STAT_LABELS[stat.key]
            if stat.key == "weight_kg":
                parts.append(f"{label} {stat.value:.1f}kg")
            else:
                parts.append(f"{label} {stat.value}")
        return f"（体质异变：{'，'.join(parts)}）"

    @filter.command("pig")
    async def pig_command(  # noqa: C901, PLR0911, PLR0912, PLR0915
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
                yield event.plain_result("用法：pig add [@用户] [名字]")
                return

            identity = self._identity_for_event(event)
            name = self._command_tail(event, normalized_action) or None
            if target is None:
                try:
                    creation = await self.service.add_random(identity, name)
                except ValidationError:
                    yield event.plain_result("猪名字不能为空且不能超过 32 个字符。")
                    return
                pig = creation.pig
                anomalies = self._render_stat_anomalies(creation.roll)
                yield event.plain_result(f"已添加独立小猪：{pig.name}{anomalies}")
                return

            try:
                creation = await self.service.add_member(
                    identity, identity.platform_id, target, name
                )
            except DuplicateMemberPigError:
                yield event.plain_result("该用户已经在你的猪圈中。")
                return
            except ValidationError:
                yield event.plain_result("猪名字不能为空且不能超过 32 个字符。")
                return
            pig = creation.pig
            anomalies = self._render_stat_anomalies(creation.roll)
            yield event.plain_result(
                f"已将用户 {target} 添加为小猪：{pig.name}{anomalies}"
            )
            return
        if normalized_action == "rename":
            tail = self._command_tail(event, normalized_action)
            parts = tail.split(maxsplit=1)
            if not parts:
                yield event.plain_result("用法：pig rename <序号> <新名字>")
                return
            name = tail.removeprefix(parts[0]).strip()
            if not name:
                yield event.plain_result("用法：pig rename <序号> <新名字>")
                return
            try:
                position = int(parts[0])
            except ValueError:
                yield event.plain_result("用法：pig rename <序号> <新名字>")
                return
            if position < 1:
                yield event.plain_result("用法：pig rename <序号> <新名字>")
                return
            try:
                pig = await self.service.rename_pig(
                    self._identity_for_event(event), position, name
                )
            except PigPositionNotFoundError:
                yield event.plain_result("用法：pig rename <序号> <新名字>")
                return
            except ValidationError:
                yield event.plain_result("猪名字不能为空且不能超过 32 个字符。")
                return
            yield event.plain_result(f"已将第 {position} 只小猪改名为：{pig.name}")
            return
        if normalized_action == "show":
            identity = self._identity_for_event(event)
            pigs = await self.service.list_pigs(identity)
            yield event.plain_result(self._render_pigsty(pigs))
            return
        yield event.plain_result(UNKNOWN_COMMAND_USAGE)

    @override
    async def terminate(self) -> None:
        """Complete the AstrBot async lifecycle; no background work exists yet."""
