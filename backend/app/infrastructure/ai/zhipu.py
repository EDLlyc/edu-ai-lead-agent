from __future__ import annotations

import asyncio
import base64
import json
import math
import re
import zlib
from collections.abc import Awaitable, Callable
from time import perf_counter_ns
from typing import Annotated, Any, TypeAlias
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.application.ports.brand_knowledge import (
    BrandDocumentOcrModel,
    BrandDocumentOcrRequest,
    BrandDocumentOcrResult,
)
from app.application.ports.governance import (
    EmbeddingRequest,
    EmbeddingResult,
    FactualAnalysisRequest,
    FactualAnalysisResult,
)
from app.application.ports.image_validation import (
    ImageTextRecognitionRequest,
    ImageTextRecognitionResult,
)
from app.application.services.governance_analysis import build_factual_analysis_prompt
from app.core.errors import (
    BrandOcrAuthenticationError,
    BrandOcrIdentityMismatchError,
    BrandOcrInputLimitError,
    BrandOcrInvalidOutputError,
    BrandOcrRateLimitError,
    BrandOcrRejectedError,
    BrandOcrTimeoutError,
    BrandOcrUnavailableError,
    InvalidProviderOutputError,
    ProviderAuthenticationError,
    ProviderDimensionMismatchError,
    ProviderIdentityMismatchError,
    ProviderInputLimitError,
    ProviderRateLimitError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.domain.governance_enums import AnalysisValidationCode
from app.domain.image_validation import validate_exact_visual_text, validate_image_output
from app.domain.value_objects import sha256_bytes, stable_key
from app.schemas.governance_analysis import FactualAnalysisOutput

_Sleep = Callable[[float], Awaitable[None]]
_TEMPERATURE = 0.0
_ACCEPT_ENCODING = "gzip"
_SAFE_PROVIDER_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}")
_MAX_EMBEDDING_RESPONSE_BYTES = 256 * 1024
_IMAGE_OCR_PROVIDER = "zhipu"
_IMAGE_OCR_MAX_INPUT_BYTES = 10 * 1024 * 1024
_IMAGE_OCR_MAX_RESPONSE_BYTES = 1024 * 1024
_IMAGE_OCR_MAX_LAYOUT_ELEMENTS = 256
_IMAGE_OCR_MAX_CONTENT_CHARACTERS = 1_600
_IMAGE_OCR_MAX_LINES = 8
_IMAGE_OCR_MAX_PAGES = 100
_IMAGE_OCR_MAX_DIMENSION = 100_000
_IMAGE_OCR_LAYOUT_LABELS = frozenset({"formula", "image", "table", "text"})
_IMAGE_OCR_RESPONSE_ENVELOPE_ISSUE = "image_ocr_response_envelope_invalid"
_IMAGE_OCR_SOURCE_INVALID_ISSUE = "image_ocr_contract_source_invalid"
_IMAGE_OCR_SOURCE_CONFLICT_ISSUE = "image_ocr_contract_source_conflict"
_IMAGE_OCR_SCHEMA_ISSUE = "image_ocr_contract_schema_invalid"
_IMAGE_OCR_PAGE_COUNT_ISSUE = "image_ocr_contract_page_count"
_IMAGE_OCR_PAGE_DIMENSIONS_ISSUE = "image_ocr_contract_page_dimensions"
_IMAGE_OCR_PAGE_DIMENSIONS_CONFLICT_ISSUE = "image_ocr_contract_page_dimensions_conflict"
_IMAGE_OCR_INDEX_ISSUE = "image_ocr_contract_index_invalid"
_IMAGE_OCR_DUPLICATE_INDEX_ISSUE = "image_ocr_contract_index_duplicate"
_IMAGE_OCR_LABEL_ISSUE = "image_ocr_contract_label_unknown"
_IMAGE_OCR_BBOX_SHAPE_ISSUE = "image_ocr_contract_bbox_shape"
_IMAGE_OCR_BBOX_SCALE_ISSUE = "image_ocr_contract_bbox_scale"
_IMAGE_OCR_BBOX_RANGE_ISSUE = "image_ocr_contract_bbox_range"
_IMAGE_OCR_CONTENT_TYPE_ISSUE = "image_ocr_contract_content_type"
_IMAGE_OCR_CONTENT_LIMIT_ISSUE = "image_ocr_contract_content_limit"
_IMAGE_OCR_ELEMENT_EXTRA_ISSUE = "image_ocr_contract_element_extra"
_IMAGE_OCR_TABLE_ISSUE = "image_ocr_contract_table_unsupported"
_IMAGE_OCR_FORMULA_ISSUE = "image_ocr_contract_formula_unsupported"
_IMAGE_OCR_LINE_LIMIT_ISSUE = "image_ocr_contract_line_limit"


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _CompletionTokenDetails(_ProviderModel):
    reasoning_tokens: int = Field(default=0, ge=0)


