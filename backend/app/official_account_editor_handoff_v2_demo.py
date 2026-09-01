"""Build the deterministic local news/IP V2 editor-handoff acceptance fixture."""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional fixture copy.

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Literal, cast
from uuid import UUID, uuid5

from PIL import Image, UnidentifiedImageError

from app.application.ports.image_generation import ImageReference
from app.application.ports.official_account_local import (
    OfficialAccountGenerationRequest,
    OfficialAccountMediaResult,
    OfficialAccountSourceMedia,
    OfficialAccountVersionIdentity,
    StoredOfficialAccountArticle,
    StoredOfficialAccountRender,
)
from app.application.services.official_account_editor_handoff_v2 import (
    EditorHandoffV2Artifact,
    bind_editor_handoff_v2_mobile_validation,
    build_editor_handoff_v2_artifact,
    write_editor_handoff_v2_artifact,
)
from app.application.services.official_account_local import (
    article_version_bundle,
    run_request_fingerprint,
)
from app.application.services.official_account_visual_generation import (
    plan_generated_body_visual,
)
from app.domain.image_provider_input import normalize_image_provider_reference
from app.domain.official_account_editor_handoff_v2 import (
    BodyVisualLineage,
    BodyVisualReferenceProjection,
    EditorHandoffMobileValidation,
    EditorHandoffRelease,
    fingerprint_v2,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V3_VERSION,
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
    OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION,
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V6_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
    OFFICIAL_ACCOUNT_RULE_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V6_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V6_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
    ArticleBlock,
    ArticleImageBlock,
    ArticleMediaSelectionItem,
    ArticleMediaSelectionSnapshot,
    ArticleNewsContextMediaItem,
    ArticleNewsContextMediaSnapshot,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleSourceProjection,
    GeneratedArticleClaim,
    OfficialAccountEvidence,
    OfficialAccountSourceSnapshot,
    RenderedOfficialAccountHtml,
    SemanticMediaCandidate,
    article_package_fingerprint,
    assign_semantic_body_media,
    build_article_package,
    fingerprint,
    render_wechat_html,
    validate_article_package,
)
from app.infrastructure.official_account_local import (
    FIXTURE_COVER_PUBLICATION_BYTE_SIZE,
    FIXTURE_COVER_PUBLICATION_MEDIA_TYPE,
    FIXTURE_COVER_PUBLICATION_SHA256,
    DeterministicFakeOfficialAccountArticleGenerator,
    fixture_cover_publication_path,
    fixture_source_snapshot,
)

_NAMESPACE = UUID("6b67a340-0d34-4b97-aec8-6dd544210bbd")
_RUN_ID = uuid5(_NAMESPACE, "official-account-editor-handoff-v2-news-fixture")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_NEWS_DIR = (
    _REPOSITORY_ROOT / "output/official-account-news-ip-editorial-news-context-20260825-v6"
)
_DEFAULT_BODY_VISUAL_DIR = (
    _REPOSITORY_ROOT
    / "output/official-account-editor-handoff-v2-reference-conditioned-source-20260827"
)
_FOUNDATION_EDUCATION_EVIDENCE_ID = uuid5(_NAMESPACE, "moe-foundation-education-meeting")
_AI_EDUCATION_EVIDENCE_ID = uuid5(_NAMESPACE, "moe-ai-education-action-plan")
_FOUNDATION_EDUCATION_SOURCE_URL = (
    "https://www.moe.gov.cn/jyb_xwfb/s6052/moe_838/202607/t20260722_1444692.html"
)
_AI_EDUCATION_SOURCE_URL = (
    "https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/t20260410_1433382.html"
)


@dataclass(frozen=True, slots=True)
class _NewsPhoto:
    path: Path
    sha256: str
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    width: int
    height: int
    alt_text: str
    caption: str
    credit: str
    source_page_url: str


@dataclass(frozen=True, slots=True)
class _BodyVisualSource:
    catalog_version: str
    ordinal: int
    section_index: int
    block_index: int
    block_kind: Literal["paragraph", "bullet_list", "quote", "callout"]
    block_fingerprint: str
    scene_brief: str
    body: bytes
    output_sha256: str
    output_byte_size: int
    reference_body: bytes
    reference_public_ref: str
    reference_role: Literal["action_reference", "identity_reference"]
    reference_characters: tuple[Literal["xiao-sai", "sai-xiansheng"], ...]
    reference_source_checksum: str
    reference_publication_checksum: str
    reference_input_version: str
    reference_input_checksum: str
    visible_characters: tuple[Literal["xiao-sai", "sai-xiansheng"], ...]
    visibility_status: Literal["passed_local_visual_inspection"]


