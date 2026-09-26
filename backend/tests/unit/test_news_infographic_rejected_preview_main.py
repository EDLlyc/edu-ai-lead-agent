"""Reviewed rejected copy may make one marked local preview, never a delivery image."""

# ruff: noqa: RUF001 -- exact Chinese reviewer sample is intentional.

from __future__ import annotations

import asyncio
import json
import stat
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from app.application.services.news_infographic_footer import render_exact_source_footer
from app.news_infographic_moments_copy_trial_main import TrialInputError
from app.news_infographic_moments_rejected_audit_main import (
    RejectedDraftAuditVerdict,
    execute_rejected_audit,
)
from app.news_infographic_rejected_preview_main import (
    _notice_font_bytes,
    _warning_overlay,
    execute_rejected_preview,
    preflight_rejected_preview,
)
from PIL import Image, ImageChops, ImageDraw
from test_news_infographic_moments_copy_trial_main import FakeChatModel
from test_news_infographic_moments_image_trial_main import FakeImageModel, _references
from test_news_infographic_moments_rejected_audit_main import (
    _preflight_rejected,
    _rejected_source,
    _supportive_verdict,
)


def _critical_verdict() -> dict[str, object]:
    return RejectedDraftAuditVerdict(
        schema_version="daily-news-infographic-rejected-copy-review-v1",
        facts_supported=False,
        brand_aligned=False,
        child_inquiry_specific=True,
        copy_quality_sufficient=False,
        no_unsupported_assertions=False,
        reviewer_supports_candidate=False,
        issues=("number_or_unit_restatement", "unsupported_distance_time_inference"),
        rationale="数字重复且把报道距离推成传播时间，不足以当作新闻事实。",
    ).model_dump(mode="json")


def _reviewed_case(tmp_path: Path, *, critical: bool) -> tuple[Any, Path, Path, Path]:
    paths, copy_dir, copy_ledger = _rejected_source(tmp_path)
    rejected = _preflight_rejected(paths, copy_dir, copy_ledger)
    audit_dir = tmp_path / "audit-01"
    audit_ledger = tmp_path / "audit-ledger"
    verdict = _critical_verdict() if critical else _supportive_verdict()
    audit = asyncio.run(
        execute_rejected_audit(
            rejected,
            output_dir=audit_dir,
            model=FakeChatModel(verdict),
            model_name="fake-reviewer",
            audit_ledger_dir=audit_ledger,
        )
    )
    assert audit["status"] == "observational_audit_complete"
    response = audit_dir / "private" / "audit-response.json"
    preflight = preflight_rejected_preview(
        input_bundle=paths[0],
        package_detail=paths[1],
        copy_run_detail=paths[2],
        source_copy_dir=copy_dir,
        expected_response_sha256=rejected.response_sha256,
        audit_dir=audit_dir,
        expected_audit_response_sha256=sha256(response.read_bytes()).hexdigest(),
        references=_references(),
        copy_ledger_dir=copy_ledger,
        audit_ledger_dir=audit_ledger,
    )
    return preflight, copy_dir, audit_dir, audit_ledger


def _oversize_review_case(
    tmp_path: Path, *, changed: dict[str, object] | None = None
) -> tuple[tuple[Path, Path, Path], Path, Path, Path, Path, str]:
    paths, copy_dir, copy_ledger = _rejected_source(tmp_path)
    rejected = _preflight_rejected(paths, copy_dir, copy_ledger)
    audit_dir = tmp_path / "audit-01"
    audit_ledger = tmp_path / "audit-ledger"
    response = _critical_verdict()
    response["rationale"] = "待核实" * 243 + "证据"  # 731 characters
    assert len(str(response["rationale"])) == 731
    if changed:
        response.update(changed)
    audit = asyncio.run(
        execute_rejected_audit(
            rejected,
            output_dir=audit_dir,
            model=FakeChatModel(response),
            model_name="fake-reviewer",
            audit_ledger_dir=audit_ledger,
        )
    )
    assert audit["status"] == "observational_audit_schema_invalid"
    digest = sha256((audit_dir / "private" / "audit-response.json").read_bytes()).hexdigest()
    return paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest


def _preflight_oversize(
    paths: tuple[Path, Path, Path],
    copy_dir: Path,
    copy_ledger: Path,
    audit_dir: Path,
    audit_ledger: Path,
    digest: str,
) -> Any:
    rejected = _preflight_rejected(paths, copy_dir, copy_ledger)
    return preflight_rejected_preview(
        input_bundle=paths[0],
        package_detail=paths[1],
        copy_run_detail=paths[2],
        source_copy_dir=copy_dir,
        expected_response_sha256=rejected.response_sha256,
        audit_dir=audit_dir,
        expected_audit_response_sha256=digest,
        references=_references(),
        copy_ledger_dir=copy_ledger,
        audit_ledger_dir=audit_ledger,
    )


