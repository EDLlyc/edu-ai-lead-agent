"""Safe identities for immutable WeChat draft-source artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

from app.application.ports.wechat_official_account import WeChatDraftRole
from app.domain.official_account_weekly_edition import WEEKLY_EDITION_ROLE_ORDER

WECHAT_DRAFT_ARTIFACT_REF_VERSION: Final = "wechat-draft-v1"
WECHAT_DRAFT_PREPARED_ARTIFACT_REF_VERSION: Final = "wechat-draft-prepared-v1"
WECHAT_DRAFT_ARTIFACT_INVALID: Final = "wechat_mp_draft_artifact_invalid"
WECHAT_DRAFT_BEFORE_ACTIVATION: Final = "wechat_mp_draft_before_activation"


class WeChatDraftArtifactError(ValueError):
    code: Final = WECHAT_DRAFT_ARTIFACT_INVALID


class WeChatDraftBeforeActivationError(ValueError):
    """Stable rejection for a valid aggregate outside the production eligibility window."""

    code: Final = WECHAT_DRAFT_BEFORE_ACTIVATION


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class WeChatDraftArtifactSource:
    """Database-safe identity for one staged weekly child."""

    role: WeChatDraftRole
    ordinal: int
    source_ref: str
    source_fingerprint: str
    article_fingerprint: str
    content_fingerprint: str
    child_zip_sha256: str

    def __post_init__(self) -> None:
        expected_role = (
            WEEKLY_EDITION_ROLE_ORDER[self.ordinal - 1] if 1 <= self.ordinal <= 3 else None
        )
        parts = self.source_ref.split(":")
        expected_ref = (
            f"{parts[0]}:{parts[1]}:{self.role}"
            if len(parts) == 3
            and parts[0]
            in {
                WECHAT_DRAFT_ARTIFACT_REF_VERSION,
                WECHAT_DRAFT_PREPARED_ARTIFACT_REF_VERSION,
            }
            else None
        )
        if (
            expected_role != self.role
            or self.source_ref != expected_ref
            or len(self.source_ref) > 128
        ):
            raise ValueError("WeChat draft artifact source identity is invalid")
        aggregate_fingerprint = parts[1]
        if not _is_sha256(aggregate_fingerprint) or any(
            not _is_sha256(value)
            for value in (
                self.source_fingerprint,
                self.article_fingerprint,
                self.content_fingerprint,
                self.child_zip_sha256,
            )
        ):
            raise ValueError("WeChat draft artifact source fingerprints are invalid")


@dataclass(frozen=True, slots=True)
class WeChatDraftArtifactBatch:
    """Safe staged aggregate projection used to build a durable enqueue request."""

    week_start: str
    batch_fingerprint: str
    aggregate_fingerprint: str
    sources: tuple[
        WeChatDraftArtifactSource,
        WeChatDraftArtifactSource,
        WeChatDraftArtifactSource,
    ]

    def __post_init__(self) -> None:
        try:
            week_start = date.fromisoformat(self.week_start)
        except ValueError as exc:
            raise ValueError("WeChat draft artifact week_start is invalid") from exc
        if week_start.weekday() != 0:
            raise ValueError("WeChat draft artifact week_start must be a Monday")
        if not _is_sha256(self.batch_fingerprint) or not _is_sha256(self.aggregate_fingerprint):
            raise ValueError("WeChat draft artifact batch fingerprints are invalid")
        if tuple(source.role for source in self.sources) != WEEKLY_EDITION_ROLE_ORDER:
            raise ValueError("WeChat draft artifact batch role order changed")
        if tuple(source.ordinal for source in self.sources) != (1, 2, 3):
            raise ValueError("WeChat draft artifact batch ordinals changed")
        ref_versions = {source.source_ref.split(":", 1)[0] for source in self.sources}
        if len(ref_versions) != 1 or ref_versions.pop() not in {
            WECHAT_DRAFT_ARTIFACT_REF_VERSION,
            WECHAT_DRAFT_PREPARED_ARTIFACT_REF_VERSION,
        }:
            raise ValueError("WeChat draft artifact reference version changed")
        if any(
            source.source_ref.split(":")[1] != self.aggregate_fingerprint for source in self.sources
        ):
            raise ValueError("WeChat draft artifact aggregate binding changed")


@dataclass(frozen=True, slots=True)
class ResolvedWeChatDraftArtifactSource:
    """Runtime-only source; the private directory must never be persisted or logged."""

    directory: Path = field(repr=False)
    source: WeChatDraftArtifactSource
    batch_fingerprint: str
    aggregate_fingerprint: str

    def __post_init__(self) -> None:
        if not self.directory.is_absolute():
            raise ValueError("resolved WeChat draft artifact directory must be absolute")
        if not _is_sha256(self.batch_fingerprint) or not _is_sha256(self.aggregate_fingerprint):
            raise ValueError("resolved WeChat draft artifact identity is invalid")
        parts = self.source.source_ref.split(":")
        if len(parts) != 3 or parts[1] != self.aggregate_fingerprint:
            raise ValueError("resolved WeChat draft artifact binding changed")


@dataclass(frozen=True, slots=True)
class WeChatDraftArtifactDiscovery:
    """Path-free bounded discovery result for automatic reconciliation."""

    batches: tuple[WeChatDraftArtifactBatch, ...]
    skipped_by_code: Mapping[str, int]

    def __post_init__(self) -> None:
        if any(not code or count < 1 for code, count in self.skipped_by_code.items()):
            raise ValueError("WeChat draft artifact discovery diagnostics are invalid")
        if len({batch.aggregate_fingerprint for batch in self.batches}) != len(self.batches):
            raise ValueError("WeChat draft artifact discovery batches must be unique")
        object.__setattr__(
            self,
            "skipped_by_code",
            MappingProxyType(dict(sorted(self.skipped_by_code.items()))),
        )


class WeChatDraftArtifactStore(Protocol):
    def stage_weekly(self, source_directory: Path) -> WeChatDraftArtifactBatch: ...

    def resolve(self, source_ref: str) -> ResolvedWeChatDraftArtifactSource: ...

    def discover_weekly(self, *, maximum: int = 100) -> WeChatDraftArtifactDiscovery: ...


__all__ = [
    "WECHAT_DRAFT_ARTIFACT_INVALID",
    "WECHAT_DRAFT_ARTIFACT_REF_VERSION",
    "WECHAT_DRAFT_BEFORE_ACTIVATION",
    "WECHAT_DRAFT_PREPARED_ARTIFACT_REF_VERSION",
    "ResolvedWeChatDraftArtifactSource",
    "WeChatDraftArtifactBatch",
    "WeChatDraftArtifactDiscovery",
    "WeChatDraftArtifactError",
    "WeChatDraftArtifactSource",
    "WeChatDraftArtifactStore",
    "WeChatDraftBeforeActivationError",
]
