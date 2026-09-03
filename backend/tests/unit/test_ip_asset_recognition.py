from __future__ import annotations

import asyncio
import io
import json
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from app.api.v1.routes import ip_assets as routes
from app.application.services.ip_asset_recognition import IpAssetRecognitionService
from app.core.config import Settings
from app.core.errors import AppError, InvalidProviderOutputError, ProviderTimeoutError
from app.domain.ip_asset_metadata_repair import IP_ASSET_METADATA_REPAIR_MODEL
from app.domain.ip_asset_recognition import (
    IpAssetRecognitionRequest,
    IpAssetRecognitionSuggestion,
    normalize_ip_asset_recognition_request,
)
from app.domain.ip_assets import (
    IpAssetCharacter,
    IpAssetType,
    validate_ip_asset_upload,
)
from app.infrastructure.ai.ip_asset_recognition import ZhipuIpAssetRecognitionAdapter
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr, ValidationError

_MODEL = "glm-4.1v-thinking-flash"


def _raster(media_type: str = "image/png", size: tuple[int, int] = (96, 72)) -> bytes:
    output = io.BytesIO()
    mode = "RGBA" if media_type == "image/png" else "RGB"
    color = (32, 150, 132, 180) if mode == "RGBA" else (32, 150, 132)
    image = Image.new(mode, size, color)
    image.save(
        output,
        format={"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[media_type],
    )
    return output.getvalue()


def _adapter(client: httpx.AsyncClient, *, model: str = _MODEL) -> ZhipuIpAssetRecognitionAdapter:
    return ZhipuIpAssetRecognitionAdapter(
        client=client,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key=SecretStr("test-secret"),
        model=model,
        connect_timeout_seconds=1,
        total_timeout_seconds=5,
        concurrency=1,
        max_request_bytes=16 * 1024 * 1024,
        max_response_bytes=1024 * 1024,
        sleep=lambda _delay: asyncio.sleep(0),
    )


def _request() -> IpAssetRecognitionRequest:
    validated = validate_ip_asset_upload(
        filename="private-source.png",
        declared_media_type="image/png",
        body=_raster(),
    )
    return normalize_ip_asset_recognition_request(validated)


def test_recognition_normalization_strips_source_representation_and_bounds_pixels() -> None:
    validated = validate_ip_asset_upload(
        filename="department/private-source.jpg",
        declared_media_type="image/jpeg",
        body=_raster("image/jpeg", (2_000, 1_000)),
    )

    request = normalize_ip_asset_recognition_request(validated)

    assert request.media_type == "image/jpeg"
    assert request.width == 1_568
    assert request.height == 784
    assert len(request.image_bytes) < 8 * 1024 * 1024
    assert not hasattr(request, "filename")
    with Image.open(io.BytesIO(request.image_bytes)) as normalized:
        assert normalized.getexif() == {}


@pytest.mark.asyncio
async def test_zhipu_recognition_discards_reasoning_extra_fields_and_unsafe_values() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-secret"
        content = "<think>raw-private-reasoning</think> ignored wrapper " + json.dumps(
            {
                "character": "xiao_sai",
                "asset_type": "meme_sticker",
                "emotion": "开心",
                "action": "挥手",
                "scene": "x" * 80,
                "intended_use": "社群推送",
                "style": "3D",
                "tags": ["开心", "bad/path", "社群", "开心"],
                "department": "must-not-leak",
                "provider_request_id": "private-request-id",
            },
            ensure_ascii=False,
        )
        return httpx.Response(
            200,
            json={
                "id": "private-provider-id",
                "model": _MODEL,
                "choices": [{"message": {"content": content}}],
            },
            headers={"x-request-id": "private-header-id"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _adapter(client).suggest(_request())

    assert result.character is IpAssetCharacter.XIAO_SAI
    assert result.asset_type is IpAssetType.MEME_STICKER
    assert result.scene == ""
    assert result.tags == ("开心", "社群")
    serialized = repr(result)
    assert "raw-private-reasoning" not in serialized
    assert "private-provider-id" not in serialized
    assert "must-not-leak" not in serialized
    assert captured["thinking"] == {"type": "disabled"}
    assert captured["do_sample"] is False
    assert "response_format" not in captured
    assert "temperature" not in captured
    messages = cast(list[dict[str, object]], captured["messages"])
    user_content = cast(list[dict[str, object]], messages[1]["content"])
    image_url = cast(dict[str, str], user_content[1]["image_url"])["url"]
    assert image_url.startswith("data:image/")


@pytest.mark.asyncio
async def test_glm5_repair_request_uses_exact_visual_contract_without_json_mode() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": IP_ASSET_METADATA_REPAIR_MODEL,
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "character": "xiao_sai",
                                    "asset_type": "portrait_avatar",
                                }
                            )
                        }
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _adapter(client, model=IP_ASSET_METADATA_REPAIR_MODEL).suggest(_request())

    assert IP_ASSET_METADATA_REPAIR_MODEL == "glm-5v-turbo"
    assert result.model == IP_ASSET_METADATA_REPAIR_MODEL
    assert captured["model"] == IP_ASSET_METADATA_REPAIR_MODEL
    assert captured["thinking"] == {"type": "disabled"}
    assert captured["do_sample"] is False
    assert "response_format" not in captured
    messages = cast(list[dict[str, object]], captured["messages"])
    user_content = cast(list[dict[str, object]], messages[1]["content"])
    assert user_content[1]["type"] == "image_url"