async def build_demo_artifact(
    *,
    news_context_directory: Path = _DEFAULT_NEWS_DIR,
    body_visual_directory: Path = _DEFAULT_BODY_VISUAL_DIR,
    browser_report: Path | None = None,
) -> EditorHandoffV2Artifact:
    """Build one zero-network V2 artifact from frozen reference-conditioned outputs."""
    body_visual_sources = _load_body_visual_sources(body_visual_directory)
    source = _demo_source_snapshot()
    identity = _identity()
    request_fingerprint = run_request_fingerprint(
        source_fingerprint=source.source_fingerprint,
        generation_mode="fixture",
        identity=identity,
    )
    base_identity = _base_identity()
    base_request_fingerprint = run_request_fingerprint(
        source_fingerprint=source.source_fingerprint,
        generation_mode="fixture",
        identity=base_identity,
    )
    generated = await DeterministicFakeOfficialAccountArticleGenerator().generate(
        OfficialAccountGenerationRequest(
            run_id=_RUN_ID,
            source=source,
            identity=base_identity,
            request_fingerprint=base_request_fingerprint,
            max_output_tokens=8_192,
        )
    )
    assignments = assign_semantic_body_media(
        sections=generated.draft.sections,
        candidates=tuple(
            SemanticMediaCandidate(
                candidate_id=item.reference_public_ref,
                sha256=item.reference_publication_checksum,
                semantic_label=item.scene_brief,
                semantic_tags=_body_visual_semantic_tags(item),
                alt_text=item.scene_brief,
                caption_text="按当前正文块生成的小赛 IP 场景插画",
                publication_priority=item.ordinal,
            )
            for item in body_visual_sources
        ),
    )
    if tuple((item.ordinal, item.section_index) for item in assignments) != tuple(
        (item.ordinal, item.section_index) for item in body_visual_sources
    ):
        raise ValueError("body-visual reference assignment changed")
    article = build_article_package(
        draft=generated.draft,
        source=source,
        versions=article_version_bundle(base_identity),
        default_author=base_identity.default_author,
        body_media_candidate_count=3,
        semantic_media_assignments=assignments,
    )
    photos = _load_news_photos(news_context_directory)
    context_items = tuple(
        ArticleNewsContextMediaItem(
            ordinal=ordinal,
            section_index=(0, 2)[ordinal],
            source_article_image_id=uuid5(_NAMESPACE, f"news-photo-{ordinal}"),
            sha256=photo.sha256,
            media_type=photo.media_type,
            width=photo.width,
            height=photo.height,
            alt_text=photo.alt_text,
            caption=photo.caption,
            credit=photo.credit,
            source_page_url=photo.source_page_url,
            rights_status="publish_permission_unverified",
            context_only_not_evidence=True,
        )
        for ordinal, photo in enumerate(photos)
    )
    article = article.model_copy(
        update={
            "versions": article_version_bundle(identity),
            "media_selection": ArticleMediaSelectionSnapshot(
                media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                visual_query_version=OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
                visual_selector_version=OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
                status="semantic_unavailable",
                closed_reason="disabled",
                catalog_version=body_visual_sources[0].catalog_version,
                catalog_fingerprint=fingerprint_v2(
                    "reference-conditioned-body-visual-source-v1",
                    tuple(item.reference_public_ref for item in body_visual_sources),
                ),
                assignments=tuple(
                    ArticleMediaSelectionItem(
                        ordinal=item.ordinal,
                        section_index=item.section_index,
                        candidate_ref=body_visual_sources[item.ordinal].reference_public_ref,
                        source_checksum=(
                            body_visual_sources[item.ordinal].reference_source_checksum
                        ),
                        publication_checksum=(
                            body_visual_sources[item.ordinal].reference_publication_checksum
                        ),
                        selection_method="deterministic_tag",
                        reason_code=item.reason_code,
                        similarity_band=None,
                    )
                    for item in assignments
                ),
            ),
            "news_context_media": ArticleNewsContextMediaSnapshot(
                selection_version=OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
                status="ready" if len(context_items) == 2 else "partial",
                items=context_items,
            ),
        }
    )
    article = _add_source_bound_news_context(article)
    article = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    article = ArticlePackage.model_validate(article.model_dump(mode="python"))
    validation_issues = validate_article_package(
        article,
        source=source,
        default_author=identity.default_author,
        min_characters=identity.min_characters,
        target_min_characters=identity.target_min_characters,
        target_max_characters=identity.target_max_characters,
        max_characters=identity.max_characters,
    )
    if any(issue.severity == "error" for issue in validation_issues):
        raise ValueError(f"V2 demo article validation failed: {validation_issues!r}")
    rendered = render_wechat_html(article)
    body_visuals = _build_body_visual_lineages(
        article=article,
        rendered=rendered,
        sources=body_visual_sources,
    )
    media = _media_rows(article=article, photos=photos, body_visuals=body_visual_sources)
    draft_request = fingerprint_v2("local-fixture-draft", request_fingerprint)
    draft_resolved = fingerprint(
        rendered.render_fingerprint, draft_request, rendered.canonical_html
    )
    release = EditorHandoffRelease(
        policy="quality_auto",
        kind="machine",
        input_fingerprint=fingerprint_v2(
            "fixture-machine-release",
            request_fingerprint,
            article.content_fingerprint,
            tuple((item.sha256, len(body)) for item, body in media),
        ),
        gate_codes=(
            "run_ready",
            "deterministic_validation_passed",
            "model_audit_accepted",
            "image_validation_passed",
            "image_audit_accepted",
            "generated_visuals_ready",
        ),
    )
    artifact = build_editor_handoff_v2_artifact(
        run_id=_RUN_ID,
        run_request_fingerprint=request_fingerprint,
        article=article,
        release=release,
        review=None,
        draft_resolved_fingerprint=draft_resolved,
        media=media,
        body_visuals=body_visuals,
        eligibility_checks=(),
    )
    if browser_report is not None:
        artifact = bind_editor_handoff_v2_mobile_validation(
            artifact, _load_browser_report(browser_report)
        )
    return artifact


