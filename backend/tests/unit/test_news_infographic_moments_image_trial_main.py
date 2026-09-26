"""Fake-provider gates for one automatic same-package Moments-rich local image."""

from __future__ import annotations

import asyncio
import json
import sys
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import app.news_infographic_moments_copy_trial_main as copy_trial
import pytest
from app import news_infographic_moments_image_trial_main as image_trial
from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageReference,
)
from app.application.services.news_infographic_footer import render_exact_source_footer
from app.application.services.news_infographic_rich_copy import (
    RichCopyError,
    build_moments_rich_draft_plan,
)
from app.infrastructure.ai.news_infographic import LOCAL_INFOGRAPHIC_IMAGE_MODEL
from app.news_infographic_moments_copy_trial_main import execute_trial, preflight_trial
from PIL import Image
from test_news_infographic_moments_copy_trial_main import (
    FakeChatModel,
    _accepted_audit,
    _draft,
    _frozen_files,
)


class FakeImageModel:
    image_model = LOCAL_INFOGRAPHIC_IMAGE_MODEL

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.calls: list[ImageGenerationRequest] = []
        self.failure = failure

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        self.calls.append(request)
        if self.failure is not None:
            raise self.failure
        stream = BytesIO()
        Image.new("RGB", (1152, 2048), "white").save(stream, format="PNG")
        return ImageGenerationResult(
            provider="comfly",
            model=self.image_model,
            request_fingerprint=request.request_fingerprint,
            provider_task_id="fake-only",
            provider_upload_id=None,
            image_bytes=stream.getvalue(),
            media_type="image/png",
            width=1152,
            height=2048,
            attempts=1,
        )


def _references() -> tuple[ImageReference, ...]:
    return tuple(
        ImageReference(
            role=role,
            asset_id=role,
            filename=f"{role}.png",
            sha256=sha256(data).hexdigest(),
            image_bytes=data,
        )
        for role, data in (
            ("approved-characters", b"fake-character-reference"),
            ("approved-style", b"fake-style-reference"),
        )
    )


def _preflight(tmp_path: Path) -> Any:
    paths = _frozen_files(tmp_path)
    return preflight_trial(input_bundle=paths[0], package_detail=paths[1], copy_run_detail=paths[2])


def test_default_cli_preflight_has_no_provider_or_image_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _frozen_files(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "moments-image-trial",
            "--input-bundle",
            str(paths[0]),
            "--package-detail",
            str(paths[1]),
            "--copy-run-detail",
            str(paths[2]),
            "--output-dir",
            str(tmp_path / "preview"),
        ],
    )
    monkeypatch.setattr(image_trial, "get_settings", lambda: pytest.fail("provider loaded"))
    assert asyncio.run(image_trial._main()) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["model_calls"] == result["image_intents"] == 0
    assert not (tmp_path / "preview").exists()


def test_invalid_draft_and_rejected_audit_never_reserve_image(
    tmp_path: Path,
) -> None:
    preflight = _preflight(tmp_path)
    plan = build_moments_rich_draft_plan(preflight.case, preflight.binding, preflight.seed)
    bad = _draft(preflight).model_dump(mode="json")
    bad["news"] = str(bad["news"]).ljust(plan.news_editorial_max_chars + 1, "字")
    image = FakeImageModel()
    result = asyncio.run(
        image_trial.run_moments_image_trial(
            preflight,
            output_dir=tmp_path / "invalid",
            chat=FakeChatModel(bad),
            image=image,
            references=_references(),
            copy_ledger_dir=tmp_path / "copy-ledger-1",
            image_ledger_dir=tmp_path / "image-ledger",
        )
    )
    assert result["copy_status"] == "generation_copy_rejected"
    assert result["image_intents"] == 0
    assert not image.calls
    rejected = _accepted_audit() | {
        "fact_bound": False,
        "accepted": False,
        "issues": ["fact_unbound"],
    }
    result = asyncio.run(
        image_trial.run_moments_image_trial(
            preflight,
            output_dir=tmp_path / "audit-rejected",
            chat=FakeChatModel(_draft(preflight).model_dump(mode="json"), rejected),
            image=image,
            references=_references(),
            copy_ledger_dir=tmp_path / "copy-ledger-2",
            image_ledger_dir=tmp_path / "image-ledger",
        )
    )
    assert result["copy_status"] == "copy_audit_rejected"
    assert result["image_intents"] == 0
    assert not image.calls
    assert (
        not list((tmp_path / "image-ledger").glob("*.intent.json"))
        if (tmp_path / "image-ledger").exists()
        else True
    )


