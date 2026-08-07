# Pigsty 宏观命令 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每位调用者现有的、哈希隔离的 Pigsty database 中，实现独立随机小猪、带 @ 用户关联的小猪和只读列表命令。

**Architecture:** `core/models.py` 继续定义严格持久化契约，允许成对可选的成员关联。新建的 `core/service.py` 保持 AstrBot-independent，负责随机模板、重复关联检查和通过 `JsonPigstyRepository.update()` 原子追加。`main.py` 只将公开 AstrBot 事件 API 映射成 `SessionIdentity` 与可选 `Comp.At` 目标，并将核心结果渲染为消息。

**Tech Stack:** Python 3.11、Pydantic v2、AnyIO、pytest、Ruff 0.16.1、basedpyright、AstrBot public event/message-components API。

---

## 文件映射

- 修改 `core/models.py`：使成员关联成对可选并保留当前严格验证。
- 新建 `core/service.py`：创建随机 Pig、创建关联 Pig、拒绝重复、读取 Pig 列表。
- 修改 `core/__init__.py`：导出服务和领域异常。
- 修改 `main.py`：解析 caller identity 与一个 `Comp.At`，实现 `pig add`、`pig show`。
- 新建/修改 `typings/astrbot/api/message_components.pyi`、`typings/astrbot/api/event.pyi`：表达公开 API。
- 新建/修改 `tests/fake_runtime/astrbot/api/message_components.py`、`tests/fake_runtime/astrbot/api/event.py`：提供测试运行时。
- 修改 `tests/test_models.py`，新建 `tests/test_service.py`，修改 `tests/test_plugin.py`：锁定核心和适配层契约。
- 修改 `README.md`：记录当前命令和数据库 owner 规则。

## Task 1: 放宽 Pig 的成员关联契约

**Files:**
- Modify: `core/models.py:29-83`
- Modify: `tests/test_models.py`

- [ ] **Step 1: 写失败模型测试。** 新增独立 Pig 与不完整关联测试：

```python
def test_pig_allows_an_independent_pig() -> None:
    pig = Pig(name="小猪-1234abcd")
    assert pig.member_platform_id is None
    assert pig.member_user_id is None


@pytest.mark.parametrize(
    ("member_platform_id", "member_user_id"),
    [("qq", None), (None, "42")],
)
def test_pig_rejects_partial_member_association(
    member_platform_id: str | None,
    member_user_id: str | None,
) -> None:
    with pytest.raises(ValidationError):
        _ = Pig(
            name="小猪-1234abcd",
            member_platform_id=member_platform_id,
            member_user_id=member_user_id,
        )
```

- [ ] **Step 2: 运行 RED。**

Run: `uv run --no-sync python -m pytest tests/test_models.py -q`

Expected: 独立 Pig 因缺少 `member_*` 字段失败。

- [ ] **Step 3: 最小实现。** 把成员字段定义为 `str | None = None`。将现有空白验证拆分为名称验证和成员 ID 验证；成员 ID 为 `None` 时允许，为字符串时拒绝空白。新增 `@model_validator(mode="after")`，当两个成员字段的 `None` 状态不一致时抛出 `PydanticCustomError("partial_member_association", ...)`。

- [ ] **Step 4: 运行 GREEN。**

Run: `uv run --no-sync python -m pytest tests/test_models.py -q`

Expected: 全部模型测试通过，已有带成员关联的 JSON 往返测试仍通过。

## Task 2: 新建纯核心 Pigsty 服务

**Files:**
- Create: `core/service.py`
- Modify: `core/__init__.py`
- Create: `tests/test_service.py`

- [ ] **Step 1: 写失败服务测试。** 覆盖随机创建、关联追加、重复拒绝和 owner 隔离：

```python
async def scenario() -> None:
    service = PigstyService(JsonPigstyRepository(tmp_path))
    owner = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)

    pig = await service.add_random(owner)

    assert pig.member_platform_id is None
    assert pig.member_user_id is None
    assert pig.name.startswith("小猪-")
    assert (await service.list_pigs(owner)) == (pig,)
```

