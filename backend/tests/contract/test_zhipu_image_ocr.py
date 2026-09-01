from __future__ import annotations

import base64
import json
from collections.abc import Callable
from io import BytesIO
from typing import Any

import httpx
import pytest
from app.application.ports.image_validation import ImageTextRecognitionRequest
from app.core.errors import (
    InvalidProviderOutputError,
    ProviderAuthenticationError,
    ProviderIdentityMismatchError,
    ProviderInputLimitError,
    ProviderRateLimitError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.infrastructure.ai.zhipu import ZhipuImageTextRecognizer
from PIL import Image
from pydantic import SecretStr

EXPECTED_TEXT = ("赛先生科学", "人工智能", "理解智能如何学习与反馈")
_NATIVE_LABEL_UNSET = object()


def _raster(format_name: str = "PNG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (16, 16), (20, 54, 96)).save(output, format=format_name)
    return output.getvalue()


PNG_BODY = _raster()
JPEG_BODY = _raster("JPEG")
WEBP_BODY = _raster("WEBP")


async def _no_sleep(_: float) -> None:
    return None


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_attempts: int = 1,
    max_input_bytes: int = 10 * 1024 * 1024,
    max_response_bytes: int = 1024 * 1024,
) -> tuple[ZhipuImageTextRecognizer, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return (
        ZhipuImageTextRecognizer(
            client=client,
            base_url="https://open.bigmodel.invalid/api/paas/v4",
            api_key=SecretStr("local-contract-secret"),
            model="glm-ocr",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=max_attempts,
            max_input_bytes=max_input_bytes,
            max_response_bytes=max_response_bytes,
            sleep=_no_sleep,
        ),
        client,
    )


@pytest.mark.parametrize(
    ("max_input_bytes", "max_response_bytes", "message"),
    (
        (10 * 1024 * 1024 + 1, 1024 * 1024, "input limit"),
        (10 * 1024 * 1024, 1024 * 1024 + 1, "response limit"),
    ),
)
def test_image_ocr_adapter_rejects_limits_above_the_reviewed_envelope(
    max_input_bytes: int,
    max_response_bytes: int,
    message: str,
) -> None:
    client = httpx.AsyncClient()
    try:
        with pytest.raises(ValueError, match=message):
            ZhipuImageTextRecognizer(
                client=client,
                base_url="https://open.bigmodel.invalid/api/paas/v4",
                api_key=SecretStr("local-contract-secret"),
                model="glm-ocr",
                connect_timeout_seconds=1,
                read_timeout_seconds=2,
                total_timeout_seconds=3,
                concurrency=1,
                max_attempts=1,
                max_input_bytes=max_input_bytes,
                max_response_bytes=max_response_bytes,
            )
    finally:
        import asyncio

        asyncio.run(client.aclose())


def _request(
    image_bytes: bytes = PNG_BODY,
    *,
    media_type: str = "image/png",
    expected_text: tuple[str, ...] = EXPECTED_TEXT,
) -> ImageTextRecognitionRequest:
    return ImageTextRecognitionRequest(
        image_bytes=image_bytes,
        request_fingerprint="controlled-image-ocr-fingerprint",
        expected_text=expected_text,
        media_type=media_type,
        require_order=True,
    )


def _layout_element(
    index: object,
    content: object,
    *,
    bbox: object,
    label: object = "text",
    height: object = 1024,
    width: object = 1024,
    native_label: object = _NATIVE_LABEL_UNSET,
) -> dict[str, object]:
    element = {
        "index": index,
        "label": label,
        "bbox_2d": bbox,
        "content": content,
        "height": height,
        "width": width,
    }
    if native_label is not _NATIVE_LABEL_UNSET:
        element["native_label"] = native_label
    return element


def _response(
    *,
    model: object = "glm-ocr",
    layout_details: object | None = None,
    data_info: object | None = None,
) -> dict[str, object]:
    return {
        "id": "private-provider-request-id",
        "created": 1_727_156_815,
        "model": model,
        "layout_details": layout_details
        if layout_details is not None
        else [
            [
                _layout_element(3, EXPECTED_TEXT[2], bbox=[0.1, 0.7, 0.9, 0.8]),
                _layout_element(
                    4,
                    "https://private-provider.invalid/crops/private-image.png",
                    bbox=[0.2, 0.4, 0.8, 0.6],
                    label="image",
                ),
                _layout_element(1, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2]),
                _layout_element(2, EXPECTED_TEXT[1], bbox=[0.1, 0.4, 0.9, 0.5]),
            ]
        ],
        "data_info": data_info
        if data_info is not None
        else {"num_pages": 1, "pages": [{"width": 1024, "height": 1024}]},
        "md_results": "provider markdown must not be projected",
        "layout_visualization": [],
        "usage": {"prompt_tokens": 3, "completion_tokens": 3, "total_tokens": 6},
        "request_id": "private-provider-request-id",
    }


@pytest.mark.parametrize(
    ("image_bytes", "media_type", "expected_prefix"),
    (
        (PNG_BODY, "image/png", "data:image/png;base64,"),
        (JPEG_BODY, "image/jpeg", "data:image/jpeg;base64,"),
    ),
)
@pytest.mark.asyncio
async def test_image_layout_parsing_uses_private_bounded_raster_and_ordered_text(
    image_bytes: bytes,
    media_type: str,
    expected_prefix: str,
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=_response(model="GLM-OCR"))

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request(image_bytes, media_type=media_type))

    payload = captured["payload"]
    assert captured["url"] == "https://open.bigmodel.invalid/api/paas/v4/layout_parsing"
    assert captured["authorization"] == "Bearer local-contract-secret"
    assert isinstance(payload, dict)
    assert payload == {
        "model": "glm-ocr",
        "file": payload["file"],
        "return_crop_images": False,
        "need_layout_visualization": False,
    }
    encoded_file = payload["file"]
    assert isinstance(encoded_file, str)
    assert encoded_file.startswith(expected_prefix)
    assert base64.b64decode(encoded_file.split(",", 1)[1], validate=True) == image_bytes
    assert result.recognized_lines == EXPECTED_TEXT
    assert result.provider == "zhipu"
    assert result.model == "glm-ocr"
    assert result.request_fingerprint == "controlled-image-ocr-fingerprint"
    assert "local-contract-secret" not in repr(result)
    assert "private-provider-request-id" not in repr(result)
    assert "provider markdown" not in repr(result)
    assert "private-provider.invalid" not in repr(result)


