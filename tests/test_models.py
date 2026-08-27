from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from core.identity import PigstyScope, resolve_session_identity
from core.models import Pig, PigEvent, PigstyDocument
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
    assert pig.unexpected_chance_percent == 20
    assert pig.unexpected_last_rolled_at is None


@pytest.mark.parametrize("chance", [19, 101])
def test_pig_rejects_out_of_range_unexpected_chance(chance: int) -> None:
    # Given an unexpected-event chance outside the pity ladder
    # When the boundary model parses it
    with pytest.raises(ValidationError):
        _ = Pig(name="Lucky", unexpected_chance_percent=chance)

    # Then the invalid chance is rejected


def test_pig_normalizes_unexpected_roll_timestamp_to_utc() -> None:
    # Given an aware roll timestamp in GMT+8
    local_time = datetime(2026, 8, 14, 9, 0, tzinfo=timezone(timedelta(hours=8)))

    # When it crosses the Pig model boundary
    pig = Pig(name="Lucky", unexpected_last_rolled_at=local_time)

    # Then it is stored as UTC without changing the instant
    assert pig.unexpected_last_rolled_at is not None
    assert pig.unexpected_last_rolled_at.hour == 1
    assert pig.unexpected_last_rolled_at.tzinfo is UTC


def test_legacy_pig_json_without_unexpected_fields_parses() -> None:
    # Given minimal legacy pig data written before the unexpected-event fields
    raw = Pig(name="Lucky").model_dump()
    del raw["unexpected_chance_percent"]
    del raw["unexpected_last_rolled_at"]

    # When the boundary model parses it
    pig = Pig.model_validate(raw)

    # Then the missing fields fall back to their defaults
    assert pig.unexpected_chance_percent == 20
    assert pig.unexpected_last_rolled_at is None


def test_pig_allows_missing_member_association() -> None:
    # Given a Pig without a member association
    # When it is created with only its name
    pig = Pig(name="Lucky")

    # Then both member identifiers remain absent
    assert pig.member_platform_id is None
    assert pig.member_user_id is None


def test_pig_allows_long_member_nickname_without_extending_pig_name() -> None:
    # Given a linked member whose group nickname is longer than the pig limit
    nickname = "这是一个很长的群昵称" * 8

    # When the linked pig is created with an independent short pig name
    pig = Pig(
        member_platform_id="qq",
        member_user_id="7",
        member_name=nickname,
        name="小猪",
    )

    # Then the member nickname is stored separately from the pig nickname
    assert pig.member_name == nickname
    assert pig.name == "小猪"


@pytest.mark.parametrize(
    ("member_platform_id", "member_user_id"),
    [("qq", None), (None, "7")],
)
def test_pig_rejects_partial_member_association(
    member_platform_id: str | None,
    member_user_id: str | None,
) -> None:
    # Given exactly one member identifier
    # When the boundary model parses it
    with pytest.raises(ValidationError):
        _ = Pig(
            member_platform_id=member_platform_id,
            member_user_id=member_user_id,
            name="Lucky",
        )

    # Then the incomplete association is rejected


@pytest.mark.parametrize("field", ["member_platform_id", "member_user_id"])
def test_pig_rejects_blank_member_identifier(field: str) -> None:
    # Given a member identifier containing only whitespace
    values: dict[str, str | None] = {
        "member_platform_id": "qq",
        "member_user_id": "7",
        "name": "Lucky",
        field: "   ",
    }

    # When the boundary model parses it
    with pytest.raises(ValidationError):
        _ = Pig.model_validate(values)

    # Then the blank identifier is rejected


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


def test_pig_event_normalizes_timestamp_and_generates_uuid() -> None:
    # Given a pig reference and an aware timestamp in GMT+8
    pig = Pig(name="Lucky")
    occurred = datetime(2026, 8, 14, 9, 0, tzinfo=timezone(timedelta(hours=8)))

    # When a regular event is created
    event = PigEvent(
        category="regular_events",
        pig_id=pig.pig_id,
        occurred_at=occurred,
        description="年龄+1",
    )

    # Then it carries an internal UUID and stores the moment in UTC
    assert isinstance(event.event_id, UUID)
    assert event.pig_id == pig.pig_id
    assert event.occurred_at.hour == 1
    assert event.occurred_at.tzinfo is UTC


@pytest.mark.parametrize(
    "category",
    ["regular_events", "unexpected_events", "user_events"],
)
def test_pig_event_accepts_known_categories(category: str) -> None:
    # Given one approved event category
    # When an event is created with it
    event = PigEvent(
        category=category,
        pig_id=Pig(name="Lucky").pig_id,
        description="测试",
    )

    # Then the category persists unchanged
    assert event.category == category


def test_pig_event_rejects_unknown_category() -> None:
    # Given an event category outside the approved set
    # When the boundary model parses it
    with pytest.raises(ValidationError):
        _ = PigEvent(
            category="admin_events",
            pig_id=Pig(name="Lucky").pig_id,
            description="测试",
        )

    # Then the unknown category is rejected


@pytest.mark.parametrize("description", ["", "   "])
def test_pig_event_rejects_blank_description(description: str) -> None:
    # Given a blank event description
    # When the boundary model parses it
    with pytest.raises(ValidationError):
        _ = PigEvent(
            category="regular_events",
            pig_id=Pig(name="Lucky").pig_id,
            description=description,
        )

    # Then the blank description is rejected


def test_pig_event_rejects_naive_timestamp() -> None:
    # Given a timestamp without timezone information
    naive = datetime(2026, 8, 14, 9, 0, tzinfo=UTC).replace(tzinfo=None)

    # When it crosses the PigEvent boundary
    with pytest.raises(ValidationError):
        _ = PigEvent(
            category="regular_events",
            pig_id=Pig(name="Lucky").pig_id,
            description="测试",
            occurred_at=naive,
        )

    # Then the ambiguous timestamp is rejected


def test_document_parses_legacy_json_without_events() -> None:
    # Given legacy JSON written before events existed
    raw = """
    {
      "schema_version": 1,
      "scope": "global",
      "platform_id": "qq",
      "owner_user_id": "42",
      "group_id": null,
      "pigs": []
    }
    """

    # When the persistence boundary parses it
    document = PigstyDocument.model_validate_json(raw)

    # Then the missing events field defaults to an empty record
    assert document.events == ()


def test_document_round_trip_preserves_events() -> None:
    # Given a document with one recorded event
    identity = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", None)
    pig = Pig(name="Lucky")
    event = PigEvent(
        category="unexpected_events",
        pig_id=pig.pig_id,
        description="测试事件",
    )
    document = PigstyDocument.empty_for_identity(identity).model_copy(
        update={"pigs": (pig,), "events": (event,)}
    )

    # When it is serialized and parsed at the JSON boundary
    restored = PigstyDocument.model_validate_json(document.model_dump_json())

    # Then the event record is preserved exactly
    assert restored == document
