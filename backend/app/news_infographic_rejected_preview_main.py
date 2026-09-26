"""One-shot, unpublished image preview of a reviewed but rejected local draft.

The existing deterministic copy rejection remains authoritative. This route
does not produce an approved proposal, delivery artifact or WeCom job.
"""

# ruff: noqa: RUF001 -- visible Chinese caution and prompt text are intentional.

from __future__ import annotations

import argparse
import asyncio
import json
import stat
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageReference,
    validate_image_generation_request_prompt,
)
from app.application.services.news_infographic import GEOMETRY, _safe_file, _validate_raster
from app.application.services.news_infographic_footer import (
    render_exact_source_footer,
    validate_exact_source_footer_layout,
)
from app.application.services.news_infographic_rich_copy import build_moments_rich_draft_plan
from app.application.services.wecom_news_infographic import prepare_infographic_group_jpeg
from app.core.config import get_settings
from app.infrastructure.ai.news_infographic import (
    LOCAL_INFOGRAPHIC_IMAGE_MODEL,
    LocalInfographicAI,
)
from app.news_infographic_local_main import _WORKSPACE_ROOT, _approved_references
from app.news_infographic_moments_copy_trial_main import (
    TrialInputError,
    _checked_output_root,
    _read_object,
    _safe_existing_regular_file,
    _write_exclusive_json,
)
from app.news_infographic_moments_image_trial_main import _validated_references
from app.news_infographic_moments_rejected_audit_main import (
    RejectedDraftAuditVerdict,
    RejectedDraftPreflight,
    _checked_private_dir,
    preflight_rejected_audit,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_COPY_LEDGER = _PROJECT_ROOT / "output" / "daily-news-infographic-moments-copy-intents"
_AUDIT_LEDGER = _PROJECT_ROOT / "output" / "daily-news-infographic-rejected-copy-audit-intents"
_IMAGE_LEDGER = _PROJECT_ROOT / "output" / "daily-news-infographic-rejected-preview-image-intents"
PREVIEW_VERSION = "daily-news-infographic-rejected-review-preview-v1"
PROMPT_VERSION = "daily-news-infographic-rejected-review-preview-prompt-v1"
NOTICE_VERSION = "daily-news-infographic-rejected-review-notice-v1"
_FONT_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
_NOTICE = "本地预览 · 内容待核实 · 未发布"
_INVALID_AUDIT_NOTICE = "审核格式异常 · 内容待核实 · 未发布"
_NOTICE_DETAIL = "下方为规则未通过的候选文案；原新闻链接仅供核对"
_MAX_PROMPT_CHARS = 9000
_MAX_GROUP_BYTES = 2 * 1024 * 1024


class ImageModel(Protocol):
    image_model: str

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult: ...


class PreviewOnlyOversizeReview(BaseModel):
    """Narrow observation of a 701-1024-char rationale, never a valid audit verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["daily-news-infographic-rejected-copy-review-v1"]
    facts_supported: StrictBool
    brand_aligned: StrictBool
    child_inquiry_specific: StrictBool
    copy_quality_sufficient: StrictBool
    no_unsupported_assertions: StrictBool
    reviewer_supports_candidate: StrictBool
    issues: tuple[
        Literal[
            "number_or_unit_restatement",
            "unsupported_distance_time_inference",
            "other_unbound_fact",
            "unbound_brand_claim",
            "generic_child_inquiry",
            "repetitive_or_thin_copy",
            "other_quality_issue",
        ],
        ...,
    ] = Field(max_length=12)
    rationale: str = Field(min_length=701, max_length=1024)

    @model_validator(mode="after")
    def check_consistency(self) -> PreviewOnlyOversizeReview:
        flags = (
            self.facts_supported,
            self.brand_aligned,
            self.child_inquiry_specific,
            self.copy_quality_sufficient,
            self.no_unsupported_assertions,
        )
        if self.reviewer_supports_candidate != (all(flags) and not self.issues):
            raise ValueError("oversize observation is internally inconsistent")
        if not self.reviewer_supports_candidate and not self.issues:
            raise ValueError("oversize observation rejection needs a closed issue")
        return self


ReviewState = Literal["typed_complete", "invalid_rationale_too_long"]


@dataclass(frozen=True, slots=True)
class RejectedPreviewPreflight:
    rejected: RejectedDraftPreflight
    audit_dir: Path
    audit_ledger_dir: Path
    audit_response_sha256: str
    verdict: RejectedDraftAuditVerdict | PreviewOnlyOversizeReview
    review_state: ReviewState
    references: tuple[ImageReference, ...]
    font_sha256: str
    image_prompt: str
    image_key: str

    @property
    def notice(self) -> str:
        return (
            _INVALID_AUDIT_NOTICE if self.review_state == "invalid_rationale_too_long" else _NOTICE
        )

    def safe_projection(self) -> dict[str, object]:
        return {
            "status": "rejected_review_preview_preflight_valid",
            "package_id": str(self.rejected.original.package_id),
            "source_copy_status": "generation_copy_rejected",
            "review_state": self.review_state,
            "reviewer_supports_candidate": (
                self.verdict.reviewer_supports_candidate
                if self.review_state == "typed_complete"
                else None
            ),
            "reviewer_issue_codes": (
                list(self.verdict.issues) if self.review_state == "typed_complete" else []
            ),
            "notice": self.notice,
            "image_intents": 0,
            "generation_calls": 0,
            "audit_calls": 0,
            "send_ready": False,
        }


def _notice_font_bytes() -> bytes:
    if _FONT_PATH.is_symlink() or not _FONT_PATH.is_file():
        raise TrialInputError("preview caution font is unavailable")
    data = _FONT_PATH.read_bytes()
    if not data or len(data) > 32 * 1024 * 1024:
        raise TrialInputError("preview caution font is invalid")
    return data


def _draw_caution(image: Image.Image, font_data: bytes, *, notice: str) -> None:
    """Make review-only status independent of the image model's text fidelity."""
    if image.size != GEOMETRY:
        raise TrialInputError("preview notice geometry differs")
    large = ImageFont.truetype(BytesIO(font_data), 45)
    medium = ImageFont.truetype(BytesIO(font_data), 29)
    # The local source footer permits a second URL line down to y=2007.
    # Only replace its note row; never erase any pixels reserved for citation.
    small = ImageFont.truetype(BytesIO(font_data), 20)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1151, 148), fill="#a41329")
    title_box = draw.textbbox((48, 20), notice, font=large, anchor="lt")
    detail_box = draw.textbbox((48, 86), _NOTICE_DETAIL, font=medium, anchor="lt")
    foot_box = draw.textbbox((48, 2010), notice, font=small, anchor="lt")
    if title_box[2] > 1104 or title_box[3] > 76:
        raise TrialInputError("preview caution heading would be clipped")
    if detail_box[2] > 1104 or detail_box[3] > 139:
        raise TrialInputError("preview caution explanation would be clipped")
    if foot_box[2] > 1104 or foot_box[3] > 2040:
        raise TrialInputError("preview caution footer would be clipped")
    draw.text((48, 20), notice, font=large, anchor="lt", fill="white")
    draw.text((48, 86), _NOTICE_DETAIL, font=medium, anchor="lt", fill="white")
    # Replace only the generic local-sample note, retaining the exact source,
    # date and complete URL drawn by render_exact_source_footer.
    draw.rectangle((42, 2008, 1108, 2041), fill="white")
    draw.text((48, 2010), notice, font=small, anchor="lt", fill="#a41329")


