"""One-case, local-only audit of the immutable WorldSkills group JPEG.

The default command is provider-free. ``--execute`` may call OCR and visual
judges, but never generates an image, writes a database, or sends to WeCom.
"""

# ruff: noqa: RUF001 -- Frozen Chinese fields and fsynced local intents.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Protocol

import httpx
from PIL import Image
from pydantic import SecretStr

from app.application.ports.image_generation import ImageReference
from app.application.ports.image_validation import (
    ImageQualityAuditRequest,
    ImageQualityAuditResult,
    ImageTextRecognitionResult,
    PosterRegionRecognitionRequest,
)
from app.application.services.news_infographic import (
    _RICH_WORLD_SKILLS_COPY_MD_SHA256,
    _RICH_WORLD_SKILLS_INPUT_FINGERPRINT,
    _RICH_WORLD_SKILLS_PACKAGE_ID,
    _RICH_WORLD_SKILLS_STYLE_SHA256,
    GEOMETRY,
    PosterCopy,
    build_reviewed_rich_worldskills_copy,
    validate_reviewed_rich_worldskills_copy,
)
from app.application.services.wecom_news_infographic import (
    _poster_ocr_regions,
    _poster_region_text_matches,
)
from app.core.config import Settings, get_settings
from app.domain.news_infographic import validate_input_bundle
from app.domain.value_objects import stable_key
from app.infrastructure.ai.image_validation import OpenAICompatibleImageQualityAuditor
from app.infrastructure.ai.zhipu import ZhipuImageTextRecognizer
from app.infrastructure.wecom.group_webhook import prepare_group_webhook_image
from app.news_infographic_local_main import _WORKSPACE_ROOT, _approved_references

AUDIT_VERSION = "daily-news-infographic-rich-exact-jpeg-audit-v1"
_RUN_NAME = "daily-news-infographic-rich-worldskills-20260925-first"
_PREFLIGHT_RUN_NAME = f"{_RUN_NAME}-exact-jpeg-preflight-v1"
_AUDIT_RUN_NAME = f"{_RUN_NAME}-exact-jpeg-audit-v1"
_IMAGE_PREFIX = "01-2e1b6d31-68c1-4f43-b77e-cd580e171595"
_HASHES = {
    "manifest.json": "6d14925e04b453c66910910e8ef07baedf5040bb4c06445ab558b23fe2b798b4",
    "quality.json": "79a8c7172cbac1f4d6698d8d8e51cfd7764586b5464299c7c0e41c81f71f43aa",
    "copy.json": "527d83583127d3e70cb34f4d2c2b857b2f7b58b901a433fac649e8ea7eac3d48",
    "evidence.json": "6df215e25fbdffde7471c8d88ca95046c672e0527ce41c1d4f5ad88a6d00498c",
    "private/01-image-request.json": (
        "c4e0e5eaf5662f918204f32a8ebf12e8d28dd2a24e9777685be06bd347db97ae"
    ),
    f"images/{_IMAGE_PREFIX}.png": (
        "36f0ed8970229951ff57bb51cf54b8ae6150ac7a18c5de8c8e4d97f0482172a8"
    ),
    f"images/{_IMAGE_PREFIX}-footer.png": (
        "8c43ff26b903172a48fe296bad5f6ab4fc4661d4bacc7832dd64aa8cdef037e8"
    ),
    f"images/{_IMAGE_PREFIX}-group.jpg": (
        "a7cbd0512725bea6140a36217b23127d6b66975392791db138b15e6098d4829e"
    ),
    f"images/{_IMAGE_PREFIX}-phone-390.png": (
        "202757842c2bdd0b329e2851d1196794686ba565983f34faaf9e9e90ed144f7e"
    ),
}
_INPUT_SHA256 = "a6f94d66427c2c8deaf383bdde97c77ecfe80d273175e588d2e4216a07981816"
_VISUAL_VERSION = "rich-worldskills-exact-group-jpeg-visual-v1"
_MAX_JSON_BYTES = 2_000_000
_MAX_JPEG_BYTES = 2 * 1024 * 1024


class ExactJpegAuditError(ValueError):
    """The selected artifact or audit execution cannot be trusted."""