@pytest.mark.parametrize("critical", [True, False])
def test_typed_review_even_if_critical_makes_only_marked_local_jpeg(
    tmp_path: Path, critical: bool
) -> None:
    preflight, copy_dir, _audit_dir, _audit_ledger = _reviewed_case(tmp_path, critical=critical)
    assert preflight.safe_projection()["image_intents"] == 0
    assert preflight.safe_projection()["reviewer_supports_candidate"] is (not critical)
    assert "137亿光年" in preflight.image_prompt
    assert "【待核实】" in preflight.image_prompt
    assert "137亿年" not in preflight.image_prompt
    image = FakeImageModel()
    output = tmp_path / "preview-01"
    summary = asyncio.run(
        execute_rejected_preview(
            preflight,
            output_dir=output,
            image=image,
            image_ledger_dir=tmp_path / "image-ledger",
        )
    )
    assert len(image.calls) == 1
    assert summary["image_status"] == "generated_review_only_pending_human_inspection"
    assert summary["source_copy_status"] == "generation_copy_rejected"
    assert summary["reviewer_supports_candidate"] is (not critical)
    assert summary["image_intents"] == 1
    assert summary["generation_calls"] == summary["audit_calls"] == 0
    assert summary["proposal_ready"] is summary["send_ready"] is False
    assert summary["notice"] == "本地预览 · 内容待核实 · 未发布"
    private_verdict = output / "private" / "review-verdict.json"
    assert stat.S_IMODE(private_verdict.stat().st_mode) == 0o600
    assert json.loads(private_verdict.read_text())["reviewer_supports_candidate"] is (not critical)
    assert not (copy_dir / "private" / "proposal.json").exists()
    group = (output / "images" / "group.jpg").read_bytes()
    assert len(group) <= 2 * 1024 * 1024
    assert sha256(group).hexdigest() == summary["group_image_sha256"]
    with Image.open(BytesIO(group)) as opened:
        assert opened.format == "JPEG"
        assert opened.size == (1152, 2048)
        opened.load()
        pixel = opened.convert("RGB").getpixel((10, 10))
        assert isinstance(pixel, tuple) and pixel[0] > 100
    with Image.open(output / "images" / "marked.png") as marked:
        assert marked.getpixel((10, 10)) == (164, 19, 41)
    assert (output / "images" / "phone-390.png").exists()
    assert json.loads((output / "summary.json").read_text())["send_ready"] is False
    replay = FakeImageModel()
    with pytest.raises(TrialInputError, match="already exists"):
        asyncio.run(
            execute_rejected_preview(
                preflight,
                output_dir=tmp_path / "preview-02",
                image=replay,
                image_ledger_dir=tmp_path / "image-ledger",
            )
        )
    assert replay.calls == []


def test_unknown_preview_consumes_fixed_image_intent_without_retry(tmp_path: Path) -> None:
    preflight, _copy, _audit, _ledger = _reviewed_case(tmp_path, critical=True)
    image_ledger = tmp_path / "image-ledger"
    image = FakeImageModel(failure=TimeoutError("unknown upstream result"))
    first = asyncio.run(
        execute_rejected_preview(
            preflight,
            output_dir=tmp_path / "preview-01",
            image=image,
            image_ledger_dir=image_ledger,
        )
    )
    assert first["image_status"] == "result_unknown_or_quality_failed"
    assert first["send_ready"] is False
    assert len(image.calls) == 1
    second = FakeImageModel()
    with pytest.raises(TrialInputError, match="already exists"):
        asyncio.run(
            execute_rejected_preview(
                preflight,
                output_dir=tmp_path / "preview-02",
                image=second,
                image_ledger_dir=image_ledger,
            )
        )
    assert second.calls == []


def test_unknown_observational_review_cannot_open_preview(tmp_path: Path) -> None:
    paths, copy_dir, copy_ledger = _rejected_source(tmp_path)
    rejected = _preflight_rejected(paths, copy_dir, copy_ledger)
    audit_dir = tmp_path / "audit-01"
    audit_ledger = tmp_path / "audit-ledger"
    result = asyncio.run(
        execute_rejected_audit(
            rejected,
            output_dir=audit_dir,
            model=FakeChatModel(TimeoutError("unknown reviewer outcome")),
            model_name="fake-reviewer",
            audit_ledger_dir=audit_ledger,
        )
    )
    assert result["status"] == "observational_audit_result_unknown"
    with pytest.raises((OSError, TrialInputError)):
        preflight_rejected_preview(
            input_bundle=paths[0],
            package_detail=paths[1],
            copy_run_detail=paths[2],
            source_copy_dir=copy_dir,
            expected_response_sha256=rejected.response_sha256,
            audit_dir=audit_dir,
            expected_audit_response_sha256="0" * 64,
            references=_references(),
            copy_ledger_dir=copy_ledger,
            audit_ledger_dir=audit_ledger,
        )
    assert not (tmp_path / "image-ledger").exists()


