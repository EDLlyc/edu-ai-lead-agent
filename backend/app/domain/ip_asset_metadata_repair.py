from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.ip_assets import (
    IP_ASSET_MAX_FREE_TAGS,
    IpAssetCharacter,
    IpAssetMetadata,
    IpAssetType,
)

IP_ASSET_METADATA_REPAIR_MODEL: Literal["glm-5v-turbo"] = "glm-5v-turbo"
IP_ASSET_METADATA_REPAIR_CANARY_SCHEMA_VERSION: Literal["ip-asset-metadata-repair-canary-v2"] = (
    "ip-asset-metadata-repair-canary-v2"
)
IP_ASSET_METADATA_REPAIR_PLAN_SCHEMA_VERSION: Literal["ip-asset-metadata-repair-plan-v2"] = (
    "ip-asset-metadata-repair-plan-v2"
)
IP_ASSET_METADATA_REPAIR_RESULT_SCHEMA_VERSION: Literal["ip-asset-metadata-repair-result-v2"] = (
    "ip-asset-metadata-repair-result-v2"
)
IP_ASSET_METADATA_REPAIR_POLICY_VERSION: Literal["ip-asset-metadata-repair-v1"] = (
    "ip-asset-metadata-repair-v1"
)
IP_ASSET_METADATA_REPAIR_ACKNOWLEDGEMENT = "I_ACKNOWLEDGE_LOCAL_IP_METADATA_REPAIR_V2"
IP_ASSET_METADATA_REPAIR_MAX_ASSETS = 41
IP_ASSET_METADATA_REPAIR_DEFAULT_PACING_SECONDS: Final[float] = 2.0
IP_ASSET_METADATA_REPAIR_MIN_PACING_SECONDS: Final[float] = 0.5
IP_ASSET_METADATA_REPAIR_MAX_PACING_SECONDS: Final[float] = 60.0

_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_ASSET_REF_PATTERN = r"^ipa_[a-f0-9]{20}$"
_RAW_DIGEST_IN_TEXT = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", re.IGNORECASE)
_UUID_IN_TEXT = re.compile(
    r"(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![0-9a-f])",
    re.IGNORECASE,
)
_PRIVATE_LOCATION_IN_TEXT = re.compile(
    r"(?:data:image/|(?:https?|s3|file)://|(?:^|\s)(?:\.\.?/|~/|/[A-Za-z0-9_.-])|"
    r"[A-Za-z]:\\|ip-assets/originals/|sha256/|\.(?:png|jpe?g|webp)(?:$|\s))",
    re.IGNORECASE,
)
_CREDENTIAL_IN_TEXT = re.compile(
    r"(?:\bBearer\s+[A-Za-z0-9._~+/=-]+|\b(?:api[_ -]?key|secret)[=: ]+\S+|\bsk-[A-Za-z0-9_-]{8,})",
    re.IGNORECASE,
)
IpAssetRepairField: TypeAlias = Literal[
    "character",
    "asset_type",
    "emotion",
    "action",
    "scene",
    "intended_use",
    "style",
    "tags",
]
_REPAIR_FIELDS: tuple[IpAssetRepairField, ...] = (
    "character",
    "asset_type",
    "emotion",
    "action",
    "scene",
    "intended_use",
    "style",
    "tags",
)