class _Usage(_ProviderModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    completion_tokens_details: _CompletionTokenDetails | None = None


class _Message(_ProviderModel):
    content: str


class _Choice(_ProviderModel):
    message: _Message


class _ChatCompletion(_ProviderModel):
    id: str | None = None
    choices: tuple[_Choice, ...] = Field(min_length=1)
    usage: _Usage = Field(default_factory=_Usage)


class _EmbeddingData(_ProviderModel):
    index: int = Field(ge=0)
    embedding: tuple[float, ...] = Field(min_length=1)


class _EmbeddingUsage(_ProviderModel):
    prompt_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class _EmbeddingResponse(_ProviderModel):
    id: str | None = None
    model: str | None = None
    data: tuple[_EmbeddingData, ...] = Field(min_length=1, max_length=1)
    usage: _EmbeddingUsage = Field(default_factory=_EmbeddingUsage)


class _OcrUsage(_ProviderModel):
    prompt_tokens: int = Field(default=0, ge=0, le=10_000_000)
    completion_tokens: int = Field(default=0, ge=0, le=10_000_000)
    total_tokens: int = Field(default=0, ge=0, le=20_000_000)


class _OcrResponse(_ProviderModel):
    id: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=120)
    md_results: str = Field(min_length=1)
    data_info: dict[str, Any]
    usage: _OcrUsage


class _ImageOcrLayoutElement(BaseModel):
    # Region keys have semantic weight in the exact visible-text gate. Keep this
    # allowlist aligned with the raw MaaS schema so a new alternate label/content
    # field cannot be silently discarded.
    model_config = ConfigDict(extra="forbid", strict=True)

    index: Any
    label: Any
    bbox_2d: Any = None
    content: Any = None
    height: Any = None
    width: Any = None


_ImageOcrLayoutPage: TypeAlias = Annotated[
    list[_ImageOcrLayoutElement],
    Field(max_length=_IMAGE_OCR_MAX_LAYOUT_ELEMENTS),
]


class _ImageOcrPageInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    width: Any
    height: Any


