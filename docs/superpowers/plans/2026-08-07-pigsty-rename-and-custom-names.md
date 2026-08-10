# Pigsty Rename and Custom Names Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support custom multi-word names when adding pigs and rename persisted pigs by their 1-based `pig show` position.

**Architecture:** Keep `main.py` as the AstrBot-only input boundary. It derives the multi-word text tail from `event.message_str`, keeps mention resolution on message components, and delegates all writes to `PigstyService`. Extend `PigstyService` with optional add names and one atomic index-based rename method; preserve the immutable Pydantic model and repository transaction boundary.

**Tech Stack:** Python 3.11, AnyIO, Pydantic v2, AstrBot public APIs, pytest, basedpyright, Ruff.

---

## File map

- `core/service.py`: Optional names, typed missing-index error, and atomic rename service.
- `tests/test_service.py`: Service-level custom-name and rename persistence tests.
- `typings/astrbot/api/event.pyi`: Declare the public `message_str` event attribute.
- `tests/fake_runtime/astrbot/api/event.py`: Simulate the same event attribute in plugin tests.
- `main.py`: Parse multi-word command tails; extend add; implement rename and stable result text.
- `tests/test_plugin.py`: Drive the new command paths through the AstrBot boundary.
- `README.md`: Replace the obsolete rename non-goal with the supported command contract.

### Task 1: Core service custom names and atomic rename

**Files:**
- Modify: `tests/test_service.py:23-76`
- Modify: `core/service.py:18-78`

- [ ] **Step 1: Write the failing service tests**

Add tests that call the wished-for APIs directly. Keep one behavior per test and use the existing `run_async()` helper.

```python
def test_add_random_persists_a_custom_name(tmp_path: Path) -> None:
    # Given an empty Pigsty for one owner
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        # When an independent pig is added with a multi-word name
        pig = await service.add_random(identity, "白雪 小猪")

        # Then the exact name is persisted
        assert pig.name == "白雪 小猪"
        assert await service.list_pigs(identity) == (pig,)

    run_async(scenario)


def test_add_member_persists_a_custom_name(tmp_path: Path) -> None:
    # Given an empty Pigsty for one owner
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        # When a member-linked pig is added with a multi-word name
        pig = await service.add_member(identity, "qq", "target", "花花 猪")

        # Then its name and member association are persisted
        assert pig.name == "花花 猪"
        assert pig.member_user_id == "target"
        assert await service.list_pigs(identity) == (pig,)

    run_async(scenario)
```

Add a separate rename success test and a missing-index test:

```python
def test_rename_pig_updates_only_the_selected_pig(tmp_path: Path) -> None:
    # Given an owner with independent and member-linked pigs
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        first = await service.add_random(identity, "原名")
        second = await service.add_member(identity, "qq", "target", "关联猪")

        # When the first show position is renamed
        renamed = await service.rename_pig(identity, 1, "新 名字")

        # Then only its name and update time change
        pigs = await service.list_pigs(identity)
        assert renamed.name == "新 名字"
        assert renamed.pig_id == first.pig_id
        assert renamed.member_user_id is None
        assert renamed.created_at == first.created_at
        assert renamed.updated_at >= first.updated_at
        assert pigs == (renamed, second)

    run_async(scenario)


def test_rename_pig_rejects_a_position_outside_the_pigsty(tmp_path: Path) -> None:
    # Given an owner with one pig
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        original = await service.add_random(identity, "原名")

        # When an absent show position is renamed
        with pytest.raises(PigPositionNotFoundError) as captured:
            _ = await service.rename_pig(identity, 2, "不会保存")

        # Then the original document stays unchanged
        assert captured.value.position == 2
        assert await service.list_pigs(identity) == (original,)

    run_async(scenario)
```

- [ ] **Step 2: Run the new service tests and confirm RED**

Run:

```powershell
uv run pytest tests/test_service.py -q
```

Expected: failure because `add_random`/`add_member` do not accept names and `rename_pig`/`PigPositionNotFoundError` do not exist.

- [ ] **Step 3: Implement the smallest service API**

Add a typed error adjacent to `DuplicateMemberPigError`:

```python
@dataclass(frozen=True, slots=True)
class PigPositionNotFoundError(Exception):
    """Raised when a 1-based pig display position does not exist."""

    position: int

    @override
    def __str__(self) -> str:
        return f"pig position {self.position} does not exist"
```

Extend both creators with `name: str | None = None`; use the existing generated name only when `name is None`:

```python
pig = Pig(
    pig_id=pig_id,
    name=f"小猪-{pig_id.hex[:8]}" if name is None else name,
)
```