@pytest.mark.parametrize("indices", ((0, 7, 19), (1, 8, 20)))
@pytest.mark.asyncio
async def test_image_ocr_accepts_zero_or_one_origin_noncontiguous_indices(
    indices: tuple[int, int, int],
) -> None:
    page = [
        _layout_element(indices[2], EXPECTED_TEXT[2], bbox=[0.1, 0.7, 0.9, 0.8]),
        _layout_element(indices[0], EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2]),
        _layout_element(indices[1], EXPECTED_TEXT[1], bbox=[0.1, 0.4, 0.9, 0.5]),
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request())

    assert result.recognized_lines == EXPECTED_TEXT


@pytest.mark.asyncio
async def test_image_ocr_accepts_official_maas_pixel_boxes_with_page_dimensions() -> None:
    page = [
        _layout_element(2, EXPECTED_TEXT[2], bbox=[102, 716, 922, 819]),
        _layout_element(0, EXPECTED_TEXT[0], bbox=[102, 102, 922, 205]),
        _layout_element(1, EXPECTED_TEXT[1], bbox=[102, 410, 922, 512]),
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request())

    assert result.recognized_lines == EXPECTED_TEXT


@pytest.mark.asyncio
async def test_image_ocr_accepts_official_full_page_pixel_box() -> None:
    # Pinned zai-org/GLM-OCR cef4d0e test fixture: a 2040x2640 page-sized
    # raw MaaS box normalizes to the SDK's [0, 0, 1000, 1000].
    page = [_layout_element(0, EXPECTED_TEXT[0], bbox=[0, 0, 2040, 2640])]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(
                layout_details=[page],
                data_info={"num_pages": 1, "pages": [{"width": 2040, "height": 2640}]},
            ),
        )

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert result.recognized_lines == (EXPECTED_TEXT[0],)


@pytest.mark.asyncio
async def test_image_ocr_uses_one_page_level_pixel_scale_for_small_pixel_boxes() -> None:
    page = [
        _layout_element(0, EXPECTED_TEXT[0], bbox=[0.1, 0.8, 0.9, 1.0]),
        _layout_element(1, EXPECTED_TEXT[1], bbox=[10, 50, 20, 60]),
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(
                layout_details=[page],
                data_info={"num_pages": 1, "pages": [{"width": 100, "height": 100}]},
            ),
        )

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request(expected_text=EXPECTED_TEXT[:2]))

    assert result.recognized_lines == EXPECTED_TEXT[:2]


