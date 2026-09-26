"""A frozen local poster keeps reviewed prose exact and fails closed."""

# ruff: noqa: RUF001 -- exact reviewed Chinese poster copy is intentional.

from __future__ import annotations

import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import app.application.services.news_infographic_text_overlay as overlay
import app.news_infographic_text_overlay_main as local_main
import pytest
from app.application.services.news_infographic import PosterCopy
from app.domain.news_infographic import validate_package_snapshot
from PIL import Image
from test_news_infographic import package_payload
from test_news_infographic_pipeline import _copy_payload, _png


def _reviewed_copy() -> PosterCopy:
    lines = overlay._REVIEWED_LINES
    return PosterCopy.model_validate(
        {
            "title": "".join(lines[1]),
            "news_summary": "".join(lines[2]),
            "news_claim_ids": ["claim-1-news", "claim-2-news", "claim-3-news"],
            "cards": [
                {
                    "kind": "science",
                    "heading": "".join(lines[3]),
                    "body": "".join(lines[4]),
                    "claim_ids": ["claim-2-news", "claim-3-news"],
                },
                {
                    "kind": "learning",
                    "heading": "".join(lines[5]),
                    "body": "".join(lines[6]),
                    "claim_ids": ["claim-3-news", "claim-7-opinion"],
                },
                {
                    "kind": "brand",
                    "heading": "".join(lines[7]),
                    "body": "".join(lines[8]),
                    "claim_ids": ["claim-4-brand", "claim-5-brand"],
                },
            ],
        }
    )


def test_reviewed_lines_are_pinned_to_the_exact_accepted_copy() -> None:
    copy = _reviewed_copy()
    assert overlay.poster_copy_fingerprint(copy) == overlay._REVIEWED_COPY_SHA256
    _, counts = overlay.preflight_text_overlay_layout(copy)
    assert counts == (1, 2, 3, 1, 5, 1, 4, 1, 5)
    assert all("".join(lines) for lines in overlay._REVIEWED_LINES)
    assert overlay._REVIEWED_LINES[1] == ("教育部启动科学教育", "做中学领航行动")
    assert "领航行动" in overlay._REVIEWED_LINES[2][1]
    assert overlay._REVIEWED_LINES[4][3].startswith("掌握科学方法，发展科学思维能力")
    assert overlay._REVIEWED_LINES[8][3] == "像科学家一样思考，"


def test_formal_generic_layout_does_not_use_historical_reviewed_line_breaks() -> None:
    copy = _reviewed_copy()
    local_font, local_counts = overlay.preflight_text_overlay_layout(copy)
    formal_font, formal_counts = overlay.preflight_text_overlay_layout(
        copy, use_reviewed_lines=False
    )
    assert local_font == formal_font
    assert local_counts == (1, 2, 3, 1, 5, 1, 4, 1, 5)
    assert formal_counts == (1, 2, 3, 1, 4, 1, 4, 1, 4)


def test_fourteen_cjk_character_heading_fits_one_line_at_approved_font_size() -> None:
    payload = _copy_payload()
    payload["cards"][0]["heading"] = "科" * 14
    copy = PosterCopy.model_validate(payload)
    _, counts = overlay.preflight_text_overlay_layout(copy, use_reviewed_lines=False)
    assert counts[3] == 1


def test_render_preserves_raw_art_outside_panels_and_records_exact_lines() -> None:
    case = validate_package_snapshot(package_payload())
    copy = PosterCopy.model_validate(_copy_payload())
    raw = _png()
    rendered = overlay.render_exact_text_overlay(raw, case, copy)
    expected = (
        "小赛洞察",
        copy.title,
        copy.news_summary,
        *(value for card in copy.cards for value in (card.heading, card.body)),
    )
    assert tuple("".join(lines) for lines in rendered.rendered_lines) == expected
    assert rendered.image_sha256 == sha256(rendered.image_bytes).hexdigest()
    assert rendered.image_bytes != raw
    with Image.open(BytesIO(raw)) as original, Image.open(BytesIO(rendered.image_bytes)) as image:
        assert image.size == (1152, 2048)
        assert image.format == "PNG"
        assert image.getpixel((800, 650)) == original.getpixel((800, 650))
        assert image.getpixel((300, 1900)) == original.getpixel((300, 1900))
        assert image.getpixel((100, 200)) != original.getpixel((100, 200))
        assert image.getpixel((1050, 300)) != original.getpixel((1050, 300))
        assert image.getpixel((1050, 800)) != original.getpixel((1050, 800))


