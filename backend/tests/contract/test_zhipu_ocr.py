from __future__ import annotations

import base64
import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.application.ports.brand_knowledge import BrandDocumentOcrRequest
from app.core.errors import (
    BrandOcrInputLimitError,
    BrandOcrInvalidOutputError,
    BrandOcrInvalidOutputReason,
    BrandOcrRateLimitError,
)
from app.domain.brand_knowledge import BrandLayoutSemanticRole, BrandOcrBlockKind
from app.domain.value_objects import sha256_bytes
from app.infrastructure.ai.zhipu import ZhipuBrandDocumentOcrModel
from pydantic import SecretStr

VERSION_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PDF_BODY = b"%PDF-1.7\nminimal contract fixture"
_NATIVE_LABEL_UNSET = object()


def _request(
    body: bytes = PDF_BODY,
    *,
    require_layout: bool = False,
) -> BrandDocumentOcrRequest:
    return BrandDocumentOcrRequest(
        version_id=VERSION_ID,
        input_hash=sha256_bytes(body),
        media_type="application/pdf",
        page_count=2,
        original_bytes=body,
        require_layout=require_layout,
    )


async def _no_sleep(_: float) -> None:
    return None


def _adapter(
    transport: httpx.AsyncBaseTransport,
    *,
    max_attempts: int = 2,
    max_request_bytes: int = 10 * 1024 * 1024,
    max_response_bytes: int = 1024 * 1024,
) -> tuple[ZhipuBrandDocumentOcrModel, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=transport)
    return (
        ZhipuBrandDocumentOcrModel(
            client=client,
            base_url="https://open.bigmodel.invalid/api/paas/v4",
            api_key=SecretStr("local-contract-secret"),
            model="glm-ocr",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=max_attempts,
            max_request_bytes=max_request_bytes,
            max_response_bytes=max_response_bytes,
            max_pages=100,
            sleep=_no_sleep,
        ),
        client,
    )


def _response_payload(
    *, model: str = "glm-ocr", markdown: str = "# 赛先生\n\n品牌原则"
) -> dict[str, Any]:
    return {
        "id": "ocr-request-1",
        "model": model,
        "md_results": markdown,
        "data_info": {"num_pages": 2, "num_chars": 8},
        "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46},
    }


def _layout_element(
    index: object,
    label: object,
    content: object,
    bbox: object,
    *,
    width: object = 1_000,
    height: object = 500,
    native_label: object = _NATIVE_LABEL_UNSET,
) -> dict[str, object]:
    element = {
        "index": index,
        "label": label,
        "content": content,
        "bbox_2d": bbox,
        "width": width,
        "height": height,
    }
    if native_label is not _NATIVE_LABEL_UNSET:
        element["native_label"] = native_label
    return element


def _valid_layout_payload(*, markdown: str) -> dict[str, Any]:
    payload = _response_payload(markdown=markdown)
    payload["layout_details"] = [
        [_layout_element(0, "text", "合成标题", [0.1, 0.1, 0.8, 0.2])],
        [],
    ]
    payload["data_info"] = {
        "num_pages": 2,
        "page_count": 2,
        "pages": [
            {"width": 1_000, "height": 500},
            {"width": 1_000, "height": 500},
        ],
    }
    return payload


def _invalid_layout_payload(case: str, *, sentinel: str) -> dict[str, Any]:
    payload = _valid_layout_payload(markdown=sentinel)
    first = payload["layout_details"][0][0]
    if case == "layout_schema":
        payload["layout_details"] = {"private": sentinel}
    elif case == "source_invalid":
        del payload["layout_details"]
        payload["json_result"] = {"private": sentinel}
    elif case == "page_count":
        payload["layout_details"] = payload["layout_details"][:1]
    elif case == "page_dimensions":
        payload["data_info"]["pages"][0]["width"] = sentinel
    elif case == "page_dimensions_conflict":
        first["width"] = 900
    elif case == "index_invalid":
        first["index"] = True
    elif case == "index_duplicate":
        payload["layout_details"][0].append(
            _layout_element(0, "text", "合成正文", [0.1, 0.3, 0.8, 0.5])
        )
    elif case == "label_unknown":
        first["label"] = "private-label-" + sentinel
    elif case == "bbox_shape":
        first["bbox_2d"] = [0.1, 0.1, 0.8]
    elif case == "bbox_scale":
        payload["layout_details"][0].append(
            _layout_element(1, "text", "合成正文", [100, 150, 800, 300])
        )
    elif case == "bbox_range":
        first["bbox_2d"] = [100, 50, 1_200, 220]
    elif case == "content_type":
        first["content"] = {"private": sentinel}
    elif case == "content_limit":
        first["content"] = sentinel + ("x" * 50_000)
    elif case == "native_label_unknown":
        first["native_label"] = "private-native-" + sentinel
    elif case == "native_label_type":
        first["native_label"] = {"private": sentinel}
    elif case == "native_label_empty":
        first["native_label"] = ""
    elif case == "native_label_limit":
        first["native_label"] = sentinel + ("x" * 65)
    elif case == "native_label_control":
        first["native_label"] = "content\t" + sentinel
    elif case == "native_label_conflict":
        first["native_label"] = "table"
    elif case == "element_extra":
        first["private_extra"] = sentinel
    elif case == "source_conflict":
        payload["json_result"] = {"private": sentinel}
    else:
        raise AssertionError("unknown synthetic brand OCR failure case")
    return payload


