# Pigsty Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a loadable AstrBot Pigsty plugin foundation with typed Pig/PigstyDocument models, scope-aware hashed JSON persistence, and automated tests.

**Architecture:** Keep `core/` independent of `astrbot.*`. `identity.py` turns a platform/session tuple into a normalized, hashed storage identity; `models.py` owns all Pydantic v2 boundary contracts; `repository.py` owns async file I/O, process-local update serialization, and atomic replacement. `main.py` is the only AstrBot adapter and only exposes the phase-one `pig status` command.

**Tech Stack:** Python 3.13, Pydantic v2, AnyIO 4, pytest, uv, Ruff, basedpyright, AstrBot plugin API.

---

## File map

- Create `main.py`: AstrBot `Star` subclass, config parsing, data-directory wiring, and `pig status`.
- Create `metadata.yaml`: plugin metadata and supported AstrBot version.
- Create `_conf_schema.json`: `pigsty_scope` selector with `global` default.
- Create `requirements.txt`: runtime dependencies for an AstrBot installation that does not resolve the project manifest.
- Create `pyproject.toml`: package metadata, runtime/dev dependencies, strict basedpyright, Ruff, and pytest settings.
- Create `README.md`: phase-one scope and local verification commands.
- Create `core/__init__.py`: explicit public core exports.
- Create `core/identity.py`: `PigstyScope`, `SessionIdentity`, normalization, effective scope, and hashed relative paths.
- Create `core/models.py`: frozen strict `Pig`, `PigstyDocument`, UTC validation, and typed persistence errors.
- Create `core/repository.py`: `JsonPigstyRepository`, async load/save/update, atomic JSON writes, and path-aware errors.
- Create `tests/test_identity.py`: identity and path isolation tests.
- Create `tests/test_models.py`: model defaults, bounds, UTC, schema version, and JSON round-trip tests.
- Create `tests/test_repository.py`: missing files, isolation, global sharing, atomic writes, concurrent updates, and corruption handling.
- Create `tests/test_plugin.py`: import smoke test with an explicit AstrBot test stub only when the runtime package is unavailable.

## Task 1: Identity and storage key

**Files:**
- Create: `tests/test_identity.py`
- Create: `core/identity.py`

- [ ] **Step 1: Write the failing tests.** Cover these exact contracts:

```python
def test_global_identity_is_shared_across_group_ids() -> None:
    first = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", "group-a")
    second = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", "group-b")
    assert first.relative_key == second.relative_key


def test_group_identity_separates_group_chat_and_private_chat() -> None:
    group = resolve_session_identity(PigstyScope.GROUP, "qq", "42", "group-a")
    private = resolve_session_identity(PigstyScope.GROUP, "qq", "42", None)
    assert group.relative_key != private.relative_key
    assert private.effective_scope is PigstyScope.GLOBAL


def test_storage_path_contains_only_hashes() -> None:
    identity = resolve_session_identity(
        PigstyScope.GROUP, "qq/unsafe", "../owner", "group:1"
    )
    path = identity.relative_path()
    assert "unsafe" not in str(path)
    assert "owner" not in str(path)
    assert path.parts[:2] == ("owners", "groups")
```

- [ ] **Step 2: Run the focused test and confirm a feature-shaped RED.**

Run: `uv run pytest tests/test_identity.py -q`

Expected: collection fails because `core.identity` and its public functions do not exist yet; do not proceed if the failure is caused by a typo in the test.

- [ ] **Step 3: Implement the smallest typed identity module.** Define `PigstyScope(StrEnum)` with `GLOBAL` and `GROUP`; define frozen/slots `SessionIdentity` with normalized `platform_id`, `owner_user_id`, and optional `group_id`; make `relative_key` include platform and owner, make `effective_scope` map group-mode private messages to global, and make `relative_path()` use SHA-256 digests under `owners/global`, `owners/private`, or `owners/groups/<group-hash>`.

- [ ] **Step 4: Run the focused test and refactor only while green.**

Run: `uv run pytest tests/test_identity.py -q`

Expected: all identity tests pass and no external identifier appears in a generated path.

## Task 2: Pydantic persistence models

**Files:**
- Create: `tests/test_models.py`
- Create: `core/models.py`

