from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import PurePath
from uuid import UUID

from app.domain.value_objects import is_sha256_hex, sha256_bytes, stable_key

_SAFE_FILENAME_CHARACTER = re.compile(r"[^\w.()\-\u4e00-\u9fff]+", re.UNICODE)
LEGACY_BRAND_DERIVATION_VERSIONS = (
    "brand-parser-v2-glm-ocr",
    "brand-chunk-v2-structure-aware",
    "brand-embedding-input-v1",
)
STRUCTURED_BRAND_DERIVATION_VERSIONS = (
    "brand-parser-v3-source-structure",
    "brand-chunk-v3-parent-child",
    "brand-embedding-input-v2-section-context",
)
LAYOUT_BRAND_DERIVATION_VERSIONS = (
    "brand-parser-v4-layout-aware",
    "brand-chunk-v4-layout-blocks",
    "brand-embedding-input-v2-section-context",
)
SUPPORTED_BRAND_DERIVATION_VERSIONS = frozenset(
    {
        LEGACY_BRAND_DERIVATION_VERSIONS,
        STRUCTURED_BRAND_DERIVATION_VERSIONS,
        LAYOUT_BRAND_DERIVATION_VERSIONS,
    }
)
LEGACY_BRAND_RETRIEVAL_VERSION = "brand-hybrid-rrf-v2-diverse"
STRUCTURED_BRAND_RETRIEVAL_VERSION = "brand-hybrid-rrf-v3-parent-diverse"
SUPPORTED_BRAND_RETRIEVAL_VERSIONS = frozenset(
    {LEGACY_BRAND_RETRIEVAL_VERSION, STRUCTURED_BRAND_RETRIEVAL_VERSION}
)
BRAND_RRF_K = 60.0
BRAND_FULL_TEXT_WEIGHT = 0.45
BRAND_VECTOR_WEIGHT = 0.55
_EXTERNAL_MEASURE_PATTERN = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|\uff05|亿|万|千|家|名|项|所|年|课时)|"
    r"[一二三四五六七八九十百千万亿两]+\s*(?:家|名|项|所|年|课时)|"
    r"超过\s*\d+|达到\s*\d+)",
    re.IGNORECASE,
)
_EXTERNAL_CLAIM_TERMS = (
    "政策",
    "教育部",
    "国务院",
    "国家战略",
    "市场规模",
    "认证",
    "备案",
    "获奖",
    "奖项",
    "第一名",
    "行业首",
    "融资",
    "续费率",
    "满班率",
    "联合发布",
    "共建",
    "合作",
    "基金支持",
)
_CONTENT_TYPE_TERMS: tuple[tuple[BrandContentType, tuple[str, ...]], ...]


class BrandDocumentKind(StrEnum):
    POSITIONING = "positioning"
    TONE = "tone"
    APPROVED_EXAMPLE = "approved_example"
    PROHIBITED_LANGUAGE = "prohibited_language"
    SAFETY_RULE = "safety_rule"
    VISUAL_GUIDANCE = "visual_guidance"
    OTHER = "other"


class BrandSectionKind(StrEnum):
    PAGE = "page"
    INTERVIEW_QA = "interview_qa"
    HEADING = "heading"
    GENERIC = "generic"


class BrandOcrBlockKind(StrEnum):
    TEXT = "text"
    TABLE = "table"
    FORMULA = "formula"


class BrandLayoutSemanticRole(StrEnum):
    """Closed PP-DocLayoutV3 semantic role retained only during v4 parse/chunk."""

    ABSTRACT = "abstract"
    ALGORITHM = "algorithm"
    ASIDE_TEXT = "aside_text"
    CHART = "chart"
    CONTENT = "content"
    DISPLAY_FORMULA = "display_formula"
    DOC_TITLE = "doc_title"
    FIGURE_TITLE = "figure_title"
    FOOTER = "footer"
    FOOTER_IMAGE = "footer_image"
    FOOTNOTE = "footnote"
    FORMULA_NUMBER = "formula_number"
    HEADER = "header"
    HEADER_IMAGE = "header_image"
    IMAGE = "image"
    INLINE_FORMULA = "inline_formula"
    NUMBER = "number"
    PARAGRAPH_TITLE = "paragraph_title"
    REFERENCE = "reference"
    REFERENCE_CONTENT = "reference_content"
    SEAL = "seal"
    TABLE = "table"
    TEXT = "text"
    VERTICAL_TEXT = "vertical_text"
    VISION_FOOTNOTE = "vision_footnote"


