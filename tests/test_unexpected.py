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
    energy: int = 80,
) -> Pig:
    """Build a deterministic pig with configured unexpected-event state."""
    return Pig(
        name="测试猪",
        mood=mood,
        health=health,
        weight_kg=weight_kg,
        energy=energy,
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
    # Given a 100% pig and a scripted normal-tier mood roll
    now = datetime(2026, 8, 14, 10, 0, tzinfo=DAY_TZ)
    pig = make_pig(chance=100, mood=50)
    rng = ScriptedRng(
        randoms=[0.5, 0.3, 0.3],  # trigger; one field; normal tier
        choices=[2],  # the mood field
        uniforms=[0.95],  # mood factor -> 47.5 -> rounds to 48
    )

    # When the dice rolls
    roll = roll_unexpected_for_pig(pig, now, rng)

    # Then the event triggers, chance resets, and the mood delta is recorded
    assert roll.rolled is True
    assert roll.triggered is True
    assert roll.pig.unexpected_chance_percent == 20
    assert roll.pig.unexpected_last_rolled_at == now
    assert len(roll.changes) == 1
    assert roll.changes[0].key == "mood"
    assert roll.changes[0].delta == -2


def test_roll_stat_changes_picks_two_distinct_fields() -> None:
    # Given a scripted two-field roll: weight (normal) and energy (major)
    pig = make_pig(weight_kg=5.0, energy=80)
    rng = ScriptedRng(
        randoms=[0.7, 0.3, 0.9],  # two fields; weight tier; energy tier
        choices=[0, 3, 1],  # weight field; energy field; positive sign
        uniforms=[0.95, 0.20],  # weight factor; energy magnitude factor
    )

    # When changes are sampled
    changes = roll_stat_changes(pig, rng)

    # Then exactly two distinct fields return their signed deltas
    assert tuple(change.key for change in changes) == ("weight_kg", "energy")
    assert changes[0].delta == pytest.approx(-0.25)
    assert changes[1].delta == 16


def test_normal_tier_stays_within_five_percent_of_current() -> None:
    # Given a pig and scripted normal-tier weight rolls at both bounds
    pig = make_pig(weight_kg=5.0)
    lower = ScriptedRng(
        randoms=[0.3, 0.0],  # one field; normal tier
        choices=[0],  # the weight field
        uniforms=[0.95],
    )
    upper = ScriptedRng(
        randoms=[0.3, 0.0],
        choices=[0],
        uniforms=[1.05],
    )

    # When the deltas are sampled
    # Then they stay within ±5% of the current weight
    assert roll_stat_changes(pig, lower)[0].delta == pytest.approx(-0.25)
    assert roll_stat_changes(pig, upper)[0].delta == pytest.approx(0.25)


def test_minor_tier_offsets_land_between_five_and_twenty_percent() -> None:
    # Given a pig and scripted minor-tier mood rolls at both bounds and signs
    pig = make_pig(mood=50)
    lower = ScriptedRng(
        randoms=[0.3, 0.8],  # one field; minor tier
        choices=[2, -1],  # the mood field; negative sign
        uniforms=[0.05],
    )
    upper = ScriptedRng(
        randoms=[0.3, 0.8],
        choices=[2, 1],
        uniforms=[0.20],
    )

    # When the deltas are sampled
    # Then they land between 5% and 20% of the current mood
    assert roll_stat_changes(pig, lower)[0].delta == -2
    assert roll_stat_changes(pig, upper)[0].delta == 10


def test_major_tier_offsets_land_between_twenty_and_fifty_percent() -> None:
    # Given a pig and scripted major-tier mood rolls at both bounds
    pig = make_pig(mood=50)
    lower = ScriptedRng(
        randoms=[0.3, 0.95],  # one field; major tier
        choices=[2, 1],
        uniforms=[0.20],
    )
    upper = ScriptedRng(
        randoms=[0.3, 0.95],
        choices=[2, 1],
        uniforms=[0.50],
    )

    # When the deltas are sampled
    # Then they land between 20% and 50% of the current mood
    assert roll_stat_changes(pig, lower)[0].delta == 10
    assert roll_stat_changes(pig, upper)[0].delta == 25


def test_extreme_bounded_tier_respects_global_bounds() -> None:
    # Given a pig and scripted extreme-tier health rolls on both sides
    pig = make_pig(health=50)
    lower = ScriptedRng(
        randoms=[0.3, 0.99],  # one field; extreme tier
        choices=[1],  # the health field
        uniforms=[25.0, 12.0],  # lower span pick; value 12
    )
    upper = ScriptedRng(
        randoms=[0.3, 0.99],
        choices=[1],
        uniforms=[40.0, 90.0],  # upper span pick; value 90
    )

    # When the deltas are sampled
    # Then both stay at least 50% away from the current health
    assert roll_stat_changes(pig, lower)[0].delta == -38
    assert roll_stat_changes(pig, upper)[0].delta == 40


def test_extreme_weight_has_no_upper_limit() -> None:
    # Given a pig and a scripted positive-side extreme weight roll
    pig = make_pig(weight_kg=5.0)
    rng = ScriptedRng(
        randoms=[0.3, 0.99],  # one field; extreme tier
        choices=[0, 1],  # the weight field; positive sign
        expovariates=[1000.0],
    )

    # When the delta is sampled
    # Then the unbounded weight follows the full exponential tail
    assert roll_stat_changes(pig, rng)[0].delta == pytest.approx(5002.5)


def test_apply_stat_changes_updates_only_targeted_fields() -> None:
    # Given a pig and a mixed delta set
    pig = make_pig(mood=50, health=50, weight_kg=5.0, energy=80)
    occurred_at = datetime(2026, 8, 14, 15, 0, tzinfo=DAY_TZ)
    changes = (
        StatChange(key="weight_kg", delta=0.53),
        StatChange(key="mood", delta=-5),
        StatChange(key="energy", delta=-38),
    )

    # When the changes are applied
    updated = apply_stat_changes(pig, changes, occurred_at)

    # Then only the targeted fields change and the evolution marker is kept
    assert updated.weight_kg == pytest.approx(5.53)
    assert updated.mood == 45
    assert updated.health == 50
    assert updated.energy == 42
    assert updated.age_days == pig.age_days


def test_apply_stat_changes_can_keep_scheduled_health_above_zero() -> None:
    # Given a pig whose scheduled event would otherwise reduce health to zero
    pig = make_pig(health=2)
    occurred_at = datetime(2026, 8, 14, 15, 0, tzinfo=DAY_TZ)

    # When the event applies a severe negative health delta
    updated = apply_stat_changes(
        pig,
        (StatChange(key="health", delta=-20),),
        occurred_at,
        health_floor=1,
    )

    # Then the scheduled-event floor keeps the pig alive
    assert updated.health == 1
    assert updated.updated_at == occurred_at
    assert updated.last_state_update_at == pig.last_state_update_at
    assert updated.pig_id == pig.pig_id


def test_apply_stat_changes_clamps_to_model_bounds() -> None:
    # Given a pig near the bounds and extreme deltas
    pig = make_pig(mood=97, health=2)
    occurred_at = datetime(2026, 8, 14, 15, 0, tzinfo=DAY_TZ)
    changes = (
        StatChange(key="mood", delta=5),
        StatChange(key="health", delta=-3),
    )

    # When the changes are applied
    updated = apply_stat_changes(pig, changes, occurred_at)

    # Then both fields clamp to the model bounds
    assert updated.mood == 100
    assert updated.health == 0


def test_repeated_sampled_changes_stay_within_model_bounds() -> None:
    # Given a pig and a deterministic seeded random source
    rng = random.Random(9)
    pig = make_pig()
    occurred_at = datetime(2026, 8, 14, 15, 0, tzinfo=DAY_TZ)

    # When many sampled change sets are applied sequentially
    # Then every intermediate pig satisfies the strict model bounds
    current = pig
    for _ in range(2000):
        changes = roll_stat_changes(current, rng)
        current = apply_stat_changes(current, changes, occurred_at)
        assert current.weight_kg > 0
        assert 0 <= current.mood <= 100
        assert 0 <= current.health <= 100
        assert 0 <= current.energy <= 100


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
