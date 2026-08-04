from __future__ import annotations

import json
from typing import TYPE_CHECKING, TypeVar

import anyio
import pytest
from core.identity import PigstyScope, resolve_session_identity
from core.models import Pig, PigstyDocument
from core.repository import JsonPigstyRepository, PigstyDataError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from core.identity import SessionIdentity

ResultT = TypeVar("ResultT")


def run_async(operation: Callable[[], Awaitable[ResultT]]) -> ResultT:
    """Run one repository scenario on AnyIO's default backend."""
    return anyio.run(operation)


def make_pig(user_id: str) -> Pig:
    """Build a deterministic test Pig for one member id."""
    return Pig(member_platform_id="qq", member_user_id=user_id, name=f"Pig-{user_id}")


def make_document(
    identity: SessionIdentity, pigs: tuple[Pig, ...] = ()
) -> PigstyDocument:
    """Build a document with the identity's effective persisted scope."""
    return PigstyDocument(
        scope=identity.scope,
        platform_id=identity.platform_id,
        owner_user_id=identity.owner_user_id,
        group_id=identity.group_id,
        pigs=pigs,
    )


def test_missing_file_returns_empty_without_creating_file(tmp_path: Path) -> None:
    # Given an empty repository and a valid owner identity
    repo = JsonPigstyRepository(tmp_path)
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", None)

    # When the owner document is loaded
    document = run_async(lambda: repo.load(identity))

    # Then an empty matching document is returned and no file is created
    assert document == make_document(identity)
    assert not repo.path_for(identity).exists()


def test_different_owners_are_isolated(tmp_path: Path) -> None:
    # Given two global owners in the same platform
    repo = JsonPigstyRepository(tmp_path)
    first = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    second = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-b", None)

    async def scenario() -> None:
        await repo.save(make_document(first, (make_pig("member-a"),)))

        # When the second owner is loaded
        loaded = await repo.load(second)

        # Then the second owner sees an independent empty Pigsty
        assert loaded == make_document(second)

    run_async(scenario)


def test_group_scope_isolated_by_group_id(tmp_path: Path) -> None:
    # Given one owner in two different groups
    repo = JsonPigstyRepository(tmp_path)
    first = resolve_session_identity(PigstyScope.GROUP, "qq", "42", "group-a")
    second = resolve_session_identity(PigstyScope.GROUP, "qq", "42", "group-b")

    async def scenario() -> None:
        await repo.save(make_document(first, (make_pig("member-a"),)))

        # When the same owner loads the other group
        loaded = await repo.load(second)

        # Then the other group remains empty
        assert loaded == make_document(second)

    run_async(scenario)


def test_group_scope_private_chat_uses_private_namespace(tmp_path: Path) -> None:
    # Given a group-scoped private message identity
    repo = JsonPigstyRepository(tmp_path)
    identity = resolve_session_identity(PigstyScope.GROUP, "qq", "42", None)

    async def scenario() -> None:
        pig = make_pig("member-a")
        await repo.save(make_document(identity, (pig,)))
        loaded = await repo.load(identity)

        # Then it is persisted below the private namespace and reloads correctly
        assert loaded.pigs == (pig,)

    run_async(scenario)
    assert identity.relative_path().parts[:2] == ("owners", "private")


def test_global_scope_shares_across_group_ids(tmp_path: Path) -> None:
    # Given one owner using global scope from two group messages
    repo = JsonPigstyRepository(tmp_path)
    first = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", "group-a")
    second = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", "group-b")

    async def scenario() -> None:
        pig = make_pig("member-a")
        await repo.save(make_document(first, (pig,)))

        # When the same owner loads through the other group
        loaded = await repo.load(second)

        # Then the same global Pigsty is returned
        assert loaded.pigs == (pig,)

    run_async(scenario)


def test_save_writes_formatted_json_without_raw_identity(tmp_path: Path) -> None:
    # Given a group identity containing path-sensitive values
    repo = JsonPigstyRepository(tmp_path)
    identity = resolve_session_identity(
        PigstyScope.GROUP,
        "qq/unsafe",
        "secret-user-42",
        "group:1",
    )

    async def scenario() -> None:
        await repo.save(make_document(identity))

    # When the document is saved
    run_async(scenario)
    path = repo.path_for(identity)
    raw = path.read_text(encoding="utf-8")

    # Then JSON is UTF-8, formatted, valid, and temporary files are absent
    assert raw.endswith("\n")
    assert json.loads(raw)["pigs"] == []
    assert "secret-user-42" not in str(path)
    assert "group:1" not in str(path)
    assert not list(path.parent.glob(".*.tmp"))


def test_concurrent_updates_preserve_every_mutation(tmp_path: Path) -> None:
    # Given one shared identity and an empty repository
    repo = JsonPigstyRepository(tmp_path)
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", None)

    async def scenario() -> None:
        async def add_one() -> None:
            def mutation(document: PigstyDocument) -> PigstyDocument:
                next_id = str(len(document.pigs))
                return document.model_copy(
                    update={"pigs": (*document.pigs, make_pig(next_id))}
                )

            _ = await repo.update(identity, mutation)

        async with anyio.create_task_group() as task_group:
            for _ in range(20):
                _ = task_group.start_soon(add_one)

        # When the final document is loaded
        loaded = await repo.load(identity)

        # Then every serialized update is present exactly once
        assert len(loaded.pigs) == 20
        assert {pig.member_user_id for pig in loaded.pigs} == {
            str(index) for index in range(20)
        }

    run_async(scenario)


def test_corrupt_json_raises_without_overwriting_file(tmp_path: Path) -> None:
    # Given a corrupt owner file
    repo = JsonPigstyRepository(tmp_path)
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", None)
    path = repo.path_for(identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_content = "{not-json"
    _ = path.write_text(corrupt_content, encoding="utf-8")

    # When the corrupt file is loaded
    with pytest.raises(PigstyDataError) as captured:
        _ = run_async(lambda: repo.load(identity))

    # Then the error identifies the path and the corrupt content remains untouched
    assert captured.value.path == path
    assert path.read_text(encoding="utf-8") == corrupt_content
