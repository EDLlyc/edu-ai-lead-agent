"""Closed durable strict-image subjects; never prompt prose or provider bodies."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal, Protocol
from uuid import UUID

from app.application.ports.image_validation import ImageQualityAuditResult
from app.core.errors import ImageGenerationFailure
from app.domain.official_account_local import fingerprint
from app.domain.official_account_visual_pipeline import (
    RESILIENT_VISUAL_PIPELINE_VERSION,
    STRICT_VISUAL_AUDIT_RUBRIC_VERSION,
    TOLERANT_VISUAL_PIPELINE_VERSION,
)

if TYPE_CHECKING:
    from app.application.ports.official_account_local import (
        ClaimedOfficialAccountRun,
        OfficialAccountGeneratedVisualPlan,
        StoredOfficialAccountGeneratedVisual,
    )

STRICT_AUDIT_PROMPT_VERSION = "official-account-strict-image-audit-v1"
STRICT_AUDIT_RUBRIC_VERSION = STRICT_VISUAL_AUDIT_RUBRIC_VERSION
STRICT_AUDIT_ROUTE = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS = 3


def resilient_visual_provider_request_fingerprint(
    logical_request_fingerprint: str,
    physical_attempt_number: int,
    *,
    policy: object = RESILIENT_VISUAL_PIPELINE_VERSION,
) -> str:
    if (
        len(logical_request_fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in logical_request_fingerprint)
        or not 1 <= physical_attempt_number <= RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS
        or policy not in {RESILIENT_VISUAL_PIPELINE_VERSION, TOLERANT_VISUAL_PIPELINE_VERSION}
    ):
        raise ValueError("resilient visual physical attempt identity is invalid")
    return fingerprint(
        "official-account-resilient-visual-physical-attempt-v1",
        policy,
        logical_request_fingerprint,
        physical_attempt_number,
    )


def resilient_visual_attempt_ordinal(slot_ordinal: int, physical_attempt_number: int) -> int:
    if (
        not 0 <= slot_ordinal <= 4
        or not 1 <= physical_attempt_number <= RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS
    ):
        raise ValueError("resilient visual attempt ordinal is invalid")
    # Deliberately disjoint from legacy run-attempt ordinals (10..64).
    return (
        101 + slot_ordinal * RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS + (physical_attempt_number - 1)
    )


def resilient_visual_failure_retries(diagnostic: ImageGenerationFailure) -> bool:
    """V3 retries provider/output ambiguity, never local/configuration/identity failures."""
    return diagnostic.reason != "lease_authority_lost" and diagnostic.error_code not in {
        "provider_authentication_failed",
        "provider_input_limit",
        "provider_identity_mismatch",
        "image_provider_not_configured",
    }


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


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveVisualAuditSubject(StrictVisualAuditSubject):
    """Additional exact-copy proof; the frozen strict subject is not reserialized."""

    catalog_publication_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        StrictVisualAuditSubject.__post_init__(self)
        values = self.catalog_publication_sha256s
        if (
            not 1 <= len(values) <= 41
            or tuple(sorted(set(values))) != values
            or self.reference_publication_sha256 not in values
            or any(
                len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
                for value in values
            )
        ):
            raise ValueError("observe catalog checksum set is invalid")


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
    # A one-time authorized compensation is a new physical request, not a logical plan change.
    provider_request_fingerprint: str | None = None
    physical_attempt_number: int | None = None
    # The normal run policy is frozen. A narrowly authorized recovery may opt into a
    # bounded decoder policy for this one physical call without changing its plan.
    output_geometry_policy: Literal["exact", "native-tolerant-v1"] = "exact"


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


@dataclass(frozen=True, slots=True, kw_only=True)
class ObserveVisualMediaEvidence(StrictVisualMediaEvidence):
    audit_status: Literal["accepted", "rejected", "unavailable", "result_unknown"]
    audit_issue_codes: tuple[str, ...]
    audit_subject: ObserveVisualAuditSubject
    quality_issue_codes: tuple[str, ...]


def observe_quality_issue_codes(
    subject: ObserveVisualAuditSubject, bodies: tuple[StrictVisualAuditSubject, ...]
) -> tuple[str, ...]:
    """Recompute observations from immutable subjects, never an accepted flag."""
    if subject.role == "cover":
        return ()
    threshold = 6
    codes = []
    if any(
        (int(subject.perceptual_hash, 16) ^ int(other, 16)).bit_count() <= threshold
        for other in subject.catalog_perceptual_hashes
    ):
        codes.append("strict_visual_catalog_reuse")
    if any(
        (int(subject.perceptual_hash, 16) ^ int(other.perceptual_hash, 16)).bit_count() <= threshold
        for other in bodies
        if other.ordinal < subject.ordinal
    ):
        codes.append("strict_visual_perceptual_repetition")
    return tuple(codes)


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