@pytest.mark.asyncio
async def test_image_ocr_ignores_optional_image_fields_and_outer_extensions() -> None:
    sentinel = "private-extension-sentinel"
    image_element: dict[str, object] = {
        "index": 50,
        "label": "image",
        "bbox_2d": {"private": sentinel},
        "content": {"private": sentinel},
    }
    response = _response()
    layout = response["layout_details"]
    assert isinstance(layout, list) and isinstance(layout[0], list)
    layout[0].append(image_element)
    response["provider_extension"] = {"private": sentinel}
    data_info = response["data_info"]
    assert isinstance(data_info, dict)
    data_info["provider_extension"] = sentinel
    pages = data_info["pages"]
    assert isinstance(pages, list) and isinstance(pages[0], dict)
    pages[0]["provider_extension"] = sentinel

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request())

    assert result.recognized_lines == EXPECTED_TEXT
    assert sentinel not in repr(result)


@pytest.mark.asyncio
async def test_image_ocr_rejects_unknown_element_extension_without_exposing_it() -> None:
    sentinel = "private-element-extension-sentinel"
    page = [
        {
            **_layout_element(0, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2]),
            "provider_crop_path": sentinel,
        }
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("image_ocr_contract_element_extra",)
    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value)
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_image_ocr_accepts_bounded_native_label_metadata() -> None:
    page = [
        _layout_element(
            0,
            EXPECTED_TEXT[0],
            bbox=[0.1, 0.1, 0.9, 0.2],
            native_label="content",
        )
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert result.recognized_lines == (EXPECTED_TEXT[0],)


@pytest.mark.parametrize("native_label", ("header_image", "footer_image"))
@pytest.mark.asyncio
async def test_image_ocr_accepts_official_native_image_labels_without_projecting_content(
    native_label: str,
) -> None:
    sentinel = "private-native-image-content-sentinel"
    page = [
        _layout_element(
            0,
            EXPECTED_TEXT[0],
            bbox=[0.1, 0.1, 0.9, 0.2],
            native_label="content",
        ),
        _layout_element(
            1,
            sentinel,
            bbox=[0.1, 0.3, 0.9, 0.5],
            label="image",
            native_label=native_label,
        ),
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert result.recognized_lines == (EXPECTED_TEXT[0],)
    assert sentinel not in repr(result)


@pytest.mark.parametrize(
    ("native_label", "expected_issue"),
    (
        (None, "image_ocr_contract_native_label_type_invalid"),
        ("", "image_ocr_contract_native_label_type_invalid"),
        (7, "image_ocr_contract_native_label_type_invalid"),
        (
            {"private": "private-native-label-sentinel"},
            "image_ocr_contract_native_label_type_invalid",
        ),
        (
            "private-native-label-sentinel",
            "image_ocr_contract_native_label_unknown",
        ),
        ("x" * 65, "image_ocr_contract_native_label_limit_exceeded"),
        (
            "content\x00private-native-label-sentinel",
            "image_ocr_contract_native_label_limit_exceeded",
        ),
        (
            "content\tprivate-native-label-sentinel",
            "image_ocr_contract_native_label_limit_exceeded",
        ),
        ("table", "image_ocr_contract_native_label_conflict"),
        ("header_picture", "image_ocr_contract_native_label_unknown"),
        ("footer_picture", "image_ocr_contract_native_label_unknown"),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_rejects_invalid_native_label_without_exposing_it(
    native_label: object,
    expected_issue: str,
) -> None:
    sentinel = "private-native-label-sentinel"
    page = [
        _layout_element(
            0,
            EXPECTED_TEXT[0],
            bbox=[0.1, 0.1, 0.9, 0.2],
            native_label=native_label,
        )
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == (expected_issue,)
    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value)
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("retained_dimension", ("height", "width", "neither", "null"))
@pytest.mark.asyncio
async def test_image_ocr_accepts_independently_optional_element_dimensions(
    retained_dimension: str,
) -> None:
    page = [_layout_element(1, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2])]
    element = page[0]
    if retained_dimension == "height":
        element.pop("width")
    elif retained_dimension == "width":
        element.pop("height")
    elif retained_dimension == "neither":
        element.pop("height")
        element.pop("width")
    else:
        element["height"] = None
        element["width"] = None

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(layout_details=[page], data_info={"num_pages": 1}),
        )

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert result.recognized_lines == (EXPECTED_TEXT[0],)


@pytest.mark.asyncio
async def test_image_ocr_uses_independent_element_dimensions_for_pixel_scale() -> None:
    page = [
        _layout_element(0, EXPECTED_TEXT[0], bbox=[100, 100, 900, 200]),
        _layout_element(1, EXPECTED_TEXT[1], bbox=[100, 400, 900, 500]),
        _layout_element(2, EXPECTED_TEXT[2], bbox=[100, 700, 900, 800]),
    ]
    page[0].pop("height")
    page[1].pop("width")
    page[2].pop("height")
    page[2].pop("width")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(layout_details=[page], data_info={"num_pages": 1}),
        )

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request())

    assert result.recognized_lines == EXPECTED_TEXT


