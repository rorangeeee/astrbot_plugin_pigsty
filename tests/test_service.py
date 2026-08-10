from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import anyio
import pytest
from core.identity import PigstyScope, resolve_session_identity
from core.repository import JsonPigstyRepository
from core.service import (
    DuplicateMemberPigError,
    PigPositionNotFoundError,
    PigstyService,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

ResultT = TypeVar("ResultT")


def run_async(operation: Callable[[], Awaitable[ResultT]]) -> ResultT:
    """Run one service scenario on AnyIO's default backend."""
    return anyio.run(operation)


def test_add_random_creates_an_independent_named_pig(tmp_path: Path) -> None:
    # Given an empty Pigsty for one owner
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        # When an independent pig is added
        pig = await service.add_random(identity)

        # Then it has no member association and a UUID-derived name
        assert pig.member_platform_id is None
        assert pig.member_user_id is None
        assert pig.name == f"小猪-{pig.pig_id.hex[:8]}"
        assert await service.list_pigs(identity) == (pig,)

    run_async(scenario)


def test_add_member_creates_a_member_linked_pig(tmp_path: Path) -> None:
    # Given an empty Pigsty for one owner
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        # When a member-linked pig is added
        pig = await service.add_member(identity, "qq", "target")

        # Then the member pair and generated name are persisted
        assert pig.member_platform_id == "qq"
        assert pig.member_user_id == "target"
        assert pig.name == f"小猪-{pig.pig_id.hex[:8]}"
        assert await service.list_pigs(identity) == (pig,)

    run_async(scenario)


def test_add_member_rejects_duplicate_member_pair(tmp_path: Path) -> None:
    # Given an owner with one member-linked pig
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        first = await service.add_member(identity, "qq", "target")

        # When the same member pair is added again
        with pytest.raises(DuplicateMemberPigError) as captured:
            _ = await service.add_member(identity, "qq", "target")

        # Then the typed conflict identifies the duplicate pair and no extra pig exists
        assert captured.value.platform_id == "qq"
        assert captured.value.user_id == "target"
        assert await service.list_pigs(identity) == (first,)

    run_async(scenario)


def test_list_pigs_preserves_creation_order(tmp_path: Path) -> None:
    # Given one owner with two pigs
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        first = await service.add_random(identity)
        second = await service.add_member(identity, "qq", "target")

        # When the owner's pigs are listed
        pigs = await service.list_pigs(identity)

        # Then a tuple in persisted creation order is returned
        assert pigs == (first, second)
        assert isinstance(pigs, tuple)

    run_async(scenario)


def test_service_isolates_pigs_by_owner_identity(tmp_path: Path) -> None:
    # Given two owners using the same repository
    first_identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    second_identity = resolve_session_identity(
        PigstyScope.GLOBAL, "qq", "owner-b", None
    )
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        # When one owner adds a pig
        first = await service.add_random(first_identity)

        # Then the other owner remains independent
        assert await service.list_pigs(second_identity) == ()
        assert await service.list_pigs(first_identity) == (first,)

    run_async(scenario)


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