@pytest.mark.asyncio
async def test_layout_parsing_sends_bounded_private_base64_pdf() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        payload = json.loads(request.content)
        captured["payload"] = payload
        return httpx.Response(200, json=_response_payload())

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        result = await adapter.parse_document(_request())

    payload = captured["payload"]
    assert captured["url"] == "https://open.bigmodel.invalid/api/paas/v4/layout_parsing"
    assert captured["authorization"] == "Bearer local-contract-secret"
    assert isinstance(payload, dict)
    encoded_file = payload["file"]
    assert encoded_file.startswith("data:application/pdf;base64,")
    assert base64.b64decode(encoded_file.split(",", 1)[1]) == PDF_BODY
    assert payload["model"] == "glm-ocr"
    assert payload["return_crop_images"] is False
    assert payload["need_layout_visualization"] is False
    assert result.markdown == "# 赛先生\n\n品牌原则"
    assert result.page_count == 2
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 34
    assert result.layout_pages == ()
    assert "local-contract-secret" not in repr(result)
    assert "# 赛先生" not in repr(result)
    assert "minimal contract fixture" not in repr(_request())


@pytest.mark.asyncio
async def test_document_ocr_projects_typed_multi_page_layout_without_image_content() -> None:
    sentinel = "private-image-content-sentinel"
    payload = _response_payload()
    payload["layout_details"] = [
        [
            _layout_element(
                8,
                "text",
                "页面标题",
                [0.1, 0.1, 0.5, 0.2],
                native_label="doc_title",
            ),
            _layout_element(
                9,
                "text",
                "页面说明。",
                [0.1, 0.24, 0.5, 0.4],
                native_label="content",
            ),
        ],
        [
            _layout_element(
                0,
                "table",
                "|产品|能力|\n|---|---|",
                [100, 50, 900, 220],
                native_label="table",
            ),
            _layout_element(
                1,
                "formula",
                "E = mc^2",
                [100, 260, 900, 340],
                native_label="display_formula",
            ),
            _layout_element(
                2,
                "image",
                sentinel,
                {"private": sentinel},
                native_label="chart",
            ),
        ],
    ]
    payload["data_info"] = {
        "num_pages": 2,
        "page_count": 2,
        "pages": [
            {"width": 1_000, "height": 500},
            {"width": 1_000, "height": 500},
        ],
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        result = await adapter.parse_document(_request(require_layout=True))

    assert [page.page_number for page in result.layout_pages] == [1, 2]
    assert [block.kind for block in result.layout_pages[0].blocks] == [
        BrandOcrBlockKind.TEXT,
        BrandOcrBlockKind.TEXT,
    ]
    assert [block.kind for block in result.layout_pages[1].blocks] == [
        BrandOcrBlockKind.TABLE,
        BrandOcrBlockKind.FORMULA,
    ]
    assert [block.semantic_role for block in result.layout_pages[0].blocks] == [
        BrandLayoutSemanticRole.DOC_TITLE,
        BrandLayoutSemanticRole.CONTENT,
    ]
    assert [block.semantic_role for block in result.layout_pages[1].blocks] == [
        BrandLayoutSemanticRole.TABLE,
        BrandLayoutSemanticRole.DISPLAY_FORMULA,
    ]
    assert result.layout_pages[1].blocks[0].normalized_bbox == (0.1, 0.1, 0.9, 0.44)
    assert sentinel not in repr(result)
    assert "页面标题" not in repr(result)
    assert "|产品|能力|" not in repr(result)


@pytest.mark.asyncio
async def test_document_ocr_accepts_the_closed_native_role_groups() -> None:
    official_pp_doc_layout_v3_id_labels = (
        "abstract",
        "algorithm",
        "aside_text",
        "chart",
        "content",
        "display_formula",
        "doc_title",
        "figure_title",
        "footer",
        "footer_image",
        "footnote",
        "formula_number",
        "header",
        "header_image",
        "image",
        "inline_formula",
        "number",
        "paragraph_title",
        "reference",
        "reference_content",
        "seal",
        "table",
        "text",
        "vertical_text",
        "vision_footnote",
    )
    canonical_by_role = {
        "abstract": "text",
        "algorithm": "text",
        "aside_text": "text",
        "chart": "image",
        "content": "text",
        "display_formula": "formula",
        "doc_title": "text",
        "figure_title": "text",
        "footer": "text",
        "footer_image": "image",
        "footnote": "text",
        "formula_number": "text",
        "header": "text",
        "header_image": "image",
        "image": "image",
        "inline_formula": "formula",
        "number": "text",
        "paragraph_title": "text",
        "reference": "text",
        "reference_content": "text",
        "seal": "text",
        "table": "table",
        "text": "text",
        "vertical_text": "text",
        "vision_footnote": "text",
    }
    assert len(official_pp_doc_layout_v3_id_labels) == 25
    assert len(set(official_pp_doc_layout_v3_id_labels)) == 25
    assert set(official_pp_doc_layout_v3_id_labels) == set(canonical_by_role)
    assert len(canonical_by_role) == 25
    assert {role.value for role in BrandLayoutSemanticRole} == set(canonical_by_role)
    payload = _response_payload()
    payload["layout_details"] = [
        [
            _layout_element(
                index,
                canonical_label,
                f"synthetic-{native_label}",
                [0.1, 0.1, 0.9, 0.2],
                native_label=native_label,
            )
            for index, (native_label, canonical_label) in enumerate(canonical_by_role.items())
        ],
        [],
    ]
    payload["data_info"] = {
        "num_pages": 2,
        "pages": [{"width": 1_000, "height": 500}, {"width": 1_000, "height": 500}],
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        result = await adapter.parse_document(_request(require_layout=True))

    projected_roles = [block.semantic_role for page in result.layout_pages for block in page.blocks]
    assert projected_roles == [
        BrandLayoutSemanticRole(native_label)
        for native_label, canonical_label in canonical_by_role.items()
        if canonical_label != "image"
    ]
    assert {
        role for role, canonical_label in canonical_by_role.items() if canonical_label == "image"
    } == {"chart", "footer_image", "header_image", "image"}


@pytest.mark.asyncio
async def test_document_ocr_native_label_omission_retains_v4_compatibility() -> None:
    payload = _valid_layout_payload(markdown="# compatibility")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        result = await adapter.parse_document(_request(require_layout=True))

    assert result.layout_pages[0].blocks[0].semantic_role is None


@pytest.mark.asyncio
async def test_frozen_v2_v3_ocr_ignores_layout_refinements() -> None:
    sentinel = "private-v3-layout-sentinel"
    payload = _response_payload(markdown="# frozen Markdown")
    payload["layout_details"] = [
        [
            {
                **_layout_element(
                    0,
                    "text",
                    sentinel,
                    [0.1, 0.1, 0.9, 0.2],
                    native_label="header",
                ),
                "private_extra": sentinel,
            }
        ],
        [],
    ]
    payload["json_result"] = {"private": sentinel}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        result = await adapter.parse_document(_request(require_layout=False))

    assert result.markdown == "# frozen Markdown"
    assert result.layout_pages == ()
    assert sentinel not in repr(result)


def test_brand_ocr_invalid_output_reason_is_allowlisted_and_content_free() -> None:
    sentinel = "private-reason-sentinel"
    error = BrandOcrInvalidOutputError(sentinel)

    assert error.code == "brand_ocr_invalid_output"
    assert error.message == "brand OCR provider returned invalid output"
    assert error.reason == BrandOcrInvalidOutputReason.OUTPUT_INVALID.value
    assert sentinel not in str(error)
    assert sentinel not in repr(error)


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    (
        ("transport_body", BrandOcrInvalidOutputReason.TRANSPORT_BODY_INVALID),
        ("base_schema", BrandOcrInvalidOutputReason.BASE_SCHEMA_INVALID),
    ),
)
@pytest.mark.asyncio
async def test_document_ocr_classifies_outer_response_failures_without_exposing_body(
    case: str,
    expected_reason: BrandOcrInvalidOutputReason,
) -> None:
    sentinel = "private-provider-body-sentinel"

    def handler(_: httpx.Request) -> httpx.Response:
        if case == "transport_body":
            return httpx.Response(200, content=("{" + sentinel).encode())
        payload = _response_payload(markdown=sentinel)
        payload["usage"] = {"prompt_tokens": sentinel}
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(BrandOcrInvalidOutputError) as raised:
            await adapter.parse_document(_request(require_layout=True))

    assert raised.value.reason == expected_reason.value
    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value)
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    (
        ("layout_schema", BrandOcrInvalidOutputReason.LAYOUT_SCHEMA_INVALID),
        ("source_invalid", BrandOcrInvalidOutputReason.LAYOUT_SOURCE_INVALID),
        ("page_count", BrandOcrInvalidOutputReason.LAYOUT_PAGE_COUNT_INVALID),
        (
            "page_dimensions",
            BrandOcrInvalidOutputReason.LAYOUT_PAGE_DIMENSIONS_INVALID,
        ),
        (
            "page_dimensions_conflict",
            BrandOcrInvalidOutputReason.LAYOUT_PAGE_DIMENSIONS_CONFLICT,
        ),
        ("index_invalid", BrandOcrInvalidOutputReason.LAYOUT_INDEX_INVALID),
        ("index_duplicate", BrandOcrInvalidOutputReason.LAYOUT_INDEX_DUPLICATE),
        ("label_unknown", BrandOcrInvalidOutputReason.LAYOUT_LABEL_UNKNOWN),
        ("bbox_shape", BrandOcrInvalidOutputReason.LAYOUT_BBOX_SHAPE_INVALID),
        ("bbox_scale", BrandOcrInvalidOutputReason.LAYOUT_BBOX_SCALE_INVALID),
        ("bbox_range", BrandOcrInvalidOutputReason.LAYOUT_BBOX_RANGE_INVALID),
        ("content_type", BrandOcrInvalidOutputReason.LAYOUT_CONTENT_TYPE_INVALID),
        (
            "content_limit",
            BrandOcrInvalidOutputReason.LAYOUT_CONTENT_LIMIT_EXCEEDED,
        ),
        (
            "native_label_unknown",
            BrandOcrInvalidOutputReason.LAYOUT_NATIVE_LABEL_UNKNOWN,
        ),
        (
            "native_label_type",
            BrandOcrInvalidOutputReason.LAYOUT_NATIVE_LABEL_TYPE_INVALID,
        ),
        (
            "native_label_empty",
            BrandOcrInvalidOutputReason.LAYOUT_NATIVE_LABEL_TYPE_INVALID,
        ),
        (
            "native_label_limit",
            BrandOcrInvalidOutputReason.LAYOUT_NATIVE_LABEL_LIMIT_EXCEEDED,
        ),
        (
            "native_label_control",
            BrandOcrInvalidOutputReason.LAYOUT_NATIVE_LABEL_LIMIT_EXCEEDED,
        ),
        (
            "native_label_conflict",
            BrandOcrInvalidOutputReason.LAYOUT_NATIVE_LABEL_CONFLICT,
        ),
        ("element_extra", BrandOcrInvalidOutputReason.LAYOUT_ELEMENT_EXTRA),
        ("source_conflict", BrandOcrInvalidOutputReason.LAYOUT_SOURCE_CONFLICT),
    ),
)
@pytest.mark.asyncio
async def test_document_ocr_classifies_layout_failure_stage_without_exposing_payload(
    case: str,
    expected_reason: BrandOcrInvalidOutputReason,
) -> None:
    sentinel = "private-layout-diagnostic-sentinel"
    payload = _invalid_layout_payload(case, sentinel=sentinel)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(BrandOcrInvalidOutputError) as raised:
            await adapter.parse_document(_request(require_layout=True))

    assert raised.value.reason == expected_reason.value
    assert raised.value.code == "brand_ocr_invalid_output"
    assert raised.value.message == "brand OCR provider returned invalid output"
    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value)
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