class _ImageOcrDataInfo(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    num_pages: Any
    page_count: Any = None
    pages: list[_ImageOcrPageInfo] | None = Field(
        default=None,
        max_length=_IMAGE_OCR_MAX_PAGES,
    )


class _ImageOcrResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    model: str = Field(min_length=1, max_length=120, strict=True)
    layout_details: list[_ImageOcrLayoutPage] = Field(
        min_length=1,
        max_length=_IMAGE_OCR_MAX_PAGES,
    )
    data_info: _ImageOcrDataInfo


class ZhipuBrandDocumentOcrModel(BrandDocumentOcrModel):
    """Bounded adapter for Zhipu's private PDF layout-parsing endpoint."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: SecretStr,
        model: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        total_timeout_seconds: float,
        concurrency: int,
        max_attempts: int,
        max_request_bytes: int,
        max_response_bytes: int,
        max_pages: int,
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        if concurrency < 1 or max_attempts < 1:
            raise ValueError("OCR concurrency and attempts must be positive")
        if max_request_bytes < 1 or max_response_bytes < 1 or max_pages < 1:
            raise ValueError("OCR byte and page limits must be positive")
        parsed_base_url = urlsplit(base_url.strip())
        if (
            parsed_base_url.scheme != "https"
            or not parsed_base_url.hostname
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise ValueError("provider base URL must be an HTTPS origin/path without credentials")
        api_key_value = api_key.get_secret_value().strip()
        if not api_key_value or any(character in api_key_value for character in "\r\n"):
            raise ValueError("provider API key must not be blank or contain line breaks")
        if (
            not model.strip()
            or any(character.isspace() for character in model.strip())
            or len(model.strip()) > 120
        ):
            raise ValueError("OCR model must be a bounded identifier without whitespace")
        if (
            connect_timeout_seconds <= 0
            or read_timeout_seconds <= 0
            or total_timeout_seconds <= 0
            or total_timeout_seconds < read_timeout_seconds
        ):
            raise ValueError("OCR timeouts must be positive and total must cover read")
        self._client = client
        self._url = f"{base_url.strip().rstrip('/')}/layout_parsing"
        self._api_key = SecretStr(api_key_value)
        self._model = model.strip()
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes
        self._max_pages = max_pages
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            # OCR sends a bounded, but much larger, Base64 PDF body than the
            # JSON-only model calls. Give the upload its bounded OCR window.
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._total_timeout_seconds = total_timeout_seconds
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_attempts = max_attempts
        self._sleep = sleep

    async def parse_document(self, request: BrandDocumentOcrRequest) -> BrandDocumentOcrResult:
        if request.page_count > self._max_pages:
            raise BrandOcrInputLimitError()
        if sha256_bytes(request.original_bytes) != request.input_hash:
            raise BrandOcrInputLimitError()
        encoded = base64.b64encode(request.original_bytes).decode("ascii")
        payload: dict[str, Any] = {
            "model": self._model,
            "file": f"data:application/pdf;base64,{encoded}",
            "return_crop_images": False,
            "need_layout_visualization": False,
        }
        if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > (
            self._max_request_bytes
        ):
            raise BrandOcrInputLimitError()
        request_fingerprint = stable_key(
            request.version_id,
            request.input_hash,
            request.media_type,
            "zhipu",
            self._model,
        )
        started = perf_counter_ns()
        try:
            response = await _post_json_with_retries(
                client=self._client,
                url=self._url,
                api_key=self._api_key,
                http_timeout=self._timeout,
                total_timeout_seconds=self._total_timeout_seconds,
                semaphore=self._semaphore,
                max_attempts=self._max_attempts,
                sleep=self._sleep,
                payload=payload,
                max_response_bytes=self._max_response_bytes,
            )
        except ProviderAuthenticationError:
            raise BrandOcrAuthenticationError() from None
        except ProviderRateLimitError:
            raise BrandOcrRateLimitError() from None
        except ProviderTimeoutError:
            raise BrandOcrTimeoutError() from None
        except ProviderUnavailableError:
            raise BrandOcrUnavailableError() from None
        except ProviderRejectedError:
            raise BrandOcrRejectedError() from None
        except InvalidProviderOutputError:
            raise BrandOcrInvalidOutputError() from None
        try:
            parsed = _OcrResponse.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            raise BrandOcrInvalidOutputError() from None
        if parsed.model != self._model:
            raise BrandOcrIdentityMismatchError()
        markdown = _normalize_ocr_markdown(parsed.md_results)
        if not markdown:
            raise BrandOcrInvalidOutputError()
        page_count = _ocr_page_count(parsed.data_info, request.page_count)
        if page_count < 1 or page_count > self._max_pages:
            raise BrandOcrInvalidOutputError()
        return BrandDocumentOcrResult(
            markdown=markdown,
            provider="zhipu",
            model=parsed.model,
            request_fingerprint=request_fingerprint,
            provider_request_id=_safe_provider_request_id(parsed.id),
            page_count=page_count,
            prompt_tokens=parsed.usage.prompt_tokens,
            completion_tokens=parsed.usage.completion_tokens,
            latency_ms=max(0, (perf_counter_ns() - started) // 1_000_000),
        )


class ZhipuImageTextRecognizer:
    """Bounded image OCR adapter for Zhipu's dedicated layout-parsing capability."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: SecretStr,
        model: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        total_timeout_seconds: float,
        concurrency: int,
        max_attempts: int,
        max_input_bytes: int,
        max_response_bytes: int,
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        normalized_base_url = base_url.strip().rstrip("/")
        try:
            parsed_base_url = urlsplit(normalized_base_url)
            port = parsed_base_url.port
        except ValueError as exc:
            raise ValueError("image OCR base URL must be a valid HTTPS origin/path") from exc
        if (
            parsed_base_url.scheme != "https"
            or not parsed_base_url.hostname
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
            or (port is not None and not 1 <= port <= 65_535)
            or any(character.isspace() for character in normalized_base_url)
        ):
            raise ValueError("image OCR base URL must be an HTTPS origin/path without credentials")
        api_key_value = api_key.get_secret_value().strip()
        if not api_key_value or any(character in api_key_value for character in "\r\n"):
            raise ValueError("image OCR API key must not be blank or contain line breaks")
        normalized_model = model.strip()
        if (
            not normalized_model
            or len(normalized_model) > 120
            or any(character.isspace() for character in normalized_model)
        ):
            raise ValueError("image OCR model must be a bounded identifier without whitespace")
        if concurrency < 1 or max_attempts < 1:
            raise ValueError("image OCR concurrency and attempts must be positive")
        if not 1 <= max_input_bytes <= _IMAGE_OCR_MAX_INPUT_BYTES:
            raise ValueError("image OCR input limit must be between 1 byte and 10 MiB")
        if not 1 <= max_response_bytes <= _IMAGE_OCR_MAX_RESPONSE_BYTES:
            raise ValueError("image OCR response limit must be between 1 byte and 1 MiB")
        if (
            connect_timeout_seconds <= 0
            or read_timeout_seconds <= 0
            or total_timeout_seconds <= 0
            or total_timeout_seconds < read_timeout_seconds
        ):
            raise ValueError("image OCR timeouts must be positive and total must cover read")

        self._client = client
        self._url = f"{normalized_base_url}/layout_parsing"
        self._api_key = SecretStr(api_key_value)
        self._model = normalized_model
        self._max_input_bytes = max_input_bytes
        self._max_request_bytes = 4 * ((max_input_bytes + 2) // 3) + 1_024
        self._max_response_bytes = max_response_bytes
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._total_timeout_seconds = total_timeout_seconds
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_attempts = max_attempts
        self._sleep = sleep

    async def recognize(self, request: ImageTextRecognitionRequest) -> ImageTextRecognitionResult:
        media_type = request.media_type.casefold()
        if media_type not in {"image/png", "image/jpeg"}:
            raise ProviderInputLimitError()
        validation = validate_image_output(
            request.image_bytes,
            media_type,
            expected_dimensions=None,
            max_bytes=self._max_input_bytes,
        )
        if not validation.passed:
            raise ProviderInputLimitError()
        encoded = base64.b64encode(request.image_bytes).decode("ascii")
        payload: dict[str, Any] = {
            "model": self._model,
            "file": f"data:{media_type};base64,{encoded}",
            "return_crop_images": False,
            "need_layout_visualization": False,
        }
        try:
            request_bytes = len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
        except (TypeError, UnicodeError):
            raise ProviderInputLimitError() from None
        if request_bytes > self._max_request_bytes:
            raise ProviderInputLimitError()

        response = await _post_json_with_retries(
            client=self._client,
            url=self._url,
            api_key=self._api_key,
            http_timeout=self._timeout,
            total_timeout_seconds=self._total_timeout_seconds,
            semaphore=self._semaphore,
            max_attempts=self._max_attempts,
            sleep=self._sleep,
            payload=payload,
            max_response_bytes=self._max_response_bytes,
        )
        try:
            response_payload = response.json()
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError):
            raise InvalidProviderOutputError((_IMAGE_OCR_RESPONSE_ENVELOPE_ISSUE,)) from None
        _validate_image_ocr_response_source(response_payload)
        try:
            parsed = _ImageOcrResponse.model_validate(response_payload)
        except ValidationError as error:
            raise InvalidProviderOutputError(_image_ocr_schema_issues(error)) from None
        if parsed.model.casefold() != self._model.casefold():
            raise ProviderIdentityMismatchError()

        page, page_width, page_height, element_widths, element_heights = (
            _sole_image_ocr_layout_page(parsed)
        )
        recognized_lines = _project_image_ocr_lines(
            page,
            page_width=page_width,
            page_height=page_height,
            element_widths=element_widths,
            element_heights=element_heights,
        )
        text_validation = validate_exact_visual_text(
            recognized_lines,
            request.expected_text,
            require_order=request.require_order,
        )
        if not text_validation.passed:
            raise InvalidProviderOutputError(text_validation.issue_codes)
        try:
            return ImageTextRecognitionResult(
                recognized_lines=recognized_lines,
                provider=_IMAGE_OCR_PROVIDER,
                model=self._model,
                request_fingerprint=request.request_fingerprint,
            )
        except ValueError:
            raise InvalidProviderOutputError((_IMAGE_OCR_SCHEMA_ISSUE,)) from None


def _image_ocr_schema_issues(error: ValidationError) -> tuple[str, ...]:
    issues: set[str] = set()
    for issue in error.errors(include_url=False, include_context=False, include_input=False):
        location = issue.get("loc")
        if not isinstance(location, tuple) or not location:
            continue
        issue_type = issue.get("type")
        if location[0] == "layout_details" and issue_type == "extra_forbidden":
            issues.add(_IMAGE_OCR_ELEMENT_EXTRA_ISSUE)
        elif "index" in location:
            issues.add(_IMAGE_OCR_INDEX_ISSUE)
        elif "label" in location:
            issues.add(_IMAGE_OCR_LABEL_ISSUE)
        elif location[0] == "data_info" and ("height" in location or "width" in location):
            issues.add(_IMAGE_OCR_PAGE_DIMENSIONS_ISSUE)
        elif location[0] == "data_info":
            issues.add(_IMAGE_OCR_PAGE_COUNT_ISSUE)
        else:
            issues.add(_IMAGE_OCR_SCHEMA_ISSUE)
    priority = (
        _IMAGE_OCR_SCHEMA_ISSUE,
        _IMAGE_OCR_PAGE_COUNT_ISSUE,
        _IMAGE_OCR_PAGE_DIMENSIONS_ISSUE,
        _IMAGE_OCR_INDEX_ISSUE,
        _IMAGE_OCR_LABEL_ISSUE,
        _IMAGE_OCR_ELEMENT_EXTRA_ISSUE,
    )
    return tuple(code for code in priority if code in issues)[:4] or (_IMAGE_OCR_SCHEMA_ISSUE,)


def _validate_image_ocr_response_source(value: Any) -> None:
    if not isinstance(value, dict):
        return
    has_raw_layout = "layout_details" in value
    has_normalized_layout = "json_result" in value
    has_error = "error" in value
    if has_raw_layout and (has_normalized_layout or has_error):
        raise InvalidProviderOutputError((_IMAGE_OCR_SOURCE_CONFLICT_ISSUE,))
    if has_normalized_layout or has_error:
        raise InvalidProviderOutputError((_IMAGE_OCR_SOURCE_INVALID_ISSUE,))


def _sole_image_ocr_layout_page(
    response: _ImageOcrResponse,
) -> tuple[
    _ImageOcrLayoutPage,
    int | None,
    int | None,
    frozenset[int],
    frozenset[int],
]:
    num_pages = response.data_info.num_pages
    if (
        isinstance(num_pages, bool)
        or not isinstance(num_pages, int)
        or num_pages != 1
        or len(response.layout_details) != 1
    ):
        raise InvalidProviderOutputError((_IMAGE_OCR_PAGE_COUNT_ISSUE,))
    if "page_count" in response.data_info.model_fields_set:
        page_count = response.data_info.page_count
        if (
            isinstance(page_count, bool)
            or not isinstance(page_count, int)
            or page_count != num_pages
        ):
            raise InvalidProviderOutputError((_IMAGE_OCR_PAGE_COUNT_ISSUE,))
    pages = response.data_info.pages
    if "pages" in response.data_info.model_fields_set and (pages is None or len(pages) != 1):
        raise InvalidProviderOutputError((_IMAGE_OCR_PAGE_COUNT_ISSUE,))

    page = response.layout_details[0]
    page_info = pages[0] if pages is not None else None
    page_width = _image_ocr_dimension(page_info.width) if page_info is not None else None
    page_height = _image_ocr_dimension(page_info.height) if page_info is not None else None
    element_widths: set[int] = set()
    element_heights: set[int] = set()
    for element in page:
        width = _image_ocr_dimension(element.width)
        height = _image_ocr_dimension(element.height)
        if width is not None:
            element_widths.add(width)
        if height is not None:
            element_heights.add(height)
    return (
        page,
        page_width,
        page_height,
        frozenset(element_widths),
        frozenset(element_heights),
    )


def _image_ocr_dimension(value: Any) -> int | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= _IMAGE_OCR_MAX_DIMENSION
    ):
        raise InvalidProviderOutputError((_IMAGE_OCR_PAGE_DIMENSIONS_ISSUE,))
    return int(value)


