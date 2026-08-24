from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import app.official_account_visual_live_acceptance as live_acceptance
import pytest
from app.application.ports.image_generation import ImageGenerationRequest
from app.application.ports.official_account_local import OfficialAccountSourceMedia
from app.application.services.official_account_visual_generation import (
    generated_visual_alt_text,
    plan_generated_body_visual,
)
from app.core.config import Settings
from app.core.errors import ImageProviderTimeoutError
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V2_VERSION,
)
from app.official_account_visual_live_acceptance import (
    _article,
    _preflight,
    _render,
    _select_reference,
    _validate_publication,
    _write_intent,
    _write_success_bundle,
)
from PIL import Image
from pydantic import SecretStr


def _candidate(index: int, *, semantic: bool = False) -> OfficialAccountSourceMedia:
    asset_ref = f"{index:016x}"
    checksum = sha256(asset_ref.encode()).hexdigest()
    return OfficialAccountSourceMedia(
        source_image_artifact_id=None,
        fixture_id=f"catalog:{asset_ref}",
        media_type="image/jpeg",
        byte_size=1024,
        sha256=checksum,
        semantic_label=f"approved-{index}",
        candidate_id=asset_ref,
        semantic_tags=("observe",) if semantic else ("neutral",),
        publication_priority=index,
        catalog_asset_id=checksum,
        catalog_asset_ref=asset_ref,
        catalog_version="catalog-v1",
        source_master_sha256=checksum,
    )


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        image_provider_mode="comfly",
        comfly_base_url="https://provider.test",
        comfly_api_key=SecretStr("test-only-secret"),
        image_model="gpt-image-2",
        image_max_attempts=1,
        official_account_local_generated_visual_plan_version=(
            OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION
        ),
        official_account_local_generated_visual_prompt_version=(
            OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V2_VERSION
        ),
    )


def _plan_fixture() -> tuple[
    OfficialAccountSourceMedia,
    Any,
    Any,
    ImageGenerationRequest,
]:
    reference = _select_reference(
        tuple(_candidate(index, semantic=index == 17) for index in range(41))
    )
    reference_bytes = BytesIO()
    Image.new("RGB", (640, 640), (32, 80, 110)).save(
        reference_bytes,
        format="JPEG",
        quality=82,
        exif=b"",
    )
    body = reference_bytes.getvalue()
    reference = replace(reference, byte_size=len(body), sha256=sha256(body).hexdigest())
    article = _article()
    render = _render(article)
    plan = plan_generated_body_visual(
        run_id=render.id,
        article=article,
        render=render,
        ordinal=0,
        reference=reference,
        provider="comfly",
        model="gpt-image-2",
        reference_bytes=body,
    )
    request = ImageGenerationRequest(
        run_id=plan.run_id,
        draft_version_id=article.id,
        prompt="transient prompt must never be written",
        request_fingerprint=plan.request_fingerprint,
    )
    return reference, article, plan, request


def test_live_acceptance_uses_one_semantic_approved_reference_and_v2_anchor() -> None:
    candidates = tuple(_candidate(index, semantic=index == 17) for index in range(41))
    reference = _select_reference(candidates)
    article = _article()
    reference_bytes = BytesIO()
    Image.new("RGB", (640, 640), (32, 80, 110)).save(
        reference_bytes,
        format="JPEG",
        quality=82,
        exif=b"",
    )
    body = reference_bytes.getvalue()
    reference = replace(
        reference,
        byte_size=len(body),
        sha256=sha256(body).hexdigest(),
    )
    plan = plan_generated_body_visual(
        run_id=_render(article).id,
        article=article,
        render=_render(article),
        ordinal=0,
        reference=reference,
        provider="comfly",
        model="gpt-image-2",
        reference_bytes=body,
    )

    assert reference.catalog_asset_ref == f"{17:016x}"
    assert plan.block_index == 0
    assert plan.block_kind == "paragraph"
    assert plan.reference_input_version == "image-reference-input-v2-png-preserve-jpeg-normalize"
    assert generated_visual_alt_text(article=article, plan=plan).endswith("核心场景插画")


def test_live_acceptance_publication_validation_and_one_shot_intent(tmp_path: Path) -> None:
    encoded = BytesIO()
    Image.new("RGB", (1536, 1024), (28, 64, 92)).save(
        encoded,
        format="JPEG",
        quality=86,
        optimize=False,
        progressive=False,
        exif=b"",
    )
    body = encoded.getvalue()

    assert _validate_publication(body) == {
        "media_type": "image/jpeg",
        "width": 1536,
        "height": 1024,
        "aspect_ratio": "3:2",
        "byte_size": len(body),
        "sha256": sha256(body).hexdigest(),
        "exif_present": False,
        "icc_profile_present": False,
    }

    output_dir = tmp_path / "one-call"
    _write_intent(output_dir, request_fingerprint="a" * 64)
    intent = json.loads((output_dir / ".paid-call-intent.json").read_text(encoding="utf-8"))
    assert intent["paid_generation_call_limit"] == 1
    assert intent["paid_generation_calls_attempted"] == 1
    with pytest.raises(FileExistsError):
        _write_intent(output_dir, request_fingerprint="a" * 64)


