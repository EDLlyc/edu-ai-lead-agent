from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO

from PIL import Image

from app.domain.image_validation import (
    DEFAULT_IMAGE_MAX_DIMENSION,
    DEFAULT_IMAGE_MAX_PIXELS,
    validate_image_output,
)

VISUAL_EMBEDDING_PROVIDER = "alibaba-model-studio"
VISUAL_EMBEDDING_MODEL = "qwen3-vl-embedding"
VISUAL_EMBEDDING_DIMENSIONS = 2048
VISUAL_EMBEDDING_INPUT_POLICY_V1 = "brand-visual-embedding-input-v1"
VISUAL_EMBEDDING_INPUT_POLICY_VERSION = "brand-visual-embedding-input-v2"
SUPPORTED_VISUAL_EMBEDDING_INPUT_POLICIES = frozenset(
    {VISUAL_EMBEDDING_INPUT_POLICY_V1, VISUAL_EMBEDDING_INPUT_POLICY_VERSION}
)
VISUAL_QUERY_VERSION = "brand-visual-query-v1"
VISUAL_SELECTOR_VERSION = "brand-visual-selector-v2-multimodal"
MAX_VISUAL_QUERY_CHARACTERS = 2_000
MAX_VISUAL_QUERY_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VISUAL_SOURCE_IMAGE_BYTES = 25 * 1024 * 1024
MAX_VISUAL_EMBEDDING_IMAGE_BYTES = 7 * 1024 * 1024
MAX_VISUAL_PROVIDER_REQUEST_BYTES = 10 * 1024 * 1024
MAX_VISUAL_SEARCH_RESULTS = 20

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_NORMALIZED_PNG_CHUNKS = frozenset({b"IHDR", b"IDAT", b"IEND"})
_NORMALIZATION_MAX_EDGE_SCHEDULE = (
    4_096,
    3_072,
    2_560,
    2_048,
    1_792,
    1_536,
    1_280,
    1_024,
    768,
    512,
    384,
    256,
)


class VisualEmbeddingModality(StrEnum):
    TEXT = "text"
    IMAGE = "image"


class VisualRetrievalUnavailableReason(StrEnum):
    DISABLED = "disabled"
    INPUT_NORMALIZATION_FAILED = "input_normalization_failed"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_PROVIDER_OUTPUT = "invalid_provider_output"
    IDENTITY_MISMATCH = "identity_mismatch"
    INDEX_INCOMPLETE = "index_incomplete"
    CATALOG_CHANGED = "catalog_changed"


class VisualRetrievalError(RuntimeError):
    """Base error whose message must remain free of provider and private input data."""


class VisualEmbeddingError(VisualRetrievalError):
    def __init__(
        self,
        reason: VisualRetrievalUnavailableReason,
        message: str = "visual embedding provider is unavailable",
    ) -> None:
        super().__init__(message)
        self.reason = reason


class VisualIndexUnavailableError(VisualRetrievalError):
    def __init__(self, reason: VisualRetrievalUnavailableReason) -> None:
        super().__init__("visual semantic retrieval is unavailable")
        self.reason = reason


