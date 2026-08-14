"""Core Pigsty domain and persistence APIs."""

from .identity import (
    IdentityError,
    PigstyScope,
    SessionIdentity,
    resolve_session_identity,
)
from .models import CURRENT_SCHEMA_VERSION, Pig, PigstyDocument, utc_now
from .randomizer import (
    InitialStatsRoll,
    RolledStat,
    RollTier,
    roll_initial_stats,
)
from .repository import JsonPigstyRepository, PigstyDataError
from .service import DuplicateMemberPigError, PigCreation, PigstyService

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DuplicateMemberPigError",
    "IdentityError",
    "InitialStatsRoll",
    "JsonPigstyRepository",
    "Pig",
    "PigCreation",
    "PigstyDataError",
    "PigstyDocument",
    "PigstyScope",
    "PigstyService",
    "RollTier",
    "RolledStat",
    "SessionIdentity",
    "resolve_session_identity",
    "roll_initial_stats",
    "utc_now",
]
