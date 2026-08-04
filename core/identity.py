"""Typed session identities and safe Pigsty storage paths."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from hashlib import sha256
from pathlib import Path
from typing import Final, assert_never

from typing_extensions import override


@unique
class PigstyScope(StrEnum):
    """Configured storage scopes supported by Pigsty."""

    GLOBAL = "global"
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class IdentityError(Exception):
    """Raised when an external session identity cannot be normalized."""

    field: str
    value: str
    reason: str

    @override
    def __str__(self) -> str:
        return f"invalid {self.field} {self.value!r}: {self.reason}"


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    """Normalized identity that selects one Pigsty persistence document."""

    scope: PigstyScope
    platform_id: str
    owner_user_id: str
    group_id: str | None

    @property
    def effective_scope(self) -> PigstyScope:
        """Return the persisted scope, including the private-message rule."""
        scope = self.scope
        match scope:
            case PigstyScope.GLOBAL:
                return PigstyScope.GLOBAL
            case PigstyScope.GROUP:
                if self.group_id is None:
                    return PigstyScope.GLOBAL
                return PigstyScope.GROUP
        assert_never(scope)

    @property
    def relative_key(self) -> str:
        """Return a canonical, non-path storage key for this identity."""
        scope = self.effective_scope
        match scope:
            case PigstyScope.GLOBAL:
                namespace = "private" if self.scope is PigstyScope.GROUP else "global"
                return _canonical_key(namespace, self.platform_id, self.owner_user_id)
            case PigstyScope.GROUP:
                group_id = self.group_id
                if group_id is None:
                    message = "group scope requires a group id"
                    raise RuntimeError(message)
                return _canonical_key(
                    "group", self.platform_id, group_id, self.owner_user_id
                )
        assert_never(scope)

    def relative_path(self) -> Path:
        """Return a hashed relative path below the repository data directory."""
        scope = self.effective_scope
        match scope:
            case PigstyScope.GLOBAL:
                directory = "private" if self.scope is PigstyScope.GROUP else "global"
                owner_hash = _digest(self.relative_key)
                return Path("owners") / directory / f"{owner_hash}.json"
            case PigstyScope.GROUP:
                group_id = self.group_id
                if group_id is None:
                    message = "group scope requires a group id"
                    raise RuntimeError(message)
                group_hash = _digest(
                    _canonical_key("group", self.platform_id, group_id)
                )
                owner_hash = _digest(self.relative_key)
                return Path("owners") / "groups" / group_hash / f"{owner_hash}.json"
        assert_never(scope)


def resolve_session_identity(
    scope: PigstyScope | str,
    platform_id: str,
    owner_user_id: str,
    group_id: str | None,
) -> SessionIdentity:
    """Parse external session values into a normalized storage identity."""
    parsed_scope = _parse_scope(scope)
    normalized_platform_id = _normalize_identifier("platform_id", platform_id)
    normalized_owner_user_id = _normalize_identifier("owner_user_id", owner_user_id)
    normalized_group_id = (
        None if group_id is None else _normalize_identifier("group_id", group_id)
    )
    if parsed_scope is PigstyScope.GLOBAL:
        normalized_group_id = None
    return SessionIdentity(
        scope=parsed_scope,
        platform_id=normalized_platform_id,
        owner_user_id=normalized_owner_user_id,
        group_id=normalized_group_id,
    )


def _parse_scope(value: PigstyScope | str) -> PigstyScope:
    if isinstance(value, PigstyScope):
        return value
    try:
        return PigstyScope(value.strip())
    except ValueError as error:
        field = "scope"
        raise IdentityError(field, value, "must be 'global' or 'group'") from error


def _normalize_identifier(field: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise IdentityError(field, value, "must not be empty")
    return normalized


def _canonical_key(*parts: str) -> str:
    return "|".join(f"{len(part)}:{part}" for part in parts)


def _digest(value: str) -> str:
    algorithm: Final = sha256
    return algorithm(value.encode("utf-8")).hexdigest()
