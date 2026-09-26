"""Validated, replayable source input for a local news infographic."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from hashlib import sha256
from ipaddress import ip_address
from typing import Any, Final, Literal
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

INPUT_SCHEMA_VERSION: Final[Literal["news-infographic-input-v1"]] = "news-infographic-input-v1"
_FOOTER_SOURCE = "新闻来源："  # noqa: RUF001 - exact accepted Chinese footer
_FOOTER_LINK = "原文链接："  # noqa: RUF001 - exact accepted Chinese footer
_SAFE_LABEL = re.compile(r"^[^<>\x00-\x1f\x7f]{1,40}$")
_SAFE_TEXT = re.compile(r"^[^<>\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+$", re.DOTALL)


class InfographicInputError(ValueError):
    """A package cannot safely become a frozen infographic input."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _safe_public_url(value: str) -> str:
    if not 1 <= len(value) <= 180 or any(ord(ch) < 33 for ch in value):
        raise ValueError("source URL is blank, overlong or contains whitespace/control characters")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.fragment or parsed.port not in {None, 80, 443}:
        raise ValueError("source URL contains unsupported credentials, port or fragment")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or "." not in host:
        raise ValueError("source URL must name a public host")
    try:
        if not ip_address(host).is_global:
            raise ValueError("source URL must not name a private address")
    except ValueError as exc:
        if "private address" in str(exc):
            raise
    return value


class BoundEvidence(_FrozenModel):
    claim_id: str = Field(min_length=1, max_length=100)
    claim_text: str = Field(min_length=1, max_length=1500)
    evidence_binding_id: UUID
    candidate_id: UUID
    passage_id: UUID
    occurrence_id: UUID
    snapshot_id: UUID
    source_url: str
    source_tier: Literal["A", "B"]
    published_at: AwareDatetime
    exact_quote: str = Field(min_length=1, max_length=20000)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return _safe_public_url(value)


class BoundBrandChunk(_FrozenModel):
    claim_id: str = Field(min_length=1, max_length=100)
    claim_text: str = Field(min_length=1, max_length=1500)
    brand_chunk_id: UUID
    document_id: UUID
    version_id: UUID
    document_title: str = Field(min_length=1, max_length=300)
    document_kind: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=20000)


class BoundClaim(_FrozenModel):
    claim_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1500)
    kind: Literal["external_fact", "brand_statement", "opinion"]
    evidence_ids: tuple[UUID, ...] = Field(max_length=12)
    brand_chunk_ids: tuple[UUID, ...] = Field(max_length=12)

    @model_validator(mode="after")
    def validate_binding_kind(self) -> BoundClaim:
        if self.kind == "external_fact" and (not self.evidence_ids or self.brand_chunk_ids):
            raise ValueError("external fact needs evidence only")
        if self.kind == "brand_statement" and (not self.brand_chunk_ids or self.evidence_ids):
            raise ValueError("brand statement needs brand chunks only")
        if self.kind == "opinion" and (self.evidence_ids or self.brand_chunk_ids):
            raise ValueError("opinion must not claim factual or brand bindings")
        return self


