from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in rendered editorial copy.
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
from html import escape
from itertools import permutations
from typing import Annotated, Literal, cast
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

OFFICIAL_ACCOUNT_FIXTURE_ID = "official-account-article-v1"
OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V1_VERSION = "official-account-article-schema-v1"
OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V2_VERSION = "official-account-article-schema-v2-multi-image"
OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V3_VERSION = "official-account-article-schema-v3-semantic-media"
OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION = "official-account-article-schema-v4-multimodal-media"
OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION = "official-account-article-schema-v5-news-context"
OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION = "official-account-media-plan-v1-deterministic"
OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION = "official-account-media-plan-v2-semantic-balanced"
OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION: Literal["official-account-media-plan-v3-multimodal-hybrid"] = (
    "official-account-media-plan-v3-multimodal-hybrid"
)
OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION: Literal["official-account-media-plan-v4-five-blocks"] = (
    "official-account-media-plan-v4-five-blocks"
)
OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION: Literal["official-account-visual-query-v1"] = (
    "official-account-visual-query-v1"
)
OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION: Literal[
    "official-account-visual-selector-v3-multimodal-hybrid"
] = "official-account-visual-selector-v3-multimodal-hybrid"
OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V1_VERSION = "official-account-generator-v1"
OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V2_VERSION = "official-account-generator-v2"
OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V3_VERSION = "official-account-generator-v3-parent-field-guide"
OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION = "official-account-generator-v4-reader-copy"
OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION = "official-account-generator-v5-structured-output"
OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION = "official-account-generator-v6-length-buffer"
OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION = (
    "official-account-generator-v7-five-to-seven-sections"
)
OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION = "official-account-auditor-v1"
OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION = "official-account-auditor-v2-structured-output"
OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION = "official-account-audit-schema-v1"
OFFICIAL_ACCOUNT_RULE_V1_VERSION = "official-account-rules-v1"
OFFICIAL_ACCOUNT_RULE_V2_VERSION = "official-account-rules-v2"
OFFICIAL_ACCOUNT_RULE_V3_VERSION = "official-account-rules-v3-parent-field-guide"
OFFICIAL_ACCOUNT_RULE_VERSION = "official-account-rules-v4-reader-copy"
OFFICIAL_ACCOUNT_RENDERER_V1_VERSION = "wechat-html-renderer-v1"
OFFICIAL_ACCOUNT_STYLE_V1_VERSION = "wechat-inline-style-v1"
OFFICIAL_ACCOUNT_TEMPLATE_V1_VERSION = "wechat-fragment-template-v1"
OFFICIAL_ACCOUNT_RENDERER_V2_VERSION = "wechat-html-renderer-v2"
OFFICIAL_ACCOUNT_STYLE_V2_VERSION = "wechat-inline-editorial-v2"
OFFICIAL_ACCOUNT_TEMPLATE_V2_VERSION = "wechat-editorial-template-v2"
OFFICIAL_ACCOUNT_RENDERER_V3_VERSION = "wechat-html-renderer-v3"
OFFICIAL_ACCOUNT_STYLE_V3_VERSION = "wechat-inline-xiaosai-v3"
OFFICIAL_ACCOUNT_TEMPLATE_V3_VERSION = "wechat-xiaosai-template-v3"
OFFICIAL_ACCOUNT_RENDERER_V4_VERSION = "wechat-html-renderer-v4"
OFFICIAL_ACCOUNT_STYLE_V4_VERSION = "wechat-inline-science-field-guide-v4"
OFFICIAL_ACCOUNT_TEMPLATE_V4_VERSION = "wechat-science-field-guide-template-v4"
OFFICIAL_ACCOUNT_RENDERER_V5_VERSION = "wechat-html-renderer-v5-multi-image"
OFFICIAL_ACCOUNT_STYLE_V5_VERSION = "wechat-inline-science-field-guide-v5-multi-image"
OFFICIAL_ACCOUNT_TEMPLATE_V5_VERSION = "wechat-science-field-guide-template-v5-multi-image"
OFFICIAL_ACCOUNT_RENDERER_V6_VERSION = "wechat-html-renderer-v6-semantic-media"
OFFICIAL_ACCOUNT_STYLE_V6_VERSION = "wechat-inline-science-field-guide-v6-semantic-media"
OFFICIAL_ACCOUNT_TEMPLATE_V6_VERSION = "wechat-science-field-guide-template-v6-semantic-media"
OFFICIAL_ACCOUNT_RENDERER_VERSION = "wechat-html-renderer-v7-multimodal-media"
OFFICIAL_ACCOUNT_STYLE_VERSION = "wechat-inline-science-field-guide-v7-multimodal-media"
OFFICIAL_ACCOUNT_TEMPLATE_VERSION = "wechat-science-field-guide-template-v7-multimodal-media"
OFFICIAL_ACCOUNT_RENDERER_V8_VERSION = "wechat-html-renderer-v8-news-context"
OFFICIAL_ACCOUNT_STYLE_V8_VERSION = "wechat-inline-science-field-guide-v8-news-context"
OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION = "wechat-science-field-guide-template-v8-news-context"
OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V1_VERSION = "official-account-local-adapter-v1"
OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION = (
    "official-account-local-adapter-v2-distinct-fixture-cover"
)
OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION = (
    "official-account-local-adapter-v3-deterministic-multi-image"
)
OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION = (
    "official-account-local-adapter-v4-publication-derivatives"
)
OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION = "official-account-local-adapter-v5-multimodal-media"
OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION = "official-account-local-adapter-v6-news-context"
OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION = (
    "official-account-local-adapter-v7-disjoint-attempt-ordinals"
)
OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION: Literal[
    "official-account-news-context-selection-v1"
] = "official-account-news-context-selection-v1"
OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V1_VERSION = "official-account-generated-visual-plan-v1"
OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V1_VERSION = "official-account-generated-visual-prompt-v1"
OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION = (
    "official-account-generated-visual-plan-v2-block-anchor"
)
OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V2_VERSION = (
    "official-account-generated-visual-prompt-v2-block-scene"
)
OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION = (
    "official-account-generated-visual-plan-v3-visible-ip"
)
OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION = (
    "official-account-generated-visual-prompt-v3-visible-ip-block-scene"
)
OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION = (
    "official-account-generated-body-publication-v2-3x2-jpeg"
)
OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER = "__OFFICIAL_ACCOUNT_BODY_MEDIA_0__"


def body_media_placeholder(ordinal: int) -> str:
    if ordinal < 0 or ordinal > 4:
        raise ValueError("official-account body-media ordinal must be between zero and four")
    return f"__OFFICIAL_ACCOUNT_BODY_MEDIA_{ordinal}__"


def context_media_placeholder(ordinal: int) -> str:
    if ordinal < 0 or ordinal > 1:
        raise ValueError("official-account context-media ordinal must be zero or one")
    return f"__OFFICIAL_ACCOUNT_CONTEXT_MEDIA_{ordinal}__"


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_UNSAFE_MARKUP = re.compile(r"<\s*/?\s*[A-Za-z]|```|\[[^\]]*\]\([^)]*\)")
_UNSAFE_URL = re.compile(r"(?i)(?:https?://|javascript:|data:)")
_UNSAFE_INSTRUCTION = re.compile(
    r"(?i)(?:立即发布|自动发布|一键群发|draft/add|AppSecret|access[_ -]?token)"
)


def _validated_source_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("article source URL must be safe HTTPS")
    return value


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class OfficialAccountEvidence(_FrozenModel):
    evidence_id: UUID
    source_url: str = Field(min_length=1, max_length=2_048)
    source_name: str = Field(min_length=1, max_length=200)
    source_tier: str | None = Field(default=None, max_length=40)
    exact_quote: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_source_url(self) -> OfficialAccountEvidence:
        _validated_source_url(self.source_url)
        return self


class OfficialAccountBrandContext(_FrozenModel):
    brand_chunk_id: UUID
    document_title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=2_000)
    tone_tags: tuple[str, ...] = Field(default=(), max_length=24)
    safety_tags: tuple[str, ...] = Field(default=(), max_length=24)


class OfficialAccountSourceSnapshot(_FrozenModel):
    source_kind: Literal["material_package", "fixture"]
    source_id: str = Field(min_length=1, max_length=120)
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    material_package_id: UUID | None = None
    source_image_artifact_id: UUID | None = None
    topic_title: str = Field(min_length=1, max_length=300)
    topic_summary: str = Field(min_length=1, max_length=2_000)
    existing_copy: str = Field(min_length=1, max_length=4_000)
    evidence: tuple[OfficialAccountEvidence, ...] = Field(min_length=1, max_length=40)
    brand_context: tuple[OfficialAccountBrandContext, ...] = Field(
        min_length=1,
        max_length=20,
    )
    inherited_quality: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_shape(self) -> OfficialAccountSourceSnapshot:
        is_material = self.source_kind == "material_package"
        if is_material != (self.material_package_id is not None):
            raise ValueError("material source must bind exactly one material package")
        if is_material != (self.source_image_artifact_id is not None):
            raise ValueError("material source must bind exactly one image artifact")
        evidence_ids = [item.evidence_id for item in self.evidence]
        brand_ids = [item.brand_chunk_id for item in self.brand_context]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("article evidence IDs must be unique")
        if len(brand_ids) != len(set(brand_ids)):
            raise ValueError("article brand chunk IDs must be unique")
        return self


class GeneratedArticleClaim(_FrozenModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9-]{0,79}$")
    text: str = Field(min_length=1, max_length=600)
    kind: Literal["external_fact", "brand_statement", "opinion"]
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=8)
    brand_chunk_ids: tuple[UUID, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_binding_shape(self) -> GeneratedArticleClaim:
        if self.kind == "external_fact":
            if not self.evidence_ids or self.brand_chunk_ids:
                raise ValueError("external facts require evidence-only bindings")
        elif self.kind == "brand_statement":
            if not self.brand_chunk_ids or self.evidence_ids:
                raise ValueError("brand statements require brand-only bindings")
        elif self.evidence_ids or self.brand_chunk_ids:
            raise ValueError("opinions cannot carry evidence or brand bindings")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("claim evidence bindings must be unique")
        if len(self.brand_chunk_ids) != len(set(self.brand_chunk_ids)):
            raise ValueError("claim brand bindings must be unique")
        return self


class ArticleParagraphBlock(_FrozenModel):
    kind: Literal["paragraph"]
    text: str = Field(min_length=1, max_length=1_200)
    claim_refs: tuple[str, ...] = Field(default=(), max_length=12)


class ArticleBulletListBlock(_FrozenModel):
    kind: Literal["bullet_list"]
    items: tuple[str, ...] = Field(min_length=1, max_length=8)
    claim_refs: tuple[str, ...] = Field(default=(), max_length=12)


class ArticleQuoteBlock(_FrozenModel):
    kind: Literal["quote", "callout"]
    text: str = Field(min_length=1, max_length=800)
    claim_refs: tuple[str, ...] = Field(default=(), max_length=12)


class ArticleImageBlock(_FrozenModel):
    kind: Literal["image"]
    slot_key: Literal["body-0", "body-1", "body-2", "body-3", "body-4"] = "body-0"
    alt_text: str = Field(min_length=1, max_length=200)
    claim_refs: tuple[str, ...] = ()


ArticleBlock = Annotated[
    ArticleParagraphBlock | ArticleBulletListBlock | ArticleQuoteBlock | ArticleImageBlock,
    Field(discriminator="kind"),
]


class GeneratedArticleSection(_FrozenModel):
    heading: str = Field(min_length=1, max_length=120)
    blocks: tuple[
        Annotated[
            ArticleParagraphBlock | ArticleBulletListBlock | ArticleQuoteBlock,
            Field(discriminator="kind"),
        ],
        ...,
    ] = Field(min_length=1, max_length=12)


class GeneratedArticleDraft(_FrozenModel):
    title: str = Field(min_length=1, max_length=120)
    digest: str = Field(min_length=1, max_length=240)
    author: str = Field(min_length=1, max_length=80)
    lead: str = Field(min_length=1, max_length=1_200)
    sections: tuple[GeneratedArticleSection, ...] = Field(min_length=3, max_length=7)
    conclusion: str = Field(min_length=1, max_length=1_200)
    claims: tuple[GeneratedArticleClaim, ...] = Field(min_length=1, max_length=40)


class ArticleSection(_FrozenModel):
    heading: str = Field(min_length=1, max_length=120)
    blocks: tuple[ArticleBlock, ...] = Field(min_length=1, max_length=13)


class ArticleSourceProjection(_FrozenModel):
    evidence_id: UUID
    source_name: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1, max_length=2_048)
    source_tier: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def validate_source_url(self) -> ArticleSourceProjection:
        _validated_source_url(self.source_url)
        return self


class ArticleMediaSlot(_FrozenModel):
    slot_key: Literal[
        "body-0",
        "body-1",
        "body-2",
        "body-3",
        "body-4",
        "cover-0",
    ]
    role: Literal["body", "cover"]
    ordinal: int = Field(default=0, ge=0, le=4)

    @model_validator(mode="after")
    def validate_slot_role(self) -> ArticleMediaSlot:
        if self.slot_key != f"{self.role}-{self.ordinal}":
            raise ValueError("article media slot key must match its role")
        if self.role == "cover" and self.ordinal != 0:
            raise ValueError("article cover media ordinal must be zero")
        return self