@pytest.mark.asyncio
async def test_zhipu_recognition_rejects_unknown_required_taxonomy_and_timeout() -> None:
    def invalid_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": _MODEL,
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"character": "unknown", "asset_type": "meme_sticker"}
                            )
                        }
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(invalid_handler)) as client:
        with pytest.raises(InvalidProviderOutputError):
            await _adapter(client).suggest(_request())

    def ambiguous_handler(_request: httpx.Request) -> httpx.Response:
        first = json.dumps({"character": "xiao_sai", "asset_type": "meme_sticker"})
        second = json.dumps({"character": "duo", "asset_type": "scene_illustration"})
        return httpx.Response(
            200,
            json={
                "model": _MODEL,
                "choices": [{"message": {"content": f"{first} {second}"}}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(ambiguous_handler)) as client:
        with pytest.raises(InvalidProviderOutputError):
            await _adapter(client).suggest(_request())

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret provider timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler)) as client:
        with pytest.raises(ProviderTimeoutError):
            await _adapter(client).suggest(_request())


class _FakeRecognitionModel:
    def __init__(self) -> None:
        self.requests: list[IpAssetRecognitionRequest] = []

    async def suggest(self, request: IpAssetRecognitionRequest) -> IpAssetRecognitionSuggestion:
        self.requests.append(request)
        return IpAssetRecognitionSuggestion(
            character=IpAssetCharacter.XIAO_SAI,
            asset_type=IpAssetType.MEME_STICKER,
            emotion="开心",
            action="挥手",
            scene="科学课堂",
            intended_use="社群推送",
            style="3D",
            tags=("开心", "社群"),
            provider="zhipu",
            model=_MODEL,
        )


def _recognition_app(model: _FakeRecognitionModel) -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(routes.router, prefix="/api/v1")
    test_app.state.settings = SimpleNamespace(
        ip_asset_hub_enabled=True,
        ip_asset_generation_enabled=False,
        ip_asset_recognition_enabled=True,
        visual_semantic_enabled=False,
    )
    test_app.state.ip_asset_service = None
    test_app.state.image_generator = None
    test_app.state.ip_asset_recognition_service = IpAssetRecognitionService(model)
    test_app.state.ip_asset_upload_semaphore = asyncio.Semaphore(1)

    @test_app.exception_handler(AppError)
    async def handle_app_error(_request: Request, error: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    return test_app


def test_transient_recognition_endpoint_projects_only_safe_suggestions() -> None:
    model = _FakeRecognitionModel()
    client = TestClient(_recognition_app(model))

    response = client.post(
        "/api/v1/ip-assets/recognitions",
        files={"file": ("local.png", _raster(), "image/png")},
    )

    assert response.status_code == 200
    assert len(model.requests) == 1
    assert response.json() == {
        "status": "suggested",
        "character": "xiao_sai",
        "asset_type": "meme_sticker",
        "emotion": "开心",
        "action": "挥手",
        "scene": "科学课堂",
        "intended_use": "社群推送",
        "style": "3D",
        "tags": ["开心", "社群"],
        "provider": "zhipu",
        "model": _MODEL,
    }
    serialized = response.text
    for forbidden in (
        "image_bytes",
        "private-source",
        "provider_request_id",
        "request_fingerprint",
        "object_key",
        "department",
        "contributor",
    ):
        assert forbidden not in serialized

    malformed = client.post(
        "/api/v1/ip-assets/recognitions",
        files={"file": ("bad.png", b"not-an-image", "image/png")},
    )
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_raster_signature"
    assert len(model.requests) == 1

    oversized = client.post(
        "/api/v1/ip-assets/recognitions",
        files={"file": ("large.png", b"x" * (25 * 1024 * 1024 + 1), "image/png")},
    )
    assert oversized.status_code == 422
    assert oversized.json()["error"]["code"] == "image_too_large"
    assert len(model.requests) == 1


def test_disabled_recognition_is_typed_and_provider_free() -> None:
    model = _FakeRecognitionModel()
    test_app = _recognition_app(model)
    test_app.state.settings.ip_asset_recognition_enabled = False
    client = TestClient(test_app)

    response = client.post(
        "/api/v1/ip-assets/recognitions",
        files={"file": ("local.png", _raster(), "image/png")},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ip_asset_recognition_unavailable"
    assert model.requests == []


def test_recognition_configuration_is_safe_off_and_fail_closed() -> None:
    assert Settings(_env_file=None).ip_asset_recognition_enabled is False
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ip_asset_recognition_enabled=True)
    enabled = Settings(
        _env_file=None,
        ip_asset_hub_enabled=True,
        ip_asset_recognition_enabled=True,
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://open.bigmodel.cn/api/paas/v4",
        ai_platform_api_key=SecretStr("local-test-key"),
    )
    assert enabled.ip_asset_recognition_model == _MODEL
