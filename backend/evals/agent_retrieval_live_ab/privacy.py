"""Fail-closed scanner for aggregate-safe Agent retrieval A/B exports."""

from __future__ import annotations

import re

_SECRET_PATTERNS = (
    re.compile(r"(?i)(?:api[_-]?key|appsecret|authorization)\s*[:=]\s*[^\s,]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)(?:postgres(?:ql)?|mysql|redis)\+?[a-z0-9]*://"),
    re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
        r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
    ),
    re.compile(r"/(?:root|home)/[^\s)]+"),
)


class PrivacyScanError(ValueError):
    """An aggregate-safe export contains a prohibited private token."""


def require_aggregate_safe(value: str) -> None:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            raise PrivacyScanError("aggregate report contains a prohibited private token")