class SemanticMediaCandidate(_FrozenModel):
    candidate_id: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_label: str = Field(min_length=1, max_length=80)
    semantic_tags: tuple[Annotated[str, Field(min_length=1, max_length=40)], ...] = Field(
        min_length=1,
        max_length=16,
    )
    alt_text: str = Field(min_length=1, max_length=160)
    caption_text: str = Field(min_length=1, max_length=200)
    publication_priority: int = Field(ge=0, le=10_000)

    @model_validator(mode="after")
    def validate_tags(self) -> SemanticMediaCandidate:
        normalized = tuple(_normalize_semantic_text(tag) for tag in self.semantic_tags)
        if any(not tag for tag in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("semantic media tags must be non-empty and unique after normalization")
        return self


class SemanticMediaAssignment(_FrozenModel):
    ordinal: int = Field(ge=0, le=4)
    section_index: int = Field(ge=0, le=6)
    candidate_id: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    alt_text: str = Field(min_length=1, max_length=160)
    caption_text: str = Field(min_length=1, max_length=200)
    score: int = Field(ge=0, le=10_000)
    score_band: Literal["heading", "body", "fallback"]
    reason_code: Literal[
        "semantic_heading_match",
        "semantic_body_match",
        "stable_fallback",
        "multimodal_similarity",
    ]
    selection_method: Literal["deterministic_tag", "multimodal_embedding"] = "deterministic_tag"
    similarity_band: Literal["very_high", "high", "medium", "low"] | None = None


class ArticleMediaEmbeddingIdentity(_FrozenModel):
    provider: Literal["alibaba-model-studio"]
    model: Literal["qwen3-vl-embedding"]
    dimensions: Literal[2048]
    input_policy_version: Literal["brand-visual-embedding-input-v2"]


class ArticleMediaSelectionItem(_FrozenModel):
    ordinal: int = Field(ge=0, le=4)
    section_index: int = Field(ge=0, le=6)
    candidate_ref: str = Field(pattern=r"^[0-9a-f]{16}$")
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_method: Literal["deterministic_tag", "multimodal_embedding"]
    reason_code: Literal[
        "semantic_heading_match",
        "semantic_body_match",
        "stable_fallback",
        "multimodal_similarity",
    ]
    similarity_band: Literal["very_high", "high", "medium", "low"] | None = None

    @model_validator(mode="after")
    def validate_similarity_shape(self) -> ArticleMediaSelectionItem:
        semantic = self.selection_method == "multimodal_embedding"
        if semantic != (self.similarity_band is not None):
            raise ValueError("multimodal selection requires exactly one similarity band")
        return self


class ArticleMediaSelectionSnapshot(_FrozenModel):
    media_plan_version: Literal[
        "official-account-media-plan-v3-multimodal-hybrid",
        "official-account-media-plan-v4-five-blocks",
    ]
    visual_query_version: Literal["official-account-visual-query-v1"]
    visual_selector_version: Literal["official-account-visual-selector-v3-multimodal-hybrid"]
    status: Literal["semantic_ready", "semantic_unavailable", "single_candidate"]
    closed_reason: (
        Literal[
            "disabled",
            "single_candidate",
            "index_incomplete",
            "provider_unavailable",
            "invalid_provider_output",
            "identity_mismatch",
            "catalog_changed",
            "input_normalization_failed",
        ]
        | None
    ) = None
    catalog_version: str = Field(min_length=1, max_length=80)
    catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_identity: ArticleMediaEmbeddingIdentity | None = None
    query_fingerprints: tuple[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")], ...] = Field(
        default=(), max_length=5
    )
    assignments: tuple[ArticleMediaSelectionItem, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_snapshot_shape(self) -> ArticleMediaSelectionSnapshot:
        semantic = self.status == "semantic_ready"
        if semantic != (self.embedding_identity is not None):
            raise ValueError("semantic-ready selection requires an embedding identity")
        if semantic != bool(self.query_fingerprints):
            raise ValueError("semantic-ready selection requires query fingerprints")
        if semantic != all(
            item.selection_method == "multimodal_embedding" for item in self.assignments
        ):
            raise ValueError("semantic selection methods do not match snapshot status")
        if semantic != (self.closed_reason is None):
            raise ValueError("semantic-ready selection cannot carry a closed reason")
        if not semantic and self.closed_reason is None:
            raise ValueError("fallback selection requires a closed reason")
        if self.status == "single_candidate" and self.closed_reason != "single_candidate":
            raise ValueError("single-candidate selection requires its closed reason")
        ordinals = tuple(item.ordinal for item in self.assignments)
        if ordinals != tuple(range(len(self.assignments))):
            raise ValueError("media selection ordinals must be contiguous")
        if len({item.section_index for item in self.assignments}) != len(self.assignments):
            raise ValueError("media selection section indexes must be distinct")
        if len({item.candidate_ref for item in self.assignments}) != len(self.assignments):
            raise ValueError("media selection candidate references must be distinct")
        if len({item.source_checksum for item in self.assignments}) != len(self.assignments):
            raise ValueError("media selection source checksums must be distinct")
        if len({item.publication_checksum for item in self.assignments}) != len(self.assignments):
            raise ValueError("media selection publication checksums must be distinct")
        return self


class ArticleNewsContextMediaItem(_FrozenModel):
    ordinal: int = Field(ge=0, le=1)
    section_index: int = Field(ge=0, le=6)
    source_article_image_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    width: int = Field(ge=320, le=8192)
    height: int = Field(ge=180, le=8192)
    alt_text: str = Field(min_length=1, max_length=200)
    caption: str | None = Field(default=None, max_length=300)
    credit: str | None = Field(default=None, max_length=200)
    source_page_url: str = Field(min_length=1, max_length=2_048)
    rights_status: Literal["publish_permission_unverified"]
    context_only_not_evidence: Literal[True] = True

    @model_validator(mode="after")
    def validate_urls(self) -> ArticleNewsContextMediaItem:
        _validated_source_url(self.source_page_url)
        return self


class ArticleNewsContextMediaSnapshot(_FrozenModel):
    selection_version: Literal["official-account-news-context-selection-v1"]
    status: Literal["not_present", "partial", "ready"]
    items: tuple[ArticleNewsContextMediaItem, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def validate_snapshot(self) -> ArticleNewsContextMediaSnapshot:
        expected_status = (
            "not_present" if not self.items else "partial" if len(self.items) == 1 else "ready"
        )
        if self.status != expected_status:
            raise ValueError("news-context status does not match selected items")
        if tuple(item.ordinal for item in self.items) != tuple(range(len(self.items))):
            raise ValueError("news-context ordinals must be contiguous")
        if len({item.section_index for item in self.items}) != len(self.items):
            raise ValueError("news-context section anchors must be distinct")
        if len({item.source_article_image_id for item in self.items}) != len(self.items):
            raise ValueError("news-context image references must be distinct")
        if len({item.sha256 for item in self.items}) != len(self.items):
            raise ValueError("news-context image checksums must be distinct")
        return self


class ArticleQualitySummary(_FrozenModel):
    inherited_copy_validation_passed: bool
    inherited_copy_audit_accepted: bool
    inherited_image_validation_passed: bool
    inherited_image_audit_status: str = Field(min_length=1, max_length=40)
    manual_review_status: str = Field(min_length=1, max_length=40)


class ArticleVersionBundle(_FrozenModel):
    generator_prompt_version: str = Field(min_length=1, max_length=80)
    article_schema_version: str = Field(min_length=1, max_length=80)
    auditor_prompt_version: str = Field(min_length=1, max_length=80)
    audit_schema_version: str = Field(min_length=1, max_length=80)
    rule_version: str = Field(min_length=1, max_length=80)
    renderer_version: str = Field(min_length=1, max_length=80)
    style_version: str = Field(min_length=1, max_length=80)
    template_version: str = Field(min_length=1, max_length=80)
    local_adapter_version: str = Field(min_length=1, max_length=80)
    media_plan_version: str | None = Field(default=None, min_length=1, max_length=80)
    visual_query_version: str | None = Field(default=None, min_length=1, max_length=80)
    visual_selector_version: str | None = Field(default=None, min_length=1, max_length=80)
    context_media_plan_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        exclude_if=lambda value: value is None,
    )


ArticleVersionKind = Literal[
    "v1",
    "v2",
    "v3",
    "v4",
    "v5",
    "v6",
    "v7",
    "v8",
    "v9",
    "v10",
]


def article_version_bundle_kind(versions: ArticleVersionBundle) -> ArticleVersionKind | None:
    """Return the frozen artifact family while preserving supported historical recovery tuples."""
    audit_versions = (
        versions.auditor_prompt_version,
        versions.audit_schema_version,
    )
    historical_audit_versions = (
        OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION,
        OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
    )
    current_audit_versions = (
        OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
        OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
    )
    if audit_versions not in {historical_audit_versions, current_audit_versions}:
        return None
    generation_versions = (
        versions.generator_prompt_version,
        versions.rule_version,
    )
    historical_generation = generation_versions in {
        (
            OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V1_VERSION,
            OFFICIAL_ACCOUNT_RULE_V1_VERSION,
        ),
        (
            OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V2_VERSION,
            OFFICIAL_ACCOUNT_RULE_V2_VERSION,
        ),
        (
            OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V3_VERSION,
            OFFICIAL_ACCOUNT_RULE_V3_VERSION,
        ),
    }
    render_versions = (
        versions.renderer_version,
        versions.style_version,
        versions.template_version,
    )
    has_no_visual_selector = (
        versions.visual_query_version is None and versions.visual_selector_version is None
    )
    has_no_context_media = versions.context_media_plan_version is None
    historical_render_kind: dict[tuple[str, str, str], ArticleVersionKind] = {
        (
            OFFICIAL_ACCOUNT_RENDERER_V1_VERSION,
            OFFICIAL_ACCOUNT_STYLE_V1_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_V1_VERSION,
        ): "v1",
        (
            OFFICIAL_ACCOUNT_RENDERER_V2_VERSION,
            OFFICIAL_ACCOUNT_STYLE_V2_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_V2_VERSION,
        ): "v2",
        (
            OFFICIAL_ACCOUNT_RENDERER_V3_VERSION,
            OFFICIAL_ACCOUNT_STYLE_V3_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_V3_VERSION,
        ): "v3",
        (
            OFFICIAL_ACCOUNT_RENDERER_V4_VERSION,
            OFFICIAL_ACCOUNT_STYLE_V4_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_V4_VERSION,
        ): "v4",
    }
    if (
        audit_versions == historical_audit_versions
        and historical_generation
        and versions.article_schema_version == OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V1_VERSION
        and versions.media_plan_version is None
        and has_no_visual_selector
        and has_no_context_media
        and versions.local_adapter_version
        in {OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V1_VERSION, OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION}
    ):
        return historical_render_kind.get(render_versions)
    if (
        audit_versions == historical_audit_versions
        and historical_generation
        and versions.article_schema_version == OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V2_VERSION
        and versions.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION
        and has_no_visual_selector
        and has_no_context_media
        and render_versions
        == (
            OFFICIAL_ACCOUNT_RENDERER_V5_VERSION,
            OFFICIAL_ACCOUNT_STYLE_V5_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_V5_VERSION,
        )
        and versions.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION
    ):
        return "v5"
    if (
        audit_versions == historical_audit_versions
        and generation_versions
        == (
            OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
            OFFICIAL_ACCOUNT_RULE_VERSION,
        )
        and versions.article_schema_version == OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V3_VERSION
        and versions.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION
        and has_no_visual_selector
        and has_no_context_media
        and render_versions
        == (
            OFFICIAL_ACCOUNT_RENDERER_V6_VERSION,
            OFFICIAL_ACCOUNT_STYLE_V6_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_V6_VERSION,
        )
        and versions.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION
    ):
        return "v6"
    if (
        audit_versions == historical_audit_versions
        and generation_versions
        == (
            OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
            OFFICIAL_ACCOUNT_RULE_VERSION,
        )
        and versions.article_schema_version == OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION
        and versions.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION
        and versions.visual_query_version == OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION
        and versions.visual_selector_version == OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION
        and has_no_context_media
        and render_versions
        == (
            OFFICIAL_ACCOUNT_RENDERER_VERSION,
            OFFICIAL_ACCOUNT_STYLE_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
        )
        and versions.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION
    ):
        return "v7"
    if (
        audit_versions == current_audit_versions
        and generation_versions
        == (
            OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
            OFFICIAL_ACCOUNT_RULE_VERSION,
        )
        and versions.article_schema_version == OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION
        and versions.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION
        and versions.visual_query_version == OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION
        and versions.visual_selector_version == OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION
        and has_no_context_media
        and render_versions
        == (
            OFFICIAL_ACCOUNT_RENDERER_VERSION,
            OFFICIAL_ACCOUNT_STYLE_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
        )
        and versions.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION
    ):
        return "v8"
    if (
        audit_versions == current_audit_versions
        and generation_versions
        in {
            (OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION, OFFICIAL_ACCOUNT_RULE_VERSION),
            (OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION, OFFICIAL_ACCOUNT_RULE_VERSION),
        }
        and versions.article_schema_version == OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION
        and versions.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION
        and versions.visual_query_version == OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION
        and versions.visual_selector_version == OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION
        and versions.context_media_plan_version == OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION
        and render_versions
        == (
            OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
            OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
        )
        and versions.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION
    ):
        return "v9"
    if (
        audit_versions == current_audit_versions
        and generation_versions
        == (
            OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
            OFFICIAL_ACCOUNT_RULE_VERSION,
        )
        and versions.article_schema_version == OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION
        and versions.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION
        and versions.visual_query_version == OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION
        and versions.visual_selector_version == OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION
        and versions.context_media_plan_version == OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION
        and render_versions
        == (
            OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
            OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
            OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
        )
        and versions.local_adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION
    ):
        return "v10"
    return None


class ArticlePackage(_FrozenModel):
    title: str = Field(min_length=1, max_length=120)
    digest: str = Field(min_length=1, max_length=240)
    author: str = Field(min_length=1, max_length=80)
    lead: str = Field(min_length=1, max_length=1_200)
    sections: tuple[ArticleSection, ...] = Field(min_length=3, max_length=7)
    conclusion: str = Field(min_length=1, max_length=1_200)
    claims: tuple[GeneratedArticleClaim, ...] = Field(min_length=1, max_length=40)
    sources: tuple[ArticleSourceProjection, ...] = Field(min_length=1, max_length=40)
    media_slots: tuple[ArticleMediaSlot, ...] = Field(min_length=2, max_length=6)
    topic_title: str = Field(min_length=1, max_length=300)
    quality: ArticleQualitySummary
    versions: ArticleVersionBundle
    media_selection: ArticleMediaSelectionSnapshot | None = None
    news_context_media: ArticleNewsContextMediaSnapshot | None = None
    content_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_media_selection_version(self) -> ArticlePackage:
        version_kind = article_version_bundle_kind(self.versions)
        if (version_kind in {"v7", "v8", "v9", "v10"}) != (self.media_selection is not None):
            raise ValueError("only v7/v8/v9/v10 articles require a media selection snapshot")
        if (version_kind in {"v9", "v10"}) != (self.news_context_media is not None):
            raise ValueError("only v9/v10 articles require a news-context snapshot")
        if self.media_selection is not None:
            if (
                self.media_selection.media_plan_version != self.versions.media_plan_version
                or self.media_selection.visual_query_version != self.versions.visual_query_version
                or self.media_selection.visual_selector_version
                != self.versions.visual_selector_version
            ):
                raise ValueError("article media selection versions do not match")
            image_slots = tuple(
                (section_index, block.slot_key)
                for section_index, section in enumerate(self.sections)
                for block in section.blocks
                if isinstance(block, ArticleImageBlock)
            )
            expected_slots = tuple(
                (item.section_index, f"body-{item.ordinal}")
                for item in self.media_selection.assignments
            )
            if image_slots != expected_slots:
                raise ValueError("article media selection does not match image blocks")
        return self


class ArticleValidationIssue(_FrozenModel):
    code: Literal[
        "article_length_out_of_bounds",
        "article_target_length_warning",
        "article_author_mismatch",
        "article_claim_id_duplicate",
        "article_claim_ref_unknown",
        "article_claim_unreferenced",
        "article_evidence_unknown",
        "article_brand_chunk_unknown",
        "article_source_set_mismatch",
        "article_media_slot_invalid",
        "article_version_bundle_invalid",
        "article_unsafe_markup",
        "article_unsafe_url",
        "article_unsafe_instruction",
        "article_content_fingerprint_mismatch",
    ]
    severity: Literal["error", "warning"]
    field: str = Field(min_length=1, max_length=120)
    claim_id: str | None = Field(default=None, max_length=80)


class OfficialAccountAuditVerdict(_FrozenModel):
    accepted: bool
    issue_codes: tuple[
        Literal[
            "fact_not_entailed",
            "brand_tone_mismatch",
            "privacy_risk",
            "safety_risk",
            "improper_distribution_instruction",
        ],
        ...,
    ] = Field(default=(), max_length=16)
    claim_ids: tuple[str, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def validate_verdict(self) -> OfficialAccountAuditVerdict:
        if self.accepted and (self.issue_codes or self.claim_ids):
            raise ValueError("accepted article audit cannot contain rejection issues")
        if not self.accepted and not self.issue_codes:
            raise ValueError("rejected article audit requires an issue code")
        return self


class RenderedOfficialAccountHtml(_FrozenModel):
    canonical_html: str = Field(min_length=1, max_length=200_000)
    render_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    renderer_version: str
    style_version: str
    template_version: str


def canonical_json(value: object) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        normalized = [_jsonable(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _jsonable(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def fingerprint(*parts: object) -> str:
    digest = sha256()
    for part in parts:
        encoded = canonical_json(part).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def article_package_fingerprint(article: ArticlePackage) -> str:
    payload = article.model_dump(mode="json", exclude={"content_fingerprint"})
    versions = payload.get("versions")
    if isinstance(versions, dict):
        for field in (
            "media_plan_version",
            "visual_query_version",
            "visual_selector_version",
            "context_media_plan_version",
        ):
            if versions.get(field) is None:
                versions.pop(field, None)
    if payload.get("media_selection") is None:
        payload.pop("media_selection", None)
    if payload.get("news_context_media") is None:
        payload.pop("news_context_media", None)
    return fingerprint(payload)


def _target_body_media_count(*, section_count: int, candidate_count: int) -> int:
    if section_count < 3 or section_count > 7:
        raise ValueError("official-account media plan requires three to seven sections")
    if candidate_count < 1 or candidate_count > 5:
        raise ValueError("official-account media plan requires one to five candidates")
    return (
        min(candidate_count, 5, max(3, section_count - 1))
        if candidate_count >= 3
        else candidate_count
    )


def _plan_body_media_slots_v1(*, section_count: int, candidate_count: int) -> tuple[int, ...]:
    target_count = _target_body_media_count(
        section_count=section_count,
        candidate_count=candidate_count,
    )
    placements = tuple((ordinal * section_count) // target_count for ordinal in range(target_count))
    if len(set(placements)) != target_count:
        raise ValueError("official-account media plan could not distribute distinct slots")
    return placements


def _plan_body_media_slots_v2(*, section_count: int, candidate_count: int) -> tuple[int, ...]:
    target_count = _target_body_media_count(
        section_count=section_count,
        candidate_count=candidate_count,
    )
    if target_count == 1:
        return (0,)
    placements = tuple(
        (ordinal * (section_count - 1) + (target_count - 1) // 2) // (target_count - 1)
        for ordinal in range(target_count)
    )
    if len(set(placements)) != target_count:
        raise ValueError("official-account semantic media plan could not balance distinct slots")
    return placements


def _plan_body_media_slots_v3(*, section_count: int, candidate_count: int) -> tuple[int, ...]:
    if section_count < 3 or section_count > 7:
        raise ValueError("official-account media plan requires three to seven sections")
    if candidate_count < 1 or candidate_count > 41:
        raise ValueError("official-account multimodal plan requires one to 41 candidates")
    target_count = min(candidate_count, 5, max(3, section_count - 1))
    if target_count == 1:
        return (0,)
    placements = tuple(
        (ordinal * (section_count - 1) + (target_count - 1) // 2) // (target_count - 1)
        for ordinal in range(target_count)
    )
    if len(set(placements)) != target_count:
        raise ValueError("official-account multimodal media plan could not balance slots")
    return placements


def _plan_body_media_slots_v4(*, section_count: int, candidate_count: int) -> tuple[int, ...]:
    if section_count < 3 or section_count > 7:
        raise ValueError("official-account media plan requires three to seven sections")
    if candidate_count < 1 or candidate_count > 41:
        raise ValueError("official-account multimodal plan requires one to 41 candidates")
    target_count = min(candidate_count, 5, section_count)
    if target_count == 1:
        return (0,)
    placements = tuple(
        (ordinal * (section_count - 1) + (target_count - 1) // 2) // (target_count - 1)
        for ordinal in range(target_count)
    )
    if len(set(placements)) != target_count:
        raise ValueError("official-account five-block media plan could not balance slots")
    return placements


def plan_body_media_slots(
    *,
    section_count: int,
    candidate_count: int,
    media_plan_version: str = OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
) -> tuple[int, ...]:
    """Return deterministic section indexes for an exact media-plan version."""
    if media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION:
        return _plan_body_media_slots_v1(
            section_count=section_count,
            candidate_count=candidate_count,
        )
    if media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION:
        return _plan_body_media_slots_v2(
            section_count=section_count,
            candidate_count=candidate_count,
        )
    if media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION:
        return _plan_body_media_slots_v3(
            section_count=section_count,
            candidate_count=candidate_count,
        )
    if media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION:
        return _plan_body_media_slots_v4(
            section_count=section_count,
            candidate_count=candidate_count,
        )
    raise ValueError("official-account media-plan version is unsupported")


def _normalize_semantic_text(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())[:1_200]


def _semantic_section_text(
    section: GeneratedArticleSection | ArticleSection,
) -> tuple[str, str]:
    body_parts: list[str] = []
    for block in section.blocks:
        if isinstance(block, ArticleBulletListBlock):
            body_parts.extend(block.items)
        elif isinstance(block, (ArticleParagraphBlock, ArticleQuoteBlock)):
            body_parts.append(block.text)
        if sum(len(part) for part in body_parts) >= 360:
            break
    return (
        _normalize_semantic_text(section.heading),
        _normalize_semantic_text("".join(body_parts)[:360]),
    )


def serialize_official_account_visual_query(
    *,
    topic_title: str,
    section: GeneratedArticleSection | ArticleSection,
) -> str:
    """Serialize only bounded reader-safe fields for one v7 text embedding request."""
    topic = " ".join(topic_title.split())[:300]
    heading = " ".join(section.heading.split())[:120]
    body_parts: list[str] = []
    for block in section.blocks:
        if isinstance(block, ArticleBulletListBlock):
            body_parts.extend(block.items)
        elif isinstance(block, (ArticleParagraphBlock, ArticleQuoteBlock)):
            body_parts.append(block.text)
        if sum(len(item) for item in body_parts) >= 360:
            break
    body = " ".join(" ".join(item.split()) for item in body_parts)[:360]
    value = f"主题：{topic}\n章节：{heading}\n正文摘要：{body}"
    if not topic or not heading or not body or len(value) > 900:
        raise ValueError("official-account visual query input is incomplete")
    if _UNSAFE_URL.search(value) or _UNSAFE_INSTRUCTION.search(value):
        raise ValueError("official-account visual query contains unsafe content")
    return value


def _semantic_pair_score(
    *,
    section: GeneratedArticleSection | ArticleSection,
    candidate: SemanticMediaCandidate,
) -> tuple[int, Literal["heading", "body", "fallback"]]:
    heading, body = _semantic_section_text(section)
    normalized_tags = tuple(_normalize_semantic_text(tag) for tag in candidate.semantic_tags)
    heading_matches = sum(tag in heading for tag in normalized_tags)
    body_matches = sum(tag in body for tag in normalized_tags)
    score = heading_matches * 100 + body_matches * 20
    if heading_matches:
        return score, "heading"
    if body_matches:
        return score, "body"
    return 0, "fallback"


def assign_semantic_body_media(
    *,
    sections: tuple[GeneratedArticleSection | ArticleSection, ...],
    candidates: tuple[SemanticMediaCandidate, ...],
) -> tuple[SemanticMediaAssignment, ...]:
    """Solve a bounded deterministic one-to-one semantic media assignment locally."""
    placements = plan_body_media_slots(
        section_count=len(sections),
        candidate_count=len(candidates),
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
    )
    if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
        raise ValueError("semantic media candidate IDs must be unique")
    if len({candidate.sha256 for candidate in candidates}) != len(candidates):
        raise ValueError("semantic media candidate checksums must be unique")
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (item.publication_priority, item.sha256, item.candidate_id),
        )
    )
    best: tuple[SemanticMediaCandidate, ...] | None = None
    best_total = -1
    for candidate_order in permutations(ordered, len(placements)):
        total = sum(
            _semantic_pair_score(section=sections[section_index], candidate=candidate)[0]
            for section_index, candidate in zip(placements, candidate_order, strict=True)
        )
        if total > best_total:
            best = candidate_order
            best_total = total
    if best is None:
        raise ValueError("semantic media assignment did not produce a candidate order")
    assignments: list[SemanticMediaAssignment] = []
    for ordinal, (section_index, candidate) in enumerate(zip(placements, best, strict=True)):
        score, score_band = _semantic_pair_score(
            section=sections[section_index],
            candidate=candidate,
        )
        reason_code: Literal[
            "semantic_heading_match",
            "semantic_body_match",
            "stable_fallback",
        ]
        if score_band == "heading":
            reason_code = "semantic_heading_match"
        elif score_band == "body":
            reason_code = "semantic_body_match"
        else:
            reason_code = "stable_fallback"
        assignments.append(
            SemanticMediaAssignment(
                ordinal=ordinal,
                section_index=section_index,
                candidate_id=candidate.candidate_id,
                sha256=candidate.sha256,
                alt_text=candidate.alt_text,
                caption_text=candidate.caption_text,
                score=score,
                score_band=score_band,
                reason_code=reason_code,
            )
        )
    return tuple(assignments)


def _similarity_band(value: float) -> Literal["very_high", "high", "medium", "low"]:
    if value >= 0.75:
        return "very_high"
    if value >= 0.5:
        return "high"
    if value >= 0.25:
        return "medium"
    return "low"


def assign_multimodal_body_media(
    *,
    sections: tuple[GeneratedArticleSection | ArticleSection, ...],
    candidates: tuple[SemanticMediaCandidate, ...],
    similarity_matrix: tuple[dict[str, float], ...],
    media_plan_version: str = OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
) -> tuple[SemanticMediaAssignment, ...]:
    """Maximum-weight bounded assignment without factorial candidate enumeration."""
    placements = plan_body_media_slots(
        section_count=len(sections),
        candidate_count=len(candidates),
        media_plan_version=media_plan_version,
    )
    if len(similarity_matrix) != len(placements):
        raise ValueError("multimodal similarity matrix does not cover every placement")
    if len({item.candidate_id for item in candidates}) != len(candidates):
        raise ValueError("multimodal candidate IDs must be unique")
    if len({item.sha256 for item in candidates}) != len(candidates):
        raise ValueError("multimodal candidate checksums must be unique")
    expected_ids = {item.candidate_id for item in candidates}
    for row in similarity_matrix:
        if set(row) != expected_ids or any(
            not isinstance(value, (int, float)) or not -1.0 <= float(value) <= 1.0
            for value in row.values()
        ):
            raise ValueError("multimodal similarity matrix is incomplete or invalid")
    ordered = tuple(
        sorted(
            candidates,
            key=lambda item: (item.publication_priority, item.sha256, item.candidate_id),
        )
    )
    # mask -> (similarity total, deterministic tag total, placement-ordered candidate indexes)
    empty_indexes = (-1,) * len(placements)
    states: dict[int, tuple[float, int, tuple[int, ...]]] = {0: (0.0, 0, empty_indexes)}
    for candidate_index, candidate in enumerate(ordered):
        updated = dict(states)
        for mask, (similarity_total, tag_total, indexes) in states.items():
            for placement_ordinal, section_index in enumerate(placements):
                bit = 1 << placement_ordinal
                if mask & bit:
                    continue
                similarity = float(similarity_matrix[placement_ordinal][candidate.candidate_id])
                tag_score = _semantic_pair_score(
                    section=sections[section_index], candidate=candidate
                )[0]
                next_mask = mask | bit
                next_indexes_list = list(indexes)
                next_indexes_list[placement_ordinal] = candidate_index
                next_indexes = tuple(next_indexes_list)
                candidate_state = (
                    similarity_total + similarity,
                    tag_total + tag_score,
                    next_indexes,
                )
                existing = updated.get(next_mask)
                if existing is None or (
                    candidate_state[0] > existing[0]
                    or (
                        candidate_state[0] == existing[0]
                        and (
                            candidate_state[1] > existing[1]
                            or (
                                candidate_state[1] == existing[1]
                                and candidate_state[2] < existing[2]
                            )
                        )
                    )
                ):
                    updated[next_mask] = candidate_state
        states = updated
    final = states.get((1 << len(placements)) - 1)
    if final is None or any(index < 0 for index in final[2]):
        raise ValueError("multimodal assignment did not cover every placement")
    assignments: list[SemanticMediaAssignment] = []
    for ordinal, (section_index, candidate_index) in enumerate(
        zip(placements, final[2], strict=True)
    ):
        candidate = ordered[candidate_index]
        similarity = float(similarity_matrix[ordinal][candidate.candidate_id])
        tag_score, score_band = _semantic_pair_score(
            section=sections[section_index], candidate=candidate
        )
        assignments.append(
            SemanticMediaAssignment(
                ordinal=ordinal,
                section_index=section_index,
                candidate_id=candidate.candidate_id,
                sha256=candidate.sha256,
                alt_text=candidate.alt_text,
                caption_text=candidate.caption_text,
                score=tag_score,
                score_band=score_band,
                reason_code="multimodal_similarity",
                selection_method="multimodal_embedding",
                similarity_band=_similarity_band(similarity),
            )
        )
    return tuple(assignments)


def assign_deterministic_body_media_v3(
    *,
    sections: tuple[GeneratedArticleSection | ArticleSection, ...],
    candidates: tuple[SemanticMediaCandidate, ...],
) -> tuple[SemanticMediaAssignment, ...]:
    """Apply the frozen tag score to the larger v7 approved-catalog pool."""
    placements = plan_body_media_slots(
        section_count=len(sections),
        candidate_count=len(candidates),
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
    )
    zero_matrix = tuple(
        {candidate.candidate_id: 0.0 for candidate in candidates} for _ in placements
    )
    semantic = assign_multimodal_body_media(
        sections=sections,
        candidates=candidates,
        similarity_matrix=zero_matrix,
    )
    deterministic: list[SemanticMediaAssignment] = []
    for item in semantic:
        reason: Literal[
            "semantic_heading_match",
            "semantic_body_match",
            "stable_fallback",
        ]
        if item.score_band == "heading":
            reason = "semantic_heading_match"
        elif item.score_band == "body":
            reason = "semantic_body_match"
        else:
            reason = "stable_fallback"
        deterministic.append(
            item.model_copy(
                update={
                    "reason_code": reason,
                    "selection_method": "deterministic_tag",
                    "similarity_band": None,
                }
            )
        )
    return tuple(deterministic)


def assign_deterministic_body_media_v4(
    *,
    sections: tuple[GeneratedArticleSection | ArticleSection, ...],
    candidates: tuple[SemanticMediaCandidate, ...],
) -> tuple[SemanticMediaAssignment, ...]:
    """Apply the frozen selector with the additive five-block placement policy."""
    placements = plan_body_media_slots(
        section_count=len(sections),
        candidate_count=len(candidates),
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    )
    zero_matrix = tuple(
        {candidate.candidate_id: 0.0 for candidate in candidates} for _ in placements
    )
    semantic = assign_multimodal_body_media(
        sections=sections,
        candidates=candidates,
        similarity_matrix=zero_matrix,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    )
    deterministic: list[SemanticMediaAssignment] = []
    for item in semantic:
        reason: Literal[
            "semantic_heading_match",
            "semantic_body_match",
            "stable_fallback",
        ]
        if item.score_band == "heading":
            reason = "semantic_heading_match"
        elif item.score_band == "body":
            reason = "semantic_body_match"
        else:
            reason = "stable_fallback"
        deterministic.append(
            item.model_copy(
                update={
                    "reason_code": reason,
                    "selection_method": "deterministic_tag",
                    "similarity_band": None,
                }
            )
        )
    return tuple(deterministic)


def build_article_package(
    *,
    draft: GeneratedArticleDraft,
    source: OfficialAccountSourceSnapshot,
    versions: ArticleVersionBundle,
    default_author: str,
    body_media_candidate_count: int = 1,
    semantic_media_assignments: tuple[SemanticMediaAssignment, ...] = (),
    media_selection: ArticleMediaSelectionSnapshot | None = None,
    news_context_media: ArticleNewsContextMediaSnapshot | None = None,
) -> ArticlePackage:
    version_kind = article_version_bundle_kind(versions)
    if version_kind == "v10" and not 5 <= len(draft.sections) <= 7:
        raise ValueError("official-account v10 article requires five to seven sections")
    is_historical_v1 = version_kind in {"v1", "v2", "v3", "v4"}
    is_historical_v2 = version_kind == "v5"
    is_semantic_v3 = version_kind == "v6"
    is_multimodal_v4 = version_kind in {"v7", "v8", "v9", "v10"}
    if (
        not is_historical_v1
        and not is_historical_v2
        and not is_semantic_v3
        and not is_multimodal_v4
    ):
        raise ValueError("official-account article schema/media-plan bundle is unsupported")
    placements: tuple[int, ...]
    if is_historical_v1:
        placements = (0,)
    elif is_historical_v2:
        placements = plan_body_media_slots(
            section_count=len(draft.sections),
            candidate_count=body_media_candidate_count,
            media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
        )
    elif is_semantic_v3:
        placements = tuple(item.section_index for item in semantic_media_assignments)
        expected = plan_body_media_slots(
            section_count=len(draft.sections),
            candidate_count=body_media_candidate_count,
            media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
        )
        if placements != expected or tuple(
            item.ordinal for item in semantic_media_assignments
        ) != tuple(range(len(expected))):
            raise ValueError("official-account semantic media assignments are incomplete")
    else:
        if media_selection is None:
            raise ValueError("official-account multimodal article requires a selection snapshot")
        placements = tuple(item.section_index for item in semantic_media_assignments)
        expected = plan_body_media_slots(
            section_count=len(draft.sections),
            candidate_count=body_media_candidate_count,
            media_plan_version=(
                OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION
                if version_kind == "v10"
                else OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION
            ),
        )
        if (
            placements != expected
            or tuple(item.ordinal for item in semantic_media_assignments)
            != tuple(range(len(expected)))
            or tuple(
                (item.ordinal, item.section_index, item.candidate_id, item.sha256)
                for item in semantic_media_assignments
            )
            != tuple(
                (
                    item.ordinal,
                    item.section_index,
                    item.candidate_ref,
                    item.publication_checksum,
                )
                for item in media_selection.assignments
            )
        ):
            raise ValueError("official-account multimodal selection snapshot is incomplete")
    assignment_by_section = {
        assignment.section_index: assignment for assignment in semantic_media_assignments
    }
    placement_to_ordinal = {
        section_index: ordinal for ordinal, section_index in enumerate(placements)
    }
    sections: list[ArticleSection] = []
    for index, section in enumerate(draft.sections):
        blocks: list[ArticleBlock] = list(section.blocks)
        ordinal = placement_to_ordinal.get(index)
        if ordinal is not None:
            blocks.append(
                ArticleImageBlock(
                    kind="image",
                    slot_key=cast(
                        Literal["body-0", "body-1", "body-2", "body-3", "body-4"],
                        f"body-{ordinal}",
                    ),
                    alt_text=(
                        assignment_by_section[index].alt_text
                        if is_semantic_v3 or is_multimodal_v4
                        else (
                            f"{source.topic_title}的本地正文配图"
                            if is_historical_v1
                            else f"{source.topic_title}的本地正文配图 {ordinal + 1}"
                        )
                    ),
                )
            )
        sections.append(ArticleSection(heading=section.heading, blocks=tuple(blocks)))
    used_evidence_ids = {
        evidence_id
        for claim in draft.claims
        if claim.kind == "external_fact"
        for evidence_id in claim.evidence_ids
    }
    source_by_id = {item.evidence_id: item for item in source.evidence}
    sources = tuple(
        ArticleSourceProjection(
            evidence_id=evidence_id,
            source_name=source_by_id[evidence_id].source_name,
            source_url=source_by_id[evidence_id].source_url,
            source_tier=source_by_id[evidence_id].source_tier,
        )
        for evidence_id in sorted(used_evidence_ids, key=str)
        if evidence_id in source_by_id
    )
    inherited = source.inherited_quality
    provisional = ArticlePackage(
        title=draft.title,
        digest=draft.digest,
        author=draft.author or default_author,
        lead=draft.lead,
        sections=tuple(sections),
        conclusion=draft.conclusion,
        claims=draft.claims,
        sources=sources,
        media_slots=tuple(
            [
                ArticleMediaSlot(
                    slot_key=cast(
                        Literal[
                            "body-0",
                            "body-1",
                            "body-2",
                            "body-3",
                            "body-4",
                            "cover-0",
                        ],
                        f"body-{ordinal}",
                    ),
                    role="body",
                    ordinal=ordinal,
                )
                for ordinal in range(len(placements))
            ]
            + [ArticleMediaSlot(slot_key="cover-0", role="cover")]
        ),
        topic_title=source.topic_title,
        quality=ArticleQualitySummary(
            inherited_copy_validation_passed=bool(inherited.get("copy_validation_passed", False)),
            inherited_copy_audit_accepted=bool(inherited.get("copy_audit_accepted", False)),
            inherited_image_validation_passed=bool(inherited.get("image_validation_passed", False)),
            inherited_image_audit_status=str(inherited.get("image_audit_status", "unknown"))[:40]
            or "unknown",
            manual_review_status=str(inherited.get("manual_review_status", "pending"))[:40]
            or "pending",
        ),
        versions=versions,
        media_selection=media_selection,
        news_context_media=news_context_media,
        content_fingerprint="0" * 64,
    )
    return provisional.model_copy(
        update={"content_fingerprint": article_package_fingerprint(provisional)}
    )


def article_body_character_count(article: ArticlePackage) -> int:
    values = [article.lead, article.conclusion]
    for section in article.sections:
        values.append(section.heading)
        for block in section.blocks:
            if isinstance(block, ArticleBulletListBlock):
                values.extend(block.items)
            elif isinstance(block, (ArticleParagraphBlock, ArticleQuoteBlock)):
                values.append(block.text)
    return sum(1 for value in values for character in value if not character.isspace())


def validate_article_package(
    article: ArticlePackage,
    *,
    source: OfficialAccountSourceSnapshot,
    default_author: str,
    min_characters: int,
    target_min_characters: int,
    target_max_characters: int,
    max_characters: int,
) -> tuple[ArticleValidationIssue, ...]:
    issues: list[ArticleValidationIssue] = []
    character_count = article_body_character_count(article)
    if character_count < min_characters or character_count > max_characters:
        issues.append(
            ArticleValidationIssue(
                code="article_length_out_of_bounds",
                severity="error",
                field="body",
            )
        )
    elif character_count < target_min_characters or character_count > target_max_characters:
        issues.append(
            ArticleValidationIssue(
                code="article_target_length_warning",
                severity="warning",
                field="body",
            )
        )
    if article.author != default_author:
        issues.append(
            ArticleValidationIssue(
                code="article_author_mismatch",
                severity="error",
                field="author",
            )
        )
    claim_ids = [claim.id for claim in article.claims]
    known_claim_ids = set(claim_ids)
    if len(claim_ids) != len(known_claim_ids):
        issues.append(
            ArticleValidationIssue(
                code="article_claim_id_duplicate",
                severity="error",
                field="claims",
            )
        )
    referenced_claim_ids: set[str] = set()
    for section_index, section in enumerate(article.sections):
        for block_index, block in enumerate(section.blocks):
            for claim_ref in block.claim_refs:
                if claim_ref not in known_claim_ids:
                    issues.append(
                        ArticleValidationIssue(
                            code="article_claim_ref_unknown",
                            severity="error",
                            field=f"sections.{section_index}.blocks.{block_index}.claim_refs",
                            claim_id=claim_ref,
                        )
                    )
                else:
                    referenced_claim_ids.add(claim_ref)
    for claim_id in sorted(known_claim_ids - referenced_claim_ids):
        issues.append(
            ArticleValidationIssue(
                code="article_claim_unreferenced",
                severity="error",
                field="claims",
                claim_id=claim_id,
            )
        )
    allowed_evidence_ids = {item.evidence_id for item in source.evidence}
    allowed_brand_ids = {item.brand_chunk_id for item in source.brand_context}
    used_evidence_ids: set[UUID] = set()
    for claim in article.claims:
        for evidence_id in claim.evidence_ids:
            used_evidence_ids.add(evidence_id)
            if evidence_id not in allowed_evidence_ids:
                issues.append(
                    ArticleValidationIssue(
                        code="article_evidence_unknown",
                        severity="error",
                        field="claims.evidence_ids",
                        claim_id=claim.id,
                    )
                )
        for brand_chunk_id in claim.brand_chunk_ids:
            if brand_chunk_id not in allowed_brand_ids:
                issues.append(
                    ArticleValidationIssue(
                        code="article_brand_chunk_unknown",
                        severity="error",
                        field="claims.brand_chunk_ids",
                        claim_id=claim.id,
                    )
                )
    if {item.evidence_id for item in article.sources} != used_evidence_ids:
        issues.append(
            ArticleValidationIssue(
                code="article_source_set_mismatch",
                severity="error",
                field="sources",
            )
        )
    body_slots = tuple(item for item in article.media_slots if item.role == "body")
    cover_slots = tuple(item for item in article.media_slots if item.role == "cover")
    image_slots = tuple(
        block.slot_key
        for section in article.sections
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    historical_schema_v1 = (
        article.versions.article_schema_version == OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V1_VERSION
        and article.versions.media_plan_version is None
    )
    historical_schema_v2 = (
        article.versions.article_schema_version == OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V2_VERSION
        and article.versions.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION
    )
    semantic_schema_v3 = (
        article.versions.article_schema_version == OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V3_VERSION
        and article.versions.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION
    )
    multimodal_schema = article.versions.article_schema_version in {
        OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
        OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
    } and article.versions.media_plan_version in {
        OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
        OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    }
    expected_body_ordinals = tuple(range(len(body_slots)))
    slots_valid = (
        len(cover_slots) == 1
        and cover_slots[0].slot_key == "cover-0"
        and cover_slots[0].ordinal == 0
        and tuple(slot.ordinal for slot in body_slots) == expected_body_ordinals
        and tuple(slot.slot_key for slot in body_slots)
        == tuple(f"body-{ordinal}" for ordinal in expected_body_ordinals)
        and image_slots == tuple(slot.slot_key for slot in body_slots)
        and (
            (historical_schema_v1 and len(body_slots) == 1)
            or (historical_schema_v2 and 1 <= len(body_slots) <= 5)
            or (semantic_schema_v3 and 1 <= len(body_slots) <= 5)
            or (multimodal_schema and 1 <= len(body_slots) <= 5)
        )
    )
    if not slots_valid:
        issues.append(
            ArticleValidationIssue(
                code="article_media_slot_invalid",
                severity="error",
                field="media_slots",
            )
        )
    if article_version_bundle_kind(article.versions) is None:
        issues.append(
            ArticleValidationIssue(
                code="article_version_bundle_invalid",
                severity="error",
                field="versions",
            )
        )
    for field, value in _iter_model_text(article):
        if _UNSAFE_MARKUP.search(value):
            issues.append(
                ArticleValidationIssue(
                    code="article_unsafe_markup",
                    severity="error",
                    field=field,
                )
            )
        if _UNSAFE_URL.search(value):
            issues.append(
                ArticleValidationIssue(
                    code="article_unsafe_url",
                    severity="error",
                    field=field,
                )
            )
        if _UNSAFE_INSTRUCTION.search(value):
            issues.append(
                ArticleValidationIssue(
                    code="article_unsafe_instruction",
                    severity="error",
                    field=field,
                )
            )
    if article.content_fingerprint != article_package_fingerprint(article):
        issues.append(
            ArticleValidationIssue(
                code="article_content_fingerprint_mismatch",
                severity="error",
                field="content_fingerprint",
            )
        )
    return tuple(issues)


def _iter_model_text(article: ArticlePackage) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = [
        ("title", article.title),
        ("digest", article.digest),
        ("author", article.author),
        ("lead", article.lead),
        ("conclusion", article.conclusion),
    ]
    for section_index, section in enumerate(article.sections):
        values.append((f"sections.{section_index}.heading", section.heading))
        for block_index, block in enumerate(section.blocks):
            prefix = f"sections.{section_index}.blocks.{block_index}"
            if isinstance(block, ArticleBulletListBlock):
                values.extend(
                    (f"{prefix}.items.{item_index}", item)
                    for item_index, item in enumerate(block.items)
                )
            elif isinstance(block, (ArticleParagraphBlock, ArticleQuoteBlock)):
                values.append((f"{prefix}.text", block.text))
    values.extend(
        (f"claims.{index}.text", claim.text) for index, claim in enumerate(article.claims)
    )
    return tuple(values)


_STYLE_V1 = {
    "root": "max-width:677px;margin:0 auto;color:#1f2937;font-size:17px;line-height:1.85;",
    "title": "margin:0 0 12px;font-size:30px;line-height:1.3;color:#102a43;",
    "digest": "margin:0 0 22px;color:#52606d;font-size:15px;",
    "lead": "margin:0 0 26px;padding:18px;background:#f0f7ff;border-left:4px solid #1677ff;",
    "heading": "margin:34px 0 14px;font-size:23px;line-height:1.45;color:#12395b;",
    "paragraph": "margin:0 0 18px;text-align:justify;",
    "quote": "margin:20px 0;padding:14px 18px;background:#f7f9fc;border-left:4px solid #f59e0b;",
    "callout": "margin:20px 0;padding:16px 18px;background:#fff7ed;border-radius:8px;",
    "list": "margin:0 0 20px;padding-left:24px;",
    "image": "display:block;width:100%;height:auto;margin:24px 0;border-radius:10px;",
    "sources": "margin-top:34px;padding-top:18px;border-top:1px solid #d9e2ec;font-size:14px;",
    "source_link": "color:#075985;text-decoration:underline;word-break:break-all;",
}


_STYLE_V2 = {
    "root": (
        "max-width:677px;margin:0 auto;padding:26px 18px 38px;background-color:#fbf8f1;"
        "color:#302e2b;font-size:15px;line-height:1.85;letter-spacing:0.8px;"
    ),
    "masthead": (
        "margin:0 0 34px;padding:28px 20px 24px;background-color:#f2ede2;"
        "border-top:5px solid #b9573f;"
    ),
    "eyebrow": (
        "margin:0 0 16px;color:#386b5a;font-size:11px;line-height:1.4;font-weight:bold;"
        "letter-spacing:2.4px;"
    ),
    "title": (
        "margin:0;color:#302e2b;font-size:28px;line-height:1.35;font-weight:bold;"
        "letter-spacing:0.4px;"
    ),
    "title_rule": "margin:18px 0 16px;border-top:1px solid #b9573f;font-size:0;line-height:0;",
    "digest": "margin:0 0 18px;color:#302e2b;font-size:14px;line-height:1.8;",
    "byline": "margin:0;color:#386b5a;font-size:12px;line-height:1.5;letter-spacing:1.2px;",
    "lead_box": (
        "margin:0 0 38px;padding:20px 18px;background-color:#edf1eb;border-left:3px solid #386b5a;"
    ),
    "lead_label": (
        "margin:0 0 9px;color:#386b5a;font-size:12px;line-height:1.4;"
        "font-weight:bold;letter-spacing:2px;"
    ),
    "lead": "margin:0;color:#302e2b;font-size:15px;line-height:1.9;text-align:justify;",
    "section": "margin:0 0 42px;",
    "heading": (
        "margin:0 0 21px;padding:0 0 13px;border-bottom:1px solid #d8d0c2;"
        "color:#302e2b;font-size:20px;line-height:1.5;font-weight:bold;letter-spacing:0.4px;"
    ),
    "section_number": (
        "display:inline-block;margin-right:12px;color:#b9573f;font-size:12px;line-height:1;"
        "font-weight:bold;letter-spacing:1.4px;vertical-align:middle;"
    ),
    "paragraph": (
        "margin:0 0 20px;color:#302e2b;font-size:15px;line-height:1.9;"
        "letter-spacing:0.8px;text-align:justify;word-break:break-word;"
    ),
    "list": (
        "margin:0 0 22px;padding:18px 18px 8px 38px;background-color:#f2ede2;"
        "color:#302e2b;font-size:15px;line-height:1.85;"
    ),
    "list_item": "margin:0 0 10px;padding-left:3px;",
    "quote": (
        "margin:24px 0;padding:18px 18px 18px 20px;background-color:#edf1eb;"
        "border-left:3px solid #386b5a;color:#302e2b;font-size:15px;line-height:1.85;"
    ),
    "quote_mark": (
        "display:block;margin:0 0 4px;color:#386b5a;font-size:28px;line-height:0.8;"
        "font-weight:bold;"
    ),
    "quote_text": "margin:0;text-align:justify;",
    "callout": (
        "margin:24px 0;padding:18px 18px 17px;background-color:#f2ede2;"
        "border-top:2px solid #b9573f;"
    ),
    "callout_label": (
        "margin:0 0 8px;color:#b9573f;font-size:12px;line-height:1.4;"
        "font-weight:bold;letter-spacing:1.8px;"
    ),
    "callout_text": "margin:0;color:#302e2b;font-size:15px;line-height:1.85;text-align:justify;",
    "image_frame": (
        "margin:28px 0;padding:6px 6px 11px;background-color:#f2ede2;border:1px solid #d8d0c2;"
    ),
    "image": "display:block;width:100%;height:auto;margin:0;",
    "image_caption": (
        "margin:9px 8px 0;color:#386b5a;font-size:12px;line-height:1.6;"
        "letter-spacing:0.5px;text-align:center;"
    ),
    "conclusion": ("margin:8px 0 0;padding:24px 20px;background-color:#386b5a;color:#fbf8f1;"),
    "conclusion_label": (
        "margin:0 0 11px;color:#fbf8f1;font-size:12px;line-height:1.4;"
        "font-weight:bold;letter-spacing:2px;"
    ),
    "conclusion_text": (
        "margin:0;color:#fbf8f1;font-size:15px;line-height:1.9;letter-spacing:0.8px;"
        "text-align:justify;"
    ),
    "closing_mark": (
        "margin:18px 0 0;color:#fbf8f1;font-size:10px;line-height:1.4;"
        "letter-spacing:3px;text-align:right;"
    ),
    "sources": (
        "margin-top:34px;padding-top:18px;border-top:1px solid #d8d0c2;"
        "color:#302e2b;font-size:12px;line-height:1.75;"
    ),
    "sources_heading": (
        "margin:0 0 12px;color:#386b5a;font-size:13px;line-height:1.5;"
        "font-weight:bold;letter-spacing:1.5px;"
    ),
    "source_list": "margin:0;padding-left:20px;",
    "source_item": "margin:0 0 8px;padding-left:2px;",
    "source_link": "color:#386b5a;text-decoration:underline;word-break:break-all;",
}

_STYLE_V3 = {
    "root": (
        "max-width:677px;margin:0 auto;padding:24px 18px 40px;background-color:#fbf8f1;"
        "color:#302e2b;font-size:15px;line-height:1.85;letter-spacing:0.7px;"
    ),
    "masthead": (
        "margin:0 0 22px;padding:25px 20px 23px;background-color:#f2ede2;"
        "border-top:5px solid #ad4f39;"
    ),
    "eyebrow": (
        "margin:0 0 15px;color:#386b5a;font-size:11px;line-height:1.4;font-weight:bold;"
        "letter-spacing:2.2px;"
    ),
    "title": (
        "margin:0;color:#302e2b;font-size:28px;line-height:1.35;font-weight:bold;"
        "letter-spacing:0.3px;"
    ),
    "title_rule": "margin:17px 0 15px;border-top:1px solid #ad4f39;font-size:0;line-height:0;",
    "value_label": (
        "margin:0 0 7px;color:#ad4f39;font-size:12px;line-height:1.4;font-weight:bold;"
        "letter-spacing:1.8px;"
    ),
    "digest": "margin:0 0 17px;color:#302e2b;font-size:15px;line-height:1.8;",
    "byline": "margin:0;color:#386b5a;font-size:12px;line-height:1.5;letter-spacing:1.1px;",
    "method_card": (
        "margin:0 0 24px;padding:18px 17px 9px;background-color:#edf1eb;"
        "border-left:3px solid #386b5a;"
    ),
    "method_heading": (
        "margin:0 0 11px;color:#386b5a;font-size:13px;line-height:1.5;font-weight:bold;"
        "letter-spacing:1.4px;"
    ),
    "method_item": (
        "margin:0 0 9px;color:#302e2b;font-size:14px;line-height:1.65;letter-spacing:0.5px;"
    ),
    "method_number": (
        "display:inline-block;margin-right:8px;color:#ad4f39;font-size:11px;line-height:1;"
        "font-weight:bold;letter-spacing:0.8px;vertical-align:middle;"
    ),
    "lead_box": (
        "margin:0 0 38px;padding:19px 18px;background-color:#f2ede2;border-top:2px solid #ad4f39;"
    ),
    "lead_label": (
        "margin:0 0 9px;color:#ad4f39;font-size:12px;line-height:1.4;font-weight:bold;"
        "letter-spacing:1.9px;"
    ),
    "lead": "margin:0;color:#302e2b;font-size:15px;line-height:1.9;text-align:justify;",
    "section": "margin:0 0 42px;",
    "heading": (
        "margin:0 0 20px;padding:0 0 12px;border-bottom:1px solid #d8d0c2;"
        "color:#302e2b;font-size:20px;line-height:1.5;font-weight:bold;letter-spacing:0.3px;"
    ),
    "section_number": (
        "display:block;margin:0 0 7px;color:#ad4f39;font-size:11px;line-height:1.2;"
        "font-weight:bold;letter-spacing:1.5px;"
    ),
    "paragraph": (
        "margin:0 0 17px;color:#302e2b;font-size:15px;line-height:1.9;"
        "letter-spacing:0.7px;text-align:justify;word-break:break-word;"
    ),
    "list": (
        "margin:0 0 22px;padding:18px 18px 8px 38px;background-color:#f2ede2;"
        "color:#302e2b;font-size:15px;line-height:1.85;"
    ),
    "list_item": "margin:0 0 10px;padding-left:3px;",
    "quote": (
        "margin:24px 0;padding:18px 18px 18px 20px;background-color:#edf1eb;"
        "border-left:3px solid #386b5a;color:#302e2b;font-size:15px;line-height:1.85;"
    ),
    "quote_mark": (
        "display:block;margin:0 0 4px;color:#386b5a;font-size:28px;line-height:0.8;"
        "font-weight:bold;"
    ),
    "quote_text": "margin:0;text-align:justify;",
    "callout": (
        "margin:24px 0;padding:18px 18px 17px;background-color:#f2ede2;"
        "border-top:2px solid #ad4f39;"
    ),
    "callout_label": (
        "margin:0 0 8px;color:#ad4f39;font-size:12px;line-height:1.4;font-weight:bold;"
        "letter-spacing:1.7px;"
    ),
    "callout_path": (
        "margin:0 0 9px;color:#386b5a;font-size:11px;line-height:1.5;letter-spacing:0.8px;"
    ),
    "callout_text": "margin:0;color:#302e2b;font-size:15px;line-height:1.85;text-align:justify;",
    "image_frame": (
        "margin:28px 0;padding:6px 6px 11px;background-color:#f2ede2;border:1px solid #d8d0c2;"
    ),
    "image": "display:block;width:100%;height:auto;margin:0;",
    "image_caption": (
        "margin:9px 8px 0;color:#386b5a;font-size:12px;line-height:1.6;"
        "letter-spacing:0.5px;text-align:center;"
    ),
    "conclusion": "margin:8px 0 0;padding:24px 20px;background-color:#386b5a;color:#fbf8f1;",
    "conclusion_label": (
        "margin:0 0 11px;color:#fbf8f1;font-size:12px;line-height:1.4;font-weight:bold;"
        "letter-spacing:1.9px;"
    ),
    "conclusion_text": (
        "margin:0;color:#fbf8f1;font-size:15px;line-height:1.9;letter-spacing:0.7px;"
        "text-align:justify;"
    ),
    "closing_mark": (
        "margin:18px 0 0;color:#fbf8f1;font-size:10px;line-height:1.4;"
        "letter-spacing:3px;text-align:right;"
    ),
    "sources": (
        "margin-top:34px;padding-top:18px;border-top:1px solid #d8d0c2;"
        "color:#302e2b;font-size:12px;line-height:1.75;"
    ),
    "sources_heading": (
        "margin:0 0 12px;color:#386b5a;font-size:13px;line-height:1.5;font-weight:bold;"
        "letter-spacing:1.4px;"
    ),
    "source_list": "margin:0;padding-left:20px;",
    "source_item": "margin:0 0 8px;padding-left:2px;",
    "source_link": "color:#386b5a;text-decoration:underline;word-break:break-all;",
    "fixture_source": "color:#52605b;word-break:break-all;",
}

_STYLE_V4 = {
    "root": (
        "max-width:677px;margin:0 auto;padding:24px 18px 42px;background-color:#fbf8f1;"
        "color:#26323d;font-size:15px;line-height:1.88;letter-spacing:0.6px;"
    ),
    "masthead": (
        "margin:0 0 22px;padding:25px 20px 23px;background-color:#eef3f3;"
        "border-top:5px solid #163c5a;"
    ),
    "eyebrow": (
        "margin:0 0 15px;color:#237482;font-size:11px;line-height:1.4;font-weight:bold;"
        "letter-spacing:2.2px;"
    ),
    "title": (
        "margin:0;color:#26323d;font-size:28px;line-height:1.35;font-weight:bold;"
        "letter-spacing:0.3px;"
    ),
    "title_rule": "margin:17px 0 15px;border-top:1px solid #8eaaaf;font-size:0;line-height:0;",
    "digest_label": (
        "margin:0 0 7px;color:#163c5a;font-size:12px;line-height:1.4;font-weight:bold;"
        "letter-spacing:1.8px;"
    ),
    "digest": "margin:0 0 17px;color:#26323d;font-size:15px;line-height:1.82;",
    "byline": "margin:0;color:#237482;font-size:12px;line-height:1.5;letter-spacing:1.1px;",
    "reading_map": (
        "margin:0 0 24px;padding:18px 17px 10px;background-color:#e3f5f6;"
        "border-left:4px solid #237482;"
    ),
    "reading_map_heading": (
        "margin:0 0 7px;color:#163c5a;font-size:13px;line-height:1.5;font-weight:bold;"
        "letter-spacing:1.4px;"
    ),
    "reading_map_note": (
        "margin:0 0 11px;color:#237482;font-size:12px;line-height:1.65;letter-spacing:0.4px;"
    ),
    "reading_map_list": "margin:0;padding-left:21px;color:#26323d;",
    "reading_map_item": "margin:0 0 8px;padding-left:2px;font-size:14px;line-height:1.7;",
    "lead_box": (
        "margin:0 0 38px;padding:19px 18px;background-color:#fff1c9;border-left:4px solid #c68716;"
    ),
    "lead_label": (
        "margin:0 0 9px;color:#7c5206;font-size:12px;line-height:1.4;font-weight:bold;"
        "letter-spacing:1.9px;"
    ),
    "lead": "margin:0;color:#26323d;font-size:15px;line-height:1.9;text-align:justify;",
    "section": "margin:0 0 42px;",
    "section_header": (
        "margin:0 0 20px;padding:14px 15px 13px;background-color:#eef3f3;"
        "border-left:5px solid #163c5a;"
    ),
    "section_number": (
        "display:block;margin:0 0 6px;color:#237482;font-size:11px;line-height:1.2;"
        "font-weight:bold;letter-spacing:1.7px;"
    ),
    "heading": (
        "margin:0;color:#163c5a;font-size:20px;line-height:1.5;font-weight:bold;"
        "letter-spacing:0.3px;"
    ),
    "paragraph": (
        "margin:0 0 17px;color:#26323d;font-size:15px;line-height:1.9;"
        "letter-spacing:0.6px;text-align:justify;word-break:break-word;"
    ),
    "list": (
        "margin:0 0 22px;padding:18px 18px 8px 38px;background-color:#eef3f3;"
        "border-top:2px solid #8eaaaf;color:#26323d;font-size:15px;line-height:1.88;"
    ),
    "list_item": "margin:0 0 10px;padding-left:3px;",
    "judgment": (
        "margin:24px 0;padding:18px 18px 17px;background-color:#e3f5f6;"
        "border-left:4px solid #237482;"
    ),
    "practice": (
        "margin:24px 0;padding:18px 18px 17px;background-color:#fff1c9;"
        "border-left:4px solid #c68716;"
    ),
    "judgment_label": (
        "margin:0 0 8px;color:#163c5a;font-size:12px;line-height:1.4;font-weight:bold;"
        "letter-spacing:1.7px;"
    ),
    "practice_label": (
        "margin:0 0 8px;color:#7c5206;font-size:12px;line-height:1.4;font-weight:bold;"
        "letter-spacing:1.7px;"
    ),
    "callout_text": "margin:0;color:#26323d;font-size:15px;line-height:1.88;text-align:justify;",
    "image_frame": (
        "margin:28px 0;padding:6px 6px 11px;background-color:#eef3f3;border:1px solid #8eaaaf;"
    ),
    "image": "display:block;width:100%;height:auto;margin:0;",
    "image_caption": (
        "margin:9px 8px 0;color:#237482;font-size:12px;line-height:1.6;"
        "letter-spacing:0.5px;text-align:center;"
    ),
    "conclusion": "margin:8px 0 0;padding:24px 20px;background-color:#163c5a;color:#fbf8f1;",
    "conclusion_label": (
        "margin:0 0 13px;color:#fbf8f1;font-size:12px;line-height:1.4;font-weight:bold;"
        "letter-spacing:1.9px;"
    ),
    "conclusion_card": (
        "margin:0 0 10px;padding:14px 14px 13px;border-left:3px solid #8fd5dc;"
        "background-color:#204a67;"
    ),
    "conclusion_number": (
        "display:block;margin:0 0 5px;color:#bceef0;font-size:11px;line-height:1.2;"
        "font-weight:bold;letter-spacing:1.4px;"
    ),
    "conclusion_text": (
        "margin:0;color:#fbf8f1;font-size:15px;line-height:1.9;letter-spacing:0.6px;"
        "text-align:justify;"
    ),
    "closing_mark": (
        "margin:17px 0 0;color:#bceef0;font-size:10px;line-height:1.4;"
        "letter-spacing:3px;text-align:right;"
    ),
    "sources": (
        "margin-top:34px;padding-top:18px;border-top:1px solid #8eaaaf;"
        "color:#26323d;font-size:12px;line-height:1.75;"
    ),
    "sources_heading": (
        "margin:0 0 12px;color:#163c5a;font-size:13px;line-height:1.5;font-weight:bold;"
        "letter-spacing:1.4px;"
    ),
    "source_list": "margin:0;padding-left:20px;",
    "source_item": "margin:0 0 8px;padding-left:2px;",
    "source_link": "color:#237482;text-decoration:underline;word-break:break-all;",
    "fixture_source": "color:#4c5f67;word-break:break-all;",
}

_RENDER_VERSION_V1 = (
    OFFICIAL_ACCOUNT_RENDERER_V1_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V1_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V1_VERSION,
)
_RENDER_VERSION_V2 = (
    OFFICIAL_ACCOUNT_RENDERER_V2_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V2_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V2_VERSION,
)
_RENDER_VERSION_V3 = (
    OFFICIAL_ACCOUNT_RENDERER_V3_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V3_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V3_VERSION,
)
_RENDER_VERSION_V4 = (
    OFFICIAL_ACCOUNT_RENDERER_V4_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V4_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V4_VERSION,
)
_RENDER_VERSION_V5 = (
    OFFICIAL_ACCOUNT_RENDERER_V5_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V5_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V5_VERSION,
)
_RENDER_VERSION_V6 = (
    OFFICIAL_ACCOUNT_RENDERER_V6_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V6_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V6_VERSION,
)
_RENDER_VERSION_V7 = (
    OFFICIAL_ACCOUNT_RENDERER_VERSION,
    OFFICIAL_ACCOUNT_STYLE_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
)
_RENDER_VERSION_V8 = (
    OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
)


def _render_wechat_html_v1(article: ArticlePackage) -> str:
    parts = [f'<section style="{_STYLE_V1["root"]}">']
    parts.append(f'<h1 style="{_STYLE_V1["title"]}">{escape(article.title)}</h1>')
    parts.append(f'<p style="{_STYLE_V1["digest"]}">{escape(article.digest)}</p>')
    parts.append(f'<p style="{_STYLE_V1["lead"]}">{escape(article.lead)}</p>')
    for section in article.sections:
        parts.append(f'<section><h2 style="{_STYLE_V1["heading"]}">{escape(section.heading)}</h2>')
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                parts.append(f'<p style="{_STYLE_V1["paragraph"]}">{escape(block.text)}</p>')
            elif isinstance(block, ArticleBulletListBlock):
                items = "".join(f"<li>{escape(item)}</li>" for item in block.items)
                parts.append(f'<ul style="{_STYLE_V1["list"]}">{items}</ul>')
            elif isinstance(block, ArticleQuoteBlock) and block.kind == "quote":
                parts.append(
                    f'<blockquote style="{_STYLE_V1["quote"]}">{escape(block.text)}</blockquote>'
                )
            elif isinstance(block, ArticleQuoteBlock):
                parts.append(
                    f'<p style="{_STYLE_V1["callout"]}"><strong>{escape(block.text)}</strong></p>'
                )
            elif isinstance(block, ArticleImageBlock):
                parts.append(
                    f'<img src="{OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER}" '
                    f'alt="{escape(block.alt_text, quote=True)}" style="{_STYLE_V1["image"]}">'
                )
        parts.append("</section>")
    parts.append(f'<p style="{_STYLE_V1["paragraph"]}">{escape(article.conclusion)}</p>')
    parts.append(f'<section style="{_STYLE_V1["sources"]}"><h2>来源</h2><ol>')
    for source in article.sources:
        source_url = _validated_source_url(source.source_url)
        parts.append(
            '<li><a rel="noopener noreferrer" referrerpolicy="no-referrer" '
            f'href="{escape(source_url, quote=True)}" '
            f'style="{_STYLE_V1["source_link"]}">{escape(source.source_name)}</a></li>'
        )
    parts.append("</ol></section></section>")
    return "".join(parts)


def _render_wechat_html_v2(article: ArticlePackage) -> str:
    parts = [f'<section style="{_STYLE_V2["root"]}">']
    parts.append(f'<section style="{_STYLE_V2["masthead"]}">')
    parts.append(f'<p style="{_STYLE_V2["eyebrow"]}">SCIENCE NOTES · 教育观察</p>')
    parts.append(f'<h1 style="{_STYLE_V2["title"]}">{escape(article.title)}</h1>')
    parts.append(f'<p style="{_STYLE_V2["title_rule"]}"><br></p>')
    parts.append(f'<p style="{_STYLE_V2["digest"]}">{escape(article.digest)}</p>')
    parts.append(f'<p style="{_STYLE_V2["byline"]}">撰文 · {escape(article.author)}</p>')
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE_V2["lead_box"]}">')
    parts.append(f'<p style="{_STYLE_V2["lead_label"]}">导读</p>')
    parts.append(f'<p style="{_STYLE_V2["lead"]}">{escape(article.lead)}</p>')
    parts.append("</section>")
    for index, section in enumerate(article.sections, start=1):
        parts.append(f'<section style="{_STYLE_V2["section"]}">')
        parts.append(f'<h2 style="{_STYLE_V2["heading"]}">')
        parts.append(
            f'<span style="{_STYLE_V2["section_number"]}">{index:02d}</span>'
            f"{escape(section.heading)}</h2>"
        )
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                parts.append(f'<p style="{_STYLE_V2["paragraph"]}">{escape(block.text)}</p>')
            elif isinstance(block, ArticleBulletListBlock):
                items = "".join(
                    f'<li style="{_STYLE_V2["list_item"]}">{escape(item)}</li>'
                    for item in block.items
                )
                parts.append(f'<ul style="{_STYLE_V2["list"]}">{items}</ul>')
            elif isinstance(block, ArticleQuoteBlock) and block.kind == "quote":
                parts.append(f'<blockquote style="{_STYLE_V2["quote"]}">')
                parts.append(f'<span style="{_STYLE_V2["quote_mark"]}">“</span>')
                parts.append(f'<p style="{_STYLE_V2["quote_text"]}">{escape(block.text)}</p>')
                parts.append("</blockquote>")
            elif isinstance(block, ArticleQuoteBlock):
                parts.append(f'<section style="{_STYLE_V2["callout"]}">')
                parts.append(f'<p style="{_STYLE_V2["callout_label"]}">实践提示</p>')
                parts.append(f'<p style="{_STYLE_V2["callout_text"]}">{escape(block.text)}</p>')
                parts.append("</section>")
            elif isinstance(block, ArticleImageBlock):
                alt_text = escape(block.alt_text, quote=True)
                parts.append(f'<section style="{_STYLE_V2["image_frame"]}">')
                parts.append(
                    f'<img src="{OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER}" '
                    f'alt="{alt_text}" style="{_STYLE_V2["image"]}">'
                )
                parts.append(
                    f'<p style="{_STYLE_V2["image_caption"]}">{escape(block.alt_text)}</p>'
                )
                parts.append("</section>")
        parts.append("</section>")
    parts.append(f'<section style="{_STYLE_V2["conclusion"]}">')
    parts.append(f'<p style="{_STYLE_V2["conclusion_label"]}">写在最后</p>')
    parts.append(f'<p style="{_STYLE_V2["conclusion_text"]}">{escape(article.conclusion)}</p>')
    parts.append(f'<p style="{_STYLE_V2["closing_mark"]}">— END —</p>')
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE_V2["sources"]}">')
    parts.append(f'<h2 style="{_STYLE_V2["sources_heading"]}">资料来源</h2>')
    parts.append(f'<ol style="{_STYLE_V2["source_list"]}">')
    for source in article.sources:
        source_url = _validated_source_url(source.source_url)
        parts.append(f'<li style="{_STYLE_V2["source_item"]}">')
        parts.append(
            '<a rel="noopener noreferrer" referrerpolicy="no-referrer" '
            f'href="{escape(source_url, quote=True)}" '
            f'style="{_STYLE_V2["source_link"]}">{escape(source.source_name)}</a></li>'
        )
    parts.append("</ol></section></section>")
    return "".join(parts)


_MOBILE_SENTENCE = re.compile(r".+?(?:[。！？；]+[”’」』】》]?|$)", re.DOTALL)


def _split_mobile_paragraph(text: str) -> tuple[str, ...]:
    if len(text) <= 140:
        return (text,)
    sentences = tuple(match.group(0) for match in _MOBILE_SENTENCE.finditer(text))
    if len(sentences) < 2 or "".join(sentences) != text:
        return (text,)
    paragraphs: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > 120:
            paragraphs.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        if paragraphs and len(current) < 36:
            paragraphs[-1] += current
        else:
            paragraphs.append(current)
    return tuple(paragraphs)


def _render_v3_paragraphs(text: str, *, style: str) -> list[str]:
    return [f'<p style="{style}">{escape(part)}</p>' for part in _split_mobile_paragraph(text)]


def _is_sanitized_fixture_source(source_url: str) -> bool:
    return urlsplit(source_url).hostname == "example.invalid"


def _render_wechat_html_v3(article: ArticlePackage) -> str:
    parts = [f'<section style="{_STYLE_V3["root"]}">']
    parts.append(f'<section style="{_STYLE_V3["masthead"]}">')
    parts.append(f'<p style="{_STYLE_V3["eyebrow"]}">SCIENCE EXPLORER · 家庭探究手册</p>')
    parts.append(f'<h1 style="{_STYLE_V3["title"]}">{escape(article.title)}</h1>')
    parts.append(f'<p style="{_STYLE_V3["title_rule"]}"><br></p>')
    parts.append(f'<p style="{_STYLE_V3["value_label"]}">先说结论</p>')
    parts.append(f'<p style="{_STYLE_V3["digest"]}">{escape(article.digest)}</p>')
    parts.append(f'<p style="{_STYLE_V3["byline"]}">撰文 · {escape(article.author)}</p>')
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE_V3["method_card"]}">')
    parts.append(f'<p style="{_STYLE_V3["method_heading"]}">这篇文章，陪你走完四步</p>')
    for number, label in enumerate(
        ("孩子行动", "看见证据", "家长协作", "下一次迭代"),
        start=1,
    ):
        parts.append(f'<p style="{_STYLE_V3["method_item"]}">')
        parts.append(f'<span style="{_STYLE_V3["method_number"]}">{number:02d}</span>{label}</p>')
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE_V3["lead_box"]}">')
    parts.append(f'<p style="{_STYLE_V3["lead_label"]}">从一个问题开始</p>')
    parts.extend(_render_v3_paragraphs(article.lead, style=_STYLE_V3["lead"]))
    parts.append("</section>")
    for index, section in enumerate(article.sections, start=1):
        parts.append(f'<section style="{_STYLE_V3["section"]}">')
        parts.append(f'<h2 style="{_STYLE_V3["heading"]}">')
        parts.append(
            f'<span style="{_STYLE_V3["section_number"]}">探索 {index:02d}</span>'
            f"{escape(section.heading)}</h2>"
        )
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                parts.extend(_render_v3_paragraphs(block.text, style=_STYLE_V3["paragraph"]))
            elif isinstance(block, ArticleBulletListBlock):
                items = "".join(
                    f'<li style="{_STYLE_V3["list_item"]}">{escape(item)}</li>'
                    for item in block.items
                )
                parts.append(f'<ul style="{_STYLE_V3["list"]}">{items}</ul>')
            elif isinstance(block, ArticleQuoteBlock) and block.kind == "quote":
                parts.append(f'<blockquote style="{_STYLE_V3["quote"]}">')
                parts.append(f'<span style="{_STYLE_V3["quote_mark"]}">“</span>')
                parts.append(f'<p style="{_STYLE_V3["quote_text"]}">{escape(block.text)}</p>')
                parts.append("</blockquote>")
            elif isinstance(block, ArticleQuoteBlock):
                parts.append(f'<section style="{_STYLE_V3["callout"]}">')
                parts.append(f'<p style="{_STYLE_V3["callout_label"]}">家庭探索任务卡</p>')
                parts.append(
                    f'<p style="{_STYLE_V3["callout_path"]}">'
                    "孩子行动 → 记录证据 → 一起复盘 → 再试一次</p>"
                )
                parts.append(f'<p style="{_STYLE_V3["callout_text"]}">{escape(block.text)}</p>')
                parts.append("</section>")
            elif isinstance(block, ArticleImageBlock):
                alt_text = escape(block.alt_text, quote=True)
                parts.append(f'<section style="{_STYLE_V3["image_frame"]}">')
                parts.append(
                    f'<img src="{OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER}" '
                    f'alt="{alt_text}" style="{_STYLE_V3["image"]}">'
                )
                parts.append(
                    f'<p style="{_STYLE_V3["image_caption"]}">观察提示 · '
                    f"{escape(block.alt_text)}</p>"
                )
                parts.append("</section>")
        parts.append("</section>")
    parts.append(f'<section style="{_STYLE_V3["conclusion"]}">')
    parts.append(f'<p style="{_STYLE_V3["conclusion_label"]}">带走一个下一步</p>')
    parts.extend(_render_v3_paragraphs(article.conclusion, style=_STYLE_V3["conclusion_text"]))
    parts.append(f'<p style="{_STYLE_V3["closing_mark"]}">— KEEP EXPLORING —</p>')
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE_V3["sources"]}">')
    parts.append(f'<h2 style="{_STYLE_V3["sources_heading"]}">资料来源与边界</h2>')
    parts.append(f'<ol style="{_STYLE_V3["source_list"]}">')
    for source in article.sources:
        source_url = _validated_source_url(source.source_url)
        parts.append(f'<li style="{_STYLE_V3["source_item"]}">')
        if _is_sanitized_fixture_source(source_url):
            parts.append(
                f'<span style="{_STYLE_V3["fixture_source"]}">'
                f"{escape(source.source_name)} · 脱敏演示来源（不提供外链）</span></li>"
            )
        else:
            parts.append(
                '<a rel="noopener noreferrer" referrerpolicy="no-referrer" '
                f'href="{escape(source_url, quote=True)}" '
                f'style="{_STYLE_V3["source_link"]}">{escape(source.source_name)}</a></li>'
            )
    parts.append("</ol></section></section>")
    return "".join(parts)


def _split_conclusion_cards(text: str) -> tuple[str, ...]:
    sentences = tuple(match.group(0) for match in _MOBILE_SENTENCE.finditer(text))
    if len(sentences) < 2 or "".join(sentences) != text:
        return (text,)
    if len(sentences) <= 3:
        return sentences
    cards: list[str] = []
    cursor = 0
    for card_index in range(3):
        remaining_sentences = len(sentences) - cursor
        remaining_cards = 3 - card_index
        take = (remaining_sentences + remaining_cards - 1) // remaining_cards
        cards.append("".join(sentences[cursor : cursor + take]))
        cursor += take
    return tuple(cards)


def _render_wechat_html_v4(
    article: ArticlePackage,
    *,
    multi_image: bool = False,
    reader_copy: bool = False,
    news_context: bool = False,
) -> str:
    parts = [f'<section style="{_STYLE_V4["root"]}">']
    parts.append(f'<section style="{_STYLE_V4["masthead"]}">')
    parts.append(f'<p style="{_STYLE_V4["eyebrow"]}">SCIENCE FIELD GUIDE · 科学教育观察</p>')
    parts.append(f'<h1 style="{_STYLE_V4["title"]}">{escape(article.title)}</h1>')
    parts.append(f'<p style="{_STYLE_V4["title_rule"]}"><br></p>')
    parts.append(f'<p style="{_STYLE_V4["digest_label"]}">先看核心判断</p>')
    parts.append(f'<p style="{_STYLE_V4["digest"]}">{escape(article.digest)}</p>')
    parts.append(f'<p style="{_STYLE_V4["byline"]}">撰文 · {escape(article.author)}</p>')
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE_V4["reading_map"]}">')
    parts.append(f'<p style="{_STYLE_V4["reading_map_heading"]}">家长先看</p>')
    parts.append(f'<p style="{_STYLE_V4["reading_map_note"]}">这篇文章将依次回答以下问题</p>')
    parts.append(f'<ol style="{_STYLE_V4["reading_map_list"]}">')
    for section in article.sections[:5]:
        parts.append(f'<li style="{_STYLE_V4["reading_map_item"]}">{escape(section.heading)}</li>')
    parts.append("</ol></section>")
    parts.append(f'<section style="{_STYLE_V4["lead_box"]}">')
    parts.append(f'<p style="{_STYLE_V4["lead_label"]}">从家长关心的问题开始</p>')
    parts.extend(_render_v3_paragraphs(article.lead, style=_STYLE_V4["lead"]))
    parts.append("</section>")
    for index, section in enumerate(article.sections, start=1):
        parts.append(f'<section style="{_STYLE_V4["section"]}">')
        parts.append(f'<section style="{_STYLE_V4["section_header"]}">')
        parts.append(f'<p style="{_STYLE_V4["section_number"]}">PART {index:02d} · FIELD NOTE</p>')
        parts.append(f'<h2 style="{_STYLE_V4["heading"]}">{escape(section.heading)}</h2>')
        parts.append("</section>")
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                parts.extend(_render_v3_paragraphs(block.text, style=_STYLE_V4["paragraph"]))
            elif isinstance(block, ArticleBulletListBlock):
                items = "".join(
                    f'<li style="{_STYLE_V4["list_item"]}">{escape(item)}</li>'
                    for item in block.items
                )
                parts.append(f'<ul style="{_STYLE_V4["list"]}">{items}</ul>')
            elif isinstance(block, ArticleQuoteBlock):
                is_judgment = block.kind == "quote"
                card_style = _STYLE_V4["judgment" if is_judgment else "practice"]
                label_style = _STYLE_V4["judgment_label" if is_judgment else "practice_label"]
                label = "关键判断" if is_judgment else "家庭实践"
                parts.append(f'<section style="{card_style}">')
                parts.append(f'<p style="{label_style}">{label}</p>')
                parts.extend(_render_v3_paragraphs(block.text, style=_STYLE_V4["callout_text"]))
                parts.append("</section>")
            elif isinstance(block, ArticleImageBlock):
                alt_text = escape(block.alt_text, quote=True)
                placeholder = (
                    body_media_placeholder(int(block.slot_key.removeprefix("body-")))
                    if multi_image
                    else OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER
                )
                parts.append(f'<section style="{_STYLE_V4["image_frame"]}">')
                parts.append(
                    f'<img src="{placeholder}" alt="{alt_text}" style="{_STYLE_V4["image"]}">'
                )
                caption = escape(block.alt_text)
                parts.append(
                    f'<p style="{_STYLE_V4["image_caption"]}">'
                    f"{caption if reader_copy else '观察记录 · ' + caption}</p>"
                )
                parts.append("</section>")
        if news_context:
            snapshot = article.news_context_media
            if snapshot is None:
                raise ValueError("v9 renderer requires a news-context snapshot")
            context_item = next(
                (item for item in snapshot.items if item.section_index == index - 1),
                None,
            )
            if context_item is not None:
                alt_text = escape(context_item.alt_text, quote=True)
                parts.append(
                    '<figure data-media-role="news-context" '
                    'data-context-only-not-evidence="true" '
                    'style="margin:26px 0 30px;padding:10px;background:#f5f7fb;'
                    'border:1px solid #d8e0ef;border-radius:14px;">'
                )
                parts.append(
                    f'<img src="{context_media_placeholder(context_item.ordinal)}" '
                    f'alt="{alt_text}" style="display:block;width:100%;height:auto;'
                    'border-radius:9px;object-fit:contain;">'
                )
                caption = context_item.caption or context_item.alt_text
                parts.append(
                    '<figcaption style="padding:10px 4px 2px;color:#526179;font-size:12px;'
                    'line-height:1.7;">'
                    f"{escape(caption)}"
                )
                if context_item.credit:
                    parts.append(f" · {escape(context_item.credit)}")
                parts.append("<br>")
                source_page_url = escape(
                    _validated_source_url(context_item.source_page_url), quote=True
                )
                parts.append(
                    '<a rel="noopener noreferrer" referrerpolicy="no-referrer" '
                    f'href="{source_page_url}" '
                    'style="color:#175cd3;text-decoration:underline;">新闻原文</a>'
                )
                parts.append(
                    '<span style="display:inline-block;margin-left:8px;color:#b54708;'
                    'font-weight:700;">发布权限未验证 · 仅作上下文参考，非事实证据</span>'
                )
                parts.append("</figcaption></figure>")
        parts.append("</section>")
    parts.append(f'<section style="{_STYLE_V4["conclusion"]}">')
    parts.append(f'<p style="{_STYLE_V4["conclusion_label"]}">给家长的三句话</p>')
    for index, conclusion_part in enumerate(_split_conclusion_cards(article.conclusion), start=1):
        parts.append(f'<section style="{_STYLE_V4["conclusion_card"]}">')
        parts.append(f'<span style="{_STYLE_V4["conclusion_number"]}">{index:02d}</span>')
        parts.append(f'<p style="{_STYLE_V4["conclusion_text"]}">{escape(conclusion_part)}</p>')
        parts.append("</section>")
    parts.append(f'<p style="{_STYLE_V4["closing_mark"]}">— KEEP ASKING WHY —</p>')
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE_V4["sources"]}">')
    parts.append(f'<h2 style="{_STYLE_V4["sources_heading"]}">资料来源与适用边界</h2>')
    parts.append(f'<ol style="{_STYLE_V4["source_list"]}">')
    for source in article.sources:
        source_url = _validated_source_url(source.source_url)
        parts.append(f'<li style="{_STYLE_V4["source_item"]}">')
        if _is_sanitized_fixture_source(source_url):
            fixture_label = (
                f"{escape(source.source_name)} · 内容边界说明（不提供外链）"
                if reader_copy
                else f"{escape(source.source_name)} · 脱敏演示来源（不提供外链）"
            )
            parts.append(f'<span style="{_STYLE_V4["fixture_source"]}">{fixture_label}</span></li>')
        else:
            parts.append(
                '<a rel="noopener noreferrer" referrerpolicy="no-referrer" '
                f'href="{escape(source_url, quote=True)}" '
                f'style="{_STYLE_V4["source_link"]}">{escape(source.source_name)}</a></li>'
            )
    parts.append("</ol></section></section>")
    return "".join(parts)


def render_wechat_html(
    article: ArticlePackage,
    *,
    renderer_version: str | None = None,
    style_version: str | None = None,
    template_version: str | None = None,
) -> RenderedOfficialAccountHtml:
    article_render_versions = (
        article.versions.renderer_version,
        article.versions.style_version,
        article.versions.template_version,
    )
    selected_versions = (
        renderer_version or article_render_versions[0],
        style_version or article_render_versions[1],
        template_version or article_render_versions[2],
    )
    if selected_versions != article_render_versions:
        raise ValueError("requested render version bundle must match the article package")
    if article_version_bundle_kind(article.versions) is None:
        raise ValueError("official-account article/render version bundle is unsupported")
    if selected_versions == _RENDER_VERSION_V1:
        canonical_html = _render_wechat_html_v1(article)
    elif selected_versions == _RENDER_VERSION_V2:
        canonical_html = _render_wechat_html_v2(article)
    elif selected_versions == _RENDER_VERSION_V3:
        canonical_html = _render_wechat_html_v3(article)
    elif selected_versions == _RENDER_VERSION_V4:
        canonical_html = _render_wechat_html_v4(article)
    elif selected_versions == _RENDER_VERSION_V5:
        canonical_html = _render_wechat_html_v4(article, multi_image=True)
    elif selected_versions in {_RENDER_VERSION_V6, _RENDER_VERSION_V7}:
        canonical_html = _render_wechat_html_v4(
            article,
            multi_image=True,
            reader_copy=True,
        )
    elif selected_versions == _RENDER_VERSION_V8:
        canonical_html = _render_wechat_html_v4(
            article,
            multi_image=True,
            reader_copy=True,
            news_context=True,
        )
    else:
        raise ValueError("official-account render version bundle is unsupported")
    expected_body_slots = tuple(slot for slot in article.media_slots if slot.role == "body")
    if selected_versions in {
        _RENDER_VERSION_V5,
        _RENDER_VERSION_V6,
        _RENDER_VERSION_V7,
        _RENDER_VERSION_V8,
    }:
        if any(
            canonical_html.count(body_media_placeholder(slot.ordinal)) != 1
            for slot in expected_body_slots
        ) or any(
            body_media_placeholder(ordinal) in canonical_html
            for ordinal in range(len(expected_body_slots), 5)
        ):
            raise ValueError("canonical article render has an invalid multi-image placeholder set")
    elif canonical_html.count(OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER) != 1:
        raise ValueError("canonical article render must contain exactly one body-media placeholder")
    if selected_versions == _RENDER_VERSION_V8:
        context_items = article.news_context_media.items if article.news_context_media else ()
        if any(
            canonical_html.count(context_media_placeholder(item.ordinal)) != 1
            for item in context_items
        ) or any(
            context_media_placeholder(ordinal) in canonical_html
            for ordinal in range(len(context_items), 2)
        ):
            raise ValueError(
                "canonical article render has an invalid context-media placeholder set"
            )
    render_fingerprint = fingerprint(
        article.content_fingerprint,
        *selected_versions,
        canonical_html,
    )
    return RenderedOfficialAccountHtml(
        canonical_html=canonical_html,
        render_fingerprint=render_fingerprint,
        renderer_version=selected_versions[0],
        style_version=selected_versions[1],
        template_version=selected_versions[2],
    )


def resolve_body_media_placeholder(canonical_html: str, media_url: str) -> str:
    if canonical_html.count(OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER) != 1:
        raise ValueError("canonical HTML has an invalid body-media placeholder count")
    if not media_url.startswith("/api/v1/official-account-local/media/"):
        raise ValueError("local article media URL is outside the controlled API path")
    resolved = canonical_html.replace(
        OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER,
        escape(media_url, quote=True),
    )
    if OFFICIAL_ACCOUNT_BODY_MEDIA_PLACEHOLDER in resolved:
        raise ValueError("resolved local draft HTML still contains a media placeholder")
    return resolved


def resolve_body_media_placeholders(
    canonical_html: str,
    media: tuple[tuple[int, str], ...],
) -> str:
    if not media or len(media) > 5:
        raise ValueError("local article requires one to five body media results")
    ordinals = tuple(ordinal for ordinal, _url in media)
    if ordinals != tuple(range(len(media))):
        raise ValueError("local article body media ordinals must be contiguous and ordered")
    resolved = canonical_html
    for ordinal, media_url in media:
        placeholder = body_media_placeholder(ordinal)
        if resolved.count(placeholder) != 1:
            raise ValueError("canonical HTML has an invalid body-media placeholder set")
        if not media_url.startswith("/api/v1/official-account-local/media/"):
            raise ValueError("local article media URL is outside the controlled API path")
        resolved = resolved.replace(placeholder, escape(media_url, quote=True))
    if any(body_media_placeholder(ordinal) in resolved for ordinal in range(5)):
        raise ValueError("resolved local draft HTML still contains a media placeholder")
    return resolved


def resolve_context_media_placeholders(
    canonical_html: str,
    media: tuple[tuple[int, str], ...],
) -> str:
    if len(media) > 2:
        raise ValueError("local article accepts at most two news-context media results")
    if tuple(item[0] for item in media) != tuple(range(len(media))):
        raise ValueError("local article context media must be ordered and contiguous")
    resolved = canonical_html
    for ordinal, media_url in media:
        placeholder = context_media_placeholder(ordinal)
        if resolved.count(placeholder) != 1:
            raise ValueError("canonical HTML has an invalid context-media placeholder set")
        if not media_url.startswith("/api/v1/official-account-local/media/"):
            raise ValueError("local article context media URL is outside the controlled API path")
        resolved = resolved.replace(placeholder, escape(media_url, quote=True))
    if any(context_media_placeholder(ordinal) in resolved for ordinal in range(2)):
        raise ValueError("resolved local draft HTML still contains a context-media placeholder")
    return resolved


def validate_version_identifier(value: str) -> str:
    if _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError("official-account version identifier is invalid")
    return value