class BrandContentType(StrEnum):
    POSITIONING = "positioning"
    PRODUCT_PROFILE = "product_profile"
    AUDIENCE_INSIGHT = "audience_insight"
    SAFETY_CAPABILITY = "safety_capability"
    DIGITAL_IP_VALUES = "digital_ip_values"
    TONE_EXAMPLE = "tone_example"
    EXTERNAL_CLAIM = "external_claim"
    VISUAL_GUIDANCE = "visual_guidance"
    OTHER = "other"


class BrandClaimScope(StrEnum):
    BRAND_STATEMENT = "brand_statement"
    EXTERNAL_CLAIM = "external_claim"
    NORMATIVE_RULE = "normative_rule"


_CONTENT_TYPE_TERMS = (
    (
        BrandContentType.SAFETY_CAPABILITY,
        ("安全", "过滤", "审核", "预审", "监护", "隐私", "风险防控", "护栏"),
    ),
    (
        BrandContentType.PRODUCT_PROFILE,
        ("产品", "课程", "探索盒", "平台功能", "工具", "服务", "价格", "适用年龄"),
    ),
    (
        BrandContentType.AUDIENCE_INSIGHT,
        ("家长需求", "用户需求", "用户痛点", "青少儿痛点", "受众", "为什么要学"),
    ),
    (
        BrandContentType.DIGITAL_IP_VALUES,
        ("数字IP", "数字 IP", "角色价值", "人格设定", "品牌理念", "价值观"),
    ),
    (
        BrandContentType.TONE_EXAMPLE,
        ("表达方式", "品牌语气", "话术", "代表性表达", "沟通语气"),
    ),
    (
        BrandContentType.VISUAL_GUIDANCE,
        ("视觉", "色彩", "字体", "版式", "海报", "插画", "配图"),
    ),
    (
        BrandContentType.POSITIONING,
        ("品牌定位", "平台定位", "愿景", "使命", "赛先生是谁", "长期愿景"),
    ),
)


class BrandAudience(StrEnum):
    PARENTS = "parents"
    INTERNAL = "internal"


class BrandVersionStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class BrandIngestionJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class BrandOriginalDescriptor:
    bucket: str
    object_key: str
    media_type: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        if not self.bucket.strip() or not self.object_key.strip() or not self.media_type.strip():
            raise ValueError("brand original descriptor fields must not be blank")
        if self.byte_size < 1 or not is_sha256_hex(self.sha256):
            raise ValueError("brand original descriptor metadata is invalid")