def test_preflight_fails_on_long_copy_and_missing_font(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    copy = PosterCopy.model_validate(_copy_payload())
    too_long = copy.model_copy(update={"title": "长" * 32})
    with pytest.raises(overlay.TextOverlayError, match="line budget"):
        overlay.preflight_text_overlay_layout(too_long)
    monkeypatch.setattr(overlay, "_FONT_PATH", tmp_path / "missing.ttc")
    with pytest.raises(overlay.TextOverlayError, match="unavailable"):
        overlay.preflight_text_overlay_layout(copy)


def test_render_rejects_non_portrait_or_corrupt_raw_bytes() -> None:
    case = validate_package_snapshot(package_payload())
    copy = PosterCopy.model_validate(_copy_payload())
    with pytest.raises(overlay.TextOverlayError, match="format or geometry"):
        overlay.render_exact_text_overlay(_png((1024, 1024)), case, copy)
    with pytest.raises(overlay.TextOverlayError, match="decoded"):
        overlay.render_exact_text_overlay(b"not an image", case, copy)


def test_local_runner_writes_distinct_review_assets_without_provider_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    case = validate_package_snapshot(package_payload())
    copy = PosterCopy.model_validate(_copy_payload())
    raw = _png()
    monkeypatch.setattr(local_main, "read_frozen_input_bundle", lambda _path: (case,))
    monkeypatch.setattr(
        local_main,
        "_verified_prior_footer_artifacts",
        lambda _path, _case: (
            {
                "image_sha256": sha256(raw).hexdigest(),
                "copy": "reused_accepted",
                "copy_provenance": "prior_local_accepted_run",
            },
            {"copy": copy.model_dump(mode="json")},
            raw,
        ),
    )
    output_dir = tmp_path / "review"
    result = local_main.run_local_text_overlay(
        input_bundle=tmp_path / "input.json",
        prior_run=tmp_path / "prior",
        output_dir=output_dir,
        package_id=case.package_id,
    )
    assert result["send_ready"] is False
    assert result["model_calls"] == 0
    assert result["poster_ocr"] == "not_checked"
    assert result["visual_audit"] == "not_checked"
    assert result["input_fingerprint"] == case.fingerprint
    assert result["group_jpeg_bytes"] <= 2 * 1024 * 1024
    assert result["raw_image_sha256"] == sha256(raw).hexdigest()
    assert (
        result["group_jpeg_sha256"]
        == sha256((output_dir / "exact-group.jpg").read_bytes()).hexdigest()
    )
    assert "".join(result["footer_url_lines"]) == case.source_url
    assert json.loads((output_dir / "manifest.json").read_text(encoding="utf-8")) == result
    assert (
        len(
            {
                result[name]
                for name in (
                    "raw_image_sha256",
                    "composite_image_sha256",
                    "formal_footer_image_sha256",
                    "group_jpeg_sha256",
                )
            }
        )
        == 4
    )
    with Image.open(output_dir / "exact-group.jpg") as group:
        expected_phone = group.resize((390, 693), Image.Resampling.LANCZOS)
    expected_bytes = BytesIO()
    expected_phone.save(expected_bytes, format="JPEG", quality=93, subsampling=0)
    assert (output_dir / "phone-390.jpg").read_bytes() == expected_bytes.getvalue()
    assert result["phone_preview_sha256"] == sha256(expected_bytes.getvalue()).hexdigest()
    with Image.open(output_dir / "phone-390.jpg") as phone:
        assert phone.size == (390, 693)
    before = (output_dir / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        local_main.run_local_text_overlay(
            input_bundle=tmp_path / "input.json",
            prior_run=tmp_path / "prior",
            output_dir=output_dir,
            package_id=case.package_id,
        )
    assert (output_dir / "manifest.json").read_bytes() == before
    with pytest.raises(ValueError, match="matching frozen case"):
        local_main.run_local_text_overlay(
            input_bundle=tmp_path / "input.json",
            prior_run=tmp_path / "prior",
            output_dir=tmp_path / "wrong-package",
            package_id=uuid4(),
        )
    assert not (tmp_path / "wrong-package").exists()


@pytest.mark.parametrize(
    ("status", "provenance"),
    [("rejected", None), ("reused_accepted", "unverified_copy")],
)
def test_local_runner_rejects_unaccepted_or_unproven_copy_before_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str, provenance: str | None
) -> None:
    case = validate_package_snapshot(package_payload())
    copy = PosterCopy.model_validate(_copy_payload())
    raw = _png()
    monkeypatch.setattr(local_main, "read_frozen_input_bundle", lambda _path: (case,))
    monkeypatch.setattr(
        local_main,
        "_verified_prior_footer_artifacts",
        lambda _path, _case: (
            {
                "image_sha256": sha256(raw).hexdigest(),
                "copy": status,
                "copy_provenance": provenance,
            },
            {"copy": copy.model_dump(mode="json")},
            raw,
        ),
    )
    output_dir = tmp_path / "unaccepted-copy"
    with pytest.raises(ValueError, match="copy was not accepted"):
        local_main.run_local_text_overlay(
            input_bundle=tmp_path / "input.json",
            prior_run=tmp_path / "prior",
            output_dir=output_dir,
            package_id=case.package_id,
        )
    assert not output_dir.exists()