def _warning_overlay(footer_png: bytes, font_data: bytes, *, notice: str) -> bytes:
    with Image.open(BytesIO(footer_png)) as opened:
        if opened.format != "PNG" or opened.size != GEOMETRY:
            raise TrialInputError("preview footer raster differs")
        opened.load()
        image = opened.convert("RGB")
    _draw_caution(image, font_data, notice=notice)
    stream = BytesIO()
    image.save(stream, format="PNG", optimize=False)
    return stream.getvalue()


def _preview_prompt(rejected: RejectedDraftPreflight) -> str:
    original = rejected.original
    plan = build_moments_rich_draft_plan(original.case, original.binding, original.seed)
    draft = rejected.draft
    prompt = "\n".join(
        (
            PROMPT_VERSION,
            "只制作一张1152×2048的内部候选图，非新闻成品。参考图一只用于赛先生/小赛的角色形象；参考图二只用于蓝白明亮版式。不要复制参考图事实。",
            "明亮蓝白的儿童新闻长图，上部留警示横条空间，中段为本条新闻相关象征性插画，下面依次为蓝、绿、紫三张宽卡。赛先生佩戴橙蓝头盔，小赛为白蓝机器人猫头鹰；二者胸前白色大写AI清晰。",
            "以下编辑文字来自已被规则拒绝的候选稿。所有解释、提问和教学示例均在卡片内冠以【待核实】；不能把数字换算、推论或假设冒充原新闻事实。不要自行增减数字、结论、来源或品牌承诺。",
            "顶部须留出y0–148供程序叠加醒目的待核实横条；底部y1858–2048留白供程序叠加真实来源与未发布标识。模型不要画来源、日期、URL或新的标语。",
            "栏目：小赛洞察",
            f"标题：{plan.title}",
            f"导语：【待核实解读】{draft.top}",
            f"蓝卡标题：{plan.news_heading}",
            f"蓝卡已绑定新闻原句（照录）：{plan.fact.text}",
            f"蓝卡候选解读：【待核实】{draft.news}",
            f"绿卡标题：{plan.child_heading}",
            f"绿卡候选探究：【待核实】{plan.child_frame}{draft.child}",
            f"紫卡标题：{plan.brand_heading}",
            f"紫卡已绑定品牌原句（照录）：{plan.brand.text}",
            f"紫卡候选示例：【待核实】{draft.brand}",
            "不得在画面其他地方重述这些候选说法。所有中文应完整清楚；实际生成像素仍需人工核对，模型成功不代表事实或文字通过。",
        )
    )
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise TrialInputError("review-only preview prompt exceeds bound")
    return prompt


