from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from core.identity import PigstyScope, resolve_session_identity
from core.models import Pig, PigstyDocument
from pydantic import ValidationError


def test_pig_uses_phase_one_defaults_and_generates_uuid() -> None:
    # Given the required member identity and name
    # When a Pig is created
    pig = Pig(member_platform_id="qq", member_user_id="7", name="Lucky")

    # Then phase-one defaults and an internal UUID are present
    assert isinstance(pig.pig_id, UUID)
    assert pig.age_days == 0
    assert pig.weight_kg == 5.0
    assert pig.health == 100
    assert pig.mood == 70
    assert pig.energy == 80
    assert pig.born_at.tzinfo is UTC
    assert pig.created_at.tzinfo is UTC
    assert pig.updated_at.tzinfo is UTC
    assert pig.last_state_update_at.tzinfo is UTC


def test_pig_rejects_blank_name() -> None:
    # Given a name containing only whitespace
    # When the boundary model parses it
    with pytest.raises(ValidationError):
        _ = Pig(member_platform_id="qq", member_user_id="7", name="   ")

    # Then Pydantic rejects the invalid boundary value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("age_days", -1),
        ("weight_kg", 0.0),
        ("health", 101),
        ("mood", -1),
        ("energy", 101),
    ],
)
def test_pig_rejects_out_of_range_state(field: str, value: float) -> None:
    # Given one out-of-range state value
    values: dict[str, str | float] = {
        "member_platform_id": "qq",
        "member_user_id": "7",
        "name": "Lucky",
        field: value,
    }

    # When the boundary model parses it
    with pytest.raises(ValidationError):
        _ = Pig.model_validate(values)

    # Then Pydantic rejects the invalid state


def test_pig_normalizes_aware_timestamps_to_utc() -> None:
    # Given an aware timestamp in a non-UTC timezone
    local_time = datetime(
        2026,
        8,
        3,
        12,
        tzinfo=timezone(timedelta(hours=8)),
    )

    # When it crosses the Pig model boundary
    pig = Pig(
        member_platform_id="qq",
        member_user_id="7",
        name="Lucky",
        born_at=local_time,
    )

    # Then it is stored as UTC without changing the instant
    assert pig.born_at.tzinfo is UTC
    assert pig.born_at.hour == 4


def test_pig_rejects_naive_timestamp() -> None:
    # Given a datetime without timezone information
    naive_time = datetime(2026, 8, 3, 12, tzinfo=UTC).replace(tzinfo=None)

    # When it crosses the Pig model boundary
    with pytest.raises(ValidationError):
        _ = Pig(
            member_platform_id="qq",
            member_user_id="7",
            name="Lucky",
            created_at=naive_time,
        )

    # Then the ambiguous timestamp is rejected


def test_pig_json_round_trip_preserves_state() -> None:
    # Given a valid Pig
    pig = Pig(member_platform_id="qq", member_user_id="7", name="Lucky")

    # When it is serialized and parsed at the JSON boundary
    restored = Pig.model_validate_json(pig.model_dump_json())

    # Then all persisted fields, including the UUID, are preserved
    assert restored == pig


def test_empty_document_matches_group_identity() -> None:
    # Given a group-scoped session identity
    identity = resolve_session_identity(PigstyScope.GROUP, "qq", "42", "1001")

    # When an empty document is created for it
    document = PigstyDocument.empty_for_identity(identity)

    # Then the persisted identity and empty collection match the session
    assert document.schema_version == 1
    assert document.scope is PigstyScope.GROUP
    assert document.platform_id == "qq"
    assert document.owner_user_id == "42"
    assert document.group_id == "1001"
    assert document.pigs == ()


def test_group_mode_private_document_preserves_group_configuration() -> None:
    # Given a private message while group mode is configured
    identity = resolve_session_identity(PigstyScope.GROUP, "qq", "42", None)

    # When an empty document is created for it
    document = PigstyDocument.empty_for_identity(identity)

    # Then the private storage document preserves group-mode configuration
    assert document.scope is PigstyScope.GROUP
    assert document.group_id is None


def test_document_rejects_unknown_schema_version() -> None:
    # Given valid JSON with an unsupported schema version
    raw = """
    {
      "schema_version": 2,
      "scope": "global",
      "platform_id": "qq",
      "owner_user_id": "42",
      "group_id": null,
      "pigs": []
    }
    """

    # When the persistence boundary parses it
    with pytest.raises(ValidationError) as captured:
        _ = PigstyDocument.model_validate_json(raw)

    # Then schema_version is the rejected field
    assert captured.value.errors()[0]["loc"] == ("schema_version",)


def test_document_serializes_pigs_as_json_array() -> None:
    # Given an empty global document
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", None)
    document = PigstyDocument.empty_for_identity(identity)

    # When it is serialized
    raw = document.model_dump_json()

    # Then the persisted JSON uses the documented array shape
    assert '"pigs":[]' in raw
