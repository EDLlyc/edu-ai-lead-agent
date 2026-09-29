"""Exact local footer repair preserves the provider image and attribution identity."""

# ruff: noqa: RUF001 -- frozen Chinese attribution uses native punctuation.

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import app.news_infographic_local_main as local_main
import pytest
from app.application.services.news_infographic import run_local_batch
from app.application.services.news_infographic_footer import (
    DELIVERY_FOOTER_VERSION,
    FOOTER_TOP,
    FOOTER_VERSION,
    FooterRenderError,
    delivery_footer_text,
    render_delivery_footer_variants,
    render_exact_source_footer,
    validate_exact_source_footer_layout,
)
from app.domain.news_infographic import validate_package_snapshot
from app.infrastructure.news_infographic_local import write_frozen_input_bundle
from PIL import Image, ImageChops
from test_news_infographic import package_payload
from test_news_infographic_pipeline import _Models, _png, _reference

_REAL_SOURCE_URL = "http://www.moe.gov.cn/jyb_xwfb/gzdt_gzdt/s5987/202608/t20260804_1446039.html"


def test_footer_copy_and_url_size_have_distinct_local_and_delivery_versions() -> None:
    assert FOOTER_VERSION == "daily-news-infographic-footer-v2"
    assert DELIVERY_FOOTER_VERSION == "daily-news-infographic-footer-v5-no-link"


@pytest.mark.parametrize("mode", ["local", "test", "formal"])
def test_footer_removes_illustration_notice_but_keeps_mode_marker(
    mode: Literal["local", "test", "formal"],
) -> None:
    import app.application.services.news_infographic_footer as footer

    with patch.object(footer, "_draw_fitted", wraps=footer._draw_fitted) as draw_fitted:
        render_exact_source_footer(_png(), validate_package_snapshot(package_payload()), mode=mode)
    rendered_text = tuple(call.args[1] for call in draw_fitted.call_args_list)
    assert all(
        "场景为科普示意" not in line and "非新闻现场照片" not in line for line in rendered_text
    )
    if mode == "test":
        assert "【测试消息】" in rendered_text
    elif mode == "local":
        assert "本地样稿 · 未发布" in rendered_text
    else:
        assert "【测试消息】" not in rendered_text
        assert "本地样稿 · 未发布" not in rendered_text


def test_footer_preserves_all_pixels_above_boundary_and_exact_locked_url() -> None:
    case = validate_package_snapshot(package_payload())
    raw = _png()
    rendered = render_exact_source_footer(raw, case)
    assert "".join(rendered.source_url_lines) == case.source_url
    assert validate_exact_source_footer_layout(case) == rendered.source_url_lines
    assert rendered.image_sha256 == sha256(rendered.image_bytes).hexdigest()
    with Image.open(BytesIO(raw)) as original, Image.open(BytesIO(rendered.image_bytes)) as final:
        assert final.size == (1152, 2048)
        assert (
            ImageChops.difference(
                original.crop((0, 0, 1152, FOOTER_TOP)),
                final.crop((0, 0, 1152, FOOTER_TOP)),
            ).getbbox()
            is None
        )
        assert (
            ImageChops.difference(
                original.crop((0, FOOTER_TOP, 1152, 2048)),
                final.crop((0, FOOTER_TOP, 1152, 2048)),
            ).getbbox()
            is not None
        )


def test_footer_rejects_long_url_instead_of_truncating_or_shrinking() -> None:
    case = validate_package_snapshot(package_payload())
    long_case = case.model_copy(update={"source_url": "https://example.com/" + "W" * 155})
    with pytest.raises(FooterRenderError, match="does not fit"):
        render_exact_source_footer(_png(), long_case)
    with pytest.raises(FooterRenderError, match="does not fit"):
        validate_exact_source_footer_layout(long_case)
    # Delivered footers carry no link, so a long URL no longer blocks them.
    for mode in ("formal", "test"):
        assert validate_exact_source_footer_layout(long_case, mode=mode) == ()


@pytest.mark.parametrize("mode", ["formal", "test"])
def test_delivered_footer_shows_date_and_source_but_no_link(
    mode: Literal["formal", "test"],
) -> None:
    """Operator request 2026-09-29: 图片上不放链接 (the link stays in the Moments text)."""
    import app.application.services.news_infographic_footer as footer

    case = validate_package_snapshot(package_payload()).model_copy(
        update={"source_url": _REAL_SOURCE_URL}
    )
    raw = _png()
    local = render_exact_source_footer(raw, case)
    with patch.object(footer, "_draw_fitted", wraps=footer._draw_fitted) as draw_fitted:
        rendered = render_exact_source_footer(raw, case, mode=mode)
    drawn_text = tuple(call.args[1] for call in draw_fitted.call_args_list)
    assert f"新闻日期：{case.source_date.isoformat()}" in drawn_text
    assert f"新闻来源：{case.source_name}" in drawn_text
    assert not any("原文链接" in text or "http" in text for text in drawn_text)
    assert rendered.source_url_lines == ()
    assert local.source_url_lines == (_REAL_SOURCE_URL,)
    expected = delivery_footer_text(case, mode=mode)
    assert "".join(drawn_text) == expected
    with Image.open(BytesIO(raw)) as original, Image.open(BytesIO(rendered.image_bytes)) as image:
        assert (
            ImageChops.difference(
                original.crop((0, 0, 1152, FOOTER_TOP)), image.crop((0, 0, 1152, FOOTER_TOP))
            ).getbbox()
            is None
        )


