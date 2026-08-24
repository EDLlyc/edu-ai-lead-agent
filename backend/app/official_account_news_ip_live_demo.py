# ruff: noqa: RUF001 -- Chinese editorial copy is intentional.
"""News-backed, three-call ToApis demo for official-account visible-IP visuals.

This operator-only command creates a fresh local bundle. It accepts no credentials, never reads
Comfly settings, never constructs article/embedding/WeChat/WeCom clients, and persists an intent
before each of at most three paid image-generation calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from app.application.ports.image_generation import ImageGenerationRequest, ImageReference
from app.application.ports.official_account_local import (
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
from app.core.errors import AppError, ImageOutputValidationError
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V2
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    ArticleImageBlock,
    ArticleMediaSlot,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQualitySummary,
    ArticleSection,
    ArticleSourceProjection,
    ArticleVersionBundle,
    GeneratedArticleClaim,
    body_media_placeholder,
    fingerprint,
    render_wechat_html,
)
from app.infrastructure.ai.factory import create_image_generator
from app.infrastructure.official_account_catalog import LocalOfficialAccountCatalogMediaProvider

REPORT_VERSION = "official-account-news-ip-live-demo-v1"
NEWS_URL = "https://www.moe.gov.cn/jyb_xwfb/s5148/202607/t20260721_1444504.html"
NEWS_FETCH_URL = "https://hudong.moe.gov.cn/jyb_xwfb/s5148/202607/t20260721_1444504.html"
PLAN_URL = "https://hudong.moe.gov.cn/srcsite/A16/s3342/202604/t20260410_1433240.html"
PAID_CALL_LIMIT = 3
_MAX_SOURCE_BYTES = 512_000
_SOURCE_TIMEOUT_SECONDS = 30.0
_REFERENCE_REFS = (
    "33586a916bbbfbf1",
    "5c2a29bbec16ca4f",
    "09c8fd9470cb5502",
)
_REQUIRED_SOURCE_FACTS = (
    "基础教育必须从传统的知识传授转向更加注重创新能力和综合素养培育",
    "坚持育人为本、素养为先、应用导向、智能向善",
)


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    evidence_id: str
    canonical_url: str
    retrieval_url: str
    source_name: str
    title: str
    published_date: str
    exact_quote: str
    document_sha256: str
    fetched_at: str


def _safe_json(path: Path, payload: object, *, exclusive: bool = False) -> None:
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _normalize_text(value: str, limit: int) -> str:
    return " ".join(value.replace("\u3000", " ").split())[:limit]


def _create_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "assets").mkdir()


def _parse_source(
    body: bytes,
    *,
    canonical_url: str,
    retrieval_url: str,
    expected_title: str,
    expected_date: str,
    required_fact: str,
    quote: str,
) -> EvidenceSnapshot:
    if not body or len(body) > _MAX_SOURCE_BYTES:
        raise ValueError("official source body is outside the bounded size")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("official source must be UTF-8") from error
    soup = BeautifulSoup(text, "html.parser")
    title = _normalize_text(str(soup.find("meta", attrs={"name": "ArticleTitle"}) or ""), 240)
    meta_title = soup.find("meta", attrs={"name": "ArticleTitle"})
    if meta_title is not None:
        title = _normalize_text(str(meta_title.get("content") or ""), 240)
    if not title and soup.title is not None:
        title = _normalize_text(soup.title.get_text(" ", strip=True).split(" - ")[0], 240)
    meta_date = soup.find("meta", attrs={"name": "publishdate"})
    published = _normalize_text(str(meta_date.get("content") if meta_date else ""), 20)
    visible = _normalize_text(soup.get_text(" ", strip=True), 120_000)
    if expected_title not in title or published != expected_date or required_fact not in visible:
        raise ValueError("official source identity or required fact changed")
    if quote not in visible:
        raise ValueError("bounded evidence quote is absent from the official source")
    canonical = urlsplit(canonical_url)
    retrieval = urlsplit(retrieval_url)
    if (
        canonical.scheme != "https"
        or canonical.hostname not in {"www.moe.gov.cn", "hudong.moe.gov.cn"}
        or retrieval.scheme != "https"
        or retrieval.hostname not in {"www.moe.gov.cn", "hudong.moe.gov.cn"}
    ):
        raise ValueError("official source URL is outside the pinned HTTPS allowlist")
    return EvidenceSnapshot(
        evidence_id=str(uuid5(NAMESPACE_URL, f"{REPORT_VERSION}:{canonical_url}:{quote}")),
        canonical_url=canonical_url,
        retrieval_url=retrieval_url,
        source_name="中华人民共和国教育部政府门户网站",
        title=title,
        published_date=published,
        exact_quote=quote,
        document_sha256=sha256(body).hexdigest(),
        fetched_at=datetime.now(UTC).isoformat(),
    )


async def _fetch_body(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(
        url,
        headers={"User-Agent": "EduAILeadAgent/official-account-news-ip-demo"},
        timeout=httpx.Timeout(_SOURCE_TIMEOUT_SECONDS),
        follow_redirects=False,
    )
    if response.status_code != 200 or len(response.content) > _MAX_SOURCE_BYTES:
        raise ValueError("official source fetch failed closed")
    return response.content


async def load_evidence(
    *, news_html: Path | None = None, plan_html: Path | None = None
) -> tuple[EvidenceSnapshot, EvidenceSnapshot, int]:
    calls = 0
    if news_html is None or plan_html is None:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            news_body = (
                await asyncio.to_thread(news_html.read_bytes)
                if news_html is not None
                else await _fetch_body(client, NEWS_FETCH_URL)
            )
            calls += int(news_html is None)
            plan_body = (
                await asyncio.to_thread(plan_html.read_bytes)
                if plan_html is not None
                else await _fetch_body(client, PLAN_URL)
            )
            calls += int(plan_html is None)
    else:
        news_body, plan_body = await asyncio.gather(
            asyncio.to_thread(news_html.read_bytes),
            asyncio.to_thread(plan_html.read_bytes),
        )
    news = _parse_source(
        news_body,
        canonical_url=NEWS_URL,
        retrieval_url=NEWS_FETCH_URL,
        expected_title="面向未来，向新而行",
        expected_date="2026-07-21",
        required_fact=_REQUIRED_SOURCE_FACTS[0],
        quote="科技教育以更加鲜明的学科融合和实践导向持续发力",
    )
    plan = _parse_source(
        plan_body,
        canonical_url=PLAN_URL,
        retrieval_url=PLAN_URL,
        expected_title="教育部等五部门关于印发《“人工智能+教育”行动计划》的通知",
        expected_date="2026-04-10",
        required_fact=_REQUIRED_SOURCE_FACTS[1],
        quote="鼓励开展人工智能跨学科教学",
    )
    return news, plan, calls


def _article(evidence: tuple[EvidenceSnapshot, EvidenceSnapshot]) -> StoredOfficialAccountArticle:
    evidence_ids = tuple(UUID(item.evidence_id) for item in evidence)
    sections = (
        ArticleSection(
            heading="这条新闻真正改变了什么",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "7月21日，教育部政府门户网站刊文回顾基础教育改革进展。文章把创新能力、"
                        "综合素养，以及学科融合与实践导向放在更突出的位置。对家长而言，这并不"
                        "等于又多了一张知识清单，而是提醒我们：孩子需要经历提出问题、动手验证、"
                        "解释结果的完整过程。"
                    ),
                    claim_refs=("news-direction",),
                ),
                ArticleImageBlock(
                    kind="image",
                    slot_key="body-0",
                    alt_text="小赛陪孩子从新闻线索中提出可验证的问题",
                ),
            ),
        ),
        ArticleSection(
            heading="行动计划把方向说得更具体",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "4月发布的“人工智能+教育”行动计划明确提出育人为本、素养为先，并鼓励"
                        "人工智能跨学科教学。把两份权威材料放在一起看，重点不是让孩子更早追逐"
                        "某个工具，而是让工具服务于理解、探究与解决真实问题。"
                    ),
                    claim_refs=("plan-principle", "plan-cross-disciplinary"),
                ),
                ArticleImageBlock(
                    kind="image",
                    slot_key="body-1",
                    alt_text="小赛与亲子一起完成跨学科人工智能探究",
                ),
            ),
        ),
        ArticleSection(
            heading="家庭可以先做一个小闭环",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "以下是面向家庭的实践建议，不是政策原文：选择一个孩子真正好奇的现象，"
                        "先写下猜想，再用观察、测量或小实验收集证据，最后请孩子说明哪里符合"
                        "预期、哪里需要重新验证。AI可以帮助整理问题和比较记录，但判断与表达"
                        "仍由孩子完成。"
                    ),
                    claim_refs=("family-interpretation",),
                ),
                ArticleImageBlock(
                    kind="image",
                    slot_key="body-2",
                    alt_text="赛先生和小赛陪亲子记录实验并复盘证据",
                ),
            ),
        ),
    )
    claims = (
        GeneratedArticleClaim(
            id="news-direction",
            text="教育部新闻把创新能力、综合素养、学科融合和实践导向置于重要位置。",
            kind="external_fact",
            evidence_ids=(evidence_ids[0],),
        ),
        GeneratedArticleClaim(
            id="plan-principle",
            text="行动计划提出育人为本、素养为先、应用导向、智能向善。",
            kind="external_fact",
            evidence_ids=(evidence_ids[1],),
        ),
        GeneratedArticleClaim(
            id="plan-cross-disciplinary",
            text="行动计划鼓励开展人工智能跨学科教学。",
            kind="external_fact",
            evidence_ids=(evidence_ids[1],),
        ),
        GeneratedArticleClaim(
            id="family-interpretation",
            text="家庭可用问题、证据与复盘构成一个小型探究闭环。",
            kind="opinion",
        ),
    )
    versions = ArticleVersionBundle(
        generator_prompt_version="official-account-news-evidence-assembler-v1",
        article_schema_version="official-account-news-evidence-schema-v1",
        auditor_prompt_version="official-account-news-evidence-audit-v1",
        audit_schema_version="official-account-news-evidence-audit-schema-v1",
        rule_version="official-account-news-evidence-rules-v1",
        renderer_version="official-account-news-renderer-v1",
        style_version="official-account-news-style-v1",
        template_version="official-account-news-template-v1",
        local_adapter_version="official-account-news-local-adapter-v1",
    )
    content = fingerprint(
        REPORT_VERSION,
        tuple(item.document_sha256 for item in evidence),
        tuple(section.model_dump(mode="json") for section in sections),
        tuple(claim.model_dump(mode="json") for claim in claims),
    )
    package = ArticlePackage.model_construct(
        title="AI教育行动计划落地：家长真正要抓住的三件事",
        digest="从教育部最新新闻与行动计划出发，读懂素养、跨学科与家庭探究的关系。",
        author="赛先生",
        lead=(
            "当AI进入课堂和家庭，真正值得追问的不是孩子用了多少工具，而是他能否提出问题、"
            "寻找证据，并对自己的判断负责。两份教育部权威材料为家长提供了更清楚的观察框架。"
        ),
        topic_title="教育部AI教育行动计划与家庭科学探究",
        sections=sections,
        conclusion=(
            "先从一个真实问题开始。让AI做助手，不替孩子做判断。每次活动留下猜想、证据和复盘。"
        ),
        claims=claims,
        sources=tuple(
            ArticleSourceProjection(
                evidence_id=UUID(item.evidence_id),
                source_name=f"教育部｜{item.title}",
                source_url=item.canonical_url,
                source_tier="A",
            )
            for item in evidence
        ),
        media_slots=(
            ArticleMediaSlot(slot_key="body-0", role="body", ordinal=0),
            ArticleMediaSlot(slot_key="body-1", role="body", ordinal=1),
            ArticleMediaSlot(slot_key="body-2", role="body", ordinal=2),
            ArticleMediaSlot(slot_key="cover-0", role="cover", ordinal=0),
        ),
        quality=ArticleQualitySummary(
            inherited_copy_validation_passed=True,
            inherited_copy_audit_accepted=True,
            inherited_image_validation_passed=True,
            inherited_image_audit_status="accepted",
            manual_review_status="pending",
        ),
        versions=versions,
        media_selection=None,
        content_fingerprint=content,
    )
    article_id = uuid5(NAMESPACE_URL, f"{REPORT_VERSION}:{content}:article")
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
        created_at=datetime.now(UTC),
    )


def _render(article: StoredOfficialAccountArticle) -> StoredOfficialAccountRender:
    # The news assembler has its own frozen local-only renderer identity, while layout bytes reuse
    # the existing escaped v7 renderer through a temporary compatible projection.
    compatible = article.article.model_copy(
        update={
            "versions": ArticleVersionBundle(
                generator_prompt_version="official-account-generator-v5-structured-output",
                article_schema_version="official-account-article-schema-v4-multimodal-media",
                auditor_prompt_version="official-account-auditor-v2-structured-output",
                audit_schema_version="official-account-audit-schema-v1",
                rule_version="official-account-rules-v4-reader-copy",
                renderer_version="wechat-html-renderer-v7-multimodal-media",
                style_version="wechat-inline-science-field-guide-v7-multimodal-media",
                template_version="wechat-science-field-guide-template-v7-multimodal-media",
                local_adapter_version="official-account-local-adapter-v5-multimodal-media",
                media_plan_version="official-account-media-plan-v3-multimodal-hybrid",
                visual_query_version="official-account-visual-query-v1",
                visual_selector_version="official-account-visual-selector-v3-multimodal-hybrid",
            )
        }
    )
    rendered = render_wechat_html(compatible)
    render_id = uuid5(NAMESPACE_URL, f"{REPORT_VERSION}:{article.id}:render")
    return StoredOfficialAccountRender(
        id=render_id,
        article_version_id=article.id,
        canonical_html=rendered.canonical_html,
        render_fingerprint=fingerprint(REPORT_VERSION, rendered.render_fingerprint),
    )


async def _references(
    settings: Settings,
) -> tuple[tuple[OfficialAccountSourceMedia, bytes], ...]:
    provider = LocalOfficialAccountCatalogMediaProvider(settings.image_asset_manifest)
    candidates = {item.catalog_asset_ref: item for item in await provider.load_candidates()}
    if len(candidates) != 41:
        raise ValueError("approved 41-item IP catalog preflight failed")
    selected: list[tuple[OfficialAccountSourceMedia, bytes]] = []
    for ordinal, asset_ref in enumerate(_REFERENCE_REFS):
        item = candidates.get(asset_ref)
        if item is None or item.catalog_version is None or item.source_master_sha256 is None:
            raise ValueError("pinned approved IP reference is unavailable")
        revalidated = await provider.revalidate_candidate(item)
        body = await provider.read_publication_bytes(
            catalog_asset_ref=asset_ref,
            catalog_version=revalidated.catalog_version or "",
            source_master_sha256=revalidated.source_master_sha256 or "",
            publication_sha256=revalidated.sha256,
        )
        selected.append(
            (
                replace(
                    revalidated,
                    ordinal=ordinal,
                    assigned_section_index=ordinal,
                    selection_method="deterministic_tag",
                    similarity_band=None,
                    selection_reason_code="news_block_visible_ip_v3",
                ),
                body,
            )
        )
    return tuple(selected)


def _preflight(settings: Settings, output_dir: Path) -> Settings:
    if output_dir.exists():
        raise FileExistsError("refusing to replace an existing news-IP output directory")
    if settings.toapis_api_key is None or not settings.toapis_api_key.get_secret_value().strip():
        raise ValueError("news-IP demo requires a server-side ToApis key")
    if settings.toapis_base_url != "https://toapis.com":
        raise ValueError("news-IP demo requires the pinned ToApis origin")
    return settings.model_copy(
        update={
            "image_provider_mode": "toapis",
            "image_max_attempts": 1,
        }
    )


def _write_intent(output_dir: Path, *, ordinal: int, plan: Any) -> None:
    intents = output_dir / "intents"
    intents.mkdir(exist_ok=True)
    _safe_json(
        intents / f"body-{ordinal}.intent.json",
        {
            "version": REPORT_VERSION,
            "ordinal": ordinal,
            "state": "generating",
            "paid_call_limit": PAID_CALL_LIMIT,
            "request_fingerprint": plan.request_fingerprint,
            "plan_version": plan.plan_version,
            "prompt_version": plan.prompt_version,
            "automatic_retry_permitted": False,
        },
        exclusive=True,
    )


def _write_failed_result(
    output_dir: Path,
    *,
    ordinal: int,
    plan: Any,
    state: str,
    safe_error_code: str,
) -> None:
    if state not in {"failed", "result_unknown"}:
        raise ValueError("news-IP result state is invalid")
    _safe_json(
        output_dir / "intents" / f"body-{ordinal}.result.json",
        {
            "version": REPORT_VERSION,
            "ordinal": ordinal,
            "state": state,
            "safe_error_code": safe_error_code,
            "request_fingerprint": plan.request_fingerprint,
            "automatic_retry_permitted": False,
        },
        exclusive=True,
    )


def _validate_jpeg(body: bytes) -> dict[str, Any]:
    with Image.open(BytesIO(body)) as image:
        image.load()
        if image.format != "JPEG" or image.size != (1536, 1024):
            raise ValueError("publication profile mismatch")
        if image.getexif() or image.info.get("icc_profile"):
            raise ValueError("publication metadata is not empty")
    return {
        "media_type": "image/jpeg",
        "width": 1536,
        "height": 1024,
        "byte_size": len(body),
        "sha256": sha256(body).hexdigest(),
        "metadata_free": True,
    }


def _article_markdown(article: StoredOfficialAccountArticle) -> str:
    lines = [f"# {article.article.title}", "", article.article.lead, ""]
    for section in article.article.sections:
        lines.extend((f"## {section.heading}", ""))
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                lines.extend((block.text, ""))
    lines.extend(("## 结语", "", article.article.conclusion, "", "## 来源", ""))
    lines.extend(
        f"- [{source.source_name}]({source.source_url})" for source in article.article.sources
    )
    return "\n".join(lines) + "\n"


def _preview_document(body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>教育部AI教育行动计划｜本地新闻草稿</title><style>"
        "html{background:#e9eef0}body{margin:0}.frame{width:min(100%,430px);margin:24px auto;"
        "background:#fff;box-shadow:0 20px 60px #18334a22}.boundary{padding:12px 20px;"
        "background:#15384b;color:#f5df83;font:600 12px system-ui;letter-spacing:.08em}"
        "@media(max-width:460px){.frame{margin:0;box-shadow:none}}</style></head><body>"
        '<main class="frame"><div class="boundary">LOCAL ONLY · 新闻证据已绑定 · 未同步公众号</div>'
        f"{body}</main></body></html>\n"
    )


def _zip_bundle(root: Path) -> Path:
    zip_path = root / f"{root.name}.zip"
    files = tuple(
        sorted(
            (p for p in root.rglob("*") if p.is_file() and p.suffix != ".zip"),
            key=lambda p: p.as_posix(),
        )
    )
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = ZipInfo(f"{root.name}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return zip_path


def record_visual_inspection(
    output_dir: Path,
    assessments: tuple[str, str, str],
) -> None:
    if not output_dir.is_dir() or any(item not in {"pass", "fail"} for item in assessments):
        raise ValueError("visual inspection input is invalid")
    visual_path = output_dir / "visual-map.json"
    run_path = output_dir / "run.json"
    visual_payload = json.loads(visual_path.read_text(encoding="utf-8"))
    run_payload = json.loads(run_path.read_text(encoding="utf-8"))
    rows = visual_payload.get("visuals")
    if not isinstance(rows, list) or len(rows) != PAID_CALL_LIMIT:
        raise ValueError("visual inspection bundle is incomplete")
    for ordinal, (row, assessment) in enumerate(zip(rows, assessments, strict=True)):
        if not isinstance(row, dict) or row.get("ordinal") != ordinal:
            raise ValueError("visual inspection ordinal changed")
        row["ip_visibility_assessment"] = assessment
        result_path = output_dir / "intents" / f"body-{ordinal}.result.json"
        result_payload = json.loads(result_path.read_text(encoding="utf-8"))
        result_payload["ip_visibility_assessment"] = assessment
        _safe_json(result_path, result_payload)
    passed = all(item == "pass" for item in assessments)
    visual_payload["quality_status"] = "passed" if passed else "failed"
    run_payload["ip_visibility_assessment"] = "passed" if passed else "failed"
    run_payload["visual_quality_status"] = "passed" if passed else "failed"
    _safe_json(visual_path, visual_payload)
    _safe_json(run_path, run_payload)
    lines = [
        "# 本地视觉检查",
        "",
        "检查范围：小赛／赛先生是否清晰可见且为主角，是否存在可读文字、Logo、二维码或水印。",
        "本检查不触发模型、Embedding 或额外图片生成。",
        "",
    ]
    for ordinal, assessment in enumerate(assessments):
        conclusion = (
            "通过：批准 IP 角色清晰可见并参与正文块场景；未发现可读文字、Logo、二维码或水印。"
            if assessment == "pass"
            else "未通过：IP 可见性或禁用元素检查存在问题；未追加付费调用。"
        )
        lines.append(f"- body-{ordinal:02d}.jpg：{conclusion}")
    lines.extend(("", "结论：" + ("三张均通过。" if passed else "存在未通过图片。"), ""))
    (output_dir / "visual-inspection.md").write_text("\n".join(lines), encoding="utf-8")
    readme_path = output_dir / "README.md"
    readme = readme_path.read_text(encoding="utf-8").replace(
        "- IP 可见性：需结合 `visual-inspection.md` 的本地视觉检查结论",
        "- IP 可见性：三张本地视觉检查均通过"
        if passed
        else "- IP 可见性：存在未通过项，详见 `visual-inspection.md`",
    )
    readme_path.write_text(readme, encoding="utf-8")
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["visual_quality_status"] = "passed" if passed else "failed"
    payload = tuple(
        sorted(
            (
                path
                for path in output_dir.rglob("*")
                if path.is_file() and path.name != "manifest.json" and path.suffix != ".zip"
            ),
            key=lambda path: path.relative_to(output_dir).as_posix(),
        )
    )
    manifest["files"] = [
        {
            "path": path.relative_to(output_dir).as_posix(),
            "byte_size": path.stat().st_size,
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }
        for path in payload
    ]
    _safe_json(manifest_path, manifest)
    _zip_bundle(output_dir)


def _finalize(
    output_dir: Path,
    *,
    run_id: UUID,
    article: StoredOfficialAccountArticle,
    render: StoredOfficialAccountRender,
    evidence: tuple[EvidenceSnapshot, EvidenceSnapshot],
    source_calls: int,
    visual_rows: list[dict[str, Any]],
) -> None:
    resolved = render.canonical_html
    for ordinal in range(PAID_CALL_LIMIT):
        token = body_media_placeholder(ordinal)
        if resolved.count(token) != 1:
            raise ValueError("rendered article placeholder set is invalid")
        resolved = resolved.replace(token, f"assets/body-{ordinal:02d}.jpg")
    if "__OFFICIAL_ACCOUNT_BODY_MEDIA_" in resolved:
        raise ValueError("resolved article still contains a body-media placeholder")
    (output_dir / "article-body.html").write_text(resolved, encoding="utf-8")
    (output_dir / "preview.html").write_text(_preview_document(resolved), encoding="utf-8")
    (output_dir / "article.md").write_text(_article_markdown(article), encoding="utf-8")
    _safe_json(
        output_dir / "evidence.json",
        {
            "version": "official-account-news-evidence-snapshot-v1",
            "fact_brand_boundary": "external facts use evidence; family advice is interpretation",
            "sources": [asdict(item) for item in evidence],
            "claims": [claim.model_dump(mode="json") for claim in article.article.claims],
        },
    )
    _safe_json(output_dir / "visual-map.json", {"visuals": visual_rows})
    _safe_json(
        output_dir / "run.json",
        {
            "version": REPORT_VERSION,
            "run_id": str(run_id),
            "status": "ready",
            "simulation": True,
            "published": False,
            "manual_review_status": "pending",
            "provider": "toapis",
            "model": get_settings().image_model,
            "source_fetch_calls_in_run": source_calls,
            "paid_generation_call_limit": PAID_CALL_LIMIT,
            "paid_generation_calls_attempted": len(visual_rows),
            "paid_generation_calls_succeeded": len(visual_rows),
            "article_provider_calls": 0,
            "embedding_provider_calls": 0,
            "comfly_calls": 0,
            "wechat_calls": 0,
            "wecom_calls": 0,
            "publish_calls": 0,
            "content_fingerprint": article.article.content_fingerprint,
            "render_fingerprint": render.render_fingerprint,
            "ip_visibility_assessment": "pending_local_visual_inspection",
        },
    )
    (output_dir / "README.md").write_text(
        "# 教育部新闻 × 小赛 IP 公众号本地全流程\n\n"
        "本目录是新增版本，不替换任何历史 run 或输出。文章事实只绑定两条教育部权威来源；"
        "家庭行动建议明确标记为解释。三张正文图分别使用一个 manifest-approved 公司 IP 参考，"
        "通过 ToApis 单参考路径生成并规范为 1536×1024、3:2、无元数据 JPEG。\n\n"
        "- 状态：ready（本地模拟，未同步公众号）\n"
        "- 付费生图：3 次尝试 / 3 次成功 / 每图 1 次 / 无隐藏重试\n"
        "- Comfly、文章模型、Embedding、微信、企微、发布：0 次\n"
        "- IP 可见性：需结合 `visual-inspection.md` 的本地视觉检查结论\n",
        encoding="utf-8",
    )
    payload = tuple(
        sorted(
            (path for path in output_dir.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(output_dir).as_posix(),
        )
    )
    _safe_json(
        output_dir / "manifest.json",
        {
            "version": REPORT_VERSION,
            "run_id": str(run_id),
            "status": "ready",
            "simulation": True,
            "published": False,
            "sources": [item.canonical_url for item in evidence],
            "files": [
                {
                    "path": path.relative_to(output_dir).as_posix(),
                    "byte_size": path.stat().st_size,
                    "sha256": sha256(path.read_bytes()).hexdigest(),
                }
                for path in payload
            ],
        },
    )
    _zip_bundle(output_dir)


async def run(
    output_dir: Path,
    *,
    news_html: Path | None = None,
    plan_html: Path | None = None,
) -> bool:
    settings = _preflight(get_settings(), output_dir)
    news, plan_source, source_calls = await load_evidence(
        news_html=news_html,
        plan_html=plan_html,
    )
    evidence = (news, plan_source)
    article = _article(evidence)
    render = _render(article)
    references = await _references(settings)
    if len(references) != PAID_CALL_LIMIT:
        raise ValueError("news-IP reference count does not match the paid-call limit")
    run_id = uuid5(
        NAMESPACE_URL,
        f"{REPORT_VERSION}:{article.article.content_fingerprint}:"
        f"{OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION}:toapis",
    )
    await asyncio.to_thread(_create_output_dir, output_dir)
    _safe_json(
        output_dir / "source-snapshot.intent.json",
        {
            "version": REPORT_VERSION,
            "run_id": str(run_id),
            "status": "evidence_bound",
            "source_fingerprints": [item.document_sha256 for item in evidence],
        },
        exclusive=True,
    )
    visual_rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(follow_redirects=False) as client:
        generator = create_image_generator(settings, client=client)
        for ordinal, (reference, reference_bytes) in enumerate(references):
            visual_plan = plan_generated_body_visual(
                run_id=run_id,
                article=article,
                render=render,
                ordinal=ordinal,
                reference=reference,
                provider="toapis",
                model=settings.image_model,
                reference_bytes=reference_bytes,
                plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
                prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
            )
            prompt = build_generated_visual_prompt(
                article=article,
                section_index=visual_plan.section_index,
                reference=reference,
                prompt_version=visual_plan.prompt_version,
                block_index=visual_plan.block_index,
            )
            _write_intent(output_dir, ordinal=ordinal, plan=visual_plan)
            request = ImageGenerationRequest(
                run_id=run_id,
                draft_version_id=article.id,
                prompt=prompt,
                request_fingerprint=visual_plan.request_fingerprint,
                references=(
                    ImageReference(
                        role="approved_ip_reference",
                        asset_id=visual_plan.reference_asset_ref,
                        filename=f"approved-ip-reference-{ordinal}.jpg",
                        sha256=visual_plan.reference_publication_checksum,
                        image_bytes=reference_bytes,
                        selection_reason="approved_catalog_visible_ip_v3",
                        input_normalization_version=(
                            visual_plan.reference_input_version or IMAGE_REFERENCE_INPUT_V2
                        ),
                        provider_input_sha256=visual_plan.reference_input_checksum,
                    ),
                ),
                reference_mode="single_reference",
            )
            try:
                generated = await generator.generate(request)
                if generated.attempts != 1:
                    raise ImageOutputValidationError("image_output_invalid")
                publication = prepare_generated_visual_result(
                    result=generated,
                    plan=visual_plan,
                    max_bytes=settings.image_max_download_bytes,
                )
            except AppError as error:
                failure_state = (
                    "result_unknown" if error.code == "image_provider_timeout" else "failed"
                )
                _write_failed_result(
                    output_dir,
                    ordinal=ordinal,
                    plan=visual_plan,
                    state=failure_state,
                    safe_error_code=error.code,
                )
                _safe_json(
                    output_dir / "run.json",
                    {
                        "version": REPORT_VERSION,
                        "run_id": str(run_id),
                        "status": failure_state,
                        "simulation": True,
                        "published": False,
                        "provider": "toapis",
                        "model": settings.image_model,
                        "safe_error_code": error.code,
                        "paid_generation_calls_attempted": ordinal + 1,
                        "paid_generation_calls_succeeded": len(visual_rows),
                        "paid_generation_call_limit": PAID_CALL_LIMIT,
                        "automatic_retry_permitted": False,
                        "article_provider_calls": 0,
                        "embedding_provider_calls": 0,
                        "comfly_calls": 0,
                        "wechat_calls": 0,
                        "wecom_calls": 0,
                        "publish_calls": 0,
                    },
                )
                return False
            image_path = output_dir / "assets" / f"body-{ordinal:02d}.jpg"
            with image_path.open("xb") as stream:
                stream.write(publication.image_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            output = _validate_jpeg(publication.image_bytes)
            row = {
                "ordinal": ordinal,
                "section_index": visual_plan.section_index,
                "block_index": visual_plan.block_index,
                "block_kind": visual_plan.block_kind,
                "block_fingerprint": visual_plan.block_fingerprint,
                "semantic_alt": generated_visual_alt_text(article=article, plan=visual_plan),
                "reference_public_ref": visual_plan.reference_asset_ref,
                "reference_catalog_version": visual_plan.reference_catalog_version,
                "reference_input_version": visual_plan.reference_input_version,
                "reference_input_sha256": visual_plan.reference_input_checksum,
                "plan_version": visual_plan.plan_version,
                "prompt_version": visual_plan.prompt_version,
                "output_profile_version": visual_plan.output_profile_version,
                "request_fingerprint": visual_plan.request_fingerprint,
                "output": output,
                "provider_attempts": generated.attempts,
                "automatic_retry_permitted": False,
                "ip_prompt_contract": "mandatory_visible_protagonist",
                "ip_visibility_assessment": "pending_local_visual_inspection",
            }
            visual_rows.append(row)
            _safe_json(output_dir / "intents" / f"body-{ordinal}.result.json", row, exclusive=True)
    _finalize(
        output_dir,
        run_id=run_id,
        article=article,
        render=render,
        evidence=evidence,
        source_calls=source_calls,
        visual_rows=visual_rows,
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the news-backed visible-IP ToApis demo")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--news-html", type=Path)
    parser.add_argument("--plan-html", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--record-visual-inspection",
        nargs=3,
        choices=("pass", "fail"),
        metavar=("BODY0", "BODY1", "BODY2"),
    )
    args = parser.parse_args()
    try:
        if args.record_visual_inspection is not None:
            record_visual_inspection(
                args.output_dir,
                (
                    args.record_visual_inspection[0],
                    args.record_visual_inspection[1],
                    args.record_visual_inspection[2],
                ),
            )
            print("official_account_news_ip_demo visual_inspection_recorded")
            return
        settings = _preflight(get_settings(), args.output_dir)
        if args.preflight_only:
            evidence = asyncio.run(
                load_evidence(news_html=args.news_html, plan_html=args.plan_html)
            )
            references = asyncio.run(_references(settings))
            print(
                "official_account_news_ip_demo preflight_passed "
                f"sources={len(evidence[:2])} catalog_refs={len(references)} "
                "provider=toapis attempts_per_image=1 paid_call_limit=3"
            )
            return
        succeeded = asyncio.run(
            run(args.output_dir, news_html=args.news_html, plan_html=args.plan_html)
        )
    except (FileExistsError, ValueError, RuntimeError):
        print("official_account_news_ip_demo preflight_failed")
        raise SystemExit(2) from None
    if not succeeded:
        print("official_account_news_ip_demo provider_failed automatic_retry=false")
        raise SystemExit(1)
    print("official_account_news_ip_demo ready paid_calls=3 retries=0")


if __name__ == "__main__":
    main()