def test_tampered_observation_fails_before_any_image_intent(tmp_path: Path) -> None:
    preflight, _copy, audit_dir, _ledger = _reviewed_case(tmp_path, critical=True)
    response = audit_dir / "private" / "audit-response.json"
    payload = json.loads(response.read_text(encoding="utf-8"))
    payload["rationale"] += "改"
    response.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    image = FakeImageModel()
    with pytest.raises(TrialInputError, match="expected digest"):
        asyncio.run(
            execute_rejected_preview(
                preflight,
                output_dir=tmp_path / "preview-01",
                image=image,
                image_ledger_dir=tmp_path / "image-ledger",
            )
        )
    assert image.calls == []
    assert not (tmp_path / "image-ledger").exists()


def test_wrong_image_model_fails_before_reservation(tmp_path: Path) -> None:
    preflight, _copy, _audit, _ledger = _reviewed_case(tmp_path, critical=False)
    image = FakeImageModel()
    image.image_model = "wrong-model"
    with pytest.raises(TrialInputError, match="pinned Comfly"):
        asyncio.run(
            execute_rejected_preview(
                preflight,
                output_dir=tmp_path / "preview-01",
                image=image,
                image_ledger_dir=tmp_path / "image-ledger",
            )
        )
    assert image.calls == []
    assert not (tmp_path / "image-ledger").exists()


def test_only_oversize_rationale_gets_degraded_local_preview(tmp_path: Path) -> None:
    paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest = _oversize_review_case(tmp_path)
    preflight = _preflight_oversize(paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest)
    assert preflight.review_state == "invalid_rationale_too_long"
    assert preflight.safe_projection()["reviewer_supports_candidate"] is None
    assert preflight.safe_projection()["reviewer_issue_codes"] == []
    assert preflight.safe_projection()["notice"] == "审核格式异常 · 内容待核实 · 未发布"
    assert not (audit_dir / "private" / "audit-verdict.json").exists()
    output = tmp_path / "preview-01"
    image = FakeImageModel()
    summary = asyncio.run(
        execute_rejected_preview(
            preflight,
            output_dir=output,
            image=image,
            image_ledger_dir=tmp_path / "image-ledger",
        )
    )
    assert len(image.calls) == 1
    assert summary["review_state"] == "invalid_rationale_too_long"
    assert summary["image_status"] == "generated_review_only_pending_human_inspection"
    assert summary["notice"] == "审核格式异常 · 内容待核实 · 未发布"
    assert summary["reviewer_supports_candidate"] is None
    assert summary["reviewer_issue_codes"] == []
    assert summary["send_ready"] is False
    assert not (output / "private" / "review-verdict.json").exists()
    observation = output / "private" / "review-observation.json"
    assert stat.S_IMODE(observation.stat().st_mode) == 0o600
    observation_payload = json.loads(observation.read_text())
    assert observation_payload["rationale_length"] == 731
    assert observation_payload["issue_codes"] == [
        "number_or_unit_restatement",
        "unsupported_distance_time_inference",
    ]
    assert (output / "images" / "group.jpg").exists()
    assert (output / "images" / "phone-390.png").exists()
    assert json.loads((audit_dir / "summary.json").read_text())["status"] == (
        "observational_audit_schema_invalid"
    )
    replay = FakeImageModel()
    with pytest.raises(TrialInputError, match="already exists"):
        asyncio.run(
            execute_rejected_preview(
                preflight,
                output_dir=tmp_path / "preview-02",
                image=replay,
                image_ledger_dir=tmp_path / "image-ledger",
            )
        )
    assert replay.calls == []


def test_degraded_review_sha_change_and_unknown_image_cannot_be_retried(tmp_path: Path) -> None:
    paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest = _oversize_review_case(tmp_path)
    preflight = _preflight_oversize(paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest)
    response_path = audit_dir / "private" / "audit-response.json"
    original_response = response_path.read_bytes()
    response_path.write_bytes(original_response + b" ")
    image_ledger = tmp_path / "image-ledger"
    image = FakeImageModel()
    with pytest.raises(TrialInputError, match="expected digest"):
        asyncio.run(
            execute_rejected_preview(
                preflight,
                output_dir=tmp_path / "preview-01",
                image=image,
                image_ledger_dir=image_ledger,
            )
        )
    assert image.calls == []
    assert not image_ledger.exists()
    response_path.write_bytes(original_response)
    unknown = FakeImageModel(failure=TimeoutError("unknown image result"))
    result = asyncio.run(
        execute_rejected_preview(
            preflight,
            output_dir=tmp_path / "preview-01",
            image=unknown,
            image_ledger_dir=image_ledger,
        )
    )
    assert result["image_status"] == "result_unknown_or_quality_failed"
    assert len(unknown.calls) == 1
    replay = FakeImageModel()
    with pytest.raises(TrialInputError, match="already exists"):
        asyncio.run(
            execute_rejected_preview(
                preflight,
                output_dir=tmp_path / "preview-02",
                image=replay,
                image_ledger_dir=image_ledger,
            )
        )
    assert replay.calls == []


