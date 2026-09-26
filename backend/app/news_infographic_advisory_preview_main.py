"""One-case, local-only v12 concise advisory poster trial.

Dry-run validates frozen same-package inputs and assets without a provider.
Execution reserves one durable intent per paid stage; it never sends to WeCom,
writes a database row, or treats a negative copy review as an approval.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import stat
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import uuid4

import httpx
from PIL import Image

from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageReference,
    validate_image_generation_request_prompt,
)
from app.application.services.news_infographic import GEOMETRY, _safe_file, _validate_raster
from app.application.services.news_infographic_advisory import (
    ADVISORY_POLICY_VERSION,
    advisory_notice_font_sha256,
    build_advisory_audit_prompt,
    build_advisory_generation_prompt,
    build_advisory_image_prompt,
    build_advisory_rich_copy,
    render_advisory_notice,
)
from app.application.services.news_infographic_footer import (
    render_exact_source_footer,
    validate_exact_source_footer_layout,
)
from app.application.services.news_infographic_rich_copy import MomentsAuditVerdict
from app.application.services.wecom_infographic_quality import (
    ADVISORY_NOTICE_TEXT,
    ADVISORY_NOTICE_VERSION,
    normalize_advisory_warnings,
)
from app.application.services.wecom_news_infographic import prepare_infographic_group_jpeg
from app.core.config import get_settings
from app.core.errors import (
    ImageOutputValidationError,
    ImageProviderConfigurationError,
    ImageProviderQuotaError,
    ImageProviderRejectedError,
    ImageProviderTimeoutError,
    ProviderAuthenticationError,
    ProviderInputLimitError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.infrastructure.ai.news_infographic import LOCAL_INFOGRAPHIC_IMAGE_MODEL, LocalInfographicAI
from app.news_infographic_local_main import _WORKSPACE_ROOT, _approved_references
from app.news_infographic_moments_copy_trial_main import (
    CopyOnlyChatModel,
    TrialInputError,
    TrialPreflight,
    _checked_output_root,
    _write_exclusive_json,
    preflight_trial,
)

_LEDGER_DIR = _WORKSPACE_ROOT / "output" / "daily-news-infographic-advisory-v12-intents"
_TRIAL_VERSION = "daily-news-infographic-advisory-v12-local-preview-v1"
_MAX_GROUP_BYTES = 2 * 1024 * 1024
_MAX_PRIVATE_JSON_BYTES = 24_000
_IMAGE_DIAGNOSTIC_VERSION = "advisory-local-image-failure-v1"


def _safe_provider_image_failure(error: Exception) -> dict[str, object]:
    """Project only known exception classes and typed, sanitized metadata."""
    if isinstance(error, ImageOutputValidationError):
        reason = error.reason
        return {
            "version": _IMAGE_DIAGNOSTIC_VERSION,
            "category": "result_validation",
            "exception_class": "ImageOutputValidationError",
            "reason_code": (
                reason
                if type(reason) is str and reason in ImageOutputValidationError._SAFE_REASONS
                else "image_output_invalid"
            ),
        }
    known = (
        (ImageProviderRejectedError, "image_provider_rejected"),
        (ImageProviderTimeoutError, "image_provider_timeout"),
        (ImageProviderQuotaError, "image_provider_quota_exhausted"),
        (ImageProviderConfigurationError, "image_provider_not_configured"),
        (ProviderAuthenticationError, "provider_authentication_failed"),
        (ProviderRateLimitError, "provider_rate_limited"),
        (ProviderUnavailableError, "provider_unavailable"),
        (ProviderInputLimitError, "provider_input_limit"),
    )
    for exception_type, reason_code in known:
        if isinstance(error, exception_type):
            diagnostic: dict[str, object] = {
                "version": _IMAGE_DIAGNOSTIC_VERSION,
                "category": "provider_exception",
                "exception_class": exception_type.__name__,
                "reason_code": reason_code,
            }
            if isinstance(error, ImageProviderRejectedError):
                if type(error.http_status) is int and 100 <= error.http_status <= 599:
                    diagnostic["http_status"] = error.http_status
                if type(error.response_kind) is str and error.response_kind in {
                    "json",
                    "raster",
                    "other",
                }:
                    diagnostic["response_kind"] = error.response_kind
            return diagnostic
    return {
        "version": _IMAGE_DIAGNOSTIC_VERSION,
        "category": "provider_exception",
        "exception_class": "other_exception",
        "reason_code": "provider_outcome_unknown",
    }


class ChatModel(Protocol):
    async def complete_json(self, prompt: str) -> dict[str, object]: ...


class ImageModel(Protocol):
    image_model: str

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult: ...


@dataclass(frozen=True, slots=True)
class AdvisoryPreviewPreflight:
    frozen: TrialPreflight
    input_bundle: Path
    package_detail: Path
    copy_run_detail: Path
    references: tuple[ImageReference, ...]
    generation_prompt: str
    notice_font_sha256: str
    intent_key: str

    def safe_projection(self) -> dict[str, object]:
        return {
            "status": "advisory_preview_preflight_valid",
            "package_id": str(self.frozen.package_id),
            "input_fingerprint": self.frozen.case.fingerprint,
            "policy_version": ADVISORY_POLICY_VERSION,
            "trial_version": _TRIAL_VERSION,
            "reference_contract": "formal_v12_character_only",
            "notice": ADVISORY_NOTICE_TEXT,
            "reference_sha256": [item.sha256 for item in self.references],
            "generation_intents": 0,
            "audit_intents": 0,
            "image_intents": 0,
            "send_ready": False,
        }


def preflight_advisory_preview(
    *,
    input_bundle: Path,
    package_detail: Path,
    copy_run_detail: Path,
    references: tuple[ImageReference, ...],
) -> AdvisoryPreviewPreflight:
    """Perform all input, fixed-font and asset checks before any paid intent."""
    frozen = preflight_trial(
        input_bundle=input_bundle,
        package_detail=package_detail,
        copy_run_detail=copy_run_detail,
    )
    if (
        len(references) != 1
        or references[0].role != "approved-characters"
        or not references[0].image_bytes
        or sha256(references[0].image_bytes).hexdigest() != references[0].sha256
    ):
        raise TrialInputError("advisory preview needs the formal v12 character reference")
    validate_exact_source_footer_layout(frozen.case, mode="formal")
    font_sha256 = advisory_notice_font_sha256()
    prompt = build_advisory_generation_prompt(frozen.case, frozen.binding)
    key = sha256(
        f"{frozen.package_id}|{ADVISORY_POLICY_VERSION}|{_TRIAL_VERSION}".encode()
    ).hexdigest()
    return AdvisoryPreviewPreflight(
        frozen,
        input_bundle,
        package_detail,
        copy_run_detail,
        references,
        prompt,
        font_sha256,
        key,
    )


def _safe_ledger(path: Path) -> None:
    if ".." in path.parts or any(item.is_symlink() for item in (path, *path.parents)):
        raise TrialInputError("advisory intent ledger path is unsafe")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise TrialInputError("advisory intent ledger permissions are unsafe")


def _assert_intent_available(preflight: AdvisoryPreviewPreflight, ledger_dir: Path) -> None:
    """Read-only check so a dry-run never advertises an already spent trial."""
    if ".." in ledger_dir.parts or any(
        item.is_symlink() for item in (ledger_dir, *ledger_dir.parents)
    ):
        raise TrialInputError("advisory intent ledger path is unsafe")
    if ledger_dir.exists() and (
        not ledger_dir.is_dir() or stat.S_IMODE(ledger_dir.stat().st_mode) & 0o077
    ):
        raise TrialInputError("advisory intent ledger permissions are unsafe")
    for stage in ("generation", "audit", "image"):
        intent = ledger_dir / f"{preflight.intent_key}.{stage}.intent.json"
        if intent.exists() or intent.is_symlink():
            raise TrialInputError("package/policy/stage already has a reserved intent")


def _reserve_intent(
    preflight: AdvisoryPreviewPreflight,
    *,
    stage: str,
    request_fingerprint: str,
    model: str,
    ledger_dir: Path,
    output_dir: Path,
) -> None:
    if stage not in {"generation", "audit", "image"}:
        raise TrialInputError("unknown advisory stage")
    _safe_ledger(ledger_dir)
    try:
        _write_exclusive_json(
            ledger_dir / f"{preflight.intent_key}.{stage}.intent.json",
            {
                "state": "reserved",
                "stage": stage,
                "package_id": str(preflight.frozen.package_id),
                "input_fingerprint": preflight.frozen.case.fingerprint,
                "policy_version": ADVISORY_POLICY_VERSION,
                "trial_version": _TRIAL_VERSION,
                "request_fingerprint": request_fingerprint,
                "model": model,
                "output_name": output_dir.name,
            },
            private=True,
        )
    except FileExistsError as exc:
        raise TrialInputError("package/policy/stage already has a reserved intent") from exc


def _private_json(path: Path, payload: object) -> None:
    _write_exclusive_json(path, payload, private=True, max_bytes=_MAX_PRIVATE_JSON_BYTES)


def _summary(
    preflight: AdvisoryPreviewPreflight,
    *,
    status: str,
    generation_intents: int,
    audit_intents: int,
    image_intents: int,
    warning_codes: list[str] | None = None,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "package_id": str(preflight.frozen.package_id),
        "input_fingerprint": preflight.frozen.case.fingerprint,
        "policy_version": ADVISORY_POLICY_VERSION,
        "reference_contract": "formal_v12_character_only",
        "notice": ADVISORY_NOTICE_TEXT,
        "notice_version": ADVISORY_NOTICE_VERSION,
        "warning_codes": normalize_advisory_warnings(warning_codes or ()),
        "generation_intents": generation_intents,
        "audit_intents": audit_intents,
        "image_intents": image_intents,
        "copy_approved": False,
        "ocr": "not_checked",
        "visual_audit": "not_checked",
        "human_inspection": "pending",
        "send_ready": False,
        **(details or {}),
    }


def _write_summary(output_dir: Path, summary: dict[str, object]) -> dict[str, object]:
    _write_exclusive_json(output_dir / "summary.json", summary, private=False)
    return summary


def _fresh_preview_dirs(output_dir: Path) -> Path:
    _checked_output_root(output_dir)
    output_dir.mkdir(mode=0o700)
    private_dir = output_dir / "private"
    private_dir.mkdir(mode=0o700)
    return private_dir


def _new_images_dir(output_dir: Path) -> Path:
    images_dir = output_dir / "images"
    images_dir.mkdir(mode=0o700)
    return images_dir


async def execute_advisory_preview(
    preflight: AdvisoryPreviewPreflight,
    *,
    output_dir: Path,
    chat: ChatModel,
    image: ImageModel,
    chat_model_name: str,
    ledger_dir: Path = _LEDGER_DIR,
) -> dict[str, object]:
    """One generation, one independent review, then at most one image request.

    A malformed/negative review is retained as a warning, not a fabricated pass.
    An unusable four-field draft cannot form a bounded image request.
    """
    current = preflight_advisory_preview(
        input_bundle=preflight.input_bundle,
        package_detail=preflight.package_detail,
        copy_run_detail=preflight.copy_run_detail,
        references=preflight.references,
    )
    if current != preflight:
        raise TrialInputError("frozen advisory preview changed after preflight")
    if image.image_model != LOCAL_INFOGRAPHIC_IMAGE_MODEL:
        raise TrialInputError("advisory preview needs pinned Comfly image model")
    _assert_intent_available(preflight, ledger_dir)
    private_dir = _fresh_preview_dirs(output_dir)
    generation_fingerprint = sha256(preflight.generation_prompt.encode()).hexdigest()
    _private_json(private_dir / "generation-prompt.json", {"prompt": preflight.generation_prompt})
    _reserve_intent(
        preflight,
        stage="generation",
        request_fingerprint=generation_fingerprint,
        model=chat_model_name,
        ledger_dir=ledger_dir,
        output_dir=output_dir,
    )
    try:
        raw_copy = await chat.complete_json(preflight.generation_prompt)
    except Exception:
        return _write_summary(
            output_dir,
            _summary(
                preflight,
                status="generation_result_unknown",
                generation_intents=1,
                audit_intents=0,
                image_intents=0,
            ),
        )
    raw_response_sha256: str | None = None
    try:
        response_path = private_dir / "generation-response.json"
        _private_json(response_path, raw_copy)
        raw_response_sha256 = sha256(response_path.read_bytes()).hexdigest()
        rich = build_advisory_rich_copy(preflight.frozen.case, preflight.frozen.binding, raw_copy)
        if rich.raw_draft_sha256 != raw_response_sha256:
            raise TrialInputError("raw advisory response differs from recorded draft")
    except (TypeError, ValueError, RecursionError):
        return _write_summary(
            output_dir,
            _summary(
                preflight,
                status="rich_copy_unusable",
                generation_intents=1,
                audit_intents=0,
                image_intents=0,
                warning_codes=["copy_deterministic_rejected"],
                details=(
                    {"raw_response_sha256": raw_response_sha256}
                    if raw_response_sha256 is not None
                    else None
                ),
            ),
        )
    _private_json(private_dir / "rich-copy.json", rich.model_dump(mode="json"))
    copy_details: dict[str, object] = {
        "raw_draft_sha256": rich.raw_draft_sha256,
        "raw_response_sha256": raw_response_sha256,
        "normalized_exact_prefixes": list(rich.normalized_exact_prefixes),
    }
    warnings = {"layout_unverified"}
    if "copy_layout_warning" in rich.warning_codes:
        warnings.add("layout_overflow")
    if {"copy_schema_warning", "copy_binding_warning"} & set(rich.warning_codes):
        warnings.add("copy_deterministic_rejected")
    audit_prompt = build_advisory_audit_prompt(
        preflight.frozen.case, preflight.frozen.binding, rich
    )
    _private_json(private_dir / "audit-prompt.json", {"prompt": audit_prompt})
    _reserve_intent(
        preflight,
        stage="audit",
        request_fingerprint=sha256(audit_prompt.encode()).hexdigest(),
        model=chat_model_name,
        ledger_dir=ledger_dir,
        output_dir=output_dir,
    )
    try:
        raw_audit = await chat.complete_json(audit_prompt)
    except Exception:
        warnings.add("copy_audit_unavailable")
        audit_snapshot: dict[str, object] = {"status": "unavailable", "issues": []}
    else:
        try:
            _private_json(private_dir / "audit-response.json", raw_audit)
            verdict = MomentsAuditVerdict.model_validate(raw_audit)
        except (TypeError, ValueError, RecursionError):
            warnings.add("copy_audit_schema_invalid")
            audit_snapshot = {"status": "schema_invalid", "issues": []}
        else:
            audit_snapshot = verdict.model_dump(mode="json")
            if not verdict.accepted:
                warnings.add("copy_audit_rejected")
            if not verdict.brand_bound:
                warnings.add("brand_unverified")
    _private_json(private_dir / "audit-snapshot.json", audit_snapshot)
    try:
        prompt = validate_image_generation_request_prompt(
            ImageGenerationRequest(
                run_id=uuid4(),
                draft_version_id=preflight.frozen.case.draft_version_id,
                prompt=build_advisory_image_prompt(preflight.frozen.case, rich),
                request_fingerprint="advisory-local-prompt-preflight",
                unrestricted_prompt_length=True,
            )
        )
    except (TypeError, ValueError):
        return _write_summary(
            output_dir,
            _summary(
                preflight,
                status="image_prompt_unusable",
                generation_intents=1,
                audit_intents=1,
                image_intents=0,
                warning_codes=list(warnings),
                details=copy_details,
            ),
        )
    request_fingerprint = sha256(
        json.dumps(
            {
                "policy_version": ADVISORY_POLICY_VERSION,
                "trial_version": _TRIAL_VERSION,
                "package_id": str(preflight.frozen.package_id),
                "input_fingerprint": preflight.frozen.case.fingerprint,
                "rich_copy": rich.model_dump(mode="json"),
                "prompt": prompt,
                "references": [item.sha256 for item in preflight.references],
                "notice_font": preflight.notice_font_sha256,
                "model": image.image_model,
                "geometry": GEOMETRY,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    request = ImageGenerationRequest(
        run_id=uuid4(),
        draft_version_id=preflight.frozen.case.draft_version_id,
        prompt=prompt,
        request_fingerprint=request_fingerprint,
        provider_request_fingerprint=request_fingerprint,
        references=preflight.references,
        reference_mode="multi",
        unrestricted_prompt_length=True,
    )
    _private_json(
        private_dir / "image-request.json",
        {
            "request_fingerprint": request_fingerprint,
            "prompt": prompt,
            "references": [
                {"role": item.role, "sha256": item.sha256} for item in preflight.references
            ],
            "model": image.image_model,
        },
    )
    _reserve_intent(
        preflight,
        stage="image",
        request_fingerprint=request_fingerprint,
        model=image.image_model,
        ledger_dir=ledger_dir,
        output_dir=output_dir,
    )
    details = dict(copy_details)
    failure_phase = "provider_call"
    failure_step = "provider_outcome_unknown"
    try:
        result = await image.generate(request)
        failure_phase = "result_validation"
        failure_step = "result_identity_invalid"
        if (result.provider, result.model, result.request_fingerprint, result.attempts) != (
            "comfly",
            image.image_model,
            request_fingerprint,
            1,
        ):
            raise ValueError("image result differs from reserved request")
        failure_step = "raster_invalid"
        extension, raw = _validate_raster(result)
        failure_phase = "derivative"
        failure_step = "notice_font_changed"
        if advisory_notice_font_sha256() != preflight.notice_font_sha256:
            raise ValueError("advisory notice font changed after image intent")
        failure_step = "raw_write_failed"
        images_dir = _new_images_dir(output_dir)
        _safe_file(images_dir / f"raw.{extension}", raw, private=True)
        details["raw_image_sha256"] = sha256(raw).hexdigest()
        failure_step = "notice_render_failed"
        notice_png = render_advisory_notice(raw)
        _safe_file(images_dir / "notice.png", notice_png, private=True)
        failure_step = "footer_render_failed"
        footer = render_exact_source_footer(notice_png, preflight.frozen.case, mode="formal")
        if "".join(footer.source_url_lines) != preflight.frozen.case.source_url:
            raise ValueError("exact frozen source footer differs")
        _safe_file(images_dir / "footer.png", footer.image_bytes, private=True)
        failure_step = "group_jpeg_failed"
        group = prepare_infographic_group_jpeg(footer.image_bytes, max_bytes=_MAX_GROUP_BYTES)
        if not group or len(group) > _MAX_GROUP_BYTES:
            raise ValueError("advisory JPEG exceeds group bound")
        with Image.open(BytesIO(group)) as opened:
            opened.load()
            if opened.format != "JPEG" or opened.size != GEOMETRY:
                raise ValueError("advisory JPEG has wrong type or geometry")
            phone = opened.convert("RGB").resize(
                (390, round(390 * GEOMETRY[1] / GEOMETRY[0])), Image.Resampling.LANCZOS
            )
        failure_step = "preview_write_failed"
        _safe_file(images_dir / "group.jpg", group, private=True)
        stream = BytesIO()
        phone.save(stream, format="PNG")
        _safe_file(images_dir / "phone-390.png", stream.getvalue(), private=True)
        details.update(
            {
                "group_image": "images/group.jpg",
                "group_image_sha256": sha256(group).hexdigest(),
                "group_image_byte_size": len(group),
                "phone_preview": "images/phone-390.png",
                "phone_preview_sha256": sha256(stream.getvalue()).hexdigest(),
                "footer_image_sha256": footer.image_sha256,
            }
        )
        status = "generated_local_preview_pending_human_inspection"
    except Exception as error:
        # An ambiguous transport result and an invalid post-response derivative
        # are both non-replayable under the same package/policy intent. The
        # allowlisted diagnostic distinguishes them without exception text.
        status = "image_result_unknown_or_quality_failed"
        if failure_phase == "provider_call":
            details["image_failure"] = _safe_provider_image_failure(error)
        else:
            details["image_failure"] = {
                "version": _IMAGE_DIAGNOSTIC_VERSION,
                "category": failure_phase,
                "reason_code": failure_step,
            }
    warnings.update({"body_ocr_unavailable", "footer_ocr_unavailable", "visual_unavailable"})
    return _write_summary(
        output_dir,
        _summary(
            preflight,
            status=status,
            generation_intents=1,
            audit_intents=1,
            image_intents=1,
            warning_codes=list(warnings),
            details=details,
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local-only one-case v12 advisory poster")
    parser.add_argument("--input-bundle", required=True, type=Path)
    parser.add_argument("--package-detail", required=True, type=Path)
    parser.add_argument("--copy-run-detail", required=True, type=Path)
    parser.add_argument("--approved-asset-root", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--execute", action="store_true")
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    try:
        references = _approved_references(
            asset_root=args.approved_asset_root,
            exact_text_quality_trial=True,
        )
        preflight = preflight_advisory_preview(
            input_bundle=args.input_bundle,
            package_detail=args.package_detail,
            copy_run_detail=args.copy_run_detail,
            references=references,
        )
        _assert_intent_available(preflight, _LEDGER_DIR)
        if not args.execute:
            print(json.dumps(preflight.safe_projection(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.output_dir is None:
            raise TrialInputError("--execute requires a fresh --output-dir")
        _checked_output_root(args.output_dir)
        settings = get_settings()
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            chat = CopyOnlyChatModel(settings, client)
            image = LocalInfographicAI(settings, client)
            summary = await execute_advisory_preview(
                preflight,
                output_dir=args.output_dir,
                chat=chat,
                image=image,
                chat_model_name=settings.ai_chat_model,
            )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary["status"] == "generated_local_preview_pending_human_inspection" else 1
    except (OSError, TypeError, ValueError, RuntimeError):
        print(
            json.dumps(
                {
                    "status": "blocked_local_advisory_preview",
                    "reason_code": "invalid_input_or_reserved_intent",
                    "send_ready": False,
                },
                sort_keys=True,
            )
        )
        return 2


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