```python
async def scenario() -> None:
    service = PigstyService(JsonPigstyRepository(tmp_path))
    owner = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)

    first = await service.add_member(owner, "qq", "target")
    with pytest.raises(DuplicateMemberPigError):
        _ = await service.add_member(owner, "qq", "target")

    assert first.member_user_id == "target"
    assert len(await service.list_pigs(owner)) == 1
```

- [ ] **Step 2: 运行 RED。**

Run: `uv run --no-sync python -m pytest tests/test_service.py -q`

Expected: collection fails because `core.service` does not exist。

- [ ] **Step 3: 最小实现。** 在 `core/service.py` 定义：

```python
@dataclass(frozen=True, slots=True)
class DuplicateMemberPigError(Exception):
    platform_id: str
    user_id: str


class PigstyService:
    def __init__(self, repository: JsonPigstyRepository) -> None: ...

    async def add_random(self, identity: SessionIdentity) -> Pig: ...

    async def add_member(
        self,
        identity: SessionIdentity,
        member_platform_id: str,
        member_user_id: str,
    ) -> Pig: ...

    async def list_pigs(self, identity: SessionIdentity) -> tuple[Pig, ...]: ...
```

每次创建都先生成 `pig_id = uuid4()`，再以 `f"小猪-{pig_id.hex[:8]}"` 建立 Pig。两种添加方法都用同步 mutation 传给 `repository.update()`；`add_member()` 在 mutation 内检查已有 Pig 的平台/用户二元组后才追加。`list_pigs()` 只调用 `repository.load()`。

- [ ] **Step 4: 导出并运行 GREEN。** 在 `core/__init__.py` 导出 `DuplicateMemberPigError` 和 `PigstyService`。

Run: `uv run --no-sync python -m pytest tests/test_service.py -q`

Expected: 所有服务测试通过，且测试确认第二个 owner 不会看到第一个 owner 的 Pig。

## Task 3: 表达和模拟公开 AstrBot 事件组件 API

**Files:**
- Modify: `typings/astrbot/api/event.pyi`
- Create: `typings/astrbot/api/message_components.pyi`
- Modify: `tests/fake_runtime/astrbot/api/event.py`
- Create: `tests/fake_runtime/astrbot/api/message_components.py`

- [ ] **Step 1: 写失败边界测试。** 在 `tests/test_plugin.py` 的 child-process script 中导入：

```python
from astrbot.api.message_components import At

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
```

- [ ] **Step 2: 运行 RED。**

Run: `uv run --no-sync python -m pytest tests/test_plugin.py -q`

Expected: child process cannot import `astrbot.api.message_components.At`。

- [ ] **Step 3: 最小实现。** 定义 frozen/slots `At`，公开只读 `qq: str`。扩展 fake/stub `AstrMessageEvent`：构造器接受 `sender_id: str = "42"`、`platform_id: str = "qq"`、`group_id: str | None = None`、`messages: tuple[object, ...] = ()`，并公开 `get_sender_id() -> str`、`get_platform_id() -> str`、`get_group_id() -> str | None`、`get_messages() -> tuple[object, ...]`。保留 `plain_result()` 返回 `MessageEventResult`。

- [ ] **Step 4: 运行 GREEN 与类型检查。**

Run: `uv run --no-sync python -m pytest tests/test_plugin.py -q`

Run: `uv run --no-sync basedpyright --pythonpath ".venv\Scripts\python.exe"`

Expected: 测试桩能表达公开 API，basedpyright 无诊断。

## Task 4: 接入 `pig add` 与 `pig show`

**Files:**
- Modify: `main.py:11-80`
- Modify: `tests/test_plugin.py`

- [ ] **Step 1: 写失败命令烟测。** 在 child-process script 中异步收集命令输出并断言：

```python
async def collect(
    event: AstrMessageEvent, action: str
) -> tuple[MessageEventResult, ...]:
    return tuple(result async for result in plugin.pig_command(event, action))


random_result = await collect(owner_event, "add")
target_result = await collect(target_event, "add")
shown_result = await collect(owner_event, "show")

assert random_result[0].text.startswith("已添加独立小猪：小猪-")
assert target_result[0].text.startswith("已将用户 target-1 添加为小猪：小猪-")
assert "你的猪圈共有 2 只小猪" in shown_result[0].text
assert "target-1" in shown_result[0].text
```