def _project_image_ocr_lines(
    elements: list[_ImageOcrLayoutElement],
    *,
    page_width: int | None,
    page_height: int | None,
    element_widths: frozenset[int],
    element_heights: frozenset[int],
) -> tuple[str, ...]:
    indexed: set[int] = set()
    text_elements: list[tuple[tuple[float, float, float, float], int, str]] = []
    for element in elements:
        index = element.index
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= 1_000_000:
            raise InvalidProviderOutputError((_IMAGE_OCR_INDEX_ISSUE,))
        if index in indexed:
            raise InvalidProviderOutputError((_IMAGE_OCR_DUPLICATE_INDEX_ISSUE,))
        indexed.add(index)
        label = element.label
        if not isinstance(label, str) or label not in _IMAGE_OCR_LAYOUT_LABELS:
            raise InvalidProviderOutputError((_IMAGE_OCR_LABEL_ISSUE,))
        if label == "table":
            raise InvalidProviderOutputError((_IMAGE_OCR_TABLE_ISSUE,))
        if label == "formula":
            raise InvalidProviderOutputError((_IMAGE_OCR_FORMULA_ISSUE,))
        if label == "text":
            content = _validated_image_ocr_text_content(element.content)
            bbox = _image_ocr_bbox_shape(element.bbox_2d)
            text_elements.append((bbox, index, content))

    uses_pixel_bbox = any(max(bbox) > 1 for bbox, _index, _content in text_elements)
    if uses_pixel_bbox:
        if page_width is None:
            if len(element_widths) > 1:
                raise InvalidProviderOutputError((_IMAGE_OCR_PAGE_DIMENSIONS_CONFLICT_ISSUE,))
            page_width = next(iter(element_widths), None)
        if page_height is None:
            if len(element_heights) > 1:
                raise InvalidProviderOutputError((_IMAGE_OCR_PAGE_DIMENSIONS_CONFLICT_ISSUE,))
            page_height = next(iter(element_heights), None)
        if page_width is None or page_height is None:
            raise InvalidProviderOutputError((_IMAGE_OCR_BBOX_SCALE_ISSUE,))

    lines: list[str] = []
    ordered_text: list[tuple[float, float, int, str]] = []
    for bbox, index, content in text_elements:
        x1, y1, _x2, _y2 = _normalized_image_ocr_bbox(
            bbox,
            pixel_coordinates=uses_pixel_bbox,
            page_width=page_width,
            page_height=page_height,
        )
        ordered_text.append((y1, x1, index, content))
    for _y1, _x1, _index, content in sorted(ordered_text):
        for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            normalized = " ".join(raw_line.strip().split())
            if not normalized:
                continue
            if len(normalized) > 200:
                raise InvalidProviderOutputError((_IMAGE_OCR_LINE_LIMIT_ISSUE,))
            lines.append(normalized)
            if len(lines) > _IMAGE_OCR_MAX_LINES:
                raise InvalidProviderOutputError((_IMAGE_OCR_LINE_LIMIT_ISSUE,))
    return tuple(lines)


