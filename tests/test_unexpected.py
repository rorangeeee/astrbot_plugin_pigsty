from __future__ import annotations

import random
from datetime import datetime, timedelta

import pytest
from core.evolution import DAY_TZ
from core.models import Pig
from core.unexpected import (
    StatChange,
    already_rolled_today,
    apply_stat_changes,
    next_chance,
    pick_unexpected_moment,
    roll_stat_changes,
    roll_unexpected_for_pig,
)
from tests.conftest import ScriptedRng

HOUR = timedelta(hours=1)


def make_pig(
    chance: int = 20,
    last_rolled_at: datetime | None = None,
    *,
    mood: int = 50,
    health: int = 50,
    weight_kg: float = 5.0,
) -> Pig:
    """Build a deterministic pig with configured unexpected-event state."""
    return Pig(
        name="测试猪",
        mood=mood,
        health=health,
        weight_kg=weight_kg,
        unexpected_chance_percent=chance,
        unexpected_last_rolled_at=last_rolled_at,
    )


def test_next_chance_resets_on_trigger() -> None:
    # Given any current chance
    # When the dice triggered
    # Then tomorrow's chance resets to the base value
    assert next_chance(20, triggered=True) == 20
    assert next_chance(100, triggered=True) == 20


def test_next_chance_climbs_and_caps() -> None:
    # Given chances across the pity ladder
    # When the dice did not trigger
    # Then the chance climbs by 10 and never exceeds 100
    assert next_chance(20, triggered=False) == 30
    assert next_chance(30, triggered=False) == 40
    assert next_chance(90, triggered=False) == 100
    assert next_chance(100, triggered=False) == 100


def test_already_rolled_today_uses_gmt8_dates() -> None:
    # Given a pig rolled earlier today and one rolled yesterday
    now = datetime(2026, 8, 14, 15, 0, tzinfo=DAY_TZ)
    today = make_pig(last_rolled_at=datetime(2026, 8, 14, 9, 0, tzinfo=DAY_TZ))
    yesterday = make_pig(last_rolled_at=datetime(2026, 8, 13, 18, 0, tzinfo=DAY_TZ))

    # When the same-day guard is checked
    # Then only same-day rolls are skipped
    assert already_rolled_today(today, now) is True
    assert already_rolled_today(yesterday, now) is False


def test_roll_skips_pigs_already_rolled_today() -> None:
    # Given a pig that already rolled today and a scripted random source
    now = datetime(2026, 8, 14, 10, 0, tzinfo=DAY_TZ)
    pig = make_pig(last_rolled_at=datetime(2026, 8, 14, 9, 0, tzinfo=DAY_TZ))
    rng = ScriptedRng()

    # When the dice rolls again the same day
    roll = roll_unexpected_for_pig(pig, now, rng)

    # Then the pig is untouched and nothing triggers
    assert roll.rolled is False
    assert roll.triggered is False
    assert roll.pig == pig
    assert roll.changes == ()


def test_roll_not_triggered_climbs_the_pity_chance() -> None:
    # Given a 20% pig and a scripted draw above the threshold
    now = datetime(2026, 8, 14, 10, 0, tzinfo=DAY_TZ)
    pig = make_pig(chance=20)
    rng = ScriptedRng(randoms=[0.95])

    # When the dice rolls
    roll = roll_unexpected_for_pig(pig, now, rng)

    # Then the chance climbs to 30% and the roll timestamp is persisted
    assert roll.rolled is True
    assert roll.triggered is False
    assert roll.changes == ()
    assert roll.pig.unexpected_chance_percent == 30
    assert roll.pig.unexpected_last_rolled_at == now


def test_roll_triggered_resets_chance_and_samples_changes() -> None:
    # Given a 100% pig and a scripted one-field roll
    now = datetime(2026, 8, 14, 10, 0, tzinfo=DAY_TZ)
    pig = make_pig(chance=100)
    rng = ScriptedRng(
        randoms=[0.5, 0.3],  # trigger draw; field-count draw (one field)
        choices=[2],  # the mood field
        uniforms=[-2.0],  # mood drift
    )

    # When the dice rolls
    roll = roll_unexpected_for_pig(pig, now, rng)

    # Then the event triggers, chance resets, and one mood change is sampled
    assert roll.rolled is True
    assert roll.triggered is True
    assert roll.pig.unexpected_chance_percent == 20
    assert roll.pig.unexpected_last_rolled_at == now
    assert len(roll.changes) == 1
    assert roll.changes[0].key == "mood"
    assert roll.changes[0].value == -2