def _identity() -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider="fake",
        model="official-account-fixture-v2-news-context",
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
        audit_schema_version=OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_VERSION,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
        visual_query_version=OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
        visual_selector_version=OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
        context_media_plan_version=OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
        default_author="赛先生",
        min_characters=1_200,
        target_min_characters=1_800,
        target_max_characters=2_600,
        max_characters=4_000,
    )


def _demo_source_snapshot() -> OfficialAccountSourceSnapshot:
    base = fixture_source_snapshot(multi_image=True, semantic_media=True)
    evidence = (
        OfficialAccountEvidence(
            evidence_id=_FOUNDATION_EDUCATION_EVIDENCE_ID,
            source_url=_FOUNDATION_EDUCATION_SOURCE_URL,
            source_name="教育部｜全国基础教育工作会议在京召开",
            source_tier="official",
            exact_quote=(
                "7月22日，全国基础教育工作会议在北京召开。中共中央政治局常委、"
                "国务院副总理丁薛祥出席会议并讲话。"
            ),
        ),
        OfficialAccountEvidence(
            evidence_id=_AI_EDUCATION_EVIDENCE_ID,
            source_url=_AI_EDUCATION_SOURCE_URL,
            source_name="教育部｜介绍《“人工智能+教育”行动计划》有关情况",
            source_tier="official",
            exact_quote="教育部召开新闻发布会介绍《“人工智能+教育”行动计划》有关情况。",
        ),
    )
    return base.model_copy(
        update={
            "source_fingerprint": fingerprint(
                "official-account-editor-handoff-v2-news-source-v1",
                tuple(item.model_dump(mode="json") for item in evidence),
                tuple(item.model_dump(mode="json") for item in base.brand_context),
            ),
            "topic_summary": (
                "从基础教育工作会议与“人工智能+教育”行动计划的权威信息出发，"
                "讨论家庭如何用观察、验证和复盘支持孩子的科学探究。"
            ),
            "evidence": evidence,
        }
    )


