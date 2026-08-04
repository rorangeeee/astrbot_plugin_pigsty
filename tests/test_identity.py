from pathlib import Path

from core.identity import PigstyScope, resolve_session_identity


def test_global_identity_is_shared_across_group_ids() -> None:
    """Given global scope, group ids do not change the owner's storage key."""
    first = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", "group-a")
    second = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", "group-b")

    assert first.relative_key == second.relative_key
    assert first.effective_scope is PigstyScope.GLOBAL


def test_group_identity_separates_group_chat_and_private_chat() -> None:
    """Given group scope, group chat and private chat use different spaces."""
    group = resolve_session_identity(PigstyScope.GROUP, "qq", "42", "group-a")
    private = resolve_session_identity(PigstyScope.GROUP, "qq", "42", None)

    assert group.relative_key != private.relative_key
    assert group.effective_scope is PigstyScope.GROUP
    assert private.effective_scope is PigstyScope.GLOBAL


def test_storage_path_contains_only_hashes() -> None:
    """Given unsafe external identifiers, the generated path contains no raw ids."""
    identity = resolve_session_identity(
        PigstyScope.GROUP,
        "qq/unsafe",
        "../secret-user-42",
        "group:1",
    )

    path = identity.relative_path()

    assert isinstance(path, Path)
    assert "unsafe" not in str(path)
    assert "secret-user-42" not in str(path)
    assert "group:1" not in str(path)
    assert path.parts[:2] == ("owners", "groups")


def test_platform_is_part_of_the_storage_key() -> None:
    """Given equal user ids on two platforms, storage keys remain isolated."""
    qq = resolve_session_identity(PigstyScope.GLOBAL, "qq", "42", None)
    telegram = resolve_session_identity(PigstyScope.GLOBAL, "telegram", "42", None)

    assert qq.relative_key != telegram.relative_key
