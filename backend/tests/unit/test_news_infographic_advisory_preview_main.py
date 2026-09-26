"""Provider-free checks for the one-case v12 advisory local poster."""

# ruff: noqa: RUF001 -- Chinese text is the poster's exact rendering contract.

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from app import news_infographic_advisory_preview_main as preview
from app.application.ports.image_generation import ImageGenerationRequest, ImageGenerationResult
from app.application.services.news_infographic_rich_copy import build_moments_rich_draft_plan
from app.core.errors import (
    ImageOutputValidationError,
    ImageProviderRejectedError,
    ImageProviderTimeoutError,
)
from app.news_infographic_advisory_preview_main import (
    execute_advisory_preview,
    preflight_advisory_preview,
)
from test_news_infographic_moments_copy_trial_main import (
    FakeChatModel,
    _accepted_audit,
    _frozen_files,
)
from test_news_infographic_moments_image_trial_main import FakeImageModel, _references


def _preflight(tmp_path: Path) -> Any:
    bundle, package, run = _frozen_files(tmp_path)
    return preflight_advisory_preview(
        input_bundle=bundle,
        package_detail=package,
        copy_run_detail=run,
        references=_references()[:1],
    )


def _concise_draft(preflight: Any) -> dict[str, str]:
    plan = build_moments_rich_draft_plan(
        preflight.frozen.case, preflight.frozen.binding, preflight.frozen.seed
    )
    return {
        "top": f"从{plan.news_anchor}出发，先看看新闻究竟说了什么。",
        "news": "报道中的哪些词句值得再核对？",
        "child": "请孩子圈出原句，再写下一个想查证的问题。",
        "brand": f"围绕{plan.news_anchor}，请孩子先说出猜想，再回到原文核对。",
    }


def test_preflight_pins_new_policy_and_makes_no_intent(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path)
    assert preflight.frozen.case.package_id == preflight.frozen.binding.package_id
    assert preflight.safe_projection()["send_ready"] is False
    assert preflight.safe_projection()["image_intents"] == 0
    assert (
        preflight.safe_projection()["policy_version"]
        == "wecom-news-infographic-v12-shared-anchor-advisory"
    )
    assert preflight.safe_projection()["reference_contract"] == "formal_v12_character_only"
    assert preview._LEDGER_DIR.name == "daily-news-infographic-advisory-v12-intents"
    assert not (tmp_path / "ledger").exists()


def test_preflight_rejects_extra_style_reference_and_wrong_lineage(tmp_path: Path) -> None:
    paths = _frozen_files(tmp_path)
    with pytest.raises(preview.TrialInputError, match="formal v12 character reference"):
        preflight_advisory_preview(
            input_bundle=paths[0],
            package_detail=paths[1],
            copy_run_detail=paths[2],
            references=_references(),
        )
    run = json.loads(paths[2].read_text(encoding="utf-8"))
    run["status"] = "rejected"
    paths[2].write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        preflight_advisory_preview(
            input_bundle=paths[0],
            package_detail=paths[1],
            copy_run_detail=paths[2],
            references=_references()[:1],
        )