@dataclass(frozen=True, slots=True)
class ValidatedBrandUpload:
    safe_filename: str
    media_type: str
    body: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class BrandUploadMetadata:
    brand_slug: str
    title: str
    document_kind: BrandDocumentKind
    audience: BrandAudience
    language: str
    valid_from: date | None
    valid_until: date | None
    tone_tags: tuple[str, ...]
    safety_tags: tuple[str, ...]
    visual_tags: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.brand_slug != "sai-xiansheng":
            raise ValueError("the MVP accepts only the single Sai Xiansheng brand")
        if not self.title.strip() or len(self.title) > 200:
            raise ValueError("brand document title must be 1-200 characters")
        if self.language != "zh-CN":
            raise ValueError("the MVP accepts only zh-CN brand documents")
        if self.valid_from is not None and self.valid_until is not None:
            if self.valid_until < self.valid_from:
                raise ValueError("brand validity end must not precede start")
        for tag_group in (self.tone_tags, self.safety_tags, self.visual_tags):
            if len(tag_group) > 20 or any(not tag or len(tag) > 40 for tag in tag_group):
                raise ValueError("brand metadata tags are invalid")

    @property
    def document_key(self) -> str:
        return stable_key(
            self.brand_slug,
            unicodedata.normalize("NFKC", self.title).strip().casefold(),
            self.document_kind.value,
            self.audience.value,
        )

    @property
    def metadata_fingerprint(self) -> str:
        """Fingerprint version-scoped metadata while treating tag order as insignificant."""
        payload = {
            "audience": self.audience.value,
            "brand_slug": self.brand_slug,
            "document_kind": self.document_kind.value,
            "language": self.language,
            "safety_tags": _canonical_tags(self.safety_tags),
            "title": unicodedata.normalize("NFKC", self.title).strip(),
            "tone_tags": _canonical_tags(self.tone_tags),
            "valid_from": self.valid_from.isoformat() if self.valid_from is not None else None,
            "valid_until": self.valid_until.isoformat() if self.valid_until is not None else None,
            "visual_tags": _canonical_tags(self.visual_tags),
        }
        return sha256_bytes(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )


NormalizedBrandBbox = tuple[float, float, float, float]


def _validate_normalized_brand_bbox(value: NormalizedBrandBbox | None) -> None:
    if value is None:
        return
    if len(value) != 4:
        raise ValueError("brand layout bbox must have four coordinates")
    x1, y1, x2, y2 = value
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        raise ValueError("brand layout bbox must be normalized and ordered")


@dataclass(frozen=True, slots=True)
class BrandOcrLayoutBlock:
    ordinal: int
    kind: BrandOcrBlockKind
    text: str = field(repr=False)
    semantic_role: BrandLayoutSemanticRole | None = None
    normalized_bbox: NormalizedBrandBbox | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.ordinal < 0 or not self.text.strip():
            raise ValueError("brand OCR layout block identity and text are invalid")
        if self.semantic_role is not None and not isinstance(
            self.semantic_role, BrandLayoutSemanticRole
        ):
            raise ValueError("brand OCR layout block semantic role is invalid")
        _validate_normalized_brand_bbox(self.normalized_bbox)


@dataclass(frozen=True, slots=True)
class BrandOcrLayoutPage:
    page_number: int
    blocks: tuple[BrandOcrLayoutBlock, ...]
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("brand OCR layout page number must be positive")
        if (self.width is None) != (self.height is None):
            raise ValueError("brand OCR layout page dimensions must be paired")
        if self.width is not None and (self.width < 1 or self.height is None or self.height < 1):
            raise ValueError("brand OCR layout page dimensions must be positive")
        if tuple(block.ordinal for block in self.blocks) != tuple(range(len(self.blocks))):
            raise ValueError("brand OCR layout block ordinals must be contiguous")


@dataclass(frozen=True, slots=True)
class ParsedBrandLayoutBlock:
    ordinal: int
    source_page: int
    kind: BrandOcrBlockKind
    text: str
    char_start: int
    char_end: int
    semantic_role: BrandLayoutSemanticRole | None = None
    normalized_bbox: NormalizedBrandBbox | None = None

    def __post_init__(self) -> None:
        if self.ordinal < 0 or self.source_page < 1 or not self.text.strip():
            raise ValueError("parsed brand layout block identity and text are invalid")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("parsed brand layout block offsets are invalid")
        if self.semantic_role is not None and not isinstance(
            self.semantic_role, BrandLayoutSemanticRole
        ):
            raise ValueError("parsed brand layout block semantic role is invalid")
        _validate_normalized_brand_bbox(self.normalized_bbox)


