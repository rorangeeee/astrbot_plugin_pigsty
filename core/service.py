"""Pure core services for creating and listing Pigsty pigs."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from typing_extensions import override

from .evolution import evolve_document, is_due
from .models import (
    UNEXPECTED_EVENT_CATEGORY,
    USER_EVENT_CATEGORY,
    Pig,
    PigEvent,
    PigstyDocument,
    utc_now,
)
from .randomizer import (
    InitialStatsRoll,
    RandomSource,
    default_random_source,
    roll_initial_stats,
)
from .repository import PigstyDataError
from .unexpected import (
    StatChange,
    apply_stat_changes,
    roll_unexpected_for_pig,
)

PIG_ID_PREFIX_MIN_LENGTH = 8

if TYPE_CHECKING:
    from datetime import datetime

    from .identity import SessionIdentity
    from .interaction import UserPigInteraction
    from .repository import JsonPigstyRepository


@dataclass(frozen=True, slots=True)
class DuplicateMemberPigError(Exception):
    """Raised when an owner already has a pig for a member pair."""

    platform_id: str
    user_id: str

    @override
    def __str__(self) -> str:
        return f"member {self.platform_id}:{self.user_id} already has a pig"


@dataclass(frozen=True, slots=True)
class PigPositionNotFoundError(Exception):
    """Raised when a 1-based pig display position does not exist."""

    position: int

    @override
    def __str__(self) -> str:
        return f"pig position {self.position} does not exist"


@dataclass(frozen=True, slots=True)
class PigTargetNotFoundError(Exception):
    """Raised when a letgo selector does not identify a persisted pig."""

    selector: str

    @override
    def __str__(self) -> str:
        return f"pig target {self.selector!r} does not exist"


@dataclass(frozen=True, slots=True)
class PigTargetAmbiguousError(Exception):
    """Raised when a nickname or id prefix matches multiple pigs."""

    selector: str
    matches: int

    @override
    def __str__(self) -> str:
        return f"pig target {self.selector!r} matches {self.matches} pigs"


@dataclass(frozen=True, slots=True)
class LetgoResult:
    """Snapshot returned after one pig and its event history are removed."""

    pig: Pig
    events: tuple[PigEvent, ...]


@dataclass(frozen=True, slots=True)
class PigCreation:
    """One persisted newborn pig together with its initial stat roll."""

    pig: Pig
    roll: InitialStatsRoll


@dataclass(frozen=True, slots=True)
class DailyTickSummary:
    """Outcome of one real-time daily evolution trigger."""

    ticked_at: datetime
    evolved_pigs: int
    recorded_events: int
    scanned_documents: int
    skipped_documents: int
    failed_documents: int


def _evolve_document_mutation(
    document: PigstyDocument,
    now: datetime,
    rng: RandomSource,
    stats: list[int],
) -> PigstyDocument:
    """Apply one evolution pass and report pig and event counts."""
    evolved = evolve_document(document, now, rng)
    stats[0] += sum(1 for pig in document.pigs if is_due(pig, now))
    stats[1] += len(evolved.events) - len(document.events)
    return evolved


@dataclass(frozen=True, slots=True)
class UnexpectedOutcome:
    """One triggered unexpected-event draft waiting for a description."""

    identity: SessionIdentity
    pig: Pig
    changes: tuple[StatChange, ...]


@dataclass(frozen=True, slots=True)
class UnexpectedPigNotFoundError(Exception):
    """Raised when an unexpected event targets a pig that no longer exists."""

    pig_id: UUID

    @override
    def __str__(self) -> str:
        return f"unexpected event target {self.pig_id} does not exist"


@dataclass(frozen=True, slots=True)
class UserInteractionPigNotFoundError(Exception):
    """Raised when a user interaction targets an absent display position."""

    position: int

    @override
    def __str__(self) -> str:
        return f"user interaction target position {self.position} does not exist"


@dataclass(frozen=True, slots=True)
class DuplicateUserInteractionPositionError(Exception):
    """Raised when one user interaction repeats a pig display position."""

    position: int

    @override
    def __str__(self) -> str:
        return f"user interaction repeats pig position {self.position}"


def _roll_unexpected_mutation(
    document: PigstyDocument,
    now: datetime,
    rng: RandomSource,
    outcomes: list[UnexpectedOutcome],
) -> PigstyDocument:
    """Roll every due pig's unexpected dice and collect triggered drafts."""
    new_pigs: list[Pig] = []
    for pig in document.pigs:
        roll = roll_unexpected_for_pig(pig, now, rng)
        new_pigs.append(roll.pig)
        if roll.triggered:
            outcomes.append(
                UnexpectedOutcome(
                    identity=document.to_identity(),
                    pig=roll.pig,
                    changes=roll.changes,
                )
            )
    return document.model_copy(update={"pigs": tuple(new_pigs)})


