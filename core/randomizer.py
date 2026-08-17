"""Randomized initial stat rolls for newborn Pigsty pigs."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Final, Protocol, assert_never

if TYPE_CHECKING:
    from collections.abc import Sequence

NORMAL_TIER_PROBABILITY: Final = 0.75
MINOR_TIER_PROBABILITY: Final = 0.15
MAJOR_TIER_PROBABILITY: Final = 0.08
EXTREME_TIER_PROBABILITY: Final = 0.02

NORMAL_FACTOR_LOW: Final = 0.95
NORMAL_FACTOR_HIGH: Final = 1.05
MINOR_MAGNITUDE_LOW: Final = 0.05
MINOR_MAGNITUDE_HIGH: Final = 0.20
MAJOR_MAGNITUDE_LOW: Final = 0.20
MAJOR_MAGNITUDE_HIGH: Final = 0.50
EXTREME_HALF_FACTOR: Final = 0.5
EXTREME_LOWER_FACTOR: Final = 1.5
EXTREME_TAIL_LAMBDA: Final = 0.5

BOUNDED_UPPER_BOUND: Final = 100.0
WEIGHT_LOWER_BOUND: Final = 0.01
WEIGHT_ROUND_DIGITS: Final = 2


@unique
class RollTier(StrEnum):
    """One of the four independent offset tiers a stat can roll into."""

    NORMAL = "normal"
    MINOR = "minor"
    MAJOR = "major"
    EXTREME = "extreme"


class RandomSource(Protocol):
    """Minimal random source consumed by stat rolls."""

    def random(self) -> float:
        """Return the next uniform draw in [0.0, 1.0)."""

    def uniform(self, a: float, b: float) -> float:
        """Return the next uniform draw in [a, b]."""

    def choice(self, seq: Sequence[int]) -> int:
        """Return one element picked from the sequence."""

    def expovariate(self, lambd: float) -> float:
        """Return the next exponential draw with the given rate."""


@dataclass(frozen=True, slots=True)
class StatSpec:
    """Roll configuration for one Pig numeric field."""

    key: str
    base: float
    integer: bool
    upper_bound: float | None
    lower_bound: float = 0.0
    round_digits: int = 0


WEIGHT_SPEC: Final = StatSpec(
    key="weight_kg",
    base=5.0,
    integer=False,
    upper_bound=None,
    lower_bound=WEIGHT_LOWER_BOUND,
    round_digits=WEIGHT_ROUND_DIGITS,
)
HEALTH_SPEC: Final = StatSpec(
    key="health",
    base=100.0,
    integer=True,
    upper_bound=BOUNDED_UPPER_BOUND,
)
MOOD_SPEC: Final = StatSpec(
    key="mood",
    base=70.0,
    integer=True,
    upper_bound=BOUNDED_UPPER_BOUND,
)
ENERGY_SPEC: Final = StatSpec(
    key="energy",
    base=80.0,
    integer=True,
    upper_bound=BOUNDED_UPPER_BOUND,
)
STAT_SPECS: Final = (WEIGHT_SPEC, HEALTH_SPEC, MOOD_SPEC, ENERGY_SPEC)


@dataclass(frozen=True, slots=True)
class RolledStat:
    """One rolled numeric value and the tier that produced it."""

    key: str
    value: int | float
    tier: RollTier


@dataclass(frozen=True, slots=True)
class InitialStatsRoll:
    """Rolled initial stats for one newborn pig."""

    stats: tuple[RolledStat, ...]

    @property
    def anomalies(self) -> tuple[RolledStat, ...]:
        """Return stats that left the normal 75% tier."""
        return tuple(stat for stat in self.stats if stat.tier is not RollTier.NORMAL)

    def values(self) -> dict[str, int | float]:
        """Return rolled values keyed by Pig field name."""
        return {stat.key: stat.value for stat in self.stats}


def default_random_source() -> random.Random:
    """Return a fresh system-seeded random source."""
    return random.Random()


def roll_initial_stats(rng: RandomSource | None = None) -> InitialStatsRoll:
    """Roll every newborn stat independently through the offset tiers."""
    source = rng if rng is not None else default_random_source()
    return InitialStatsRoll(tuple(roll_stat(spec, source) for spec in STAT_SPECS))


def roll_stat(spec: StatSpec, rng: RandomSource) -> RolledStat:
    """Roll one stat value through the offset tiers."""
    tier = _pick_tier(rng)
    raw_value = _roll_value(spec, tier, rng)
    return RolledStat(key=spec.key, value=_finalize(spec, raw_value), tier=tier)


def _pick_tier(rng: RandomSource) -> RollTier:
    roll = rng.random()
    if roll < NORMAL_TIER_PROBABILITY:
        return RollTier.NORMAL
    if roll < NORMAL_TIER_PROBABILITY + MINOR_TIER_PROBABILITY:
        return RollTier.MINOR
    if roll < NORMAL_TIER_PROBABILITY + MINOR_TIER_PROBABILITY + MAJOR_TIER_PROBABILITY:
        return RollTier.MAJOR
    return RollTier.EXTREME


def _roll_value(spec: StatSpec, tier: RollTier, rng: RandomSource) -> float:
    match tier:
        case RollTier.NORMAL:
            return spec.base * rng.uniform(NORMAL_FACTOR_LOW, NORMAL_FACTOR_HIGH)
        case RollTier.MINOR:
            magnitude = spec.base * rng.uniform(
                MINOR_MAGNITUDE_LOW, MINOR_MAGNITUDE_HIGH
            )
            return spec.base + _sign(rng) * magnitude
        case RollTier.MAJOR:
            magnitude = spec.base * rng.uniform(
                MAJOR_MAGNITUDE_LOW, MAJOR_MAGNITUDE_HIGH
            )
            return spec.base + _sign(rng) * magnitude
        case RollTier.EXTREME:
            return _roll_extreme(spec, rng)
    assert_never(tier)


def _sign(rng: RandomSource) -> float:
    """Return a uniformly random +1 or -1 offset factor."""
    return 1.0 if rng.choice((-1, 1)) > 0 else -1.0


def _roll_extreme(spec: StatSpec, rng: RandomSource) -> float:
    if spec.upper_bound is None:
        return _roll_extreme_unbounded(spec, rng)
    return _roll_extreme_bounded(spec, rng, spec.upper_bound)


def _roll_extreme_bounded(
    spec: StatSpec,
    rng: RandomSource,
    upper_bound: float,
) -> float:
    spans: list[tuple[float, float]] = []
    lower_span = (spec.lower_bound, min(spec.base * EXTREME_HALF_FACTOR, upper_bound))
    upper_span = (max(spec.base * EXTREME_LOWER_FACTOR, spec.lower_bound), upper_bound)
    if lower_span[1] >= lower_span[0]:
        spans.append(lower_span)
    if upper_span[1] >= upper_span[0]:
        spans.append(upper_span)
    start, end = _pick_weighted_span(spans, rng)
    return rng.uniform(start, end)


def _pick_weighted_span(
    spans: list[tuple[float, float]],
    rng: RandomSource,
) -> tuple[float, float]:
    total = sum(end - start for start, end in spans)
    cursor = rng.uniform(0.0, total)
    for start, end in spans:
        cursor -= end - start
        if cursor <= 0.0:
            return start, end
    return spans[-1]


def _roll_extreme_unbounded(spec: StatSpec, rng: RandomSource) -> float:
    if rng.choice((-1, 1)) < 0:
        return rng.uniform(spec.lower_bound, spec.base * EXTREME_HALF_FACTOR)
    return spec.base * (EXTREME_LOWER_FACTOR + rng.expovariate(EXTREME_TAIL_LAMBDA))


def _finalize(spec: StatSpec, value: float) -> int | float:
    if spec.integer:
        rounded = round(value)
        lower = int(spec.lower_bound)
        if spec.upper_bound is None:
            return max(rounded, lower)
        return max(min(rounded, int(spec.upper_bound)), lower)
    bounded = max(round(value, spec.round_digits), spec.lower_bound)
    if spec.upper_bound is not None:
        bounded = min(bounded, spec.upper_bound)
    return bounded
