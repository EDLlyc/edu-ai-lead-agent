"""Provider-free checks for the one-case exact-group-JPEG audit command."""

# ruff: noqa: RUF001 -- Frozen Chinese poster headings are intentional.

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path

import app.news_infographic_exact_jpeg_audit_main as audit
import pytest
from app.application.ports.image_validation import (
    ImageQualityAuditRequest,
    ImageQualityAuditResult,
    ImageTextRecognitionResult,
    PosterRegionRecognitionRequest,
)
from app.application.services.news_infographic import _approved_rich_worldskills_copy
from app.application.services.wecom_news_infographic import _poster_ocr_regions
from app.domain.image_validation import ImageQualityAuditIssue
from PIL import Image


def _jpeg() -> bytes:
    target = BytesIO()
    Image.new("RGB", (1152, 2048), "white").save(target, format="JPEG")
    return target.getvalue()


class _Models:
    def __init__(
        self,
        audited: audit.AuditInput,
        *,
        wrong_region: str = "",
        fail: bool = False,
        visual_warning: bool = False,
    ) -> None:
        self.expected = {
            region.region_id: region.expected_text
            for region in _poster_ocr_regions(
                audited.image_bytes, audited.copy, audited.footer_text
            )
        }
        self.wrong_region = wrong_region
        self.fail = fail
        self.visual_warning = visual_warning
        self.ocr_calls: list[str] = []
        self.visual_calls = 0

    async def recognize_poster_region(
        self, request: PosterRegionRecognitionRequest
    ) -> ImageTextRecognitionResult:
        self.ocr_calls.append(request.region_id)
        if self.fail:
            raise RuntimeError("ambiguous provider result")
        observed = (
            "wrong" if request.region_id == self.wrong_region else self.expected[request.region_id]
        )
        return ImageTextRecognitionResult(
            recognized_lines=(observed,), request_fingerprint=request.request_fingerprint
        )

    async def audit_visual(self, request: ImageQualityAuditRequest) -> ImageQualityAuditResult:
        self.visual_calls += 1
        return ImageQualityAuditResult(
            accepted=True,
            request_fingerprint=request.request_fingerprint,
            issues=(ImageQualityAuditIssue(code="text_artifact", severity="warning"),)
            if self.visual_warning
            else (),
        )


@pytest.fixture
def audited(monkeypatch: pytest.MonkeyPatch) -> audit.AuditInput:
    image = _jpeg()
    result = audit.AuditInput(
        image_bytes=image,
        copy=_approved_rich_worldskills_copy(),
        footer_text="新闻日期：2026-09-23新闻来源：中国政府网要闻原文链接：https://example.org/news",
        image_sha256=sha256(image).hexdigest(),
        input_fingerprint="1" * 64,
    )
    monkeypatch.setattr(audit, "preflight_existing", lambda *_: result)
    return result


@pytest.mark.asyncio
async def test_default_preflight_never_calls_provider(
    tmp_path: Path, audited: audit.AuditInput
) -> None:
    source = tmp_path / audit._RUN_NAME
    output = tmp_path / audit._PREFLIGHT_RUN_NAME
    models = _Models(audited)
    summary = await audit.audit_existing(
        run_dir=source,
        input_bundle=tmp_path / "input.json",
        output_dir=output,
        models=models,
    )
    assert summary["preflight"] == "passed"
    assert summary["ocr"] == "not_checked"
    assert summary["visual"] == "not_checked"
    assert summary["send_ready"] is False
    assert summary["provider_call_intents"] == 0
    assert not models.ocr_calls and models.visual_calls == 0
    assert (output / "summary.json").is_file()
    with pytest.raises(FileExistsError):
        await audit.audit_existing(
            run_dir=source, input_bundle=tmp_path / "input.json", output_dir=output
        )


@pytest.mark.asyncio
async def test_exact_five_regions_and_visual_still_do_not_mark_sendable(
    tmp_path: Path, audited: audit.AuditInput
) -> None:
    models = _Models(audited)
    output = tmp_path / audit._AUDIT_RUN_NAME
    summary = await audit.audit_existing(
        run_dir=tmp_path / audit._RUN_NAME,
        input_bundle=tmp_path / "input.json",
        output_dir=output,
        execute=True,
        models=models,
    )
    assert models.ocr_calls == ["masthead", "science", "learning", "brand", "footer"]
    assert models.visual_calls == 1
    assert summary["ocr"] == "passed" and summary["visual"] == "passed"
    assert summary["provider_call_intents"] == 6
    assert summary["human_phone_review"] == "pending"
    assert summary["send_ready"] is False
    assert len(list((output / "private").glob("*.intent.json"))) == 6
    assert (output / "private/visual-verdict.json").is_file()


@pytest.mark.asyncio
async def test_visual_warning_is_not_a_pass(tmp_path: Path, audited: audit.AuditInput) -> None:
    models = _Models(audited, visual_warning=True)
    summary = await audit.audit_existing(
        run_dir=tmp_path / audit._RUN_NAME,
        input_bundle=tmp_path / "input.json",
        output_dir=tmp_path / audit._AUDIT_RUN_NAME,
        execute=True,
        models=models,
    )
    assert summary["ocr"] == "passed"
    assert summary["visual"] == "rejected"
    assert summary["send_ready"] is False


