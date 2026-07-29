from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_key(*parts: object) -> str:
    normalized = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(normalized.encode()).hexdigest()


def scheduled_instant(business_date: date, timezone: str, hour: int, minute: int) -> datetime:
    return datetime(
        business_date.year,
        business_date.month,
        business_date.day,
        hour,
        minute,
        tzinfo=ZoneInfo(timezone),
    )


def due_business_date(
    now: datetime, *, timezone: str, hour: int, minute: int, catchup_hours: int
) -> date | None:
    local_now = now.astimezone(ZoneInfo(timezone))
    due_at = scheduled_instant(local_now.date(), timezone, hour, minute)
    if local_now < due_at or local_now > due_at + timedelta(hours=catchup_hours):
        return None
    return local_now.date()