class ValidatedInfographicInput(_FrozenModel):
    schema_version: Literal["news-infographic-input-v1"] = INPUT_SCHEMA_VERSION
    package_id: UUID
    copy_generation_run_id: UUID
    package_version: int = Field(ge=1)
    package_status: Literal["ready", "awaiting_manual_use", "completed"]
    selected_event_id: UUID
    selected_event_version_id: UUID
    business_date: date
    draft_version_id: UUID
    draft_version: int = Field(ge=1)
    copywriting: str = Field(min_length=1, max_length=12000)
    topic_title: str = Field(min_length=1, max_length=300)
    topic_summary: str | None = Field(default=None, max_length=1500)
    source_name: str = Field(min_length=1, max_length=40)
    source_url: str
    source_published_at: AwareDatetime
    claims: tuple[BoundClaim, ...] = Field(min_length=1, max_length=40)
    evidence: tuple[BoundEvidence, ...] = Field(min_length=1, max_length=48)
    brand_context: tuple[BoundBrandChunk, ...] = Field(min_length=1, max_length=48)
    copy_prompt_version: str = Field(min_length=1, max_length=120)
    copy_rule_version: str = Field(min_length=1, max_length=120)
    validation_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    audit_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return _safe_public_url(value)

    @field_validator("source_name")
    @classmethod
    def validate_source_name(cls, value: str) -> str:
        if not _SAFE_LABEL.fullmatch(value):
            raise ValueError("source name contains an unsafe character")
        return value

    @field_validator("topic_title")
    @classmethod
    def validate_topic_title(cls, value: str) -> str:
        if not _SAFE_TEXT.fullmatch(value):
            raise ValueError("display text contains an unsafe character")
        return value

    @field_validator("copywriting", "topic_summary")
    @classmethod
    def validate_copy_text(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_TEXT.fullmatch(value):
            raise ValueError("copy contains HTML or control characters")
        return value

    @model_validator(mode="after")
    def validate_integrity(self) -> ValidatedInfographicInput:
        if not self.claims or not any(item.kind == "external_fact" for item in self.claims):
            raise ValueError("input needs an evidence-bound external claim")
        if not any(item.kind == "brand_statement" for item in self.claims):
            raise ValueError("input needs a brand-bound statement")
        if len({item.claim_id for item in self.claims}) != len(self.claims):
            raise ValueError("claim IDs are ambiguous")
        claims = {item.claim_id: item for item in self.claims}
        evidence: dict[tuple[str, UUID], BoundEvidence] = {}
        evidence_identity: dict[UUID, dict[str, object]] = {}
        for item in self.evidence:
            claim = claims.get(item.claim_id)
            if claim is None or claim.kind != "external_fact" or claim.text != item.claim_text:
                raise ValueError("evidence has no matching external claim")
            signature = item.model_dump(exclude={"claim_id", "claim_text"})
            previous = evidence_identity.setdefault(item.evidence_binding_id, signature)
            if previous != signature:
                raise ValueError("one evidence ID has conflicting metadata")
            evidence[item.claim_id, item.evidence_binding_id] = item
        brand: dict[tuple[str, UUID], BoundBrandChunk] = {}
        brand_identity: dict[UUID, dict[str, object]] = {}
        for brand_item in self.brand_context:
            claim = claims.get(brand_item.claim_id)
            if (
                claim is None
                or claim.kind != "brand_statement"
                or claim.text != brand_item.claim_text
            ):
                raise ValueError("brand chunk has no matching brand claim")
            signature = brand_item.model_dump(exclude={"claim_id", "claim_text"})
            previous = brand_identity.setdefault(brand_item.brand_chunk_id, signature)
            if previous != signature:
                raise ValueError("one brand chunk ID has conflicting metadata")
            brand[brand_item.claim_id, brand_item.brand_chunk_id] = brand_item
        for claim in self.claims:
            if any((claim.claim_id, item) not in evidence for item in claim.evidence_ids):
                raise ValueError("claim has a dangling evidence ID")
            if any((claim.claim_id, item) not in brand for item in claim.brand_chunk_ids):
                raise ValueError("claim has a dangling brand chunk ID")
        primary = self.evidence[0]
        if (
            self.source_url != primary.source_url
            or self.source_published_at != primary.published_at
        ):
            raise ValueError("primary source does not match first locked evidence")
        if not _has_exact_footer(self.copywriting, self.source_name, self.source_url):
            raise ValueError("accepted copy source footer is absent or mismatched")
        return self

    @property
    def source_date(self) -> date:
        return self.source_published_at.astimezone(ZoneInfo("Asia/Shanghai")).date()

    @property
    def source_footer(self) -> str:
        return f"{_FOOTER_SOURCE}{self.source_name}\n{_FOOTER_LINK}{self.source_url}"

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

    def public_projection(self) -> dict[str, str]:
        """Return only safe attribution and identity; never include brand/source excerpts."""
        return {
            "package_id": str(self.package_id),
            "draft_version_id": str(self.draft_version_id),
            "event_version_id": str(self.selected_event_version_id),
            "business_date": self.business_date.isoformat(),
            "source_date": self.source_date.isoformat(),
            "source_name": self.source_name,
            "source_url": self.source_url,
            "input_fingerprint": self.fingerprint,
        }


def _has_exact_footer(copywriting: str, source_name: str, source_url: str) -> bool:
    lines = [line.strip() for line in copywriting.splitlines() if line.strip()]
    if lines and lines[-1].startswith("#"):
        lines.pop()
    return (
        len(lines) >= 2
        and lines[-2] == f"{_FOOTER_SOURCE}{source_name}"
        and lines[-1] == f"{_FOOTER_LINK}{source_url}"
    )


def _source_name_from_copy(copywriting: str, source_url: str) -> str:
    lines = [line.strip() for line in copywriting.splitlines() if line.strip()]
    if lines and lines[-1].startswith("#"):
        lines.pop()
    if len(lines) < 2 or lines[-1] != f"{_FOOTER_LINK}{source_url}":
        raise InfographicInputError("accepted copy footer does not match locked source")
    source_line = lines[-2]
    if not source_line.startswith(_FOOTER_SOURCE):
        raise InfographicInputError("accepted copy has no source name")
    name = source_line.removeprefix(_FOOTER_SOURCE)
    if not _SAFE_LABEL.fullmatch(name):
        raise InfographicInputError("accepted source name is unsafe or overlong")
    return name


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise InfographicInputError(f"{name} must be an object")
    return value


def _items(value: object, name: str, *, maximum: int) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise InfographicInputError(f"{name} must contain 1-{maximum} items")
    return [_object(item, name) for item in value]


def validate_package_snapshot(
    payload: Mapping[str, Any], *, expected_package_id: UUID | None = None
) -> ValidatedInfographicInput:
    """Project an exact accepted package detail response into private immutable input."""
    try:
        if expected_package_id is not None and UUID(str(payload["id"])) != expected_package_id:
            raise InfographicInputError("package response ID differs from requested ID")
        topic = _object(payload["topic"], "topic")
        copy = _object(payload["copy"], "copy")
        validation = _object(payload["validation"], "validation")
        audit = _object(payload["audit"], "audit")
        if topic.get("decision_kind") != "selected":
            raise InfographicInputError("package topic is not selected")
        if validation.get("passed") is not True or audit.get("accepted") is not True:
            raise InfographicInputError("accepted deterministic validation and audit are required")
        if payload.get("review_status") == "rejected" or payload.get("status") not in {
            "ready",
            "awaiting_manual_use",
            "completed",
        }:
            raise InfographicInputError("package is not eligible for local reuse")
        source_rows = _items(payload["sources"], "sources", maximum=48)
        brand_rows = _items(payload["brand_bindings"], "brand_bindings", maximum=48)
        claims = _items(copy["claims"], "copy claims", maximum=40)
        evidence = tuple(BoundEvidence.model_validate(item) for item in source_rows)
        brand = tuple(
            BoundBrandChunk.model_validate(
                {key: item[key] for key in BoundBrandChunk.model_fields if key in item}
            )
            for item in brand_rows
        )
        first_source = evidence[0]
        copywriting = copy["copywriting"]
        if not isinstance(copywriting, str):
            raise InfographicInputError("copywriting must be text")
        source_name = _source_name_from_copy(copywriting, first_source.source_url)
        return ValidatedInfographicInput.model_validate(
            {
                "package_id": payload["id"],
                "copy_generation_run_id": payload["copy_generation_run_id"],
                "package_version": payload["package_version"],
                "package_status": payload["status"],
                "selected_event_id": topic["selected_event_id"],
                "selected_event_version_id": topic["selected_event_version_id"],
                "business_date": topic["business_date"],
                "draft_version_id": copy["draft_version_id"],
                "draft_version": copy["version"],
                "copywriting": copywriting,
                "topic_title": topic["title"],
                "topic_summary": topic.get("summary"),
                "source_name": source_name,
                "source_url": first_source.source_url,
                "source_published_at": first_source.published_at,
                "claims": claims,
                "evidence": evidence,
                "brand_context": brand,
                "copy_prompt_version": copy["prompt_version"],
                "copy_rule_version": copy["rule_version"],
                "validation_fingerprint": validation.get("result_fingerprint"),
                "audit_fingerprint": audit.get("result_fingerprint"),
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, InfographicInputError):
            raise
        raise InfographicInputError(
            "material package has incomplete or invalid bound input"
        ) from exc


def build_private_input_bundle(
    cases: tuple[ValidatedInfographicInput, ...],
) -> dict[str, object]:
    if not 1 <= len(cases) <= 3 or len({case.package_id for case in cases}) != len(cases):
        raise InfographicInputError("input bundle needs 1-3 distinct packages")
    return {
        "schema_version": INPUT_SCHEMA_VERSION,
        "cases": [case.model_dump(mode="json") for case in cases],
    }


def validate_input_bundle(payload: object) -> tuple[ValidatedInfographicInput, ...]:
    bundle = _object(payload, "input bundle")
    if (
        set(bundle) != {"schema_version", "cases"}
        or bundle["schema_version"] != INPUT_SCHEMA_VERSION
    ):
        raise InfographicInputError("input bundle schema is unsupported")
    items = _items(bundle["cases"], "cases", maximum=3)
    try:
        cases = tuple(ValidatedInfographicInput.model_validate(item) for item in items)
        if len({case.package_id for case in cases}) != len(cases):
            raise InfographicInputError("input bundle repeats a package")
        if len({case.selected_event_version_id for case in cases}) != len(cases):
            raise InfographicInputError("input bundle repeats a selected event")
        return cases
    except ValueError as exc:
        if isinstance(exc, InfographicInputError):
            raise
        raise InfographicInputError("frozen input bundle failed validation") from exc
