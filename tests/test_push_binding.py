"""Notification routing scenarios at the plugin and host boundary."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SCENARIOS = r"""
import json
import sys
from datetime import timedelta

import anyio
import pytest

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import At
from astrbot.api.star import Context
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.platform.message_type import MessageType
from astrbot_plugin_pigsty.core.models import utc_now
from astrbot_plugin_pigsty.core.service import UnexpectedOutcome
from astrbot_plugin_pigsty.core.unexpected import StatChange
from astrbot_plugin_pigsty.main import PigstyPlugin


class FixedLlm:
    async def complete(self, prompt, *, unified_origin=None):
        return "小猪捡到了苹果。"


context = Context()
plugin = PigstyPlugin(context, AstrBotConfig(pigsty_scope="global"), llm=FixedLlm())


def event(group="group-a", text="", owner="owner", messages=()):
    return AstrMessageEvent(
        sender_id=owner,
        platform_id="napcat-instance",
        group_id=group,
        message_str=f"pig {text}",
        messages=messages,
    )


async def command(group, tail, *, owner="owner", messages=()):
    source = event(group, tail, owner, messages)
    results = [reply async for reply in plugin.pig_command(source, tail.split()[0])]
    assert len(results) == 1
    return results[0].text


def identity(owner="owner"):
    return plugin._identity_for_event(event(owner=owner))


async def pigs():
    return await plugin.service.list_pigs(identity())


async def trigger(pig):
    now = utc_now()
    await plugin._process_unexpected_outcome(
        UnexpectedOutcome(identity(), pig, (StatChange("mood", 1),)), now
    )
    return now + timedelta(days=1)


async def auto_binding():
    await command("group-a", "add 小花")
    await command("group-b", "add @target 小黑", messages=(At(qq="target"),))
    await command(None, "add 小白")
    stored = await pigs()
    assert [pig.push_origin for pig in stored] == [
        "napcat-instance:GroupMessage:group-a",
        "napcat-instance:GroupMessage:group-b",
        "napcat-instance:FriendMessage:owner",
    ]
    assert stored[1].member_user_id == "target"
    assert identity().group_id is None
    for pig in stored:
        session = MessageSession.from_str(pig.push_origin)
        assert session.platform_id == "napcat-instance"
        assert session.message_type in (
            MessageType.GROUP_MESSAGE, MessageType.FRIEND_MESSAGE
        )
    await command("group-c", "rename 1 花花")
    assert (await pigs())[0].push_origin == stored[0].push_origin
    assert "绑定" not in await command("group-c", "show")
    assert await plugin.repository.load(identity()) == (
        await plugin.repository.load(plugin._identity_for_event(event("group-c")))
    )


async def old_pigs_and_show():
    old = (await plugin.service.add_random(identity(), "旧猪")).pig
    path = plugin.repository.path_for(identity())
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["pigs"][0]["push_origin"]
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert (await pigs())[0].push_origin is None
    await command("group-a", "add 新猪")
    shown = await command("group-a", "show")
    assert "1. 旧猪（未绑定）" in shown
    assert "2. 新猪\n" in shown
    assert shown.count("未绑定") == 1
    assert "已绑定" not in shown
    assert "当前群聊" in await command("group-b", "bind 1")
    assert "绑定" not in await command("group-a", "show")
    stored = await pigs()
    assert stored[0].pig_id == old.pig_id
    assert stored[0].push_origin == "napcat-instance:GroupMessage:group-b"
    assert stored[1].push_origin == "napcat-instance:GroupMessage:group-a"


async def rebind_and_isolation():
    await command("group-a", "add 小花")
    await command("group-b", "add 小黑")
    other = (await plugin.service.add_random(identity("other"), "别人的猪")).pig
    before = await pigs()
    assert "当前群聊" in await command("group-c", "bind 1")
    stored = await pigs()
    assert stored[0].push_origin == "napcat-instance:GroupMessage:group-c"
    assert stored[1] == before[1]
    assert "当前私聊" in await command(None, "bind 1")
    assert (await pigs())[0].push_origin == "napcat-instance:FriendMessage:owner"
    assert "全部 2 只小猪" in await command("group-d", "bind all")
    assert all(
        pig.push_origin == "napcat-instance:GroupMessage:group-d"
        for pig in await pigs()
    )
    assert "当前私聊" in await command(None, "bind all")
    assert all(
        pig.push_origin == "napcat-instance:FriendMessage:owner"
        for pig in await pigs()
    )
    assert await plugin.service.list_pigs(identity("other")) == (other,)
    assert "还是空的" in await command("group-a", "bind all", owner="empty")


