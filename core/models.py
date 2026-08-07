"""Strict Pydantic models for Pigsty persistence boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar, Final, Literal, Self, assert_never
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from .identity import PigstyScope, SessionIdentity

CURRENT_SCHEMA_VERSION: Final = 1


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class Pig(BaseModel):
    """Persisted state for one adopted group member."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        validate_default=True,
        revalidate_instances="always",
    )

    pig_id: UUID = Field(default_factory=uuid4)
    member_platform_id: str | None = Field(default=None, min_length=1)
    member_user_id: str | None = Field(default=None, min_length=1)
    name: str = Field(min_length=1, max_length=32)
    age_days: int = Field(default=0, ge=0)
    weight_kg: float = Field(default=5.0, gt=0)
    health: int = Field(default=100, ge=0, le=100)
    mood: int = Field(default=70, ge=0, le=100)
    energy: int = Field(default=80, ge=0, le=100)
    born_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_state_update_at: datetime = Field(default_factory=utc_now)

    @field_validator("member_platform_id", "member_user_id")
    @classmethod
    def reject_blank_member_ids(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        """Reject member identifiers that contain no non-space characters."""
        if value is not None and not value.strip():
            error_type = "blank_string"
            raise PydanticCustomError(
                error_type,
                "{field_name} must contain a non-space character",
                {"field_name": info.field_name},
            )
        return value

    @field_validator("name")
    @classmethod
    def reject_blank_name(cls, value: str, info: ValidationInfo) -> str:
        """Reject names that contain no non-space characters."""
        if not value.strip():
            error_type = "blank_string"
            raise PydanticCustomError(
                error_type,
                "{field_name} must contain a non-space character",
                {"field_name": info.field_name},
            )
        return value

    @model_validator(mode="after")
    def validate_member_association(self) -> Self:
        """Require member identifiers to be present together or both absent."""
        if (self.member_platform_id is None) != (self.member_user_id is None):
            error_type = "partial_member_association"
            raise PydanticCustomError(
                error_type,
                "member identifiers must be provided together",
            )
        return self

    @field_validator(
        "born_at",
        "created_at",
        "updated_at",
        "last_state_update_at",
        mode="after",
    )
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Require timezone-aware timestamps and store them in UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            error_type = "timezone_required"
            raise PydanticCustomError(
                error_type,
                "timestamp must include timezone information",
            )
        return value.astimezone(UTC)


class PigstyDocument(BaseModel):
    """One versioned, scope-specific Pigsty JSON document."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        validate_default=True,
        revalidate_instances="always",
    )

    schema_version: Literal[1] = CURRENT_SCHEMA_VERSION
    scope: PigstyScope
    platform_id: str = Field(min_length=1)
    owner_user_id: str = Field(min_length=1)
    group_id: str | None = None
    pigs: tuple[Pig, ...] = ()

    @field_validator("platform_id", "owner_user_id")
    @classmethod
    def reject_blank_identity_fields(cls, value: str) -> str:
        """Reject identity fields containing no non-space characters."""
        if not value.strip():
            error_type = "blank_identity"
            raise PydanticCustomError(
                error_type,
                "identity fields must contain a non-space character",
            )
        return value

    @field_validator("group_id")
    @classmethod
    def reject_blank_group_id(cls, value: str | None) -> str | None:
        """Reject a group id that is present but contains only whitespace."""
        if value is not None and not value.strip():
            error_type = "blank_group_id"
            raise PydanticCustomError(
                error_type,
                "group_id must contain a non-space character",
            )
        return value

    @model_validator(mode="after")
    def validate_scope_shape(self) -> Self:
        """Keep persisted group ids consistent with the effective scope."""
        scope = self.scope
        match scope:
            case PigstyScope.GLOBAL:
                if self.group_id is not None:
                    error_type = "global_group_id"
                    raise PydanticCustomError(
                        error_type,
                        "global documents cannot contain a group id",
                    )
                return self
            case PigstyScope.GROUP:
                return self
        assert_never(scope)

    @classmethod
    def empty_for_identity(cls, identity: SessionIdentity) -> Self:
        """Create a non-persisted empty document matching an identity."""
        return cls(
            schema_version=CURRENT_SCHEMA_VERSION,
            scope=identity.scope,
            platform_id=identity.platform_id,
            owner_user_id=identity.owner_user_id,
            group_id=identity.group_id,
            pigs=(),
        )

    def to_identity(self) -> SessionIdentity:
        """Convert persisted identity fields back into a repository key."""
        return SessionIdentity(
            scope=self.scope,
            platform_id=self.platform_id,
            owner_user_id=self.owner_user_id,
            group_id=self.group_id,
        )