@pytest.mark.asyncio
async def test_image_ocr_prefers_page_dimensions_over_vendor_element_metadata() -> None:
    page = [
        _layout_element(
            0,
            EXPECTED_TEXT[0],
            bbox=[100, 100, 900, 200],
            height=800,
            width=900,
        )
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(
                layout_details=[page],
                data_info={"num_pages": 1, "pages": [{"width": 1024, "height": 1024}]},
            ),
        )

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert result.recognized_lines == (EXPECTED_TEXT[0],)


@pytest.mark.parametrize("index", (True, "0", -1, 1_000_001))
@pytest.mark.asyncio
async def test_image_ocr_rejects_invalid_indices_with_granular_code(index: object) -> None:
    page = [_layout_element(index, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2])]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("image_ocr_contract_index_invalid",)


@pytest.mark.asyncio
async def test_image_ocr_rejects_duplicate_index_with_granular_code() -> None:
    page = [
        _layout_element(0, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2]),
        _layout_element(0, EXPECTED_TEXT[1], bbox=[0.1, 0.4, 0.9, 0.5]),
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=EXPECTED_TEXT[:2]))

    assert raised.value.issue_codes == ("image_ocr_contract_index_duplicate",)


@pytest.mark.parametrize("label", ("unknown", "Text", " text ", 7))
@pytest.mark.asyncio
async def test_image_ocr_rejects_unknown_raw_labels(label: object) -> None:
    page = [_layout_element(0, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2], label=label)]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("image_ocr_contract_label_unknown",)