def test_measured_layout_failure_never_reserves_audit_or_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preflight = _preflight(tmp_path)
    image = FakeImageModel()

    def reject_layout(*_args: object) -> None:
        raise RichCopyError("Moments rich card exceeds full-width layout")

    monkeypatch.setattr(copy_trial, "preflight_moments_rich_layout", reject_layout)
    chat = FakeChatModel(_draft(preflight).model_dump(mode="json"))
    result = asyncio.run(
        image_trial.run_moments_image_trial(
            preflight,
            output_dir=tmp_path / "layout-rejected",
            chat=chat,
            image=image,
            references=_references(),
            copy_ledger_dir=tmp_path / "copy-ledger",
            image_ledger_dir=tmp_path / "image-ledger",
        )
    )
    assert result["copy_status"] == "generation_copy_rejected"
    assert result["image_intents"] == 0
    assert len(chat.calls) == 1
    assert not image.calls


def test_changed_independent_audit_intent_cannot_enter_image_stage(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path)
    copy_dir = tmp_path / "accepted-copy"
    copy_ledger = tmp_path / "copy-ledger"
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=copy_dir,
            models=FakeChatModel(_draft(preflight).model_dump(mode="json"), _accepted_audit()),
            model_name="fake-chat",
            ledger_dir=copy_ledger,
        )
    )
    assert result["status"] == "copy_audit_passed_unpublished"
    audit_intent = copy_dir / "private" / "audit.intent.json"
    intent = json.loads(audit_intent.read_text(encoding="utf-8"))
    intent["prompt_sha256"] = "0" * 64
    audit_intent.write_text(json.dumps(intent), encoding="utf-8")
    with pytest.raises(ValueError, match="audit intent differs"):
        image_trial._accepted_copy(preflight, copy_dir, copy_ledger)


def test_changed_generated_draft_cannot_reuse_accepted_image_proposal(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path)
    copy_dir = tmp_path / "accepted-copy"
    copy_ledger = tmp_path / "copy-ledger"
    result = asyncio.run(
        execute_trial(
            preflight,
            output_dir=copy_dir,
            models=FakeChatModel(_draft(preflight).model_dump(mode="json"), _accepted_audit()),
            model_name="fake-chat",
            ledger_dir=copy_ledger,
        )
    )
    assert result["status"] == "copy_audit_passed_unpublished"
    response_path = copy_dir / "private" / "generation-response.json"
    response = json.loads(response_path.read_text(encoding="utf-8"))
    response["top"] = response["top"].replace("值得", "适合", 1)
    response_path.write_text(json.dumps(response, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="differs from generated same-package draft"):
        image_trial._accepted_copy(preflight, copy_dir, copy_ledger)


def test_passed_same_package_copy_can_make_one_review_only_jpeg(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path)
    image = FakeImageModel()
    result = asyncio.run(
        image_trial.run_moments_image_trial(
            preflight,
            output_dir=tmp_path / "accepted",
            chat=FakeChatModel(_draft(preflight).model_dump(mode="json"), _accepted_audit()),
            image=image,
            references=_references(),
            copy_ledger_dir=tmp_path / "copy-ledger-1",
            image_ledger_dir=tmp_path / "image-ledger",
        )
    )
    assert result["copy_status"] == "copy_audit_passed_unpublished"
    assert result["image_status"] == "generated_pending_exact_jpeg_review"
    assert result["image_intents"] == 1
    assert result["send_ready"] is False
    assert result["footer_mode"] == "local_unpublished"
    assert result["ocr"] == result["visual_audit"] == "not_checked"
    assert len(image.calls) == 1
    assert image.calls[0].references == _references()
    assert len(list((tmp_path / "image-ledger").glob("*.intent.json"))) == 1
    jpeg = (tmp_path / "accepted" / "images" / "group.jpg").read_bytes()
    assert sha256(jpeg).hexdigest() == result["group_image_sha256"]
    raw = (tmp_path / "accepted" / "images" / "raw.png").read_bytes()
    local_footer = render_exact_source_footer(raw, preflight.case, mode="local")
    assert local_footer.image_sha256 == result["footer_image_sha256"]
    with Image.open(BytesIO(jpeg)) as opened:
        assert opened.format == "JPEG"
        assert opened.size == (1152, 2048)


def test_unknown_image_result_stays_reserved_and_cannot_replay(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path)
    image = FakeImageModel(failure=TimeoutError("fake provider uncertainty"))
    first = asyncio.run(
        image_trial.run_moments_image_trial(
            preflight,
            output_dir=tmp_path / "first",
            chat=FakeChatModel(_draft(preflight).model_dump(mode="json"), _accepted_audit()),
            image=image,
            references=_references(),
            copy_ledger_dir=tmp_path / "copy-ledger-1",
            image_ledger_dir=tmp_path / "image-ledger",
        )
    )
    assert first["image_status"] == "result_unknown_or_quality_failed"
    assert len(image.calls) == 1
    with pytest.raises(ValueError, match="already reserved"):
        asyncio.run(
            image_trial.run_moments_image_trial(
                preflight,
                output_dir=tmp_path / "second",
                chat=FakeChatModel(_draft(preflight).model_dump(mode="json"), _accepted_audit()),
                image=image,
                references=_references(),
                copy_ledger_dir=tmp_path / "copy-ledger-2",
                image_ledger_dir=tmp_path / "image-ledger",
            )
        )
    assert len(image.calls) == 1