def _identity_value(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if _VERSION.fullmatch(normalized) is None:
        raise ValueError(f"visual embedding {field_name} is invalid")
    return normalized


def _sha256(value: str, *, field_name: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"visual embedding {field_name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class VisualEmbeddingIdentity:
    provider: str = VISUAL_EMBEDDING_PROVIDER
    model: str = VISUAL_EMBEDDING_MODEL
    dimensions: int = VISUAL_EMBEDDING_DIMENSIONS
    input_policy_version: str = VISUAL_EMBEDDING_INPUT_POLICY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _identity_value(self.provider, field_name="provider"))
        object.__setattr__(self, "model", _identity_value(self.model, field_name="model"))
        object.__setattr__(
            self,
            "input_policy_version",
            _identity_value(self.input_policy_version, field_name="input policy"),
        )
        if (
            self.provider != VISUAL_EMBEDDING_PROVIDER
            or self.model != VISUAL_EMBEDDING_MODEL
            or self.dimensions != VISUAL_EMBEDDING_DIMENSIONS
            or self.input_policy_version not in SUPPORTED_VISUAL_EMBEDDING_INPUT_POLICIES
        ):
            raise ValueError("visual embedding identity is not supported")

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            "\0".join(
                (
                    self.provider,
                    self.model,
                    str(self.dimensions),
                    self.input_policy_version,
                )
            ).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class VisualEmbeddingRequest:
    modality: VisualEmbeddingModality
    input_sha256: str
    identity: VisualEmbeddingIdentity
    text: str | None = None
    image_png: bytes | None = None

    def __post_init__(self) -> None:
        _sha256(self.input_sha256, field_name="input hash")
        if self.modality is VisualEmbeddingModality.TEXT:
            normalized = (self.text or "").strip()
            if not normalized or len(normalized) > MAX_VISUAL_QUERY_CHARACTERS:
                raise ValueError("visual text query is blank or too long")
            if self.image_png is not None:
                raise ValueError("visual text query cannot include image bytes")
            if hashlib.sha256(normalized.encode()).hexdigest() != self.input_sha256:
                raise ValueError("visual text query hash does not match")
            object.__setattr__(self, "text", normalized)
        else:
            body = self.image_png
            maximum_bytes = (
                MAX_VISUAL_QUERY_IMAGE_BYTES
                if self.identity.input_policy_version == VISUAL_EMBEDDING_INPUT_POLICY_V1
                else MAX_VISUAL_EMBEDDING_IMAGE_BYTES
            )
            if (
                body is None
                or not 1 <= len(body) <= maximum_bytes
                or not body.startswith(_PNG_SIGNATURE)
            ):
                raise ValueError("visual image query must be a bounded PNG")
            validation = validate_image_output(
                body,
                "image/png",
                expected_dimensions=None,
                max_bytes=maximum_bytes,
                max_dimension=DEFAULT_IMAGE_MAX_DIMENSION,
                max_pixels=DEFAULT_IMAGE_MAX_PIXELS,
            )
            if not validation.passed:
                raise ValueError("visual image query must be a valid bounded PNG")
            if self.text is not None:
                raise ValueError("visual image query cannot include text")
            if hashlib.sha256(body).hexdigest() != self.input_sha256:
                raise ValueError("visual image query hash does not match")

    @property
    def request_fingerprint(self) -> str:
        return hashlib.sha256(
            "\0".join(
                (
                    self.modality.value,
                    self.input_sha256,
                    self.identity.fingerprint,
                )
            ).encode()
        ).hexdigest()

    @classmethod
    def for_text(
        cls, text: str, *, identity: VisualEmbeddingIdentity | None = None
    ) -> VisualEmbeddingRequest:
        normalized = text.strip()
        return cls(
            modality=VisualEmbeddingModality.TEXT,
            input_sha256=hashlib.sha256(normalized.encode()).hexdigest(),
            identity=identity or VisualEmbeddingIdentity(),
            text=normalized,
        )

    @classmethod
    def for_image(
        cls, body: bytes, *, identity: VisualEmbeddingIdentity | None = None
    ) -> VisualEmbeddingRequest:
        selected_identity = identity or VisualEmbeddingIdentity()
        normalized = normalize_visual_embedding_image(body, identity=selected_identity)
        return cls.for_normalized_image(normalized.png_bytes, identity=selected_identity)

    @classmethod
    def for_normalized_image(
        cls, body: bytes, *, identity: VisualEmbeddingIdentity
    ) -> VisualEmbeddingRequest:
        return cls(
            modality=VisualEmbeddingModality.IMAGE,
            input_sha256=hashlib.sha256(body).hexdigest(),
            identity=identity,
            image_png=body,
        )


@dataclass(frozen=True, slots=True)
class VisualEmbeddingResult:
    identity: VisualEmbeddingIdentity
    input_sha256: str
    request_fingerprint: str
    vector: tuple[float, ...]
    input_tokens: int = 0
    image_tokens: int = 0
    latency_ms: int = 0

    def __post_init__(self) -> None:
        _sha256(self.input_sha256, field_name="input hash")
        _sha256(self.request_fingerprint, field_name="request fingerprint")
        if len(self.vector) != self.identity.dimensions:
            raise ValueError("visual embedding vector dimensions do not match")
        if any(not math.isfinite(value) for value in self.vector) or not any(
            value != 0.0 for value in self.vector
        ):
            raise ValueError("visual embedding vector must be finite and non-zero")
        if not 0 <= self.input_tokens <= 10_000_000:
            raise ValueError("visual embedding text usage is invalid")
        if not 0 <= self.image_tokens <= 10_000_000:
            raise ValueError("visual embedding image usage is invalid")
        if not 0 <= self.latency_ms <= 3_600_000:
            raise ValueError("visual embedding latency is invalid")


@dataclass(frozen=True, slots=True)
class VisualAssetDerivation:
    asset_id: str
    asset_checksum: str
    embedding_input_sha256: str
    catalog_version: str
    identity: VisualEmbeddingIdentity = VisualEmbeddingIdentity()

    def __post_init__(self) -> None:
        _sha256(self.asset_id, field_name="asset id")
        _sha256(self.asset_checksum, field_name="asset checksum")
        _sha256(self.embedding_input_sha256, field_name="normalized input hash")
        if (
            self.identity.input_policy_version == VISUAL_EMBEDDING_INPUT_POLICY_V1
            and self.embedding_input_sha256 != self.asset_checksum
        ):
            raise ValueError("visual v1 embedding input must equal the source asset")
        object.__setattr__(
            self, "catalog_version", _identity_value(self.catalog_version, field_name="catalog")
        )

    @property
    def key(self) -> str:
        parts = [
            self.asset_id,
            self.asset_checksum,
            self.catalog_version,
            self.identity.fingerprint,
        ]
        if self.identity.input_policy_version != VISUAL_EMBEDDING_INPUT_POLICY_V1:
            parts.append(self.embedding_input_sha256)
        return hashlib.sha256("\0".join(parts).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class NormalizedVisualImage:
    input_policy_version: str
    source_sha256: str
    embedding_input_sha256: str
    png_bytes: bytes
    width: int
    height: int
    normalized: bool

    def __post_init__(self) -> None:
        if self.input_policy_version not in SUPPORTED_VISUAL_EMBEDDING_INPUT_POLICIES:
            raise ValueError("normalized visual input policy is unsupported")
        _sha256(self.source_sha256, field_name="source image hash")
        _sha256(self.embedding_input_sha256, field_name="normalized input hash")
        if hashlib.sha256(self.png_bytes).hexdigest() != self.embedding_input_sha256:
            raise ValueError("normalized visual input hash does not match")
        maximum_bytes = (
            MAX_VISUAL_QUERY_IMAGE_BYTES
            if self.input_policy_version == VISUAL_EMBEDDING_INPUT_POLICY_V1
            else MAX_VISUAL_EMBEDDING_IMAGE_BYTES
        )
        if not 1 <= len(self.png_bytes) <= maximum_bytes:
            raise ValueError("normalized visual input exceeds the provider byte bound")
        if self.width < 1 or self.height < 1:
            raise ValueError("normalized visual input dimensions are invalid")


def normalize_visual_embedding_image(
    source: bytes,
    *,
    identity: VisualEmbeddingIdentity | None = None,
) -> NormalizedVisualImage:
    """Validate and deterministically normalize one PNG without mutating its source."""

    selected_identity = identity or VisualEmbeddingIdentity()
    source_maximum = (
        MAX_VISUAL_QUERY_IMAGE_BYTES
        if selected_identity.input_policy_version == VISUAL_EMBEDDING_INPUT_POLICY_V1
        else MAX_VISUAL_SOURCE_IMAGE_BYTES
    )
    validation = validate_image_output(
        source,
        "image/png",
        expected_dimensions=None,
        max_bytes=source_maximum,
        max_dimension=DEFAULT_IMAGE_MAX_DIMENSION,
        max_pixels=DEFAULT_IMAGE_MAX_PIXELS,
    )
    if not validation.passed or validation.width is None or validation.height is None:
        raise ValueError("visual embedding source must be a valid bounded PNG")
    try:
        with Image.open(BytesIO(source)) as opened:
            if opened.format != "PNG" or opened.size != (validation.width, validation.height):
                raise ValueError("visual embedding source raster identity is invalid")
            opened.load()
            if (
                selected_identity.input_policy_version == VISUAL_EMBEDDING_INPUT_POLICY_V1
                or len(source) <= MAX_VISUAL_EMBEDDING_IMAGE_BYTES
            ):
                return NormalizedVisualImage(
                    input_policy_version=selected_identity.input_policy_version,
                    source_sha256=hashlib.sha256(source).hexdigest(),
                    embedding_input_sha256=hashlib.sha256(source).hexdigest(),
                    png_bytes=source,
                    width=validation.width,
                    height=validation.height,
                    normalized=False,
                )
            target_mode = (
                "RGBA" if "A" in opened.getbands() or "transparency" in opened.info else "RGB"
            )
            raster = opened.convert(target_mode)
    except (Image.DecompressionBombError, OSError, ValueError) as error:
        raise ValueError("visual embedding source raster is invalid") from error

    source_sha256 = hashlib.sha256(source).hexdigest()
    for maximum_edge in _normalization_edge_schedule(raster.width, raster.height):
        scale = min(1.0, maximum_edge / max(raster.width, raster.height))
        target_size = (
            max(1, round(raster.width * scale)),
            max(1, round(raster.height * scale)),
        )
        candidate = (
            raster.copy()
            if target_size == raster.size
            else raster.resize(target_size, Image.Resampling.LANCZOS, reducing_gap=3.0)
        )
        candidate.info.clear()
        output = BytesIO()
        candidate.save(output, format="PNG", optimize=False, compress_level=9)
        body = output.getvalue()
        if len(body) > MAX_VISUAL_EMBEDDING_IMAGE_BYTES:
            continue
        if not _png_contains_only_normalized_chunks(body):
            raise ValueError("normalized visual input contains unsupported metadata")
        normalized_validation = validate_image_output(
            body,
            "image/png",
            expected_dimensions=target_size,
            max_bytes=MAX_VISUAL_EMBEDDING_IMAGE_BYTES,
            max_dimension=DEFAULT_IMAGE_MAX_DIMENSION,
            max_pixels=DEFAULT_IMAGE_MAX_PIXELS,
        )
        if not normalized_validation.passed:
            raise ValueError("normalized visual input failed validation")
        return NormalizedVisualImage(
            input_policy_version=selected_identity.input_policy_version,
            source_sha256=source_sha256,
            embedding_input_sha256=hashlib.sha256(body).hexdigest(),
            png_bytes=body,
            width=target_size[0],
            height=target_size[1],
            normalized=True,
        )
    raise ValueError("visual embedding source cannot fit the provider request bound")


def _normalization_edge_schedule(width: int, height: int) -> tuple[int, ...]:
    source_edge = max(width, height)
    first_edge = min(source_edge, _NORMALIZATION_MAX_EDGE_SCHEDULE[0])
    return (
        first_edge,
        *(edge for edge in _NORMALIZATION_MAX_EDGE_SCHEDULE if edge < first_edge),
    )


def _png_contains_only_normalized_chunks(body: bytes) -> bool:
    if not body.startswith(_PNG_SIGNATURE):
        return False
    offset = len(_PNG_SIGNATURE)
    chunks: list[bytes] = []
    while offset + 12 <= len(body):
        length = struct.unpack(">I", body[offset : offset + 4])[0]
        chunk_type = body[offset + 4 : offset + 8]
        offset += 12 + length
        if offset > len(body):
            return False
        chunks.append(chunk_type)
        if chunk_type == b"IEND":
            break
    return (
        offset == len(body)
        and bool(chunks)
        and chunks[0] == b"IHDR"
        and chunks[-1] == b"IEND"
        and set(chunks).issubset(_NORMALIZED_PNG_CHUNKS)
    )


@dataclass(frozen=True, slots=True)
class VisualSemanticScore:
    asset_id: str
    similarity: float

    def __post_init__(self) -> None:
        _sha256(self.asset_id, field_name="asset id")
        if not math.isfinite(self.similarity) or not -1.0 <= self.similarity <= 1.0:
            raise ValueError("visual similarity is outside [-1, 1]")


@dataclass(frozen=True, slots=True)
class VisualSemanticRanking:
    catalog_version: str
    identity: VisualEmbeddingIdentity
    query_fingerprint: str
    scores: tuple[VisualSemanticScore, ...]
    indexed_asset_count: int
    catalog_asset_count: int
    complete: bool

    def __post_init__(self) -> None:
        _identity_value(self.catalog_version, field_name="catalog")
        _sha256(self.query_fingerprint, field_name="query fingerprint")
        if self.indexed_asset_count < 0 or self.catalog_asset_count < 0:
            raise ValueError("visual ranking counts are invalid")
        if self.complete != (
            self.indexed_asset_count == self.catalog_asset_count
            and len(self.scores) == self.catalog_asset_count
        ):
            raise ValueError("visual ranking completeness proof is inconsistent")
        ids = tuple(score.asset_id for score in self.scores)
        if len(ids) != len(set(ids)):
            raise ValueError("visual ranking contains duplicate assets")

    @property
    def score_map(self) -> dict[str, float]:
        return {score.asset_id: score.similarity for score in self.scores}


def canonical_visual_query(fields: dict[str, object]) -> str:
    """Serialize only allowlisted, bounded visual-plan fields in a stable order."""

    allowed = (
        "category",
        "title",
        "learning_goal",
        "scene",
        "main_action",
        "characters",
        "subject",
        "cast",
        "composition",
        "camera",
        "asset_tags",
    )
    normalized: dict[str, object] = {"version": VISUAL_QUERY_VERSION}
    for key in allowed:
        value = fields.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                normalized[key] = text[:240]
        elif isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
            items = sorted({item.strip()[:80] for item in value if item.strip()})[:20]
            if items:
                normalized[key] = items
    serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=False, separators=(",", ":"))
    if len(serialized) > MAX_VISUAL_QUERY_CHARACTERS:
        raise ValueError("canonical visual query is too long")
    return serialized