def test_negative_audit_still_makes_one_marked_local_image(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path)
    plan = build_moments_rich_draft_plan(
        preflight.frozen.case, preflight.frozen.binding, preflight.frozen.seed
    )
    raw_draft = _concise_draft(preflight)
    raw_draft["child"] = plan.child_frame + raw_draft["child"]
    old_ledger = tmp_path / "daily-news-infographic-advisory-v10-intents"
    old_ledger.mkdir(mode=0o700)
    old_intent = old_ledger / "consumed-v10.generation.intent.json"
    old_intent.write_text('{"state":"reserved"}', encoding="utf-8")
    old_bytes = old_intent.read_bytes()
    rejected = _accepted_audit()
    rejected["accepted"] = False
    rejected["fact_bound"] = False
    rejected["issues"] = ["fact_unbound"]
    chat = FakeChatModel(raw_draft, rejected)
    image = FakeImageModel()
    output = tmp_path / "preview"
    result = asyncio.run(
        execute_advisory_preview(
            preflight,
            output_dir=output,
            chat=chat,
            image=image,
            chat_model_name="fake-chat",
            ledger_dir=tmp_path / "ledger",
        )
    )
    assert result["status"] == "generated_local_preview_pending_human_inspection"
    assert result["send_ready"] is False and result["copy_approved"] is False
    assert result["generation_intents"] == result["audit_intents"] == 1
    assert result["image_intents"] == len(image.calls) == 1
    assert "copy_audit_rejected" in result["warning_codes"]
    assert (output / "images/group.jpg").is_file()
    assert (output / "images/phone-390.png").is_file()
    assert (output / "private/generation-response.json").stat().st_mode & 0o077 == 0
    assert json.loads((output / "private/generation-response.json").read_text()) == raw_draft
    normalized = json.loads((output / "private/rich-copy.json").read_text())
    assert normalized["normalized_exact_prefixes"] == ["child"]
    assert result["normalized_exact_prefixes"] == ["child"]
    assert result["raw_draft_sha256"] == normalized["raw_draft_sha256"]
    assert (
        result["raw_draft_sha256"]
        == sha256((output / "private/generation-response.json").read_bytes()).hexdigest()
    )
    assert result["raw_response_sha256"] == result["raw_draft_sha256"]
    assert normalized["child_body"] == raw_draft["child"]
    assert normalized["child_body"].count(plan.child_frame) == 1
    assert old_intent.read_bytes() == old_bytes
    assert len(list((tmp_path / "ledger").glob("*.intent.json"))) == 3
    with pytest.raises(preview.TrialInputError, match="reserved intent"):
        asyncio.run(
            execute_advisory_preview(
                preflight,
                output_dir=tmp_path / "second",
                chat=FakeChatModel(_concise_draft(preflight), rejected),
                image=FakeImageModel(),
                chat_model_name="fake-chat",
                ledger_dir=tmp_path / "ledger",
            )
        )
    assert not (tmp_path / "second").exists()


def test_malformed_audit_is_warning_not_fake_approval(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path)
    chat = FakeChatModel(_concise_draft(preflight), {"accepted": True})
    image = FakeImageModel()
    result = asyncio.run(
        execute_advisory_preview(
            preflight,
            output_dir=tmp_path / "preview",
            chat=chat,
            image=image,
            chat_model_name="fake-chat",
            ledger_dir=tmp_path / "ledger",
        )
    )
    assert result["image_intents"] == len(image.calls) == 1
    assert "copy_audit_schema_invalid" in result["warning_codes"]
    assert result["copy_approved"] is False


def test_unknown_generation_reserves_only_its_own_intent(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path)
    image = FakeImageModel()
    result = asyncio.run(
        execute_advisory_preview(
            preflight,
            output_dir=tmp_path / "preview",
            chat=FakeChatModel(TimeoutError()),
            image=image,
            chat_model_name="fake-chat",
            ledger_dir=tmp_path / "ledger",
        )
    )
    assert result["status"] == "generation_result_unknown"
    assert result["generation_intents"] == 1
    assert result["audit_intents"] == result["image_intents"] == 0
    assert len(image.calls) == 0
    assert len(list((tmp_path / "ledger").glob("*.intent.json"))) == 1


