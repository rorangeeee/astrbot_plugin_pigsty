"""AstrBot adapter for the Pigsty pigsty plugin."""

from __future__ import annotations

import asyncio
import re
from collections.abc import (
    AsyncIterator,  # noqa: TC003 - AstrBot evaluates command annotations at runtime.
)
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

import anyio
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult, filter
from astrbot.api.message_components import At
from astrbot.api.star import Star, StarTools, register
from pydantic import ValidationError
from typing_extensions import override

from .core.evolution import DAY_TZ, daily_tick_reached, next_tick_at
from .core.identity import (
    IdentityError,
    PigstyScope,
    SessionIdentity,
    resolve_session_identity,
)
from .core.models import REGULAR_EVENT_CATEGORY, utc_now
from .core.randomizer import default_random_source
from .core.repository import JsonPigstyRepository
from .core.service import (
    DuplicateMemberPigError,
    PigPositionNotFoundError,
    PigstyService,
)
from .core.unexpected import pick_unexpected_moment

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path
    from uuid import UUID

    from astrbot.api import AstrBotConfig
    from astrbot.api.star import Context

    from .core.models import Pig, PigEvent
    from .core.randomizer import InitialStatsRoll
    from .core.service import DailyTickSummary, UnexpectedOutcome
    from .core.unexpected import StatChange

PLUGIN_NAME: Final = "astrbot_plugin_pigsty"
ADD_USAGE: Final = "pig add [@用户] [名字]"
RENAME_USAGE: Final = "pig rename <序号> <新名字>"
DIARY_USAGE: Final = "pig diary [序号]"
UNKNOWN_COMMAND_USAGE: Final = (
    f"用法：pig status | {ADD_USAGE} | {RENAME_USAGE} | {DIARY_USAGE} | pig show"
)
STAT_LABELS: Final = {
    "weight_kg": "体重",
    "health": "健康",
    "mood": "心情",
    "energy": "体力",
}
DIARY_LIMIT: Final = 10
EVENT_CATEGORY_LABELS: Final = {
    "regular_events": "例行事件",
    "unexpected_events": "突发事件",
    "user_events": "用户事件",
}
UNEXPECTED_PROMPT_TEMPLATE: Final = (
    "请根据以下信息为一只宠物小猪编写一条突发事件描述。\n"
    "小猪名字：{name}\n"
    "数值变化：{changes}\n"
    "要求：仅输出事件描述本身（一句话，不超过50字），不要输出任何其他内容。"
)
UNEXPECTED_PUSH_TEMPLATE: Final = (
    "⚠️ 突发事件：{position}. {name}\n{description}\n（数值变化：{changes}）"
)


class InvalidMemberTargetError(Exception):
    """Raised when a pig add command has an invalid mention target."""


class LlmClient(Protocol):
    """Seam for asking the default conversation LLM for a description."""

    async def complete(self, prompt: str) -> str:
        """Return the model's completion text for one prompt."""


class PigstyPusher(Protocol):
    """Seam for pushing proactive plain-text messages to one session."""

    async def push(self, unified_origin: str, text: str) -> None:
        """Send one plain-text message to the given session."""


@dataclass(frozen=True, slots=True)
class PendingPush:
    """One proactive message scheduled for a future moment."""

    unified_origin: str
    text: str
    due_at: datetime


class AstrBotLlmClient:
    """Ask AstrBot's default LLM without any persona or history."""

    def __init__(self, context: Context, unified_origin: str) -> None:
        """Bind the client to one session's unified message origin."""
        self._context: Context = context
        self._unified_origin: str = unified_origin

    async def complete(self, prompt: str) -> str:
        """Return the model's completion text, or an empty string on failure."""
        try:
            provider = await self._context.get_using_provider_async(
                umo=self._unified_origin
            )
        except Exception:
            return ""
        if provider is None:
            return ""
        try:
            response = await provider.text_chat(
                prompt=prompt,
                context=[],
                system_prompt="",
            )
        except Exception:
            return ""
        return response.completion_text.strip()


