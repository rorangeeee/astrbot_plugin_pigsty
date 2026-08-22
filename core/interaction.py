"""LLM user-interaction contracts for Pigsty pigs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .unexpected import StatChange

if TYPE_CHECKING:
    from .models import Pig

CLASSIFICATION_PROMPT_TEMPLATE: Final = (
    """请判断下面这条聊天消息是否包含对“该用户自己猪圈中现有小猪”"""
    """的具体互动行为。\n"""
    """当前猪圈中的小猪（序号与 pig show 一致）：\n"""
    """{pigs}\n"""
    """\n"""
    """用户消息：\n"""
    """{user_message}\n"""
    """\n"""
    """要求：\n"""
    """1. 只有消息明确表示要对上述某只小猪执行动作"""
    """（例如喂食、玩耍、抚摸、洗澡、运动、训练等）才返回 true。\n"""
    """2. 普通聊天、询问小猪状态、pig 开头的命令、"""
    """没有提及任何现有小猪的消息都返回 false。\n"""
    """3. 仅输出一个 JSON 对象，格式："""
    """{{"involves_pigs": true, "reason": "简短理由"}}。"""
)

CONVERSION_PROMPT_TEMPLATE: Final = (
    """请把用户对猪圈中小猪的行为叙述转换为每只受影响小猪的数值变化。\n"""
    """当前可操作的小猪（序号与 pig show 一致，当前值为最新值）：\n"""
    """{pigs}\n"""
    """\n"""
    """用户消息：\n"""
    """{user_message}\n"""
    """\n"""
    """全局数值约束：\n"""
    """- weight_kg：最终值必须大于 0kg（下限 0.01kg），没有上限，保留两位小数。\n"""
    """- health：最终值必须是 0 到 100 的整数。\n"""
    """- mood：最终值必须是 0 到 100 的整数。\n"""
    """- energy：最终值必须是 0 到 100 的整数。\n"""
    """- age_days 不可由用户互动改变。\n"""
    """\n"""
    """要求：\n"""
    """1. 数值偏移量本身不做限制，正负均可；插件会负责夹紧到上述全局约束。\n"""
    """2. pig_position 必须使用上面列出的显示序号；只能选择现有小猪。\n"""
    """3. 每只受影响小猪只出现一次；没有明确受影响的小猪不要写入。\n"""
    """4. changes 对象只允许 weight_kg、health、mood、energy 四个键；"""
    """省略或填 0 表示该项不变。\n"""
    """5. description 是写入该小猪日志的结构化事件描述，不超过 200 字；"""
    """reply 是回复给用户的一句话。\n"""
    """6. 仅输出一个 JSON 对象，格式：\n"""
    """{{"interactions": [{{"pig_position": 1, "description": "喂了一碗玉米糊", """
    """"changes": {{"weight_kg": 0.20, "health": 2, "mood": 5, """
    """"energy": 10}}}}], "reply": "已经给小猪喂了一碗玉米糊。"}}"""
)


@dataclass(frozen=True, slots=True)
class UserPigInteraction:
    """One parsed user interaction targeting one displayed pig position."""

    position: int
    description: str
    changes: tuple[StatChange, ...]


@dataclass(frozen=True, slots=True)
class UserInteractionPlan:
    """A parsed LLM response describing zero or more pig interactions."""

    interactions: tuple[UserPigInteraction, ...]
    reply: str


class _InteractionChanges(BaseModel):
    """Numeric deltas allowed in an LLM user-interaction response."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    weight_kg: float = Field(default=0.0)
    health: float = Field(default=0.0)
    mood: float = Field(default=0.0)
    energy: float = Field(default=0.0)

    def stat_changes(self) -> tuple[StatChange, ...]:
        """Return only the non-zero changes requested by the model."""
        deltas = (
            ("weight_kg", self.weight_kg),
            ("health", self.health),
            ("mood", self.mood),
            ("energy", self.energy),
        )
        return tuple(
            StatChange(key=key, delta=delta) for key, delta in deltas if delta != 0
        )


class _PigInteractionItem(BaseModel):
    """One pig entry inside an LLM user-interaction response."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    pig_position: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=200)
    changes: _InteractionChanges


class _UserInteractionResponse(BaseModel):
    """Full JSON shape returned by the interaction-conversion LLM."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    interactions: tuple[_PigInteractionItem, ...] = ()
    reply: str = ""


class _IntentResponse(BaseModel):
    """Full JSON shape returned by the interaction-classification LLM."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    involves_pigs: bool


def build_interaction_classification_prompt(
    pigs: tuple[Pig, ...],
    user_message: str,
) -> str:
    """Build the classification prompt for one user message and a pig list."""
    return CLASSIFICATION_PROMPT_TEMPLATE.format(
        pigs=_render_pig_positions(pigs),
        user_message=user_message.strip(),
    )


def build_interaction_conversion_prompt(
    pigs: tuple[Pig, ...],
    user_message: str,
) -> str:
    """Build the conversion prompt containing current values and global limits."""
    return CONVERSION_PROMPT_TEMPLATE.format(
        pigs=_render_pig_states(pigs),
        user_message=user_message.strip(),
    )


def parse_intent_response(raw: str) -> bool | None:
    """Return whether the classifier judged the message as a pig interaction."""
    json_text = _extract_json_text(raw)
    if json_text is None:
        return None
    try:
        return _IntentResponse.model_validate_json(json_text).involves_pigs
    except ValidationError:
        return None


def parse_user_interaction_plan(raw: str) -> UserInteractionPlan | None:
    """Parse an LLM response into a validated, duplicate-free interaction plan."""
    json_text = _extract_json_text(raw)
    if json_text is None:
        return None
    try:
        response = _UserInteractionResponse.model_validate_json(json_text)
    except ValidationError:
        return None

    interactions: list[UserPigInteraction] = []
    seen_positions: set[int] = set()
    for item in response.interactions:
        changes = item.changes.stat_changes()
        if not changes:
            continue
        if item.pig_position in seen_positions:
            return None
        description = item.description.strip()
        if not description:
            return None
        seen_positions.add(item.pig_position)
        interactions.append(
            UserPigInteraction(
                position=item.pig_position,
                description=description,
                changes=changes,
            )
        )
    return UserInteractionPlan(
        interactions=tuple(interactions),
        reply=response.reply.strip(),
    )


def _render_pig_positions(pigs: tuple[Pig, ...]) -> str:
    return "\n".join(f"{index}. {pig.name}" for index, pig in enumerate(pigs, start=1))


def _render_pig_states(pigs: tuple[Pig, ...]) -> str:
    return "\n".join(
        _render_pig_state(index, pig) for index, pig in enumerate(pigs, start=1)
    )


def _render_pig_state(index: int, pig: Pig) -> str:
    return "".join(
        (
            f"{index}. 名称：{pig.name}；体重：{pig.weight_kg:.2f}kg；",
            f"健康：{pig.health}；心情：{pig.mood}；体力：{pig.energy}",
        )
    )


def _extract_json_text(raw: str) -> str | None:
    """Extract one JSON object substring from LLM text, tolerating fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None
    return text[start : end + 1]