def _read_preview_observation(
    raw: object,
) -> tuple[RejectedDraftAuditVerdict | PreviewOnlyOversizeReview, ReviewState]:
    """Accept only a complete verdict or the single known rationale-length miss."""
    try:
        return RejectedDraftAuditVerdict.model_validate(raw), "typed_complete"
    except ValidationError as error:
        failures = error.errors(include_input=False, include_url=False)
        if (
            len(failures) != 1
            or failures[0].get("loc") != ("rationale",)
            or failures[0].get("type") != "string_too_long"
        ):
            raise TrialInputError("observational review has another schema failure") from error
    try:
        return PreviewOnlyOversizeReview.model_validate(raw), "invalid_rationale_too_long"
    except ValidationError as exc:
        raise TrialInputError("oversize observational review is otherwise invalid") from exc


def preflight_rejected_preview(
    *,
    input_bundle: Path,
    package_detail: Path,
    copy_run_detail: Path,
    source_copy_dir: Path,
    expected_response_sha256: str,
    audit_dir: Path,
    expected_audit_response_sha256: str,
    references: tuple[ImageReference, ...],
    copy_ledger_dir: Path = _COPY_LEDGER,
    audit_ledger_dir: Path = _AUDIT_LEDGER,
) -> RejectedPreviewPreflight:
    """Recheck immutable rejected copy and typed observation without a provider."""
    rejected = preflight_rejected_audit(
        input_bundle=input_bundle,
        package_detail=package_detail,
        copy_run_detail=copy_run_detail,
        source_copy_dir=source_copy_dir,
        expected_response_sha256=expected_response_sha256,
        copy_ledger_dir=copy_ledger_dir,
    )
    _checked_private_dir(audit_dir)
    _checked_private_dir(audit_dir / "private")
    _checked_private_dir(audit_ledger_dir)
    _validated_references(references)
    validate_exact_source_footer_layout(rejected.original.case, mode="local")
    font_data = _notice_font_bytes()
    audit_bytes = _safe_existing_regular_file(audit_dir / "private" / "audit-response.json")
    audit_hash = sha256(audit_bytes).hexdigest()
    if len(expected_audit_response_sha256) != 64 or audit_hash != expected_audit_response_sha256:
        raise TrialInputError("saved observational review differs from expected digest")
    try:
        raw_verdict = json.loads(audit_bytes)
    except (ValueError, TypeError) as exc:
        raise TrialInputError("observational review response is not JSON") from exc
    verdict, review_state = _read_preview_observation(raw_verdict)
    notice = _INVALID_AUDIT_NOTICE if review_state == "invalid_rationale_too_long" else _NOTICE
    _draw_caution(Image.new("RGB", GEOMETRY, "white"), font_data, notice=notice)
    saved_verdict_path = audit_dir / "private" / "audit-verdict.json"
    if review_state == "typed_complete":
        if verdict.model_dump(mode="json") != _read_object(saved_verdict_path):
            raise TrialInputError("observational review verdict differs from saved response")
    elif saved_verdict_path.exists() or saved_verdict_path.is_symlink():
        raise TrialInputError("invalid observational review was mislabeled as a verdict")
    summary = _read_object(audit_dir / "summary.json")
    expected_status = (
        "observational_audit_complete"
        if review_state == "typed_complete"
        else "observational_audit_schema_invalid"
    )
    expected_support = (
        verdict.reviewer_supports_candidate if review_state == "typed_complete" else None
    )
    expected_codes = list(verdict.issues) if review_state == "typed_complete" else []
    if (
        summary.get("status") != expected_status
        or summary.get("package_id") != str(rejected.original.package_id)
        or summary.get("input_fingerprint") != rejected.original.case.fingerprint
        or summary.get("source_copy_status") != "generation_copy_rejected"
        or summary.get("deterministic_rejection_code") != rejected.rejection_code
        or summary.get("audit_intents") != 1
        or summary.get("reviewer_supports_candidate") is not expected_support
        or summary.get("reviewer_issue_codes") != expected_codes
        or summary.get("production_effect") != "none_observational_only"
        or summary.get("generation_calls") != 0
        or summary.get("image_intents") != 0
        or summary.get("send_ready") is not False
    ):
        raise TrialInputError("observational review summary is not the same completed case")
    local_intent = _read_object(audit_dir / "private" / "audit.intent.json")
    global_intent = _read_object(audit_ledger_dir / f"{rejected.audit_key}.intent.json")
    if (
        local_intent.get("stage") != "observational-rejected-copy-audit"
        or local_intent.get("state") != "reserved"
        or local_intent.get("audit_key") != rejected.audit_key
        or local_intent.get("source_response_sha256") != rejected.response_sha256
        or global_intent.get("stage") != "observational-rejected-copy-audit"
        or global_intent.get("state") != "reserved"
        or global_intent.get("package_id") != str(rejected.original.package_id)
        or global_intent.get("source_response_sha256") != rejected.response_sha256
        or global_intent.get("input_fingerprint") != rejected.original.case.fingerprint
        or global_intent.get("output_name") != audit_dir.name
        or global_intent.get("audit_prompt_sha256")
        != sha256(rejected.audit_prompt.encode("utf-8")).hexdigest()
        or _read_object(audit_dir / "private" / "audit-prompt.json").get("prompt")
        != rejected.audit_prompt
    ):
        raise TrialInputError("observational review intent differs from source")
    prompt = _preview_prompt(rejected)
    image_key = sha256(
        f"{PREVIEW_VERSION}|{rejected.original.package_id}|{rejected.original.intent_key}".encode()
    ).hexdigest()
    return RejectedPreviewPreflight(
        rejected,
        audit_dir,
        audit_ledger_dir,
        audit_hash,
        verdict,
        review_state,
        references,
        sha256(font_data).hexdigest(),
        prompt,
        image_key,
    )