def test_live_acceptance_rejects_wrong_publication_shape() -> None:
    encoded = BytesIO()
    Image.new("RGB", (1024, 1024), (28, 64, 92)).save(encoded, format="JPEG")

    with pytest.raises(ValueError, match="output profile mismatch"):
        _validate_publication(encoded.getvalue())


def test_live_acceptance_preflight_requires_comfly_one_attempt_and_current_versions(
    tmp_path: Path,
) -> None:
    settings = _settings()
    output_dir = tmp_path / "acceptance"

    _preflight(settings, output_dir)
    with pytest.raises(ValueError, match="Comfly provider"):
        _preflight(settings.model_copy(update={"image_provider_mode": "fake"}), output_dir)
    with pytest.raises(ValueError, match="exactly one provider attempt"):
        _preflight(settings.model_copy(update={"image_max_attempts": 2}), output_dir)
    with pytest.raises(ValueError, match="current official-account visual bundle"):
        _preflight(
            settings.model_copy(
                update={"official_account_local_generated_visual_plan_version": "stale-plan"}
            ),
            output_dir,
        )
    with pytest.raises(ValueError, match="current official-account visual bundle"):
        _preflight(
            settings.model_copy(
                update={"official_account_local_generated_visual_prompt_version": "stale-prompt"}
            ),
            output_dir,
        )
    with pytest.raises(ValueError, match="server-side Comfly key"):
        _preflight(settings.model_copy(update={"comfly_api_key": None}), output_dir)

    output_dir.mkdir()
    with pytest.raises(FileExistsError, match="refusing to reuse"):
        _preflight(settings, output_dir)


def test_live_acceptance_bundle_is_sanitized_and_validated_before_write(
    tmp_path: Path,
) -> None:
    settings = _settings()
    reference, article, plan, _request = _plan_fixture()
    encoded = BytesIO()
    Image.new("RGB", (1536, 1024), (28, 64, 92)).save(
        encoded,
        format="JPEG",
        quality=86,
        optimize=False,
        progressive=False,
        exif=b"",
    )
    output_dir = tmp_path / "bundle"
    _write_intent(output_dir, request_fingerprint=plan.request_fingerprint)
    _write_success_bundle(
        output_dir,
        settings=settings,
        reference=reference,
        plan=plan,
        prompt_sha256=sha256(b"transient prompt must never be written").hexdigest(),
        alt_text=generated_visual_alt_text(article=article, plan=plan),
        body=encoded.getvalue(),
    )

    report = json.loads((output_dir / "acceptance.json").read_text(encoding="utf-8"))
    assert report["request_identity_validated"] is True
    assert report["paid_generation_calls_attempted"] == 1
    assert report["paid_generation_calls_succeeded"] == 1
    assert report["reference_source_media_type"] == "image/jpeg"
    assert report["reference_input_media_type"] == "image/png"
    assert report["boundaries"] == {
        "article_provider_calls": 0,
        "embedding_provider_calls": 0,
        "wechat_calls": 0,
        "wecom_calls": 0,
        "publish_calls": 0,
        "local_only": True,
    }
    serialized = "\n".join(
        (output_dir / name).read_text(encoding="utf-8")
        for name in (".paid-call-intent.json", "acceptance.json", "preview.html", "README.md")
    )
    assert "test-only-secret" not in serialized
    assert "https://provider.test" not in serialized
    assert "transient prompt must never be written" not in serialized
    assert "private/" not in serialized
    assert '"prompt"' not in serialized

    invalid_dir = tmp_path / "invalid"
    invalid_dir.mkdir()
    invalid = BytesIO()
    Image.new("RGB", (1024, 1024), (28, 64, 92)).save(invalid, format="JPEG")
    with pytest.raises(ValueError, match="output profile mismatch"):
        _write_success_bundle(
            invalid_dir,
            settings=settings,
            reference=reference,
            plan=plan,
            prompt_sha256="a" * 64,
            alt_text="safe alt",
            body=invalid.getvalue(),
        )
    assert not (invalid_dir / "body-0.jpg").exists()


@pytest.mark.asyncio
async def test_live_acceptance_timeout_is_result_unknown_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    reference, article, plan, request = _plan_fixture()

    class NoNetworkClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> NoNetworkClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class TimeoutGenerator:
        calls = 0

        async def generate(self, _request: ImageGenerationRequest) -> Any:
            self.calls += 1
            raise ImageProviderTimeoutError()

    generator = TimeoutGenerator()

    async def prepare(_settings_value: Settings) -> tuple[Any, Any, Any, str, Any]:
        return reference, article, plan, request.prompt, request

    monkeypatch.setattr(live_acceptance, "get_settings", lambda: settings)
    monkeypatch.setattr(live_acceptance, "_prepare_acceptance", prepare)
    monkeypatch.setattr(live_acceptance.httpx, "AsyncClient", NoNetworkClient)
    monkeypatch.setattr(
        live_acceptance,
        "create_image_generator",
        lambda _settings_value, client: generator,
    )

    output_dir = tmp_path / "timeout"
    assert await live_acceptance.run(output_dir) is False
    assert generator.calls == 1
    report = json.loads((output_dir / "acceptance.json").read_text(encoding="utf-8"))
    assert report["status"] == "result_unknown"
    assert report["paid_generation_calls_attempted"] == 1
    assert report["paid_generation_calls_succeeded"] == 0
    assert report["automatic_retry_permitted"] is False
    assert report["safe_error_code"] == "image_provider_timeout"