@dataclass(frozen=True, slots=True)
class ParsedBrandSection:
    ordinal: int
    kind: BrandSectionKind
    title: str
    text: str
    char_start: int
    char_end: int
    source_page: int | None = None
    question_number: int | None = None
    question_text: str | None = None
    layout_blocks: tuple[ParsedBrandLayoutBlock, ...] = ()

    def __post_init__(self) -> None:
        if self.ordinal < 0 or not self.title.strip() or not self.text.strip():
            raise ValueError("parsed brand section identity and text are invalid")
        if len(self.title) > 240:
            raise ValueError("parsed brand section title is too long")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("parsed brand section offsets are invalid")
        if self.source_page is not None and self.source_page < 1:
            raise ValueError("parsed brand section page must be positive")
        if self.question_number is not None and self.question_number < 1:
            raise ValueError("parsed brand section question number must be positive")
        if self.question_text is not None:
            if not self.question_text.strip() or len(self.question_text) > 1_000:
                raise ValueError("parsed brand section question text is invalid")
        if self.kind == BrandSectionKind.PAGE and self.source_page is None:
            raise ValueError("page sections require a source page")
        if self.kind == BrandSectionKind.INTERVIEW_QA:
            if self.question_number is None or self.question_text is None:
                raise ValueError("interview sections require a question identity")
        if self.layout_blocks and self.kind != BrandSectionKind.PAGE:
            raise ValueError("layout blocks require a page section")
        if tuple(block.ordinal for block in self.layout_blocks) != tuple(
            range(len(self.layout_blocks))
        ):
            raise ValueError("parsed brand layout block ordinals must be contiguous")
        for block in self.layout_blocks:
            if block.source_page != self.source_page:
                raise ValueError("parsed brand layout block page must match its section")
            if block.char_start < self.char_start or block.char_end > self.char_end:
                raise ValueError("parsed brand layout block exceeds its section")
            local_start = block.char_start - self.char_start
            local_end = block.char_end - self.char_start
            if self.text[local_start:local_end] != block.text:
                raise ValueError("parsed brand layout block must be an exact section slice")
        for left, right in zip(self.layout_blocks, self.layout_blocks[1:], strict=False):
            if left.char_end > right.char_start:
                raise ValueError("parsed brand layout blocks must not overlap")


@dataclass(frozen=True, slots=True)
class ParsedBrandDocument:
    text: str
    page_count: int | None
    sections: tuple[ParsedBrandSection, ...] = ()
    extraction_method: str = "local"
    requires_ocr: bool = False
    ocr_provider: str | None = None
    ocr_model: str | None = None
    ocr_request_fingerprint: str | None = None
    ocr_provider_request_id: str | None = None
    ocr_page_count: int | None = None
    ocr_prompt_tokens: int | None = None
    ocr_completion_tokens: int | None = None
    ocr_latency_ms: int | None = None

    def __post_init__(self) -> None:
        if not self.text.strip() and not self.requires_ocr:
            raise ValueError("parsed brand document must contain text")
        if self.page_count is not None and self.page_count < 1:
            raise ValueError("parsed page count must be positive")
        if self.extraction_method not in {"local", "ocr"}:
            raise ValueError("brand extraction method is invalid")
        if self.requires_ocr and self.extraction_method != "local":
            raise ValueError("OCR-needed brand documents must use local extraction metadata")
        if self.extraction_method == "ocr" and not self.text.strip():
            raise ValueError("OCR brand document must contain text")
        for expected_ordinal, section in enumerate(self.sections):
            if section.ordinal != expected_ordinal:
                raise ValueError("parsed brand section ordinals must be contiguous")
            if section.char_end > len(self.text):
                raise ValueError("parsed brand section exceeds document text")
            if self.text[section.char_start : section.char_end] != section.text:
                raise ValueError("parsed brand section must be an exact document slice")
        for left, right in zip(self.sections, self.sections[1:], strict=False):
            if left.char_end > right.char_start:
                raise ValueError("parsed brand sections must not overlap")
        if self.ocr_page_count is not None and self.ocr_page_count < 1:
            raise ValueError("OCR page count must be positive")
        for value in (self.ocr_prompt_tokens, self.ocr_completion_tokens, self.ocr_latency_ms):
            if value is not None and value < 0:
                raise ValueError("OCR usage counters must not be negative")

    @property
    def ocr_required(self) -> bool:
        """Compatibility alias for callers that describe the decision as an OCR requirement."""
        return self.requires_ocr