- [ ] **Step 1: Write failing tests for the model boundary.** Test `Pig` default values, UUID generation, rejection of empty/whitespace names, age/weight/status bounds, timezone-aware UTC timestamps, and JSON round-trip. Test `PigstyDocument.empty_for_identity()` and rejection of an unknown `schema_version`.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_models.py -q`

Expected: collection or assertion failure caused by missing model symbols, not an invalid fixture.

- [ ] **Step 3: Implement strict frozen Pydantic v2 models.** Use `ConfigDict(strict=True, frozen=True, extra="forbid")`; use `UUID`, `datetime`, `Literal[1]`, `Field(ge=..., le=...)`, and field validators that reject naive datetimes and normalize aware datetimes to UTC. Keep `pig_id` in persisted state but do not expose it from any user-facing command.

- [ ] **Step 4: Run model tests and keep the implementation minimal.**

Run: `uv run pytest tests/test_models.py -q`

Expected: all model tests pass, including serialized ISO-8601 offsets and list-shaped JSON for `pigs`.

## Task 3: Atomic JSON repository

**Files:**
- Create: `tests/test_repository.py`
- Create: `core/repository.py`

- [ ] **Step 1: Write failing repository tests.** Use `tmp_path` and `anyio.run()` rather than an asyncio-specific fixture. Cover: missing file returns a matching empty document without creating a file; two owners are isolated; group identities are isolated; global identities share across groups; save creates formatted UTF-8 JSON; no temporary files remain after save; concurrent `update()` calls preserve every mutation; malformed JSON raises `PigstyDataError` and leaves the corrupt file untouched.

- [ ] **Step 2: Run RED.**

Run: `uv run pytest tests/test_repository.py -q`

Expected: failure because `JsonPigstyRepository` is missing; any JSON or concurrency failure before implementation means the test fixture is wrong and must be corrected.

- [ ] **Step 3: Implement the repository.** Keep a repository-level `anyio.Lock`; route `Path.read_text`, `Path.mkdir`, and atomic writes through `anyio.to_thread.run_sync`. Parse every existing file with `json.loads` then `PigstyDocument.model_validate`; catch only `FileNotFoundError`, `OSError`, `JSONDecodeError`, and Pydantic `ValidationError`, converting data failures to a frozen/slots `PigstyDataError(path, reason)`. Write to a same-directory named temporary file, flush and `os.fsync()` it, then call `os.replace()`; clean only the temporary path in `finally`. `update(identity, mutation)` must read, call a typed synchronous mutation, verify the returned document still represents the supplied identity, and save while holding the lock.

- [ ] **Step 4: Run the repository tests and refactor only after green.**

Run: `uv run pytest tests/test_repository.py -q`

Expected: all repository behavior passes, including concurrent update preservation and refusal to replace corrupt data.

## Task 4: Package and AstrBot boundary

**Files:**
- Create: `core/__init__.py`, `main.py`, `metadata.yaml`, `_conf_schema.json`, `requirements.txt`, `pyproject.toml`, `README.md`
- Create: `tests/test_plugin.py`

- [ ] **Step 1: Add the configuration and metadata files.** Declare `astrbot_version: ">=4.16,<5"` in `metadata.yaml`; define `_conf_schema.json` with a string `pigsty_scope`, default `global`, and options `global`/`group`; list `pydantic>=2.11,<3` and `anyio>=4.9,<5` in runtime dependencies. Configure `uv` project metadata plus strict basedpyright, Ruff `select = ["ALL"]` with only documented formatter/docstyle/test exceptions, and pytest strict settings.

- [ ] **Step 2: Write the failing plugin smoke test.** Verify the module exports `PigstyPlugin`, that the class subclasses AstrBot `Star` in a real AstrBot runtime, and that the source does not import `astrbot.*` from `core/`. If AstrBot is not installed in the local environment, install no new global packages and use a small test-only `sys.modules` stub that supplies `Context`, `Star`, `StarTools`, `AstrBotConfig`, `filter.command`, and `register`.

- [ ] **Step 3: Run RED.**

Run: `uv run pytest tests/test_plugin.py -q`

Expected: the test fails because `main.py` and/or `PigstyPlugin` do not exist.

- [ ] **Step 4: Implement the minimal adapter.** In `main.py`, import `Star`, `Context`, `StarTools`, `AstrBotConfig`, `AstrMessageEvent`, and `filter` only at the adapter boundary; construct the data directory with `StarTools.get_data_dir("astrabot_plugin_pigsty")`; parse `pigsty_scope` into `PigstyScope`; construct `JsonPigstyRepository`; implement `@filter.command("pig")` as an async generator that returns `pig status` text containing only the scope and readiness, never Pig UUIDs; leave `terminate()` as an async no-op.

- [ ] **Step 5: Run the plugin smoke test.**

Run: `uv run pytest tests/test_plugin.py -q`

Expected: the import and boundary checks pass without touching the real AstrBot data directory.

## Task 5: Full verification and review

**Files:** all files created above.

- [ ] **Step 1: Format and lint.**

Run: `uv run ruff format .` followed by `uv run ruff check .`

Expected: Ruff formats the project and reports zero lint violations.

- [ ] **Step 2: Run the complete test suite.**

Run: `uv run pytest -q`

Expected: zero failures and zero warnings, with all tests using temporary directories.

- [ ] **Step 3: Run strict type checking.**

Run: `uv run basedpyright`

Expected: zero errors. Do not use `Any`, `cast`, `# type: ignore`, or broad exception handlers to silence diagnostics.

- [ ] **Step 4: Run the closest runtime smoke check.**

Run: `uv run python -c "from pathlib import Path; import anyio; from core.identity import PigstyScope, resolve_session_identity; from core.repository import JsonPigstyRepository; async def main(): ...; anyio.run(main)"` using the repository API to save and reload one document below a temporary directory.

Expected: the reloaded document equals the saved document and the generated path contains only digest components.

- [ ] **Step 5: Re-read the approved spec and inspect every changed file.** Confirm every phase-one requirement is covered and explicitly confirm no `pig add`, state evolution, LLM parsing, admin migration, or dashboard code was added. No Git commit is part of this task.
