"""Bounded privacy scans for private panel evidence and public safe reports."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum

from pydantic import BaseModel

from .models import canonical_json_bytes

MAX_PRIVACY_SCAN_BYTES = 4 * 1024 * 1024


class PrivacyProfile(StrEnum):
    PRIVATE_EVIDENCE = "private_evidence"
    SAFE_REPORT = "safe_report"


class ModelPanelPrivacyError(ValueError):
    """Evidence contains forbidden content, credentials, PII, or unsafe paths."""


_ALWAYS_PROHIBITED_KEYS = frozenset(
    {
        "api_key",
        "authorization_header",
        "bearer_token",
        "chain_of_thought",
        "cookie",
        "credential",
        "password",
        "private_key",
        "refresh_token",
        "prompt",
        "provider_body",
        "provider_response",
        "raw_prompt",
        "reasoning",
        "secret",
        "access_token",
    }
)
_SAFE_REPORT_PROHIBITED_KEYS = _ALWAYS_PROHIBITED_KEYS | {
    "article_text",
    "content",
    "filename",
    "object_key",
    "private_path",
    "raw_body",
    "source_path",
    "user_id",
}
_SENSITIVE_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE)),
    (
        "bearer_token",
        re.compile(r"(?:authorization\s*:\s*)?bearer\s+[A-Za-z0-9._~+\/-]{8,}", re.IGNORECASE),
    ),
    ("provider_key", re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_-]{12,}\b", re.IGNORECASE)),
    ("github_token", re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack_token", re.compile(r"\bxox[a-z]-[A-Za-z0-9-]{12,}\b", re.IGNORECASE)),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    ("api_key_assignment", re.compile(r"\b[A-Z0-9_]*API_KEY\s*=", re.IGNORECASE)),
    ("database_url", re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb)://", re.IGNORECASE)),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("mainland_phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("identity_number", re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")),
    (
        "private_path",
        re.compile(
            r"(?:(?<![A-Za-z0-9])/(?:etc|home|root|tmp|Users|var|workspace)/|"
            r"[A-Z]:\\Users\\|(?:^|[\s\"'])private[/\\])",
            re.IGNORECASE,
        ),
    ),
    ("query_url", re.compile(r"https?://[^\s?#]+\?[^\s]+", re.IGNORECASE)),
    ("data_url", re.compile(r"data:[^;,]+;base64,", re.IGNORECASE)),
)
_SAFE_REPORT_PATTERNS = (
    (
        "raw_uuid",
        re.compile(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "untrusted_instruction",
        re.compile(
            r"\b(?:ignore|disregard) (?:all |the )?(?:previous|prior) instructions\b",
            re.IGNORECASE,
        ),
    ),
)

_OPAQUE_HASH_REFERENCE_PATTERNS = {
    "attempt_ref": re.compile(r"attempt-[0-9a-f]{32}"),
    "pair_ref": re.compile(r"pair-[0-9a-f]{28}"),
    "blind_a_ref": re.compile(r"blind-[0-9a-f]{32}"),
    "blind_b_ref": re.compile(r"blind-[0-9a-f]{32}"),
    "artifact_ref": re.compile(r"(?:img|imgblind)-[0-9a-f]{28,32}"),
}


def scan_privacy(
    value: object,
    *,
    profile: PrivacyProfile,
) -> tuple[str, ...]:
    """Return sorted stable issue codes; an empty tuple is a passing scan."""

    try:
        payload = canonical_json_bytes(value)
    except (TypeError, ValueError):
        return ("unserializable_artifact",)
    if len(payload) > MAX_PRIVACY_SCAN_BYTES:
        return ("artifact_too_large",)
    issues: set[str] = set()
    _scan_value(value, issues, field_name=None, profile=profile)
    return tuple(sorted(issues))


def require_privacy_safe(value: object, *, profile: PrivacyProfile) -> None:
    issues = scan_privacy(value, profile=profile)
    if issues:
        raise ModelPanelPrivacyError("privacy_scan_failed:" + ",".join(issues))


def _scan_value(
    value: object,
    issues: set[str],
    *,
    field_name: str | None,
    profile: PrivacyProfile,
) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        prohibited = (
            _SAFE_REPORT_PROHIBITED_KEYS
            if profile is PrivacyProfile.SAFE_REPORT
            else _ALWAYS_PROHIBITED_KEYS
        )
        for key, child in value.items():
            normalized = _normalize_key(str(key))
            path_key = normalized == "path" or normalized.endswith("_path")
            digest_value = isinstance(child, str) and _is_opaque_digest(normalized, child)
            if not digest_value and (
                _is_prohibited_key(normalized, prohibited=prohibited, profile=profile)
                or (profile is PrivacyProfile.SAFE_REPORT and path_key)
            ):
                issues.add(f"prohibited_key:{normalized}")
            _scan_text(str(key), issues, profile=profile)
            _scan_value(child, issues, field_name=normalized, profile=profile)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _scan_value(child, issues, field_name=field_name, profile=profile)
        return
    if isinstance(value, str) and not _is_opaque_digest(field_name, value):
        _scan_text(value, issues, profile=profile)


def _is_opaque_digest(field_name: str | None, value: str) -> bool:
    if field_name is None:
        return False
    digest_field = field_name in {"sha256", "fingerprint"} or field_name.endswith(
        ("_sha256", "_fingerprint", "_fingerprints")
    )
    if digest_field and re.fullmatch(r"[0-9a-f]{64}", value) is not None:
        return True
    reference_pattern = _OPAQUE_HASH_REFERENCE_PATTERNS.get(field_name)
    return reference_pattern is not None and reference_pattern.fullmatch(value) is not None


def _normalize_key(value: str) -> str:
    snake_case = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value.strip())
    snake_case = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", snake_case)
    return re.sub(r"[^a-z0-9]+", "_", snake_case.lower()).strip("_")


def _is_prohibited_key(
    normalized: str,
    *,
    prohibited: frozenset[str],
    profile: PrivacyProfile,
) -> bool:
    if normalized in prohibited:
        return True
    padded = f"_{normalized}_"
    credential_fragments = (
        "api_key",
        "access_token",
        "authorization_header",
        "bearer_token",
        "chain_of_thought",
        "credential",
        "password",
        "private_key",
        "provider_body",
        "provider_response",
        "raw_prompt",
        "refresh_token",
        "secret",
    )
    if any(f"_{fragment}_" in padded for fragment in credential_fragments):
        return True
    if profile is PrivacyProfile.SAFE_REPORT:
        safe_report_fragments = (
            "article_text",
            "candidate_a_text",
            "candidate_b_text",
            "candidate_text",
            "image_bytes",
            "private_path",
            "raw_body",
            "source_path",
            "user_id",
        )
        if any(f"_{fragment}_" in padded for fragment in safe_report_fragments):
            return True
        if normalized.endswith(("_filename", "_object_key")):
            return True
        if normalized.endswith(("_prompt", "_prompt_text")):
            return True
    return False


def _scan_text(text: str, issues: set[str], *, profile: PrivacyProfile) -> None:
    for code, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            issues.add(code)
    if profile is PrivacyProfile.SAFE_REPORT:
        for code, pattern in _SAFE_REPORT_PATTERNS:
            if pattern.search(text):
                issues.add(code)
