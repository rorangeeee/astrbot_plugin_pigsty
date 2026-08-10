"""Pure core services for creating and listing Pigsty pigs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from typing_extensions import override

from .models import Pig, PigstyDocument, utc_now

if TYPE_CHECKING:
    from .identity import SessionIdentity
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


class PigstyService:
    """Create and read pigs within the repository-owned identity scope."""

    def __init__(self, repository: JsonPigstyRepository) -> None:
        """Create a service backed by the supplied repository."""
        self._repository: JsonPigstyRepository = repository

    async def add_random(
        self, identity: SessionIdentity, name: str | None = None
    ) -> Pig:
        """Create and persist an independent pig for one owner."""
        pig_id = uuid4()
        pig = Pig(
            pig_id=pig_id,
            name=f"小猪-{pig_id.hex[:8]}" if name is None else name,
        )

        def append_pig(document: PigstyDocument) -> PigstyDocument:
            return document.model_copy(update={"pigs": (*document.pigs, pig)})

        _ = await self._repository.update(identity, append_pig)
        return pig

    async def add_member(
        self,
        identity: SessionIdentity,
        member_platform_id: str,
        member_user_id: str,
        name: str | None = None,
    ) -> Pig:
        """Create and persist a pig linked to one owner member pair."""
        pig_id = uuid4()
        pig = Pig(
            pig_id=pig_id,
            member_platform_id=member_platform_id,
            member_user_id=member_user_id,
            name=f"小猪-{pig_id.hex[:8]}" if name is None else name,
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
        return pig

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