def _add_source_bound_news_context(article: ArticlePackage) -> ArticlePackage:
    additions = {
        0: (
            "7月22日，全国基础教育工作会议在北京召开。把这则教育改革动态放回"
            "家庭日常，值得追问的不是再给孩子增加多少任务，而是怎样让一次观察、"
            "一次提问真正走向有证据的学习。"
        ),
        2: (
            "教育部召开新闻发布会介绍《“人工智能+教育”行动计划》有关情况。"
            "工具进入教育现场之后，家庭里的小实验更需要守住一条清楚的线："
            "AI可以协助整理信息，观察、判断和表达仍要由孩子完成。"
        ),
    }
    news_claim_refs = {
        0: ("news-foundation-education",),
        2: ("news-ai-education",),
    }

    def normalize_fixture_wording(block: ArticleBlock) -> ArticleBlock:
        if not isinstance(block, ArticleParagraphBlock):
            return block
        text = block.text.replace(
            "脱敏示例材料提醒我们，一次完整的科学探究通常包含",
            "本文把一次完整的科学探究理解为",
        ).replace(
            "也对应了示例材料中描述的完整探究过程",
            "也串起了前文梳理的完整探究过程",
        )
        return block.model_copy(update={"text": text})

    sections = tuple(
        section.model_copy(
            update={
                "blocks": (
                    *tuple(normalize_fixture_wording(block) for block in section.blocks[:1]),
                    ArticleParagraphBlock(
                        kind="paragraph",
                        text=additions[section_index],
                        claim_refs=news_claim_refs[section_index],
                    ),
                    *tuple(normalize_fixture_wording(block) for block in section.blocks[1:]),
                )
            }
        )
        if section_index in additions
        else section.model_copy(
            update={"blocks": tuple(normalize_fixture_wording(block) for block in section.blocks)}
        )
        for section_index, section in enumerate(article.sections)
    )
    claims = (
        *(
            claim.model_copy(
                update={
                    "text": "本文将观察、提问、验证与复盘作为家庭科学探究的编辑框架。",
                    "kind": "opinion",
                    "evidence_ids": (),
                }
            )
            if claim.id == "fact-1"
            else claim
            for claim in article.claims
        ),
        GeneratedArticleClaim(
            id="news-foundation-education",
            text="7月22日，全国基础教育工作会议在北京召开。",
            kind="external_fact",
            evidence_ids=(_FOUNDATION_EDUCATION_EVIDENCE_ID,),
        ),
        GeneratedArticleClaim(
            id="news-ai-education",
            text="教育部召开新闻发布会介绍《“人工智能+教育”行动计划》有关情况。",
            kind="external_fact",
            evidence_ids=(_AI_EDUCATION_EVIDENCE_ID,),
        ),
    )
    sources = (
        ArticleSourceProjection(
            evidence_id=_FOUNDATION_EDUCATION_EVIDENCE_ID,
            source_name="教育部｜全国基础教育工作会议在京召开",
            source_url=_FOUNDATION_EDUCATION_SOURCE_URL,
            source_tier="official",
        ),
        ArticleSourceProjection(
            evidence_id=_AI_EDUCATION_EVIDENCE_ID,
            source_name="教育部｜介绍《“人工智能+教育”行动计划》有关情况",
            source_url=_AI_EDUCATION_SOURCE_URL,
            source_tier="official",
        ),
    )
    return article.model_copy(update={"sections": sections, "claims": claims, "sources": sources})


def _base_identity() -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider="fake",
        model="official-account-fixture-v1",
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V3_VERSION,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION,
        audit_schema_version=OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_VERSION,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V6_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V6_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V6_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
        default_author="赛先生",
        min_characters=1_200,
        target_min_characters=1_800,
        target_max_characters=2_600,
        max_characters=4_000,
    )


def _load_news_photos(directory: Path) -> tuple[_NewsPhoto, ...]:
    root = directory.expanduser().resolve()
    provenance_path = root / "news-photo-provenance.json"
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    if payload.get("version") != "official-account-news-context-photo-provenance-v1":
        raise ValueError("news photo provenance version is unsupported")
    rows = payload.get("photos")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2:
        raise ValueError("news photo provenance requires one or two photos")
    photos: list[_NewsPhoto] = []
    for ordinal, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("news photo provenance row is invalid")
        relative = PurePosixPath(str(row.get("local_path", "")))
        if (
            relative.is_absolute()
            or not relative.parts
            or relative.parts[0] != "assets"
            or ".." in relative.parts
            or "." in relative.parts
        ):
            raise ValueError("news photo fixture path is unsafe")
        path = root.joinpath(*relative.parts)
        if not path.is_file() or path.is_symlink():
            raise ValueError("news photo fixture is missing or symlinked")
        body = path.read_bytes()
        expected_sha = str(row.get("sha256", ""))
        if sha256(body).hexdigest() != expected_sha or len(body) != int(row.get("byte_size", 0)):
            raise ValueError("news photo fixture integrity changed")
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            media_type = {
                "JPEG": "image/jpeg",
                "PNG": "image/png",
                "WEBP": "image/webp",
            }.get(image.format or "")
        if (
            media_type != row.get("media_type")
            or width != int(row.get("width", 0))
            or height != int(row.get("height", 0))
        ):
            raise ValueError("news photo dimensions or media type changed")
        photos.append(
            _NewsPhoto(
                path=path,
                sha256=expected_sha,
                media_type=cast(Literal["image/jpeg", "image/png", "image/webp"], media_type),
                width=width,
                height=height,
                alt_text=str(row.get("alt_text", "")),
                caption=str(row.get("caption", "")),
                credit=str(row.get("credit", "")),
                source_page_url=str(row.get("source_page_url", "")),
            )
        )
        if ordinal > 1:  # pragma: no cover - bounded above
            raise ValueError("too many news photos")
    return tuple(photos)