def _reserve_image_intent(
    preflight: RejectedPreviewPreflight,
    *,
    ledger_dir: Path,
    output_dir: Path,
    request: ImageGenerationRequest,
) -> None:
    if ".." in ledger_dir.parts:
        raise TrialInputError("review preview ledger contains parent traversal")
    current = ledger_dir
    while current != current.parent:
        if current.is_symlink():
            raise TrialInputError("review preview ledger contains a symlink")
        current = current.parent
    ledger_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(ledger_dir.stat().st_mode) & 0o077:
        raise TrialInputError("review preview ledger permissions are too broad")
    _write_exclusive_json(
        ledger_dir / f"{preflight.image_key}.intent.json",
        {
            "stage": "rejected-review-image-preview",
            "state": "reserved",
            "package_id": str(preflight.rejected.original.package_id),
            "policy_version": PREVIEW_VERSION,
            "source_response_sha256": preflight.rejected.response_sha256,
            "audit_response_sha256": preflight.audit_response_sha256,
            "request_fingerprint": request.request_fingerprint,
            "model": LOCAL_INFOGRAPHIC_IMAGE_MODEL,
            "reference_sha256": [item.sha256 for item in preflight.references],
            "font_sha256": preflight.font_sha256,
            "output_name": output_dir.name,
        },
        private=True,
    )