class AuditModels(Protocol):
    async def recognize_poster_region(
        self, request: PosterRegionRecognitionRequest
    ) -> ImageTextRecognitionResult | None: ...

    async def audit_visual(
        self, request: ImageQualityAuditRequest
    ) -> ImageQualityAuditResult | None: ...


@dataclass(frozen=True, slots=True)
class AuditInput:
    image_bytes: bytes
    copy: PosterCopy
    footer_text: str
    image_sha256: str
    input_fingerprint: str


def _read_regular(path: Path, *, limit: int) -> bytes:
    if ".." in path.parts or any(part.is_symlink() for part in (path, *path.parents)):
        raise ExactJpegAuditError("audit input contains a symlink or traversal")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise ExactJpegAuditError("audit input is unavailable") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ExactJpegAuditError("audit input is not a bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read(limit + 1)
    finally:
        os.close(descriptor)


def _json(data: bytes) -> object:
    try:
        return json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExactJpegAuditError("audit JSON is invalid") from exc


def _one_record(value: object) -> dict[str, object]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ExactJpegAuditError("audit record is not one case")
    return value[0]


def preflight_existing(run_dir: Path, input_bundle: Path) -> AuditInput:
    """Verify frozen lineage and all image bytes before creating any audit intent."""
    if run_dir.name != _RUN_NAME or run_dir.is_symlink() or not run_dir.is_dir():
        raise ExactJpegAuditError("wrong or unsafe source run")
    input_bytes = _read_regular(input_bundle, limit=_MAX_JSON_BYTES)
    if sha256(input_bytes).hexdigest() != _INPUT_SHA256:
        raise ExactJpegAuditError("frozen input bundle SHA differs")
    cases = validate_input_bundle(_json(input_bytes))
    if len(cases) != 1:
        raise ExactJpegAuditError("audit requires one frozen case")
    case = cases[0]
    if (
        case.package_id != _RICH_WORLD_SKILLS_PACKAGE_ID
        or case.fingerprint != _RICH_WORLD_SKILLS_INPUT_FINGERPRINT
    ):
        raise ExactJpegAuditError("frozen case identity differs")
    checked: dict[str, bytes] = {}
    for name, expected in _HASHES.items():
        body = _read_regular(
            run_dir / name, limit=_MAX_JPEG_BYTES if name.endswith(".jpg") else 24 * 1024 * 1024
        )
        if expected and sha256(body).hexdigest() != expected:
            raise ExactJpegAuditError("immutable run artifact SHA differs")
        checked[name] = body
    manifest = _json(checked["manifest.json"])
    if (
        not isinstance(manifest, dict)
        or manifest.get("case_count") != 1
        or manifest.get("send_ready") is not False
    ):
        raise ExactJpegAuditError("source manifest state differs")
    record = _one_record(manifest.get("cases"))
    quality = _one_record(_json(checked["quality.json"]))
    evidence = _one_record(_json(checked["evidence.json"]))
    copy_record = _one_record(_json(checked["copy.json"]))
    request = _json(checked["private/01-image-request.json"])
    if not isinstance(request, dict):
        raise ExactJpegAuditError("frozen request is invalid")
    copy = PosterCopy.model_validate(copy_record.get("copy"))
    validate_reviewed_rich_worldskills_copy(case, copy)
    if copy != build_reviewed_rich_worldskills_copy(case) or request.get("copy") != copy.model_dump(
        mode="json"
    ):
        raise ExactJpegAuditError("copy/request lineage differs")
    projected = case.public_projection()
    for field in (
        "package_id",
        "draft_version_id",
        "event_version_id",
        "business_date",
        "source_date",
        "source_name",
        "source_url",
        "input_fingerprint",
    ):
        if record.get(field) != projected[field] or evidence.get(field) != projected[field]:
            raise ExactJpegAuditError("manifest/evidence lineage differs")
    for field in ("package_id", "input_fingerprint"):
        if request.get(field) != projected[field]:
            raise ExactJpegAuditError("request identity differs")
    if copy_record.get("package_id") != projected["package_id"]:
        raise ExactJpegAuditError("copy identity differs")
    if (
        record != quality
        or request.get("reviewed_copy_document_sha256") != _RICH_WORLD_SKILLS_COPY_MD_SHA256
        or manifest.get("reviewed_copy_document_sha256") != _RICH_WORLD_SKILLS_COPY_MD_SHA256
    ):
        raise ExactJpegAuditError("run quality or reviewed-copy SHA differs")
    refs = request.get("references")
    if (
        not isinstance(refs, list)
        or len(refs) != 2
        or not isinstance(refs[0], dict)
        or refs[0].get("sha256")
        != "471bf408e572a3e0a45ff801a831ba48f135616eceaf995d7413b4f910038623"
        or not isinstance(refs[1], dict)
        or refs[1].get("sha256") != _RICH_WORLD_SKILLS_STYLE_SHA256
    ):
        raise ExactJpegAuditError("style-reference identity differs")
    if record.get("group_image_sha256") != _HASHES[f"images/{_IMAGE_PREFIX}-group.jpg"]:
        raise ExactJpegAuditError("group JPEG manifest SHA differs")
    for key, sha_key in (
        ("image", "image_sha256"),
        ("derived_image", "derived_image_sha256"),
        ("group_image", "group_image_sha256"),
        ("phone_preview", "phone_preview_sha256"),
    ):
        image_name = record.get(key)
        if (
            not isinstance(image_name, str)
            or image_name not in checked
            or record.get(sha_key) != sha256(checked[image_name]).hexdigest()
        ):
            raise ExactJpegAuditError("image descriptor differs from exact bytes")
    if (
        record.get("footer_source_url_lines") != [case.source_url]
        or record.get("source_date") != case.source_date.isoformat()
        or record.get("source_name") != case.source_name
    ):
        raise ExactJpegAuditError("source footer identity differs")
    body = checked[str(record["group_image"])]
    if (
        record.get("group_image_byte_size") != len(body)
        or len(body) > _MAX_JPEG_BYTES
        or record.get("group_image_media_type") != "image/jpeg"
    ):
        raise ExactJpegAuditError("group JPEG size/media differs")
    with Image.open(BytesIO(body)) as opened:
        opened.load()
        if (
            opened.format != "JPEG"
            or opened.size != GEOMETRY
            or getattr(opened, "n_frames", 1) != 1
        ):
            raise ExactJpegAuditError("group JPEG raster differs")
    prepared = prepare_group_webhook_image(body, "image/jpeg", max_bytes=_MAX_JPEG_BYTES)
    if prepared.body != body or prepared.media_type != "image/jpeg":
        raise ExactJpegAuditError("group adapter would change audited bytes")
    footer_text = (
        f"新闻日期：{case.source_date.isoformat()}"
        f"新闻来源：{case.source_name}"
        f"原文链接：{case.source_url}"
    )
    return AuditInput(body, copy, footer_text, sha256(body).hexdigest(), case.fingerprint)


def _fresh_dir(path: Path, source: Path, *, execute: bool) -> None:
    expected_name = _AUDIT_RUN_NAME if execute else _PREFLIGHT_RUN_NAME
    if (
        path.parent != source.parent
        or path.name != expected_name
        or ".." in path.parts
        or any(part.is_symlink() for part in (path, *path.parents))
    ):
        raise ExactJpegAuditError("result must use the fixed fresh audit sibling")
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    (path / "private").mkdir(mode=0o700)


def _write_json(path: Path, value: object) -> None:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


async def audit_existing(
    *,
    run_dir: Path,
    input_bundle: Path,
    output_dir: Path,
    execute: bool = False,
    models: AuditModels | None = None,
    references: tuple[ImageReference, ...] = (),
) -> dict[str, object]:
    audited = preflight_existing(run_dir, input_bundle)
    if execute and models is None:
        raise ExactJpegAuditError("live audit models are unavailable")
    regions = _poster_ocr_regions(audited.image_bytes, audited.copy, audited.footer_text)
    if tuple(region.region_id for region in regions) != (
        "masthead",
        "science",
        "learning",
        "brand",
        "footer",
    ):
        raise ExactJpegAuditError("audit OCR region contract differs")
    _fresh_dir(output_dir, run_dir, execute=execute)
    summary: dict[str, object] = {
        "audit_version": AUDIT_VERSION,
        "source_image_sha256": audited.image_sha256,
        "input_fingerprint": audited.input_fingerprint,
        "case_count": 1,
        "preflight": "passed",
        "ocr": "not_checked",
        "visual": "not_checked",
        "human_phone_review": "pending",
        "send_ready": False,
        "provider_call_intents": 0,
    }
    if not execute:
        _write_json(output_dir / "summary.json", summary)
        return summary
    assert models is not None
    intents = 0
    results: list[dict[str, object]] = []
    for region in regions:
        fingerprint = stable_key(
            AUDIT_VERSION,
            audited.image_sha256,
            region.region_id,
            sha256(region.image_bytes).hexdigest(),
            region.expected_text,
        )
        _write_json(
            output_dir / "private" / f"{region.region_id}.intent.json",
            {
                "audit_version": AUDIT_VERSION,
                "image_sha256": audited.image_sha256,
                "region_id": region.region_id,
                "crop_sha256": sha256(region.image_bytes).hexdigest(),
                "expected_sha256": sha256(
                    "".join(region.expected_text.split()).encode()
                ).hexdigest(),
                "request_fingerprint": fingerprint,
            },
        )
        intents += 1
        summary["provider_call_intents"] = intents
        try:
            result = await models.recognize_poster_region(
                PosterRegionRecognitionRequest(
                    image_bytes=region.image_bytes,
                    media_type="image/jpeg",
                    region_id=region.region_id,
                    request_fingerprint=fingerprint,
                )
            )
        except Exception:
            summary["ocr"] = "result_unknown"
            break
        matched = _poster_region_text_matches(
            result, fingerprint=fingerprint, expected_text=region.expected_text
        )
        results.append(
            {"region_id": region.region_id, "matched": matched, "request_fingerprint": fingerprint}
        )
        if not matched:
            summary["ocr"] = "failed"
            break
    else:
        summary["ocr"] = "passed"
    _write_json(output_dir / "private" / "ocr-verdict.json", results)
    if summary["ocr"] == "passed":
        fingerprint = stable_key(AUDIT_VERSION, audited.image_sha256, _VISUAL_VERSION)
        _write_json(
            output_dir / "private" / "visual.intent.json",
            {
                "audit_version": AUDIT_VERSION,
                "image_sha256": audited.image_sha256,
                "rubric_version": _VISUAL_VERSION,
                "request_fingerprint": fingerprint,
            },
        )
        intents += 1
        summary["provider_call_intents"] = intents
        try:
            visual = await models.audit_visual(
                ImageQualityAuditRequest(
                    image_bytes=audited.image_bytes,
                    media_type="image/jpeg",
                    request_fingerprint=fingerprint,
                    references=references,
                    prompt_version="daily-news-infographic-rich-worldskills-prompt-v1",
                    rubric_version=_VISUAL_VERSION,
                    criteria=(
                        "Exact 1152x2048 three-card Chinese poster; no stray background text, "
                        "English slogan, invented numbers or unreadable characters.",
                        "Both hero mascots visibly carry clear uppercase AI chest marks; "
                        "the orange-blue mascot cap reads 赛先生 exactly.",
                        "Masthead, deck, all three cards and source/date/URL are legible "
                        "on the exact group JPEG at native resolution.",
                        "No decorative or illustrated text conflicts with the frozen copy; "
                        "no false government endorsement or fabricated venue signage.",
                    ),
                )
            )
        except Exception:
            summary["visual"] = "result_unknown"
        else:
            summary["visual"] = (
                "passed"
                if visual is not None
                and visual.request_fingerprint == fingerprint
                and visual.accepted
                and not visual.issue_codes
                else "rejected"
                if visual is not None and visual.request_fingerprint == fingerprint
                else "invalid_result_identity"
                if visual is not None
                else "unavailable"
            )
            if visual is not None:
                summary["visual_issue_codes"] = list(visual.issue_codes)
        _write_json(
            output_dir / "private" / "visual-verdict.json",
            {
                "status": summary["visual"],
                "request_fingerprint": fingerprint,
                "issue_codes": summary.get("visual_issue_codes", []),
            },
        )
    _write_json(output_dir / "summary.json", summary)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit one immutable rich WorldSkills group JPEG; never send"
    )
    parser.add_argument("--prior-run", type=Path, required=True)
    parser.add_argument("--input-bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--execute", action="store_true", help="explicitly allow bounded OCR/visual provider calls"
    )
    return parser