@dataclass(frozen=True, slots=True)
class BrandSection:
    id: UUID
    version_id: UUID
    ordinal: int
    section_key: str
    kind: BrandSectionKind
    title: str
    text: str
    text_hash: str
    char_start: int
    char_end: int
    source_page: int | None = None
    question_number: int | None = None
    question_text: str | None = None

    def __post_init__(self) -> None:
        if self.ordinal < 0 or not self.title.strip() or not self.text.strip():
            raise ValueError("brand section identity and text are invalid")
        if len(self.title) > 240:
            raise ValueError("brand section title is too long")
        if not is_sha256_hex(self.section_key) or not is_sha256_hex(self.text_hash):
            raise ValueError("brand section hashes are invalid")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("brand section offsets are invalid")
        if self.source_page is not None and self.source_page < 1:
            raise ValueError("brand section page must be positive")
        if self.question_number is not None and self.question_number < 1:
            raise ValueError("brand section question number must be positive")
        if self.question_text is not None:
            if not self.question_text.strip() or len(self.question_text) > 1_000:
                raise ValueError("brand section question text is invalid")
        if self.kind == BrandSectionKind.PAGE and self.source_page is None:
            raise ValueError("page sections require a source page")
        if self.kind == BrandSectionKind.INTERVIEW_QA:
            if self.question_number is None or self.question_text is None:
                raise ValueError("interview sections require a question identity")


@dataclass(frozen=True, slots=True)
class BrandChunk:
    id: UUID
    section_id: UUID | None
    ordinal: int
    section_ordinal: int | None
    text: str
    text_hash: str
    embedding_text: str
    embedding_input_hash: str
    content_type: BrandContentType
    claim_scope: BrandClaimScope
    verification_required: bool
    char_start: int
    char_end: int
    chunk_key: str

    def __post_init__(self) -> None:
        if self.ordinal < 0 or not self.text.strip():
            raise ValueError("brand chunk ordinal and text are invalid")
        if (self.section_id is None) != (self.section_ordinal is None):
            raise ValueError("brand chunk section binding is invalid")
        if self.section_ordinal is not None and self.section_ordinal < 0:
            raise ValueError("brand chunk section ordinal is invalid")
        if not self.embedding_text.strip() or self.text not in self.embedding_text:
            raise ValueError("brand chunk embedding input is invalid")
        if len(self.embedding_text) > 3_000:
            raise ValueError("brand chunk embedding input is too long")
        if (
            not is_sha256_hex(self.text_hash)
            or not is_sha256_hex(self.embedding_input_hash)
            or not is_sha256_hex(self.chunk_key)
        ):
            raise ValueError("brand chunk hashes are invalid")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("brand chunk offsets are invalid")
        if self.claim_scope == BrandClaimScope.EXTERNAL_CLAIM and not self.verification_required:
            raise ValueError("external brand claims must require verification")


@dataclass(frozen=True, slots=True)
class BrandChunkingResult:
    sections: tuple[BrandSection, ...]
    chunks: tuple[BrandChunk, ...]

    def __post_init__(self) -> None:
        if not self.chunks:
            raise ValueError("brand chunking must produce chunks")
        section_ids = {section.id for section in self.sections}
        if len(section_ids) != len(self.sections):
            raise ValueError("brand section ids must be unique")
        if self.sections and any(chunk.section_id not in section_ids for chunk in self.chunks):
            raise ValueError("brand chunks must reference a result section")
        if not self.sections and any(chunk.section_id is not None for chunk in self.chunks):
            raise ValueError("sectionless brand chunks must not reference a section")
        if tuple(section.ordinal for section in self.sections) != tuple(range(len(self.sections))):
            raise ValueError("brand section ordinals must be contiguous")
        if tuple(chunk.ordinal for chunk in self.chunks) != tuple(range(len(self.chunks))):
            raise ValueError("brand chunk ordinals must be contiguous")

    def __len__(self) -> int:
        return len(self.chunks)

    def __iter__(self) -> Iterator[BrandChunk]:
        return iter(self.chunks)

    def __getitem__(self, index: int) -> BrandChunk:
        return self.chunks[index]