async def invalid_bind():
    await command("group-a", "add 小花")
    before = await pigs()
    for tail in ("bind", "bind nope", "bind 0", "bind -1", "bind 1 extra"):
        assert "用法：pig bind <序号/all>" == await command("group-b", tail)
        assert await pigs() == before
    assert "找不到第 2 只小猪" in await command("group-b", "bind 2")
    assert await pigs() == before


async def unbound_event():
    old = (await plugin.service.add_random(identity(), "旧猪")).pig
    due = await trigger(old)
    assert plugin._pending_pushes == []
    await plugin._send_due_pushes(due)
    assert context.sent_messages == []
    events = await plugin.service.list_events(identity())
    assert len(events) == 1
    assert events[0].category == "unexpected_events"
    assert events[0].pig_id == old.pig_id
    assert (await pigs())[0].mood == min(old.mood + 1, 100)
    assert "小猪捡到了苹果" in await command("group-a", "diary")


async def bound_events():
    for group, name in (("group-a", "小花"), ("group-b", "小黑"), (None, "小白")):
        await command(group, f"add {name}")
    stored = await pigs()
    for pig in stored:
        due = await trigger(pig)
    await plugin._send_due_pushes(due)
    assert len(context.sent_messages) == 3
    assert {origin for origin, _ in context.sent_messages} == {
        pig.push_origin for pig in stored
    }
    for origin, chain in context.sent_messages:
        assert "突发事件" in chain.parts[0]
        assert "小猪捡到了苹果" in chain.parts[0]
        assert MessageSession.from_str(origin).platform_id == "napcat-instance"
    await plugin._send_due_pushes(due)
    assert len(context.sent_messages) == 3


async def rebind_pending():
    await command("group-a", "add 小花")
    await command("group-a", "add 小黑")
    stored = await pigs()
    for pig in stored:
        due = await trigger(pig)
    assert len(plugin._pending_pushes) == 2
    await command("group-b", "bind 1")
    await command(None, "bind 2")
    await plugin._send_due_pushes(due)
    assert {origin for origin, _ in context.sent_messages} == {
        "napcat-instance:GroupMessage:group-b",
        "napcat-instance:FriendMessage:owner",
    }


async def removed_pending():
    await command("group-a", "add 小花")
    due = await trigger((await pigs())[0])
    await command("group-a", "letgo 1")
    await plugin._send_due_pushes(due)
    assert context.sent_messages == []


async def group_scope():
    plugin.scope = type(plugin.scope).GROUP
    await command("group-a", "add 小花")
    await command("group-b", "add 小黑")
    await command(None, "add 小白")
    assert "还是空的" in await command("group-c", "bind all")
    for group, expected in (
        ("group-a", "napcat-instance:GroupMessage:group-a"),
        ("group-b", "napcat-instance:GroupMessage:group-b"),
        (None, "napcat-instance:FriendMessage:owner"),
    ):
        stored = await plugin.service.list_pigs(
            plugin._identity_for_event(event(group))
        )
        assert len(stored) == 1
        assert stored[0].push_origin == expected


async def host_parser():
    for invalid in (
        "napcat-instance:group_message:group-a",
        "napcat-instance:private_message:owner",
    ):
        with pytest.raises(ValueError):
            await context.send_message(invalid, MessageChain().message("test"))
    assert context.sent_messages == []
    assert plugin._unified_origin_for(identity()) == (
        "napcat-instance:FriendMessage:owner"
    )


anyio.run(globals()[sys.argv[1]])
"""


@pytest.mark.parametrize(
    "scenario",
    [
        "auto_binding",
        "old_pigs_and_show",
        "rebind_and_isolation",
        "invalid_bind",
        "unbound_event",
        "bound_events",
        "rebind_pending",
        "removed_pending",
        "group_scope",
        "host_parser",
    ],
)
def test_notification_binding_at_host_boundary(tmp_path: Path, scenario: str) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (
            str(PROJECT_ROOT / "tests" / "fake_runtime"),
            str(PROJECT_ROOT.parent),
        )
    )
    environment["ASTRBOT_TEST_DATA_DIR"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-c", SCENARIOS, scenario],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