@pytest.mark.parametrize("rationale_length", [701, 1024])
def test_oversize_supportive_observation_is_not_falsely_treated_as_a_verdict(
    tmp_path: Path, rationale_length: int
) -> None:
    supportive = _supportive_verdict()
    supportive.pop("rationale")
    supportive["rationale"] = "待" * rationale_length
    paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest = _oversize_review_case(
        tmp_path, changed=supportive
    )
    preflight = _preflight_oversize(paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest)
    assert preflight.review_state == "invalid_rationale_too_long"
    assert preflight.safe_projection()["reviewer_supports_candidate"] is None
    assert preflight.safe_projection()["reviewer_issue_codes"] == []
    assert not (audit_dir / "private" / "audit-verdict.json").exists()


@pytest.mark.parametrize(
    "changed",
    [
        {"extra": "not permitted"},
        {"facts_supported": "false"},
        {"reviewer_supports_candidate": 0},
        {"reviewer_supports_candidate": True},
        {"issues": []},
        {"rationale": "待" * 1025},
    ],
)
def test_other_review_schema_errors_never_reserve_image(
    tmp_path: Path, changed: dict[str, object]
) -> None:
    paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest = _oversize_review_case(
        tmp_path, changed=changed
    )
    with pytest.raises(TrialInputError):
        _preflight_oversize(paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest)
    assert not (tmp_path / "image-ledger").exists()


def test_unknown_audit_has_no_preview_or_image_intent(tmp_path: Path) -> None:
    paths, copy_dir, copy_ledger = _rejected_source(tmp_path)
    rejected = _preflight_rejected(paths, copy_dir, copy_ledger)
    audit_dir = tmp_path / "audit-01"
    audit_ledger = tmp_path / "audit-ledger"
    result = asyncio.run(
        execute_rejected_audit(
            rejected,
            output_dir=audit_dir,
            model=FakeChatModel(TimeoutError("unknown result")),
            model_name="fake-reviewer",
            audit_ledger_dir=audit_ledger,
        )
    )
    assert result["status"] == "observational_audit_result_unknown"
    with pytest.raises((OSError, TrialInputError)):
        _preflight_oversize(paths, copy_dir, copy_ledger, audit_dir, audit_ledger, "0" * 64)
    assert not (tmp_path / "image-ledger").exists()


@pytest.mark.parametrize("degraded", [False, True])
def test_warning_overlay_preserves_complete_two_line_source_url(
    tmp_path: Path, degraded: bool
) -> None:
    if degraded:
        paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest = _oversize_review_case(
            tmp_path
        )
        preflight = _preflight_oversize(
            paths, copy_dir, copy_ledger, audit_dir, audit_ledger, digest
        )
    else:
        preflight, _copy, _audit, _ledger = _reviewed_case(tmp_path, critical=True)
    original_case = preflight.rejected.original.case
    two_line_case = original_case.model_copy(
        update={"source_url": "https://example.org/" + "g" * 110}
    )
    base = BytesIO()
    Image.new("RGB", (1152, 2048), "white").save(base, format="PNG")
    footer = render_exact_source_footer(base.getvalue(), two_line_case, mode="local")
    assert len(footer.source_url_lines) == 2
    with Image.open(BytesIO(footer.image_bytes)) as opened:
        citation = opened.convert("RGB")
    # The footer contract reserves through y=2007 for its second URL line.
    # A sentinel in that last row catches an overlay that starts too early.
    ImageDraw.Draw(citation).line((48, 2007, 1104, 2007), fill="#075a9e", width=1)
    stream = BytesIO()
    citation.save(stream, format="PNG")
    marked = _warning_overlay(stream.getvalue(), _notice_font_bytes(), notice=preflight.notice)
    with Image.open(BytesIO(marked)) as opened:
        actual = opened.convert("RGB")
    assert (
        ImageChops.difference(
            citation.crop((0, 1900, 1152, 2008)), actual.crop((0, 1900, 1152, 2008))
        ).getbbox()
        is None
    )
