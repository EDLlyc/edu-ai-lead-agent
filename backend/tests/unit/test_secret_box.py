from __future__ import annotations

import pytest
from app.domain.secret_box import SecretBoxError, last4, new_key, open_sealed, parse_key, seal


def test_a_sealed_secret_opens_only_with_its_key_and_purpose() -> None:
    key = parse_key(new_key())
    sealed = seal("0123456789abcdef0123456789abcdef", key=key, purpose="wechat_app_secret:wx1")
    assert sealed.startswith("v1:")
    assert "0123456789abcdef" not in sealed
    assert open_sealed(sealed, key=key, purpose="wechat_app_secret:wx1") == (
        "0123456789abcdef0123456789abcdef"
    )
    # A fresh nonce every time.
    assert seal("same", key=key, purpose="p") != seal("same", key=key, purpose="p")

    with pytest.raises(SecretBoxError):
        open_sealed(sealed, key=parse_key(new_key()), purpose="wechat_app_secret:wx1")
    with pytest.raises(SecretBoxError):
        open_sealed(sealed, key=key, purpose="wechat_app_secret:wx2")
    with pytest.raises(SecretBoxError):
        open_sealed(sealed[:-6] + "AAAAAA", key=key, purpose="wechat_app_secret:wx1")
    with pytest.raises(SecretBoxError):
        open_sealed("plain", key=key, purpose="x")


@pytest.mark.parametrize("value", ["", "not base64 !!", "c2hvcnQ"])
def test_a_bad_key_is_refused(value: str) -> None:
    with pytest.raises(SecretBoxError):
        parse_key(value)


def test_last4_hides_short_values() -> None:
    assert last4("0123456789abcdef") == "cdef"
    assert last4("abc") == "****"