def test_roll_stat_changes_picks_two_distinct_fields() -> None:
    # Given a scripted draw forcing two fields (weight and energy)
    rng = ScriptedRng(
        randoms=[0.7],  # field-count draw (two fields)
        choices=[0, 3],  # weight element, then the energy element
        uniforms=[0.53, 65.0],  # weight growth; energy reroll
    )

    # When changes are sampled
    changes = roll_stat_changes(rng)

    # Then exactly two distinct fields are returned in canonical order
    assert tuple(change.key for change in changes) == ("weight_kg", "energy")
    assert changes[0].kind == "offset"
    assert changes[0].value == pytest.approx(0.53)
    assert changes[1].kind == "reroll"
    assert changes[1].value == 65


def test_roll_stat_changes_respects_daily_magnitudes() -> None:
    # Given a deterministic seeded random source
    rng = random.Random(3)

    # When many change sets are sampled
    # Then every value follows the daily-rule magnitudes
    for _ in range(2000):
        for change in roll_stat_changes(rng):
            if change.key == "weight_kg":
                assert 0.01 <= change.value <= 1.0
            elif change.key == "mood":
                assert -5 <= change.value <= 5
            elif change.key == "health":
                assert -3 <= change.value <= 3
            else:
                assert 0 <= change.value <= 100


def test_apply_stat_changes_updates_only_targeted_fields() -> None:
    # Given a pig and a mixed offset/reroll change set
    pig = make_pig(mood=50, health=50, weight_kg=5.0)
    occurred_at = datetime(2026, 8, 14, 15, 0, tzinfo=DAY_TZ)
    changes = (
        StatChange(key="weight_kg", kind="offset", value=0.53),
        StatChange(key="mood", kind="offset", value=-5),
        StatChange(key="energy", kind="reroll", value=42),
    )

    # When the changes are applied
    updated = apply_stat_changes(pig, changes, occurred_at)

    # Then only the targeted fields change and the evolution marker is kept
    assert updated.weight_kg == pytest.approx(5.53)
    assert updated.mood == 45
    assert updated.health == 50
    assert updated.energy == 42
    assert updated.age_days == pig.age_days
    assert updated.updated_at == occurred_at
    assert updated.last_state_update_at == pig.last_state_update_at
    assert updated.pig_id == pig.pig_id


def test_apply_stat_changes_clamps_to_model_bounds() -> None:
    # Given a pig near the bounds and extreme offsets
    pig = make_pig(mood=97, health=2)
    occurred_at = datetime(2026, 8, 14, 15, 0, tzinfo=DAY_TZ)
    changes = (
        StatChange(key="mood", kind="offset", value=5),
        StatChange(key="health", kind="offset", value=-3),
    )

    # When the changes are applied
    updated = apply_stat_changes(pig, changes, occurred_at)

    # Then both fields clamp to the model bounds
    assert updated.mood == 100
    assert updated.health == 0


def test_pick_unexpected_moment_stays_in_today_window() -> None:
    # Given a GMT+8 now moment and a seeded random source
    now = datetime(2026, 8, 14, 10, 0, tzinfo=DAY_TZ)
    rng = random.Random(7)

    # When many moments are sampled
    # Then every moment stays within today's 9:00-18:00 GMT+8 window
    window_start = datetime(2026, 8, 14, 9, 0, tzinfo=DAY_TZ)
    window_end = datetime(2026, 8, 14, 18, 0, tzinfo=DAY_TZ)
    for _ in range(500):
        moment = pick_unexpected_moment(now, rng)
        assert window_start <= moment < window_end
        assert moment.astimezone(DAY_TZ).date() == now.astimezone(DAY_TZ).date()
