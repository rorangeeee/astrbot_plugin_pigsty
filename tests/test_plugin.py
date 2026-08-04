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

import anyio

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star
from astrbot_plugin_pigsty.core.identity import PigstyScope
from astrbot_plugin_pigsty.main import PigstyPlugin

plugin = PigstyPlugin(Context(), AstrBotConfig(pigsty_scope="group"))
assert issubclass(PigstyPlugin, Star)
assert plugin.scope is PigstyScope.GROUP
assert plugin.repository.data_dir == Path(os.environ["ASTRBOT_TEST_DATA_DIR"])

async def assert_status_result() -> None:
    results = [result async for result in plugin.pig_command(AstrMessageEvent())]
    assert len(results) == 1
    assert isinstance(results[0], MessageEventResult)
    assert results[0].text == "Pigsty 数据层已就绪\\n作用域\\uff1agroup"

anyio.run(assert_status_result)
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
        'desc: "严格类型化的群友小猪圈基础插件"',
        'version: "0.1.0"',
        'author: "wkc20"',
        'repo: "https://github.com/wkc20/astrbot_plugin_pigsty"',
        'astrbot_version: ">=4.16,<5"',
    } <= declarations
