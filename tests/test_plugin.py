import os
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_RUNTIME = PROJECT_ROOT / "tests" / "fake_runtime"


class ScopeSchema(BaseModel):
    """Typed boundary for the scope section of the WebUI schema."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    default: str
    options: tuple[str, ...]


class PluginSchema(BaseModel):
    """Typed boundary for the plugin WebUI schema."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

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

import anyio

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.message_components import At
from astrbot.api.star import Context, Star
from astrbot_plugin_pigsty.core.identity import (
    PigstyScope,
    resolve_session_identity,
)
from astrbot_plugin_pigsty.main import PigstyPlugin

inspect.signature(PigstyPlugin.pig_command, eval_str=True)
plugin = PigstyPlugin(Context(), AstrBotConfig(pigsty_scope="group"))
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
    messages=(At(qq="target-1"),),
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

async def assert_macro_commands() -> None:
    unknown_results = await collect(owner_event, "wat")
    assert unknown_results[0].text == (
        "用法\uff1apig status | pig add [@用户] [名字] | "
        "pig rename <序号> <新名字> | pig diary [序号] | pig show"
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
    assert random_results[0].text.startswith(
        "已添加独立小猪\uff1a小猪-"
    )
    independent_text = random_results[0].text.removeprefix(
        "已添加独立小猪\uff1a"
    )
    independent_name = independent_text.split("\uff08体质异变\uff1a", 1)[0]

    linked_results = await collect(target_event, "add")
    assert linked_results[0].text.startswith(
        "已将用户 target-1 添加为小猪\uff1a小猪-"
    )
    linked_text = linked_results[0].text.removeprefix(
        "已将用户 target-1 添加为小猪\uff1a"
    )
    linked_name = linked_text.split("\uff08体质异变\uff1a", 1)[0]

    numeric_results = await collect(numeric_target_event, "add")
    assert numeric_results[0].text.startswith(
        "已将用户 123456 添加为小猪\uff1a小猪-"
    )

    duplicate_results = await collect(target_event, "add")
    assert duplicate_results[0].text == "该用户已经在你的猪圈中。"

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
    assert shown_lines[1].startswith(f"1. {independent_name}")
    assert shown_lines[2].startswith(f"2. {linked_name}")
    assert "独立小猪" in shown_lines[1]
    assert "关联用户 target-1" in shown_lines[2]
    for line in shown_lines[1:]:
        assert all(label in line for label in ("体重", "健康", "心情", "体力"))

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
    assert "你的猪圈共有 2 只小猪\uff1a" in after_invalid_results[0].text

    named_results = await collect(named_owner_event, "add")
    assert named_results[0].text == "已添加独立小猪\uff1a白雪 小猪"

    named_target_results = await collect(named_target_event, "add")
    assert named_target_results[0].text == (
        "已将用户 target-2 添加为小猪\uff1a花花 猪"
    )

    rename_results = await collect(rename_event, "rename")
    assert rename_results[0].text == "已将第 1 只小猪改名为\uff1a粉红 小猪"

    shown_after_rename = await collect(owner_event, "show")
    assert "1. 粉红 小猪" in shown_after_rename[0].text
    assert "白雪 小猪" in shown_after_rename[0].text
    assert "花花 猪" in shown_after_rename[0].text

    invalid_rename_results = await collect(invalid_rename_event, "rename")
    assert invalid_rename_results[0].text == "用法\uff1apig rename <序号> <新名字>"


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
        "已添加独立小猪\uff1a异常 小猪\uff08体质异变\uff1a心情 45\uff09"
    )

    service_module.roll_initial_stats = lambda rng=None: normal
    normal_event = AstrMessageEvent(
        sender_id="owner-a",
        platform_id="qq",
        group_id="group-1",
        message_str="pig add 常态 小猪",
    )
    normal_results = await collect(normal_event, "add")
    assert normal_results[0].text == "已添加独立小猪\uff1a常态 小猪"


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

    # Guard every pig against unexpected rolls so the first ticks stay deterministic
    guarded = document.model_copy(
        update={
            "pigs": tuple(
                pig.model_copy(update={"unexpected_last_rolled_at": future})
                for pig in document.pigs
            )
        }
    )
    await plugin.repository.save(guarded)

    summary = await plugin._run_daily_tick(future)
    assert summary.evolved_pigs == pig_count
    assert summary.recorded_events == pig_count
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
            return "捡到了一张彩票"

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
    assert unexpected_events[0].description == "捡到了一张彩票"

    await plugin._send_due_pushes(future + timedelta(days=1))
    assert len(fake_pusher.sent) == 1
    push_text = fake_pusher.sent[0][1]
    assert "\u7a81\u53d1\u4e8b\u4ef6" in push_text
    assert "捡到了一张彩票" in push_text
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


anyio.run(assert_status_result)
anyio.run(assert_macro_commands)
anyio.run(assert_random_stat_markers)
anyio.run(assert_diary_and_daily_tick)
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


def test_metadata_declares_required_plugin_contract() -> None:
    # Given the plugin metadata file
    raw = (PROJECT_ROOT / "metadata.yaml").read_text(encoding="utf-8")

    # When its flat plugin contract is inspected
    declarations = {line.strip() for line in raw.splitlines() if line.strip()}

    # Then required fields and the approved compatibility range are present
    assert {
        "name: astrbot_plugin_pigsty",
        'desc: "群友小猪圈基础插件"',
        "version: v0.1.0",
        "author: when",
        "repo: https://github.com/rorangeeee/astrbot_plugin_pigsty",
        'astrbot_version: ">=4.16"',
    } <= declarations
