import os
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_RUNTIME = PROJECT_ROOT / "tests" / "fake_runtime"


class ScopeSchema(BaseModel):
    """Typed boundary for the scope section of the WebUI schema."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    default: str
    options: tuple[str, ...]


class LlmProviderSchema(BaseModel):
    """Typed boundary for the WebUI's dynamic provider selector."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        frozen=True,
        populate_by_name=True,
    )

    type_name: str = Field(alias="type")
    description: str
    special: str = Field(alias="_special")
    default: str
    hint: str


class AdminIdsSchema(BaseModel):
    """Typed boundary for configured administrator IDs."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    type_name: str = Field(alias="type")
    description: str
    hint: str
    default: list[str]
    items: dict[str, str]


class PluginSchema(BaseModel):
    """Typed boundary for the plugin WebUI schema."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    llm_provider_id: LlmProviderSchema
    admin_ids: AdminIdsSchema
    pigsty_scope: ScopeSchema


def test_plugin_import_and_initialization_use_astrbot_boundary(tmp_path: Path) -> None:
    # Given a test-only AstrBot runtime and isolated plugin data directory
    environment = os.environ.copy()
    previous_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        part
        for part in (
            str(FAKE_RUNTIME),
            str(PROJECT_ROOT.parent),
            previous_pythonpath,
        )
        if part
    )
    environment["ASTRBOT_TEST_DATA_DIR"] = str(tmp_path)
    script = """
from pathlib import Path
import os
import inspect
import logging

import anyio
import pytest

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.message_components import At
from astrbot.api.star import Context, Star
from astrbot_plugin_pigsty.core.identity import (
    PigstyScope,
    resolve_session_identity,
)
from astrbot_plugin_pigsty.core.models import Pig
from astrbot_plugin_pigsty.main import PigstyPlugin

inspect.signature(PigstyPlugin.pig_command, eval_str=True)
plugin = PigstyPlugin(
    Context(),
    AstrBotConfig(pigsty_scope="group", admin_ids=["owner-a"]),
)
assert issubclass(PigstyPlugin, Star)
assert plugin.scope is PigstyScope.GROUP
assert plugin.repository.data_dir == Path(os.environ["ASTRBOT_TEST_DATA_DIR"])
owner_event = AstrMessageEvent(
    sender_id="owner-a",
    platform_id="qq",
    group_id="group-1",
)
target_event = AstrMessageEvent(
    sender_id="owner-a",
    platform_id="qq",
    group_id="group-1",
    messages=(At(qq="target-1", name="target-one"),),
)
empty_owner_event = AstrMessageEvent(
    sender_id="owner-b",
    platform_id="qq",
    group_id="group-1",
)
target_owner_event = AstrMessageEvent(
    sender_id="target-1",
    platform_id="qq",
    group_id="group-1",
)
numeric_target_event = AstrMessageEvent(
    sender_id="owner-int",
    platform_id="qq",
    group_id="group-1",
    messages=(At(qq=123456),),
)
named_owner_event = AstrMessageEvent(
    sender_id="owner-a",
    platform_id="qq",
    group_id="group-1",
    message_str="pig add 白雪 小猪",
)
named_target_event = AstrMessageEvent(
    sender_id="owner-a",
    platform_id="qq",
    group_id="group-1",
    messages=(At(qq="target-2"),),
    message_str="pig add 花花 猪",
)
rename_event = AstrMessageEvent(
    sender_id="owner-a",
    platform_id="qq",
    group_id="group-1",
    message_str="pig rename 1 粉红 小猪",
)
invalid_rename_event = AstrMessageEvent(
    sender_id="owner-a",
    platform_id="qq",
    group_id="group-1",
    message_str="pig rename 0 无效",
)
private_event = AstrMessageEvent(
    sender_id="private-owner",
    platform_id="qq",
    group_id="",
)

async def collect(
    event: AstrMessageEvent, action: str
) -> tuple[MessageEventResult, ...]:
    return tuple([result async for result in plugin.pig_command(event, action)])

async def assert_status_result() -> None:
    results = await collect(owner_event, "status")
    assert len(results) == 1
    assert isinstance(results[0], MessageEventResult)
    assert results[0].text == "Pigsty 数据层已就绪\\n作用域\\uff1agroup"
    denied = await collect(empty_owner_event, "status")
    assert denied[0].text == "此命令仅限管理员使用。"

async def assert_macro_commands() -> None:
    unknown_results = await collect(owner_event, "wat")
    assert unknown_results[0].text == (
        "用法：\\n"
        "pig status\\n"
        "pig add [@用户] [名字]\\n"
        "pig rename <序号> <新名字>\\n"
        "pig diary [序号]\\n"
        "pig letgo [序号/id/昵称]\\n"
        "pig show"
    )

    empty_results = await collect(empty_owner_event, "show")
    assert empty_results[0].text == (
        "你的猪圈还是空的\uff0c使用 pig add 添加一只小猪吧。"
    )

    private_results = await collect(private_event, "show")
    assert private_results[0].text == (
        "你的猪圈还是空的\uff0c使用 pig add 添加一只小猪吧。"
    )

    random_results = await collect(owner_event, "add")
    assert random_results[0].text.startswith("成功添加小猪小猪-")
    independent_name = random_results[0].text.splitlines()[0].removeprefix(
        "成功添加小猪"
    ).removesuffix("！")

    linked_results = await collect(target_event, "add")
    assert linked_results[0].text.startswith("成功将@target-1 小猪-")
    linked_name = linked_results[0].text.splitlines()[0].split(" ", 2)[1]
    linked_name = linked_name.removesuffix("添加进猪圈！")

    numeric_results = await collect(numeric_target_event, "add")
    assert numeric_results[0].text.startswith("成功将@123456 小猪-")

    long_nickname = "这是一个长度超过三十二字且不应成为小猪名称的群昵称" * 2
    long_nickname_event = AstrMessageEvent(
        sender_id="owner-long",
        platform_id="qq",
        group_id="group-1",
        messages=(At(qq="long-target", name=long_nickname),),
        message_str=f"pig add @{long_nickname}",
    )
    long_results = await collect(long_nickname_event, "add")
    assert long_results[0].text.startswith("成功将@long-target 小猪-")
    long_show = await collect(long_nickname_event, "show")
    assert f"@{long_nickname}" in long_show[0].text
    long_without_metadata_event = AstrMessageEvent(
        sender_id="owner-long2",
        platform_id="qq",
        group_id="group-1",
        messages=(At(qq="long-target2"),),
        message_str=f"pig add {long_nickname}",
    )
    long_without_metadata_results = await collect(
        long_without_metadata_event, "add"
    )
    assert long_without_metadata_results[0].text.startswith(
        "成功将@long-target2 小猪-"
    )

    duplicate_results = await collect(target_event, "add")
    assert duplicate_results[0].text.startswith("该小猪")
    assert duplicate_results[0].text.endswith("已经在你的猪圈中。")

    for messages in (
        (At(qq="target-2"), At(qq="target-3")),
        (At(qq=" "),),
        (At(qq="all"),),
    ):
        invalid_event = AstrMessageEvent(
            sender_id="owner-a",
            platform_id="qq",
            group_id="group-1",
            messages=messages,
        )
        invalid_results = await collect(invalid_event, "add")
        assert invalid_results[0].text == "用法\uff1apig add [@用户] [名字]"

    shown_results = await collect(owner_event, "show")
    shown_lines = shown_results[0].text.splitlines()
    assert shown_lines[0] == "你的猪圈共有 2 只小猪\uff1a"
    assert shown_lines[1] == f"1. {independent_name}"
    assert shown_lines[2].startswith("体重：")
    assert shown_lines[6].startswith(f"2. {linked_name} @target-one")
    assert shown_lines[7].startswith("体重：")
    assert all(
        label in shown_lines[2] + shown_lines[3] + shown_lines[4] + shown_lines[5]
        for label in ("体重", "健康", "心情", "体力")
    )

    identity = resolve_session_identity(
        PigstyScope.GROUP,
        "qq",
        "owner-a",
        "group-1",
    )
    document = await plugin.repository.load(identity)
    pig_ids = tuple(str(pig.pig_id) for pig in document.pigs)
    user_outputs = (
        random_results[0].text,
        linked_results[0].text,
        shown_results[0].text,
    )
    for pig_id in pig_ids:
        assert all(pig_id not in output for output in user_outputs)

    target_owner_results = await collect(target_owner_event, "show")
    assert target_owner_results[0].text == (
        "你的猪圈还是空的\uff0c使用 pig add 添加一只小猪吧。"
    )

    after_invalid_results = await collect(owner_event, "show")
    assert "你的猪圈共有 2 只小猪：" in after_invalid_results[0].text

    named_results = await collect(named_owner_event, "add")
    assert named_results[0].text.splitlines()[0] == "成功添加小猪白雪 小猪！"

    named_target_results = await collect(named_target_event, "add")
    assert named_target_results[0].text.splitlines()[0] == (
        "成功将@target-2 花花 猪添加进猪圈！"
    )

    rename_results = await collect(rename_event, "rename")
    assert rename_results[0].text.endswith("改名为粉红 小猪。")

    shown_after_rename = await collect(owner_event, "show")
    assert "1. 粉红 小猪" in shown_after_rename[0].text
    assert "白雪 小猪" in shown_after_rename[0].text
    assert "花花 猪" in shown_after_rename[0].text

    invalid_rename_results = await collect(invalid_rename_event, "rename")
    assert invalid_rename_results[0].text == "用法\uff1apig rename <序号> <新名字>"


async def assert_letgo_does_not_use_llm() -> None:
    identity = resolve_session_identity(
        PigstyScope.GROUP,
        "qq",
        "letgo-owner",
        "letgo-group",
    )
    release_event = AstrMessageEvent(
        sender_id="letgo-owner",
        platform_id="qq",
        group_id="letgo-group",
        message_str="pig letgo 1",
    )
    _ = await plugin.service.add_random(identity, "待放生猪")

    class FailingLlm:
        async def complete(self, prompt: str) -> str:
            raise AssertionError(f"pig letgo must not call the LLM: {prompt}")

    plugin._llm = FailingLlm()
    results = await collect(release_event, "letgo")

    assert results[0].text == (
        "已将待放生猪放生，ta会在一个不愁吃喝、安全温馨的地方度过它幸福的余生。"
        "它很感谢你这段时间的陪伴。"
    )
    assert await plugin.service.list_pigs(identity) == ()
    assert await plugin.service.list_events(identity) == ()
    assert "它走之前对你留下了一些话：" not in results[0].text


async def assert_random_stat_markers() -> None:
    from astrbot_plugin_pigsty.core.randomizer import (
        InitialStatsRoll,
        RolledStat,
        RollTier,
    )

    import astrbot_plugin_pigsty.core.service as service_module

    anomalous = InitialStatsRoll(
        stats=(
            RolledStat("weight_kg", 5.0, RollTier.NORMAL),
            RolledStat("health", 100, RollTier.NORMAL),
            RolledStat("mood", 45, RollTier.MAJOR),
            RolledStat("energy", 80, RollTier.NORMAL),
        )
    )
    normal = InitialStatsRoll(
        stats=(
            RolledStat("weight_kg", 5.0, RollTier.NORMAL),
            RolledStat("health", 100, RollTier.NORMAL),
            RolledStat("mood", 70, RollTier.NORMAL),
            RolledStat("energy", 80, RollTier.NORMAL),
        )
    )

    service_module.roll_initial_stats = lambda rng=None: anomalous
    anomalous_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        message_str="pig add 异常 小猪",
    )
    anomalous_results = await collect(anomalous_event, "add")
    assert anomalous_results[0].text == (
        "成功添加小猪异常 小猪！\\n"
        "体重：5.0 kg\\n"
        "健康：100\\n"
        "！！心情：45！！\\n"
        "活力：80"
    )

    service_module.roll_initial_stats = lambda rng=None: normal
    normal_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        message_str="pig add 常态 小猪",
    )
    normal_results = await collect(normal_event, "add")
    assert normal_results[0].text == (
        "成功添加小猪常态 小猪！\\n"
        "体重：5.0 kg\\n"
        "健康：100\\n"
        "心情：70\\n"
        "活力：80"
    )


async def assert_diary_and_daily_tick() -> None:
    from datetime import timedelta

    from astrbot_plugin_pigsty.core.models import utc_now

    identity = resolve_session_identity(
        PigstyScope.GROUP,
        "qq",
        "owner-a",
        "group-1",
    )
    document = await plugin.repository.load(identity)
    pig_count = len(document.pigs)
    assert pig_count >= 2

    for raw in ("pig diary 0", "pig diary abc"):
        invalid_event = AstrMessageEvent(
            sender_id="owner-a",
            platform_id="qq",
            group_id="group-1",
            message_str=raw,
        )
        invalid_results = await collect(invalid_event, "diary")
        assert invalid_results[0].text == "用法\uff1apig diary [序号]"

    empty_results = await collect(empty_owner_event, "diary")
    assert empty_results[0].text == "你的猪圈还没有值得记录的事件。"

    future = utc_now() + timedelta(days=2)

    # Guard every pig in every document against unexpected rolls
    paths = await plugin.repository.document_paths()
    documents = []
    for path in paths:
        current = await plugin.repository._read_existing(path)
        guarded = current.model_copy(
            update={
                "pigs": tuple(
                    pig.model_copy(update={"unexpected_last_rolled_at": future})
                    for pig in current.pigs
                )
            }
        )
        documents.append(guarded)
        await plugin.repository.save(guarded)

    all_pig_count = sum(len(current.pigs) for current in documents)
    summary = await plugin._run_daily_tick(future)
    assert summary.evolved_pigs == all_pig_count
    assert summary.recorded_events == all_pig_count
    assert summary.failed_documents == 0

    repeated = await plugin._run_daily_tick(future)
    assert repeated.evolved_pigs == 0
    assert repeated.recorded_events == 0

    diary_results = await collect(owner_event, "diary")
    assert diary_results[0].text == "你的猪圈还没有值得记录的事件。"

    # Arm exactly one pig with a guaranteed unexpected-event trigger
    current = await plugin.repository.load(identity)
    target_pig = current.pigs[0]
    armed = current.model_copy(
        update={
            "pigs": tuple(
                pig.model_copy(
                    update={
                        "unexpected_chance_percent": 100,
                        "unexpected_last_rolled_at": None,
                    }
                )
                if pig.pig_id == target_pig.pig_id
                else pig
                for pig in current.pigs
            )
        }
    )
    await plugin.repository.save(armed)

    class FakeLlm:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def complete(self, prompt: str) -> str:
            self.prompts.append(prompt)
            return "捡到彩票"

    class FakePusher:
        def __init__(self) -> None:
            self.sent: list[tuple[str, str]] = []

        async def push(self, unified_origin: str, text: str) -> None:
            self.sent.append((unified_origin, text))

    fake_llm = FakeLlm()
    fake_pusher = FakePusher()
    plugin._llm = fake_llm
    plugin._pusher = fake_pusher

    after = await plugin._run_daily_tick(future)
    assert after.evolved_pigs == 0

    assert len(fake_llm.prompts) == 1
    assert "\u6570\u503c\u53d8\u5316" in fake_llm.prompts[0]
    assert target_pig.name in fake_llm.prompts[0]

    events = await plugin.service.list_events(identity)
    unexpected_events = [
        event for event in events if event.category == "unexpected_events"
    ]
    assert len(unexpected_events) == 1
    assert unexpected_events[0].pig_id == target_pig.pig_id
    assert unexpected_events[0].description == "捡到彩票"

    await plugin._send_due_pushes(future + timedelta(days=1))
    assert len(fake_pusher.sent) == 1
    push_text = fake_pusher.sent[0][1]
    assert "\u7a81\u53d1\u4e8b\u4ef6" in push_text
    assert "捡到彩票" in push_text
    assert "1. " in push_text

    diary_results = await collect(owner_event, "diary")
    diary_text = diary_results[0].text
    assert "\u7a81\u53d1\u4e8b\u4ef6" in diary_text
    assert "捡到彩票" in diary_text
    assert "\u4f8b\u884c\u4e8b\u4ef6" not in diary_text

    first_diary_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        message_str="pig diary 1",
    )
    first_results = await collect(first_diary_event, "diary")
    assert "捡到彩票" in first_results[0].text

    other_diary_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        message_str="pig diary 2",
    )
    other_results = await collect(other_diary_event, "diary")
    assert other_results[0].text == "这只小猪还没有值得记录的事件。"

    out_of_range_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        message_str=f"pig diary {pig_count + 1}",
    )
    out_of_range_results = await collect(out_of_range_event, "diary")
    assert out_of_range_results[0].text == "用法\uff1apig diary [序号]"


async def assert_llm_user_interaction() -> None:
    identity = resolve_session_identity(
        PigstyScope.GROUP,
        "qq",
        "owner-a",
        "group-1",
    )
    before = await plugin.service.list_pigs(identity)
    assert before

    class ScriptedLlm:
        def __init__(self) -> None:
            self.responses = [
                '{"involves_pigs": true}',
                (
                    '{"interactions": [{"pig_position": 1, '
                    '"description": "喂了一碗玉米糊", '
                    '"changes": {"weight_kg": 0.10, "mood": 5}}], '
                    '"reply": "已经给小猪喂了一碗玉米糊。"}'
                ),
            ]
            self.prompts: list[str] = []

        async def complete(self, prompt: str) -> str:
            self.prompts.append(prompt)
            return self.responses.pop(0)

    fake_llm = ScriptedLlm()
    plugin._llm = fake_llm
    class CaptureHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.messages: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.messages.append(record.getMessage())

    capture_handler = CaptureHandler()
    previous_level = plugin.logger.level
    plugin.logger.setLevel(logging.INFO)
    plugin.logger.addHandler(capture_handler)
    message_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        message_str="给小猪喂一碗玉米糊",
        is_at_or_wake_command=True,
    )

    try:
        reply = await plugin._handle_user_interaction(message_event)
    finally:
        plugin.logger.removeHandler(capture_handler)
        plugin.logger.setLevel(previous_level)

    assert reply.startswith("已经给小猪喂了一碗玉米糊。\\n具体数值变化：\\n")
    assert "体重 +0.10" in reply
    assert "心情 +5" in reply
    assert len(fake_llm.prompts) == 2
    assert "1. " in fake_llm.prompts[0]
    assert "全局数值约束" in fake_llm.prompts[1]
    assert "体重：{:.2f}kg".format(before[0].weight_kg) in fake_llm.prompts[1]

    after = await plugin.service.list_pigs(identity)
    assert after[0].weight_kg == pytest.approx(before[0].weight_kg + 0.10)
    assert after[0].mood == min(before[0].mood + 5, 100)
    pigsty_log = plugin._pigsty_log_label(identity)
    assert f"Pigsty 判断到对小猪执行动作：猪圈={pigsty_log}" in capture_handler.messages
    actual_changes = plugin._render_stat_changes(
        plugin._actual_stat_changes(before[0], after[0])
    ).replace("\n", "；")
    assert (
        f"Pigsty 小猪数值变动：猪圈={pigsty_log}，小猪={after[0].name}，"
        f"变化：{actual_changes}"
    ) in capture_handler.messages

    events = await plugin.service.list_events(identity)
    user_events = [event for event in events if event.category == "user_events"]
    assert len(user_events) == 1
    assert user_events[0].pig_id == before[0].pig_id
    assert user_events[0].description == "喂了一碗玉米糊"

    class GuardLlm:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def complete(self, prompt: str) -> str:
            self.prompts.append(prompt)
            return '{"involves_pigs": false}'

    ordinary_llm = GuardLlm()
    plugin._llm = ordinary_llm
    ordinary_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        message_str="普通群聊，不要触发小猪互动",
    )
    before_ordinary = await plugin.service.list_pigs(identity)
    assert await plugin._handle_user_interaction(ordinary_event) is None
    assert ordinary_llm.prompts == []
    assert await plugin.service.list_pigs(identity) == before_ordinary

    other_mention_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        messages=(At(qq="another-user"),),
        message_str="@another-user 给小猪喂饭",
    )
    assert await plugin._handle_user_interaction(other_mention_event) is None
    assert ordinary_llm.prompts == []

    bot_mention_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        messages=(At(qq="bot"),),
        message_str="@bot 给小猪喂饭",
    )
    bot_llm = ScriptedLlm()
    plugin._llm = bot_llm
    assert await plugin._handle_user_interaction(bot_mention_event)
    assert len(bot_llm.prompts) == 2

    class DeathLlm:
        def __init__(self) -> None:
            self.responses = [
                '{"involves_pigs": true}',
                (
                    '{"interactions": [{"pig_position": 1, '
                    '"description": "造成致命伤害", '
                    '"changes": {"health": -200}}], '
                    '"reply": "互动完成。"}'
                ),
            ]

        async def complete(self, prompt: str) -> str:
            return self.responses.pop(0)

    death_llm = DeathLlm()
    plugin._llm = death_llm
    death_target = (await plugin.service.list_pigs(identity))[0]
    death_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        messages=(At(qq="bot"),),
        message_str="@bot 让第一只小猪承受致命伤害",
    )
    death_reply = await plugin._handle_user_interaction(death_event)
    assert death_reply == f"@owner-a，很抱歉，你的小猪{death_target.name}已死亡。"
    assert death_target not in await plugin.service.list_pigs(identity)
    death_show = await collect(death_event, "show")
    assert death_show[0].text == "你的猪圈还是空的，使用 pig add 添加一只小猪吧。"
    linked_pig = Pig(
        member_platform_id="qq",
        member_user_id="linked-user",
        name="关联猪",
    )
    assert plugin._render_death_notice(identity, linked_pig) == (
        "@owner-a @linked-user，很抱歉，你的小猪关联猪已死亡。"
    )

    pig_command_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        message_str="pig status",
    )
    assert await plugin._handle_user_interaction(pig_command_event) is None

    empty_llm = ScriptedLlm()
    plugin._llm = empty_llm
    empty_owner_message = AstrMessageEvent(
        sender_id="empty-owner",
        platform_id="qq",
        group_id="group-1",
        message_str="喂小猪",
    )
    assert await plugin._handle_user_interaction(empty_owner_message) is None
    assert empty_llm.prompts == []


anyio.run(assert_status_result)
anyio.run(assert_macro_commands)
anyio.run(assert_letgo_does_not_use_llm)
anyio.run(assert_random_stat_markers)
anyio.run(assert_diary_and_daily_tick)
anyio.run(assert_llm_user_interaction)
"""

    # When the plugin module is imported and initialized in a child process
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )

    # Then the AstrBot adapter loads without touching the deployment directory
    assert completed.returncode == 0, completed.stderr