@pytest.mark.asyncio
async def test_explicit_execution_requires_models_before_writing(
    tmp_path: Path, audited: audit.AuditInput
) -> None:
    output = tmp_path / audit._AUDIT_RUN_NAME
    with pytest.raises(audit.ExactJpegAuditError, match="models are unavailable"):
        await audit.audit_existing(
            run_dir=tmp_path / audit._RUN_NAME,
            input_bundle=tmp_path / "input.json",
            output_dir=output,
            execute=True,
        )
    assert not output.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_region", ["masthead", "science", "learning", "brand", "footer"])
async def test_any_mismatched_region_stops_visual(
    tmp_path: Path, audited: audit.AuditInput, wrong_region: str
) -> None:
    models = _Models(audited, wrong_region=wrong_region)
    summary = await audit.audit_existing(
        run_dir=tmp_path / audit._RUN_NAME,
        input_bundle=tmp_path / "input.json",
        output_dir=tmp_path / audit._AUDIT_RUN_NAME,
        execute=True,
        models=models,
    )
    assert summary["ocr"] == "failed"
    assert summary["visual"] == "not_checked"
    assert summary["send_ready"] is False
    assert models.visual_calls == 0


@pytest.mark.asyncio
async def test_unknown_ocr_preserves_intent_and_blocks_replay(
    tmp_path: Path, audited: audit.AuditInput
) -> None:
    models = _Models(audited, fail=True)
    output = tmp_path / audit._AUDIT_RUN_NAME
    summary = await audit.audit_existing(
        run_dir=tmp_path / audit._RUN_NAME,
        input_bundle=tmp_path / "input.json",
        output_dir=output,
        execute=True,
        models=models,
    )
    assert summary["ocr"] == "result_unknown"
    assert summary["provider_call_intents"] == 1
    assert summary["send_ready"] is False
    assert (output / "private/masthead.intent.json").is_file()
    with pytest.raises(FileExistsError):
        await audit.audit_existing(
            run_dir=tmp_path / audit._RUN_NAME,
            input_bundle=tmp_path / "input.json",
            output_dir=output,
            execute=True,
            models=models,
        )


def test_symlink_input_is_refused(tmp_path: Path) -> None:
    actual = tmp_path / "real.json"
    actual.write_text("{}", encoding="utf-8")
    linked = tmp_path / "linked.json"
    linked.symlink_to(actual)
    with pytest.raises(audit.ExactJpegAuditError, match="symlink"):
        audit._read_regular(linked, limit=100)


def test_cli_rejects_copied_run_and_alternate_paid_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit, "_WORKSPACE_ROOT", tmp_path)
    run = tmp_path / "output" / audit._RUN_NAME
    source = tmp_path / "output/daily-news-infographic-skills-input-20260924/input.json"
    output = tmp_path / "output" / audit._AUDIT_RUN_NAME
    audit._validate_cli_paths(run_dir=run, input_bundle=source, output_dir=output, execute=True)
    with pytest.raises(audit.ExactJpegAuditError, match="frozen local case"):
        audit._validate_cli_paths(
            run_dir=tmp_path / "copied" / audit._RUN_NAME,
            input_bundle=source,
            output_dir=tmp_path / "copied" / audit._AUDIT_RUN_NAME,
            execute=True,
        )
    with pytest.raises(audit.ExactJpegAuditError, match="frozen local case"):
        audit._validate_cli_paths(
            run_dir=run,
            input_bundle=source,
            output_dir=tmp_path / "output/renamed-audit-to-retry",
            execute=True,
        )


@pytest.mark.asyncio
async def test_changing_output_name_cannot_replay_an_unknown_provider_intent(
    tmp_path: Path, audited: audit.AuditInput
) -> None:
    models = _Models(audited, fail=True)
    source = tmp_path / audit._RUN_NAME
    await audit.audit_existing(
        run_dir=source,
        input_bundle=tmp_path / "input.json",
        output_dir=tmp_path / audit._AUDIT_RUN_NAME,
        execute=True,
        models=models,
    )
    with pytest.raises(audit.ExactJpegAuditError, match="fixed fresh audit sibling"):
        await audit.audit_existing(
            run_dir=source,
            input_bundle=tmp_path / "input.json",
            output_dir=tmp_path / "renamed-audit-to-retry",
            execute=True,
            models=models,
        )
    assert models.ocr_calls == ["masthead"]


@pytest.mark.asyncio
async def test_preflight_does_not_consume_paid_audit_identity(
    tmp_path: Path, audited: audit.AuditInput
) -> None:
    source = tmp_path / audit._RUN_NAME
    models = _Models(audited)
    await audit.audit_existing(
        run_dir=source,
        input_bundle=tmp_path / "input.json",
        output_dir=tmp_path / audit._PREFLIGHT_RUN_NAME,
    )
    summary = await audit.audit_existing(
        run_dir=source,
        input_bundle=tmp_path / "input.json",
        output_dir=tmp_path / audit._AUDIT_RUN_NAME,
        execute=True,
        models=models,
    )
    assert summary["ocr"] == "passed"
    assert summary["visual"] == "passed"