def _safe_summary(
    preflight: RejectedPreviewPreflight, *, image_status: str, image_intents: int
) -> dict[str, object]:
    return {
        "status": "local_rejected_review_preview",
        "package_id": str(preflight.rejected.original.package_id),
        "source_copy_status": "generation_copy_rejected",
        "review_state": preflight.review_state,
        "reviewer_supports_candidate": (
            preflight.verdict.reviewer_supports_candidate
            if preflight.review_state == "typed_complete"
            else None
        ),
        "reviewer_issue_codes": (
            list(preflight.verdict.issues) if preflight.review_state == "typed_complete" else []
        ),
        "image_status": image_status,
        "image_intents": image_intents,
        "notice": preflight.notice,
        "footer_mode": "review_only_caution",
        "ocr": "not_checked",
        "visual_audit": "not_checked",
        "human_inspection": "pending",
        "generation_calls": 0,
        "audit_calls": 0,
        "proposal_ready": False,
        "send_ready": False,
    }


def _fresh_preview_directories(output_dir: Path) -> Path:
    _checked_output_root(output_dir)
    output_dir.mkdir(mode=0o700)
    private_dir = output_dir / "private"
    private_dir.mkdir(mode=0o700)
    return private_dir


def _new_images_directory(output_dir: Path) -> Path:
    images = output_dir / "images"
    images.mkdir(mode=0o700)
    return images