@pytest.mark.parametrize(
    ("label", "issue_code"),
    (
        ("formula", "image_ocr_contract_formula_unsupported"),
        ("table", "image_ocr_contract_table_unsupported"),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_rejects_unsupported_structured_layout(
    label: str,
    issue_code: str,
) -> None:
    sentinel = "private unsupported provider content"
    page = [_layout_element(1, sentinel, bbox=None, label=label)]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == (issue_code,)
    assert sentinel not in str(raised.value)


@pytest.mark.parametrize(
    "bbox",
    (
        None,
        [0.1, 0.2, 0.9],
        [0.1, True, 0.9, 0.2],
        [-0.1, 0.1, 0.9, 0.2],
        [0.9, 0.1, 0.1, 0.2],
        "0,0,1,1",
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_rejects_malformed_text_bbox(bbox: object) -> None:
    page = [_layout_element(0, EXPECTED_TEXT[0], bbox=bbox)]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("image_ocr_contract_bbox_shape",)


@pytest.mark.asyncio
async def test_image_ocr_rejects_unbound_pixel_bbox_scale() -> None:
    element = _layout_element(0, EXPECTED_TEXT[0], bbox=[10, 10, 90, 20])
    element.pop("height")
    element.pop("width")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(layout_details=[[element]], data_info={"num_pages": 1}),
        )

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("image_ocr_contract_bbox_scale",)


@pytest.mark.asyncio
async def test_image_ocr_rejects_pixel_bbox_outside_page_range() -> None:
    page = [_layout_element(0, EXPECTED_TEXT[0], bbox=[10, 10, 1025, 20])]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("image_ocr_contract_bbox_range",)


@pytest.mark.parametrize("dimension", (0, 100_001, "1024", True, 2.5))
@pytest.mark.asyncio
async def test_image_ocr_rejects_invalid_optional_dimensions(dimension: object) -> None:
    page = [
        _layout_element(
            0,
            EXPECTED_TEXT[0],
            bbox=[0.1, 0.1, 0.9, 0.2],
            width=dimension,
        )
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("image_ocr_contract_page_dimensions",)


@pytest.mark.parametrize(
    "page_info",
    (
        {"width": 1024},
        {"height": 1024},
        {"width": 0, "height": 1024},
        {"width": 1024, "height": "1024"},
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_rejects_invalid_page_dimensions(page_info: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(data_info={"num_pages": 1, "pages": [page_info]}),
        )

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())

    assert raised.value.issue_codes == ("image_ocr_contract_page_dimensions",)


@pytest.mark.asyncio
async def test_image_ocr_rejects_conflicting_dimension_fallback_for_pixel_scale() -> None:
    page = [
        _layout_element(0, EXPECTED_TEXT[0], bbox=[10, 10, 90, 20], width=100),
        _layout_element(1, EXPECTED_TEXT[1], bbox=[10, 40, 90, 50], width=200),
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(layout_details=[page], data_info={"num_pages": 1}),
        )

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=EXPECTED_TEXT[:2]))

    assert raised.value.issue_codes == ("image_ocr_contract_page_dimensions_conflict",)


@pytest.mark.parametrize(
    ("content", "issue_code"),
    (
        (7, "image_ocr_contract_content_type"),
        ("bad\x00text", "image_ocr_contract_content_limit"),
        ("x" * 1_601, "image_ocr_contract_content_limit"),
        ("\n".join(f"line-{number}" for number in range(9)), "image_ocr_contract_line_limit"),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_rejects_malformed_text_content_without_exposing_it(
    content: object,
    issue_code: str,
) -> None:
    page = [_layout_element(0, content, bbox=[0.1, 0.1, 0.9, 0.9])]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[page]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == (issue_code,)
    assert str(content) not in str(raised.value)


@pytest.mark.parametrize("content_field", ("missing", "null"))
@pytest.mark.asyncio
async def test_image_ocr_routes_optional_empty_text_content_to_exact_gate(
    content_field: str,
) -> None:
    element = _layout_element(0, None, bbox=[0.1, 0.1, 0.9, 0.2])
    if content_field == "missing":
        element.pop("content")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[[element]]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("missing_visual_text",)


@pytest.mark.asyncio
async def test_image_ocr_rejects_flat_legacy_layout_shape() -> None:
    flat_layout = [_layout_element(1, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2])]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=flat_layout))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("image_ocr_contract_schema_invalid",)


@pytest.mark.parametrize(
    "data_info",
    (
        {},
        {"num_pages": 0},
        {"num_pages": 2},
        {"num_pages": True},
        {"num_pages": "1"},
        {"num_pages": 1, "pages": None},
        {"num_pages": 1, "pages": []},
        {
            "num_pages": 1,
            "pages": [
                {"width": 1024, "height": 1024},
                {"width": 1024, "height": 1024},
            ],
        },
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_requires_exactly_one_typed_page(data_info: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(data_info=data_info))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())

    assert raised.value.issue_codes == ("image_ocr_contract_page_count",)


@pytest.mark.parametrize("page_count", (0, 2, True, "1"))
@pytest.mark.asyncio
async def test_image_ocr_rejects_conflicting_page_count_extension(page_count: object) -> None:
    data_info = {
        "num_pages": 1,
        "page_count": page_count,
        "pages": [{"width": 1024, "height": 1024}],
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(data_info=data_info))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())

    assert raised.value.issue_codes == ("image_ocr_contract_page_count",)


@pytest.mark.asyncio
async def test_image_ocr_accepts_matching_page_count_extension() -> None:
    data_info = {
        "num_pages": 1,
        "page_count": 1,
        "pages": [{"width": 1024, "height": 1024}],
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(data_info=data_info))

    adapter, client = _adapter(handler)
    async with client:
        result = await adapter.recognize(_request())

    assert result.recognized_lines == EXPECTED_TEXT


@pytest.mark.asyncio
async def test_image_ocr_rejects_multiple_nested_layout_pages() -> None:
    page = [_layout_element(1, EXPECTED_TEXT[0], bbox=[0.1, 0.1, 0.9, 0.2])]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response(
                layout_details=[page, page],
                data_info={"num_pages": 2},
            ),
        )

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request(expected_text=(EXPECTED_TEXT[0],)))

    assert raised.value.issue_codes == ("image_ocr_contract_page_count",)


@pytest.mark.parametrize(
    ("extra_field", "expected_issue"),
    (
        ("json_result", "image_ocr_contract_source_conflict"),
        ("error", "image_ocr_contract_source_conflict"),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_rejects_conflicting_response_sources_without_exposing_values(
    extra_field: str,
    expected_issue: str,
) -> None:
    sentinel = "private-conflicting-envelope-sentinel"
    response = _response()
    response[extra_field] = {"private": sentinel}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())

    assert raised.value.issue_codes == (expected_issue,)
    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value)