def test_core_modules_do_not_import_astrbot() -> None:
    # Given every core Python module
    core_sources = sorted((PROJECT_ROOT / "core").glob("*.py"))

    # When their source boundaries are inspected
    violations = [
        path.name
        for path in core_sources
        if "astrbot" in path.read_text(encoding="utf-8").lower()
    ]

    # Then no domain or persistence module depends on AstrBot
    assert violations == []


def test_scope_schema_defaults_to_global() -> None:
    # Given the plugin configuration schema
    raw = (PROJECT_ROOT / "_conf_schema.json").read_text(encoding="utf-8")

    # When the scope field is parsed
    scope = PluginSchema.model_validate_json(raw).pigsty_scope

    # Then WebUI exposes only the approved values with global as the default
    assert scope.default == "global"
    assert scope.options == ("global", "group")


def test_llm_schema_uses_astrbot_provider_selector() -> None:
    # Given the plugin WebUI schema
    raw = (PROJECT_ROOT / "_conf_schema.json").read_text(encoding="utf-8")

    # When the default conversation-model setting is inspected
    llm = PluginSchema.model_validate_json(raw).llm_provider_id

    # Then AstrBot can populate it from configured provider/model entries
    assert llm.type_name == "string"
    assert llm.description == "LLM交互模型配置"
    assert llm.special == "select_provider"
    assert llm.default == ""
    assert llm.hint == "建议使用快速稳定的模型选项，获得更好的体验。"


def test_admin_ids_schema_is_a_string_list() -> None:
    # Given the plugin WebUI schema
    raw = (PROJECT_ROOT / "_conf_schema.json").read_text(encoding="utf-8")

    # When the administrator setting is inspected
    admin_ids = PluginSchema.model_validate_json(raw).admin_ids

    # Then the panel exposes an optional list of user IDs
    assert admin_ids.type_name == "list"
    assert admin_ids.default == []
    assert admin_ids.items == {"type": "string"}


def test_metadata_declares_required_plugin_contract() -> None:
    # Given the plugin metadata file
    raw = (PROJECT_ROOT / "metadata.yaml").read_text(encoding="utf-8")

    # When its flat plugin contract is inspected
    declarations = {line.strip() for line in raw.splitlines() if line.strip()}

    # Then required fields and the approved compatibility range are present
    assert {
        "name: astrbot_plugin_pigsty",
        'desc: "一个可以把群友圈养起来的养猪猪插件"',
        "version: v0.1.0",
        "author: when",
        "repo: https://github.com/rorangeeee/astrbot_plugin_pigsty",
        'astrbot_version: ">=4.16"',
    } <= declarations
