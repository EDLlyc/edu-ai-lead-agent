# ruff: noqa: RUF001 -- Chinese editorial copy is intentional.
"""Offline editorial repackage for the ready news-backed visible-IP bundle.

This operator-only command validates and reuses an existing local bundle. It does not read
credentials, construct provider clients, fetch sources, or call WeChat/WeCom/publish paths.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image

from app.domain.official_account_local import (
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticleMediaSlot,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQualitySummary,
    ArticleQuoteBlock,
    ArticleSection,
    ArticleSourceProjection,
    ArticleVersionBundle,
    GeneratedArticleClaim,
    article_body_character_count,
    article_package_fingerprint,
    body_media_placeholder,
    fingerprint,
)
from app.official_account_news_ip_live_demo import (
    NEWS_FETCH_URL as _NEWS_FETCH_URL,
)
from app.official_account_news_ip_live_demo import (
    NEWS_URL as _NEWS_URL,
)
from app.official_account_news_ip_live_demo import (
    PLAN_URL as _PLAN_URL,
)

NEWS_FETCH_URL = _NEWS_FETCH_URL
NEWS_URL = _NEWS_URL
PLAN_URL = _PLAN_URL
REPORT_VERSION = "official-account-news-editorial-demo-v2"
SOURCE_REPORT_VERSION = "official-account-news-ip-live-demo-v1"
SOURCE_EVIDENCE_VERSION = "official-account-news-evidence-snapshot-v1"
ARTICLE_SCHEMA_VERSION = "official-account-news-editorial-schema-v2"
RENDERER_VERSION = "wechat-news-editorial-renderer-v2-reference-learned"
STYLE_VERSION = "wechat-news-editorial-style-v2-paper"
TEMPLATE_VERSION = "wechat-news-editorial-template-v2-mobile"
REFERENCE_STUDY_VERSION = "wechat-public-reference-patterns-v1"
DEFAULT_SOURCE_DIR = Path("output/official-account-news-ip-20260824-v1")
DEFAULT_OUTPUT_DIR = Path("output/official-account-news-ip-editorial-20260824-v2")
REFERENCE_URL = "https://mp.weixin.qq.com/s/FaTvS15StljJ2DQSaRAHxw"
BODY_IMAGE_NAMES = ("body-00.jpg", "body-01.jpg", "body-02.jpg")
BODY_TARGET_MIN = 1_800
BODY_TARGET_MAX = 2_600
_MAX_JSON_BYTES = 1_000_000
_MAX_MANIFEST_FILE_BYTES = 8_000_000
_MAX_MANIFEST_TOTAL_BYTES = 32_000_000
_MAX_MANIFEST_ROWS = 64
_EXPECTED_REFERENCE_PUBLIC_REFS = (
    "33586a916bbbfbf1",
    "5c2a29bbec16ca4f",
    "09c8fd9470cb5502",
)
_EXPECTED_EVIDENCE_IDS = (
    "a611e73c-3b99-586a-8852-0ddd82d81488",
    "ef6c7101-d4f1-55b2-bdb6-0a1de6c65d5f",
)
_EXPECTED_EVIDENCE_DOCUMENT_SHA256 = (
    "0d0714514dfba079e1e370cad432389b8ab11c9bbc2a66fb6ec05cdfa28cbfb6",
    "43a66c61a1a2dcad585ab2f6167a00e5bda2e423ff804d433ddd7784f184ce22",
)
_EXPECTED_VISUAL_CONTRACT = (
    {
        "block_fingerprint": "bf1a346648d0eb0155aea5b4ad1a35d6aab124a44430579d99ba947271bd0ef6",
        "reference_input_sha256": (
            "24a48ebbc65b437ecfe577028ac6ab0f472518405c4ad066941cac14add69f4c"
        ),
        "request_fingerprint": ("1584fe6ce6bcfa9be41cfb7fff7b1578a98e99655d5757021b818c5669d12963"),
        "semantic_alt": "第 1 节“这条新闻真正改变了什么”的核心场景插画",
    },
    {
        "block_fingerprint": "43c6e3a3af07109274637a7caeb06519ba0ab67f6c23e914193e031e9f3ccaf9",
        "reference_input_sha256": (
            "c12fcf30f3c20504caf94e459e08840d078740291e7655e9bea7cf7936a680cc"
        ),
        "request_fingerprint": ("5ff744c74160bd87fd60ea81aaa2ab5ecf53f918500be59e8be9b3ecd517cfcd"),
        "semantic_alt": "第 2 节“行动计划把方向说得更具体”的核心场景插画",
    },
    {
        "block_fingerprint": "7b38447371fc0a6f0a6531f74e0194b2b93caf867f08fa70a66aed7cb0ed3f45",
        "reference_input_sha256": (
            "4ff061d29751fe85a25f8e7af9aa3dc02062d0b8c44eebf57ef760cab73446f4"
        ),
        "request_fingerprint": ("b6247a65caba98b5d3bbdf5c70b1d9dd217055ed89ed9dec26ca6f888f9a3176"),
        "semantic_alt": "第 3 节“家庭可以先做一个小闭环”的核心场景插画",
    },
)
_EXPECTED_SOURCE_META = (
    (
        NEWS_URL,
        NEWS_FETCH_URL,
        "2026-07-21",
        "面向未来，向新而行",
        "科技教育以更加鲜明的学科融合和实践导向持续发力",
    ),
    (
        PLAN_URL,
        PLAN_URL,
        "2026-04-10",
        "教育部等五部门关于印发《“人工智能+教育”行动计划》的通知",
        "鼓励开展人工智能跨学科教学",
    ),
)


@dataclass(frozen=True, slots=True)
class EditorialSourceBundle:
    evidence_sources: tuple[dict[str, Any], dict[str, Any]]
    visual_rows: tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
    image_bodies: tuple[bytes, bytes, bytes]
    image_checksums: tuple[str, str, str]
    source_content_fingerprint: str
    source_render_fingerprint: str
    source_run_id: str
    source_manifest_sha256: str


def _read_json_body(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required source file is unavailable: {path.name}")
    body = path.read_bytes()
    if not body or len(body) > _MAX_JSON_BYTES:
        raise ValueError(f"source JSON is outside the bounded size: {path.name}")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"source JSON is invalid: {path.name}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"source JSON root must be an object: {path.name}")
    return payload, body


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(body: bytes) -> str:
    return sha256(body).hexdigest()


def _require_hex_digest(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return value


def _validated_jpeg(body: bytes) -> dict[str, Any]:
    with Image.open(BytesIO(body)) as image:
        image.load()
        if image.format != "JPEG" or image.size != (1536, 1024):
            raise ValueError("source image must be an exact 1536x1024 JPEG")
        if image.getexif() or image.info.get("icc_profile"):
            raise ValueError("source image must be metadata-free")
    return {
        "media_type": "image/jpeg",
        "width": 1536,
        "height": 1024,
        "byte_size": len(body),
        "sha256": _sha256(body),
        "metadata_free": True,
    }


def _manifest_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload.get("files")
    if not isinstance(rows, list) or not rows or len(rows) > _MAX_MANIFEST_ROWS:
        raise ValueError("source manifest files are invalid")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("source manifest row is invalid")
        path = row["path"]
        normalized = PurePosixPath(path)
        if (
            not path
            or normalized.is_absolute()
            or normalized.as_posix() != path
            or ".." in normalized.parts
        ):
            raise ValueError("source manifest path is unsafe")
        _require_hex_digest(row.get("sha256"), field="source manifest sha256")
        if (
            type(row.get("byte_size")) is not int
            or row["byte_size"] < 1
            or row["byte_size"] > _MAX_MANIFEST_FILE_BYTES
        ):
            raise ValueError("source manifest byte_size is invalid")
        if path in result:
            raise ValueError("source manifest paths must be unique")
        result[path] = row
    return result


def _validate_manifest_tree(source_dir: Path, manifest_rows: dict[str, dict[str, Any]]) -> None:
    if sum(row["byte_size"] for row in manifest_rows.values()) > _MAX_MANIFEST_TOTAL_BYTES:
        raise ValueError("source manifest total byte size is invalid")
    for relative_path, row in manifest_rows.items():
        path = source_dir
        for part in PurePosixPath(relative_path).parts:
            path /= part
            if path.is_symlink():
                raise ValueError(f"source manifest file is unavailable: {relative_path}")
        if not path.is_file() or path.stat().st_size != row["byte_size"]:
            raise ValueError(f"source file does not match the manifest: {relative_path}")
        if _sha256(path.read_bytes()) != row["sha256"]:
            raise ValueError(f"source file does not match the manifest: {relative_path}")


def _validate_manifested_body(
    manifest_rows: dict[str, dict[str, Any]], relative_path: str, body: bytes
) -> None:
    row = manifest_rows.get(relative_path)
    if row is None:
        raise ValueError(f"required source file is absent from the manifest: {relative_path}")
    if row["byte_size"] != len(body) or row["sha256"] != _sha256(body):
        raise ValueError(f"source file does not match the manifest: {relative_path}")


def _validate_evidence_sources(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if payload.get("version") != SOURCE_EVIDENCE_VERSION:
        raise ValueError("source evidence version changed")
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) != 2:
        raise ValueError("source evidence set must contain exactly two records")
    validated: list[dict[str, Any]] = []
    for ordinal, (
        source,
        (
            expected_url,
            expected_retrieval_url,
            expected_date,
            expected_title,
            expected_quote,
        ),
    ) in enumerate(zip(sources, _EXPECTED_SOURCE_META, strict=True)):
        if not isinstance(source, dict):
            raise ValueError("source evidence row is invalid")
        if (
            source.get("canonical_url") != expected_url
            or source.get("retrieval_url") != expected_retrieval_url
            or source.get("published_date") != expected_date
            or source.get("title") != expected_title
            or source.get("source_name") != "中华人民共和国教育部政府门户网站"
            or source.get("exact_quote") != expected_quote
        ):
            raise ValueError("source evidence identity changed")
        evidence_id = str(UUID(str(source.get("evidence_id"))))
        document_sha256 = _require_hex_digest(
            source.get("document_sha256"), field="evidence document_sha256"
        )
        if (
            evidence_id != _EXPECTED_EVIDENCE_IDS[ordinal]
            or document_sha256 != _EXPECTED_EVIDENCE_DOCUMENT_SHA256[ordinal]
        ):
            raise ValueError("source evidence snapshot identity changed")
        quote = source.get("exact_quote")
        if not isinstance(quote, str) or not quote.strip() or len(quote) > 120:
            raise ValueError("source evidence quote is invalid")
        validated.append(
            {
                "canonical_url": expected_url,
                "document_sha256": document_sha256,
                "evidence_id": evidence_id,
                "exact_quote": expected_quote,
                "published_date": expected_date,
                "retrieval_url": expected_retrieval_url,
                "source_name": "中华人民共和国教育部政府门户网站",
                "title": expected_title,
            }
        )
    return (validated[0], validated[1])


def load_source_bundle(source_dir: Path) -> EditorialSourceBundle:
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError("source bundle directory is unavailable")
    manifest_path = source_dir / "manifest.json"
    manifest, manifest_body = _read_json_body(manifest_path)
    manifest_rows = _manifest_rows(manifest)
    _validate_manifest_tree(source_dir, manifest_rows)
    run, run_body = _read_json_body(source_dir / "run.json")
    evidence, evidence_body = _read_json_body(source_dir / "evidence.json")
    visual, visual_body = _read_json_body(source_dir / "visual-map.json")
    for relative_path, body in (
        ("run.json", run_body),
        ("evidence.json", evidence_body),
        ("visual-map.json", visual_body),
    ):
        _validate_manifested_body(manifest_rows, relative_path, body)

    if (
        run.get("version") != SOURCE_REPORT_VERSION
        or manifest.get("version") != SOURCE_REPORT_VERSION
        or run.get("status") != "ready"
        or manifest.get("status") != "ready"
        or run.get("simulation") is not True
        or manifest.get("simulation") is not True
        or run.get("published") is not False
        or manifest.get("published") is not False
        or run.get("visual_quality_status") != "passed"
        or run.get("ip_visibility_assessment") != "passed"
        or manifest.get("visual_quality_status") != "passed"
        or visual.get("quality_status") != "passed"
        or manifest.get("sources") != [NEWS_URL, PLAN_URL]
    ):
        raise ValueError("source bundle is not a complete inspected ready bundle")
    try:
        run_id = str(UUID(str(run.get("run_id"))))
        manifest_run_id = str(UUID(str(manifest.get("run_id"))))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError("source bundle run identity is invalid") from error
    if run_id != manifest_run_id:
        raise ValueError("source bundle run identity changed")
    for field in ("wechat_calls", "wecom_calls", "publish_calls"):
        if run.get(field) != 0:
            raise ValueError("source bundle distribution boundary changed")
    if (
        run.get("provider") != "toapis"
        or run.get("model") != "gpt-image-2"
        or run.get("manual_review_status") != "pending"
        or run.get("paid_generation_call_limit") != 3
        or run.get("paid_generation_calls_attempted") != 3
        or run.get("paid_generation_calls_succeeded") != 3
        or run.get("article_provider_calls") != 0
        or run.get("embedding_provider_calls") != 0
        or run.get("comfly_calls") != 0
        or run.get("source_fetch_calls_in_run") != 0
    ):
        raise ValueError("source bundle call ledger changed")

    source_content = _require_hex_digest(
        run.get("content_fingerprint"), field="source content_fingerprint"
    )
    source_render = _require_hex_digest(
        run.get("render_fingerprint"), field="source render_fingerprint"
    )
    evidence_sources = _validate_evidence_sources(evidence)
    rows = visual.get("visuals")
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("source visual map must contain exactly three rows")
    bodies: list[bytes] = []
    checksums: list[str] = []
    validated_rows: list[dict[str, Any]] = []
    for ordinal, (name, row, expected_contract) in enumerate(
        zip(BODY_IMAGE_NAMES, rows, _EXPECTED_VISUAL_CONTRACT, strict=True)
    ):
        if (
            not isinstance(row, dict)
            or type(row.get("ordinal")) is not int
            or row.get("ordinal") != ordinal
        ):
            raise ValueError("source visual ordinals changed")
        if (
            row.get("ip_visibility_assessment") != "pass"
            or row.get("automatic_retry_permitted") is not False
            or row.get("ip_prompt_contract") != "mandatory_visible_protagonist"
            or row.get("plan_version") != "official-account-generated-visual-plan-v3-visible-ip"
            or row.get("prompt_version")
            != "official-account-generated-visual-prompt-v3-visible-ip-block-scene"
            or row.get("output_profile_version")
            != "official-account-generated-body-publication-v2-3x2-jpeg"
            or row.get("provider_attempts") != 1
            or row.get("reference_public_ref") != _EXPECTED_REFERENCE_PUBLIC_REFS[ordinal]
            or row.get("reference_catalog_version") != "brand-visual-catalog-v1"
            or row.get("reference_input_version")
            != "image-reference-input-v2-png-preserve-jpeg-normalize"
            or row.get("block_kind") != "paragraph"
            or row.get("block_index") != 0
            or row.get("section_index") != ordinal
            or row.get("block_fingerprint") != expected_contract["block_fingerprint"]
            or row.get("reference_input_sha256") != expected_contract["reference_input_sha256"]
            or row.get("request_fingerprint") != expected_contract["request_fingerprint"]
            or row.get("semantic_alt") != expected_contract["semantic_alt"]
        ):
            raise ValueError("source visual contract or local IP inspection changed")
        output = row.get("output")
        if not isinstance(output, dict):
            raise ValueError("source visual output metadata is invalid")
        path = source_dir / "assets" / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("source visual file is unavailable")
        body = path.read_bytes()
        profile = _validated_jpeg(body)
        relative = f"assets/{name}"
        _validate_manifested_body(manifest_rows, relative, body)
        manifest_row = manifest_rows[relative]
        if (
            output.get("sha256") != profile["sha256"]
            or output.get("byte_size") != profile["byte_size"]
            or output.get("width") != 1536
            or output.get("height") != 1024
            or output.get("media_type") != "image/jpeg"
            or output.get("metadata_free") is not True
            or manifest_row.get("sha256") != profile["sha256"]
            or manifest_row.get("byte_size") != profile["byte_size"]
        ):
            raise ValueError("source visual bytes do not match durable metadata")
        bodies.append(body)
        checksums.append(profile["sha256"])
        validated_rows.append(row)
    if len(set(checksums)) != 3:
        raise ValueError("source visuals must remain byte-distinct")
    return EditorialSourceBundle(
        evidence_sources=evidence_sources,
        visual_rows=(validated_rows[0], validated_rows[1], validated_rows[2]),
        image_bodies=(bodies[0], bodies[1], bodies[2]),
        image_checksums=(checksums[0], checksums[1], checksums[2]),
        source_content_fingerprint=source_content,
        source_render_fingerprint=source_render,
        source_run_id=run_id,
        source_manifest_sha256=_sha256(manifest_body),
    )


def _editorial_versions() -> ArticleVersionBundle:
    return ArticleVersionBundle(
        generator_prompt_version="official-account-news-editorial-assembler-v2",
        article_schema_version=ARTICLE_SCHEMA_VERSION,
        auditor_prompt_version="official-account-news-editorial-audit-v2",
        audit_schema_version="official-account-news-editorial-audit-schema-v2",
        rule_version="official-account-news-editorial-rules-v2-evidence-boundary",
        renderer_version=RENDERER_VERSION,
        style_version=STYLE_VERSION,
        template_version=TEMPLATE_VERSION,
        local_adapter_version="official-account-news-editorial-local-adapter-v2",
    )


def _validate_editorial_article(article: ArticlePackage) -> None:
    if article.versions != _editorial_versions():
        raise ValueError("editorial Article Package version changed")
    if len(article.sections) != 6:
        raise ValueError("editorial Article Package must contain exactly six units")
    character_count = article_body_character_count(article)
    if character_count < BODY_TARGET_MIN or character_count > BODY_TARGET_MAX:
        raise ValueError("editorial article is outside the approved target length")
    if article.content_fingerprint != article_package_fingerprint(article):
        raise ValueError("editorial Article Package fingerprint changed")

    claim_ids = tuple(claim.id for claim in article.claims)
    if len(set(claim_ids)) != len(claim_ids):
        raise ValueError("editorial claim IDs must be unique")
    known_claim_ids = set(claim_ids)
    referenced_claim_ids = {
        claim_ref
        for section in article.sections
        for block in section.blocks
        for claim_ref in block.claim_refs
    }
    if referenced_claim_ids != known_claim_ids:
        raise ValueError("editorial claim references must be exact and complete")

    source_evidence_ids = {source.evidence_id for source in article.sources}
    if source_evidence_ids != {UUID(value) for value in _EXPECTED_EVIDENCE_IDS}:
        raise ValueError("editorial evidence identity set changed")
    if any(
        claim.kind not in {"external_fact", "opinion"}
        or (
            claim.kind == "external_fact"
            and (
                not claim.evidence_ids
                or not set(claim.evidence_ids).issubset(source_evidence_ids)
                or bool(claim.brand_chunk_ids)
            )
        )
        or (claim.kind == "opinion" and (bool(claim.evidence_ids) or bool(claim.brand_chunk_ids)))
        for claim in article.claims
    ):
        raise ValueError("editorial fact and interpretation bindings changed")
    used_evidence_ids = {
        evidence_id
        for claim in article.claims
        if claim.kind == "external_fact"
        for evidence_id in claim.evidence_ids
    }
    if used_evidence_ids != source_evidence_ids:
        raise ValueError("editorial factual claims must use the exact source set")
    if tuple(source.source_url for source in article.sources) != (NEWS_URL, PLAN_URL):
        raise ValueError("editorial source set changed")

    image_placements = tuple(
        (section_index, block.slot_key)
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    if image_placements != ((0, "body-0"), (2, "body-1"), (4, "body-2")):
        raise ValueError("editorial image placements changed")
    expected_slots = (
        ("body-0", "body", 0),
        ("body-1", "body", 1),
        ("body-2", "body", 2),
        ("cover-0", "cover", 0),
    )
    actual_slots = tuple((slot.slot_key, slot.role, slot.ordinal) for slot in article.media_slots)
    if actual_slots != expected_slots:
        raise ValueError("editorial media slots changed")


def build_editorial_article(bundle: EditorialSourceBundle) -> ArticlePackage:
    news_evidence_id = UUID(str(bundle.evidence_sources[0]["evidence_id"]))
    plan_evidence_id = UUID(str(bundle.evidence_sources[1]["evidence_id"]))
    claims = (
        GeneratedArticleClaim(
            id="news-direction",
            text="教育部新闻强调基础教育更加注重创新能力、综合素养、学科融合与实践导向。",
            kind="external_fact",
            evidence_ids=(news_evidence_id,),
        ),
        GeneratedArticleClaim(
            id="plan-principle",
            text="人工智能+教育行动计划提出育人为本、素养为先、应用导向、智能向善。",
            kind="external_fact",
            evidence_ids=(plan_evidence_id,),
        ),
        GeneratedArticleClaim(
            id="plan-cross-disciplinary",
            text="人工智能+教育行动计划鼓励开展人工智能跨学科教学。",
            kind="external_fact",
            evidence_ids=(plan_evidence_id,),
        ),
        GeneratedArticleClaim(
            id="parent-questions",
            text="家长可以用学习目标、孩子行动与证据产出判断一次AI学习是否有效。",
            kind="opinion",
        ),
        GeneratedArticleClaim(
            id="learning-loop",
            text="问题、假设、行动、证据和复盘可以构成家庭探究的小闭环。",
            kind="opinion",
        ),
        GeneratedArticleClaim(
            id="ai-boundary",
            text="AI适合帮助整理和比较信息，但不应替代孩子的观察、判断与表达。",
            kind="opinion",
        ),
        GeneratedArticleClaim(
            id="parent-role",
            text="家长从讲答案转向追问证据，更有利于孩子形成自主解释和迭代习惯。",
            kind="opinion",
        ),
    )
    sections = (
        ArticleSection(
            heading="先看新闻信号：教育正在把“会不会”推向“能不能解决问题”",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "7月21日，教育部政府门户网站在回顾基础教育改革进展时，把创新能力和综合素养"
                        "放到更突出的位置，也明确提到科技教育正在强化学科融合与实践导向。这个表述"
                        "值得家长留意：评价学习的视角，正在从孩子记住了多少知识，走向他能否调动知识"
                        "理解一个现象、提出一个问题，并把想法变成可以检验的行动。"
                    ),
                    claim_refs=("news-direction", "parent-questions"),
                ),
                ArticleBulletListBlock(
                    kind="bullet_list",
                    items=(
                        "方向一：知识仍然重要，但要进入真实任务，成为解决问题的工具。",
                        "方向二：科学、技术与其他学科不再各自孤立，而是围绕同一个问题协同。",
                        "方向三：学习结果不只是一句正确答案，还包括过程、证据、解释与迭代。",
                    ),
                    claim_refs=("news-direction", "parent-questions"),
                ),
                ArticleQuoteBlock(
                    kind="quote",
                    text="真正值得追踪的变化，不是孩子多学了一个名词，而是他开始用知识做事。",
                    claim_refs=("parent-questions",),
                ),
                ArticleImageBlock(
                    kind="image",
                    slot_key="body-0",
                    alt_text="小赛陪孩子和家长观察植物实验并讨论可验证的问题",
                ),
            ),
        ),
        ArticleSection(
            heading="家长最先问的三个问题，答案都不在“多学一个工具”",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "第一，孩子是不是越早熟练使用AI越好？工具熟练度当然有价值，但它不是学习质量"
                        "的同义词。更关键的问题是：孩子为什么使用它，输入了什么信息，怎样判断输出"
                        "是否可靠，最后又形成了什么属于自己的解释。若这些环节缺席，再流畅的操作也"
                        "可能只是把思考外包。"
                    ),
                    claim_refs=("parent-questions", "ai-boundary"),
                ),
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "第二，跨学科是不是把几门课简单拼在一起？不是。跨学科真正困难的地方，是让"
                        "孩子围绕一个问题选择合适的方法：需要数学时测量和比较，需要语文时描述和"
                        "论证，需要科学时控制变量，需要技术时制作并改进。学科不是装饰，而是解决"
                        "问题时被调用的不同视角。"
                    ),
                    claim_refs=("parent-questions", "plan-cross-disciplinary"),
                ),
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "第三，家长要不要再准备一套复杂课程？不必先从课程表出发。一次散步、一盆植物、"
                        "一块融化速度不同的冰，甚至家里反复出现的收纳难题，都可以成为小项目。重点"
                        "不是把活动做得宏大，而是让孩子拥有问题，让证据在过程中出现。"
                    ),
                    claim_refs=("parent-questions", "learning-loop"),
                ),
                ArticleQuoteBlock(
                    kind="callout",
                    text=(
                        "边界说明：以上是面向家庭的编辑性解释，不是政策原文，也不意味着学校新增"
                        "考试或家庭必须购买课程。"
                    ),
                    claim_refs=("parent-questions",),
                ),
            ),
        ),
        ArticleSection(
            heading="真正的变化，是把“听懂结论”改造成“生成理解”",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "传统学习很容易沿着一条熟悉的路径前进：老师给出原理，学生记住步骤，再用"
                        "标准答案确认自己是否掌握。探究式学习并不排斥讲解，却会把顺序重新安排。"
                        "孩子先看见现象、提出猜想，再决定怎样观察或测量；结论不是开场白，而是对"
                        "一组证据的暂时解释。"
                    ),
                    claim_refs=("learning-loop",),
                ),
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "这也解释了为什么“动手”本身并不够。照着视频复制一个实验，可能很热闹，却"
                        "未必发生真正的探究。只有当孩子能说明为什么这样做、什么现象支持判断、哪里"
                        "与预期不同，以及下一次准备改变什么，动手才与思考连在一起。"
                    ),
                    claim_refs=("learning-loop",),
                ),
                ArticleBulletListBlock(
                    kind="bullet_list",
                    items=(
                        "先问：我到底想弄清楚什么？",
                        "再做：我需要观察、测量或比较什么？",
                        "后说：证据支持了什么，还不能说明什么？",
                        "再试：下一轮只改变一个关键条件。",
                    ),
                    claim_refs=("learning-loop",),
                ),
                ArticleImageBlock(
                    kind="image",
                    slot_key="body-1",
                    alt_text="赛先生和小赛陪亲子搭建跨学科科学实验并记录证据",
                ),
            ),
        ),
        ArticleSection(
            heading="把AI放回学习现场：它是助手，不是答案的终点",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "4月发布的“人工智能+教育”行动计划提出育人为本、素养为先、应用导向、智能向善，"
                        "并鼓励开展人工智能跨学科教学。把这些原则放在一起看，重点并不是让AI成为"
                        "独立表演项目，而是让它进入真实的学习任务，同时始终服务于人的成长与判断。"
                    ),
                    claim_refs=("plan-principle", "plan-cross-disciplinary", "ai-boundary"),
                ),
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "例如观察一周的植物变化，孩子可以先自己拍照、测量和记录，再请AI协助整理表格"
                        "或寻找可能遗漏的比较角度。接下来仍要回到现场核对：叶片变化真的来自光照吗？"
                        "样本够不够？有没有同时改变浇水量？AI给出的解释只能成为新假设，不能直接"
                        "替代证据。"
                    ),
                    claim_refs=("ai-boundary", "learning-loop"),
                ),
                ArticleQuoteBlock(
                    kind="quote",
                    text="先有孩子的观察，再有AI的协助；先核对证据，再接受结论。顺序不能倒。",
                    claim_refs=("ai-boundary",),
                ),
            ),
        ),
        ArticleSection(
            heading="今晚就能开始：一个20分钟的家庭探究小闭环",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "选择一个孩子此刻真的好奇、又能在家里安全观察的问题。不要急着搜索答案，先让"
                        "孩子说出自己的猜想，并追问他为什么这样想。把猜想写成一句可以被观察推翻或"
                        "支持的话，探究就有了清楚的起点。"
                    ),
                    claim_refs=("learning-loop", "parent-role"),
                ),
                ArticleBulletListBlock(
                    kind="bullet_list",
                    items=(
                        "第1步｜定问题：从一个具体的“为什么”开始，不追求宏大。",
                        "第2步｜留猜想：让孩子先说理由，家长不抢答。",
                        "第3步｜找证据：观察、计时、测量或做一次小比较。",
                        "第4步｜做复盘：说清符合预期的地方，也记录意外。",
                        "第5步｜再迭代：下一次只调整一个条件，看看解释是否更稳。",
                    ),
                    claim_refs=("learning-loop", "parent-role"),
                ),
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "如果使用AI，可以请它帮助把记录整理成表格、把孩子已经提出的问题归类，或者"
                        "生成几个供比较的追问。不要让它直接写完整结论。最后用孩子自己的话讲一遍："
                        "我原来怎么想，后来看到什么，现在为什么改变或保留判断。"
                    ),
                    claim_refs=("ai-boundary", "learning-loop"),
                ),
                ArticleImageBlock(
                    kind="image",
                    slot_key="body-2",
                    alt_text="小赛陪孩子按步骤复盘科学记录并形成自己的解释",
                ),
            ),
        ),
        ArticleSection(
            heading="最后，家长要做的不是更会讲，而是更会追问",
            blocks=(
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "很多家庭活动卡住，不是因为缺材料，而是成人太快给出正确答案。答案一出现，"
                        "孩子的问题就结束了。试着把“我来告诉你”换成几个慢一点的问题：你观察到了"
                        "什么？哪一条记录最能支持你的想法？如果朋友不同意，你准备怎样解释？"
                    ),
                    claim_refs=("parent-role",),
                ),
                ArticleParagraphBlock(
                    kind="paragraph",
                    text=(
                        "这样的退后并不是放任。家长仍然负责安全、时间和材料边界，也可以帮助孩子"
                        "把模糊的问题变得可执行；只是把观察权、判断权和表达权尽量还给孩子。长期看，"
                        "这比替他完成一份漂亮作品更接近创新能力和综合素养真正发生的地方。"
                    ),
                    claim_refs=("parent-role", "news-direction"),
                ),
                ArticleQuoteBlock(
                    kind="callout",
                    text="今天不必完成一个完美项目。只要孩子比昨天多提出一个问题、多保留一条证据，学习就已经向前走了一步。",
                    claim_refs=("parent-role", "learning-loop"),
                ),
            ),
        ),
    )
    provisional = ArticlePackage(
        title="AI进入教育新阶段：家长真正要抓住的，不是“多学一个工具”",
        digest="政策释放的关键信号，是让知识进入真实问题，让AI回到助手的位置。",
        author="赛先生",
        lead=(
            "两份教育部公开材料，把创新能力、综合素养、跨学科与人工智能放进了同一条教育线索。"
            "家长最容易被“AI”两个字吸引，却也最需要先停下来问：孩子究竟要学什么？是不是越早"
            "熟练操作越好？家庭又该怎样参与，才不会把一次探究变成另一份作业？这篇文章不追逐"
            "工具清单，而是从权威材料出发，拆解学习方式正在发生的变化，并给出一个今晚就能开始"
            "的家庭小闭环。"
        ),
        topic_title="教育部AI教育行动计划与家庭科学探究",
        sections=sections,
        conclusion=(
            "真正重要的，从来不是孩子有没有抢先使用某个新工具，而是他能否面对真实问题，提出"
            "自己的猜想，寻找足以支持判断的证据，并愿意根据结果修正解释。AI可以帮助整理、比较"
            "和追问，小赛与赛先生也可以陪伴这个过程；但观察、判断和表达必须留在孩子手里。"
            "从一个20分钟的小问题开始，给孩子时间，也给答案晚一点出现的机会。"
        ),
        claims=claims,
        sources=tuple(
            ArticleSourceProjection(
                evidence_id=UUID(str(source["evidence_id"])),
                source_name=f"教育部｜{source['title']}",
                source_url=str(source["canonical_url"]),
                source_tier="A",
            )
            for source in bundle.evidence_sources
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
        versions=_editorial_versions(),
        media_selection=None,
        content_fingerprint="0" * 64,
    )
    article = provisional.model_copy(
        update={"content_fingerprint": article_package_fingerprint(provisional)}
    )
    _validate_editorial_article(article)
    return article


_STYLE = {
    "root": (
        "margin:0;padding:22px 17px 42px;background-color:#fbf8ef;color:#183347;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB',"
        "'Microsoft YaHei',sans-serif;letter-spacing:.25px;"
    ),
    "topline": "margin:0 0 22px;border-top:4px solid #d8663a;height:0;line-height:0;",
    "eyebrow": (
        "margin:0 0 12px;color:#2f7c79;font-size:11px;line-height:1.5;font-weight:700;"
        "letter-spacing:2.2px;"
    ),
    "title": (
        "margin:0;color:#173449;font-size:30px;line-height:1.26;font-weight:800;letter-spacing:-.35px;"
    ),
    "deck": (
        "margin:17px 0 0;padding:0 0 0 13px;border-left:3px solid #d8663a;color:#49606d;"
        "font-size:14px;line-height:1.85;"
    ),
    "byline": "margin:16px 0 0;color:#7d7065;font-size:11px;line-height:1.5;letter-spacing:1.5px;",
    "reading_map": (
        "margin:30px 0 0;padding:20px 18px 17px;background-color:#173449;border-radius:3px;"
        "box-shadow:8px 8px 0 #e7dfcf;"
    ),
    "reading_label": (
        "margin:0 0 10px;color:#f0d67a;font-size:11px;line-height:1.4;font-weight:700;"
        "letter-spacing:2px;"
    ),
    "reading_item": (
        "margin:0;padding:8px 0;border-top:1px solid #ffffff24;color:#f9f5eb;font-size:13px;"
        "line-height:1.6;"
    ),
    "lead": (
        "margin:32px 0 0;padding:22px 18px;background-color:#f0e8d8;"
        "border-radius:16px 2px 16px 2px;"
    ),
    "lead_label": (
        "margin:0 0 12px;color:#c75431;font-size:11px;line-height:1.4;font-weight:800;"
        "letter-spacing:2px;"
    ),
    "lead_text": "margin:0 0 10px;color:#273f4e;font-size:16px;line-height:2;text-align:justify;",
    "section": "margin:42px 0 0;",
    "section_kicker": (
        "margin:0 0 9px;color:#d8663a;font-size:10px;line-height:1.4;font-weight:800;"
        "letter-spacing:2.2px;"
    ),
    "section_heading": (
        "margin:0 0 19px;padding:0 0 13px;border-bottom:1px solid #b9c4c4;color:#173449;"
        "font-size:22px;line-height:1.45;font-weight:800;"
    ),
    "paragraph": "margin:0 0 13px;color:#263f4d;font-size:16px;line-height:2;text-align:justify;",
    "list": (
        "margin:22px 0;padding:16px 16px 8px;background-color:#fffdf7;border:1px solid #d8cdbb;"
        "border-radius:2px;list-style:none;"
    ),
    "list_label": (
        "margin:-29px 0 10px;display:inline-block;padding:5px 9px;background-color:#2f7c79;"
        "color:#fff;font-size:10px;line-height:1.3;font-weight:800;letter-spacing:1.6px;"
    ),
    "list_item": (
        "margin:0;padding:10px 0 10px 25px;border-bottom:1px solid #e6ded0;color:#294452;"
        "font-size:14px;line-height:1.8;"
    ),
    "list_number": (
        "display:inline-block;width:22px;margin-left:-25px;color:#d8663a;font-size:10px;"
        "line-height:1.8;font-weight:800;vertical-align:top;"
    ),
    "quote": (
        "margin:25px 0;padding:19px 18px 18px;background-color:#d8663a;color:#fff9ed;"
        "border-radius:2px 18px 2px 18px;"
    ),
    "quote_mark": "display:block;margin:0 0 4px;color:#f4d77b;font:800 25px/1 Georgia,serif;",
    "quote_text": "margin:0;font-size:17px;line-height:1.85;font-weight:700;",
    "callout": (
        "margin:24px 0;padding:18px;border-left:4px solid #f0d67a;background-color:#e1efeb;"
        "color:#1f4c50;"
    ),
    "callout_label": (
        "margin:0 0 8px;color:#2f7c79;font-size:10px;line-height:1.4;font-weight:800;"
        "letter-spacing:1.8px;"
    ),
    "callout_text": "margin:0;font-size:14px;line-height:1.9;font-weight:600;",
    "image_frame": (
        "margin:27px -7px 30px;padding:7px;background-color:#fff;border:1px solid #d9d1c5;"
    ),
    "image": "display:block;width:100%;height:auto;border:0;aspect-ratio:3/2;object-fit:cover;",
    "caption": (
        "margin:9px 6px 3px;color:#697982;font-size:10px;line-height:1.6;letter-spacing:.5px;"
    ),
    "conclusion": (
        "margin:44px 0 0;padding:24px 19px 22px;background-color:#173449;"
        "border-radius:18px 2px 18px 2px;"
    ),
    "conclusion_label": (
        "margin:0 0 12px;color:#f0d67a;font-size:11px;line-height:1.4;font-weight:800;"
        "letter-spacing:2px;"
    ),
    "conclusion_text": (
        "margin:0 0 10px;color:#f9f5ec;font-size:15px;line-height:2;text-align:justify;"
    ),
    "sources": (
        "margin:34px 0 0;padding:18px 0 0;border-top:1px solid #bcc5c2;color:#64747c;"
        "font-size:11px;line-height:1.8;"
    ),
    "sources_heading": (
        "margin:0 0 10px;color:#173449;font-size:12px;line-height:1.5;font-weight:800;"
        "letter-spacing:1.5px;"
    ),
    "source_item": "margin:0 0 8px;padding-left:2px;",
    "source_link": "color:#2f6f73;text-decoration:underline;word-break:break-all;",
    "boundary": "margin:14px 0 0;color:#8a7767;font-size:10px;line-height:1.7;",
}


def _mobile_paragraphs(text: str, *, max_characters: int = 86) -> tuple[str, ...]:
    punctuation = "。！？；"
    sentences: list[str] = []
    start = 0
    for index, character in enumerate(text):
        if character in punctuation:
            sentences.append(text[start : index + 1])
            start = index + 1
    if start < len(text):
        sentences.append(text[start:])
    if not sentences:
        return (text,)
    result: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > max_characters:
            result.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        result.append(current)
    return tuple(result)


def _safe_source_url(value: str) -> str:
    parsed = urlsplit(value)
    if value not in {NEWS_URL, PLAN_URL} or parsed.scheme != "https" or parsed.username:
        raise ValueError("editorial source URL is outside the pinned allowlist")
    return value


def _paragraph_html(text: str, style: str) -> list[str]:
    return [f'<p style="{style}">{escape(part)}</p>' for part in _mobile_paragraphs(text)]


def render_editorial_html(article: ArticlePackage) -> str:
    _validate_editorial_article(article)
    parts = [f'<section style="{_STYLE["root"]}">', f'<p style="{_STYLE["topline"]}"><br></p>']
    parts.append(f'<p style="{_STYLE["eyebrow"]}">EDUCATION FIELD NOTE · 教育观察</p>')
    parts.append(f'<h1 style="{_STYLE["title"]}">{escape(article.title)}</h1>')
    parts.append(f'<p style="{_STYLE["deck"]}">{escape(article.digest)}</p>')
    parts.append(f'<p style="{_STYLE["byline"]}">撰文 · {escape(article.author)}　/　2026.08</p>')
    parts.append(f'<section style="{_STYLE["reading_map"]}">')
    parts.append(f'<p style="{_STYLE["reading_label"]}">READING MAP · 这篇文章回答什么</p>')
    for index, section in enumerate(article.sections, start=1):
        parts.append(
            f'<p style="{_STYLE["reading_item"]}">{index:02d}　{escape(section.heading)}</p>'
        )
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE["lead"]}">')
    parts.append(f'<p style="{_STYLE["lead_label"]}">从家长的问题开始</p>')
    parts.extend(_paragraph_html(article.lead, _STYLE["lead_text"]))
    parts.append("</section>")
    list_labels = {
        0: "POLICY SNAPSHOT · 信号速览",
        1: "PARENT QUESTIONS · 家长先问",
        4: "20-MIN PLAN · 行动卡",
    }
    image_ordinals: list[int] = []
    for section_index, section in enumerate(article.sections):
        parts.append(f'<section style="{_STYLE["section"]}">')
        parts.append(
            f'<p style="{_STYLE["section_kicker"]}">FIELD NOTE {section_index + 1:02d}</p>'
        )
        parts.append(f'<h2 style="{_STYLE["section_heading"]}">{escape(section.heading)}</h2>')
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                parts.extend(_paragraph_html(block.text, _STYLE["paragraph"]))
            elif isinstance(block, ArticleBulletListBlock):
                parts.append(f'<section style="{_STYLE["list"]}">')
                label = list_labels.get(section_index, "KEY POINTS · 要点")
                parts.append(f'<p style="{_STYLE["list_label"]}">{label}</p>')
                for item_index, item in enumerate(block.items, start=1):
                    parts.append(f'<p style="{_STYLE["list_item"]}">')
                    parts.append(
                        f'<span style="{_STYLE["list_number"]}">{item_index:02d}</span>'
                        f"{escape(item)}</p>"
                    )
                parts.append("</section>")
            elif isinstance(block, ArticleQuoteBlock) and block.kind == "quote":
                parts.append(f'<blockquote style="{_STYLE["quote"]}">')
                parts.append(f'<span style="{_STYLE["quote_mark"]}">“</span>')
                parts.append(f'<p style="{_STYLE["quote_text"]}">{escape(block.text)}</p>')
                parts.append("</blockquote>")
            elif isinstance(block, ArticleQuoteBlock):
                parts.append(f'<section style="{_STYLE["callout"]}">')
                parts.append(
                    f'<p style="{_STYLE["callout_label"]}">BOUNDARY · 事实与解释的边界</p>'
                )
                parts.append(f'<p style="{_STYLE["callout_text"]}">{escape(block.text)}</p>')
                parts.append("</section>")
            elif isinstance(block, ArticleImageBlock):
                ordinal = int(block.slot_key.removeprefix("body-"))
                image_ordinals.append(ordinal)
                alt = escape(block.alt_text, quote=True)
                parts.append(f'<section style="{_STYLE["image_frame"]}">')
                parts.append(
                    f'<img src="{body_media_placeholder(ordinal)}" alt="{alt}" '
                    f'style="{_STYLE["image"]}">'
                )
                parts.append(
                    f'<p style="{_STYLE["caption"]}">小赛科学现场 · {escape(block.alt_text)}</p>'
                )
                parts.append("</section>")
        parts.append("</section>")
    if image_ordinals != [0, 1, 2]:
        raise ValueError("editorial image placements changed")
    parts.append(f'<section style="{_STYLE["conclusion"]}">')
    parts.append(f'<p style="{_STYLE["conclusion_label"]}">TAKEAWAY · 带走一个判断</p>')
    parts.extend(_paragraph_html(article.conclusion, _STYLE["conclusion_text"]))
    parts.append("</section>")
    parts.append(f'<section style="{_STYLE["sources"]}">')
    parts.append(f'<p style="{_STYLE["sources_heading"]}">资料来源</p><ol>')
    for source in article.sources:
        source_url = _safe_source_url(source.source_url)
        parts.append(f'<li style="{_STYLE["source_item"]}">')
        parts.append(
            '<a rel="noopener noreferrer" referrerpolicy="no-referrer" '
            f'href="{escape(source_url, quote=True)}" style="{_STYLE["source_link"]}">'
            f"{escape(source.source_name)}</a></li>"
        )
    parts.append("</ol>")
    parts.append(
        f'<p style="{_STYLE["boundary"]}">事实绑定上述权威来源；家庭建议为编辑性解释。'
        "本地草稿，未同步公众号，未发布。</p>"
    )
    parts.append("</section></section>")
    return "".join(parts)


def _article_markdown(article: ArticlePackage) -> str:
    lines = [f"# {article.title}", "", f"> {article.digest}", "", article.lead, ""]
    for section in article.sections:
        lines.extend((f"## {section.heading}", ""))
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                lines.extend((block.text, ""))
            elif isinstance(block, ArticleBulletListBlock):
                lines.extend(f"- {item}" for item in block.items)
                lines.append("")
            elif isinstance(block, ArticleQuoteBlock):
                lines.extend((f"> {block.text}", ""))
            elif isinstance(block, ArticleImageBlock):
                ordinal = int(block.slot_key.removeprefix("body-"))
                lines.extend((f"![{block.alt_text}](assets/body-{ordinal:02d}.jpg)", ""))
    lines.extend(("## 写在最后", "", article.conclusion, "", "## 资料来源", ""))
    lines.extend(f"- [{source.source_name}]({source.source_url})" for source in article.sources)
    lines.extend(("", "事实绑定上述权威来源；家庭建议为编辑性解释。", ""))
    return "\n".join(lines)


def _preview_document(body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; img-src 'self'; "
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'\">"
        "<title>AI进入教育新阶段｜本地编辑型预览</title><style>"
        "*{box-sizing:border-box}html{background:#e8e3d9}body{margin:0}.frame{width:min(100%,430px);"
        "margin:28px auto;background:#fbf8ef;box-shadow:0 24px 70px #17344928}"
        ".boundary{padding:11px 17px;"
        "background:#173449;color:#f0d67a;font:700 10px/1.5 system-ui;letter-spacing:1.6px}"
        "@media(max-width:460px){.frame{margin:0;box-shadow:none}}"
        "@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}"
        '</style></head><body><main class="frame"><div class="boundary">'
        "LOCAL REVIEW · 证据已绑定 · 未同步公众号</div>"
        f"{body}</main></body></html>\n"
    )


def _zip_bundle(root: Path, *, archive_root_name: str) -> Path:
    zip_path = root / f"{archive_root_name}.zip"
    files = tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_file() and path.suffix != ".zip"),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = ZipInfo(f"{archive_root_name}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return zip_path


def export_editorial_bundle(source_dir: Path, output_dir: Path) -> Path:
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("refusing to replace an existing editorial output directory")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    bundle = load_source_bundle(source_dir)
    article = build_editorial_article(bundle)
    canonical_html = render_editorial_html(article)
    resolved_html = canonical_html
    for ordinal, image_name in enumerate(BODY_IMAGE_NAMES):
        token = body_media_placeholder(ordinal)
        if resolved_html.count(token) != 1:
            raise ValueError("editorial render placeholder set is invalid")
        resolved_html = resolved_html.replace(token, f"assets/{image_name}")
    if "__OFFICIAL_ACCOUNT_BODY_MEDIA_" in resolved_html:
        raise ValueError("editorial render retains an unresolved media placeholder")
    render_fingerprint = fingerprint(
        REPORT_VERSION,
        RENDERER_VERSION,
        STYLE_VERSION,
        TEMPLATE_VERSION,
        canonical_html,
        bundle.image_checksums,
    )
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=str(output_dir.parent)))
    try:
        (temporary / "assets").mkdir()
        for name, body, expected_checksum in zip(
            BODY_IMAGE_NAMES, bundle.image_bodies, bundle.image_checksums, strict=True
        ):
            if _sha256(body) != expected_checksum:
                raise ValueError("source image changed during the repackage")
            (temporary / "assets" / name).write_bytes(body)
        (temporary / "article-body.html").write_text(resolved_html, encoding="utf-8")
        (temporary / "preview.html").write_text(_preview_document(resolved_html), encoding="utf-8")
        (temporary / "article.md").write_text(_article_markdown(article), encoding="utf-8")
        _write_json(
            temporary / "article-package.json",
            {
                "version": ARTICLE_SCHEMA_VERSION,
                "article": article.model_dump(mode="json"),
            },
        )
        _write_json(
            temporary / "evidence.json",
            {
                "version": "official-account-news-editorial-evidence-v2",
                "source_snapshot_version": SOURCE_EVIDENCE_VERSION,
                "fact_brand_boundary": (
                    "external facts use evidence; family advice is interpretation"
                ),
                "sources": list(bundle.evidence_sources),
                "claims": [claim.model_dump(mode="json") for claim in article.claims],
            },
        )
        visual_rows: list[dict[str, Any]] = []
        section_indexes = (0, 2, 4)
        for ordinal, (source_row, checksum, section_index) in enumerate(
            zip(bundle.visual_rows, bundle.image_checksums, section_indexes, strict=True)
        ):
            visual_rows.append(
                {
                    "ordinal": ordinal,
                    "section_index": section_index,
                    "section_heading": article.sections[section_index].heading,
                    "semantic_alt": next(
                        block.alt_text
                        for block in article.sections[section_index].blocks
                        if isinstance(block, ArticleImageBlock)
                    ),
                    "output_sha256": checksum,
                    "source_output_sha256": source_row["output"]["sha256"],
                    "reused_byte_exact": True,
                    "inherited_ip_visibility_assessment": source_row["ip_visibility_assessment"],
                    "inherited_reference_public_ref": source_row["reference_public_ref"],
                    "current_repackage_provider_calls": 0,
                }
            )
        _write_json(
            temporary / "visual-map.json",
            {
                "version": "official-account-news-editorial-visual-map-v2",
                "quality_status": "passed_inherited_local_inspection",
                "visuals": visual_rows,
            },
        )
        _write_json(
            temporary / "reference-learning.json",
            {
                "version": REFERENCE_STUDY_VERSION,
                "reference_url": REFERENCE_URL,
                "retained_source_content": False,
                "retained_source_html": False,
                "retained_source_images": False,
                "observed_aggregate": {
                    "visible_characters_approx": 2512,
                    "paragraph_nodes": 54,
                    "median_paragraph_characters_approx": 38,
                    "paragraphs_at_most_30_characters": 27,
                    "image_nodes": 21,
                },
                "applied_original_patterns": [
                    "current-news opening",
                    "parent-question framing",
                    "policy-at-a-glance card",
                    "short mobile paragraph rhythm",
                    "staged fact and interpretation boundary",
                    "balanced body-image placement",
                ],
                "copied_reference_expression": False,
            },
        )
        _write_json(
            temporary / "run.json",
            {
                "version": REPORT_VERSION,
                "status": "ready",
                "simulation": True,
                "local_only": True,
                "copy_ready": False,
                "published": False,
                "manual_review_status": "pending",
                "article_body_character_count": article_body_character_count(article),
                "article_section_count": len(article.sections),
                "body_image_count": len(bundle.image_bodies),
                "content_fingerprint": article.content_fingerprint,
                "render_fingerprint": render_fingerprint,
                "renderer_version": RENDERER_VERSION,
                "style_version": STYLE_VERSION,
                "template_version": TEMPLATE_VERSION,
                "source_bundle_version": SOURCE_REPORT_VERSION,
                "source_bundle_content_fingerprint": bundle.source_content_fingerprint,
                "source_bundle_render_fingerprint": bundle.source_render_fingerprint,
                "source_bundle_run_id": bundle.source_run_id,
                "source_bundle_manifest_sha256": bundle.source_manifest_sha256,
                "inherited_historical_paid_image_calls": 3,
                "source_fetch_calls_in_repackage": 0,
                "article_provider_calls_in_repackage": 0,
                "embedding_provider_calls_in_repackage": 0,
                "image_provider_calls_in_repackage": 0,
                "comfly_calls_in_repackage": 0,
                "toapis_calls_in_repackage": 0,
                "wechat_calls": 0,
                "wecom_calls": 0,
                "publish_calls": 0,
            },
        )
        (temporary / "README.md").write_text(
            "# 教育部新闻 × 小赛 IP｜编辑型本地版 v2\n\n"
            "本目录学习了用户提供案例的编辑节奏，但没有复制其文字、HTML 或图片。正文为全新"
            "六单元结构，事实继续绑定两条教育部来源，家庭建议明确属于解释。\n\n"
            "- 视觉：暖纸张、深墨蓝、克制橙/青；适配 320--430 px 手机阅读\n"
            "- 图片：复用上一版三张已验收 IP 图，文件字节与 SHA-256 完全一致\n"
            "- 本次重排调用：新闻 0、文章模型 0、Embedding 0、生图 0、微信 0、企微 0、发布 0\n"
            "- 状态：ready / local-only / manual review pending / copy-ready false / "
            "unpublished\n\n"
            "打开 `preview.html` 可本地查看；`article-body.html` 是正文片段，"
            "`article.md` 是可读稿。\n",
            encoding="utf-8",
        )
        payload = tuple(
            sorted(
                (path for path in temporary.rglob("*") if path.is_file()),
                key=lambda path: path.relative_to(temporary).as_posix(),
            )
        )
        _write_json(
            temporary / "manifest.json",
            {
                "version": REPORT_VERSION,
                "status": "ready",
                "simulation": True,
                "local_only": True,
                "copy_ready": False,
                "published": False,
                "manual_review_status": "pending",
                "current_repackage_external_calls": 0,
                "inherited_historical_paid_image_calls": 3,
                "source_bundle_version": SOURCE_REPORT_VERSION,
                "source_bundle_run_id": bundle.source_run_id,
                "source_bundle_manifest_sha256": bundle.source_manifest_sha256,
                "files": [
                    {
                        "path": path.relative_to(temporary).as_posix(),
                        "byte_size": path.stat().st_size,
                        "sha256": _sha256(path.read_bytes()),
                    }
                    for path in payload
                ],
            },
        )
        _zip_bundle(temporary, archive_root_name=output_dir.name)
        if output_dir.exists() or output_dir.is_symlink():
            raise FileExistsError("refusing to replace an existing editorial output directory")
        temporary.rename(output_dir)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    output = export_editorial_bundle(args.source_dir, args.output_dir)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
