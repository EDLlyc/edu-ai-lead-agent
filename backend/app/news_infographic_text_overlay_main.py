"""Provider-free local prototype for exact approved text on one existing poster."""

from __future__ import annotations

import argparse
import json
import os
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image

from app.application.services.news_infographic import PosterCopy
from app.application.services.news_infographic_footer import (
    DELIVERY_FOOTER_VERSION,
    render_exact_source_footer,
)
from app.application.services.news_infographic_text_overlay import (
    OVERLAY_VERSION,
    poster_copy_fingerprint,
    preflight_text_overlay_layout,
    render_exact_text_overlay,
)
from app.application.services.wecom_news_infographic import prepare_infographic_group_jpeg
from app.infrastructure.news_infographic_local import read_frozen_input_bundle
from app.news_infographic_local_main import _verified_prior_footer_artifacts


def _exclusive_write(path: Path, body: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def run_local_text_overlay(
    *, input_bundle: Path, prior_run: Path, output_dir: Path, package_id: UUID
) -> dict[str, object]:
    """Validate input lineage before writing a fresh, explicitly non-sendable run."""
    cases = read_frozen_input_bundle(input_bundle)
    matches = tuple(case for case in cases if case.package_id == package_id)
    if len(matches) != 1:
        raise ValueError("text overlay prototype needs one matching frozen case")
    case = matches[0]
    prior, record, raw = _verified_prior_footer_artifacts(prior_run, case)
    if prior.get("copy") not in {"accepted", "reused_accepted"} or (
        prior.get("copy") == "reused_accepted"
        and prior.get("copy_provenance") != "prior_local_accepted_run"
    ):
        raise ValueError("prior poster copy was not accepted")
    copy = PosterCopy.model_validate(record["copy"])
    font_hash, expected_counts = preflight_text_overlay_layout(copy)
    rendered = render_exact_text_overlay(raw, case, copy)
    if rendered.font_sha256 != font_hash or rendered.line_counts != expected_counts:
        raise ValueError("poster text overlay differs from preflight")
    footer = render_exact_source_footer(rendered.image_bytes, case, mode="formal")
    exact_jpeg = prepare_infographic_group_jpeg(footer.image_bytes, max_bytes=2 * 1024 * 1024)
    with Image.open(BytesIO(exact_jpeg)) as opened:
        opened.load()
        preview = opened.resize((390, 693), Image.Resampling.LANCZOS)
    phone_buffer = BytesIO()
    preview.save(phone_buffer, format="JPEG", quality=93, subsampling=0)
    phone_bytes = phone_buffer.getvalue()
    raw_sha = sha256(raw).hexdigest()
    jpeg_sha = sha256(exact_jpeg).hexdigest()
    if len({raw_sha, rendered.image_sha256, footer.image_sha256, jpeg_sha}) != 4:
        raise ValueError("the raw, composite, footer and group assets must be distinct")
    if ".." in output_dir.parts or any(
        parent.is_symlink() for parent in (output_dir, *output_dir.parents)
    ):
        raise ValueError("prototype output path is unsafe")
    manifest: dict[str, object] = {
        "schema_version": OVERLAY_VERSION,
        "purpose": "provider_free_local_visual_review_only",
        "send_ready": False,
        "model_calls": 0,
        "package_id": str(case.package_id),
        "business_date": case.business_date.isoformat(),
        "source_date": case.source_date.isoformat(),
        "source_name": case.source_name,
        "source_url": case.source_url,
        "input_fingerprint": case.fingerprint,
        "approved_copy_sha256": poster_copy_fingerprint(copy),
        "raw_image_sha256": raw_sha,
        "composite_image_sha256": rendered.image_sha256,
        "formal_footer_image_sha256": footer.image_sha256,
        "group_jpeg_sha256": jpeg_sha,
        "phone_preview_sha256": sha256(phone_bytes).hexdigest(),
        "font_sha256": rendered.font_sha256,
        "footer_font_sha256": footer.font_sha256,
        "footer_version": DELIVERY_FOOTER_VERSION,
        "footer_url_lines": list(footer.source_url_lines),
        "line_counts": list(rendered.line_counts),
        "rendered_lines": [list(lines) for lines in rendered.rendered_lines],
        "group_jpeg_bytes": len(exact_jpeg),
        "poster_ocr": "not_checked",
        "visual_audit": "not_checked",
        "human_phone_review": "pending",
        "unapproved_decorative_text": "masked_by_local_panels_pending_visual_confirmation",
        "prior_run_image_sha256": prior["image_sha256"],
    }
    output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    _exclusive_write(output_dir / "composite.png", rendered.image_bytes)
    _exclusive_write(output_dir / "formal-footer.png", footer.image_bytes)
    _exclusive_write(output_dir / "exact-group.jpg", exact_jpeg)
    _exclusive_write(output_dir / "phone-390.jpg", phone_bytes)
    _exclusive_write(
        output_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"),
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Render one provider-free exact-text poster")
    parser.add_argument("--input-bundle", required=True, type=Path)
    parser.add_argument("--prior-run", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--package-id", required=True, type=UUID)
    args = parser.parse_args()
    manifest = run_local_text_overlay(
        input_bundle=args.input_bundle,
        prior_run=args.prior_run,
        output_dir=args.output_dir,
        package_id=args.package_id,
    )
    print(
        json.dumps(
            {
                "send_ready": False,
                "package_id": manifest["package_id"],
                "group_jpeg_sha256": manifest["group_jpeg_sha256"],
                "group_jpeg_bytes": manifest["group_jpeg_bytes"],
                "output_dir": str(args.output_dir),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