async def execute_rejected_preview(
    preflight: RejectedPreviewPreflight,
    *,
    output_dir: Path,
    image: ImageModel,
    image_ledger_dir: Path = _IMAGE_LEDGER,
) -> dict[str, object]:
    """One fixed Comfly request even when the typed reviewer rejects the copy."""
    current = preflight_rejected_preview(
        input_bundle=preflight.rejected.input_bundle,
        package_detail=preflight.rejected.package_detail,
        copy_run_detail=preflight.rejected.copy_run_detail,
        source_copy_dir=preflight.rejected.source_copy_dir,
        expected_response_sha256=preflight.rejected.response_sha256,
        audit_dir=preflight.audit_dir,
        expected_audit_response_sha256=preflight.audit_response_sha256,
        references=preflight.references,
        copy_ledger_dir=preflight.rejected.copy_ledger_dir,
        audit_ledger_dir=preflight.audit_ledger_dir,
    )
    if current != preflight:
        raise TrialInputError("review preview preflight changed before image intent")
    if image.image_model != LOCAL_INFOGRAPHIC_IMAGE_MODEL:
        raise TrialInputError("review preview requires pinned Comfly portrait model")
    prompt = validate_image_generation_request_prompt(
        ImageGenerationRequest(
            run_id=uuid4(),
            draft_version_id=preflight.rejected.original.case.draft_version_id,
            prompt=preflight.image_prompt,
            request_fingerprint="review-preview-preflight",
            unrestricted_prompt_length=True,
        )
    )
    request_fingerprint = sha256(
        json.dumps(
            {
                "preview_version": PREVIEW_VERSION,
                "prompt_version": PROMPT_VERSION,
                "notice_version": NOTICE_VERSION,
                "package_id": str(preflight.rejected.original.package_id),
                "copy_response_sha256": preflight.rejected.response_sha256,
                "audit_response_sha256": preflight.audit_response_sha256,
                "prompt": prompt,
                "references": [item.sha256 for item in preflight.references],
                "font_sha256": preflight.font_sha256,
                "model": image.image_model,
                "geometry": GEOMETRY,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    request = ImageGenerationRequest(
        run_id=uuid4(),
        draft_version_id=preflight.rejected.original.case.draft_version_id,
        prompt=prompt,
        request_fingerprint=request_fingerprint,
        provider_request_fingerprint=request_fingerprint,
        references=preflight.references,
        reference_mode="multi",
        unrestricted_prompt_length=True,
    )
    private_dir = _fresh_preview_directories(output_dir)
    _write_exclusive_json(
        private_dir / "image-request.json",
        {
            "preview_version": PREVIEW_VERSION,
            "prompt_version": PROMPT_VERSION,
            "notice_version": NOTICE_VERSION,
            "request_fingerprint": request_fingerprint,
            "prompt": prompt,
            "copy_response_sha256": preflight.rejected.response_sha256,
            "audit_response_sha256": preflight.audit_response_sha256,
            "references": [
                {"role": item.role, "sha256": item.sha256} for item in preflight.references
            ],
        },
        private=True,
    )
    if preflight.review_state == "typed_complete":
        _write_exclusive_json(
            private_dir / "review-verdict.json",
            preflight.verdict.model_dump(mode="json"),
            private=True,
        )
    else:
        _write_exclusive_json(
            private_dir / "review-observation.json",
            {
                "review_state": preflight.review_state,
                "audit_response_sha256": preflight.audit_response_sha256,
                "issue_codes": list(preflight.verdict.issues),
                "rationale_length": len(preflight.verdict.rationale),
                "rationale_sha256": sha256(preflight.verdict.rationale.encode("utf-8")).hexdigest(),
            },
            private=True,
        )
    try:
        _reserve_image_intent(
            preflight, ledger_dir=image_ledger_dir, output_dir=output_dir, request=request
        )
    except FileExistsError as exc:
        raise TrialInputError("review preview image intent already exists") from exc
    details: dict[str, object] = {}
    image_status = "result_unknown_or_quality_failed"
    try:
        result = await image.generate(request)
        if (
            result.provider != "comfly"
            or result.model != image.image_model
            or result.request_fingerprint != request_fingerprint
            or result.attempts != 1
        ):
            raise ValueError("preview image result differs from reserved request")
        extension, raw = _validate_raster(result)
        images = _new_images_directory(output_dir)
        raw_name = f"raw.{extension}"
        _safe_file(images / raw_name, raw, private=True)
        details["raw_image"] = f"images/{raw_name}"
        details["raw_image_sha256"] = sha256(raw).hexdigest()
        footer = render_exact_source_footer(raw, preflight.rejected.original.case, mode="local")
        _safe_file(images / "footer.png", footer.image_bytes, private=True)
        details["footer_image_sha256"] = footer.image_sha256
        font_data = _notice_font_bytes()
        if sha256(font_data).hexdigest() != preflight.font_sha256:
            raise ValueError("review notice font changed after image intent")
        marked = _warning_overlay(footer.image_bytes, font_data, notice=preflight.notice)
        _safe_file(images / "marked.png", marked, private=True)
        details["marked_image_sha256"] = sha256(marked).hexdigest()
        group = prepare_infographic_group_jpeg(marked, max_bytes=_MAX_GROUP_BYTES)
        if not group or len(group) > _MAX_GROUP_BYTES:
            raise ValueError("review preview JPEG exceeds size limit")
        with Image.open(BytesIO(group)) as opened:
            if opened.format != "JPEG" or opened.size != GEOMETRY:
                raise ValueError("review preview JPEG geometry or format differs")
            opened.load()
            phone = opened.convert("RGB").resize(
                (390, round(390 * GEOMETRY[1] / GEOMETRY[0])), Image.Resampling.LANCZOS
            )
        _safe_file(images / "group.jpg", group, private=True)
        phone_stream = BytesIO()
        phone.save(phone_stream, format="PNG")
        _safe_file(images / "phone-390.png", phone_stream.getvalue(), private=True)
        details.update(
            {
                "group_image": "images/group.jpg",
                "group_image_sha256": sha256(group).hexdigest(),
                "group_image_byte_size": len(group),
                "phone_preview": "images/phone-390.png",
                "phone_preview_sha256": sha256(phone_stream.getvalue()).hexdigest(),
            }
        )
        image_status = "generated_review_only_pending_human_inspection"
    except Exception:
        # A reserved request is never replayed, including post-response derivative
        # or unknown transport failures. Surviving private artifacts remain.
        pass
    summary = {**_safe_summary(preflight, image_status=image_status, image_intents=1), **details}
    _write_exclusive_json(output_dir / "summary.json", summary, private=False)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One-shot local preview of rejected reviewed copy")
    parser.add_argument("--input-bundle", required=True, type=Path)
    parser.add_argument("--package-detail", required=True, type=Path)
    parser.add_argument("--copy-run-detail", required=True, type=Path)
    parser.add_argument("--source-copy-dir", required=True, type=Path)
    parser.add_argument("--expected-response-sha256", required=True)
    parser.add_argument("--audit-dir", required=True, type=Path)
    parser.add_argument("--expected-audit-response-sha256", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--approved-asset-root", type=Path, default=_WORKSPACE_ROOT)
    parser.add_argument("--execute", action="store_true")
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    try:
        references = _approved_references(
            asset_root=args.approved_asset_root,
            exact_text_quality_trial=True,
            rich_worldskills_trial=True,
        )
        preflight = preflight_rejected_preview(
            input_bundle=args.input_bundle,
            package_detail=args.package_detail,
            copy_run_detail=args.copy_run_detail,
            source_copy_dir=args.source_copy_dir,
            expected_response_sha256=args.expected_response_sha256,
            audit_dir=args.audit_dir,
            expected_audit_response_sha256=args.expected_audit_response_sha256,
            references=references,
        )
        if not args.execute:
            print(json.dumps(preflight.safe_projection(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.output_dir is None:
            raise TrialInputError("--execute requires a fresh --output-dir")
        _checked_output_root(args.output_dir)
        settings = get_settings()
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            image = LocalInfographicAI(settings, client)
            summary = await execute_rejected_preview(
                preflight,
                output_dir=args.output_dir,
                image=image,
            )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return (
            0 if summary["image_status"] == "generated_review_only_pending_human_inspection" else 1
        )
    except (OSError, ValueError, RuntimeError):
        print(
            json.dumps(
                {
                    "status": "blocked_rejected_review_preview",
                    "reason_code": "invalid_input_or_reserved_intent",
                    "image_intents": 0,
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
