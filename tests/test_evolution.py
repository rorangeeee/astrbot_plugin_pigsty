from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest
from core.evolution import (
    DAY_TZ,
    daily_tick_reached,
    evolve_document,
    evolve_pig_days,
    is_due,
    missed_day_count,
    next_tick_at,
)
from core.identity import PigstyScope
from core.models import REGULAR_EVENT_CATEGORY, Pig, PigstyDocument, utc_now
from tests.conftest import ScriptedRng

DAY = timedelta(days=1)


def make_pig(
    last_state_update_at: datetime | None = None,
    *,
    mood: int = 50,
    health: int = 50,
) -> Pig:
    """Build a deterministic pig with optional evolution timestamps."""
    return Pig(
        name="测试猪",
        mood=mood,
        health=health,
        last_state_update_at=last_state_update_at or utc_now(),
    )


def test_next_tick_at_before_nine_returns_today_nine() -> None:
    # Given a GMT+8 moment before the daily tick hour
    now = datetime(2026, 8, 14, 8, 59, 59, tzinfo=DAY_TZ)

    # When the next tick is computed
    # Then it is today's 9:00 GMT+8
    assert next_tick_at(now) == datetime(2026, 8, 14, 9, 0, tzinfo=DAY_TZ)


def test_next_tick_at_on_or_after_nine_returns_tomorrow_nine() -> None:
    # Given GMT+8 moments at and after the daily tick hour
    at_nine = datetime(2026, 8, 14, 9, 0, tzinfo=DAY_TZ)
    after_nine = datetime(2026, 8, 14, 23, 30, tzinfo=DAY_TZ)

    # When the next tick is computed
    # Then both fall strictly after now, on the next 9:00
    assert next_tick_at(at_nine) == datetime(2026, 8, 15, 9, 0, tzinfo=DAY_TZ)
    assert next_tick_at(after_nine) == datetime(2026, 8, 15, 9, 0, tzinfo=DAY_TZ)


def test_next_tick_at_converts_utc_input() -> None:
    # Given 09:00 GMT+8 expressed in UTC (01:00)
    now = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)

    # When the next tick is computed
    # Then the moment is strictly after now in absolute time
    assert next_tick_at(now) == datetime(2026, 8, 15, 9, 0, tzinfo=DAY_TZ)


def test_daily_tick_reached_boundary() -> None:
    # Given GMT+8 moments around the daily tick hour
    before = datetime(2026, 8, 14, 8, 59, 59, tzinfo=DAY_TZ)
    at_nine = datetime(2026, 8, 14, 9, 0, tzinfo=DAY_TZ)
    after = datetime(2026, 8, 14, 9, 0, 1, tzinfo=DAY_TZ)

    # When the tick readiness is checked
    # Then only moments at or after 9:00 count as reached
    assert daily_tick_reached(before) is False
    assert daily_tick_reached(at_nine) is True
    assert daily_tick_reached(after) is True


def test_missed_day_count_uses_gmt8_calendar_days() -> None:
    # Given a pig last updated on the current GMT+8 day
    now = datetime(2026, 8, 14, 12, 0, tzinfo=DAY_TZ)
    today = make_pig(datetime(2026, 8, 14, 3, 0, tzinfo=DAY_TZ))
    yesterday = make_pig(datetime(2026, 8, 13, 20, 0, tzinfo=DAY_TZ))
    last_week = make_pig(datetime(2026, 8, 8, 9, 0, tzinfo=DAY_TZ))

    # When owed days are computed
    # Then only complete missed calendar days count
    assert missed_day_count(today, now) == 0
    assert is_due(today, now) is False
    assert missed_day_count(yesterday, now) == 1
    assert is_due(yesterday, now) is True
    assert missed_day_count(last_week, now) == 6
    assert is_due(last_week, now) is True


def test_evolve_pig_days_applies_all_daily_rules() -> None:
    # Given a pig and a scripted single-day roll
    pig = make_pig()
    occurred_at = datetime(2026, 8, 14, 9, 0, tzinfo=DAY_TZ)
    rng = ScriptedRng(uniforms=[0.53, -2.0, 1.0, 65.0])

    # When one day is evolved
    evolved, event = evolve_pig_days(pig, 1, occurred_at, rng)

    # Then every rule is applied and one real-time event is recorded
    assert evolved.age_days == pig.age_days + 1
    assert evolved.weight_kg == pytest.approx(5.53)
    assert evolved.mood == 48
    assert evolved.health == 51
    assert evolved.energy == 65
    assert evolved.born_at == pig.born_at
    assert evolved.created_at == pig.created_at
    assert evolved.updated_at == occurred_at.astimezone(UTC)
    assert evolved.last_state_update_at == occurred_at.astimezone(UTC)
    assert event.category == REGULAR_EVENT_CATEGORY
    assert event.pig_id == pig.pig_id
    assert event.occurred_at == occurred_at.astimezone(UTC)
    assert event.description == "年龄+1，体重+0.53kg，心情-2，健康+1，精力 65"


