"""Core Pigsty domain and persistence APIs."""

from .evolution import (
    DAY_TZ,
    DayChanges,
    daily_tick_reached,
    evolve_document,
    evolve_pig_days,
    is_due,
    missed_day_count,
    next_tick_at,
)
from .identity import (
    IdentityError,
    PigstyScope,
    SessionIdentity,
    resolve_session_identity,
)
from .models import (
    CURRENT_SCHEMA_VERSION,
    REGULAR_EVENT_CATEGORY,
    Pig,
    PigEvent,
    PigstyDocument,
    utc_now,
)
from .randomizer import (
    InitialStatsRoll,
    RolledStat,
    RollTier,
    default_random_source,
    roll_initial_stats,
)
from .repository import JsonPigstyRepository, PigstyDataError
from .service import (
    DailyTickSummary,
    DuplicateMemberPigError,
    PigCreation,
    PigstyService,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DAY_TZ",
    "REGULAR_EVENT_CATEGORY",
    "DailyTickSummary",
    "DayChanges",
    "DuplicateMemberPigError",
    "IdentityError",
    "InitialStatsRoll",
    "JsonPigstyRepository",
    "Pig",
    "PigCreation",
    "PigEvent",
    "PigstyDataError",
    "PigstyDocument",
    "PigstyScope",
    "PigstyService",
    "RollTier",
    "RolledStat",
    "SessionIdentity",
    "daily_tick_reached",
    "default_random_source",
    "evolve_document",
    "evolve_pig_days",
    "is_due",
    "missed_day_count",
    "next_tick_at",
    "resolve_session_identity",
    "roll_initial_stats",
    "utc_now",
]
