"""ADMIN_SESSION_COOKIE_DOMAIN accepts a bare domain; blank means unset."""

from __future__ import annotations

import pytest
from app.core.config import Settings
from pydantic import ValidationError


def _settings(value: str | None) -> Settings:
    return Settings(_env_file=None, admin_session_cookie_domain=value)  # type: ignore[call-arg]


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_or_missing_cookie_domain_is_unset(blank: str | None) -> None:
    assert _settings(blank).admin_session_cookie_domain is None


def test_bare_domain_is_kept_lowercase() -> None:
    assert _settings(" XiaoSaiAI.com ").admin_session_cookie_domain == "xiaosaiai.com"


@pytest.mark.parametrize(
    "bad",
    ["https://xiaosaiai.com", "xiaosaiai.com/admin", ".xiaosaiai.com", "localhost", "a b.com"],
)
def test_urls_paths_and_dotted_forms_are_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        _settings(bad)