def test_evolve_pig_days_clamps_drift_to_model_bounds() -> None:
    # Given a pig near the mood and health bounds
    pig = make_pig(mood=97, health=2)
    occurred_at = datetime(2026, 8, 14, 9, 0, tzinfo=DAY_TZ)
    rng = ScriptedRng(uniforms=[0.5, 5.0, -3.0, 50.0])

    # When one day is evolved with extreme drift
    evolved, _ = evolve_pig_days(pig, 1, occurred_at, rng)

    # Then mood and health clamp to the model bounds
    assert evolved.mood == 100
    assert evolved.health == 0


def test_evolve_pig_days_records_one_event_per_trigger() -> None:
    # Given a pig owing three missed days
    pig = make_pig()
    occurred_at = datetime(2026, 8, 14, 9, 0, tzinfo=DAY_TZ)
    rng = ScriptedRng(
        uniforms=[
            0.5,
            5.0,
            3.0,
            10.0,  # day 1
            1.0,
            -5.0,
            -3.0,
            90.0,  # day 2
            0.25,
            0.0,
            0.0,
            42.0,  # day 3
        ]
    )

    # When three days are evolved in one real-time trigger
    evolved, event = evolve_pig_days(pig, 3, occurred_at, rng)

    # Then the net changes apply and exactly one event is recorded
    assert evolved.age_days == pig.age_days + 3
    assert evolved.weight_kg == pytest.approx(6.75)
    assert evolved.mood == 50
    assert evolved.health == 50
    assert evolved.energy == 42
    assert event.description == "年龄+3，体重+1.75kg，心情+0，健康+0，精力 42"
    assert event.occurred_at == occurred_at.astimezone(UTC)


def test_evolve_pig_days_rejects_non_positive_days() -> None:
    # Given a pig and a scripted random source
    pig = make_pig()
    rng = ScriptedRng()

    # When zero days are requested
    # Then the call is rejected
    with pytest.raises(ValueError, match="days must be at least 1"):
        _ = evolve_pig_days(pig, 0, utc_now(), rng)


def test_evolve_document_only_evolves_due_pigs() -> None:
    # Given one owed pig and one fresh pig in the same document
    now = datetime(2026, 8, 14, 9, 0, tzinfo=DAY_TZ)
    owed = make_pig(datetime(2026, 8, 12, 9, 0, tzinfo=DAY_TZ))
    fresh = make_pig(datetime(2026, 8, 14, 8, 0, tzinfo=DAY_TZ))
    document = PigstyDocument(
        scope=PigstyScope.GLOBAL,
        platform_id="qq",
        owner_user_id="owner-a",
        pigs=(owed, fresh),
    )
    rng = ScriptedRng(uniforms=[0.5, 0.0, 0.0, 50.0, 0.5, 0.0, 0.0, 50.0])

    # When the document evolves at the trigger
    evolved = evolve_document(document, now, rng)

    # Then only the owed pig changes and gains exactly one event
    assert evolved.pigs[0].age_days == owed.age_days + 2
    assert evolved.pigs[1] == fresh
    assert len(evolved.events) == 1
    assert evolved.events[0].pig_id == owed.pig_id
    assert evolved.events[0].description.startswith("年龄+2")


def test_evolved_values_always_satisfy_model_bounds() -> None:
    # Given a deterministic seeded random source
    rng = random.Random(11)
    pig = make_pig()

    # When many multi-day evolutions are applied sequentially
    # Then every intermediate pig satisfies the strict model bounds
    occurred_at = utc_now()
    for _ in range(500):
        evolved, _ = evolve_pig_days(pig, 3, occurred_at, rng)
        assert evolved.weight_kg > 0
        assert 0 <= evolved.mood <= 100
        assert 0 <= evolved.health <= 100
        assert 0 <= evolved.energy <= 100
        assert evolved.age_days >= 0
        pig = evolved
    assert pig.age_days == 1500