@dataclass(frozen=True, slots=True)
class ClaimedBrandIngestionJob:
    job_id: UUID
    version_id: UUID
    attempt_number: int
    lease_token: UUID
    bucket: str
    object_key: str
    media_type: str
    sha256: str
    safe_filename: str
    document_title: str
    document_kind: BrandDocumentKind
    parser_version: str
    chunk_version: str
    embedding_input_version: str


@dataclass(frozen=True, slots=True)
class BrandChunkEmbedding:
    chunk: BrandChunk
    vector: tuple[float, ...]
    provider: str
    model: str
    request_fingerprint: str
    provider_request_id: str | None

    def __post_init__(self) -> None:
        if len(self.vector) != 2048:
            raise ValueError("brand embedding must contain exactly 2048 dimensions")


@dataclass(frozen=True, slots=True)
class BrandRetrievalHit:
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    document_title: str
    document_kind: BrandDocumentKind
    audience: BrandAudience
    text: str
    tone_tags: tuple[str, ...]
    safety_tags: tuple[str, ...]
    visual_tags: tuple[str, ...]
    full_text_score: float
    vector_score: float
    fused_score: float
    section_id: UUID | None = None
    section_title: str | None = None
    section_kind: BrandSectionKind | None = None
    source_page: int | None = None
    question_number: int | None = None
    question_text: str | None = None
    content_type: BrandContentType | None = None
    claim_scope: BrandClaimScope | None = None
    verification_required: bool = False


def fuse_brand_retrieval_score(
    *,
    full_text_rank: int | None,
    vector_rank: int | None,
) -> float:
    """Fuse one candidate's positive one-based ranks under the frozen brand RRF policy."""

    if full_text_rank is None and vector_rank is None:
        raise ValueError("brand retrieval candidate must have at least one rank")
    for rank in (full_text_rank, vector_rank):
        if rank is not None and (isinstance(rank, bool) or rank < 1):
            raise ValueError("brand retrieval ranks must be positive integers")
    score = 0.0
    if full_text_rank is not None:
        score += BRAND_FULL_TEXT_WEIGHT / (BRAND_RRF_K + full_text_rank)
    if vector_rank is not None:
        score += BRAND_VECTOR_WEIGHT / (BRAND_RRF_K + vector_rank)
    return score


def sanitize_brand_filename(filename: str) -> str:
    normalized = unicodedata.normalize("NFKC", PurePath(filename.replace("\\", "/")).name)
    normalized = "".join(character for character in normalized if character.isprintable())
    safe = _SAFE_FILENAME_CHARACTER.sub("-", normalized).strip(" .-")
    if not safe or len(safe) > 180:
        raise ValueError("brand upload filename is invalid")
    return safe


def _canonical_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        sorted({unicodedata.normalize("NFKC", tag).strip() for tag in tags if tag.strip()})
    )


def validated_brand_upload(
    *, filename: str, declared_media_type: str | None, body: bytes
) -> ValidatedBrandUpload:
    safe_filename = sanitize_brand_filename(filename)
    extension = PurePath(safe_filename).suffix.casefold()
    declared = (declared_media_type or "").split(";", 1)[0].strip().casefold()
    if extension == ".pdf" and body.startswith(b"%PDF-"):
        media_type = "application/pdf"
        allowed_declared = {"", "application/pdf", "application/octet-stream"}
    elif extension == ".docx" and body.startswith(b"PK\x03\x04"):
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        allowed_declared = {"", media_type, "application/octet-stream", "application/zip"}
    elif extension in {".txt", ".md", ".markdown"} and b"\x00" not in body[:4096]:
        media_type = "text/markdown" if extension != ".txt" else "text/plain"
        allowed_declared = {
            "",
            media_type,
            "text/plain",
            "text/markdown",
            "application/octet-stream",
        }
    else:
        raise ValueError("file signature and supported extension do not agree")
    if declared not in allowed_declared:
        raise ValueError("declared media type does not agree with the uploaded file")
    if not body:
        raise ValueError("brand upload must not be empty")
    return ValidatedBrandUpload(
        safe_filename=safe_filename,
        media_type=media_type,
        body=body,
        sha256=sha256_bytes(body),
    )


