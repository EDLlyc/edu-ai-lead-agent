"""Safe durable state contracts for automated WeChat draft creation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid5

from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_ROLE_ORDER,
    WeeklyArticleRole,
)

WECHAT_DRAFT_JOB_POLICY_VERSION: Final = "wechat-mp-draft-job-v1"
WECHAT_DRAFT_JOB_NAMESPACE: Final = UUID("9be33e75-0df1-4c04-a2c5-4f331df8b68f")
WECHAT_DRAFT_JOB_ITEM_COUNT: Final = 3

_SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SAFE_ERROR = re.compile(r"[a-z][a-z0-9_.:-]{0,79}")
_SAFE_ENDPOINT = re.compile(r"[a-z][a-z0-9_.:-]{0,79}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class WeChatDraftJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYABLE_FAILED = "retryable_failed"
    READY = "ready"
    TERMINAL_FAILED = "terminal_failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class WeChatDraftItemStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYABLE_FAILED = "retryable_failed"
    SUCCEEDED = "succeeded"
    TERMINAL_FAILED = "terminal_failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


class WeChatDraftAttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILED = "retryable_failed"
    TERMINAL_FAILED = "terminal_failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    LEASE_EXPIRED = "lease_expired"


class WeChatDraftJobErrorCode(StrEnum):
    INVALID_CHECKPOINT = "invalid_checkpoint"
    ARTIFACT_CONFLICT = "artifact_conflict"
    LEASE_LOST = "lease_lost"
    LEASE_LOST_AFTER_SIDE_EFFECT = "lease_lost_after_side_effect"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"


class WeChatDraftJobFailure(Exception):
    """Stable repository failure that is safe to surface in worker logs."""

    def __init__(self, error_code: str, *, retryable: bool) -> None:
        _validate_error(error_code)
        super().__init__(error_code)
        self.error_code = error_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class WeChatDraftJobItemInput:
    role: WeeklyArticleRole
    ordinal: int
    source_ref: str
    source_fingerprint: str
    article_fingerprint: str
    content_fingerprint: str
    policy_fingerprint: str

    def __post_init__(self) -> None:
        expected_role = (
            WEEKLY_EDITION_ROLE_ORDER[self.ordinal - 1] if 1 <= self.ordinal <= 3 else None
        )
        if expected_role != self.role.value:
            raise ValueError("WeChat draft item role order changed")
        _validate_ref(self.source_ref, "source reference")
        _validate_sha256(self.source_fingerprint, "source fingerprint")
        _validate_sha256(self.article_fingerprint, "article fingerprint")
        _validate_sha256(self.content_fingerprint, "content fingerprint")
        _validate_sha256(self.policy_fingerprint, "policy fingerprint")


@dataclass(frozen=True, slots=True)
class WeChatDraftJobEnqueue:
    account_fingerprint: str
    aggregate_fingerprint: str
    batch_fingerprint: str
    items: tuple[WeChatDraftJobItemInput, ...]
    max_attempts: int = 3

    def __post_init__(self) -> None:
        _validate_sha256(self.account_fingerprint, "account fingerprint")
        _validate_sha256(self.aggregate_fingerprint, "aggregate fingerprint")
        _validate_sha256(self.batch_fingerprint, "batch fingerprint")
        if len(self.items) != WECHAT_DRAFT_JOB_ITEM_COUNT:
            raise ValueError("WeChat draft enqueue requires exactly three items")
        if tuple(item.ordinal for item in self.items) != (1, 2, 3):
            raise ValueError("WeChat draft enqueue ordinals changed")
        if tuple(item.role.value for item in self.items) != WEEKLY_EDITION_ROLE_ORDER:
            raise ValueError("WeChat draft enqueue role order changed")
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("WeChat draft max attempts must be between 1 and 10")

    @property
    def request_fingerprint(self) -> str:
        return wechat_draft_request_fingerprint(
            account_fingerprint=self.account_fingerprint,
            aggregate_fingerprint=self.aggregate_fingerprint,
            batch_fingerprint=self.batch_fingerprint,
            items=self.items,
        )

    @property
    def job_id(self) -> UUID:
        return wechat_draft_job_id(self.request_fingerprint)


@dataclass(frozen=True, slots=True)
class WeChatDraftJobSnapshot:
    job_id: UUID
    request_fingerprint: str
    account_fingerprint: str
    aggregate_fingerprint: str
    batch_fingerprint: str
    policy_version: str
    status: WeChatDraftJobStatus
    attempt_count: int
    max_attempts: int
    fencing_token: int
    available_at: datetime
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_fingerprint, "request fingerprint"),
            (self.account_fingerprint, "account fingerprint"),
            (self.aggregate_fingerprint, "aggregate fingerprint"),
            (self.batch_fingerprint, "batch fingerprint"),
        ):
            _validate_sha256(value, label)
        if self.policy_version != WECHAT_DRAFT_JOB_POLICY_VERSION:
            raise ValueError("WeChat draft job policy version changed")
        if not (0 <= self.attempt_count <= self.max_attempts * WECHAT_DRAFT_JOB_ITEM_COUNT):
            raise ValueError("WeChat draft job attempt count is invalid")
        if not 1 <= self.max_attempts <= 10 or self.fencing_token < 0:
            raise ValueError("WeChat draft job retry or fencing state is invalid")
        if self.error_code is not None:
            _validate_error(self.error_code)
        _validate_aware(self.available_at, "available_at")
        _validate_aware(self.created_at, "created_at")
        _validate_aware(self.updated_at, "updated_at")
        if self.completed_at is not None:
            _validate_aware(self.completed_at, "completed_at")


@dataclass(frozen=True, slots=True)
class WeChatDraftItemSnapshot:
    job_id: UUID
    role: WeeklyArticleRole
    ordinal: int
    source_ref: str
    source_fingerprint: str
    article_fingerprint: str
    content_fingerprint: str
    policy_fingerprint: str
    status: WeChatDraftItemStatus
    attempt_count: int
    side_effect_started_at: datetime | None
    endpoint: str | None
    uploaded_image_count: int
    draft_media_fingerprint: str | None
    error_code: str | None
    started_at: datetime | None
    completed_at: datetime | None

    def __post_init__(self) -> None:
        WeChatDraftJobItemInput(
            role=self.role,
            ordinal=self.ordinal,
            source_ref=self.source_ref,
            source_fingerprint=self.source_fingerprint,
            article_fingerprint=self.article_fingerprint,
            content_fingerprint=self.content_fingerprint,
            policy_fingerprint=self.policy_fingerprint,
        )
        if self.attempt_count < 0 or self.uploaded_image_count < 0:
            raise ValueError("WeChat draft item counters must be non-negative")
        if self.endpoint is not None:
            _validate_endpoint(self.endpoint)
        if self.draft_media_fingerprint is not None:
            _validate_sha256(self.draft_media_fingerprint, "draft media fingerprint")
        if self.error_code is not None:
            _validate_error(self.error_code)
        for value, label in (
            (self.side_effect_started_at, "side_effect_started_at"),
            (self.started_at, "started_at"),
            (self.completed_at, "completed_at"),
        ):
            if value is not None:
                _validate_aware(value, label)
        if self.status is WeChatDraftItemStatus.SUCCEEDED and (
            self.draft_media_fingerprint is None
            or self.side_effect_started_at is None
            or self.completed_at is None
        ):
            raise ValueError("successful WeChat draft item checkpoint is incomplete")


@dataclass(frozen=True, slots=True)
class WeChatDraftJobClaim:
    job: WeChatDraftJobSnapshot
    item: WeChatDraftItemSnapshot
    worker_id: str
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        _validate_ref(self.worker_id, "worker ID")
        _validate_aware(self.lease_expires_at, "lease expiry")
        if self.job.status is not WeChatDraftJobStatus.RUNNING:
            raise ValueError("WeChat draft claim must own a running job")
        if self.item.status is not WeChatDraftItemStatus.RUNNING:
            raise ValueError("WeChat draft claim must own a running item")
        if self.item.job_id != self.job.job_id:
            raise ValueError("WeChat draft claim contains a cross-job item")
        if self.item.attempt_count <= 0 or self.job.fencing_token <= 0:
            raise ValueError("WeChat draft claim identity is incomplete")


@dataclass(frozen=True, slots=True)
class WeChatDraftStatusProjection:
    job: WeChatDraftJobSnapshot
    items: tuple[WeChatDraftItemSnapshot, ...]

    def __post_init__(self) -> None:
        if len(self.items) != WECHAT_DRAFT_JOB_ITEM_COUNT:
            raise ValueError("WeChat draft status requires exactly three items")
        if tuple(item.ordinal for item in self.items) != (1, 2, 3):
            raise ValueError("WeChat draft status item order changed")
        if tuple(item.role.value for item in self.items) != WEEKLY_EDITION_ROLE_ORDER:
            raise ValueError("WeChat draft status role order changed")
        if any(item.job_id != self.job.job_id for item in self.items):
            raise ValueError("WeChat draft status contains a cross-job item")

    def as_dict(self) -> dict[str, object]:
        """Return a safe operator projection with no path, content, credential, or media ID."""
        return {
            "job_id": str(self.job.job_id),
            "request_fingerprint": self.job.request_fingerprint,
            "batch_fingerprint": self.job.batch_fingerprint,
            "status": self.job.status.value,
            "attempt_count": self.job.attempt_count,
            "max_attempts_per_item": self.job.max_attempts,
            "error_code": self.job.error_code,
            "created_at": self.job.created_at.isoformat(),
            "updated_at": self.job.updated_at.isoformat(),
            "completed_at": (
                self.job.completed_at.isoformat() if self.job.completed_at is not None else None
            ),
            "items": [
                {
                    "role": item.role.value,
                    "ordinal": item.ordinal,
                    "status": item.status.value,
                    "attempt_count": item.attempt_count,
                    "endpoint": item.endpoint,
                    "uploaded_image_count": item.uploaded_image_count,
                    "draft_created": item.draft_media_fingerprint is not None,
                    "error_code": item.error_code,
                    "started_at": item.started_at.isoformat() if item.started_at else None,
                    "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                }
                for item in self.items
            ],
        }


def wechat_draft_account_fingerprint(app_id: str) -> str:
    if not app_id or app_id != app_id.strip() or any(char.isspace() for char in app_id):
        raise ValueError("WeChat AppID must be a non-blank normalized value")
    if any(ord(char) < 32 or ord(char) == 127 for char in app_id):
        raise ValueError("WeChat AppID contains control characters")
    # AppID is an opaque provider identity, not user-facing text. Preserve its
    # exact normalized bytes so two case-distinct provider accounts can never
    # share one durable idempotency lane.
    return _fingerprint("wechat-mp-account-v1", app_id)


def wechat_draft_policy_fingerprint(
    *,
    content_source_url: str | None,
    need_open_comment: bool,
    only_fans_can_comment: bool,
) -> str:
    if only_fans_can_comment and not need_open_comment:
        raise ValueError("fan-only comments require comments to be enabled")
    return _fingerprint(
        "wechat-mp-draft-item-policy-v1",
        content_source_url,
        need_open_comment,
        only_fans_can_comment,
    )


def wechat_draft_request_fingerprint(
    *,
    account_fingerprint: str,
    aggregate_fingerprint: str,
    batch_fingerprint: str,
    items: tuple[WeChatDraftJobItemInput, ...],
) -> str:
    _validate_sha256(account_fingerprint, "account fingerprint")
    _validate_sha256(aggregate_fingerprint, "aggregate fingerprint")
    _validate_sha256(batch_fingerprint, "batch fingerprint")
    if tuple(item.role.value for item in items) != WEEKLY_EDITION_ROLE_ORDER:
        raise ValueError("WeChat draft request roles changed")
    return _fingerprint(
        WECHAT_DRAFT_JOB_POLICY_VERSION,
        account_fingerprint,
        aggregate_fingerprint,
        batch_fingerprint,
        tuple(
            (
                item.role.value,
                item.ordinal,
                item.source_fingerprint,
                item.article_fingerprint,
                item.content_fingerprint,
                item.policy_fingerprint,
            )
            for item in items
        ),
    )


def wechat_draft_job_id(request_fingerprint: str) -> UUID:
    _validate_sha256(request_fingerprint, "request fingerprint")
    return uuid5(WECHAT_DRAFT_JOB_NAMESPACE, request_fingerprint)


def draft_media_fingerprint(media_id: str) -> str:
    if not media_id or media_id != media_id.strip():
        raise ValueError("WeChat draft media ID must be non-blank and normalized")
    return _fingerprint("wechat-mp-draft-media-v1", media_id)


def validate_error_code(error_code: str) -> None:
    _validate_error(error_code)


def validate_endpoint(endpoint: str) -> None:
    _validate_endpoint(endpoint)


def _fingerprint(*parts: object) -> str:
    body = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()


def _validate_ref(value: str, label: str) -> None:
    if _SAFE_REF.fullmatch(value) is None:
        raise ValueError(f"WeChat draft {label} is invalid")


def _validate_sha256(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"WeChat draft {label} must be lowercase SHA-256")


def _validate_error(error_code: str) -> None:
    if _SAFE_ERROR.fullmatch(error_code) is None:
        raise ValueError("WeChat draft error code is invalid")


def _validate_endpoint(endpoint: str) -> None:
    if _SAFE_ENDPOINT.fullmatch(endpoint) is None:
        raise ValueError("WeChat draft endpoint is invalid")


def _validate_aware(value: datetime, label: str) -> None:
    if value.utcoffset() is None:
        raise ValueError(f"WeChat draft {label} must be timezone-aware")
