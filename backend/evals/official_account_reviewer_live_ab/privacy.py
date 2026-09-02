"""Bounded privacy scan for Reviewer A/B inputs and evidence artifacts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from .models import canonical_json_bytes

MAX_SCANNED_BYTES = 4_194_304

_PROHIBITED_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "chain_of_thought",
        "cookie",
        "credential",
        "password",
        "private_path",
        "prompt",
        "provider_body",
        "provider_response",
        "raw_body",
        "raw_prompt",
        "secret",
        "session_id",
        "user_id",
    }
)
_SENSITIVE_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE)),
    ("bearer_token", re.compile(r"authorization\s*:\s*bearer", re.IGNORECASE)),
    ("provider_key", re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_-]{12,}\b", re.IGNORECASE)),
    ("database_url", re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb)://", re.IGNORECASE)),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("mainland_phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("identity_number", re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")),
    ("private_path", re.compile(r"(?:^|[\s\"'])(?:/home/|/root/|[A-Z]:\\Users\\)")),
    ("query_url", re.compile(r"https?://[^\s?#]+\?[^\s]+", re.IGNORECASE)),
    ("data_url", re.compile(r"data:[^;,]+;base64,", re.IGNORECASE)),
)


class PrivacyScanError(ValueError):
    """An evidence artifact contains prohibited secrets, PII, or raw provider data."""


def scan_evidence(value: object) -> tuple[str, ...]:
    """Return stable issue codes; an empty tuple is a passing privacy scan."""

    payload = canonical_json_bytes(value)
    issues: set[str] = set()
    if len(payload) > MAX_SCANNED_BYTES:
        issues.add("artifact_too_large")
        return tuple(sorted(issues))
    _scan_value(value, issues, field_name=None)
    return tuple(sorted(issues))


def require_privacy_safe(value: object) -> None:
    issues = scan_evidence(value)
    if issues:
        raise PrivacyScanError("privacy scan failed: " + ",".join(issues))


def _scan_value(value: object, issues: set[str], *, field_name: str | None) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in _PROHIBITED_KEYS:
                issues.add(f"prohibited_key:{normalized}")
            _scan_sensitive_text(str(key), issues)
            _scan_value(child, issues, field_name=normalized)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _scan_value(child, issues, field_name=field_name)
    elif isinstance(value, str):
        if _is_typed_opaque_digest(field_name, value):
            return
        _scan_sensitive_text(value, issues)


def _is_typed_opaque_digest(field_name: str | None, value: str) -> bool:
    """Ignore PII-shaped entropy only for a schema-named, full SHA-256 value."""

    if field_name is None:
        return False
    is_digest_field = field_name.endswith("_sha256") or field_name == "request_fingerprint"
    return is_digest_field and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _scan_sensitive_text(text: str, issues: set[str]) -> None:
    for code, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            issues.add(code)