def normalize_brand_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    output: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line
        if blank and previous_blank:
            continue
        output.append(line)
        previous_blank = blank
    return "\n".join(output).strip()


def classify_brand_chunk(
    *,
    document_kind: BrandDocumentKind,
    section_title: str,
    question_text: str | None,
    text: str,
) -> tuple[BrandContentType, BrandClaimScope, bool]:
    """Project conservative, replay-stable semantic metadata without a model call."""

    normalized = normalize_brand_text(
        "\n".join(part for part in (section_title, question_text or "", text) if part.strip())
    )
    content_type = BrandContentType.OTHER
    for candidate, terms in _CONTENT_TYPE_TERMS:
        if any(term.casefold() in normalized.casefold() for term in terms):
            content_type = candidate
            break
    if content_type == BrandContentType.OTHER:
        by_document_kind = {
            BrandDocumentKind.POSITIONING: BrandContentType.POSITIONING,
            BrandDocumentKind.TONE: BrandContentType.TONE_EXAMPLE,
            BrandDocumentKind.APPROVED_EXAMPLE: BrandContentType.TONE_EXAMPLE,
            BrandDocumentKind.SAFETY_RULE: BrandContentType.SAFETY_CAPABILITY,
            BrandDocumentKind.VISUAL_GUIDANCE: BrandContentType.VISUAL_GUIDANCE,
        }
        content_type = by_document_kind.get(document_kind, BrandContentType.OTHER)

    has_external_term = any(
        term.casefold() in normalized.casefold() for term in _EXTERNAL_CLAIM_TERMS
    )
    has_external_measure = _EXTERNAL_MEASURE_PATTERN.search(text) is not None
    external_claim = has_external_term or has_external_measure
    if external_claim:
        claim_scope = BrandClaimScope.EXTERNAL_CLAIM
    elif document_kind in {
        BrandDocumentKind.PROHIBITED_LANGUAGE,
        BrandDocumentKind.SAFETY_RULE,
    } or any(term in normalized for term in ("不得", "禁止", "必须", "严禁")):
        claim_scope = BrandClaimScope.NORMATIVE_RULE
    else:
        claim_scope = BrandClaimScope.BRAND_STATEMENT
    if content_type == BrandContentType.OTHER and external_claim:
        content_type = BrandContentType.EXTERNAL_CLAIM
    return content_type, claim_scope, external_claim


def build_brand_embedding_text(
    *,
    document_title: str,
    section_title: str,
    question_text: str | None,
    content_type: BrandContentType,
    raw_text: str,
) -> str:
    """Build the one canonical contextual text used by FTS and brand embedding."""

    title = normalize_brand_text(document_title)
    section = normalize_brand_text(section_title)
    question = normalize_brand_text(question_text or "")
    body = raw_text.strip()
    if not title or not section or not body:
        raise ValueError("brand embedding context must not be blank")
    if len(title) > 200 or len(section) > 240 or len(question) > 1_000:
        raise ValueError("brand embedding context metadata is too long")
    lines = [f"文档\uff1a{title}", f"章节\uff1a{section}"]
    if question:
        lines.append(f"问题\uff1a{question}")
    lines.extend((f"类型\uff1a{content_type.value}", f"正文\uff1a{body}"))
    result = "\n".join(lines)
    if len(result) > 3_000:
        raise ValueError("brand embedding context is too long")
    return result