For member pigs, retain the existing member fields and use the same name expression. Add this service method:

```python
async def rename_pig(
    self,
    identity: SessionIdentity,
    position: int,
    name: str,
) -> Pig:
    """Rename one persisted pig selected by its 1-based display position."""

    def rename(document: PigstyDocument) -> PigstyDocument:
        index = position - 1
        if index < 0 or index >= len(document.pigs):
            raise PigPositionNotFoundError(position)
        existing = document.pigs[index]
        renamed = Pig.model_validate(
            existing.model_dump() | {"name": name, "updated_at": utc_now()}
        )
        pigs = (*document.pigs[:index], renamed, *document.pigs[index + 1 :])
        return document.model_copy(update={"pigs": pigs})

    document = await self._repository.update(identity, rename)
    return document.pigs[position - 1]
```

Import `utc_now` beside `Pig` and `PigstyDocument`. Do not change the schema version, repository implementation, member-duplicate check, or default naming behavior.

- [ ] **Step 4: Run the service tests and confirm GREEN**

Run:

```powershell
uv run pytest tests/test_service.py -q
```

Expected: all service tests pass, including existing generated-name and duplicate-member coverage.

### Task 2: Type and fake-runtime support for raw command text

**Files:**
- Modify: `typings/astrbot/api/event.pyi:10-22`
- Modify: `tests/fake_runtime/astrbot/api/event.py:18-51`
- Test: `tests/test_plugin.py:30-213`

- [ ] **Step 1: Write the failing boundary test inputs**

In the child-process script in `tests/test_plugin.py`, construct custom-name events with explicit raw plain text while retaining `At` components separately:

```python
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
```

Call the existing `collect()` helper with actions `"add"` and `"rename"`; assert the success messages contain the complete multi-word names. Add an invalid `"pig rename 0 无效"` event and assert the rename usage text.

- [ ] **Step 2: Run the plugin test and confirm RED**

Run:

```powershell
uv run pytest tests/test_plugin.py::test_plugin_import_and_initialization_use_astrbot_boundary -q
```

Expected: the fake event constructor rejects `message_str`, proving the test exercises the missing framework boundary.

- [ ] **Step 3: Extend the public event contract in both test surfaces**

Change the fake runtime constructor and store the field:

```python
def __init__(
    self,
    sender_id: str = "42",
    platform_id: str = "qq",
    group_id: str | None = None,
    messages: tuple[object, ...] = (),
    message_str: str = "",
) -> None:
    self._sender_id: str = sender_id
    self._platform_id: str = platform_id
    self._group_id: str | None = group_id
    self._messages: tuple[object, ...] = messages
    self.message_str: str = message_str
```

Mirror the constructor parameter and public attribute in `typings/astrbot/api/event.pyi`:

```python
class AstrMessageEvent:
    message_str: str

    def __init__(
        self,
        sender_id: str = "42",
        platform_id: str = "qq",
        group_id: str | None = None,
        messages: tuple[_MessageComponent, ...] = (),
        message_str: str = "",
    ) -> None: ...
```

- [ ] **Step 4: Re-run the focused boundary test**

Run:

```powershell
uv run pytest tests/test_plugin.py::test_plugin_import_and_initialization_use_astrbot_boundary -q
```

Expected: it now fails only because `PigstyPlugin.pig_command` has not implemented custom names or rename.

### Task 3: Parse command tails and wire the AstrBot command behavior

**Files:**
- Modify: `main.py:5-167`
- Modify: `tests/test_plugin.py:99-199`

- [ ] **Step 1: Complete the failing command assertions**

Extend `assert_macro_commands()` to prove all observable behavior:

```python
named_results = await collect(named_owner_event, "add")
assert named_results[0].text == "已添加独立小猪：白雪 小猪"

named_target_results = await collect(named_target_event, "add")
assert named_target_results[0].text == "已将用户 target-2 添加为小猪：花花 猪"

rename_results = await collect(rename_event, "rename")
assert rename_results[0].text == "已将第 1 只小猪改名为：粉红 小猪"

shown_after_rename = await collect(owner_event, "show")
assert "1. 粉红 小猪" in shown_after_rename[0].text
assert "白雪 小猪" in shown_after_rename[0].text
assert "花花 猪" in shown_after_rename[0].text

invalid_rename_results = await collect(invalid_rename_event, "rename")
assert invalid_rename_results[0].text == "用法：pig rename <序号> <新名字>"
```

Update the unknown-command assertion to the complete new usage text. Ensure the test still checks UUID secrecy, owner isolation, duplicate members, invalid At handling, and no-name generated-name behavior.

