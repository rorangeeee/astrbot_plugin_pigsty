from __future__ import annotations

import random
from datetime import timedelta
from typing import TYPE_CHECKING, TypeVar

import anyio
import pytest
from core.identity import PigstyScope, resolve_session_identity
from core.randomizer import roll_initial_stats
from core.repository import JsonPigstyRepository
from core.service import (
    DuplicateMemberPigError,
    PigPositionNotFoundError,
    PigstyService,
)
from tests.conftest import ScriptedRng

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
        creation = await service.add_random(identity)
        pig = creation.pig

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
        creation = await service.add_member(identity, "qq", "target")
        pig = creation.pig

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
        first = (await service.add_member(identity, "qq", "target")).pig

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
        first = (await service.add_random(identity)).pig
        second = (await service.add_member(identity, "qq", "target")).pig

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
        first = (await service.add_random(first_identity)).pig

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
        pig = (await service.add_random(identity, "白雪 小猪")).pig

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
        pig = (await service.add_member(identity, "qq", "target", "花花 猪")).pig

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
        first = (await service.add_random(identity, "原名")).pig
        second = (await service.add_member(identity, "qq", "target", "关联猪")).pig

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
        original = (await service.add_random(identity, "原名")).pig

        # When an absent show position is renamed
        with pytest.raises(PigPositionNotFoundError) as captured:
            _ = await service.rename_pig(identity, 2, "不会保存")

        # Then the original document stays unchanged
        assert captured.value.position == 2
        assert await service.list_pigs(identity) == (original,)

    run_async(scenario)


def test_add_random_applies_the_initial_stat_roll(tmp_path: Path) -> None:
    # Given an empty Pigsty for one owner and a seeded random source
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        # When an independent pig is added with a seeded roll
        expected = roll_initial_stats(random.Random(42))
        creation = await service.add_random(identity, rng=random.Random(42))

        # Then every rolled value is persisted and the full roll is reported
        assert creation.roll == expected
        assert creation.pig.weight_kg == expected.values()["weight_kg"]
        assert creation.pig.health == expected.values()["health"]
        assert creation.pig.mood == expected.values()["mood"]
        assert creation.pig.energy == expected.values()["energy"]
        assert await service.list_pigs(identity) == (creation.pig,)

    run_async(scenario)


def test_add_member_applies_the_initial_stat_roll(tmp_path: Path) -> None:
    # Given an empty Pigsty for one owner and a seeded random source
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))

    async def scenario() -> None:
        # When a member-linked pig is added with a seeded roll
        expected = roll_initial_stats(random.Random(7))
        creation = await service.add_member(
            identity, "qq", "target", rng=random.Random(7)
        )

        # Then rolled stats, member association, and the roll report persist
        assert creation.roll == expected
        assert creation.pig.member_platform_id == "qq"
        assert creation.pig.member_user_id == "target"
        assert creation.pig.mood == expected.values()["mood"]
        assert await service.list_pigs(identity) == (creation.pig,)

    run_async(scenario)


def test_creation_reports_stats_outside_the_normal_tier(tmp_path: Path) -> None:
    # Given an empty Pigsty and a scripted roll with one extreme stat
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    service = PigstyService(JsonPigstyRepository(tmp_path))
    rng = ScriptedRng(
        randoms=[0.5, 0.99, 0.5, 0.5],
        uniforms=[1.0, 0.0, 50.0, 1.0, 1.0],
    )

    async def scenario() -> None:
        # When an independent pig is added
        creation = await service.add_random(identity, rng=rng)

        # Then only the extreme stat is reported as an anomaly
        assert tuple(stat.key for stat in creation.roll.anomalies) == ("health",)
        assert creation.pig.health == 50

    run_async(scenario)


def test_evolve_all_due_evolves_every_due_pig(tmp_path: Path) -> None:
    # Given two owners each with one pig
    repo = JsonPigstyRepository(tmp_path)
    service = PigstyService(repo)
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    other = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-b", None)

    async def scenario() -> None:
        first = (await service.add_random(identity)).pig
        second = (await service.add_member(other, "qq", "target")).pig
        future = first.last_state_update_at + timedelta(days=2)

        # When a daily trigger runs two days later
        summary = await service.evolve_all_due(future)

        # Then both pigs are evolved once and one real-time event is recorded each
        assert summary.evolved_pigs == 2
        assert summary.recorded_events == 2
        assert summary.failed_documents == 0
        assert summary.scanned_documents == 2
        pigs = await service.list_pigs(identity)
        assert pigs[0].age_days == first.age_days + 2
        assert pigs[0].weight_kg > first.weight_kg
        events = await service.list_events(identity)
        assert len(events) == 1
        assert events[0].pig_id == first.pig_id
        assert events[0].description.startswith("年龄+2")
        other_pigs = await service.list_pigs(other)
        assert other_pigs[0].age_days == second.age_days + 2

    run_async(scenario)


def test_evolve_all_due_is_idempotent_within_one_day(tmp_path: Path) -> None:
    # Given one owner with one pig
    service = PigstyService(JsonPigstyRepository(tmp_path))
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)

    async def scenario() -> None:
        pig = (await service.add_random(identity)).pig
        future = pig.last_state_update_at + timedelta(days=1)

        # When the same trigger moment runs twice
        first_summary = await service.evolve_all_due(future)
        second_summary = await service.evolve_all_due(future)

        # Then the second pass finds nothing owed
        assert first_summary.evolved_pigs == 1
        assert second_summary.evolved_pigs == 0
        assert second_summary.recorded_events == 0
        events = await service.list_events(identity)
        assert len(events) == 1

    run_async(scenario)


def test_evolve_all_due_skips_fresh_pigs(tmp_path: Path) -> None:
    # Given one pig created moments ago
    service = PigstyService(JsonPigstyRepository(tmp_path))
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)

    async def scenario() -> None:
        pig = (await service.add_random(identity)).pig

        # When a trigger runs one hour after creation
        future = pig.last_state_update_at + timedelta(hours=1)
        summary = await service.evolve_all_due(future)

        # Then the same-day pig is not evolved
        assert summary.evolved_pigs == 0
        assert summary.recorded_events == 0
        assert await service.list_events(identity) == ()

    run_async(scenario)


def test_evolve_all_due_tolerates_corrupt_documents(tmp_path: Path) -> None:
    # Given one valid pig and one corrupt owner document
    repo = JsonPigstyRepository(tmp_path)
    service = PigstyService(repo)
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-a", None)
    other = resolve_session_identity(PigstyScope.GLOBAL, "qq", "owner-b", None)

    async def scenario() -> None:
        valid = (await service.add_random(identity)).pig
        path = repo.path_for(other)
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text("{not-json", encoding="utf-8")
        future = valid.last_state_update_at + timedelta(days=1)

        # When the daily trigger runs
        summary = await service.evolve_all_due(future)

        # Then the corrupt document is reported while valid pigs still evolve
        assert summary.failed_documents == 1
        assert summary.evolved_pigs == 1
        pigs = await service.list_pigs(identity)
        assert pigs[0].age_days == valid.age_days + 1

    run_async(scenario)