再调用一次 `target_event`，断言输出为重复提示且 `show` 仍显示 2 只。以另一个 sender 调用 `show`，断言其空列表输出，证明 target 没有成为 owner。

- [ ] **Step 2: 运行 RED。**

Run: `uv run --no-sync python -m pytest tests/test_plugin.py -q`

Expected: 现有命令把 `add`/`show` 视为未知 action。

- [ ] **Step 3: 最小实现。** 在 `PigstyPlugin.__init__()` 创建 `self.service = PigstyService(self.repository)`。新增私有 helper：

```python
def _identity_for_event(self, event: AstrMessageEvent) -> SessionIdentity: ...


def _member_target_for_event(self, event: AstrMessageEvent) -> str | None: ...


def _render_pigsty(self, pigs: tuple[Pig, ...]) -> str: ...
```

`_identity_for_event()` 使用 `resolve_session_identity(self.scope, event.get_platform_id(), event.get_sender_id(), event.get_group_id())`。`_member_target_for_event()` 只接受一个 `Comp.At`，拒绝多个、空 `qq` 或 `qq == "all"`。`pig_command()`：

- `status` 保持原响应；
- `add` 无 target 调用 `service.add_random(identity)`；
- `add` 有 target 调用 `service.add_member(identity, platform_id, target)`；
- `show` 调用 `service.list_pigs(identity)`；
- 捕获 `DuplicateMemberPigError` 并返回 `该用户已经在你的猪圈中。`；
- 非法 target 返回 `用法：pig add [@用户]`；
- 未知 action 返回 `用法：pig status | pig add [@用户] | pig show`。

`_render_pigsty()` 对空 tuple 返回指定空猪圈提示；对非空 tuple 以持久化顺序输出序号、`name`、`独立小猪` 或 `关联用户 <id>`、体重/健康/心情/体力，绝不读取或输出 `pig_id`。

- [ ] **Step 4: 运行 GREEN。**

Run: `uv run --no-sync python -m pytest tests/test_plugin.py -q`

Expected: `pig add`、单 @ 添加、重复拒绝、`pig show`、owner/target 隔离和 UUID 隐藏均通过。

## Task 5: 文档与全量验证

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-04-pigsty-macro-commands-design.md` only if implementation reveals a documented contract mismatch.

- [ ] **Step 1: 更新 README。** 以简短命令表说明 `pig status`、`pig add`、`pig add @用户`、`pig show`；明确调用者拥有自己的 database、@ 用户只作关联、重复关联被拒绝。

- [ ] **Step 2: 运行全量测试和严格类型检查。**

Run: `uv run --no-sync python -m pytest -q`

Run: `uv run --no-sync basedpyright --pythonpath ".venv\Scripts\python.exe"`

Expected: 全部 pytest 通过；basedpyright 为 `0 errors, 0 warnings, 0 notes`。

- [ ] **Step 3: 格式、lint 与运行时验证。**

Run: `uv run --no-sync --with "ruff @ file:///C:/Users/wkc20/AppData/Local/Temp/opencode/ruff-0.16.1-verified/ruff-0.16.1-py3-none-win_amd64.whl" ruff format --check .`

Run: `uv run --no-sync --with "ruff @ file:///C:/Users/wkc20/AppData/Local/Temp/opencode/ruff-0.16.1-verified/ruff-0.16.1-py3-none-win_amd64.whl" ruff check .`

Expected: `already formatted` 和 `All checks passed!`。

- [ ] **Step 4: 检查 LSP、规模和范围。** 对每个改动的 `.py/.pyi` 文件运行 LSP diagnostics；测量所有 `.py/.pyi` 的纯代码行并确认最大值不超过 250；搜索 production code，确认不存在 `feed`、`play`、`rename`、时间 Tick、LLM、内部 `astrbot.core` 导入或 Pig UUID 用户输出。

- [ ] **Step 5: 检查 Git 状态但不提交。**

Run: `git status --short`

Expected: 只显示本计划的源代码、测试、README、spec 和 plan 修改；不创建 commit，除非用户随后明确要求。