class AstrBotPusher:
    """Push proactive plain-text messages through AstrBot."""

    def __init__(self, context: Context) -> None:
        """Bind the pusher to the plugin context."""
        self._context: Context = context

    async def push(self, unified_origin: str, text: str) -> None:
        """Send one plain-text message; platform failures propagate."""
        await self._context.send_message(
            unified_origin,
            MessageChain().message(text),
        )


@register(
    PLUGIN_NAME,
    "when",
    "群友小猪圈基础插件",
    "v0.1.0",
    "https://github.com/rorangeeee/astrbot_plugin_pigsty",
)
class PigstyPlugin(Star):
    """AstrBot lifecycle adapter for Pigsty's core services."""

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
        *,
        llm: LlmClient | None = None,
        pusher: PigstyPusher | None = None,
    ) -> None:
        """Initialize the plugin, its repository, seams, and the daily task."""
        super().__init__(context)
        self.scope: PigstyScope = self._read_scope(config)
        self.data_dir: Path = StarTools.get_data_dir(PLUGIN_NAME)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.repository: JsonPigstyRepository = JsonPigstyRepository(self.data_dir)
        self.service: PigstyService = PigstyService(self.repository)
        self._llm: LlmClient | None = llm
        self._pusher: PigstyPusher = (
            pusher if pusher is not None else AstrBotPusher(context)
        )
        self._pending_pushes: list[PendingPush] = []
        self._last_tick_summary: DailyTickSummary | None = None
        self._tick_task: asyncio.Task[None] = asyncio.create_task(self._daily_loop())

    async def _daily_loop(self) -> None:
        """Run the 9:00 GMT+8 tick and deliver scheduled pushes forever."""
        while True:
            now = utc_now()
            if daily_tick_reached(now):
                await self._run_daily_tick(now)
            await self._send_due_pushes(utc_now())
            await anyio.sleep(self._seconds_until_next_wake(utc_now()))

    def _seconds_until_next_wake(self, now: datetime) -> float:
        """Return seconds until the next tick or scheduled push."""
        target = next_tick_at(now)
        if self._pending_pushes:
            target = min(target, self._pending_pushes[0].due_at)
        return max((target - now).total_seconds(), 0.0)

    async def _run_daily_tick(self, now: datetime) -> DailyTickSummary:
        """Evolve due pigs, roll unexpected events, and schedule their pushes."""
        summary = await self.service.evolve_all_due(now)
        outcomes = await self.service.roll_unexpected_all(now)
        for outcome in outcomes:
            try:
                await self._process_unexpected_outcome(outcome, now)
            except Exception:
                self.logger.exception("failed to process an unexpected event")
        self._last_tick_summary = summary
        return summary

    async def _process_unexpected_outcome(
        self,
        outcome: UnexpectedOutcome,
        now: datetime,
    ) -> None:
        """Describe, apply, record, and schedule one triggered event."""
        name = outcome.pig.name
        changes_text = self._render_stat_changes(outcome.changes)
        prompt = UNEXPECTED_PROMPT_TEMPLATE.format(name=name, changes=changes_text)
        description = await self._llm_complete(outcome.identity, prompt)
        if not description:
            description = f"数值变化：{changes_text}"
        description = description[:200]
        moment = pick_unexpected_moment(now, default_random_source())
        await self.service.apply_unexpected_event(
            outcome.identity,
            outcome.pig.pig_id,
            outcome.changes,
            description,
            moment,
        )
        pigs = await self.service.list_pigs(outcome.identity)
        position = next(
            (
                index
                for index, pig in enumerate(pigs, start=1)
                if pig.pig_id == outcome.pig.pig_id
            ),
            0,
        )
        text = UNEXPECTED_PUSH_TEMPLATE.format(
            position=position,
            name=name,
            description=description,
            changes=changes_text,
        )
        self._schedule_push(
            PendingPush(
                unified_origin=self._unified_origin_for(outcome.identity),
                text=text,
                due_at=moment,
            )
        )

    async def _llm_complete(self, identity: SessionIdentity, prompt: str) -> str:
        """Ask the injected or AstrBot default LLM for a description."""
        if self._llm is not None:
            try:
                return (await self._llm.complete(prompt)).strip()
            except Exception:
                self.logger.exception("unexpected description LLM failed")
                return ""
        return await AstrBotLlmClient(
            self.context,
            self._unified_origin_for(identity),
        ).complete(prompt)

    def _schedule_push(self, push: PendingPush) -> None:
        """Queue one proactive message sorted by its due moment."""
        self._pending_pushes.append(push)
        self._pending_pushes.sort(key=lambda item: item.due_at)

    async def _send_due_pushes(self, now: datetime) -> None:
        """Send every queued push whose moment has arrived."""
        due = [push for push in self._pending_pushes if push.due_at <= now]
        self._pending_pushes = [
            push for push in self._pending_pushes if push.due_at > now
        ]
        for push in due:
            try:
                await self._pusher.push(push.unified_origin, push.text)
            except Exception:
                self.logger.exception("failed to push an unexpected event message")

    @staticmethod
    def _unified_origin_for(identity: SessionIdentity) -> str:
        """Build AstrBot's unified_msg_origin string for a pigsty context."""
        if identity.group_id is not None:
            message_type = "group_message"
            session_id = identity.group_id
        else:
            message_type = "private_message"
            session_id = identity.owner_user_id
        return f"{identity.platform_id}:{message_type}:{session_id}"

    @staticmethod
    def _render_stat_changes(changes: tuple[StatChange, ...]) -> str:
        """Render one event's stat changes with Chinese labels."""
        parts: list[str] = []
        for change in changes:
            label = STAT_LABELS[change.key]
            if change.key == "weight_kg":
                parts.append(f"{label} +{change.value:.2f}kg")
            elif change.key == "energy":
                parts.append(f"精力 {change.value}")
            else:
                parts.append(f"{label} {change.value:+d}")
        return "，".join(parts)

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

    @staticmethod
    def _render_diary(
        pigs: tuple[Pig, ...],
        events: tuple[PigEvent, ...],
        position: int | None,
    ) -> str:
        """Render the most recent notable (non-regular) events."""
        header = "你的猪圈事件记录："
        empty_text = "你的猪圈还没有值得记录的事件。"
        target: UUID | None = None
        if position is not None:
            target = pigs[position - 1].pig_id
            header = f"第 {position} 只小猪的事件记录："
            empty_text = "这只小猪还没有值得记录的事件。"
        notable = [
            event for event in events if event.category != REGULAR_EVENT_CATEGORY
        ]
        if target is not None:
            notable = [event for event in notable if event.pig_id == target]
        if not notable:
            return empty_text
        pig_names = {pig.pig_id: pig.name for pig in pigs}
        pig_positions = {pig.pig_id: index for index, pig in enumerate(pigs, start=1)}
        lines = [header]
        for index, event in enumerate(reversed(notable[-DIARY_LIMIT:]), start=1):
            pig_label = (
                f"{pig_positions.get(event.pig_id, 0)}. "
                f"{pig_names.get(event.pig_id, '未知小猪')}"
            )
            category_label = EVENT_CATEGORY_LABELS.get(event.category, event.category)
            local_time = event.occurred_at.astimezone(DAY_TZ)
            lines.append(
                f"{index}. [{category_label}] {local_time:%Y-%m-%d %H:%M} · "
                f"{pig_label}：{event.description}"
            )
        return "\n".join(lines)

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
        if normalized_action == "diary":
            identity = self._identity_for_event(event)
            position: int | None = None
            tail = self._command_tail(event, normalized_action)
            if tail:
                try:
                    position = int(tail)
                except ValueError:
                    yield event.plain_result(f"用法：{DIARY_USAGE}")
                    return
                if position < 1:
                    yield event.plain_result(f"用法：{DIARY_USAGE}")
                    return
            pigs = await self.service.list_pigs(identity)
            if position is not None and position > len(pigs):
                yield event.plain_result(f"用法：{DIARY_USAGE}")
                return
            events = await self.service.list_events(identity)
            yield event.plain_result(self._render_diary(pigs, events, position))
            return
        if normalized_action == "show":
            identity = self._identity_for_event(event)
            pigs = await self.service.list_pigs(identity)
            yield event.plain_result(self._render_pigsty(pigs))
            return
        yield event.plain_result(UNKNOWN_COMMAND_USAGE)

    @override
    async def terminate(self) -> None:
        """Cancel the background daily tick before the AstrBot lifecycle ends."""
        task = self._tick_task
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