class PigstyService:
    """Create and read pigs within the repository-owned identity scope."""

    def __init__(self, repository: JsonPigstyRepository) -> None:
        """Create a service backed by the supplied repository."""
        self._repository: JsonPigstyRepository = repository

    async def add_random(
        self,
        identity: SessionIdentity,
        name: str | None = None,
        rng: RandomSource | None = None,
    ) -> PigCreation:
        """Create and persist an independent pig with rolled initial stats."""
        pig_id = uuid4()
        roll = roll_initial_stats(rng)
        pig = Pig(
            pig_id=pig_id,
            name=f"小猪-{pig_id.hex[:8]}" if name is None else name,
            **roll.values(),
        )

        def append_pig(document: PigstyDocument) -> PigstyDocument:
            return document.model_copy(update={"pigs": (*document.pigs, pig)})

        _ = await self._repository.update(identity, append_pig)
        return PigCreation(pig=pig, roll=roll)

    async def add_member(
        self,
        identity: SessionIdentity,
        member_platform_id: str,
        member_user_id: str,
        name: str | None = None,
        rng: RandomSource | None = None,
    ) -> PigCreation:
        """Create and persist a member-linked pig with rolled initial stats."""
        pig_id = uuid4()
        roll = roll_initial_stats(rng)
        pig = Pig(
            pig_id=pig_id,
            member_platform_id=member_platform_id,
            member_user_id=member_user_id,
            name=f"小猪-{pig_id.hex[:8]}" if name is None else name,
            **roll.values(),
        )

        def append_pig(document: PigstyDocument) -> PigstyDocument:
            member_pair = (member_platform_id, member_user_id)
            if any(
                (existing.member_platform_id, existing.member_user_id) == member_pair
                for existing in document.pigs
            ):
                raise DuplicateMemberPigError(*member_pair)
            return document.model_copy(update={"pigs": (*document.pigs, pig)})

        _ = await self._repository.update(identity, append_pig)
        return PigCreation(pig=pig, roll=roll)

    async def rename_pig(
        self,
        identity: SessionIdentity,
        position: int,
        name: str,
    ) -> Pig:
        """Rename one persisted pig selected by its 1-based display position."""

        def rename(document: PigstyDocument) -> PigstyDocument:
            index = position - 1
            if index < 0 or index >= len(document.pigs):
                raise PigPositionNotFoundError(position)
            existing = document.pigs[index]
            renamed = Pig.model_validate(
                existing.model_dump() | {"name": name, "updated_at": utc_now()}
            )
            pigs = (*document.pigs[:index], renamed, *document.pigs[index + 1 :])
            return document.model_copy(update={"pigs": pigs})

        document = await self._repository.update(identity, rename)
        return document.pigs[position - 1]

    async def list_pigs(self, identity: SessionIdentity) -> tuple[Pig, ...]:
        """Return the persisted pigs for one owner in creation order."""
        document = await self._repository.load(identity)
        return document.pigs

    async def list_events(self, identity: SessionIdentity) -> tuple[PigEvent, ...]:
        """Return the persisted events for one owner in record order."""
        document = await self._repository.load(identity)
        return document.events

    async def letgo_pig(
        self,
        identity: SessionIdentity,
        selector: str,
    ) -> LetgoResult:
        """Remove one pig by position, UUID, unique prefix, or exact nickname."""
        normalized_selector = selector.strip()
        removed: list[LetgoResult] = []

        def remove(document: PigstyDocument) -> PigstyDocument:
            index, pig = self._locate_pig(document.pigs, normalized_selector)
            events = tuple(
                event for event in document.events if event.pig_id == pig.pig_id
            )
            removed.append(LetgoResult(pig=pig, events=events))
            return document.model_copy(
                update={
                    "pigs": (*document.pigs[:index], *document.pigs[index + 1 :]),
                    "events": tuple(
                        event
                        for event in document.events
                        if event.pig_id != pig.pig_id
                    ),
                }
            )

        _ = await self._repository.update(identity, remove)
        return removed[0]

    @staticmethod
    def _locate_pig(  # noqa: C901
        pigs: tuple[Pig, ...],
        selector: str,
    ) -> tuple[int, Pig]:
        if not selector:
            raise PigTargetNotFoundError(selector)
        try:
            requested_id = UUID(selector)
        except ValueError:
            requested_id = None
        if requested_id is not None:
            exact = next(
                (
                    (index, pig)
                    for index, pig in enumerate(pigs)
                    if pig.pig_id == requested_id
                ),
                None,
            )
            if exact is not None:
                return exact
            raise PigTargetNotFoundError(selector)
        if selector.isdecimal():
            position = int(selector)
            if 1 <= position <= len(pigs):
                return position - 1, pigs[position - 1]
            raise PigTargetNotFoundError(selector)
        lowered = selector.lower()
        if len(selector) >= PIG_ID_PREFIX_MIN_LENGTH and all(
            character in "0123456789abcdef" for character in lowered
        ):
            matches = [
                (index, pig)
                for index, pig in enumerate(pigs)
                if pig.pig_id.hex.startswith(lowered)
            ]
            if len(matches) > 1:
                raise PigTargetAmbiguousError(selector, len(matches))
            if matches:
                return matches[0]
        matches = [
            (index, pig) for index, pig in enumerate(pigs) if pig.name == selector
        ]
        if len(matches) > 1:
            raise PigTargetAmbiguousError(selector, len(matches))
        if matches:
            return matches[0]
        raise PigTargetNotFoundError(selector)

    async def evolve_all_due(
        self,
        now: datetime,
        rng: RandomSource | None = None,
    ) -> DailyTickSummary:
        """Evolve every due pig across all documents and record real-time events."""
        source = rng if rng is not None else default_random_source()
        paths = await self._repository.document_paths()
        evolved_pigs = 0
        recorded_events = 0
        skipped_documents = 0
        failed_documents = 0
        for path in paths:
            stats = [0, 0]
            mutation = partial(
                _evolve_document_mutation,
                now=now,
                rng=source,
                stats=stats,
            )
            try:
                _ = await self._repository.update_path(path, mutation)
            except FileNotFoundError:
                skipped_documents += 1
                continue
            except PigstyDataError:
                failed_documents += 1
                continue
            evolved_pigs += stats[0]
            recorded_events += stats[1]
        return DailyTickSummary(
            ticked_at=now,
            evolved_pigs=evolved_pigs,
            recorded_events=recorded_events,
            scanned_documents=len(paths),
            skipped_documents=skipped_documents,
            failed_documents=failed_documents,
        )

    async def roll_unexpected_all(
        self,
        now: datetime,
        rng: RandomSource | None = None,
    ) -> tuple[UnexpectedOutcome, ...]:
        """Roll every due pig's unexpected dice and return triggered drafts."""
        source = rng if rng is not None else default_random_source()
        outcomes: list[UnexpectedOutcome] = []
        paths = await self._repository.document_paths()
        for path in paths:
            box: list[UnexpectedOutcome] = []
            mutation = partial(
                _roll_unexpected_mutation,
                now=now,
                rng=source,
                outcomes=box,
            )
            try:
                _ = await self._repository.update_path(path, mutation)
            except (FileNotFoundError, PigstyDataError):
                continue
            outcomes.extend(box)
        return tuple(outcomes)

    async def apply_unexpected_event(
        self,
        identity: SessionIdentity,
        pig_id: UUID,
        changes: tuple[StatChange, ...],
        description: str,
        occurred_at: datetime,
    ) -> Pig:
        """Apply one unexpected event's stat changes and record it."""

        def mutation(document: PigstyDocument) -> PigstyDocument:
            pigs = list(document.pigs)
            for index, existing in enumerate(pigs):
                if existing.pig_id != pig_id:
                    continue
                updated = apply_stat_changes(existing, changes, occurred_at)
                event = PigEvent(
                    category=UNEXPECTED_EVENT_CATEGORY,
                    pig_id=pig_id,
                    occurred_at=occurred_at,
                    description=description,
                )
                pigs[index] = updated
                return document.model_copy(
                    update={
                        "pigs": tuple(pigs),
                        "events": (*document.events, event),
                    }
                )
            raise UnexpectedPigNotFoundError(pig_id)

        document = await self._repository.update(identity, mutation)
        return next(pig for pig in document.pigs if pig.pig_id == pig_id)

    async def apply_user_interaction(
        self,
        identity: SessionIdentity,
        interactions: tuple[UserPigInteraction, ...],
        occurred_at: datetime,
    ) -> tuple[Pig, ...]:
        """Apply LLM-derived user interactions and record one user event per pig."""
        if not interactions:
            return await self.list_pigs(identity)

        def mutation(document: PigstyDocument) -> PigstyDocument:
            pigs = list(document.pigs)
            events = document.events
            seen_positions: set[int] = set()
            for interaction in interactions:
                if interaction.position in seen_positions:
                    raise DuplicateUserInteractionPositionError(interaction.position)
                seen_positions.add(interaction.position)
                index = interaction.position - 1
                if index < 0 or index >= len(pigs):
                    raise UserInteractionPigNotFoundError(interaction.position)
                existing = pigs[index]
                updated = apply_stat_changes(
                    existing,
                    interaction.changes,
                    occurred_at,
                )
                event = PigEvent(
                    category=USER_EVENT_CATEGORY,
                    pig_id=existing.pig_id,
                    occurred_at=occurred_at,
                    description=interaction.description,
                )
                pigs[index] = updated
                events = (*events, event)
            return document.model_copy(update={"pigs": tuple(pigs), "events": events})

        updated = await self._repository.update(identity, mutation)
        return tuple(
            updated.pigs[interaction.position - 1] for interaction in interactions
        )
