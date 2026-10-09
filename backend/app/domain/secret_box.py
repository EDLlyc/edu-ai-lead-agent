"""Encrypt operator-entered secrets (WeChat AppSecret, later model API keys) at rest.

AES-256-GCM with a key that lives only in the server environment (`ADMIN_SECRET_KEY`, url-safe
base64 of 32 bytes). The stored form is `v1:<base64(nonce | ciphertext | tag)>`. The associated
data names what the secret belongs to (for example `wechat_app_secret:<app_id>`), so a ciphertext
copied onto another row fails to decrypt.
"""

from __future__ import annotations

import base64
import binascii
import secrets

from Crypto.Cipher import AES  # pycryptodome, already in the runtime lock

_VERSION = "v1:"
_NONCE_BYTES = 12
_TAG_BYTES = 16


class SecretBoxError(ValueError):
    """The key is missing or malformed, or a stored secret cannot be decrypted."""


def parse_key(value: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(value.strip() + "=" * (-len(value.strip()) % 4))
    except (binascii.Error, ValueError) as error:
        raise SecretBoxError("ADMIN_SECRET_KEY must be url-safe base64") from error
    if len(key) != 32:
        raise SecretBoxError("ADMIN_SECRET_KEY must decode to 32 bytes")
    return key


def new_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def seal(plaintext: str, *, key: bytes, purpose: str) -> str:
    nonce = secrets.token_bytes(_NONCE_BYTES)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=_TAG_BYTES)
    cipher.update(purpose.encode("utf-8"))
    ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
    return _VERSION + base64.urlsafe_b64encode(nonce + ciphertext + tag).decode("ascii")


def open_sealed(sealed: str, *, key: bytes, purpose: str) -> str:
    if not sealed.startswith(_VERSION):
        raise SecretBoxError("unknown secret format")
    try:
        raw = base64.urlsafe_b64decode(sealed[len(_VERSION) :])
    except (binascii.Error, ValueError) as error:
        raise SecretBoxError("stored secret is damaged") from error
    if len(raw) < _NONCE_BYTES + _TAG_BYTES + 1:
        raise SecretBoxError("stored secret is damaged")
    nonce, body, tag = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:-_TAG_BYTES], raw[-_TAG_BYTES:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=_TAG_BYTES)
    cipher.update(purpose.encode("utf-8"))
    try:
        return cipher.decrypt_and_verify(body, tag).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise SecretBoxError("stored secret cannot be decrypted with this key") from error


def last4(secret: str) -> str:
    return secret[-4:] if len(secret) >= 8 else "****"


__all__ = ["SecretBoxError", "last4", "new_key", "open_sealed", "parse_key", "seal"]