def _load_body_visual_sources(directory: Path) -> tuple[_BodyVisualSource, ...]:
    """Load the frozen demo source without accepting private or unverifiable lineage."""

    expanded = directory.expanduser()
    if _path_has_symlink_component(expanded):
        raise ValueError("body-visual source directory is symlinked")
    root = expanded.resolve()
    map_path = root / "visual-map.json"
    if not map_path.is_file() or _path_has_symlink_component(map_path):
        raise ValueError("body-visual source map is missing or symlinked")
    raw_map = map_path.read_bytes()
    if not 2 <= len(raw_map) <= 64 * 1024:
        raise ValueError("body-visual source map is outside bounds")
    try:
        payload = json.loads(raw_map, object_pairs_hook=_reject_duplicate_json_fields)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("body-visual source map is invalid") from error
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "catalog_version",
        "selection_execution",
        "generation_execution",
        "visuals",
    }:
        raise ValueError("body-visual source map fields are invalid")
    if payload["schema_version"] != "official-account-editor-handoff-body-visual-source-v1":
        raise ValueError("body-visual source map version is unsupported")
    catalog_version = payload["catalog_version"]
    if not isinstance(catalog_version, str) or not 1 <= len(catalog_version) <= 80:
        raise ValueError("body-visual catalog version is invalid")
    if payload["selection_execution"] != {
        "method": "deterministic_fixture_semantic",
        "reason_code": "approved_reference_exact_block_fixture_selection",
        "embedding_provider_calls": 0,
    }:
        raise ValueError("body-visual fixture selection truth changed")
    if payload["generation_execution"] != {
        "kind": "built_in_imagegen_reference_conditioned",
        "provider_call_claim": "authorized_local_generation_completed",
        "image_generation_calls": 3,
        "wechat_calls": 0,
        "wecom_calls": 0,
        "publish_calls": 0,
    }:
        raise ValueError("body-visual fixture execution truth changed")
    rows = payload["visuals"]
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("body-visual source requires exactly three outputs")

    sources: list[_BodyVisualSource] = []
    expected_locations = ((0, 0, 0), (1, 2, 0), (2, 3, 0))
    for row, expected in zip(rows, expected_locations, strict=True):
        if not isinstance(row, dict) or set(row) != {
            "ordinal",
            "section_index",
            "block_index",
            "block_kind",
            "block_fingerprint",
            "scene_brief",
            "asset",
            "media_type",
            "byte_size",
            "width",
            "height",
            "output_sha256",
            "visible_characters",
            "visibility_status",
            "reference",
        }:
            raise ValueError("body-visual source row fields are invalid")
        if (row["ordinal"], row["section_index"], row["block_index"]) != expected:
            raise ValueError("body-visual source block locations changed")
        if row["block_kind"] != "paragraph" or not _is_sha256(row["block_fingerprint"]):
            raise ValueError("body-visual source block identity is invalid")
        if not isinstance(row["scene_brief"], str) or not 8 <= len(row["scene_brief"]) <= 480:
            raise ValueError("body-visual scene brief is invalid")
        body = _load_body_visual_image(
            root=root,
            relative_value=row["asset"],
            expected_prefix="assets",
            expected_ordinal=expected[0],
            expected_sha=row["output_sha256"],
            expected_size=row["byte_size"],
        )
        if row["media_type"] != "image/jpeg" or row["width"] != 1_536 or row["height"] != 1_024:
            raise ValueError("body-visual publication profile changed")
        reference = row["reference"]
        if not isinstance(reference, dict) or set(reference) != {
            "asset",
            "public_ref",
            "role",
            "characters",
            "source_checksum",
            "publication_checksum",
            "input_version",
            "input_checksum",
        }:
            raise ValueError("body-visual reference fields are invalid")
        if (
            not _is_public_ref(reference["public_ref"])
            or reference["role"] not in {"action_reference", "identity_reference"}
            or not _is_sha256(reference["source_checksum"])
            or not _is_sha256(reference["publication_checksum"])
            or not _is_sha256(reference["input_checksum"])
            or reference["input_version"] != "image-reference-input-v2-png-preserve-jpeg-normalize"
        ):
            raise ValueError("body-visual reference identity is invalid")
        reference_body = _load_body_visual_image(
            root=root,
            relative_value=reference["asset"],
            expected_prefix="references",
            expected_ordinal=expected[0],
            expected_sha=reference["publication_checksum"],
            expected_size=None,
        )
        normalized = normalize_image_provider_reference(
            reference_body,
            version=cast(str, reference["input_version"]),
        )
        if normalized.sha256 != reference["input_checksum"]:
            raise ValueError("body-visual provider reference input changed")
        reference_characters = _character_labels(reference["characters"])
        visible_characters = _character_labels(row["visible_characters"])
        if row["visibility_status"] != "passed_local_visual_inspection" or set(
            visible_characters
        ) != {"xiao-sai", "sai-xiansheng"}:
            raise ValueError("body-visual visible IP evidence is incomplete")
        sources.append(
            _BodyVisualSource(
                catalog_version=catalog_version,
                ordinal=row["ordinal"],
                section_index=row["section_index"],
                block_index=row["block_index"],
                block_kind=row["block_kind"],
                block_fingerprint=row["block_fingerprint"],
                scene_brief=row["scene_brief"],
                body=body,
                output_sha256=row["output_sha256"],
                output_byte_size=row["byte_size"],
                reference_body=reference_body,
                reference_public_ref=reference["public_ref"],
                reference_role=reference["role"],
                reference_characters=reference_characters,
                reference_source_checksum=reference["source_checksum"],
                reference_publication_checksum=reference["publication_checksum"],
                reference_input_version=reference["input_version"],
                reference_input_checksum=reference["input_checksum"],
                visible_characters=visible_characters,
                visibility_status=row["visibility_status"],
            )
        )
    if (
        len({item.output_sha256 for item in sources}) != 3
        or len({item.reference_public_ref for item in sources}) != 3
        or len({item.reference_publication_checksum for item in sources}) != 3
        or len({item.reference_input_checksum for item in sources}) != 3
    ):
        raise ValueError("body-visual outputs and references must be distinct")
    return tuple(sources)