- [ ] **Step 2: Run the focused plugin test and confirm RED**

Run:

```powershell
uv run pytest tests/test_plugin.py::test_plugin_import_and_initialization_use_astrbot_boundary -q
```

Expected: custom add and rename assertions fail while existing paths remain intact.

- [ ] **Step 3: Implement boundary parsing and command branches**

Import `re`, `ValidationError`, and `PigPositionNotFoundError`. Add one shared helper to find an action as a full token and preserve its complete text tail:

```python
@staticmethod
def _command_tail(event: AstrMessageEvent, action: str) -> str:
    """Return trimmed raw text after one command action token."""
    pattern = re.compile(rf"(?:^|\s){re.escape(action)}(?:\s+|$)", re.IGNORECASE)
    match = pattern.search(event.message_str)
    return "" if match is None else event.message_str[match.end() :].strip()
```

In the `add` branch, pass `self._command_tail(event, normalized_action) or None` to the service creator. Preserve the existing `At` target validation and `DuplicateMemberPigError` handling.

Add a `rename` branch before `show`:

```python
tail = self._command_tail(event, normalized_action)
parts = tail.split(maxsplit=1)
if len(parts) != 2 or not parts[1].strip():
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
        self._identity_for_event(event), position, parts[1].strip()
    )
except PigPositionNotFoundError:
    yield event.plain_result("用法：pig rename <序号> <新名字>")
    return
yield event.plain_result(f"已将第 {position} 只小猪改名为：{pig.name}")
```

Map Pydantic `ValidationError` from command-supplied names to a stable message such as `猪名字不能为空且不能超过 32 个字符。`; do not truncate names. Update all add and unknown-command usage text to include `[名字]` and rename.

- [ ] **Step 4: Run the focused plugin test and confirm GREEN**

Run:

```powershell
uv run pytest tests/test_plugin.py::test_plugin_import_and_initialization_use_astrbot_boundary -q
```

Expected: one focused plugin test passes, with all previous and new command assertions successful.

### Task 4: Documentation and full verification

**Files:**
- Modify: `README.md:5-20`
- Verify: `main.py`, `core/service.py`, `typings/astrbot/api/event.pyi`, `tests/fake_runtime/astrbot/api/event.py`, `tests/test_service.py`, `tests/test_plugin.py`

- [ ] **Step 1: Update the README command contract**

Replace the obsolete “不实现改名” statement and extend the command list with:

```markdown
- `pig add [名字]`：在调用者自己的猪圈中添加一只独立小猪；省略名字时自动命名，名字支持空格。
- `pig add @用户 [名字]`：添加与目标用户关联的小猪；省略名字时自动命名，名字支持空格。
- `pig rename 序号 新名字`：按 `pig show` 中从 1 开始的序号改名；不展示内部 UUID。
```

Update the unknown-command usage text to exactly match the implementation.

- [ ] **Step 2: Run focused tests**

Run:

```powershell
uv run pytest tests/test_service.py tests/test_plugin.py -q
```

Expected: all service and plugin tests pass.

- [ ] **Step 3: Run full quality gates**

Run the project checks:

```powershell
uv run pytest -q
uv run basedpyright --pythonpath ".venv\Scripts\python.exe"
uv run ruff format --check .
uv run ruff check .
```

Expected: all tests pass; basedpyright reports zero errors, warnings, and notes; Ruff reports every file formatted and all checks passed.

- [ ] **Step 4: Inspect modified Python files and the final diff**

Run diagnostics in parallel for `main.py`, `core/service.py`, `tests/test_service.py`, `tests/test_plugin.py`, and `tests/fake_runtime/astrbot/api/event.py`; then run:

```powershell
git diff --check
git diff -- main.py core/service.py typings/astrbot/api/event.pyi tests/fake_runtime/astrbot/api/event.py tests/test_service.py tests/test_plugin.py README.md
```

Expected: no diagnostics, no whitespace errors, and a diff limited to this approved feature and its documentation/tests.

## Plan self-review

- **Spec coverage:** Tasks 1–3 cover optional names, 1-based rename, whitespace-preserving tail parsing, atomic persistence, typed missing-position behavior, and unchanged UUID/owner semantics. Task 4 covers README and all quality gates.
- **Placeholder scan:** No incomplete steps or deferred validation remain; every code change includes a concrete target, test, command, and expected outcome.
- **Type consistency:** `PigPositionNotFoundError`, `rename_pig(identity, position, name)`, `message_str`, and the 1-based `position` terminology are used consistently across all tasks.
