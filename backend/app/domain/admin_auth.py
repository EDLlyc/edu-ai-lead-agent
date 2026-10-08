"""Login rules of the 运营后台: password hashing, session tokens and the lockout policy.

Passwords use stdlib scrypt (no extra dependency). Session tokens are random and only their
SHA-256 is stored, so a database read never yields a usable cookie.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

AdminRole = Literal["owner", "editor"]
ADMIN_ROLES: tuple[AdminRole, ...] = ("owner", "editor")

SESSION_COOKIE_NAME = "edu_admin_session"
SESSION_LIFETIME = timedelta(hours=12)
# A request header a cross-site form cannot send; required on every admin write.
WRITE_GUARD_HEADER = "X-Admin-Request"

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)

PASSWORD_MIN_CHARS = 10
PASSWORD_MAX_CHARS = 128
_USERNAME = re.compile(r"^[a-z][a-z0-9_.-]{1,39}$")

# scrypt cost: about 50 ms and 16 MiB per check.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_KEY_BYTES = 32
_SCRYPT_MAXMEM = 64 * 1024 * 1024


class AdminInputError(ValueError):
    """An account field broke a rule; the message is safe to show."""


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if not _USERNAME.fullmatch(username):
        raise AdminInputError(
            "username must be 2-40 characters: a-z first, then a-z, 0-9, '_', '.' or '-'"
        )
    return username


def check_display_name(value: str) -> str:
    name = value.strip()
    if not 1 <= len(name) <= 40:
        raise AdminInputError("display name must be 1-40 characters")
    return name


def check_new_password(password: str) -> None:
    if not PASSWORD_MIN_CHARS <= len(password) <= PASSWORD_MAX_CHARS:
        raise AdminInputError(
            f"password must be {PASSWORD_MIN_CHARS}-{PASSWORD_MAX_CHARS} characters"
        )
    if password.strip() != password:
        raise AdminInputError("password must not start or end with spaces")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=_SCRYPT_MAXMEM,
        dklen=_SCRYPT_KEY_BYTES,
    )


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    """`scrypt$n$r$p$salt$key`, with url-safe base64 salt and key."""

    salt = secrets.token_bytes(16)
    key = _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, key = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(key)
        actual = _scrypt(password, _unb64(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Checked against when the username is unknown, so both failures cost the same time.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FailedLogin:
    failed_login_count: int
    locked_until: datetime | None


def register_failed_login(failed_login_count: int, now: datetime) -> FailedLogin:
    """Count one more wrong password; the 5th in a row locks the account for 15 minutes."""

    count = failed_login_count + 1
    if count >= MAX_FAILED_LOGINS:
        return FailedLogin(0, now + LOCKOUT)
    return FailedLogin(count, None)


def is_locked(locked_until: datetime | None, now: datetime) -> bool:
    return locked_until is not None and locked_until > now


def role_allows(role: str, required: AdminRole) -> bool:
    return role == "owner" or role == required


__all__ = [
    "ADMIN_ROLES",
    "LOCKOUT",
    "MAX_FAILED_LOGINS",
    "SESSION_COOKIE_NAME",
    "SESSION_LIFETIME",
    "WRITE_GUARD_HEADER",
    "AdminInputError",
    "AdminRole",
    "FailedLogin",
    "burn_password_check",
    "check_display_name",
    "check_new_password",
    "hash_password",
    "hash_session_token",
    "is_locked",
    "new_session_token",
    "normalize_username",
    "register_failed_login",
    "role_allows",
    "verify_password",
]
