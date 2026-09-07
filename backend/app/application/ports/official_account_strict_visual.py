"""Closed durable strict-image subjects; never prompt prose or provider bodies."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from app.application.ports.image_validation import ImageQualityAuditResult
from app.domain.official_account_local import fingerprint
from app.domain.official_account_visual_pipeline import STRICT_VISUAL_AUDIT_RUBRIC_VERSION

if TYPE_CHECKING:
    from app.application.ports.official_account_local import (
        ClaimedOfficialAccountRun,
        OfficialAccountGeneratedVisualPlan,
        StoredOfficialAccountGeneratedVisual,
    )

STRICT_AUDIT_PROMPT_VERSION = "official-account-strict-image-audit-v1"
STRICT_AUDIT_RUBRIC_VERSION = STRICT_VISUAL_AUDIT_RUBRIC_VERSION
STRICT_AUDIT_ROUTE = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


@dataclass(frozen=True, slots=True)
class StrictVisualAuditSubject:
    run_id: UUID
    article_version_id: UUID
    render_version_id: UUID
    role: Literal["body", "cover"]
    ordinal: int
    generated_visual_id: UUID
    generated_plan_request_fingerprint: str
    reference_asset_ref: str
    reference_publication_sha256: str
    publication_sha256: str
    upload_sha256: str
    upload_policy_version: str
    media_type: str
    byte_size: int
    width: int
    height: int
    criteria_fingerprint: str
    perceptual_hash: str
    catalog_perceptual_hashes: tuple[str, ...]
    provider: Literal["zhipu"] = "zhipu"
    model: Literal["glm-5v-turbo"] = "glm-5v-turbo"
    route: str = STRICT_AUDIT_ROUTE
    prompt_version: str = STRICT_AUDIT_PROMPT_VERSION
    rubric_version: str = STRICT_AUDIT_RUBRIC_VERSION

    def __post_init__(self) -> None:
        if any(
            type(value) is not int
            for value in (self.ordinal, self.byte_size, self.width, self.height)
        ):
            raise ValueError("strict visual subject numeric fields are invalid")
        if any(
            not isinstance(value, UUID)
            for value in (
                self.run_id,
                self.article_version_id,
                self.render_version_id,
                self.generated_visual_id,
            )
        ):
            raise ValueError("strict visual subject relational identities are invalid")
        for value in (
            self.generated_plan_request_fingerprint,
            self.reference_publication_sha256,
            self.publication_sha256,
            self.upload_sha256,
            self.criteria_fingerprint,
        ):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("strict visual subject checksum is invalid")
        if (
            self.role not in {"body", "cover"}
            or not 0 <= self.ordinal <= (4 if self.role == "body" else 0)
            or self.provider != "zhipu"
            or self.model != "glm-5v-turbo"
            or self.route != STRICT_AUDIT_ROUTE
            or self.prompt_version != STRICT_AUDIT_PROMPT_VERSION
            or self.rubric_version != STRICT_AUDIT_RUBRIC_VERSION
            or self.media_type != "image/jpeg"
            or not 1 <= self.byte_size < 1024 * 1024
            or not 1 <= self.width <= 1536
            or not 1 <= self.height <= 1024
            or not 1 <= len(self.catalog_perceptual_hashes) <= 41
            or tuple(sorted(set(self.catalog_perceptual_hashes))) != self.catalog_perceptual_hashes
            or any(
                len(h) != 16 or any(c not in "0123456789abcdef" for c in h)
                for h in (self.perceptual_hash, *self.catalog_perceptual_hashes)
            )
        ):
            raise ValueError("strict visual subject identity is invalid")

    @property
    def request_fingerprint(self) -> str:
        return fingerprint("official-account-strict-visual-audit-request-v1", asdict(self))


@dataclass(frozen=True, slots=True)
class StoredStrictVisualAudit:
    id: UUID
    subject: StrictVisualAuditSubject
    status: Literal["calling", "accepted", "rejected", "unavailable", "result_unknown"]
    issue_codes: tuple[str, ...]
    record_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class StrictVisualAuditClaim:
    outcome: Literal["newly_claimed", "in_flight", "completed", "result_unknown", "lease_lost"]
    audit: StoredStrictVisualAudit | None


@dataclass(frozen=True, slots=True)
class StrictGeneratedVisualClaim:
    outcome: Literal["newly_claimed", "in_flight", "completed", "result_unknown", "lease_lost"]
    visual: StoredOfficialAccountGeneratedVisual | None


@dataclass(frozen=True, slots=True)
class StrictVisualMediaEvidence:
    role: Literal["body", "cover"]
    ordinal: int
    generated_visual_id: UUID
    generated_plan_request_fingerprint: str
    reference_asset_ref: str
    reference_publication_sha256: str
    publication_sha256: str
    upload_sha256: str
    upload_policy_version: str
    media_type: str
    byte_size: int
    width: int
    height: int
    audit_id: UUID
    audit_request_fingerprint: str
    audit_record_fingerprint: str
    provider: str
    model: str
    plan_version: str
    prompt_version: str
    native_output_size: str


def strict_audit_record_fingerprint(
    subject: StrictVisualAuditSubject, status: str, issue_codes: tuple[str, ...]
) -> str:
    return fingerprint(
        "official-account-strict-visual-audit-record-v1",
        subject.request_fingerprint,
        status,
        issue_codes,
    )


def strict_visual_derivative_descriptor(subject: StrictVisualAuditSubject) -> dict[str, object]:
    return {
        "kind": "generated-cover-upload-v1"
        if subject.role == "cover"
        else "generated-body-upload-v1",
        "parent_generated_visual_id": str(subject.generated_visual_id),
        "publication_sha256": subject.publication_sha256,
        "upload_sha256": subject.upload_sha256,
        "policy_version": subject.upload_policy_version,
        "width": subject.width,
        "height": subject.height,
        "audit_request_fingerprint": subject.request_fingerprint,
    }


class StrictVisualRepository(Protocol):
    async def claim_strict_generated_visual(
        self, *, claimed: ClaimedOfficialAccountRun, plan: OfficialAccountGeneratedVisualPlan
    ) -> StrictGeneratedVisualClaim: ...

    async def claim_strict_visual_audit(
        self, *, claimed: ClaimedOfficialAccountRun, subject: StrictVisualAuditSubject
    ) -> StrictVisualAuditClaim: ...

    async def complete_strict_visual_audit(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        subject: StrictVisualAuditSubject,
        status: Literal["accepted", "rejected", "unavailable", "result_unknown"],
        issue_codes: tuple[str, ...],
        result: ImageQualityAuditResult | None = None,
    ) -> StoredStrictVisualAudit | None: ...

    async def load_strict_visual_evidence(
        self, run_id: UUID
    ) -> tuple[StrictVisualMediaEvidence, ...]: ...
