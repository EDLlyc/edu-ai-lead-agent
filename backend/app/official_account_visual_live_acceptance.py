# ruff: noqa: RUF001 -- Chinese punctuation is intentional local acceptance copy.
"""One-call live acceptance for the official-account v2 body-visual contract.

This operator-only command intentionally accepts no provider credentials or URLs.  It reads the
validated server-side image settings, creates one durable local call-intent marker, performs one
image-generation call, and writes only a safe local acceptance bundle.  It never constructs an
article/embedding, WeChat, WeCom, or publishing client.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from PIL import Image

from app.application.ports.image_generation import ImageGenerationRequest, ImageReference
from app.application.ports.official_account_local import (
    OfficialAccountGeneratedVisualPlan,
    OfficialAccountSourceMedia,
    StoredOfficialAccountArticle,
    StoredOfficialAccountRender,
)
from app.application.services.official_account_visual_generation import (
    build_generated_visual_prompt,
    generated_visual_alt_text,
    plan_generated_body_visual,
    prepare_generated_visual_result,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V2
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V2_VERSION,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQualitySummary,
    ArticleSection,
    ArticleVersionBundle,
    fingerprint,
)
from app.infrastructure.ai.factory import create_image_generator
from app.infrastructure.official_account_catalog import LocalOfficialAccountCatalogMediaProvider

_REPORT_VERSION = "official-account-live-image-acceptance-v1"
_OUTPUT_NAME = "body-0.jpg"
_REPORT_NAME = "acceptance.json"
_PREVIEW_NAME = "preview.html"
_README_NAME = "README.md"
_INTENT_NAME = ".paid-call-intent.json"
_COMMAND = (
    "IMAGE_MAX_ATTEMPTS=1 PYTHONPATH=backend conda run --name edu-ai python -m "
    "app.official_account_visual_live_acceptance "
    "--output-dir output/official-account-live-image-acceptance-20260824"
)
_TOPIC = "孩子如何从一次观察走向可验证的科学问题"
_HEADING = "先观察，再把好奇变成问题"
_BODY = (
    "孩子先比较两片叶子的纹理与颜色，把看到的差异记录下来，再选择其中一个变化，"
    "提出能够通过下一次观察或小实验验证的问题。"
)
_SEMANTIC_TAGS = frozenset(
    {"experiment", "observe", "microscope", "question", "thinking", "education"}
)


def _article() -> StoredOfficialAccountArticle:
    content_fingerprint = fingerprint(
        "official-account-live-image-acceptance-article-v1",
        _TOPIC,
        _HEADING,
        _BODY,
    )
    package = ArticlePackage.model_construct(
        title=_TOPIC,
        digest="一次正文配图真实链路验收。",
        author="赛先生",
        lead=_BODY,
        topic_title=_TOPIC,
        sections=(
            ArticleSection(
                heading=_HEADING,
                blocks=(ArticleParagraphBlock(kind="paragraph", text=_BODY),),
            ),
        ),
        conclusion="把观察转化为下一次可以验证的行动。",
        claims=(),
        sources=(),
        media_slots=(),
        quality=ArticleQualitySummary(
            inherited_copy_validation_passed=True,
            inherited_copy_audit_accepted=True,
            inherited_image_validation_passed=True,
            inherited_image_audit_status="accepted",
            manual_review_status="pending",
        ),
        versions=ArticleVersionBundle(
            generator_prompt_version="acceptance-v1",
            article_schema_version="acceptance-v1",
            auditor_prompt_version="acceptance-v1",
            audit_schema_version="acceptance-v1",
            rule_version="acceptance-v1",
            renderer_version="acceptance-v1",
            style_version="acceptance-v1",
            template_version="acceptance-v1",
            local_adapter_version="acceptance-v1",
        ),
        content_fingerprint=content_fingerprint,
    )
    article_id = uuid5(NAMESPACE_URL, f"{_REPORT_VERSION}:{content_fingerprint}:article")
    return StoredOfficialAccountArticle(
        id=article_id,
        article=package,
        validation_issues=(),
        audit=None,
        provider_request_id=None,
        prompt_tokens=0,
        completion_tokens=0,
        reasoning_tokens=0,
        latency_ms=0,
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
    )


def _render(article: StoredOfficialAccountArticle) -> StoredOfficialAccountRender:
    return StoredOfficialAccountRender(
        id=uuid5(NAMESPACE_URL, f"{_REPORT_VERSION}:{article.id}:render"),
        article_version_id=article.id,
        canonical_html="<section>live acceptance</section>",
        render_fingerprint=fingerprint(
            "official-account-live-image-acceptance-render-v1",
            article.article.content_fingerprint,
        ),
    )


def _select_reference(
    candidates: tuple[OfficialAccountSourceMedia, ...],
) -> OfficialAccountSourceMedia:
    if len(candidates) != 41:
        raise ValueError("approved catalog preflight failed")

    def rank(item: OfficialAccountSourceMedia) -> tuple[int, int, str]:
        semantic_score = len(_SEMANTIC_TAGS.intersection(item.semantic_tags))
        return (-semantic_score, -item.publication_priority, item.catalog_asset_ref or "")

    selected = sorted(candidates, key=rank)[0]
    if not _SEMANTIC_TAGS.intersection(selected.semantic_tags):
        raise ValueError("approved catalog has no semantic acceptance reference")
    return replace(
        selected,
        ordinal=0,
        assigned_section_index=0,
        score_band="heading",
        selection_reason_code="live_acceptance_semantic_block",
        selection_method="deterministic_tag",
        similarity_band=None,
    )


def _preflight(settings: Settings, output_dir: Path) -> None:
    if settings.image_provider_mode != "comfly":
        raise ValueError("live acceptance requires the configured Comfly provider")
    if settings.image_max_attempts != 1:
        raise ValueError("live acceptance requires exactly one provider attempt")
    if settings.comfly_api_key is None or not settings.comfly_api_key.get_secret_value().strip():
        raise ValueError("live acceptance requires a server-side Comfly key")
    if (
        settings.official_account_local_generated_visual_plan_version
        != OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION
        or settings.official_account_local_generated_visual_prompt_version
        != OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V2_VERSION
    ):
        raise ValueError("live acceptance requires the current official-account visual bundle")
    if output_dir.exists():
        raise FileExistsError("refusing to reuse a live-acceptance output directory")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_intent(output_dir: Path, *, request_fingerprint: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    intent = {
        "version": _REPORT_VERSION,
        "paid_generation_call_limit": 1,
        "paid_generation_calls_attempted": 1,
        "request_fingerprint": request_fingerprint,
    }
    with (output_dir / _INTENT_NAME).open("x", encoding="utf-8") as stream:
        json.dump(intent, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def _validate_publication(body: bytes) -> dict[str, Any]:
    with Image.open(BytesIO(body)) as image:
        image.load()
        if image.format != "JPEG" or image.size != (1536, 1024):
            raise ValueError("publication output profile mismatch")
        if image.getexif() or image.info.get("icc_profile"):
            raise ValueError("publication output contains disallowed metadata")
    return {
        "media_type": "image/jpeg",
        "width": 1536,
        "height": 1024,
        "aspect_ratio": "3:2",
        "byte_size": len(body),
        "sha256": sha256(body).hexdigest(),
        "exif_present": False,
        "icc_profile_present": False,
    }


def _write_success_bundle(
    output_dir: Path,
    *,
    settings: Settings,
    reference: OfficialAccountSourceMedia,
    plan: Any,
    prompt_sha256: str,
    alt_text: str,
    body: bytes,
) -> None:
    output = _validate_publication(body)
    output_path = output_dir / _OUTPUT_NAME
    with output_path.open("xb") as stream:
        stream.write(body)
    report = {
        "version": _REPORT_VERSION,
        "status": "passed",
        "command": _COMMAND,
        "paid_generation_call_limit": 1,
        "paid_generation_calls_attempted": 1,
        "paid_generation_calls_succeeded": 1,
        "provider": settings.image_provider_mode,
        "model": settings.image_model,
        "request_identity_validated": True,
        "request_fingerprint": plan.request_fingerprint,
        "prompt_sha256": prompt_sha256,
        "plan_version": plan.plan_version,
        "prompt_version": plan.prompt_version,
        "reference_input_version": plan.reference_input_version,
        "reference_input_media_type": "image/png",
        "reference_input_sha256": plan.reference_input_checksum,
        "reference_source_media_type": reference.media_type,
        "reference_public_ref": reference.catalog_asset_ref,
        "reference_catalog_version": reference.catalog_version,
        "reference_source_sha256": reference.source_master_sha256,
        "reference_publication_sha256": reference.sha256,
        "block_anchor": {
            "section_index": plan.section_index,
            "block_index": plan.block_index,
            "block_kind": plan.block_kind,
            "block_fingerprint": plan.block_fingerprint,
            "semantic_alt": alt_text,
        },
        "output_profile_version": plan.output_profile_version,
        "output_file": _OUTPUT_NAME,
        "output": output,
        "boundaries": {
            "article_provider_calls": 0,
            "embedding_provider_calls": 0,
            "wechat_calls": 0,
            "wecom_calls": 0,
            "publish_calls": 0,
            "local_only": True,
        },
    }
    _write_json(output_dir / _REPORT_NAME, report)
    safe_alt = html.escape(alt_text, quote=True)
    (output_dir / _PREVIEW_NAME).write_text(
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>公众号正文配图单次真实验收</title><style>body{margin:0;background:#f4f1e8;"
        "color:#18334a;font-family:system-ui,sans-serif}.wrap{width:min(92vw,760px);margin:40px "
        "auto;padding:24px;background:#fff;border-radius:20px;box-shadow:0 18px 48px #18334a18}"
        "img{display:block;width:100%;aspect-ratio:3/2;object-fit:cover;border-radius:14px}"
        'p{line-height:1.75}</style></head><body><main class="wrap"><h1>本地单次真实验收</h1>'
        f'<img src="{_OUTPUT_NAME}" alt="{safe_alt}"><p>{safe_alt}</p>'
        "<p>LOCAL ONLY · 未同步公众号</p></main></body></html>\n",
        encoding="utf-8",
    )
    (output_dir / _README_NAME).write_text(
        "# 公众号正文配图单次真实验收\n\n"
        "本目录保存一次明确授权的 Comfly 真实图片生成验收结果。图片已经通过公众号 v2 "
        "正文块锚点、JPEG→PNG 参考输入规范化和 1536×1024（3:2）发布衍生链路。\n\n"
        "- 付费图片生成调用：1 次\n"
        "- 文章、Embedding、微信、企微、发布调用：0 次\n"
        "- 范围：本地验收，未同步公众号\n"
        f"- 语义说明：{alt_text}\n\n"
        "`acceptance.json` 保存安全身份、校验和、尺寸及调用边界；不含密钥、Provider URL、"
        "响应体、prompt 或私有素材路径。\n",
        encoding="utf-8",
    )


def _write_failure(output_dir: Path, *, settings: Settings, plan: Any, error: AppError) -> None:
    _write_json(
        output_dir / _REPORT_NAME,
        {
            "version": _REPORT_VERSION,
            "status": "result_unknown" if error.code == "image_provider_timeout" else "failed",
            "command": _COMMAND,
            "paid_generation_call_limit": 1,
            "paid_generation_calls_attempted": 1,
            "paid_generation_calls_succeeded": 0,
            "provider": settings.image_provider_mode,
            "model": settings.image_model,
            "request_fingerprint": plan.request_fingerprint,
            "safe_error_code": error.code,
            "retryable": error.retryable,
            "automatic_retry_permitted": False,
            "boundaries": {
                "article_provider_calls": 0,
                "embedding_provider_calls": 0,
                "wechat_calls": 0,
                "wecom_calls": 0,
                "publish_calls": 0,
                "local_only": True,
            },
        },
    )


async def _prepare_acceptance(
    settings: Settings,
) -> tuple[
    OfficialAccountSourceMedia,
    StoredOfficialAccountArticle,
    OfficialAccountGeneratedVisualPlan,
    str,
    ImageGenerationRequest,
]:
    catalog = LocalOfficialAccountCatalogMediaProvider(settings.image_asset_manifest)
    reference = _select_reference(await catalog.load_candidates())
    reference = await catalog.revalidate_candidate(reference)
    reference_bytes = await catalog.read_publication_bytes(
        catalog_asset_ref=reference.catalog_asset_ref or "",
        catalog_version=reference.catalog_version or "",
        source_master_sha256=reference.source_master_sha256 or "",
        publication_sha256=reference.sha256,
    )
    article = _article()
    render = _render(article)
    run_id = uuid5(NAMESPACE_URL, f"{_REPORT_VERSION}:{article.id}:run")
    plan = plan_generated_body_visual(
        run_id=run_id,
        article=article,
        render=render,
        ordinal=0,
        reference=reference,
        provider="comfly",
        model=settings.image_model,
        reference_bytes=reference_bytes,
        plan_version=settings.official_account_local_generated_visual_plan_version,
        prompt_version=settings.official_account_local_generated_visual_prompt_version,
    )
    prompt = build_generated_visual_prompt(
        article=article,
        section_index=plan.section_index,
        reference=reference,
        prompt_version=plan.prompt_version,
        block_index=plan.block_index,
    )
    request = ImageGenerationRequest(
        run_id=run_id,
        draft_version_id=article.id,
        prompt=prompt,
        request_fingerprint=plan.request_fingerprint,
        references=(
            ImageReference(
                role="approved_ip_reference",
                asset_id=plan.reference_asset_ref,
                filename=f"official-account-reference-{plan.reference_asset_ref}.jpg",
                sha256=plan.reference_publication_checksum,
                image_bytes=reference_bytes,
                selection_reason="approved_catalog_semantic_reference",
                input_normalization_version=(
                    plan.reference_input_version or IMAGE_REFERENCE_INPUT_V2
                ),
                provider_input_sha256=plan.reference_input_checksum,
            ),
        ),
        reference_mode="single_reference",
    )
    return reference, article, plan, prompt, request


async def run(output_dir: Path) -> bool:
    settings = get_settings()
    _preflight(settings, output_dir)
    reference, article, plan, prompt, request = await _prepare_acceptance(settings)
    _write_intent(output_dir, request_fingerprint=plan.request_fingerprint)
    try:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            generator = create_image_generator(settings, client=client)
            result = await generator.generate(request)
        prepared = prepare_generated_visual_result(
            result=result,
            plan=plan,
            max_bytes=settings.image_max_download_bytes,
        )
    except AppError as error:
        _write_failure(output_dir, settings=settings, plan=plan, error=error)
        return False
    alt_text = generated_visual_alt_text(article=article, plan=plan)
    _write_success_bundle(
        output_dir,
        settings=settings,
        reference=reference,
        plan=plan,
        prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
        alt_text=alt_text,
        body=prepared.image_bytes,
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one authorized Comfly acceptance for the official-account v2 visual path"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.preflight_only:
            settings = get_settings()
            _preflight(settings, args.output_dir)
            reference, _article_value, plan, _prompt, _request = asyncio.run(
                _prepare_acceptance(settings)
            )
            print(
                "official_account_visual_live_acceptance preflight_passed "
                f"provider={settings.image_provider_mode} model={settings.image_model} "
                f"attempts={settings.image_max_attempts} reference={reference.catalog_asset_ref} "
                f"input=image/jpeg->image/png block={plan.block_kind}:{plan.block_index}"
            )
            return
        succeeded = asyncio.run(run(args.output_dir))
    except (FileExistsError, ValueError, RuntimeError):
        print("official_account_visual_live_acceptance preflight_failed")
        raise SystemExit(2) from None
    if not succeeded:
        print("official_account_visual_live_acceptance provider_failed calls_attempted=1")
        raise SystemExit(1)
    print("official_account_visual_live_acceptance passed calls_attempted=1")


if __name__ == "__main__":
    main()