class IpAssetMetadataRepairItemStatus(StrEnum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    READ_FAILED = "read_failed"
    INVALID_RASTER = "invalid_raster"
    PROVIDER_FAILED = "provider_failed"
    INVALID_SUGGESTION = "invalid_suggestion"
    NOT_PROCESSED = "not_processed"


class IpAssetMetadataRepairCallStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_CALLED = "not_called"


class IpAssetMetadataRepairErrorCode(StrEnum):
    READ_FAILED = "read_failed"
    INVALID_RASTER = "invalid_raster"
    PROVIDER_AUTHENTICATION_FAILED = "provider_authentication_failed"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_REQUEST_REJECTED = "provider_request_rejected"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_PROVIDER_OUTPUT = "invalid_provider_output"
    PROVIDER_IDENTITY_MISMATCH = "provider_identity_mismatch"
    INVALID_SUGGESTION = "invalid_suggestion"
    NOT_CALLED_AFTER_TRANSIENT_FAILURE = "not_called_after_transient_failure"
    CANARY_FAILED = "canary_failed"


class IpAssetMetadataMutationStatus(StrEnum):
    APPLIED = "applied"
    RESTORED = "restored"
    ALREADY_APPLIED = "already_applied"
    NO_CHANGE_PLANNED = "no_change_planned"
    NOT_PLANNED = "not_planned"
    CONTENT_DRIFT = "content_drift"
    METADATA_DRIFT = "metadata_drift"
    NOT_ELIGIBLE = "not_eligible"
    NOT_FOUND = "not_found"
    MUTATION_FAILED = "mutation_failed"


class IpAssetRepairMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    character: IpAssetCharacter
    asset_type: IpAssetType
    emotion: str = Field(default="", max_length=40)
    action: str = Field(default="", max_length=40)
    scene: str = Field(default="", max_length=60)
    intended_use: str = Field(default="", max_length=60)
    style: str = Field(default="", max_length=40)
    tags: tuple[str, ...] = Field(default_factory=tuple, max_length=IP_ASSET_MAX_FREE_TAGS)

    @model_validator(mode="after")
    def validate_domain_metadata(self) -> IpAssetRepairMetadata:
        normalized = self.to_domain()
        if (
            normalized.character is not self.character
            or normalized.asset_type is not self.asset_type
            or normalized.emotion != self.emotion
            or normalized.action != self.action
            or normalized.scene != self.scene
            or normalized.intended_use != self.intended_use
            or normalized.style != self.style
            or normalized.tags != self.tags
        ):
            raise ValueError("IP asset repair metadata must be canonical")
        for value in (
            self.emotion,
            self.action,
            self.scene,
            self.intended_use,
            self.style,
            *self.tags,
        ):
            if (
                _RAW_DIGEST_IN_TEXT.search(value)
                or _UUID_IN_TEXT.search(value)
                or _PRIVATE_LOCATION_IN_TEXT.search(value)
                or _CREDENTIAL_IN_TEXT.search(value)
            ):
                raise ValueError("IP asset repair metadata contains private artifact data")
        return self

    def to_domain(self, *, department: str = "", contributor: str = "") -> IpAssetMetadata:
        return IpAssetMetadata(
            character=self.character,
            asset_type=self.asset_type,
            department=department,
            contributor=contributor,
            emotion=self.emotion,
            action=self.action,
            scene=self.scene,
            intended_use=self.intended_use,
            style=self.style,
            tags=self.tags,
        )


class IpAssetMetadataRepairPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    asset_ref: str = Field(pattern=_ASSET_REF_PATTERN)
    content_commitment: str = Field(pattern=_DIGEST_PATTERN)
    before_metadata: IpAssetRepairMetadata
    suggestion_metadata: IpAssetRepairMetadata | None = None
    proposed_metadata: IpAssetRepairMetadata | None = None
    before_metadata_fingerprint: str = Field(pattern=_DIGEST_PATTERN)
    proposed_metadata_fingerprint: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    changed_fields: tuple[IpAssetRepairField, ...] = Field(
        default_factory=tuple, max_length=len(_REPAIR_FIELDS)
    )
    status: IpAssetMetadataRepairItemStatus
    error_code: IpAssetMetadataRepairErrorCode | None = None
    provider_call_status: IpAssetMetadataRepairCallStatus

    @model_validator(mode="after")
    def validate_status_shape(self) -> IpAssetMetadataRepairPlanItem:
        expected_call_status = {
            IpAssetMetadataRepairItemStatus.CHANGED: (IpAssetMetadataRepairCallStatus.COMPLETED),
            IpAssetMetadataRepairItemStatus.UNCHANGED: (IpAssetMetadataRepairCallStatus.COMPLETED),
            IpAssetMetadataRepairItemStatus.READ_FAILED: (
                IpAssetMetadataRepairCallStatus.NOT_CALLED
            ),
            IpAssetMetadataRepairItemStatus.INVALID_RASTER: (
                IpAssetMetadataRepairCallStatus.NOT_CALLED
            ),
            IpAssetMetadataRepairItemStatus.PROVIDER_FAILED: (
                IpAssetMetadataRepairCallStatus.FAILED
            ),
            IpAssetMetadataRepairItemStatus.INVALID_SUGGESTION: (
                IpAssetMetadataRepairCallStatus.FAILED
            ),
            IpAssetMetadataRepairItemStatus.NOT_PROCESSED: (
                IpAssetMetadataRepairCallStatus.NOT_CALLED
            ),
        }[self.status]
        if self.provider_call_status is not expected_call_status:
            raise ValueError("IP asset repair call status is inconsistent")
        suggested = self.status in {
            IpAssetMetadataRepairItemStatus.CHANGED,
            IpAssetMetadataRepairItemStatus.UNCHANGED,
        }
        if suggested != (
            self.suggestion_metadata is not None
            and self.proposed_metadata is not None
            and self.proposed_metadata_fingerprint is not None
        ):
            raise ValueError("IP asset repair suggestion shape is inconsistent")
        if suggested == (self.error_code is not None):
            raise ValueError("IP asset repair error shape is inconsistent")
        interrupted = self.status is IpAssetMetadataRepairItemStatus.NOT_PROCESSED
        interrupted_error = (
            self.error_code is IpAssetMetadataRepairErrorCode.NOT_CALLED_AFTER_TRANSIENT_FAILURE
        )
        if interrupted != interrupted_error or (
            interrupted
            and self.provider_call_status is not IpAssetMetadataRepairCallStatus.NOT_CALLED
        ):
            raise ValueError("IP asset repair interrupted-item shape is inconsistent")
        if self.status is IpAssetMetadataRepairItemStatus.CHANGED and not self.changed_fields:
            raise ValueError("changed repair item requires changed fields")
        if self.status is not IpAssetMetadataRepairItemStatus.CHANGED and self.changed_fields:
            raise ValueError("non-changed repair item cannot have changed fields")
        if self.before_metadata_fingerprint != metadata_fingerprint(self.before_metadata):
            raise ValueError("IP asset repair before fingerprint is invalid")
        if self.proposed_metadata is not None and self.proposed_metadata_fingerprint != (
            metadata_fingerprint(self.proposed_metadata)
        ):
            raise ValueError("IP asset repair proposed fingerprint is invalid")
        if self.proposed_metadata is not None:
            actual_changed_fields = changed_fields(self.before_metadata, self.proposed_metadata)
            if self.changed_fields != actual_changed_fields:
                raise ValueError("IP asset repair changed fields are not canonical")
            expected_status = (
                IpAssetMetadataRepairItemStatus.CHANGED
                if actual_changed_fields
                else IpAssetMetadataRepairItemStatus.UNCHANGED
            )
            if self.status is not expected_status:
                raise ValueError("IP asset repair item status does not match its metadata diff")
        return self


class IpAssetMetadataRepairCanary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["ip-asset-metadata-repair-canary-v2"] = (
        IP_ASSET_METADATA_REPAIR_CANARY_SCHEMA_VERSION
    )
    policy_version: Literal["ip-asset-metadata-repair-v1"] = IP_ASSET_METADATA_REPAIR_POLICY_VERSION
    recognition_policy_version: Literal["ip-asset-recognition-v1"] = "ip-asset-recognition-v1"
    review_status: Literal["ai_suggestion_unreviewed"] = "ai_suggestion_unreviewed"
    provider: Literal["zhipu"] = "zhipu"
    model: Literal["glm-5v-turbo"] = IP_ASSET_METADATA_REPAIR_MODEL
    created_at: datetime
    asset_set_fingerprint: str = Field(pattern=_DIGEST_PATTERN)
    provider_call_count: int = Field(ge=0, le=1)
    item: IpAssetMetadataRepairPlanItem
    canary_fingerprint: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_canary(self) -> IpAssetMetadataRepairCanary:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("IP asset repair canary time must be timezone-aware")
        actual_calls = int(
            self.item.provider_call_status is not IpAssetMetadataRepairCallStatus.NOT_CALLED
        )
        if self.provider_call_count != actual_calls:
            raise ValueError("IP asset repair canary call count is inconsistent")
        return self


class IpAssetMetadataRepairPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["ip-asset-metadata-repair-plan-v2"] = (
        IP_ASSET_METADATA_REPAIR_PLAN_SCHEMA_VERSION
    )
    policy_version: Literal["ip-asset-metadata-repair-v1"] = IP_ASSET_METADATA_REPAIR_POLICY_VERSION
    recognition_policy_version: Literal["ip-asset-recognition-v1"] = "ip-asset-recognition-v1"
    review_status: Literal["ai_suggestion_unreviewed"] = "ai_suggestion_unreviewed"
    provider: Literal["zhipu"] = "zhipu"
    model: Literal["glm-5v-turbo"] = IP_ASSET_METADATA_REPAIR_MODEL
    created_at: datetime
    asset_set_fingerprint: str = Field(pattern=_DIGEST_PATTERN)
    selected_count: int = Field(ge=1, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    scanned_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    suggested_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    changed_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    unchanged_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    failed_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    provider_call_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    inter_request_pacing_seconds: float = Field(
        ge=IP_ASSET_METADATA_REPAIR_MIN_PACING_SECONDS,
        le=IP_ASSET_METADATA_REPAIR_MAX_PACING_SECONDS,
    )
    items: tuple[IpAssetMetadataRepairPlanItem, ...] = Field(
        min_length=1, max_length=IP_ASSET_METADATA_REPAIR_MAX_ASSETS
    )
    plan_fingerprint: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_counts_and_identity(self) -> IpAssetMetadataRepairPlan:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("IP asset repair plan time must be timezone-aware")
        if len({item.asset_ref for item in self.items}) != len(self.items):
            raise ValueError("IP asset repair plan assets must be unique")
        if tuple(item.asset_ref for item in self.items) != tuple(
            sorted(item.asset_ref for item in self.items)
        ):
            raise ValueError("IP asset repair plan assets must use canonical order")
        suggested = sum(
            item.status
            in {
                IpAssetMetadataRepairItemStatus.CHANGED,
                IpAssetMetadataRepairItemStatus.UNCHANGED,
            }
            for item in self.items
        )
        changed = sum(item.status is IpAssetMetadataRepairItemStatus.CHANGED for item in self.items)
        scanned = sum(
            item.status is not IpAssetMetadataRepairItemStatus.NOT_PROCESSED for item in self.items
        )
        expected = (
            len(self.items),
            scanned,
            suggested,
            changed,
            suggested - changed,
            len(self.items) - suggested,
        )
        actual = (
            self.selected_count,
            self.scanned_count,
            self.suggested_count,
            self.changed_count,
            self.unchanged_count,
            self.failed_count,
        )
        if actual != expected:
            raise ValueError("IP asset repair plan counts are inconsistent")
        if self.asset_set_fingerprint != asset_set_fingerprint(self.items):
            raise ValueError("IP asset repair asset-set fingerprint is invalid")
        actual_provider_calls = sum(
            item.provider_call_status is not IpAssetMetadataRepairCallStatus.NOT_CALLED
            for item in self.items
        )
        if self.provider_call_count != actual_provider_calls:
            raise ValueError("IP asset repair provider call count is inconsistent")
        if self.items[0].provider_call_status is not IpAssetMetadataRepairCallStatus.COMPLETED:
            raise ValueError("IP asset repair plan requires a completed canary item")
        transient_positions = tuple(
            index
            for index, item in enumerate(self.items)
            if item.error_code
            in {
                IpAssetMetadataRepairErrorCode.PROVIDER_RATE_LIMITED,
                IpAssetMetadataRepairErrorCode.PROVIDER_TIMEOUT,
                IpAssetMetadataRepairErrorCode.PROVIDER_UNAVAILABLE,
            }
        )
        not_processed_positions = tuple(
            index
            for index, item in enumerate(self.items)
            if item.status is IpAssetMetadataRepairItemStatus.NOT_PROCESSED
        )
        if transient_positions:
            if len(transient_positions) != 1:
                raise ValueError("IP asset repair plan has multiple transient circuit breakers")
            transient_index = transient_positions[0]
            expected_remainder = tuple(range(transient_index + 1, len(self.items)))
            if not_processed_positions != expected_remainder:
                raise ValueError("IP asset repair interrupted suffix is inconsistent")
        elif not_processed_positions:
            raise ValueError("IP asset repair interrupted suffix lacks a transient failure")
        return self


class IpAssetMetadataRepairResultItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    asset_ref: str = Field(pattern=_ASSET_REF_PATTERN)
    content_commitment: str = Field(pattern=_DIGEST_PATTERN)
    before_metadata: IpAssetRepairMetadata
    proposed_metadata: IpAssetRepairMetadata | None = None
    before_metadata_fingerprint: str = Field(pattern=_DIGEST_PATTERN)
    proposed_metadata_fingerprint: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    status: IpAssetMetadataMutationStatus

    @model_validator(mode="after")
    def validate_item_fingerprints(self) -> IpAssetMetadataRepairResultItem:
        if self.before_metadata_fingerprint != metadata_fingerprint(self.before_metadata):
            raise ValueError("IP asset repair result before fingerprint is invalid")
        if (self.proposed_metadata is None) != (self.proposed_metadata_fingerprint is None):
            raise ValueError("IP asset repair result proposal shape is inconsistent")
        if self.proposed_metadata is not None and self.proposed_metadata_fingerprint != (
            metadata_fingerprint(self.proposed_metadata)
        ):
            raise ValueError("IP asset repair result proposed fingerprint is invalid")
        if self.status in {
            IpAssetMetadataMutationStatus.APPLIED,
            IpAssetMetadataMutationStatus.RESTORED,
            IpAssetMetadataMutationStatus.ALREADY_APPLIED,
        }:
            if self.proposed_metadata is None:
                raise ValueError("IP asset repair mutation result requires proposed metadata")
            if not changed_fields(self.before_metadata, self.proposed_metadata):
                raise ValueError("IP asset repair mutation result requires an actual metadata diff")
        return self


class IpAssetMetadataRepairResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["ip-asset-metadata-repair-result-v2"] = (
        IP_ASSET_METADATA_REPAIR_RESULT_SCHEMA_VERSION
    )
    provider: Literal["zhipu"] = "zhipu"
    model: Literal["glm-5v-turbo"] = IP_ASSET_METADATA_REPAIR_MODEL
    operation: Literal["apply", "restore"]
    created_at: datetime
    plan_fingerprint: str = Field(pattern=_DIGEST_PATTERN)
    asset_set_fingerprint: str = Field(pattern=_DIGEST_PATTERN)
    changed_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    already_applied_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    drift_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    failed_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    skipped_count: int = Field(ge=0, le=IP_ASSET_METADATA_REPAIR_MAX_ASSETS)
    items: tuple[IpAssetMetadataRepairResultItem, ...] = Field(
        min_length=1, max_length=IP_ASSET_METADATA_REPAIR_MAX_ASSETS
    )
    result_fingerprint: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def validate_result(self) -> IpAssetMetadataRepairResult:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("IP asset repair result time must be timezone-aware")
        if len({item.asset_ref for item in self.items}) != len(self.items):
            raise ValueError("IP asset repair result assets must be unique")
        if tuple(item.asset_ref for item in self.items) != tuple(
            sorted(item.asset_ref for item in self.items)
        ):
            raise ValueError("IP asset repair result assets must use canonical order")
        if self.asset_set_fingerprint != asset_set_fingerprint(self.items):
            raise ValueError("IP asset repair result asset-set fingerprint is invalid")
        disallowed = (
            {IpAssetMetadataMutationStatus.RESTORED}
            if self.operation == "apply"
            else {IpAssetMetadataMutationStatus.APPLIED}
        )
        if any(item.status in disallowed for item in self.items):
            raise ValueError("IP asset repair result operation status is inconsistent")
        changed_status = (
            IpAssetMetadataMutationStatus.APPLIED
            if self.operation == "apply"
            else IpAssetMetadataMutationStatus.RESTORED
        )
        changed = sum(item.status is changed_status for item in self.items)
        already = sum(
            item.status is IpAssetMetadataMutationStatus.ALREADY_APPLIED for item in self.items
        )
        drift = sum(
            item.status
            in {
                IpAssetMetadataMutationStatus.CONTENT_DRIFT,
                IpAssetMetadataMutationStatus.METADATA_DRIFT,
                IpAssetMetadataMutationStatus.NOT_ELIGIBLE,
                IpAssetMetadataMutationStatus.NOT_FOUND,
            }
            for item in self.items
        )
        failed = sum(
            item.status is IpAssetMetadataMutationStatus.MUTATION_FAILED for item in self.items
        )
        if (
            self.changed_count,
            self.already_applied_count,
            self.drift_count,
            self.failed_count,
            self.skipped_count,
        ) != (
            changed,
            already,
            drift,
            failed,
            len(self.items) - changed - already - drift - failed,
        ):
            raise ValueError("IP asset repair result counts are inconsistent")
        return self


def repair_metadata(metadata: IpAssetMetadata) -> IpAssetRepairMetadata:
    return IpAssetRepairMetadata(
        character=metadata.character,
        asset_type=metadata.asset_type,
        emotion=metadata.emotion,
        action=metadata.action,
        scene=metadata.scene,
        intended_use=metadata.intended_use,
        style=metadata.style,
        tags=metadata.tags,
    )


def metadata_fingerprint(metadata: IpAssetRepairMetadata | IpAssetMetadata) -> str:
    projected = (
        metadata if isinstance(metadata, IpAssetRepairMetadata) else repair_metadata(metadata)
    )
    return _domain_digest(
        "ip-asset-metadata-repair-state-v1",
        canonical_json(projected.model_dump(mode="json")),
    )


def content_commitment(raw_sha256: str) -> str:
    if len(raw_sha256) != 64 or any(value not in "0123456789abcdef" for value in raw_sha256):
        raise ValueError("IP asset repair content digest is invalid")
    return _domain_digest("ip-asset-metadata-repair-content-v1", raw_sha256.encode())


def asset_set_fingerprint(
    items: tuple[IpAssetMetadataRepairPlanItem | IpAssetMetadataRepairResultItem, ...],
) -> str:
    identity = tuple((item.asset_ref, item.content_commitment) for item in items)
    return asset_identity_fingerprint(identity)


def asset_identity_fingerprint(identity: tuple[tuple[str, str], ...]) -> str:
    return _domain_digest("ip-asset-metadata-repair-set-v1", canonical_json(identity))


def changed_fields(
    before: IpAssetRepairMetadata, proposed: IpAssetRepairMetadata
) -> tuple[IpAssetRepairField, ...]:
    return tuple(
        field_name
        for field_name in _REPAIR_FIELDS
        if getattr(before, field_name) != getattr(proposed, field_name)
    )


def plan_fingerprint(plan: IpAssetMetadataRepairPlan) -> str:
    payload = plan.model_dump(mode="json", exclude={"plan_fingerprint"})
    return _domain_digest("ip-asset-metadata-repair-plan-fingerprint-v2", canonical_json(payload))


def canary_fingerprint(canary: IpAssetMetadataRepairCanary) -> str:
    payload = canary.model_dump(mode="json", exclude={"canary_fingerprint"})
    return _domain_digest("ip-asset-metadata-repair-canary-fingerprint-v2", canonical_json(payload))


def result_fingerprint(result: IpAssetMetadataRepairResult) -> str:
    payload = result.model_dump(mode="json", exclude={"result_fingerprint"})
    return _domain_digest("ip-asset-metadata-repair-result-fingerprint-v2", canonical_json(payload))


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _domain_digest(domain: str, payload: bytes) -> str:
    return hashlib.sha256(domain.encode() + b"\0" + payload).hexdigest()
