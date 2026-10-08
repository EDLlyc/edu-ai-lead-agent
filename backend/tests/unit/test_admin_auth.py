from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.domain.admin_auth import (
    LOCKOUT,
    MAX_FAILED_LOGINS,
    AdminInputError,
    check_new_password,
    hash_password,
    hash_session_token,
    is_locked,
    new_session_token,
    normalize_username,
    register_failed_login,
    role_allows,
    verify_password,
)
from app.infrastructure.db.admin_auth import _check_no_secrets

NOW = datetime(2026, 10, 8, 2, 0, tzinfo=UTC)


def test_password_hash_round_trips_and_never_contains_the_password() -> None:
    encoded = hash_password("correct horse 42")
    assert encoded.startswith("scrypt$16384$8$1$")
    assert "correct horse" not in encoded
    assert verify_password("correct horse 42", encoded)
    assert not verify_password("correct horse 43", encoded)
    # A fresh salt every time.
    assert hash_password("correct horse 42") != encoded


@pytest.mark.parametrize(
    "encoded",
    ["", "plain", "bcrypt$1$2$3$4$5", "scrypt$x$8$1$AAAA$AAAA", "scrypt$16384$8$1$!!$!!"],
)
def test_a_malformed_hash_never_verifies(encoded: str) -> None:
    assert not verify_password("anything", encoded)


def test_session_tokens_are_random_and_stored_only_as_sha256() -> None:
    first, second = new_session_token(), new_session_token()
    assert first != second
    assert len(first) >= 40
    digest = hash_session_token(first)
    assert len(digest) == 64
    assert first not in digest


def test_usernames_are_normalised_and_checked() -> None:
    assert normalize_username("  Teacher.Li ") == "teacher.li"
    for bad in ["", "a", "1abc", "李老师", "a b", "x" * 41]:
        with pytest.raises(AdminInputError):
            normalize_username(bad)


def test_new_passwords_need_ten_characters_without_edge_spaces() -> None:
    check_new_password("0123456789")
    for bad in ["short", " 0123456789", "x" * 129]:
        with pytest.raises(AdminInputError):
            check_new_password(bad)


def test_the_fifth_wrong_password_locks_for_fifteen_minutes() -> None:
    count = 0
    for _ in range(MAX_FAILED_LOGINS - 1):
        failed = register_failed_login(count, NOW)
        assert failed.locked_until is None
        count = failed.failed_login_count
    locked = register_failed_login(count, NOW)
    assert locked == type(locked)(0, NOW + LOCKOUT)
    assert is_locked(locked.locked_until, NOW + LOCKOUT - timedelta(seconds=1))
    assert not is_locked(locked.locked_until, NOW + LOCKOUT)
    assert not is_locked(None, NOW)


def test_owner_can_do_everything_an_editor_cannot_do_owner_work() -> None:
    assert role_allows("owner", "owner")
    assert role_allows("owner", "editor")
    assert role_allows("editor", "editor")
    assert not role_allows("editor", "owner")
    assert not role_allows("viewer", "editor")


def test_audit_details_refuse_secret_looking_keys_at_any_depth() -> None:
    _check_no_secrets({"reason": "wrong_password", "changes": [{"field": "url"}]})
    for detail in [
        {"password": "x"},
        {"changes": [{"api_key": "x"}]},
        {"nested": {"AppSecret": "x"}},
        {"session_token": "x"},
    ]:
        with pytest.raises(ValueError, match="secret"):
            _check_no_secrets(detail)