def _validate_cli_paths(
    *, run_dir: Path, input_bundle: Path, output_dir: Path, execute: bool
) -> None:
    """Keep a copied run or renamed output from bypassing the one-intent audit."""
    expected_run = _WORKSPACE_ROOT / "output" / _RUN_NAME
    expected_input = (
        _WORKSPACE_ROOT / "output/daily-news-infographic-skills-input-20260924/input.json"
    )
    expected_output = expected_run.parent / (_AUDIT_RUN_NAME if execute else _PREFLIGHT_RUN_NAME)
    if (
        run_dir.absolute() != expected_run
        or input_bundle.absolute() != expected_input
        or output_dir.absolute() != expected_output
    ):
        raise ExactJpegAuditError("audit CLI paths do not match the frozen local case")


async def _main() -> None:
    args = _parser().parse_args()
    _validate_cli_paths(
        run_dir=args.prior_run,
        input_bundle=args.input_bundle,
        output_dir=args.output_dir,
        execute=args.execute,
    )
    if not args.execute:
        summary = await audit_existing(
            run_dir=args.prior_run, input_bundle=args.input_bundle, output_dir=args.output_dir
        )
    else:
        settings: Settings = get_settings()
        if (
            not settings.image_ocr_enabled
            or not settings.image_quality_audit_enabled
            or settings.ai_platform_api_key is None
            or settings.ai_platform_base_url is None
        ):
            raise ExactJpegAuditError("OCR and visual audit must both be configured")
        # All immutable checks and reference SHA checks occur before opening the result.
        preflight_existing(args.prior_run, args.input_bundle)
        references = _approved_references(
            asset_root=_WORKSPACE_ROOT,
            exact_text_quality_trial=True,
            rich_worldskills_trial=True,
        )
        if len(references) != 2 or references[1].sha256 != _RICH_WORLD_SKILLS_STYLE_SHA256:
            raise ExactJpegAuditError("audit references differ from frozen request")
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            key = SecretStr(settings.ai_platform_api_key.get_secret_value())
            ocr = ZhipuImageTextRecognizer(
                client=client,
                base_url=settings.ai_platform_base_url,
                api_key=key,
                model=settings.image_ocr_model,
                connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                read_timeout_seconds=settings.image_ocr_timeout_seconds,
                total_timeout_seconds=settings.image_ocr_timeout_seconds,
                concurrency=1,
                max_attempts=1,
                max_input_bytes=settings.image_ocr_max_input_bytes,
                max_response_bytes=settings.image_ocr_max_response_bytes,
            )
            visual = OpenAICompatibleImageQualityAuditor(
                client=client,
                base_url=settings.ai_platform_base_url,
                api_key=key,
                model=settings.image_quality_audit_model,
                connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                read_timeout_seconds=settings.ai_read_timeout_seconds,
                total_timeout_seconds=settings.ai_total_timeout_seconds,
                concurrency=1,
                max_attempts=1,
                max_request_bytes=max(24 * 1024 * 1024, settings.image_max_request_bytes),
                max_response_bytes=1024 * 1024,
            )

            class Models:
                async def recognize_poster_region(
                    self, request: PosterRegionRecognitionRequest
                ) -> ImageTextRecognitionResult:
                    return await ocr.recognize_poster_region(request)

                async def audit_visual(
                    self, request: ImageQualityAuditRequest
                ) -> ImageQualityAuditResult:
                    return await visual.audit(request)

            summary = await audit_existing(
                run_dir=args.prior_run,
                input_bundle=args.input_bundle,
                output_dir=args.output_dir,
                execute=True,
                models=Models(),
                references=references,
            )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(_main())