@pytest.mark.parametrize(
    ("failure", "category", "exception_class", "reason_code", "http_status"),
    [
        (
            ImageProviderRejectedError(http_status=503, response_kind="json"),
            "provider_exception",
            "ImageProviderRejectedError",
            "image_provider_rejected",
            503,
        ),
        (
            ImageProviderTimeoutError(),
            "provider_exception",
            "ImageProviderTimeoutError",
            "image_provider_timeout",
            None,
        ),
        (
            ImageOutputValidationError("image_dimensions_invalid"),
            "result_validation",
            "ImageOutputValidationError",
            "image_dimensions_invalid",
            None,
        ),
        (
            RuntimeError("PRIVATE_PROVIDER_RESPONSE secret-token"),
            "provider_exception",
            "other_exception",
            "provider_outcome_unknown",
            None,
        ),
    ],
)
def test_image_provider_failure_has_only_allowlisted_non_replayable_diagnostic(
    tmp_path: Path,
    failure: Exception,
    category: str,
    exception_class: str,
    reason_code: str,
    http_status: int | None,
) -> None:
    preflight = _preflight(tmp_path)
    image = FakeImageModel(failure=failure)
    output = tmp_path / "preview"
    result = asyncio.run(
        execute_advisory_preview(
            preflight,
            output_dir=output,
            chat=FakeChatModel(_concise_draft(preflight), _accepted_audit()),
            image=image,
            chat_model_name="fake-chat",
            ledger_dir=tmp_path / "ledger",
        )
    )
    assert result["status"] == "image_result_unknown_or_quality_failed"
    assert result["image_intents"] == len(image.calls) == 1
    assert result["send_ready"] is False
    assert result["image_failure"] == {
        "version": "advisory-local-image-failure-v1",
        "category": category,
        "exception_class": exception_class,
        "reason_code": reason_code,
        **({"http_status": http_status, "response_kind": "json"} if http_status else {}),
    }
    assert not (output / "images").exists()
    assert "PRIVATE_PROVIDER_RESPONSE" not in (output / "summary.json").read_text()
    assert "secret-token" not in (output / "summary.json").read_text()
    assert len(list((tmp_path / "ledger").glob("*.intent.json"))) == 3
    with pytest.raises(preview.TrialInputError, match="reserved intent"):
        asyncio.run(
            execute_advisory_preview(
                preflight,
                output_dir=tmp_path / "retry",
                chat=FakeChatModel(_concise_draft(preflight)),
                image=FakeImageModel(),
                chat_model_name="fake-chat",
                ledger_dir=tmp_path / "ledger",
            )
        )
    assert not (tmp_path / "retry").exists()


@pytest.mark.parametrize("kind", ["rejected", "output_invalid"])
def test_mutated_provider_metadata_cannot_leak_into_public_summary(
    tmp_path: Path, kind: str
) -> None:
    preflight = _preflight(tmp_path)
    failure: Exception
    if kind == "rejected":
        failure = ImageProviderRejectedError(http_status=503, response_kind="json")
        failure.http_status = "PRIVATE_PROVIDER_RESPONSE"  # type: ignore[assignment]
        failure.response_kind = "secret-token"
        expected: dict[str, object] = {
            "version": "advisory-local-image-failure-v1",
            "category": "provider_exception",
            "exception_class": "ImageProviderRejectedError",
            "reason_code": "image_provider_rejected",
        }
    else:
        failure = ImageOutputValidationError("image_dimensions_invalid")
        failure.reason = "PRIVATE_PROVIDER_RESPONSE secret-token"
        expected = {
            "version": "advisory-local-image-failure-v1",
            "category": "result_validation",
            "exception_class": "ImageOutputValidationError",
            "reason_code": "image_output_invalid",
        }
    output = tmp_path / "preview"
    result = asyncio.run(
        execute_advisory_preview(
            preflight,
            output_dir=output,
            chat=FakeChatModel(_concise_draft(preflight), _accepted_audit()),
            image=FakeImageModel(failure=failure),
            chat_model_name="fake-chat",
            ledger_dir=tmp_path / "ledger",
        )
    )
    assert result["image_failure"] == expected
    assert "PRIVATE_PROVIDER_RESPONSE" not in (output / "summary.json").read_text()
    assert "secret-token" not in (output / "summary.json").read_text()
    assert result["image_intents"] == 1 and result["send_ready"] is False


def test_returned_image_identity_failure_is_not_a_provider_exception(tmp_path: Path) -> None:
    class WrongResultImage(FakeImageModel):
        async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
            result = await super().generate(request)
            return replace(result, request_fingerprint="other-request")

    preflight = _preflight(tmp_path)
    result = asyncio.run(
        execute_advisory_preview(
            preflight,
            output_dir=tmp_path / "preview",
            chat=FakeChatModel(_concise_draft(preflight), _accepted_audit()),
            image=WrongResultImage(),
            chat_model_name="fake-chat",
            ledger_dir=tmp_path / "ledger",
        )
    )
    assert result["image_failure"] == {
        "version": "advisory-local-image-failure-v1",
        "category": "result_validation",
        "reason_code": "result_identity_invalid",
    }
    assert result["image_intents"] == 1 and result["send_ready"] is False
    assert not (tmp_path / "preview/images").exists()