def _load_body_visual_image(
    *,
    root: Path,
    relative_value: object,
    expected_prefix: Literal["assets", "references"],
    expected_ordinal: int,
    expected_sha: object,
    expected_size: object | None,
) -> bytes:
    relative = PurePosixPath(str(relative_value))
    if relative.is_absolute() or relative.parts != (
        expected_prefix,
        f"{'body' if expected_prefix == 'assets' else 'reference'}-{expected_ordinal:02d}.jpg",
    ):
        raise ValueError("body-visual fixture path is unsafe")
    path = root.joinpath(*relative.parts)
    if not path.is_file() or _path_has_symlink_component(path):
        raise ValueError("body-visual fixture image is missing or symlinked")
    body = path.read_bytes()
    if (
        not _is_sha256(expected_sha)
        or sha256(body).hexdigest() != expected_sha
        or (expected_size is not None and len(body) != expected_size)
        or not 24 <= len(body) <= 15 * 1024 * 1024
    ):
        raise ValueError("body-visual fixture image integrity changed")
    try:
        with Image.open(BytesIO(body)) as image:
            image.load()
            width, height = image.size
            invalid_dimensions = (
                image.size != (1_536, 1_024)
                if expected_prefix == "assets"
                else (
                    min(width, height) < 256
                    or max(width, height) > 1_536
                    or width / height > 3
                    or height / width > 3
                )
            )
            if image.format != "JPEG" or invalid_dimensions:
                raise ValueError("body-visual fixture image profile changed")
            structural_info = {"jfif", "jfif_version", "jfif_unit", "jfif_density"}
            if image.getexif() or set(image.info).difference(structural_info):
                raise ValueError("body-visual fixture image contains retained metadata")
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("body-visual fixture image cannot be decoded") from error
    return body


def _path_has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    return any(component.is_symlink() for component in (absolute, *absolute.parents))


def _reject_duplicate_json_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("body-visual source map contains duplicate fields")
        result[key] = value
    return result


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_public_ref(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 16
        and all(character in "0123456789abcdef" for character in value)
    )