@pytest.mark.parametrize("extra_field", ("json_result", "error"))
@pytest.mark.asyncio
async def test_image_ocr_rejects_non_raw_response_source(extra_field: str) -> None:
    sentinel = "private-source-sentinel"
    response = {extra_field: {"private": sentinel}}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())

    assert raised.value.issue_codes == ("image_ocr_contract_source_invalid",)
    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value)


@pytest.mark.parametrize(
    ("lines", "expected_issue"),
    (
        ((), "missing_visual_text"),
        ((EXPECTED_TEXT[0], EXPECTED_TEXT[2]), "missing_visual_text"),
        ((*EXPECTED_TEXT, "额外文字"), "unexpected_visual_text"),
        (tuple(reversed(EXPECTED_TEXT)), "misordered_visual_text"),
        (
            (EXPECTED_TEXT[0], EXPECTED_TEXT[1], EXPECTED_TEXT[1], EXPECTED_TEXT[2]),
            "duplicate_visual_text",
        ),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_preserves_existing_exact_text_gate(
    lines: tuple[str, ...],
    expected_issue: str,
) -> None:
    layout = [
        _layout_element(
            index,
            line,
            bbox=[0.1, index / 10, 0.9, index / 10 + 0.05],
        )
        for index, line in enumerate(lines, start=1)
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(layout_details=[layout]))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())

    assert expected_issue in raised.value.issue_codes


@pytest.mark.asyncio
async def test_image_ocr_rejects_wrong_model_identity() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response(model="glm-5.2"))

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(ProviderIdentityMismatchError):
            await adapter.recognize(_request())


@pytest.mark.parametrize(
    ("body", "expected_issues"),
    (
        (b"not-json", ("image_ocr_response_envelope_invalid",)),
        (b"[]", ("image_ocr_contract_schema_invalid",)),
        (
            b'{"model":"glm-ocr"}',
            (
                "image_ocr_contract_schema_invalid",
                "image_ocr_contract_page_count",
            ),
        ),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_rejects_malformed_response_envelopes(
    body: bytes,
    expected_issues: tuple[str, ...],
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())
    assert raised.value.issue_codes == expected_issues
    assert body.decode("utf-8") not in str(raised.value)


@pytest.mark.parametrize(
    ("image_bytes", "media_type", "max_input_bytes"),
    (
        (WEBP_BODY, "image/webp", 10 * 1024 * 1024),
        (b"not-a-raster", "image/png", 10 * 1024 * 1024),
        (PNG_BODY, "image/png", len(PNG_BODY) - 1),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_rejects_unsupported_malformed_or_oversized_input_before_http(
    image_bytes: bytes,
    media_type: str,
    max_input_bytes: int,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _adapter(handler, max_input_bytes=max_input_bytes)
    async with client:
        with pytest.raises(ProviderInputLimitError):
            await adapter.recognize(_request(image_bytes, media_type=media_type))
    assert calls == 0


def test_image_ocr_request_rejects_empty_and_non_image_media_before_http() -> None:
    with pytest.raises(ValueError):
        _request(b"")
    with pytest.raises(ValueError):
        _request(b"%PDF-1.7", media_type="application/pdf")


@pytest.mark.asyncio
async def test_image_ocr_response_limit_is_terminal_and_body_free() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": "2048"},
            content=b'{"private":"provider body"}',
        )

    adapter, client = _adapter(handler, max_response_bytes=1024)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(_request())
    assert raised.value.issue_codes == ("output_limit_exceeded",)
    assert "provider body" not in str(raised.value)


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    (
        (400, ProviderRejectedError),
        (422, ProviderRejectedError),
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailableError),
    ),
)
@pytest.mark.asyncio
async def test_image_ocr_http_failures_are_typed_and_body_free(
    status_code: int,
    error_type: type[Exception],
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"message": "private provider body"}})

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(error_type) as raised:
            await adapter.recognize(_request())
    assert "private provider body" not in str(raised.value)


@pytest.mark.asyncio
async def test_image_ocr_timeout_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout detail", request=request)

    adapter, client = _adapter(handler)
    async with client:
        with pytest.raises(ProviderTimeoutError) as raised:
            await adapter.recognize(_request())
    assert "private timeout detail" not in str(raised.value)
