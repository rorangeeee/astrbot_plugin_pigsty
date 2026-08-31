from __future__ import annotations

import random

import pytest
from core.randomizer import (
    InitialStatsRoll,
    RolledStat,
    RollTier,
    roll_initial_stats,
)
from tests.conftest import ScriptedRng


@pytest.mark.parametrize(
    ("draw", "expected"),
    [
        (0.0, RollTier.NORMAL),
        (0.7499, RollTier.NORMAL),
        (0.75, RollTier.MINOR),
        (0.8999, RollTier.MINOR),
        (0.90, RollTier.MAJOR),
        (0.9799, RollTier.MAJOR),
        (0.98, RollTier.EXTREME),
        (0.9999, RollTier.EXTREME),
    ],
)
def test_tier_thresholds_match_probability_table(
    draw: float, expected: RollTier
) -> None:
    # Given a scripted random source drawing one tier for every stat
    rng = ScriptedRng(
        randoms=[draw, draw, draw, draw],
        uniforms=[1.0] * 12,
        choices=[1] * 4,
        expovariates=[0.0] * 4,
    )

    # When all four stats are rolled
    roll = roll_initial_stats(rng)

    # Then every stat lands in the tier selected by the cumulative table
    assert {stat.tier for stat in roll.stats} == {expected}


def test_normal_tier_stays_within_five_percent_of_base() -> None:
    # Given a scripted roll pinning every stat to the normal tier
    rng = ScriptedRng(
        randoms=[0.5, 0.5, 0.5, 0.5],
        uniforms=[0.95, 1.05, 1.0, 0.97],
    )

    # When the stats are rolled at the tier boundaries
    roll = roll_initial_stats(rng)
    values = roll.values()

    # Then offsets never leave ±5% and model bounds are respected
    assert values["weight_kg"] == pytest.approx(4.75)
    assert values["health"] == 100  # 105 clamped to the model maximum
    assert values["mood"] == 70
    assert values["energy"] == 78
    assert {stat.tier for stat in roll.stats} == {RollTier.NORMAL}
    assert isinstance(values["weight_kg"], float)
    assert isinstance(values["health"], int)
    assert isinstance(values["mood"], int)
    assert isinstance(values["energy"], int)


def test_minor_tier_offsets_land_between_five_and_twenty_percent() -> None:
    # Given a scripted roll pinning every stat to the minor tier
    rng = ScriptedRng(
        randoms=[0.8, 0.8, 0.8, 0.8],
        uniforms=[0.05, 0.20, 0.05, 0.20],
        choices=[-1, 1, -1, 1],
    )

    # When the stats are rolled at both magnitude bounds and both signs
    roll = roll_initial_stats(rng)
    values = roll.values()

    # Then offsets stay inside 5%-20% and follow the scripted signs
    assert values["weight_kg"] == pytest.approx(4.75)
    assert values["health"] == 100  # 120 clamped to the model maximum
    assert values["mood"] == 66
    assert values["energy"] == 96
    assert {stat.tier for stat in roll.stats} == {RollTier.MINOR}


def test_major_tier_offsets_land_between_twenty_and_fifty_percent() -> None:
    # Given a scripted roll pinning every stat to the major tier
    rng = ScriptedRng(
        randoms=[0.95, 0.95, 0.95, 0.95],
        uniforms=[0.20, 0.50, 0.20, 0.50],
        choices=[1, -1, 1, -1],
    )

    # When the stats are rolled at both magnitude bounds and both signs
    roll = roll_initial_stats(rng)
    values = roll.values()

    # Then offsets stay inside 20%-50% and follow the scripted signs
    assert values["weight_kg"] == pytest.approx(6.0)
    assert values["health"] == 50
    assert values["mood"] == 84
    assert values["energy"] == 40
    assert {stat.tier for stat in roll.stats} == {RollTier.MAJOR}


def test_extreme_bounded_tier_respects_model_bounds() -> None:
    # Given a scripted roll pinning every stat to the extreme tier
    rng = ScriptedRng(
        randoms=[0.99, 0.99, 0.99, 0.99],
        choices=[-1],
        uniforms=[0.01, 25.0, 12.0, 0.0, 35.0, 0.0, 40.0],
    )

    # When the stats are rolled
    roll = roll_initial_stats(rng)
    values = roll.values()

    # Then every value sits at least 50% away from its base within model bounds
    assert values["weight_kg"] == pytest.approx(0.01)
    assert values["health"] == 12
    assert values["mood"] == 35
    assert values["energy"] == 40
    assert {stat.tier for stat in roll.stats} == {RollTier.EXTREME}


def test_extreme_weight_has_no_upper_limit() -> None:
    # Given a scripted positive-side extreme weight roll with a huge tail draw
    rng = ScriptedRng(
        randoms=[0.99, 0.99, 0.99, 0.99],
        choices=[1],
        uniforms=[0.0, 50.0, 0.0, 35.0, 0.0, 40.0],
        expovariates=[1000.0],
    )

    # When the stats are rolled
    roll = roll_initial_stats(rng)

    # Then the unbounded weight follows the full exponential tail draw
    assert roll.values()["weight_kg"] == pytest.approx(5007.5)


def test_anomalies_only_collect_non_normal_stats() -> None:
    # Given a mixed roll with normal and out-of-tier stats
    roll = InitialStatsRoll(
        stats=(
            RolledStat("weight_kg", 5.0, RollTier.NORMAL),
            RolledStat("health", 100, RollTier.NORMAL),
            RolledStat("mood", 45, RollTier.MAJOR),
            RolledStat("energy", 35, RollTier.EXTREME),
        )
    )

    # When anomalies and values are collected
    # Then only the out-of-tier stats are reported
    assert tuple(stat.key for stat in roll.anomalies) == ("mood", "energy")
    assert roll.values() == {
        "weight_kg": 5.0,
        "health": 100,
        "mood": 45,
        "energy": 35,
    }


def test_seeded_rolls_are_reproducible() -> None:
    # Given two identically seeded random sources
    # When the same stats are rolled twice
    first = roll_initial_stats(random.Random(2024))
    second = roll_initial_stats(random.Random(2024))

    # Then both rolls are identical
    assert first == second


def test_tier_distribution_matches_probability_table() -> None:
    # Given a deterministic seeded random source
    rng = random.Random(0)
    counts = dict.fromkeys(RollTier, 0)

    # When 20000 newborn pigs are rolled
    for _ in range(20000):
        for stat in roll_initial_stats(rng).stats:
            counts[stat.tier] += 1
    total = sum(counts.values())

    # Then the observed tier shares match the configured probabilities
    assert counts[RollTier.NORMAL] / total == pytest.approx(0.75, abs=0.02)
    assert counts[RollTier.MINOR] / total == pytest.approx(0.15, abs=0.02)
    assert counts[RollTier.MAJOR] / total == pytest.approx(0.08, abs=0.02)
    assert counts[RollTier.EXTREME] / total == pytest.approx(0.02, abs=0.01)


def test_rolled_values_always_satisfy_model_bounds() -> None:
    # Given a deterministic seeded random source
    rng = random.Random(7)

    # When 2000 newborn pigs are rolled
    # Then every value satisfies the strict Pig model constraints
    for _ in range(2000):
        values = roll_initial_stats(rng).values()
        assert isinstance(values["weight_kg"], float)
        assert values["weight_kg"] > 0
        assert isinstance(values["health"], int)
        assert isinstance(values["mood"], int)
        assert isinstance(values["energy"], int)
        assert 1 <= values["health"] <= 100
        assert 0 <= values["mood"] <= 100
        assert 0 <= values["energy"] <= 100
