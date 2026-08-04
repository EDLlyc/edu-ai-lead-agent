from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import PurePath
from uuid import UUID

from app.domain.value_objects import is_sha256_hex, sha256_bytes, stable_key

_SAFE_FILENAME_CHARACTER = re.compile(r"[^\w.()\-\u4e00-\u9fff]+", re.UNICODE)


class BrandDocumentKind(StrEnum):
    POSITIONING = "positioning"
    TONE = "tone"
    APPROVED_EXAMPLE = "approved_example"
    PROHIBITED_LANGUAGE = "prohibited_language"
    SAFETY_RULE = "safety_rule"
    VISUAL_GUIDANCE = "visual_guidance"
    OTHER = "other"


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


@dataclass(frozen=True, slots=True)
class ParsedBrandDocument:
    text: str
    page_count: int | None
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
class BrandChunk:
    id: UUID
    ordinal: int
    text: str
    text_hash: str
    char_start: int
    char_end: int
    chunk_key: str

    def __post_init__(self) -> None:
        if self.ordinal < 0 or not self.text.strip():
            raise ValueError("brand chunk ordinal and text are invalid")
        if not is_sha256_hex(self.text_hash) or not is_sha256_hex(self.chunk_key):
            raise ValueError("brand chunk hashes are invalid")
        if self.char_start < 0 or self.char_end <= self.char_start:
            raise ValueError("brand chunk offsets are invalid")


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
