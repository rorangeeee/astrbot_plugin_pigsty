"""Daily natural evolution for Pigsty pigs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Final

from .models import REGULAR_EVENT_CATEGORY, Pig, PigEvent, PigstyDocument
from .randomizer import WEIGHT_ROUND_DIGITS

if TYPE_CHECKING:
    from .randomizer import RandomSource

DAY_TZ: Final = timezone(timedelta(hours=8))
DAILY_TICK_HOUR: Final = 9
WEIGHT_DAILY_GROWTH_MAX: Final = 1.0
WEIGHT_DAILY_GROWTH_MIN: Final = 0.01
MOOD_DAILY_DRIFT: Final = 5.0
HEALTH_DAILY_DRIFT: Final = 3.0
ENERGY_LOWER_BOUND: Final = 0.0
ENERGY_UPPER_BOUND: Final = 100.0


@dataclass(frozen=True, slots=True)
class DayChanges:
    """Numeric changes applied by one simulated day."""

    growth_kg: float
    mood_delta: int
    health_delta: int
    energy: int  # The new energy value rolled for the day, not a delta.


def next_tick_at(now: datetime) -> datetime:
    """Return the next 9:00 GMT+8 tick moment strictly after ``now``."""
    local = now.astimezone(DAY_TZ)
    today_tick = datetime.combine(local.date(), time(DAILY_TICK_HOUR), tzinfo=DAY_TZ)
    if local >= today_tick:
        today_tick += timedelta(days=1)
    return today_tick


def daily_tick_reached(now: datetime) -> bool:
    """Return whether the 9:00 GMT+8 tick moment has been reached today."""
    local = now.astimezone(DAY_TZ)
    today_tick = datetime.combine(local.date(), time(DAILY_TICK_HOUR), tzinfo=DAY_TZ)
    return local >= today_tick


def missed_day_count(pig: Pig, now: datetime) -> int:
    """Return the number of daily evolutions a pig is owed."""
    last_day = pig.last_state_update_at.astimezone(DAY_TZ).date()
    today = now.astimezone(DAY_TZ).date()
    return max((today - last_day).days, 0)


def is_due(pig: Pig, now: datetime) -> bool:
    """Return whether a pig owes at least one daily evolution."""
    return missed_day_count(pig, now) > 0


def evolve_pig_days(
    pig: Pig,
    days: int,
    occurred_at: datetime,
    rng: RandomSource,
) -> tuple[Pig, PigEvent]:
    """Apply ``days`` daily evolutions and record one real-time regular event."""
    if days < 1:
        message = "days must be at least 1"
        raise ValueError(message)
    if pig.health <= 0:
        return pig, PigEvent(
            category=REGULAR_EVENT_CATEGORY,
            pig_id=pig.pig_id,
            occurred_at=occurred_at,
            description="小猪已死亡，未发生成长",
        )
    evolved = pig
    total_growth = 0.0
    total_mood = 0
    total_health = 0
    for _ in range(days):
        evolved, changes = _evolve_one_day(evolved, rng)
        total_growth += changes.growth_kg
        total_mood += changes.mood_delta
        total_health += changes.health_delta
    evolved = Pig.model_validate(
        evolved.model_dump()
        | {"updated_at": occurred_at, "last_state_update_at": occurred_at}
    )
    event = PigEvent(
        category=REGULAR_EVENT_CATEGORY,
        pig_id=pig.pig_id,
        occurred_at=occurred_at,
        description=(
            f"年龄+{days}，体重+{total_growth:.2f}kg，"
            f"心情{total_mood:+d}，健康{total_health:+d}，精力 {evolved.energy}"
        ),
    )
    return evolved, event


def evolve_document(
    document: PigstyDocument,
    now: datetime,
    rng: RandomSource,
) -> PigstyDocument:
    """Evolve every due pig for this trigger and record one event each."""
    new_pigs: list[Pig] = []
    deceased_ids = {pig.pig_id for pig in document.pigs if pig.health <= 0}
    events = tuple(
        event for event in document.events if event.pig_id not in deceased_ids
    )
    for pig in document.pigs:
        if pig.health <= 0:
            continue
        owed = missed_day_count(pig, now)
        if owed < 1:
            new_pigs.append(pig)
            continue
        evolved, event = evolve_pig_days(pig, owed, now, rng)
        new_pigs.append(evolved)
        events = (*events, event)
    return document.model_copy(update={"pigs": tuple(new_pigs), "events": events})


def _evolve_one_day(pig: Pig, rng: RandomSource) -> tuple[Pig, DayChanges]:
    growth = max(
        round(rng.uniform(0.0, WEIGHT_DAILY_GROWTH_MAX), WEIGHT_ROUND_DIGITS),
        WEIGHT_DAILY_GROWTH_MIN,
    )
    mood_delta = round(rng.uniform(-MOOD_DAILY_DRIFT, MOOD_DAILY_DRIFT))
    sampled_health_delta = round(
        rng.uniform(-HEALTH_DAILY_DRIFT, HEALTH_DAILY_DRIFT)
    )
    energy = round(rng.uniform(ENERGY_LOWER_BOUND, ENERGY_UPPER_BOUND))
    health = (
        0
        if pig.health <= 0
        else max(min(pig.health + sampled_health_delta, 100), 1)
    )
    evolved = Pig.model_validate(
        pig.model_dump()
        | {
            "age_days": pig.age_days + 1,
            "weight_kg": pig.weight_kg + growth,
            "mood": max(min(pig.mood + mood_delta, 100), 0),
            "health": health,
            "energy": energy,
        }
    )
    return evolved, DayChanges(
        growth_kg=growth,
        mood_delta=mood_delta,
        health_delta=health - pig.health,
        energy=energy,
    )