def test_document_ocr_unknown_shared_layout_issue_uses_generic_reason() -> None:
    from app.infrastructure.ai.zhipu import _brand_ocr_layout_reason

    assert (
        _brand_ocr_layout_reason(("future_image_ocr_issue",))
        == BrandOcrInvalidOutputReason.OUTPUT_INVALID
    )


@pytest.mark.parametrize(
    ("layout_details", "expected_reason"),
    (
        (
            [
                [
                    _layout_element(0, "text", "标题", [0.1, 0.1, 0.5, 0.2]),
                    _layout_element(0, "text", "正文", [0.1, 0.3, 0.5, 0.4]),
                ],
                [],
            ],
            BrandOcrInvalidOutputReason.LAYOUT_INDEX_DUPLICATE,
        ),
        (
            [
                [
                    _layout_element(0, "text", "标题", [0.1, 0.1, 0.5, 0.2]),
                    _layout_element(1, "text", "正文", [100, 150, 500, 300]),
                ],
                [],
            ],
            BrandOcrInvalidOutputReason.LAYOUT_BBOX_SCALE_INVALID,
        ),
        (
            [[_layout_element(0, "caption", "标题", [0.1, 0.1, 0.5, 0.2])], []],
            BrandOcrInvalidOutputReason.LAYOUT_LABEL_UNKNOWN,
        ),
    ),
)
@pytest.mark.asyncio
async def test_document_ocr_rejects_invalid_layout_contract_without_exposing_content(
    layout_details: object,
    expected_reason: BrandOcrInvalidOutputReason,
) -> None:
    sentinel = "private-provider-layout-sentinel"
    payload = _response_payload(markdown=sentinel)
    payload["layout_details"] = layout_details
    payload["data_info"] = {
        "num_pages": 2,
        "pages": [
            {"width": 1_000, "height": 500},
            {"width": 1_000, "height": 500},
        ],
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(BrandOcrInvalidOutputError) as raised:
            await adapter.parse_document(_request(require_layout=True))

    assert raised.value.code == "brand_ocr_invalid_output"
    assert raised.value.message == "brand OCR provider returned invalid output"
    assert raised.value.reason == expected_reason.value
    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value)
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_document_ocr_rejects_page_count_conflict_before_projection() -> None:
    payload = _response_payload()
    payload["data_info"] = {"num_pages": 1}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(BrandOcrInvalidOutputError) as raised:
            await adapter.parse_document(_request())
    assert raised.value.reason == BrandOcrInvalidOutputReason.PAGE_IDENTITY_INVALID.value


