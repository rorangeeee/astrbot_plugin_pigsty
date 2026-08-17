"""Daily unexpected events for Pigsty pigs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING, Final

from .evolution import DAY_TZ
from .models import Pig
from .randomizer import (
    BOUNDED_UPPER_BOUND,
    WEIGHT_LOWER_BOUND,
    WEIGHT_ROUND_DIGITS,
    StatSpec,
    roll_stat,
)

if TYPE_CHECKING:
    from .randomizer import RandomSource

UNEXPECTED_BASE_CHANCE: Final = 20
UNEXPECTED_CHANCE_STEP: Final = 10
UNEXPECTED_CHANCE_MAX: Final = 100
UNEXPECTED_WINDOW_START_HOUR: Final = 9
UNEXPECTED_WINDOW_END_HOUR: Final = 18
UNEXPECTED_SECOND_FIELD_CHANCE: Final = 0.5
UNEXPECTED_TWO_FIELDS: Final = 2

_STAT_FIELDS: Final = ("weight_kg", "health", "mood", "energy")


@dataclass(frozen=True, slots=True)
class StatChange:
    """One signed stat delta sampled for an unexpected event."""

    key: str
    delta: float | int


@dataclass(frozen=True, slots=True)
class UnexpectedRoll:
    """Outcome of one pig's daily unexpected-event dice roll."""

    pig: Pig  # The pig after the chance and last-rolled fields were updated.
    rolled: bool  # False when the pig already rolled today and was left untouched.
    triggered: bool
    changes: tuple[StatChange, ...]


def next_chance(chance: int, triggered: bool) -> int:
    """Return tomorrow's chance after one daily roll."""
    if triggered:
        return UNEXPECTED_BASE_CHANCE
    return min(chance + UNEXPECTED_CHANCE_STEP, UNEXPECTED_CHANCE_MAX)


def already_rolled_today(pig: Pig, now: datetime) -> bool:
    """Return whether the pig already rolled for the GMT+8 day of ``now``."""
    last_rolled = pig.unexpected_last_rolled_at
    if last_rolled is None:
        return False
    return last_rolled.astimezone(DAY_TZ).date() == now.astimezone(DAY_TZ).date()


def roll_unexpected_for_pig(
    pig: Pig,
    now: datetime,
    rng: RandomSource,
) -> UnexpectedRoll:
    """Roll one pig's daily unexpected-event dice and persist its pity state."""
    if already_rolled_today(pig, now):
        return UnexpectedRoll(pig=pig, rolled=False, triggered=False, changes=())
    triggered = rng.random() < pig.unexpected_chance_percent / 100
    chance_after = next_chance(pig.unexpected_chance_percent, triggered)
    changes = roll_stat_changes(pig, rng) if triggered else ()
    updated = Pig.model_validate(
        pig.model_dump()
        | {
            "unexpected_chance_percent": chance_after,
            "unexpected_last_rolled_at": now,
        }
    )
    return UnexpectedRoll(
        pig=updated,
        rolled=True,
        triggered=triggered,
        changes=changes,
    )


def roll_stat_changes(pig: Pig, rng: RandomSource) -> tuple[StatChange, ...]:
    """Sample one or two distinct stat deltas through the offset tiers."""
    count = (
        1 if rng.random() < UNEXPECTED_SECOND_FIELD_CHANCE else UNEXPECTED_TWO_FIELDS
    )
    first_index = rng.choice(range(len(_STAT_FIELDS)))
    chosen = [first_index]
    if count == UNEXPECTED_TWO_FIELDS:
        remaining = [
            index for index in range(len(_STAT_FIELDS)) if index != first_index
        ]
        chosen.append(rng.choice(remaining))
    return tuple(_change_for(pig, _STAT_FIELDS[index], rng) for index in sorted(chosen))


def _change_for(pig: Pig, key: str, rng: RandomSource) -> StatChange:
    rolled = roll_stat(_spec_for(pig, key), rng)
    return StatChange(key=key, delta=rolled.value - _current_value(pig, key))


def _spec_for(pig: Pig, key: str) -> StatSpec:
    match key:
        case "weight_kg":
            return StatSpec(
                key="weight_kg",
                base=pig.weight_kg,
                integer=False,
                upper_bound=None,
                lower_bound=WEIGHT_LOWER_BOUND,
                round_digits=WEIGHT_ROUND_DIGITS,
            )
        case "health":
            return StatSpec(
                key="health",
                base=float(pig.health),
                integer=True,
                upper_bound=BOUNDED_UPPER_BOUND,
            )
        case "mood":
            return StatSpec(
                key="mood",
                base=float(pig.mood),
                integer=True,
                upper_bound=BOUNDED_UPPER_BOUND,
            )
        case "energy":
            return StatSpec(
                key="energy",
                base=float(pig.energy),
                integer=True,
                upper_bound=BOUNDED_UPPER_BOUND,
            )
        case _:
            message = f"unknown stat field {key!r}"
            raise ValueError(message)


def _current_value(pig: Pig, key: str) -> float | int:
    match key:
        case "weight_kg":
            return pig.weight_kg
        case "health":
            return pig.health
        case "mood":
            return pig.mood
        case "energy":
            return pig.energy
        case _:
            message = f"unknown stat field {key!r}"
            raise ValueError(message)


def apply_stat_changes(
    pig: Pig,
    changes: tuple[StatChange, ...],
    occurred_at: datetime,
) -> Pig:
    """Apply unexpected stat deltas without touching the evolution marker."""
    updates: dict[str, float | int | datetime] = {}
    for change in changes:
        match change.key:
            case "weight_kg":
                updates["weight_kg"] = max(
                    round(pig.weight_kg + change.delta, WEIGHT_ROUND_DIGITS),
                    WEIGHT_LOWER_BOUND,
                )
            case "mood":
                updates["mood"] = _clamp_int(pig.mood + change.delta)
            case "health":
                updates["health"] = _clamp_int(pig.health + change.delta)
            case "energy":
                updates["energy"] = _clamp_int(pig.energy + change.delta)
            case _:
                message = f"unknown stat field {change.key!r}"
                raise ValueError(message)
    updates["updated_at"] = occurred_at
    return Pig.model_validate(pig.model_dump() | updates)


def pick_unexpected_moment(now: datetime, rng: RandomSource) -> datetime:
    """Pick a random GMT+8 moment within today's 9:00-18:00 window."""
    local = now.astimezone(DAY_TZ)
    window_start = datetime.combine(
        local.date(),
        time(UNEXPECTED_WINDOW_START_HOUR),
        tzinfo=DAY_TZ,
    )
    span_seconds = (UNEXPECTED_WINDOW_END_HOUR - UNEXPECTED_WINDOW_START_HOUR) * 3600
    return window_start + timedelta(seconds=rng.uniform(0.0, span_seconds))


def _clamp_int(value: float) -> int:
    return max(min(round(value), 100), 0)