def _character_labels(
    value: object,
) -> tuple[Literal["xiao-sai", "sai-xiansheng"], ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 2:
        raise ValueError("body-visual character labels are invalid")
    labels = tuple(value)
    if len(set(labels)) != len(labels) or any(
        item not in {"xiao-sai", "sai-xiansheng"} for item in labels
    ):
        raise ValueError("body-visual character labels are invalid")
    return cast(tuple[Literal["xiao-sai", "sai-xiansheng"], ...], labels)


def _body_visual_semantic_tags(item: _BodyVisualSource) -> tuple[str, ...]:
    return {
        0: ("问题", "观察", "好奇", "孩子", "植物"),
        1: ("实验", "验证", "动手", "观察", "证据"),
        2: ("证据", "记录", "资料", "判断", "复盘"),
    }[item.ordinal]


def _build_body_visual_lineages(
    *,
    article: ArticlePackage,
    rendered: RenderedOfficialAccountHtml,
    sources: tuple[_BodyVisualSource, ...],
) -> tuple[BodyVisualLineage, ...]:
    stored_article = StoredOfficialAccountArticle(
        id=uuid5(_NAMESPACE, f"v2-body-visual-article:{article.content_fingerprint}"),
        article=article,
        validation_issues=(),
        audit=None,
        provider_request_id=None,
        prompt_tokens=0,
        completion_tokens=0,
        reasoning_tokens=0,
        latency_ms=0,
        created_at=datetime(2026, 8, 27, tzinfo=UTC),
    )
    render_fingerprint = rendered.render_fingerprint
    stored_render = StoredOfficialAccountRender(
        id=uuid5(_NAMESPACE, f"v2-body-visual-render:{render_fingerprint}"),
        article_version_id=stored_article.id,
        canonical_html=rendered.canonical_html,
        render_fingerprint=render_fingerprint,
    )
    lineages: list[BodyVisualLineage] = []
    for item in sources:
        reference = OfficialAccountSourceMedia(
            source_image_artifact_id=None,
            fixture_id=f"catalog:{item.reference_public_ref}",
            media_type="image/jpeg",
            byte_size=len(item.reference_body),
            sha256=item.reference_publication_checksum,
            ordinal=item.ordinal,
            semantic_label=item.scene_brief,
            selection_reason="approved_reference_exact_block_fixture_selection",
            candidate_id=item.reference_public_ref,
            assigned_section_index=item.section_index,
            selection_method="deterministic_tag",
            similarity_band=None,
            catalog_asset_ref=item.reference_public_ref,
            catalog_version=item.catalog_version,
            source_master_sha256=item.reference_source_checksum,
        )
        plan = plan_generated_body_visual(
            run_id=_RUN_ID,
            article=stored_article,
            render=stored_render,
            ordinal=item.ordinal,
            reference=reference,
            provider="fake",
            model="official-account-v2-frozen-reference-conditioned-fixture",
            reference_bytes=item.reference_body,
        )
        provider_reference = ImageReference(
            role="approved_ip_reference",
            asset_id=plan.reference_asset_ref,
            filename=f"official-account-reference-{plan.reference_asset_ref}.jpg",
            sha256=plan.reference_publication_checksum,
            image_bytes=item.reference_body,
            selection_reason="approved_catalog_semantic_reference",
            input_normalization_version=plan.reference_input_version or "",
            provider_input_sha256=plan.reference_input_checksum,
        )
        if (
            plan.section_index != item.section_index
            or plan.block_index != item.block_index
            or plan.block_kind != item.block_kind
            or plan.block_fingerprint != item.block_fingerprint
            or plan.reference_asset_ref != item.reference_public_ref
            or plan.reference_input_version != item.reference_input_version
            or plan.reference_input_checksum != item.reference_input_checksum
            or provider_reference.sha256 != item.reference_publication_checksum
            or provider_reference.provider_input_sha256 != item.reference_input_checksum
        ):
            raise ValueError("body-visual production plan no longer matches frozen source")
        lineages.append(
            BodyVisualLineage(
                ordinal=item.ordinal,
                section_index=item.section_index,
                block_index=item.block_index,
                block_kind=item.block_kind,
                block_fingerprint=item.block_fingerprint,
                scene_brief=item.scene_brief,
                scene_brief_fingerprint=fingerprint_v2(
                    "editor-handoff-body-visual-scene-brief-v1",
                    item.section_index,
                    item.block_index,
                    item.block_kind,
                    item.scene_brief,
                ),
                reference=BodyVisualReferenceProjection(
                    public_ref=item.reference_public_ref,
                    catalog_version=item.catalog_version,
                    role=item.reference_role,
                    character_labels=item.reference_characters,
                    source_checksum=item.reference_source_checksum,
                    publication_checksum=item.reference_publication_checksum,
                    input_version=cast(
                        Literal["image-reference-input-v2-png-preserve-jpeg-normalize"],
                        item.reference_input_version,
                    ),
                    input_checksum=item.reference_input_checksum,
                ),
                selection_method="deterministic_fixture_semantic",
                similarity_band=None,
                generation_kind="frozen_reference_conditioned_fixture",
                provider_execution="authorized_local_imagegen_result",
                plan_fingerprint=plan.request_fingerprint,
                output_sha256=item.output_sha256,
                output_byte_size=item.output_byte_size,
                visible_character_labels=item.visible_characters,
                visibility_status=item.visibility_status,
            )
        )
    return tuple(lineages)


def _media_rows(
    *,
    article: ArticlePackage,
    photos: tuple[_NewsPhoto, ...],
    body_visuals: tuple[_BodyVisualSource, ...],
) -> tuple[tuple[OfficialAccountMediaResult, bytes], ...]:
    section_indexes = tuple(
        section_index
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    rows: list[tuple[OfficialAccountMediaResult, bytes]] = []
    for item in body_visuals:
        ordinal = item.ordinal
        body = item.body
        rows.append(
            (
                OfficialAccountMediaResult(
                    local_media_id=f"fixture-v2-body-{ordinal}",
                    role="body",
                    ordinal=ordinal,
                    media_url=f"/local/fixture-v2-body-{ordinal}",
                    media_type="image/jpeg",
                    byte_size=len(body),
                    sha256=item.output_sha256,
                    semantic_label=item.scene_brief,
                    selection_method="deterministic_tag",
                    selection_reason_code="frozen_fixture_reference_selection",
                    alt_text=item.scene_brief,
                    caption="按当前正文块生成的小赛 IP 场景插画",
                    assigned_section_index=section_indexes[ordinal],
                    provenance_kind="generated_visual",
                ),
                body,
            )
        )
    for ordinal, photo in enumerate(photos):
        body = photo.path.read_bytes()
        rows.append(
            (
                OfficialAccountMediaResult(
                    local_media_id=f"fixture-v2-context-{ordinal}",
                    role="context",
                    ordinal=ordinal,
                    media_url=f"/local/fixture-v2-context-{ordinal}",
                    media_type=photo.media_type,
                    byte_size=len(body),
                    sha256=photo.sha256,
                    assigned_section_index=(0, 2)[ordinal],
                    alt_text=photo.alt_text,
                    provenance_kind="source_news",
                    source_page_url=photo.source_page_url,
                    caption=photo.caption,
                    credit=photo.credit,
                    rights_status="publish_permission_unverified",
                    context_only_not_evidence=True,
                ),
                body,
            )
        )
    cover = fixture_cover_publication_path().read_bytes()
    if (
        len(cover) != FIXTURE_COVER_PUBLICATION_BYTE_SIZE
        or sha256(cover).hexdigest() != FIXTURE_COVER_PUBLICATION_SHA256
    ):
        raise ValueError("fixture cover publication bytes changed")
    rows.append(
        (
            OfficialAccountMediaResult(
                local_media_id="fixture-v2-cover-0",
                role="cover",
                ordinal=0,
                media_url="/local/fixture-v2-cover-0",
                media_type=FIXTURE_COVER_PUBLICATION_MEDIA_TYPE,
                byte_size=len(cover),
                sha256=FIXTURE_COVER_PUBLICATION_SHA256,
                provenance_kind="fixture",
            ),
            cover,
        )
    )
    return tuple(rows)


def _load_browser_report(path: Path) -> EditorHandoffMobileValidation:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") != "passed":
        raise ValueError("browser report did not pass")
    observations = payload.get("viewports")
    if not isinstance(observations, list) or len(observations) != 2:
        raise ValueError("browser report requires exact 320/430 observations")
    for expected_width, observation in zip((320, 430), observations, strict=True):
        if not isinstance(observation, dict):
            raise ValueError("browser report viewport observation is invalid")
        if (
            observation.get("viewport") != expected_width
            or observation.get("documentClientWidth") != expected_width
            or not isinstance(observation.get("imageCount"), int)
            or observation["imageCount"] < 1
            or not isinstance(observation.get("documentScrollWidth"), int)
            or observation["documentScrollWidth"] > expected_width
        ):
            raise ValueError("browser report viewport did not pass exact mobile checks")
    return EditorHandoffMobileValidation(
        status="passed",
        content_fingerprint=payload.get("content_fingerprint"),
        body_sha256=payload.get("body_sha256"),
        media_sha256s=tuple(payload.get("media_sha256s", ())),
        viewports=(320, 430),
        external_requests=payload.get("external_requests"),
        copy_root_matches_body=payload.get("copy_root_matches_body"),
    )


async def _run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--news-context-dir", type=Path, default=_DEFAULT_NEWS_DIR)
    parser.add_argument("--body-visual-dir", type=Path, default=_DEFAULT_BODY_VISUAL_DIR)
    parser.add_argument("--browser-report", type=Path)
    args = parser.parse_args()
    artifact = await build_demo_artifact(
        news_context_directory=args.news_context_dir,
        body_visual_directory=args.body_visual_dir,
        browser_report=args.browser_report,
    )
    target = write_editor_handoff_v2_artifact(artifact, args.output_dir)
    print(target)


if __name__ == "__main__":
    asyncio.run(_run())