@pytest.mark.asyncio
async def test_unrenderable_footer_stops_before_any_paid_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.application.services.news_infographic_footer as footer

    case = validate_package_snapshot(package_payload())
    monkeypatch.setattr(footer, "_FONT_PATH", tmp_path / "missing-font.ttc")
    models = _Models()
    run_dir = tmp_path / "fresh"
    summary = await run_local_batch(
        (case,), run_dir=run_dir, models=models, references=_reference()
    )
    outcome = summary.cases[0]
    assert outcome["generation"] == "blocked_preflight"
    assert outcome["footer"] == "failed"
    assert outcome["footer_reason_code"] == "exact_source_footer_unavailable"
    assert models.prompts == []
    assert models.image_requests == []
    assert list((run_dir / "private").glob("*.intent.json")) == []


@pytest.mark.asyncio
async def test_overlong_frozen_url_stops_before_image_intent(tmp_path: Path) -> None:
    case = validate_package_snapshot(package_payload()).model_copy(
        update={"source_url": "https://example.com/" + "W" * 155}
    )
    models = _Models()
    run_dir = tmp_path / "fresh"
    summary = await run_local_batch(
        (case,), run_dir=run_dir, models=models, references=_reference()
    )
    assert summary.cases[0]["generation"] == "blocked_preflight"
    assert models.image_requests == []
    assert not (run_dir / "private" / "01-image.intent.json").exists()


@pytest.mark.asyncio
async def test_offline_repair_creates_fresh_derived_run_without_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_main, "_PROJECT_ROOT", tmp_path)
    output_root = tmp_path / "output"
    output_root.mkdir()
    case = validate_package_snapshot(package_payload())
    input_dir = output_root / "input"
    input_dir.mkdir()
    bundle = input_dir / "input.json"
    write_frozen_input_bundle(bundle, (case,))
    prior = output_root / "prior"
    models = _Models()
    prior_summary = await run_local_batch(
        (case,), run_dir=prior, models=models, references=_reference()
    )
    assert len(models.image_requests) == 1
    original_image = prior / str(prior_summary.cases[0]["image"])
    original_bytes = original_image.read_bytes()
    prior_manifest_bytes = (prior / "manifest.json").read_bytes()
    monkeypatch.setattr(
        local_main,
        "local_infographic_models",
        lambda *_args: (_ for _ in ()).throw(AssertionError("no model construction")),
    )
    repaired = output_root / "repaired"
    args = argparse.Namespace(
        mode="repair-footer", input_bundle=bundle, prior_run=prior, output_dir=repaired
    )
    assert await local_main._run(args) == 0
    assert (prior / "manifest.json").read_bytes() == prior_manifest_bytes
    assert original_image.read_bytes() == original_bytes
    manifest = json.loads((repaired / "manifest.json").read_text(encoding="utf-8"))
    outcome = manifest["cases"][0]
    assert manifest["repair"]["model_calls"] == 0
    assert manifest["batch_accepted"] is False
    assert outcome["human_inspection"] == "pending"
    assert outcome["user_approval"] == "pending"
    assert outcome["footer"] == "passed"
    assert "".join(outcome["footer_source_url_lines"]) == case.source_url
    assert (repaired / str(outcome["image"])).read_bytes() == original_bytes
    derived = (repaired / str(outcome["derived_image"])).read_bytes()
    assert sha256(derived).hexdigest() == outcome["derived_image_sha256"]
    assert str(outcome["derived_image"]) in (repaired / "preview.html").read_text(encoding="utf-8")
    assert case.source_url in (repaired / "preview.html").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        await local_main._run(args)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    args.output_dir = elsewhere / "fresh"
    with pytest.raises(ValueError, match="fresh sibling"):
        await local_main._run(args)
    assert not args.output_dir.exists()


@pytest.mark.asyncio
async def test_offline_repair_rejects_checksum_path_and_input_tampering_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local_main, "_PROJECT_ROOT", tmp_path)
    output_root = tmp_path / "output"
    output_root.mkdir()
    case = validate_package_snapshot(package_payload())
    bundle = output_root / "input.json"
    write_frozen_input_bundle(bundle, (case,))
    prior = output_root / "prior"
    summary = await run_local_batch(
        (case,), run_dir=prior, models=_Models(), references=_reference()
    )
    manifest_path = prior / "manifest.json"
    quality_path = prior / "quality.json"
    original_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    original_quality = json.loads(quality_path.read_text(encoding="utf-8"))
    args = argparse.Namespace(
        mode="repair-footer",
        input_bundle=bundle,
        prior_run=prior,
        output_dir=output_root / "repaired",
    )
    image = prior / str(summary.cases[0]["image"])
    image.write_bytes(image.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        await local_main._run(args)
    assert not args.output_dir.exists()
    image.write_bytes(_png())
    original_manifest["cases"][0]["image"] = "images/../../untrusted.png"
    quality_path.write_text(json.dumps(original_manifest["cases"]), encoding="utf-8")
    manifest_path.write_text(json.dumps(original_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="image path"):
        await local_main._run(args)
    assert not args.output_dir.exists()
    original_manifest["cases"] = original_quality
    quality_path.write_text(json.dumps(original_quality), encoding="utf-8")
    manifest_path.write_text(json.dumps(original_manifest), encoding="utf-8")
    altered = case.model_dump(mode="json")
    altered["topic_title"] = "another accepted topic"
    bundle.write_text(
        json.dumps({"schema_version": "news-infographic-input-v1", "cases": [altered]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match"):
        await local_main._run(args)
    assert not args.output_dir.exists()


def test_send_gates_can_still_verify_posters_made_with_the_linked_v4_footer() -> None:
    case = validate_package_snapshot(package_payload()).model_copy(
        update={"source_url": _REAL_SOURCE_URL}
    )
    current, legacy = render_delivery_footer_variants(_png(), case)

    assert current.source_url_lines == ()
    assert "".join(legacy.source_url_lines) == _REAL_SOURCE_URL
    assert current.image_sha256 != legacy.image_sha256