def test_derivative_failure_keeps_raw_but_never_claims_a_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preflight = _preflight(tmp_path)

    def fail_notice(_: bytes) -> bytes:
        raise RuntimeError("PRIVATE_PROVIDER_RESPONSE secret-token")

    monkeypatch.setattr(preview, "render_advisory_notice", fail_notice)
    result = asyncio.run(
        execute_advisory_preview(
            preflight,
            output_dir=tmp_path / "preview",
            chat=FakeChatModel(_concise_draft(preflight), _accepted_audit()),
            image=FakeImageModel(),
            chat_model_name="fake-chat",
            ledger_dir=tmp_path / "ledger",
        )
    )
    assert result["image_failure"] == {
        "version": "advisory-local-image-failure-v1",
        "category": "derivative",
        "reason_code": "notice_render_failed",
    }
    assert result["image_intents"] == 1 and result["send_ready"] is False
    assert (tmp_path / "preview/images/raw.png").is_file()
    assert not (tmp_path / "preview/images/group.jpg").exists()
    assert "PRIVATE_PROVIDER_RESPONSE" not in (tmp_path / "preview/summary.json").read_text()


def test_rejected_draft_keeps_private_raw_response_hash_without_image(tmp_path: Path) -> None:
    preflight = _preflight(tmp_path)
    raw = _concise_draft(preflight)
    raw["child"] = "不合格" * 200
    image = FakeImageModel()
    output = tmp_path / "preview"
    result = asyncio.run(
        execute_advisory_preview(
            preflight,
            output_dir=output,
            chat=FakeChatModel(raw),
            image=image,
            chat_model_name="fake-chat",
            ledger_dir=tmp_path / "ledger",
        )
    )
    assert result["status"] == "rich_copy_unusable"
    assert (
        result["raw_response_sha256"]
        == sha256((output / "private/generation-response.json").read_bytes()).hexdigest()
    )
    assert result["audit_intents"] == result["image_intents"] == 0
    assert image.calls == []


def test_dry_cli_never_loads_provider_or_creates_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _frozen_files(tmp_path)
    monkeypatch.setattr(preview, "_approved_references", lambda **_: _references()[:1])
    monkeypatch.setattr(preview, "get_settings", lambda: pytest.fail("provider loaded"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "advisory-preview",
            "--input-bundle",
            str(paths[0]),
            "--package-detail",
            str(paths[1]),
            "--copy-run-detail",
            str(paths[2]),
            "--approved-asset-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "no-output"),
        ],
    )
    assert asyncio.run(preview._main()) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "advisory_preview_preflight_valid"
    assert not (tmp_path / "no-output").exists()


def test_dry_cli_blocks_an_already_reserved_stage_without_provider_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _frozen_files(tmp_path)
    preflight = preflight_advisory_preview(
        input_bundle=paths[0],
        package_detail=paths[1],
        copy_run_detail=paths[2],
        references=_references()[:1],
    )
    ledger = tmp_path / "ledger"
    ledger.mkdir(mode=0o700)
    (ledger / f"{preflight.intent_key}.generation.intent.json").write_text("{}")
    monkeypatch.setattr(preview, "_LEDGER_DIR", ledger)
    monkeypatch.setattr(preview, "_approved_references", lambda **_: _references()[:1])
    monkeypatch.setattr(preview, "get_settings", lambda: pytest.fail("provider loaded"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "advisory-preview",
            "--input-bundle",
            str(paths[0]),
            "--package-detail",
            str(paths[1]),
            "--copy-run-detail",
            str(paths[2]),
            "--approved-asset-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "no-output"),
        ],
    )
    assert asyncio.run(preview._main()) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked_local_advisory_preview"
    assert not (tmp_path / "no-output").exists()
