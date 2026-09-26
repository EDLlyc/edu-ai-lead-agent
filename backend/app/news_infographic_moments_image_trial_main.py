"""One-case local Moments-rich copy -> audited portrait image comparison.

This is an operator-only experiment. It never creates a delivery-ready artifact,
touches production state, or retries an ambiguous image request.
"""

# ruff: noqa: RUF001 -- exact Chinese poster instructions are intentional.

from __future__ import annotations

import argparse
import asyncio
import json
import stat
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
from app.application.services.news_infographic_footer import (
    render_exact_source_footer,
    validate_exact_source_footer_layout,
)
from app.application.services.news_infographic_rich_copy import (
    MOMENTS_AUDIT_VERSION,
    MOMENTS_PROPOSAL_VERSION,
    MomentsAuditVerdict,
    MomentsRichDraft,
    MomentsRichProposal,
    assemble_moments_rich_proposal,
    build_moments_rich_audit_prompt,
    preflight_moments_rich_layout,
)
from app.application.services.wecom_news_infographic import prepare_infographic_group_jpeg
from app.core.config import get_settings
from app.infrastructure.ai.news_infographic import (
    LOCAL_INFOGRAPHIC_IMAGE_MODEL,
    LocalInfographicAI,
)
from app.news_infographic_local_main import _WORKSPACE_ROOT, _approved_references
from app.news_infographic_moments_copy_trial_main import (
    ChatJsonModel,
    CopyOnlyChatModel,
    TrialPreflight,
    _checked_output_root,
    _read_object,
    _write_exclusive_json,
    execute_trial,
    preflight_trial,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_COPY_LEDGER = _PROJECT_ROOT / "output" / "daily-news-infographic-moments-copy-intents"
_IMAGE_LEDGER = _PROJECT_ROOT / "output" / "daily-news-infographic-moments-image-intents"
IMAGE_TRIAL_VERSION = "daily-news-infographic-moments-rich-image-local-v1"
IMAGE_PROMPT_VERSION = "daily-news-infographic-moments-rich-image-prompt-v1"
_MAX_PROMPT_CHARS = 6000
_MAX_GROUP_BYTES = 2 * 1024 * 1024


class ImageModel(Protocol):
    image_model: str

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult: ...


def _validated_references(references: tuple[ImageReference, ...]) -> None:
    if tuple(item.role for item in references) != (
        "approved-characters",
        "approved-style",
    ) or any(
        not item.image_bytes or sha256(item.image_bytes).hexdigest() != item.sha256
        for item in references
    ):
        raise ValueError("Moments image trial needs exact approved character and style references")


def build_moments_image_prompt(preflight: TrialPreflight, proposal: MomentsRichProposal) -> str:
    """Use only the already-bound and measured same-package proposal."""
    preflight_moments_rich_layout(preflight.case, preflight.binding, preflight.seed, proposal)
    paragraphs = ["".join(span.text for span in card.spans) for card in proposal.cards]
    summary = "".join(span.text for span in proposal.top_summary)
    prompt = "\n".join(
        (
            IMAGE_PROMPT_VERSION,
            "制作精确1152×2048像素的中文儿童新闻长图。第一张参考图仅用于赛先生和白蓝小赛形象，第二张仅用于蓝白明亮的版式与蓝绿紫三张宽幅卡；不得复制参考图的新闻、文字或事实。",
            "顶部蓝色圆角栏目为‘小赛洞察’，下方是标题和导语；中间画与当前新闻主题相关的象征性插画；下方依次放蓝色新闻解读、绿色孩子探究、紫色赛先生教学三张大卡。文字优先，完整正文不得被角色、装饰或插画遮挡。",
            "赛先生戴橙蓝头盔与橙色护目镜，小赛是白蓝色猫头鹰机器人。两者身前的蓝色AI徽章要清晰，尤其每一次出现的小赛胸前都须有白色大写AI。",
            "只绘制下面锁定的文字，不改字、不增添新闻数字、人物身份、政策效果、品牌承诺、英文标语、伪字或额外标签：",
            "栏目：小赛洞察",
            f"标题：{proposal.title}",
            f"导语：{summary}",
            f"蓝色卡标题：{proposal.cards[0].heading}",
            f"蓝色卡正文：{paragraphs[0]}",
            f"绿色卡标题：{proposal.cards[1].heading}",
            f"绿色卡正文：{paragraphs[1]}",
            f"紫色卡标题：{proposal.cards[2].heading}",
            f"紫色卡正文：{paragraphs[2]}",
            "正文采用清晰规范的简体中文，缩至390像素宽时仍应可读。全部标题、导语和三卡正文须在y1790前结束；y1858–2048完全留白，供程序后绘精确日期、来源和完整原文链接。",
        )
    )
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise ValueError("Moments image prompt exceeds local bound")
    return prompt


def _accepted_copy(
    preflight: TrialPreflight, copy_dir: Path, copy_ledger_dir: Path
) -> tuple[MomentsRichProposal, str]:
    """Recheck persisted private artifacts before any image reservation."""
    generation_intent = _read_object(copy_dir / "private" / "generation.intent.json")
    global_intent = _read_object(copy_ledger_dir / f"{preflight.intent_key}.intent.json")
    if (
        generation_intent.get("stage") != "generation"
        or generation_intent.get("state") != "reserved"
        or generation_intent.get("intent_key") != preflight.intent_key
        or global_intent.get("stage") != "moments-rich-copy-generation"
        or global_intent.get("state") != "reserved"
        or global_intent.get("package_id") != str(preflight.package_id)
        or global_intent.get("policy_version") != MOMENTS_PROPOSAL_VERSION
        or global_intent.get("input_fingerprint") != preflight.case.fingerprint
        or global_intent.get("seed_fingerprint") != preflight.seed.seed_fingerprint
        or global_intent.get("prompt_sha256")
        != sha256(preflight.generation_prompt.encode("utf-8")).hexdigest()
        or global_intent.get("output_name") != copy_dir.name
        or _read_object(copy_dir / "private" / "generation-prompt.json").get("prompt")
        != preflight.generation_prompt
    ):
        raise ValueError("Moments generation intent differs from frozen same-package copy")
    proposal = MomentsRichProposal.model_validate(
        _read_object(copy_dir / "private" / "proposal.json")
    )
    draft = MomentsRichDraft.model_validate(
        _read_object(copy_dir / "private" / "generation-response.json")
    )
    if proposal != assemble_moments_rich_proposal(
        preflight.case, preflight.binding, preflight.seed, draft
    ):
        raise ValueError("Moments image proposal differs from generated same-package draft")
    verdict = MomentsAuditVerdict.model_validate(
        _read_object(copy_dir / "private" / "audit-verdict.json")
    )
    if not verdict.accepted:
        raise ValueError("independent Moments copy audit did not accept")
    prompt = build_moments_rich_audit_prompt(
        preflight.case, preflight.binding, preflight.seed, proposal
    )
    intent = _read_object(copy_dir / "private" / "audit.intent.json")
    if (
        intent.get("stage") != "independent-copy-audit"
        or intent.get("state") != "reserved"
        or intent.get("schema_version") != MOMENTS_AUDIT_VERSION
        or intent.get("prompt_sha256") != sha256(prompt.encode("utf-8")).hexdigest()
        or _read_object(copy_dir / "private" / "audit-prompt.json").get("prompt") != prompt
    ):
        raise ValueError("independent audit intent differs from approved proposal")
    preflight_moments_rich_layout(preflight.case, preflight.binding, preflight.seed, proposal)
    return proposal, sha256(
        json.dumps(proposal.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _image_intent(
    *,
    preflight: TrialPreflight,
    ledger_dir: Path,
    output_dir: Path,
    request: ImageGenerationRequest,
    proposal_sha256: str,
    references: tuple[ImageReference, ...],
    model_name: str,
) -> None:
    if ".." in ledger_dir.parts or any(
        path.is_symlink() for path in (ledger_dir, *ledger_dir.parents)
    ):
        raise ValueError("Moments image intent ledger path is unsafe")
    ledger_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(ledger_dir.stat().st_mode) & 0o077:
        raise ValueError("Moments image intent ledger permissions are too broad")
    # The name intentionally excludes output directory and prompt. One package /
    # policy can never acquire a second physical attempt after an unknown result.
    key = sha256(
        f"{preflight.package_id}|{MOMENTS_PROPOSAL_VERSION}|{IMAGE_TRIAL_VERSION}".encode()
    ).hexdigest()
    try:
        _write_exclusive_json(
            ledger_dir / f"{key}.intent.json",
            {
                "state": "reserved",
                "package_id": str(preflight.package_id),
                "input_fingerprint": preflight.case.fingerprint,
                "copy_policy_version": MOMENTS_PROPOSAL_VERSION,
                "image_policy_version": IMAGE_TRIAL_VERSION,
                "proposal_sha256": proposal_sha256,
                "request_fingerprint": request.request_fingerprint,
                "reference_sha256": [item.sha256 for item in references],
                "model": model_name,
                "output_name": output_dir.name,
            },
            private=True,
        )
    except FileExistsError as exc:
        raise ValueError("package/policy image request was already reserved") from exc


def _safe_summary(
    preflight: TrialPreflight, *, copy_status: str, image_status: str, image_intents: int
) -> dict[str, object]:
    return {
        "status": "local_moments_image_trial",
        "package_id": str(preflight.package_id),
        "input_fingerprint": preflight.case.fingerprint,
        "copy_status": copy_status,
        "image_status": image_status,
        "image_intents": image_intents,
        "ocr": "not_checked",
        "visual_audit": "not_checked",
        "human_inspection": "pending",
        "body_text_verification": "not_checked",
        "footer_mode": "local_unpublished",
        "send_ready": False,
    }


def _fresh_run_directory(output_dir: Path) -> None:
    _checked_output_root(output_dir)
    output_dir.mkdir(mode=0o700)


def _new_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700)


async def run_moments_image_trial(
    preflight: TrialPreflight,
    *,
    output_dir: Path,
    chat: ChatJsonModel,
    image: ImageModel,
    references: tuple[ImageReference, ...],
    chat_model_name: str = "test-chat-model",
    copy_ledger_dir: Path = _COPY_LEDGER,
    image_ledger_dir: Path = _IMAGE_LEDGER,
) -> dict[str, object]:
    """One generation, one independent audit, then at most one image request."""
    _validated_references(references)
    if image.image_model != LOCAL_INFOGRAPHIC_IMAGE_MODEL:
        raise ValueError("Moments image trial requires the pinned portrait model")
    validate_exact_source_footer_layout(preflight.case, mode="local")
    _fresh_run_directory(output_dir)
    copy_dir = output_dir / "copy"
    copy_result = await execute_trial(
        preflight,
        output_dir=copy_dir,
        models=chat,
        model_name=chat_model_name,
        ledger_dir=copy_ledger_dir,
    )
    copy_status = str(copy_result["status"])
    if copy_status != "copy_audit_passed_unpublished":
        summary = _safe_summary(
            preflight, copy_status=copy_status, image_status="not_started", image_intents=0
        )
        _write_exclusive_json(output_dir / "summary.json", summary, private=False)
        return summary
    proposal, proposal_sha256 = _accepted_copy(preflight, copy_dir, copy_ledger_dir)
    prompt = build_moments_image_prompt(preflight, proposal)
    prompt = validate_image_generation_request_prompt(
        ImageGenerationRequest(
            run_id=uuid4(),
            draft_version_id=preflight.case.draft_version_id,
            prompt=prompt,
            request_fingerprint="local-prompt-preflight",
            unrestricted_prompt_length=True,
        )
    )
    request_fingerprint = sha256(
        json.dumps(
            {
                "version": IMAGE_TRIAL_VERSION,
                "package": str(preflight.package_id),
                "input": preflight.case.fingerprint,
                "proposal": proposal_sha256,
                "prompt": prompt,
                "references": [item.sha256 for item in references],
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
        draft_version_id=preflight.case.draft_version_id,
        prompt=prompt,
        request_fingerprint=request_fingerprint,
        provider_request_fingerprint=request_fingerprint,
        references=references,
        reference_mode="multi",
        unrestricted_prompt_length=True,
    )
    private_dir = output_dir / "private"
    _new_private_directory(private_dir)
    _write_exclusive_json(
        private_dir / "image-request.json",
        {
            "image_prompt_version": IMAGE_PROMPT_VERSION,
            "image_policy_version": IMAGE_TRIAL_VERSION,
            "proposal_sha256": proposal_sha256,
            "prompt": prompt,
            "request_fingerprint": request_fingerprint,
            "references": [{"role": item.role, "sha256": item.sha256} for item in references],
        },
        private=True,
    )
    _image_intent(
        preflight=preflight,
        ledger_dir=image_ledger_dir,
        output_dir=output_dir,
        request=request,
        proposal_sha256=proposal_sha256,
        references=references,
        model_name=image.image_model,
    )
    image_status = "result_unknown"
    details: dict[str, object] = {}
    try:
        result = await image.generate(request)
        if (
            result.provider != "comfly"
            or result.model != image.image_model
            or result.request_fingerprint != request_fingerprint
            or result.attempts != 1
        ):
            raise ValueError("image result differs from reserved request")
        extension, body = _validate_raster(result)
        images_dir = output_dir / "images"
        _new_private_directory(images_dir)
        raw_name = f"raw.{extension}"
        _safe_file(images_dir / raw_name, body, private=True)
        details["raw_image"] = f"images/{raw_name}"
        details["raw_image_sha256"] = sha256(body).hexdigest()
        footer = render_exact_source_footer(body, preflight.case, mode="local")
        _safe_file(images_dir / "footer.png", footer.image_bytes, private=True)
        details["footer_image"] = "images/footer.png"
        details["footer_image_sha256"] = footer.image_sha256
        group_body = prepare_infographic_group_jpeg(footer.image_bytes, max_bytes=_MAX_GROUP_BYTES)
        if not group_body or len(group_body) > _MAX_GROUP_BYTES:
            raise ValueError("group JPEG exceeds the bounded limit")
        with Image.open(BytesIO(group_body)) as opened:
            if opened.format != "JPEG" or opened.size != GEOMETRY:
                raise ValueError("exact group JPEG geometry or format differs")
            opened.load()
            phone = opened.convert("RGB").resize(
                (390, round(390 * GEOMETRY[1] / GEOMETRY[0])), Image.Resampling.LANCZOS
            )
        _safe_file(images_dir / "group.jpg", group_body, private=True)
        phone_stream = BytesIO()
        phone.save(phone_stream, format="PNG")
        _safe_file(images_dir / "phone-390.png", phone_stream.getvalue(), private=True)
        details.update(
            {
                "group_image": "images/group.jpg",
                "group_image_sha256": sha256(group_body).hexdigest(),
                "group_image_byte_size": len(group_body),
                "phone_preview": "images/phone-390.png",
                "phone_preview_sha256": sha256(phone_stream.getvalue()).hexdigest(),
            }
        )
        image_status = "generated_pending_exact_jpeg_review"
    except Exception:
        # A timeout and a failed post-response derivative are both non-replayable
        # once the physical request has been reserved. Private artifacts survive.
        image_status = "result_unknown_or_quality_failed"
    summary = {
        **_safe_summary(
            preflight, copy_status=copy_status, image_status=image_status, image_intents=1
        ),
        **details,
    }
    _write_exclusive_json(output_dir / "summary.json", summary, private=False)
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local one-case Moments-rich image trial")
    parser.add_argument("--input-bundle", type=Path, required=True)
    parser.add_argument("--package-detail", type=Path, required=True)
    parser.add_argument("--copy-run-detail", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--approved-asset-root", type=Path, default=_WORKSPACE_ROOT)
    parser.add_argument("--execute", action="store_true")
    return parser


async def _main() -> int:
    args = _parser().parse_args()
    preflight = preflight_trial(
        input_bundle=args.input_bundle,
        package_detail=args.package_detail,
        copy_run_detail=args.copy_run_detail,
    )
    if not args.execute:
        print(
            json.dumps(
                {
                    **preflight.safe_projection(),
                    "status": "preflight_valid_no_image_or_model_call",
                    "image_intents": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    references = _approved_references(
        asset_root=args.approved_asset_root,
        exact_text_quality_trial=True,
        rich_worldskills_trial=True,
    )
    settings = get_settings()
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        chat = CopyOnlyChatModel(settings, client)
        image = LocalInfographicAI(settings, client)
        summary = await run_moments_image_trial(
            preflight,
            output_dir=args.output_dir,
            chat=chat,
            image=image,
            references=references,
            chat_model_name=settings.ai_chat_model,
        )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["image_status"] == "generated_pending_exact_jpeg_review" else 2


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
