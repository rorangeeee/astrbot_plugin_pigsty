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
        "pig rename <序号> <新名字> | pig show"
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
    independent_name = random_results[0].text.removeprefix(
        "已添加独立小猪\uff1a"
    )

    linked_results = await collect(target_event, "add")
    assert linked_results[0].text.startswith(
        "已将用户 target-1 添加为小猪\uff1a小猪-"
    )
    linked_name = linked_results[0].text.removeprefix(
        "已将用户 target-1 添加为小猪\uff1a"
    )

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

anyio.run(assert_status_result)
anyio.run(assert_macro_commands)
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