def _image_ocr_bbox_shape(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise InvalidProviderOutputError((_IMAGE_OCR_BBOX_SHAPE_ISSUE,))
    coordinates: list[float] = []
    for coordinate in value:
        if (
            isinstance(coordinate, bool)
            or not isinstance(coordinate, (int, float))
            or not math.isfinite(coordinate)
            or coordinate < 0
        ):
            raise InvalidProviderOutputError((_IMAGE_OCR_BBOX_SHAPE_ISSUE,))
        coordinates.append(float(coordinate))
    x1, y1, x2, y2 = coordinates
    if x1 >= x2 or y1 >= y2:
        raise InvalidProviderOutputError((_IMAGE_OCR_BBOX_SHAPE_ISSUE,))
    return x1, y1, x2, y2


def _normalized_image_ocr_bbox(
    value: tuple[float, float, float, float],
    *,
    pixel_coordinates: bool,
    page_width: int | None,
    page_height: int | None,
) -> tuple[float, float, float, float]:
    if not pixel_coordinates:
        return value
    if page_width is None or page_height is None:
        raise InvalidProviderOutputError((_IMAGE_OCR_BBOX_SCALE_ISSUE,))
    x1, y1, x2, y2 = value
    if x2 > page_width or y2 > page_height:
        raise InvalidProviderOutputError((_IMAGE_OCR_BBOX_RANGE_ISSUE,))
    return (
        x1 / page_width,
        y1 / page_height,
        x2 / page_width,
        y2 / page_height,
    )


def _validated_image_ocr_text_content(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidProviderOutputError((_IMAGE_OCR_CONTENT_TYPE_ISSUE,))
    if len(value) > _IMAGE_OCR_MAX_CONTENT_CHARACTERS:
        raise InvalidProviderOutputError((_IMAGE_OCR_CONTENT_LIMIT_ISSUE,))
    if any(
        (ord(character) < 32 and character not in "\t\r\n") or ord(character) == 127
        for character in value
    ):
        raise InvalidProviderOutputError((_IMAGE_OCR_CONTENT_LIMIT_ISSUE,))
    return value


def _normalize_ocr_markdown(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _ocr_page_count(data_info: dict[str, Any], fallback: int) -> int:
    for key in ("page_count", "num_pages", "pages"):
        value = data_info.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return fallback


class ZhipuFactualAnalysisModel:
    """OpenAI-compatible Zhipu adapter that returns only validated provider-neutral data."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: SecretStr,
        model: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        total_timeout_seconds: float,
        concurrency: int,
        max_attempts: int,
        max_input_characters: int,
        max_output_tokens: int,
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        if concurrency < 1 or max_attempts < 1:
            raise ValueError("provider concurrency and attempts must be positive")
        if not base_url.strip() or not model.strip():
            raise ValueError("provider base URL and model must not be blank")
        parsed_base_url = urlsplit(base_url.strip())
        if (
            parsed_base_url.scheme != "https"
            or not parsed_base_url.hostname
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise ValueError("provider base URL must be an HTTPS origin/path without credentials")
        api_key_value = api_key.get_secret_value().strip()
        if not api_key_value or any(character in api_key_value for character in "\r\n"):
            raise ValueError("provider API key must not be blank or contain line breaks")
        if any(character.isspace() for character in model.strip()) or len(model.strip()) > 120:
            raise ValueError("provider model must be a bounded identifier without whitespace")
        if (
            connect_timeout_seconds <= 0
            or read_timeout_seconds <= 0
            or total_timeout_seconds <= 0
            or total_timeout_seconds < read_timeout_seconds
        ):
            raise ValueError("provider timeouts must be positive and total must cover read")
        if max_input_characters < 1 or max_output_tokens < 1:
            raise ValueError("provider input and output limits must be positive")
        self._client = client
        self._url = f"{base_url.strip().rstrip('/')}/chat/completions"
        self._api_key = SecretStr(api_key_value)
        self._model = model.strip()
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=connect_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._total_timeout_seconds = total_timeout_seconds
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_attempts = max_attempts
        self._max_input_characters = max_input_characters
        self._max_output_tokens = max_output_tokens
        self._sleep = sleep

    async def analyze(self, request: FactualAnalysisRequest) -> FactualAnalysisResult:
        prompt = build_factual_analysis_prompt(request)
        input_characters = len(prompt.system_message) + len(prompt.user_message)
        if input_characters > self._max_input_characters:
            raise ProviderInputLimitError()
        bounded_output_tokens = min(request.max_output_tokens, self._max_output_tokens)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": prompt.system_message},
                {"role": "user", "content": prompt.user_message},
            ],
            # Factual analysis is a bounded JSON transformation. GLM-5.2 enables thinking by
            # default, which can consume the complete max_tokens budget before emitting content.
            # Keep that budget for the schema-bound answer, matching the other JSON adapters.
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "temperature": _TEMPERATURE,
            "max_tokens": bounded_output_tokens,
        }
        request_fingerprint = stable_key(
            request.candidate_id,
            prompt.fingerprint,
            "zhipu",
            self._model,
            bounded_output_tokens,
            _TEMPERATURE,
        )
        started = perf_counter_ns()
        response = await self._post_with_retries(payload)
        completion = self._parse_completion(response, bounded_output_tokens)
        analysis = self._parse_analysis(completion.choices[0].message.content)
        latency_ms = max(0, (perf_counter_ns() - started) // 1_000_000)
        details = completion.usage.completion_tokens_details
        provider_request_id = _safe_provider_request_id(
            completion.id or response.headers.get("x-request-id")
        )
        return FactualAnalysisResult(
            analysis=analysis,
            provider="zhipu",
            model=self._model,
            request_fingerprint=request_fingerprint,
            provider_request_id=provider_request_id,
            prompt_tokens=completion.usage.prompt_tokens,
            completion_tokens=completion.usage.completion_tokens,
            reasoning_tokens=details.reasoning_tokens if details is not None else 0,
            latency_ms=latency_ms,
        )

    async def _post_with_retries(self, payload: dict[str, Any]) -> httpx.Response:
        max_output_tokens = int(payload["max_tokens"])
        return await _post_json_with_retries(
            client=self._client,
            url=self._url,
            api_key=self._api_key,
            http_timeout=self._timeout,
            total_timeout_seconds=self._total_timeout_seconds,
            semaphore=self._semaphore,
            max_attempts=self._max_attempts,
            sleep=self._sleep,
            payload=payload,
            max_response_bytes=max(16_384, max_output_tokens * 16),
        )

    @staticmethod
    def _parse_completion(response: httpx.Response, max_output_tokens: int) -> _ChatCompletion:
        max_response_bytes = max(16_384, max_output_tokens * 16)
        if len(response.content) > max_response_bytes:
            raise InvalidProviderOutputError((AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,))
        try:
            payload = response.json()
            completion = _ChatCompletion.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            raise InvalidProviderOutputError(
                (AnalysisValidationCode.INVALID_SCHEMA.value,)
            ) from None
        if completion.usage.completion_tokens > max_output_tokens:
            raise InvalidProviderOutputError((AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,))
        return completion

    @staticmethod
    def _parse_analysis(content: str) -> FactualAnalysisOutput:
        try:
            return FactualAnalysisOutput.model_validate_json(content)
        except ValidationError as exc:
            issue_codes = _safe_schema_issue_codes(exc)
            raise InvalidProviderOutputError(issue_codes) from None


class ZhipuEmbeddingModel:
    """Bounded embedding-3 adapter with a fixed persistence dimension."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: SecretStr,
        model: str,
        dimensions: int,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        total_timeout_seconds: float,
        concurrency: int,
        max_attempts: int,
        max_input_characters: int,
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        if dimensions != 2048:
            raise ValueError("embedding-3 adapter requires the fixed 2048 dimension")
        if concurrency < 1 or max_attempts < 1 or max_input_characters < 1:
            raise ValueError("embedding concurrency, attempts, and input limit must be positive")
        parsed_base_url = urlsplit(base_url.strip())
        if (
            parsed_base_url.scheme != "https"
            or not parsed_base_url.hostname
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise ValueError("provider base URL must be an HTTPS origin/path without credentials")
        api_key_value = api_key.get_secret_value().strip()
        if not api_key_value or any(character in api_key_value for character in "\r\n"):
            raise ValueError("provider API key must not be blank or contain line breaks")
        if (
            not model.strip()
            or any(character.isspace() for character in model.strip())
            or len(model.strip()) > 120
        ):
            raise ValueError("provider model must be a bounded identifier without whitespace")
        if (
            connect_timeout_seconds <= 0
            or read_timeout_seconds <= 0
            or total_timeout_seconds <= 0
            or total_timeout_seconds < read_timeout_seconds
        ):
            raise ValueError("provider timeouts must be positive and total must cover read")
        self._client = client
        self._url = f"{base_url.strip().rstrip('/')}/embeddings"
        self._api_key = SecretStr(api_key_value)
        self._model = model.strip()
        self._dimensions = dimensions
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=connect_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._total_timeout_seconds = total_timeout_seconds
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_attempts = max_attempts
        self._max_input_characters = max_input_characters
        self._sleep = sleep

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        if len(request.text) > self._max_input_characters:
            raise ProviderInputLimitError()
        payload: dict[str, Any] = {
            "model": self._model,
            "input": request.text,
            "dimensions": self._dimensions,
        }
        request_fingerprint = stable_key(
            request.artifact_id,
            request.purpose.value,
            request.input_hash,
            "zhipu",
            self._model,
            self._dimensions,
        )
        started = perf_counter_ns()
        response = await _post_json_with_retries(
            client=self._client,
            url=self._url,
            api_key=self._api_key,
            http_timeout=self._timeout,
            total_timeout_seconds=self._total_timeout_seconds,
            semaphore=self._semaphore,
            max_attempts=self._max_attempts,
            sleep=self._sleep,
            payload=payload,
            max_response_bytes=_MAX_EMBEDDING_RESPONSE_BYTES,
        )
        try:
            parsed = _EmbeddingResponse.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            raise InvalidProviderOutputError(
                (AnalysisValidationCode.INVALID_SCHEMA.value,)
            ) from None
        vector = parsed.data[0].embedding
        if len(vector) != request.expected_dimensions or len(vector) != self._dimensions:
            raise ProviderDimensionMismatchError()
        if any(not math.isfinite(value) for value in vector) or not any(vector):
            raise InvalidProviderOutputError((AnalysisValidationCode.INVALID_SCHEMA.value,))
        return EmbeddingResult(
            vector=vector,
            provider="zhipu",
            model=self._model,
            dimensions=len(vector),
            request_fingerprint=request_fingerprint,
            provider_request_id=_safe_provider_request_id(
                parsed.id or response.headers.get("x-request-id")
            ),
            prompt_tokens=parsed.usage.prompt_tokens or parsed.usage.total_tokens,
            latency_ms=max(0, (perf_counter_ns() - started) // 1_000_000),
        )


async def _post_json_with_retries(
    *,
    client: httpx.AsyncClient,
    url: str,
    api_key: SecretStr,
    http_timeout: httpx.Timeout,
    total_timeout_seconds: float,
    semaphore: asyncio.Semaphore,
    max_attempts: int,
    sleep: _Sleep,
    payload: dict[str, Any],
    max_response_bytes: int,
) -> httpx.Response:
    if max_response_bytes < 1:
        raise ValueError("provider response byte limit must be positive")
    last_error: ProviderRateLimitError | ProviderTimeoutError | ProviderUnavailableError | None = (
        None
    )
    for attempt in range(1, max_attempts + 1):
        try:
            async with semaphore:
                async with asyncio.timeout(total_timeout_seconds):
                    async with client.stream(
                        "POST",
                        url,
                        headers={
                            "Authorization": f"Bearer {api_key.get_secret_value()}",
                            "Accept-Encoding": _ACCEPT_ENCODING,
                            "Content-Type": "application/json",
                        },
                        json=payload,
                        timeout=http_timeout,
                    ) as streamed_response:
                        if streamed_response.status_code >= 400:
                            response = httpx.Response(
                                status_code=streamed_response.status_code,
                                headers=streamed_response.headers,
                                content=b"",
                                request=streamed_response.request,
                            )
                        else:
                            response = await _read_bounded_response(
                                streamed_response,
                                max_response_bytes=max_response_bytes,
                            )
        except (TimeoutError, httpx.TimeoutException):
            last_error = ProviderTimeoutError()
        except httpx.RequestError:
            last_error = ProviderUnavailableError()
        else:
            if response.status_code in {401, 403}:
                raise ProviderAuthenticationError()
            if response.status_code == 429:
                last_error = ProviderRateLimitError()
            elif 500 <= response.status_code <= 599:
                last_error = ProviderUnavailableError()
            elif response.status_code >= 400:
                raise ProviderRejectedError()
            else:
                return response
        if attempt < max_attempts:
            await sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
    if last_error is None:
        raise ProviderUnavailableError()
    raise last_error


async def _read_bounded_response(
    response: httpx.Response,
    *,
    max_response_bytes: int,
) -> httpx.Response:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_bytes = int(content_length)
        except ValueError:
            raise InvalidProviderOutputError(
                (AnalysisValidationCode.INVALID_SCHEMA.value,)
            ) from None
        if declared_bytes < 0:
            raise InvalidProviderOutputError((AnalysisValidationCode.INVALID_SCHEMA.value,))
        if declared_bytes > max_response_bytes:
            raise InvalidProviderOutputError((AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,))
    content_encoding = response.headers.get("content-encoding", "identity").strip().casefold()
    if content_encoding not in {"", "identity", _ACCEPT_ENCODING}:
        raise InvalidProviderOutputError((AnalysisValidationCode.INVALID_SCHEMA.value,))
    if response.is_stream_consumed:
        # MockTransport and preloaded responses have already passed through httpx's decoder.
        # The declared length still bounds the encoded body while this check bounds decoded bytes.
        content = response.content
        if len(content) > max_response_bytes:
            raise InvalidProviderOutputError((AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,))
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.casefold() not in {"content-encoding", "content-length", "transfer-encoding"}
        }
        return httpx.Response(
            status_code=response.status_code,
            headers=headers,
            content=content,
            request=response.request,
        )
    decoder = (
        zlib.decompressobj(zlib.MAX_WBITS | 16) if content_encoding == _ACCEPT_ENCODING else None
    )
    chunks: list[bytes] = []
    raw_byte_count = 0
    decoded_byte_count = 0
    try:
        async for raw_chunk in response.aiter_raw():
            raw_byte_count += len(raw_chunk)
            if raw_byte_count > max_response_bytes:
                raise InvalidProviderOutputError(
                    (AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,)
                )
            decoded_chunk = raw_chunk
            if decoder is not None:
                decoded_chunk = decoder.decompress(
                    raw_chunk,
                    max_response_bytes - decoded_byte_count + 1,
                )
            decoded_byte_count += len(decoded_chunk)
            if decoded_byte_count > max_response_bytes:
                raise InvalidProviderOutputError(
                    (AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,)
                )
            if decoder is not None and decoder.unconsumed_tail:
                raise InvalidProviderOutputError(
                    (AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,)
                )
            chunks.append(decoded_chunk)
        if decoder is not None:
            trailing = decoder.flush(max_response_bytes - decoded_byte_count + 1)
            decoded_byte_count += len(trailing)
            if decoded_byte_count > max_response_bytes:
                raise InvalidProviderOutputError(
                    (AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,)
                )
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise InvalidProviderOutputError((AnalysisValidationCode.INVALID_SCHEMA.value,))
            chunks.append(trailing)
    except zlib.error:
        raise InvalidProviderOutputError((AnalysisValidationCode.INVALID_SCHEMA.value,)) from None
    headers = {
        key: value
        for key, value in response.headers.items()
        if key.casefold() not in {"content-encoding", "content-length", "transfer-encoding"}
    }
    return httpx.Response(
        status_code=response.status_code,
        headers=headers,
        content=b"".join(chunks),
        request=response.request,
    )


def _safe_provider_request_id(value: str | None) -> str | None:
    if value is None or _SAFE_PROVIDER_REQUEST_ID.fullmatch(value) is None:
        return None
    return value


def _safe_schema_issue_codes(error: ValidationError) -> tuple[str, ...]:
    issue_codes: list[str] = []
    for issue in error.errors(include_url=False, include_input=False):
        location = tuple(str(part) for part in issue.get("loc", ()))
        issue_type = str(issue.get("type", ""))
        if issue_type == "json_invalid":
            code = AnalysisValidationCode.MALFORMED_JSON
        elif "categories" in location and issue_type in {"enum", "literal_error"}:
            code = AnalysisValidationCode.UNSUPPORTED_TAXONOMY
        elif "passage_ids" in location and issue_type in {
            "missing",
            "too_short",
            "list_type",
            "tuple_type",
        }:
            code = AnalysisValidationCode.MISSING_EVIDENCE
        elif issue_type == "extra_forbidden":
            code = AnalysisValidationCode.UNEXPECTED_FIELD
        else:
            code = AnalysisValidationCode.INVALID_SCHEMA
        if code.value not in issue_codes:
            issue_codes.append(code.value)
    specific_codes = [
        code for code in issue_codes if code != AnalysisValidationCode.INVALID_SCHEMA.value
    ]
    if specific_codes:
        return tuple(specific_codes)
    return tuple(issue_codes) or (AnalysisValidationCode.INVALID_SCHEMA.value,)