@pytest.mark.asyncio
async def test_document_ocr_requires_layout_only_for_v4_request() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response_payload())

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(BrandOcrInvalidOutputError) as raised:
            await adapter.parse_document(_request(require_layout=True))
    assert raised.value.reason == BrandOcrInvalidOutputReason.LAYOUT_MISSING.value


@pytest.mark.asyncio
async def test_document_ocr_rejects_conflicting_page_and_element_dimensions() -> None:
    payload = _response_payload()
    payload["layout_details"] = [
        [_layout_element(0, "text", "标题", [100, 50, 900, 220], width=900)],
        [],
    ]
    payload["data_info"] = {
        "num_pages": 2,
        "pages": [
            {"width": 1_000, "height": 500},
            {"width": 1_000, "height": 500},
        ],
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(BrandOcrInvalidOutputError) as raised:
            await adapter.parse_document(_request(require_layout=True))
    assert raised.value.reason == BrandOcrInvalidOutputReason.LAYOUT_PAGE_DIMENSIONS_CONFLICT.value


@pytest.mark.asyncio
async def test_ocr_rejects_encoded_request_before_provider_call() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    adapter, client = _adapter(
        httpx.MockTransport(handler), max_attempts=2, max_request_bytes=len(PDF_BODY)
    )
    async with client:
        with pytest.raises(BrandOcrInputLimitError):
            await adapter.parse_document(_request())
    assert requests == 0


@pytest.mark.asyncio
async def test_ocr_invalid_output_and_identity_are_terminal() -> None:
    responses = iter(
        (
            {**_response_payload(), "md_results": "   "},
            _response_payload(model="other-ocr"),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(BrandOcrInvalidOutputError) as markdown_error:
            await adapter.parse_document(_request())
        with pytest.raises(BrandOcrInvalidOutputError) as model_error:
            await adapter.parse_document(_request())
    assert markdown_error.value.reason == BrandOcrInvalidOutputReason.MARKDOWN_INVALID.value
    assert model_error.value.reason == BrandOcrInvalidOutputReason.MODEL_IDENTITY_INVALID.value


@pytest.mark.asyncio
async def test_ocr_response_limit_is_a_brand_typed_terminal_failure() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": "2048"},
            content=b"{}",
        )

    adapter, client = _adapter(
        httpx.MockTransport(handler), max_attempts=1, max_response_bytes=1024
    )
    async with client:
        with pytest.raises(BrandOcrInvalidOutputError) as raised:
            await adapter.parse_document(_request())
    assert raised.value.reason == BrandOcrInvalidOutputReason.TRANSPORT_BODY_INVALID.value


@pytest.mark.asyncio
async def test_ocr_rate_limit_retries_and_exhaustion_is_typed() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, json={"error": {"message": "private body"}})

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=2)
    async with client:
        with pytest.raises(BrandOcrRateLimitError) as raised:
            await adapter.parse_document(_request())
    assert attempts == 2
    assert raised.value.retryable is True
    assert "private body" not in str(raised.value)
