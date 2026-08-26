from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in review artifacts.
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, replace
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from app.application.ports.official_account_local import (
    OfficialAccountMediaResult,
    StoredOfficialAccountManualReview,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_RENDERER_V4_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V5_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V6_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_VERSION,
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
    ArticleValidationIssue,
    OfficialAccountAuditVerdict,
    article_version_bundle_kind,
    body_media_placeholder,
    context_media_placeholder,
    fingerprint,
)

WECHAT_DRAFT_PREFLIGHT_RULE_VERSION = "wechat-draft-preflight-v1"
OFFICIAL_ACCOUNT_REVIEW_BUNDLE_V1_VERSION = "official-account-review-bundle-v1"
OFFICIAL_ACCOUNT_REVIEW_BUNDLE_V2_VERSION = "official-account-review-bundle-v2-multi-image"
OFFICIAL_ACCOUNT_REVIEW_BUNDLE_V3_VERSION = "official-account-review-bundle-v3-editorial"
OFFICIAL_ACCOUNT_REVIEW_BUNDLE_VERSION = "official-account-review-bundle-v4-multimodal-media"
OFFICIAL_ACCOUNT_LIVE_LOCAL_REVIEW_BUNDLE_VERSION = "official-account-live-local-review-bundle-v1"
OFFICIAL_ACCOUNT_NEWS_CONTEXT_REVIEW_BUNDLE_VERSION = (
    "official-account-review-bundle-v5-news-context"
)
OFFICIAL_ACCOUNT_NEWS_CONTEXT_LIVE_LOCAL_REVIEW_BUNDLE_VERSION = (
    "official-account-live-local-review-bundle-v2-news-context"
)
OFFICIAL_ACCOUNT_NEWS_CONTEXT_POLISHED_REVIEW_BUNDLE_VERSION = (
    "official-account-review-bundle-v6-news-context-export-polish"
)
OFFICIAL_ACCOUNT_NEWS_CONTEXT_POLISHED_LIVE_LOCAL_REVIEW_BUNDLE_VERSION = (
    "official-account-live-local-review-bundle-v3-news-context-export-polish"
)
OFFICIAL_ACCOUNT_NEWS_CONTEXT_EXPORT_POLISH_VERSION = (
    "official-account-news-context-export-polish-v1"
)
OFFICIAL_ACCOUNT_COVER_EXPORT_DERIVATIVE_VERSION = (
    "official-account-cover-export-derivative-v1-top-biased"
)
OFFICIAL_ACCOUNT_CONTEXT_DISPLAY_FALLBACK_VERSION = "official-account-context-display-fallback-v1"

_CONSERVATIVE_FIELD_SOURCE = "conservative_public_reference_unverified_by_account"
_LOCAL_SAFETY_SOURCE = "local_safety_contract"
_INTERNAL_SCHEMA_SOURCE = "internal_article_schema"
_NOT_RUN_SOURCE = "not_run"
_TITLE_LIMIT = 32
_AUTHOR_LIMIT = 16
_DIGEST_LIMIT = 120
_HTML_CHARACTER_LIMIT = 20_000
_HTML_BYTE_LIMIT = 1_048_576
_MEDIA_BYTE_LIMIT = 10 * 1_048_576
_EXPORT_IMAGE_MAX_DIMENSION = 8_192
_EXPORT_IMAGE_MAX_PIXELS = 32_000_000
_COVER_TARGET_RATIO = 2.35
_COVER_RATIO_TOLERANCE = 0.08
_ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_GENERIC_CAS_CONTEXT_TEXT = frozenset(
    {
        "文章配图",
        "原文配图",
        "新闻原图",
        "新闻图片",
        "新闻现场图",
        "相关新闻图片",
    }
)
_ALLOWED_TAG_ATTRIBUTES = {
    "a": frozenset({"href", "referrerpolicy", "rel", "style"}),
    "blockquote": frozenset({"style"}),
    "br": frozenset(),
    "em": frozenset(),
    "figcaption": frozenset({"style"}),
    "figure": frozenset({"data-context-only-not-evidence", "data-media-role", "style"}),
    "h1": frozenset({"style"}),
    "h2": frozenset({"style"}),
    "img": frozenset({"alt", "src", "style"}),
    "li": frozenset({"style"}),
    "ol": frozenset({"style"}),
    "p": frozenset({"style"}),
    "section": frozenset({"style"}),
    "span": frozenset({"style"}),
    "strong": frozenset(),
    "ul": frozenset({"style"}),
}
_UNSAFE_HTML_PATTERN = re.compile(
    r"(?is)<\s*(?:script|style|iframe|form|object|embed|link|base)\b|\son[a-z]+\s*="
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WechatDraftPreflightRecord(_FrozenModel):
    code: str = Field(min_length=1, max_length=100)
    severity: Literal["info", "warning", "error"]
    passed: bool
    field: str = Field(min_length=1, max_length=120)
    observed: str | int | bool
    limit: str | int | None = None
    rule_version: Literal["wechat-draft-preflight-v1"] = "wechat-draft-preflight-v1"
    source_status: str = Field(min_length=1, max_length=100)


class WechatDraftPreflightReport(_FrozenModel):
    rule_version: Literal["wechat-draft-preflight-v1"] = "wechat-draft-preflight-v1"
    policy_status: Literal["conservative_unverified"] = "conservative_unverified"
    passed: bool
    manual_review_status: Literal["pending", "approved", "rejected"] = "pending"
    editorially_approved: bool = False
    mobile_screenshot_status: Literal["not_run"] = "not_run"
    records: tuple[WechatDraftPreflightRecord, ...]


@dataclass(frozen=True, slots=True)
class ReviewBundleInput:
    run_id: UUID
    run_status: str
    request_fingerprint: str
    generation_mode: str
    simulation: bool
    article: ArticlePackage
    validation_issues: tuple[ArticleValidationIssue, ...]
    audit: OfficialAccountAuditVerdict | None
    resolved_html: str
    draft_request_fingerprint: str
    resolved_fingerprint: str
    render_fingerprint: str
    body_media: OfficialAccountMediaResult
    cover_media: OfficialAccountMediaResult
    body_bytes: bytes
    cover_bytes: bytes
    body_media_items: tuple[OfficialAccountMediaResult, ...] = ()
    body_bytes_items: tuple[bytes, ...] = ()
    context_media_items: tuple[OfficialAccountMediaResult, ...] = ()
    context_bytes_items: tuple[bytes, ...] = ()
    manual_review: StoredOfficialAccountManualReview | None = None


@dataclass(frozen=True, slots=True)
class ReviewBundleExportResult:
    bundle_directory: Path
    zip_path: Path
    zip_sha256: str
    manifest_path: Path
    preflight: WechatDraftPreflightReport
    reused: bool


@dataclass(frozen=True, slots=True)
class _ExportCoverAsset:
    media: OfficialAccountMediaResult
    body: bytes
    dimensions: tuple[int, int]
    applied: bool
    crop_box: tuple[int, int, int, int] | None


@dataclass(frozen=True, slots=True)
class _ExportContextMedia:
    media: OfficialAccountMediaResult
    display_text_source: Literal["persisted_source", "export_semantic_fallback"]


class _ArticleHtmlInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.shape_errors: list[str] = []
        self.hrefs: list[str] = []
        self.image_sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        allowed = _ALLOWED_TAG_ATTRIBUTES.get(tag)
        if allowed is None:
            self.shape_errors.append(f"tag:{tag}")
            return
        attribute_map = dict(attrs)
        disallowed = set(attribute_map) - allowed
        if disallowed:
            self.shape_errors.append(f"attrs:{tag}:{','.join(sorted(disallowed))}")
        style = attribute_map.get("style") or ""
        lowered_style = style.casefold()
        if any(token in lowered_style for token in ("url(", "@import", "javascript:")):
            self.shape_errors.append(f"style:{tag}")
        if tag == "a":
            href = attribute_map.get("href") or ""
            self.hrefs.append(href)
            if attribute_map.get("rel") != "noopener noreferrer":
                self.shape_errors.append("a:rel")
            if attribute_map.get("referrerpolicy") != "no-referrer":
                self.shape_errors.append("a:referrerpolicy")
        if tag == "img":
            self.image_sources.append(attribute_map.get("src") or "")


def run_wechat_draft_preflight(
    *,
    article: ArticlePackage,
    resolved_html: str,
    body_media: OfficialAccountMediaResult,
    cover_media: OfficialAccountMediaResult,
    body_dimensions: tuple[int, int] | None,
    cover_dimensions: tuple[int, int] | None,
    body_media_items: tuple[OfficialAccountMediaResult, ...] = (),
    body_dimensions_items: tuple[tuple[int, int] | None, ...] = (),
    context_media_items: tuple[OfficialAccountMediaResult, ...] = (),
    context_dimensions_items: tuple[tuple[int, int] | None, ...] = (),
    manual_review_status: Literal["pending", "approved", "rejected"] = "pending",
    editorially_approved: bool = False,
) -> WechatDraftPreflightReport:
    if editorially_approved and manual_review_status != "approved":
        raise ValueError("editorial approval requires an approved manual review")
    body_media_all = body_media_items or (body_media,)
    body_dimensions_all = body_dimensions_items or (body_dimensions,)
    records: list[WechatDraftPreflightRecord] = []

    def record(
        *,
        code: str,
        field: str,
        passed: bool,
        observed: str | int | bool,
        limit: str | int | None,
        source_status: str,
        failure_severity: Literal["warning", "error"] = "error",
    ) -> None:
        records.append(
            WechatDraftPreflightRecord(
                code=code,
                severity="info" if passed else failure_severity,
                passed=passed,
                field=field,
                observed=observed,
                limit=limit,
                source_status=source_status,
            )
        )

    for code, field, value, limit in (
        ("title_conservative_limit", "title", article.title, _TITLE_LIMIT),
        ("author_conservative_limit", "author", article.author, _AUTHOR_LIMIT),
        ("digest_conservative_limit", "digest", article.digest, _DIGEST_LIMIT),
    ):
        record(
            code=code,
            field=field,
            passed=len(value) <= limit,
            observed=len(value),
            limit=limit,
            source_status=_CONSERVATIVE_FIELD_SOURCE,
        )

    html_bytes = resolved_html.encode("utf-8")
    record(
        code="html_character_conservative_limit",
        field="resolved_html",
        passed=len(resolved_html) <= _HTML_CHARACTER_LIMIT,
        observed=len(resolved_html),
        limit=_HTML_CHARACTER_LIMIT,
        source_status=_CONSERVATIVE_FIELD_SOURCE,
    )
    record(
        code="html_utf8_byte_conservative_limit",
        field="resolved_html",
        passed=len(html_bytes) <= _HTML_BYTE_LIMIT,
        observed=len(html_bytes),
        limit=_HTML_BYTE_LIMIT,
        source_status=_CONSERVATIVE_FIELD_SOURCE,
    )
    record(
        code="html_media_placeholder_resolved",
        field="resolved_html",
        passed=not any(body_media_placeholder(index) in resolved_html for index in range(5))
        and not any(context_media_placeholder(index) in resolved_html for index in range(2)),
        observed=sum(resolved_html.count(body_media_placeholder(index)) for index in range(5))
        + sum(resolved_html.count(context_media_placeholder(index)) for index in range(2)),
        limit=0,
        source_status=_LOCAL_SAFETY_SOURCE,
    )
    record(
        code="html_executable_markup_absent",
        field="resolved_html",
        passed=_UNSAFE_HTML_PATTERN.search(resolved_html) is None,
        observed=bool(_UNSAFE_HTML_PATTERN.search(resolved_html)),
        limit=False,
        source_status=_LOCAL_SAFETY_SOURCE,
    )

    inspector = _ArticleHtmlInspector()
    try:
        inspector.feed(resolved_html)
        inspector.close()
    except Exception:
        inspector.shape_errors.append("parser_error")
    record(
        code="html_allowlisted_shape",
        field="resolved_html",
        passed=not inspector.shape_errors,
        observed=",".join(inspector.shape_errors) or "allowlisted",
        limit="fixed tag and attribute allowlist",
        source_status=_LOCAL_SAFETY_SOURCE,
    )
    links_safe = all(
        urlsplit(href).scheme == "https"
        and bool(urlsplit(href).hostname)
        and urlsplit(href).username is None
        and urlsplit(href).password is None
        for href in inspector.hrefs
    )
    record(
        code="source_links_safe_https",
        field="sources",
        passed=links_safe,
        observed=len(inspector.hrefs),
        limit="HTTPS links or non-link sanitized fixture source",
        source_status=_LOCAL_SAFETY_SOURCE,
    )
    expected_media_urls = {item.media_url for item in (*body_media_all, *context_media_items)}
    controlled_media_references = (
        inspector.image_sources == [item.media_url for item in body_media_all]
        if not context_media_items
        else len(inspector.image_sources) == len(expected_media_urls)
        and set(inspector.image_sources) == expected_media_urls
    )
    record(
        code="body_media_reference_controlled",
        field="resolved_html.img",
        passed=controlled_media_references,
        observed=(
            "controlled_local_media_reference"
            if controlled_media_references
            else "uncontrolled_or_missing_media_reference"
        ),
        limit=(
            "five ordered body and up to two controlled context media references"
            if context_media_items
            else "one to five ordered controlled local media references"
        ),
        source_status=_LOCAL_SAFETY_SOURCE,
    )

    record(
        code="body_media_role",
        field="body_media.role",
        passed=(
            body_media_all[0] == body_media
            and tuple(item.role for item in body_media_all) == ("body",) * len(body_media_all)
            and tuple(item.ordinal for item in body_media_all) == tuple(range(len(body_media_all)))
            and len({item.sha256 for item in body_media_all}) == len(body_media_all)
        ),
        observed=",".join(f"{item.role}:{item.ordinal}" for item in body_media_all),
        limit="ordered body ordinals 0--4 with distinct checksums",
        source_status=_INTERNAL_SCHEMA_SOURCE,
    )
    record(
        code="cover_media_role",
        field="cover_media.role",
        passed=cover_media.role == "cover" and cover_media.ordinal == 0,
        observed=f"{cover_media.role}:{cover_media.ordinal}",
        limit="cover:0",
        source_status=_INTERNAL_SCHEMA_SOURCE,
    )
    record(
        code="body_cover_bytes_distinct",
        field="media.sha256",
        passed=all(item.sha256 != cover_media.sha256 for item in body_media_all),
        observed=any(item.sha256 == cover_media.sha256 for item in body_media_all),
        limit=False,
        source_status=_LOCAL_SAFETY_SOURCE,
    )
    if context_media_items:
        record(
            code="context_media_role",
            field="context_media.role",
            passed=(
                tuple(item.role for item in context_media_items)
                == ("context",) * len(context_media_items)
                and tuple(item.ordinal for item in context_media_items)
                == tuple(range(len(context_media_items)))
                and len({item.sha256 for item in context_media_items}) == len(context_media_items)
                and all(item.context_only_not_evidence for item in context_media_items)
            ),
            observed=",".join(f"{item.role}:{item.ordinal}" for item in context_media_items),
            limit="zero to two ordered contextual-not-evidence media references",
            source_status=_INTERNAL_SCHEMA_SOURCE,
        )
    for media in (*body_media_all, cover_media):
        record(
            code=f"{media.role}_media_type_allowlisted",
            field=f"{media.role}_media.media_type",
            passed=media.media_type in _ALLOWED_MEDIA_TYPES,
            observed=media.media_type,
            limit=",".join(sorted(_ALLOWED_MEDIA_TYPES)),
            source_status=_LOCAL_SAFETY_SOURCE,
        )
        record(
            code=f"{media.role}_media_local_byte_limit",
            field=f"{media.role}_media.byte_size",
            passed=0 < media.byte_size <= _MEDIA_BYTE_LIMIT,
            observed=media.byte_size,
            limit=_MEDIA_BYTE_LIMIT,
            source_status=_LOCAL_SAFETY_SOURCE,
        )
    for media in context_media_items:
        record(
            code=f"context_{media.ordinal}_media_type_allowlisted",
            field=f"context_media[{media.ordinal}].media_type",
            passed=media.media_type in _ALLOWED_MEDIA_TYPES,
            observed=media.media_type,
            limit=",".join(sorted(_ALLOWED_MEDIA_TYPES)),
            source_status=_LOCAL_SAFETY_SOURCE,
        )
        record(
            code=f"context_{media.ordinal}_media_local_byte_limit",
            field=f"context_media[{media.ordinal}].byte_size",
            passed=0 < media.byte_size <= _MEDIA_BYTE_LIMIT,
            observed=media.byte_size,
            limit=_MEDIA_BYTE_LIMIT,
            source_status=_LOCAL_SAFETY_SOURCE,
        )
    record(
        code="body_image_dimensions_readable",
        field="body_media.dimensions",
        passed=(
            len(body_dimensions_all) == len(body_media_all)
            and all(item is not None for item in body_dimensions_all)
        ),
        observed=",".join(_dimensions_value(item) for item in body_dimensions_all),
        limit="positive width x height for every body image",
        source_status=_LOCAL_SAFETY_SOURCE,
    )
    if context_media_items:
        record(
            code="context_image_dimensions_readable",
            field="context_media.dimensions",
            passed=(
                len(context_dimensions_items) == len(context_media_items)
                and all(item is not None for item in context_dimensions_items)
            ),
            observed=",".join(_dimensions_value(item) for item in context_dimensions_items),
            limit="positive natural width x height for every context image",
            source_status=_LOCAL_SAFETY_SOURCE,
        )
    cover_ratio_ok = False
    if cover_dimensions is not None and cover_dimensions[1] > 0:
        cover_ratio_ok = abs((cover_dimensions[0] / cover_dimensions[1]) - 2.35) <= 0.08
    record(
        code="cover_wide_ratio_advisory",
        field="cover_media.dimensions",
        passed=cover_ratio_ok,
        observed=_dimensions_value(cover_dimensions),
        limit="2.35:1 ± 0.08",
        source_status=_CONSERVATIVE_FIELD_SOURCE,
        failure_severity="warning",
    )
    record(
        code=f"manual_editorial_review_{manual_review_status}",
        field="manual_review_status",
        passed=manual_review_status == "approved",
        observed=manual_review_status,
        limit="human approval bound to content/render fingerprints",
        source_status=_LOCAL_SAFETY_SOURCE,
        failure_severity="warning",
    )
    record(
        code="mobile_screenshot_not_run",
        field="mobile_screenshot",
        passed=False,
        observed="not_run",
        limit="not faked by exporter",
        source_status=_NOT_RUN_SOURCE,
        failure_severity="warning",
    )
    return WechatDraftPreflightReport(
        passed=not any(item.severity == "error" for item in records),
        manual_review_status=manual_review_status,
        editorially_approved=editorially_approved,
        records=tuple(records),
    )


def export_fixture_review_bundle(
    bundle: ReviewBundleInput,
    *,
    output_directory: Path,
    mode: Literal["review", "copy-ready"] = "review",
) -> ReviewBundleExportResult:
    _validate_bundle_input(bundle)
    return _export_review_bundle(
        bundle,
        output_directory=output_directory,
        mode=mode,
        live_local=False,
    )


def export_live_local_review_bundle(
    bundle: ReviewBundleInput,
    *,
    output_directory: Path,
) -> ReviewBundleExportResult:
    """Export an explicitly authorized live run for local review only.

    This is intentionally a separate function from fixture/copy-ready export: it
    never treats a human-review row as permission to publish or as copy-ready.
    """

    _validate_live_local_bundle_input(bundle)
    return _export_review_bundle(
        bundle,
        output_directory=output_directory,
        mode="review",
        live_local=True,
    )


def _export_review_bundle(
    bundle: ReviewBundleInput,
    *,
    output_directory: Path,
    mode: Literal["review", "copy-ready"],
    live_local: bool,
) -> ReviewBundleExportResult:
    bundle_kind = article_version_bundle_kind(bundle.article.versions)
    is_current_bundle = bundle_kind in {"v6", "v7", "v8", "v9", "v10"}
    if not live_local and not is_current_bundle and mode != "review":
        raise ValueError("historical review bundles do not support copy-ready mode")
    if (
        not live_local
        and mode == "copy-ready"
        and (bundle.manual_review is None or bundle.manual_review.decision != "approved")
    ):
        raise ValueError("copy-ready export requires an approved manual review")
    _assert_copy_ready_context_rights(bundle.article, mode=mode)
    output_root = output_directory.expanduser().resolve()
    if output_root == Path(output_root.anchor):
        raise ValueError("review bundle output directory cannot be a filesystem root")
    output_root.mkdir(parents=True, exist_ok=True)
    if not output_root.is_dir():
        raise ValueError("review bundle output path must be a directory")

    review_suffix = (
        f"-{bundle.manual_review.request_fingerprint[:10]}"
        if (is_current_bundle or live_local) and bundle.manual_review is not None
        else ""
    )
    bundle_name = (
        f"live-local-review-{str(bundle.run_id)[:8]}-"
        f"{bundle.article.content_fingerprint[:10]}{review_suffix}"
        if live_local
        else f"{'copy' if mode == 'copy-ready' else 'review'}-{str(bundle.run_id)[:8]}-"
        f"{bundle.article.content_fingerprint[:10]}{review_suffix}"
    )
    target = output_root / bundle_name
    if target.is_symlink():
        raise ValueError("review bundle target cannot be a symbolic link")
    temporary_root = Path(tempfile.mkdtemp(prefix=f".{bundle_name}.", dir=output_root))
    try:
        result = (
            _write_live_local_bundle(
                temporary_root,
                bundle_name=bundle_name,
                bundle=bundle,
            )
            if live_local
            else _write_bundle_v3(
                temporary_root,
                bundle_name=bundle_name,
                bundle=bundle,
                mode=mode,
            )
            if is_current_bundle
            else _write_bundle(temporary_root, bundle_name=bundle_name, bundle=bundle)
        )
        if target.exists():
            reused = _existing_bundle_matches(target, temporary_root, bundle_name=bundle_name)
            if not reused:
                raise FileExistsError(
                    "review bundle target exists with different or incomplete contents"
                )
            shutil.rmtree(temporary_root)
            return ReviewBundleExportResult(
                bundle_directory=target,
                zip_path=target / f"{bundle_name}.zip",
                zip_sha256=_file_sha256(target / f"{bundle_name}.zip"),
                manifest_path=target / "manifest.json",
                preflight=result.preflight,
                reused=True,
            )
        os.replace(temporary_root, target)
        return ReviewBundleExportResult(
            bundle_directory=target,
            zip_path=target / f"{bundle_name}.zip",
            zip_sha256=result.zip_sha256,
            manifest_path=target / "manifest.json",
            preflight=result.preflight,
            reused=False,
        )
    except Exception:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
        raise


def _assert_copy_ready_context_rights(
    article: ArticlePackage,
    *,
    mode: Literal["review", "copy-ready"],
) -> None:
    if (
        mode == "copy-ready"
        and article.news_context_media is not None
        and any(
            item.rights_status == "publish_permission_unverified"
            for item in article.news_context_media.items
        )
    ):
        raise ValueError(
            "copy-ready export cannot contain source images with unverified publication rights"
        )


def _validate_bundle_input(bundle: ReviewBundleInput) -> None:
    if bundle.run_status != "ready":
        raise ValueError("only a ready fixture run can be exported")
    if bundle.generation_mode != "fixture" or not bundle.simulation:
        raise ValueError("review bundle export accepts local fixture simulations only")
    _validate_review_bundle_common(bundle)


def _validate_live_local_bundle_input(bundle: ReviewBundleInput) -> None:
    if bundle.run_status != "ready":
        raise ValueError("only a ready live local run can be exported")
    if bundle.generation_mode != "live" or not bundle.simulation:
        raise ValueError("live-local export accepts simulated live runs only")
    _validate_review_bundle_common(bundle)


def _validate_review_bundle_common(bundle: ReviewBundleInput) -> None:
    if bundle.audit is None or not bundle.audit.accepted:
        raise ValueError("review bundle requires an accepted model audit")
    if any(issue.severity == "error" for issue in bundle.validation_issues):
        raise ValueError("review bundle requires deterministic validation to pass")
    if article_version_bundle_kind(bundle.article.versions) is None:
        raise ValueError("review bundle article version identity is unsupported")
    body_media, body_bytes = _bundle_body_items(bundle)
    context_media, context_bytes = _bundle_context_items(bundle)
    for media, body in (
        *zip(body_media, body_bytes, strict=True),
        *zip(context_media, context_bytes, strict=True),
        (bundle.cover_media, bundle.cover_bytes),
    ):
        if len(body) != media.byte_size or sha256(body).hexdigest() != media.sha256:
            raise ValueError(f"{media.role} media bytes do not match persisted metadata")
        if _detected_image_media_type(body) != media.media_type:
            raise ValueError(f"{media.role} media type does not match its encoded bytes")
    if tuple(item.ordinal for item in body_media) != tuple(range(len(body_media))):
        raise ValueError("body media export ordinals must be contiguous and ordered")
    if len({item.sha256 for item in body_media}) != len(body_media):
        raise ValueError("body media export checksums must be distinct")
    expected_resolved_fingerprint = fingerprint(
        bundle.render_fingerprint,
        bundle.draft_request_fingerprint,
        bundle.resolved_html,
    )
    if bundle.resolved_fingerprint != expected_resolved_fingerprint:
        raise ValueError("resolved article fingerprint does not match its immutable lineage")


@dataclass(frozen=True, slots=True)
class _WrittenBundle:
    zip_sha256: str
    preflight: WechatDraftPreflightReport


def _write_bundle(root: Path, *, bundle_name: str, bundle: ReviewBundleInput) -> _WrittenBundle:
    assets = root / "assets"
    assets.mkdir()
    body_media, body_bytes = _bundle_body_items(bundle)
    for media, body in zip(body_media, body_bytes, strict=True):
        (assets / f"body-{media.ordinal:02d}.png").write_bytes(body)
    (assets / "cover-wide.png").write_bytes(bundle.cover_bytes)

    preflight = run_wechat_draft_preflight(
        article=bundle.article,
        resolved_html=bundle.resolved_html,
        body_media=bundle.body_media,
        cover_media=bundle.cover_media,
        body_dimensions=_png_dimensions(bundle.body_bytes),
        cover_dimensions=_png_dimensions(bundle.cover_bytes),
        body_media_items=body_media,
        body_dimensions_items=tuple(_png_dimensions(body) for body in body_bytes),
    )
    article_body = _review_article_body(bundle.resolved_html, body_media)
    (root / "article-body.html").write_text(article_body, encoding="utf-8")
    (root / "preview.html").write_text(_preview_document(article_body), encoding="utf-8")
    (root / "article.md").write_text(_article_markdown(bundle.article), encoding="utf-8")
    (root / "article.json").write_text(
        _pretty_json(
            {
                "manual_review_status": "pending",
                "editorially_approved": False,
                "article": bundle.article,
            }
        ),
        encoding="utf-8",
    )
    (root / "sources.json").write_text(
        _pretty_json(
            {
                "sources": bundle.article.sources,
                "claims": bundle.article.claims,
                "fixture_source_policy": (
                    "example.invalid is a sanitized placeholder and remains non-clickable in "
                    f"{bundle.article.versions.renderer_version}"
                ),
            }
        ),
        encoding="utf-8",
    )
    (root / "review.json").write_text(
        _pretty_json(
            {
                "manual_review_status": "pending",
                "editorially_approved": False,
                "approval_fingerprint": None,
                "blocking_label": "NOT EDITORIALLY APPROVED",
                "model_audit": bundle.audit,
                "deterministic_validation": {
                    "passed": True,
                    "issues": bundle.validation_issues,
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "preflight.json").write_text(_pretty_json(preflight), encoding="utf-8")
    (root / "README.md").write_text(_bundle_readme(bundle, preflight), encoding="utf-8")

    payload_files = tuple(
        sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.name != "manifest.json" and path.suffix != ".zip"
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
    manifest = {
        "bundle_version": (
            OFFICIAL_ACCOUNT_REVIEW_BUNDLE_V2_VERSION
            if len(body_media) > 1
            else OFFICIAL_ACCOUNT_REVIEW_BUNDLE_V1_VERSION
        ),
        "run_id": str(bundle.run_id),
        "run_status": bundle.run_status,
        "generation_mode": bundle.generation_mode,
        "simulation": True,
        "manual_review_status": "pending",
        "editorially_approved": False,
        "blocking_label": "NOT EDITORIALLY APPROVED",
        "mobile_screenshot_status": "not_run",
        "preflight_passed": preflight.passed,
        "versions": bundle.article.versions,
        "fingerprints": {
            "run_request": bundle.request_fingerprint,
            "content": bundle.article.content_fingerprint,
            "render": bundle.render_fingerprint,
            "resolved": bundle.resolved_fingerprint,
        },
        "media": {
            "body": _media_manifest(body_media[0], "assets/body-00.png"),
            "body_images": [
                _media_manifest(media, f"assets/body-{media.ordinal:02d}.png")
                for media in body_media
            ],
            "cover": _media_manifest(bundle.cover_media, "assets/cover-wide.png"),
        },
        "files": [_file_manifest(path, root=root) for path in payload_files],
        "archive": {
            "path": f"{bundle_name}.zip",
            "contains": f"{bundle_name}/",
            "self_included": False,
            "integrity": "verified_after_write",
        },
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(_pretty_json(manifest), encoding="utf-8")
    archive_inputs = (*payload_files, manifest_path)
    zip_path = root / f"{bundle_name}.zip"
    _write_deterministic_zip(
        zip_path,
        files=archive_inputs,
        root=root,
        archive_root=bundle_name,
    )
    _verify_zip(zip_path, files=archive_inputs, root=root, archive_root=bundle_name)
    return _WrittenBundle(zip_sha256=_file_sha256(zip_path), preflight=preflight)


def _write_bundle_v3(
    root: Path,
    *,
    bundle_name: str,
    bundle: ReviewBundleInput,
    mode: Literal["review", "copy-ready"],
    live_local: bool = False,
) -> _WrittenBundle:
    assets = root / "assets"
    assets.mkdir()
    body_media, body_bytes = _bundle_body_items(bundle)
    context_media, context_bytes = _bundle_context_items(bundle)
    news_context_export_polish = bool(context_media) and article_version_bundle_kind(
        bundle.article.versions
    ) in {"v9", "v10"}
    export_context_items = (
        _export_context_media_items(bundle.article, context_media)
        if news_context_export_polish
        else tuple(
            _ExportContextMedia(media=item, display_text_source="persisted_source")
            for item in context_media
        )
    )
    export_context_media = tuple(item.media for item in export_context_items)
    export_cover = _export_cover_asset(
        bundle.cover_media,
        bundle.cover_bytes,
        derive_if_needed=news_context_export_polish,
    )
    body_paths = tuple(
        f"assets/body-{media.ordinal:02d}{_media_extension(media.media_type)}"
        for media in body_media
    )
    cover_path = f"assets/cover-wide{_media_extension(export_cover.media.media_type)}"
    context_paths = tuple(
        f"assets/context-{media.ordinal:02d}{_media_extension(media.media_type)}"
        for media in context_media
    )
    for relative, body in zip(body_paths, body_bytes, strict=True):
        (root / relative).write_bytes(body)
    for relative, body in zip(context_paths, context_bytes, strict=True):
        (root / relative).write_bytes(body)
    (root / cover_path).write_bytes(export_cover.body)
    body_dimensions = tuple(_image_dimensions(body) for body in body_bytes)
    cover_dimensions = export_cover.dimensions
    context_dimensions = tuple(_image_dimensions(body) for body in context_bytes)

    manual_status: Literal["pending", "approved", "rejected"] = (
        bundle.manual_review.decision if bundle.manual_review is not None else "pending"
    )
    copy_ready = mode == "copy-ready"
    preflight = run_wechat_draft_preflight(
        article=bundle.article,
        resolved_html=bundle.resolved_html,
        body_media=bundle.body_media,
        cover_media=export_cover.media,
        body_dimensions=body_dimensions[0],
        cover_dimensions=cover_dimensions,
        body_media_items=body_media,
        body_dimensions_items=body_dimensions,
        context_media_items=context_media,
        context_dimensions_items=context_dimensions,
        manual_review_status=manual_status,
        editorially_approved=copy_ready,
    )
    article_body = (
        _live_local_article_body(
            bundle.resolved_html,
            body_media=body_media,
            body_paths=body_paths,
            context_media=context_media,
            export_context_media=export_context_media,
            context_paths=context_paths,
            manual_status=manual_status,
        )
        if live_local
        else _editorial_article_body(
            bundle.resolved_html,
            body_media=body_media,
            body_paths=body_paths,
            context_media=context_media,
            export_context_media=export_context_media,
            context_paths=context_paths,
            manual_status=manual_status,
            copy_ready=copy_ready,
        )
    )
    (root / "article-body.html").write_text(article_body, encoding="utf-8")
    (root / "preview.html").write_text(
        _preview_document_live_local(article_body)
        if live_local
        else _preview_document_v3(article_body, copy_ready=copy_ready),
        encoding="utf-8",
    )
    (root / "article.md").write_text(
        _article_markdown_live_local(
            bundle.article,
            body_paths=body_paths,
            manual_status=manual_status,
        )
        if live_local
        else _article_markdown_v3(
            bundle.article,
            body_paths=body_paths,
            manual_status=manual_status,
            copy_ready=copy_ready,
        ),
        encoding="utf-8",
    )
    approval = _approval_projection(bundle.manual_review)
    (root / "article.json").write_text(
        _pretty_json(
            {
                "manual_review_status": manual_status,
                "editorially_approved": copy_ready,
                "copy_ready": copy_ready,
                **(
                    {
                        "export_scope": "live_local",
                        "local_only": True,
                        "published": False,
                        "boundary_label": "LOCAL ONLY · 未同步公众号",
                    }
                    if live_local
                    else {}
                ),
                **(
                    {
                        "export_presentation": _export_presentation_projection(
                            export_cover=export_cover,
                            context_items=export_context_items,
                        )
                    }
                    if news_context_export_polish
                    else {}
                ),
                "article": _safe_article_export_projection(bundle.article),
            }
        ),
        encoding="utf-8",
    )
    (root / "sources.json").write_text(
        _pretty_json(
            {
                "sources": bundle.article.sources,
                "claims": bundle.article.claims,
                **(
                    {
                        "news_context_media": _safe_context_provenance(
                            export_context_items,
                        )
                    }
                    if context_media
                    else {}
                ),
                "source_boundary": (
                    "Persisted source and claim bindings are included for local human review only."
                    if live_local
                    else "Fixture provenance is retained for review and is not a factual web link."
                ),
            }
        ),
        encoding="utf-8",
    )
    (root / "review.json").write_text(
        _pretty_json(
            {
                "manual_review_status": manual_status,
                "editorially_approved": copy_ready,
                "copy_ready": copy_ready,
                "manual_review": approval,
                "blocking_label": (
                    "LOCAL ONLY · 未同步公众号"
                    if live_local
                    else None
                    if copy_ready
                    else "NOT READY FOR PUBLICATION"
                ),
                **(
                    {
                        "export_scope": "live_local",
                        "local_only": True,
                        "published": False,
                    }
                    if live_local
                    else {}
                ),
                "model_audit": bundle.audit,
                "deterministic_validation": {
                    "passed": True,
                    "issues": bundle.validation_issues,
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "preflight.json").write_text(_pretty_json(preflight), encoding="utf-8")
    (root / "README.md").write_text(
        _bundle_readme_live_local(
            bundle,
            preflight=preflight,
            manual_status=manual_status,
            export_polished=news_context_export_polish,
        )
        if live_local
        else _bundle_readme_v3(
            bundle,
            preflight=preflight,
            manual_status=manual_status,
            copy_ready=copy_ready,
            export_polished=news_context_export_polish,
        ),
        encoding="utf-8",
    )

    payload_files = tuple(
        sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.name != "manifest.json" and path.suffix != ".zip"
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
    manifest = {
        "bundle_version": (
            OFFICIAL_ACCOUNT_NEWS_CONTEXT_POLISHED_LIVE_LOCAL_REVIEW_BUNDLE_VERSION
            if live_local and news_context_export_polish
            else OFFICIAL_ACCOUNT_NEWS_CONTEXT_POLISHED_REVIEW_BUNDLE_VERSION
            if news_context_export_polish
            else OFFICIAL_ACCOUNT_NEWS_CONTEXT_LIVE_LOCAL_REVIEW_BUNDLE_VERSION
            if live_local and context_media
            else OFFICIAL_ACCOUNT_LIVE_LOCAL_REVIEW_BUNDLE_VERSION
            if live_local
            else OFFICIAL_ACCOUNT_NEWS_CONTEXT_REVIEW_BUNDLE_VERSION
            if context_media
            else OFFICIAL_ACCOUNT_REVIEW_BUNDLE_VERSION
            if article_version_bundle_kind(bundle.article.versions) in {"v7", "v8"}
            else OFFICIAL_ACCOUNT_REVIEW_BUNDLE_V3_VERSION
        ),
        "run_id": str(bundle.run_id),
        "run_status": bundle.run_status,
        "generation_mode": bundle.generation_mode,
        "simulation": True,
        "manual_review_status": manual_status,
        "editorially_approved": copy_ready,
        "copy_ready": copy_ready,
        "blocking_label": (
            "LOCAL ONLY · 未同步公众号"
            if live_local
            else None
            if copy_ready
            else "NOT READY FOR PUBLICATION"
        ),
        **(
            {
                "export_scope": "live_local",
                "local_only": True,
                "published": False,
            }
            if live_local
            else {}
        ),
        **(
            {
                "export_presentation": _export_presentation_projection(
                    export_cover=export_cover,
                    context_items=export_context_items,
                )
            }
            if news_context_export_polish
            else {}
        ),
        "mobile_screenshot_status": "not_run",
        "preflight_passed": preflight.passed,
        "manual_review": approval,
        "versions": bundle.article.versions,
        **(
            {"media_selection": bundle.article.media_selection}
            if bundle.article.media_selection is not None
            else {}
        ),
        "fingerprints": {
            "run_request": bundle.request_fingerprint,
            "content": bundle.article.content_fingerprint,
            "render": bundle.render_fingerprint,
            "resolved": bundle.resolved_fingerprint,
            "manual_review": (
                bundle.manual_review.request_fingerprint
                if bundle.manual_review is not None
                else None
            ),
        },
        "media": {
            "body": _media_manifest(
                body_media[0],
                body_paths[0],
                dimensions=body_dimensions[0],
            ),
            "body_images": [
                _media_manifest(media, path, dimensions=dimensions)
                for media, path, dimensions in zip(
                    body_media,
                    body_paths,
                    body_dimensions,
                    strict=True,
                )
            ],
            "cover": (
                _cover_media_manifest(
                    export_cover,
                    source_media=bundle.cover_media,
                    path=cover_path,
                )
                if news_context_export_polish
                else _media_manifest(
                    bundle.cover_media,
                    cover_path,
                    dimensions=cover_dimensions,
                )
            ),
            **(
                {
                    "context_images": [
                        _context_media_manifest(
                            export_item,
                            path,
                            dimensions=dimensions,
                        )
                        for export_item, path, dimensions in zip(
                            export_context_items,
                            context_paths,
                            context_dimensions,
                            strict=True,
                        )
                    ]
                }
                if context_media
                else {}
            ),
        },
        "files": [_file_manifest(path, root=root) for path in payload_files],
        "archive": {
            "path": f"{bundle_name}.zip",
            "contains": f"{bundle_name}/",
            "self_included": False,
            "integrity": "verified_after_write",
        },
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(_pretty_json(manifest), encoding="utf-8")
    archive_inputs = (*payload_files, manifest_path)
    zip_path = root / f"{bundle_name}.zip"
    _write_deterministic_zip(
        zip_path,
        files=archive_inputs,
        root=root,
        archive_root=bundle_name,
    )
    _verify_zip(zip_path, files=archive_inputs, root=root, archive_root=bundle_name)
    return _WrittenBundle(zip_sha256=_file_sha256(zip_path), preflight=preflight)


def _write_live_local_bundle(
    root: Path,
    *,
    bundle_name: str,
    bundle: ReviewBundleInput,
) -> _WrittenBundle:
    return _write_bundle_v3(
        root,
        bundle_name=bundle_name,
        bundle=bundle,
        mode="review",
        live_local=True,
    )


def _editorial_article_body(
    resolved_html: str,
    *,
    body_media: tuple[OfficialAccountMediaResult, ...],
    body_paths: tuple[str, ...],
    context_media: tuple[OfficialAccountMediaResult, ...],
    export_context_media: tuple[OfficialAccountMediaResult, ...],
    context_paths: tuple[str, ...],
    manual_status: Literal["pending", "approved", "rejected"],
    copy_ready: bool,
) -> str:
    rewritten = resolved_html
    for media, relative_path in zip(body_media, body_paths, strict=True):
        source = f'src="{escape(media.media_url, quote=True)}"'
        if rewritten.count(source) != 1:
            raise ValueError("resolved article has an invalid controlled body media reference")
        rewritten = rewritten.replace(source, f'src="{relative_path}"')
    rewritten = _rewrite_context_media(
        rewritten,
        context_media=context_media,
        export_context_media=export_context_media,
        context_paths=context_paths,
    )
    if _has_runtime_media_dependency(rewritten):
        raise ValueError("exported article body retained a runtime media dependency")
    if copy_ready:
        return rewritten
    review_banner = (
        '<section style="margin:0 0 18px;padding:12px 14px;background-color:#fff4e8;'
        "border:2px solid #ad4f39;color:#7a2f20;font-size:13px;line-height:1.6;"
        'font-weight:bold;text-align:center;">'
        f"NOT READY FOR PUBLICATION · 人工审稿状态：{manual_status}</section>"
    )
    return review_banner + rewritten


def _live_local_article_body(
    resolved_html: str,
    *,
    body_media: tuple[OfficialAccountMediaResult, ...],
    body_paths: tuple[str, ...],
    context_media: tuple[OfficialAccountMediaResult, ...],
    export_context_media: tuple[OfficialAccountMediaResult, ...],
    context_paths: tuple[str, ...],
    manual_status: Literal["pending", "approved", "rejected"],
) -> str:
    """Rewrite a persisted live draft only to offline relative media paths."""

    rewritten = resolved_html
    for media, relative_path in zip(body_media, body_paths, strict=True):
        source = f'src="{escape(media.media_url, quote=True)}"'
        if rewritten.count(source) != 1:
            raise ValueError("resolved article has an invalid controlled body media reference")
        rewritten = rewritten.replace(source, f'src="{relative_path}"')
    rewritten = _rewrite_context_media(
        rewritten,
        context_media=context_media,
        export_context_media=export_context_media,
        context_paths=context_paths,
    )
    if _has_runtime_media_dependency(rewritten):
        raise ValueError("exported article body retained a runtime media dependency")
    review_banner = (
        '<section style="margin:0 0 18px;padding:12px 14px;background-color:#fff4e8;'
        "border:2px solid #ad4f39;color:#7a2f20;font-size:13px;line-height:1.6;"
        'font-weight:bold;text-align:center;">'
        "LOCAL ONLY · 未同步公众号 · 非 copy-ready / 未发布 · "
        f"人工审稿状态：{manual_status}</section>"
    )
    return review_banner + rewritten


def _rewrite_context_media(
    resolved_html: str,
    *,
    context_media: tuple[OfficialAccountMediaResult, ...],
    export_context_media: tuple[OfficialAccountMediaResult, ...],
    context_paths: tuple[str, ...],
) -> str:
    rewritten = resolved_html
    for media, export_media, relative_path in zip(
        context_media,
        export_context_media,
        context_paths,
        strict=True,
    ):
        source = f'src="{escape(media.media_url, quote=True)}"'
        if rewritten.count(source) != 1:
            raise ValueError("resolved article has an invalid controlled context media reference")
        rewritten = rewritten.replace(source, f'src="{relative_path}"')
        rewritten = _rewrite_context_figure_display_text(
            rewritten,
            source_media=media,
            export_media=export_media,
            relative_path=relative_path,
        )
    return rewritten


def _rewrite_context_figure_display_text(
    resolved_html: str,
    *,
    source_media: OfficialAccountMediaResult,
    export_media: OfficialAccountMediaResult,
    relative_path: str,
) -> str:
    image_source = f'src="{relative_path}"'
    image_position = resolved_html.find(image_source)
    if image_position < 0 or resolved_html.find(image_source, image_position + 1) >= 0:
        raise ValueError("exported context media reference is not unique")
    figure_start = resolved_html.rfind(
        '<figure data-media-role="news-context"',
        0,
        image_position,
    )
    figure_end = resolved_html.find("</figure>", image_position)
    if figure_start < 0 or figure_end < 0:
        raise ValueError("exported context media is outside its controlled figure")
    figure_end += len("</figure>")
    figure = resolved_html[figure_start:figure_end]

    source_alt = source_media.alt_text or ""
    export_alt = export_media.alt_text or ""
    source_alt_attribute = f'alt="{escape(source_alt, quote=True)}"'
    if figure.count(source_alt_attribute) != 1:
        raise ValueError("exported context media has an invalid source alt attribute")
    figure = figure.replace(
        source_alt_attribute,
        f'alt="{escape(export_alt, quote=True)}"',
        1,
    )

    caption_tag = figure.find("<figcaption ")
    caption_text_start = figure.find(">", caption_tag) + 1 if caption_tag >= 0 else -1
    source_caption = escape(source_media.caption or source_alt)
    export_caption = escape(export_media.caption or export_alt)
    if caption_text_start <= 0 or not figure.startswith(source_caption, caption_text_start):
        raise ValueError("exported context media has an invalid source caption")
    figure = (
        figure[:caption_text_start]
        + export_caption
        + figure[caption_text_start + len(source_caption) :]
    )
    return resolved_html[:figure_start] + figure + resolved_html[figure_end:]


def _has_runtime_media_dependency(resolved_html: str) -> bool:
    return (
        "/api/" in resolved_html
        or any(body_media_placeholder(index) in resolved_html for index in range(5))
        or any(context_media_placeholder(index) in resolved_html for index in range(2))
    )


def _preview_document_v3(article_body: str, *, copy_ready: bool) -> str:
    title = "本地公众号可复制预览" if copy_ready else "本地公众号人工审稿预览"
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f"<title>{title}</title></head>"
        f'<body style="margin:0;background:#ded9cf;">{article_body}</body></html>'
    )


def _preview_document_live_local(article_body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        "<title>公众号文章本地审阅预览（未同步）</title></head>"
        f'<body style="margin:0;background:#ded9cf;">{article_body}</body></html>'
    )


def _review_article_body(
    resolved_html: str,
    body_media: tuple[OfficialAccountMediaResult, ...],
) -> str:
    rewritten = resolved_html
    for media in body_media:
        source = f'src="{escape(media.media_url, quote=True)}"'
        if rewritten.count(source) != 1:
            raise ValueError("resolved article has an invalid controlled body media reference")
        rewritten = rewritten.replace(source, f'src="assets/body-{media.ordinal:02d}.png"')
    if "/api/" in rewritten or any(
        body_media_placeholder(index) in rewritten for index in range(5)
    ):
        raise ValueError("exported article body retained a runtime media dependency")
    review_banner = (
        '<section style="margin:0 0 18px;padding:12px 14px;background-color:#fff4e8;'
        "border:2px solid #ad4f39;color:#7a2f20;font-size:13px;line-height:1.6;"
        'font-weight:bold;text-align:center;">'
        "NOT EDITORIALLY APPROVED · 人工审稿状态：pending</section>"
    )
    return review_banner + rewritten


def _preview_document(article_body: str) -> str:
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        "<title>本地公众号人工审稿预览</title></head>"
        f'<body style="margin:0;background:#ded9cf;">{article_body}</body></html>'
    )


def _bundle_body_items(
    bundle: ReviewBundleInput,
) -> tuple[tuple[OfficialAccountMediaResult, ...], tuple[bytes, ...]]:
    media = bundle.body_media_items or (bundle.body_media,)
    bodies = bundle.body_bytes_items or (bundle.body_bytes,)
    if not media or len(media) > 5 or len(media) != len(bodies) or media[0] != bundle.body_media:
        raise ValueError("review bundle body media collection is invalid")
    if bodies[0] != bundle.body_bytes:
        raise ValueError("review bundle primary body bytes are not ordinal zero")
    return media, bodies


def _bundle_context_items(
    bundle: ReviewBundleInput,
) -> tuple[tuple[OfficialAccountMediaResult, ...], tuple[bytes, ...]]:
    media = bundle.context_media_items
    bodies = bundle.context_bytes_items
    if len(media) > 2 or len(media) != len(bodies):
        raise ValueError("review bundle context media collection is invalid")
    if tuple(item.role for item in media) != ("context",) * len(media):
        raise ValueError("review bundle context media roles are invalid")
    if tuple(item.ordinal for item in media) != tuple(range(len(media))):
        raise ValueError("review bundle context media ordinals must be contiguous and ordered")
    if len({item.sha256 for item in media}) != len(media):
        raise ValueError("review bundle context media checksums must be distinct")
    snapshot = bundle.article.news_context_media
    if snapshot is None:
        if media:
            raise ValueError("review bundle context media requires an article selection snapshot")
        return media, bodies
    if len(snapshot.items) != len(media):
        raise ValueError("review bundle context media does not match the article selection")
    for selected, persisted in zip(snapshot.items, media, strict=True):
        if (
            selected.ordinal != persisted.ordinal
            or selected.section_index != persisted.assigned_section_index
            or selected.sha256 != persisted.sha256
            or selected.media_type != persisted.media_type
            or selected.alt_text != persisted.alt_text
            or selected.caption != persisted.caption
            or selected.credit != persisted.credit
            or selected.source_page_url != persisted.source_page_url
            or selected.rights_status != persisted.rights_status
            or selected.context_only_not_evidence != persisted.context_only_not_evidence
        ):
            raise ValueError("review bundle context media provenance changed during export")
    return media, bodies


def _export_context_media_items(
    article: ArticlePackage,
    media: tuple[OfficialAccountMediaResult, ...],
) -> tuple[_ExportContextMedia, ...]:
    exported: list[_ExportContextMedia] = []
    for item in media:
        hostname = (urlsplit(item.source_page_url or "").hostname or "").casefold()
        is_cas_source = hostname == "cas.cn" or hostname.endswith(".cas.cn")
        source_alt = item.alt_text or ""
        source_caption = item.caption or ""
        alt_is_generic = is_cas_source and _is_generic_cas_context_text(source_alt)
        caption_is_generic = is_cas_source and (
            not source_caption or _is_generic_cas_context_text(source_caption)
        )
        if not alt_is_generic and not (caption_is_generic and not source_alt):
            exported.append(
                _ExportContextMedia(
                    media=item,
                    display_text_source="persisted_source",
                )
            )
            continue

        section_index = item.assigned_section_index
        if section_index is None or not 0 <= section_index < len(article.sections):
            raise ValueError("context-media export fallback requires a valid section anchor")
        title = _bounded_export_display_text(article.title, limit=72)
        heading = _bounded_export_display_text(
            article.sections[section_index].heading,
            limit=80,
        )
        fallback_alt = f"新闻上下文图片：{title}；对应章节：{heading}"[:200]
        fallback_caption = (
            f"新闻上下文 · {title} · 对应章节：{heading}（仅作上下文参考，非事实证据）"
        )[:300]
        exported.append(
            _ExportContextMedia(
                media=replace(
                    item,
                    alt_text=fallback_alt if alt_is_generic else item.alt_text,
                    caption=(
                        fallback_caption if alt_is_generic and caption_is_generic else item.caption
                    ),
                ),
                display_text_source="export_semantic_fallback",
            )
        )
    return tuple(exported)


def _is_generic_cas_context_text(value: str) -> bool:
    normalized = "".join(character for character in value.strip() if character.isalnum())
    return normalized in _GENERIC_CAS_CONTEXT_TEXT


def _bounded_export_display_text(value: str, *, limit: int) -> str:
    normalized = " ".join(value.split()).strip("，。；：、 ")
    if not normalized:
        raise ValueError("context-media export fallback requires non-empty article display text")
    return normalized[:limit].rstrip("，。；：、 ")


def _export_cover_asset(
    media: OfficialAccountMediaResult,
    body: bytes,
    *,
    derive_if_needed: bool,
) -> _ExportCoverAsset:
    dimensions = _image_dimensions(body)
    if dimensions is None:
        raise ValueError("review bundle cover dimensions are unreadable")
    width, height = dimensions
    if (
        width > _EXPORT_IMAGE_MAX_DIMENSION
        or height > _EXPORT_IMAGE_MAX_DIMENSION
        or width * height > _EXPORT_IMAGE_MAX_PIXELS
    ):
        raise ValueError("review bundle cover exceeds the safe export raster bound")
    ratio = width / height
    if not derive_if_needed or abs(ratio - _COVER_TARGET_RATIO) <= _COVER_RATIO_TOLERANCE:
        return _ExportCoverAsset(
            media=media,
            body=body,
            dimensions=dimensions,
            applied=False,
            crop_box=None,
        )

    with Image.open(BytesIO(body)) as source:
        source.load()
        raster = ImageOps.exif_transpose(source)
        width, height = raster.size
        ratio = width / height
        if ratio < _COVER_TARGET_RATIO:
            target_height = max(1, min(height, (width * 100 + 117) // 235))
            top = (height - target_height) // 3
            crop_box = (0, top, width, top + target_height)
        else:
            target_width = max(1, min(width, (height * 235 + 50) // 100))
            left = (width - target_width) // 2
            crop_box = (left, 0, left + target_width, height)
        cropped = raster.crop(crop_box)
        derived_body = _encode_export_cover(cropped, media_type=media.media_type)

    if not 0 < len(derived_body) <= _MEDIA_BYTE_LIMIT:
        raise ValueError("review bundle cover derivative exceeds the local byte bound")
    derived_dimensions = _image_dimensions(derived_body)
    if (
        derived_dimensions is None
        or abs((derived_dimensions[0] / derived_dimensions[1]) - _COVER_TARGET_RATIO) > 0.01
    ):
        raise ValueError("review bundle cover derivative does not match the wide profile")
    derived_media_type = _detected_image_media_type(derived_body)
    if derived_media_type != media.media_type:
        raise ValueError("review bundle cover derivative changed its media type")
    derived_media = replace(
        media,
        byte_size=len(derived_body),
        sha256=sha256(derived_body).hexdigest(),
    )
    return _ExportCoverAsset(
        media=derived_media,
        body=derived_body,
        dimensions=derived_dimensions,
        applied=True,
        crop_box=crop_box,
    )


def _encode_export_cover(image: Image.Image, *, media_type: str) -> bytes:
    output = BytesIO()
    if media_type == "image/png":
        has_alpha = image.mode in {"LA", "RGBA"} or "transparency" in image.info
        normalized = image.convert("RGBA" if has_alpha else "RGB")
        normalized.save(output, format="PNG", compress_level=9, optimize=False)
    elif media_type == "image/jpeg":
        image.convert("RGB").save(
            output,
            format="JPEG",
            quality=92,
            subsampling=0,
            optimize=False,
            progressive=False,
        )
    elif media_type == "image/webp":
        has_alpha = image.mode in {"LA", "RGBA"} or "transparency" in image.info
        normalized = image.convert("RGBA" if has_alpha else "RGB")
        normalized.save(output, format="WEBP", lossless=True, method=6, exact=True)
    else:
        raise ValueError("review bundle cover media type cannot be derived")
    return output.getvalue()


def _safe_article_export_projection(article: ArticlePackage) -> ArticlePackage | dict[str, object]:
    if article.news_context_media is None:
        return article
    projection = article.model_dump(mode="json")
    news_context = projection.get("news_context_media")
    if isinstance(news_context, dict):
        items = news_context.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    item.pop("source_article_image_id", None)
    return projection


def _safe_context_provenance(
    media: tuple[_ExportContextMedia, ...],
) -> list[dict[str, object]]:
    return [
        {
            "role": item.media.role,
            "ordinal": item.media.ordinal,
            "assigned_section_index": item.media.assigned_section_index,
            "alt_text": item.media.alt_text,
            "caption": item.media.caption,
            "credit": item.media.credit,
            "source_page_url": item.media.source_page_url,
            "rights_status": item.media.rights_status,
            "context_only_not_evidence": item.media.context_only_not_evidence,
            "display_text_source": item.display_text_source,
            "display_text_version": OFFICIAL_ACCOUNT_CONTEXT_DISPLAY_FALLBACK_VERSION,
        }
        for item in media
    ]


def _article_markdown(article: ArticlePackage) -> str:
    is_field_guide_v4 = article.versions.renderer_version in {
        OFFICIAL_ACCOUNT_RENDERER_V4_VERSION,
        OFFICIAL_ACCOUNT_RENDERER_V5_VERSION,
        OFFICIAL_ACCOUNT_RENDERER_V6_VERSION,
        OFFICIAL_ACCOUNT_RENDERER_VERSION,
    }
    lines = [
        "# NOT EDITORIALLY APPROVED — 人工审稿状态：pending",
        "",
        f"# {article.title}",
        "",
        f"> {article.digest}",
        "",
        f"撰文：{article.author}",
        "",
        article.lead,
        "",
    ]
    for section in article.sections:
        lines.extend((f"## {section.heading}", ""))
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                lines.extend((block.text, ""))
            elif isinstance(block, ArticleBulletListBlock):
                lines.extend(f"- {item}" for item in block.items)
                lines.append("")
            elif isinstance(block, ArticleQuoteBlock):
                if is_field_guide_v4:
                    label = "家庭实践" if block.kind == "callout" else "关键判断"
                else:
                    label = "家庭探索任务" if block.kind == "callout" else "引文"
                lines.extend((f"> **{label}**：{block.text}", ""))
            elif isinstance(block, ArticleImageBlock):
                ordinal = int(block.slot_key.removeprefix("body-"))
                lines.extend((f"![{block.alt_text}](assets/body-{ordinal:02d}.png)", ""))
    conclusion_heading = "给家长的三句话" if is_field_guide_v4 else "带走一个下一步"
    source_heading = "资料来源与适用边界" if is_field_guide_v4 else "资料来源与边界"
    lines.extend(
        (f"## {conclusion_heading}", "", article.conclusion, "", f"## {source_heading}", "")
    )
    for source in article.sources:
        if urlsplit(source.source_url).hostname == "example.invalid":
            lines.append(f"- {source.source_name}（脱敏演示来源，不提供外链）")
        else:
            lines.append(f"- [{source.source_name}]({source.source_url})")
    lines.append("")
    return "\n".join(lines)


def _article_markdown_v3(
    article: ArticlePackage,
    *,
    body_paths: tuple[str, ...],
    manual_status: Literal["pending", "approved", "rejected"],
    copy_ready: bool,
) -> str:
    lines = (
        [] if copy_ready else [f"# NOT READY FOR PUBLICATION — 人工审稿状态：{manual_status}", ""]
    )
    lines.extend(
        [
            f"# {article.title}",
            "",
            f"> {article.digest}",
            "",
            f"撰文：{article.author}",
            "",
            article.lead,
            "",
        ]
    )
    for section in article.sections:
        lines.extend((f"## {section.heading}", ""))
        for block in section.blocks:
            if isinstance(block, ArticleParagraphBlock):
                lines.extend((block.text, ""))
            elif isinstance(block, ArticleBulletListBlock):
                lines.extend(f"- {item}" for item in block.items)
                lines.append("")
            elif isinstance(block, ArticleQuoteBlock):
                label = "家庭实践" if block.kind == "callout" else "关键判断"
                lines.extend((f"> **{label}**：{block.text}", ""))
            elif isinstance(block, ArticleImageBlock):
                ordinal = int(block.slot_key.removeprefix("body-"))
                lines.extend((f"![{block.alt_text}]({body_paths[ordinal]})", ""))
    lines.extend(
        (
            "## 给家长的三句话",
            "",
            article.conclusion,
            "",
            "## 资料来源与适用边界",
            "",
        )
    )
    for source in article.sources:
        if urlsplit(source.source_url).hostname == "example.invalid":
            lines.append(f"- {source.source_name}（内容边界说明，不提供外链）")
        else:
            lines.append(f"- [{source.source_name}]({source.source_url})")
    lines.append("")
    return "\n".join(lines)


def _article_markdown_live_local(
    article: ArticlePackage,
    *,
    body_paths: tuple[str, ...],
    manual_status: Literal["pending", "approved", "rejected"],
) -> str:
    body = _article_markdown_v3(
        article,
        body_paths=body_paths,
        manual_status=manual_status,
        copy_ready=False,
    )
    previous = f"# NOT READY FOR PUBLICATION — 人工审稿状态：{manual_status}"
    return body.replace(
        previous,
        f"# LOCAL ONLY · 未同步公众号 · 非 copy-ready / 未发布 — 人工审稿状态：{manual_status}",
        1,
    )


def _bundle_readme(
    bundle: ReviewBundleInput,
    preflight: WechatDraftPreflightReport,
) -> str:
    return (
        "# NOT EDITORIALLY APPROVED — 人工审稿状态：pending\n\n"
        "这是本地模拟草稿的人工复核包，不是发布包，也不表示文章已经获得编辑批准。\n"
        "导出过程不访问模型、微信或任何外部网络；包内没有账号、令牌或发布能力。\n\n"
        f"- Run ID: `{bundle.run_id}`\n"
        f"- Content fingerprint: `{bundle.article.content_fingerprint}`\n"
        f"- Render fingerprint: `{bundle.render_fingerprint}`\n"
        f"- Conservative preflight passed: `{str(preflight.passed).lower()}`\n"
        "- Mobile screenshot: `not_run`（导出器没有伪造截图）\n"
        "- Simulation: `true`（未同步公众号）\n\n"
        "打开 `preview.html` 可离线查看；`article.md` 适合逐段审稿；"
        "`review.json`、`preflight.json`、`sources.json` 与 `manifest.json` 用于核对门禁、"
        "来源、版本和文件哈希。任何正式使用前都需要人工复核事实、标题、摘要、配图和移动端效果。\n"
    )


def _bundle_readme_v3(
    bundle: ReviewBundleInput,
    *,
    preflight: WechatDraftPreflightReport,
    manual_status: Literal["pending", "approved", "rejected"],
    copy_ready: bool,
    export_polished: bool = False,
) -> str:
    if copy_ready:
        heading = "# COPY-READY — 人工审稿已批准"
        purpose = (
            "这是通过最终人工审稿后生成的本地可复制包；它仍是本地模拟，"
            "不会连接、上传或发布到公众号。"
        )
    else:
        heading = f"# NOT READY FOR PUBLICATION — 人工审稿状态：{manual_status}"
        purpose = "这是本地模拟草稿的人工复核包，不是可发布包。"
    presentation_note = (
        "\n导出展示采用版本化新闻上下文优化：非横版封面生成 2.35:1 顶部偏置派生图；"
        "通用 CAS 图注仅在导出 HTML、manifest 与 sources 展示层补充为文章标题和对应章节语义。"
        "`article.json` 仍保存不可变运行时 Article 快照；上下文图片不作为事实证据。\n"
        if export_polished
        else ""
    )
    return (
        f"{heading}\n\n"
        f"{purpose}\n"
        "导出过程不访问模型、微信或任何外部网络；包内没有账号、令牌或发布能力。\n\n"
        f"- Run ID: `{bundle.run_id}`\n"
        f"- Content fingerprint: `{bundle.article.content_fingerprint}`\n"
        f"- Render fingerprint: `{bundle.render_fingerprint}`\n"
        f"- Manual review: `{manual_status}`\n"
        f"- Copy ready: `{str(copy_ready).lower()}`\n"
        f"- Conservative preflight passed: `{str(preflight.passed).lower()}`\n"
        "- Mobile screenshot: `not_run`（导出器没有伪造截图）\n"
        "- Simulation: `true`（未同步公众号）\n\n"
        "打开 `preview.html` 可离线查看；`article.md` 适合逐段核对；"
        "`review.json`、`preflight.json`、`sources.json` 与 `manifest.json` 保存来源、"
        f"版本、最终审稿事件和文件哈希。{presentation_note}\n"
    )


def _bundle_readme_live_local(
    bundle: ReviewBundleInput,
    *,
    preflight: WechatDraftPreflightReport,
    manual_status: Literal["pending", "approved", "rejected"],
    export_polished: bool = False,
) -> str:
    presentation_note = (
        "\n导出展示采用版本化新闻上下文优化：非横版封面生成 2.35:1 顶部偏置派生图；"
        "通用 CAS 图注仅在导出 HTML、manifest 与 sources 展示层补充为文章标题和对应章节语义。"
        "`article.json` 仍保存不可变运行时 Article 快照；上下文图片不作为事实证据。\n"
        if export_polished
        else ""
    )
    return (
        "# LOCAL ONLY · 未同步公众号\n\n"
        "这是一次经显式命令确认的真实文章本地审阅导出。它只写入当前机器的目录，"
        "不连接、上传或发布到微信公众号，也不表示文章 copy-ready 或已发布。\n"
        "人工审稿状态会原样保留；即使状态为 approved，本包仍只用于本地复核。\n\n"
        f"- Run ID: `{bundle.run_id}`\n"
        f"- Content fingerprint: `{bundle.article.content_fingerprint}`\n"
        f"- Render fingerprint: `{bundle.render_fingerprint}`\n"
        f"- Manual review: `{manual_status}`\n"
        "- Export scope: `live_local`\n"
        "- Copy ready: `false`\n"
        "- Published: `false`\n"
        f"- Conservative preflight passed: `{str(preflight.passed).lower()}`\n"
        "- Mobile screenshot: `not_run`（导出器没有伪造截图）\n"
        "- Simulation: `true`（未同步公众号）\n\n"
        "打开 `preview.html` 可离线查看；`article-body.html` 是使用相对本地图片重写后的"
        "持久化草稿 HTML；`article.md`、`article.json`、`sources.json`、`review.json`、"
        f"`preflight.json` 与 `manifest.json` 保留审阅所需的来源、版本、状态和文件哈希。"
        f"{presentation_note}\n"
    )


def _approval_projection(
    review: StoredOfficialAccountManualReview | None,
) -> dict[str, object] | None:
    if review is None:
        return None
    return {
        "review_id": str(review.id),
        "decision": review.decision,
        "reviewer_label": review.reviewer_label,
        "note": review.note,
        "request_fingerprint": review.request_fingerprint,
        "reviewed_at": review.reviewed_at.isoformat(),
    }


def _media_extension(media_type: str) -> str:
    try:
        return {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }[media_type]
    except KeyError:
        raise ValueError("review bundle media type has no approved extension") from None


def _media_manifest(
    media: OfficialAccountMediaResult,
    path: str,
    *,
    dimensions: tuple[int, int] | None = None,
) -> dict[str, object]:
    _safe_relative_path(path)
    result: dict[str, object] = {
        "path": path,
        "role": media.role,
        "ordinal": media.ordinal,
        "media_type": media.media_type,
        "byte_size": media.byte_size,
        "sha256": media.sha256,
    }
    if dimensions is not None:
        result["dimensions"] = {"width": dimensions[0], "height": dimensions[1]}
    return result


def _context_media_manifest(
    export_item: _ExportContextMedia,
    path: str,
    *,
    dimensions: tuple[int, int] | None,
) -> dict[str, object]:
    media = export_item.media
    result = _media_manifest(media, path, dimensions=dimensions)
    result.update(
        {
            "assigned_section_index": media.assigned_section_index,
            "alt_text": media.alt_text,
            "caption": media.caption,
            "credit": media.credit,
            "source_page_url": media.source_page_url,
            "rights_status": media.rights_status,
            "context_only_not_evidence": media.context_only_not_evidence,
            "display_text_source": export_item.display_text_source,
            "display_text_version": OFFICIAL_ACCOUNT_CONTEXT_DISPLAY_FALLBACK_VERSION,
        }
    )
    return result


def _cover_media_manifest(
    export_cover: _ExportCoverAsset,
    *,
    source_media: OfficialAccountMediaResult,
    path: str,
) -> dict[str, object]:
    result = _media_manifest(
        export_cover.media,
        path,
        dimensions=export_cover.dimensions,
    )
    result["export_derivative"] = {
        "version": OFFICIAL_ACCOUNT_COVER_EXPORT_DERIVATIVE_VERSION,
        "applied": export_cover.applied,
        "target_ratio": "2.35:1",
        "crop_policy": (
            "top_biased_one_third_or_centered_horizontal"
            if export_cover.applied
            else "preserved_already_wide"
        ),
        "crop_box": (
            {
                "left": export_cover.crop_box[0],
                "top": export_cover.crop_box[1],
                "right": export_cover.crop_box[2],
                "bottom": export_cover.crop_box[3],
            }
            if export_cover.crop_box is not None
            else None
        ),
        "source_media_type": source_media.media_type,
        "source_byte_size": source_media.byte_size,
        "source_sha256": source_media.sha256,
    }
    return result


def _export_presentation_projection(
    *,
    export_cover: _ExportCoverAsset,
    context_items: tuple[_ExportContextMedia, ...],
) -> dict[str, object]:
    return {
        "version": OFFICIAL_ACCOUNT_NEWS_CONTEXT_EXPORT_POLISH_VERSION,
        "runtime_article_immutable": True,
        "runtime_render_immutable": True,
        "cover_derivative_version": OFFICIAL_ACCOUNT_COVER_EXPORT_DERIVATIVE_VERSION,
        "cover_derivative_applied": export_cover.applied,
        "context_display_version": OFFICIAL_ACCOUNT_CONTEXT_DISPLAY_FALLBACK_VERSION,
        "context_display_sources": [item.display_text_source for item in context_items],
        "context_boundary": "context_only_not_evidence",
    }


def _file_manifest(path: Path, *, root: Path) -> dict[str, object]:
    relative = path.relative_to(root).as_posix()
    _safe_relative_path(relative)
    return {
        "path": relative,
        "byte_size": path.stat().st_size,
        "sha256": _file_sha256(path),
    }


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise ValueError("review bundle manifest contains an unsafe relative path")
    if any(not part or "\x00" in part for part in path.parts):
        raise ValueError("review bundle manifest contains an unsafe path segment")
    return value


def _write_deterministic_zip(
    zip_path: Path,
    *,
    files: tuple[Path, ...],
    root: Path,
    archive_root: str,
) -> None:
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
            relative = _safe_relative_path(path.relative_to(root).as_posix())
            info = ZipInfo(f"{archive_root}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())


def _verify_zip(
    zip_path: Path,
    *,
    files: tuple[Path, ...],
    root: Path,
    archive_root: str,
) -> None:
    expected = {
        f"{archive_root}/{path.relative_to(root).as_posix()}": (
            path.stat().st_size,
            _file_sha256(path),
        )
        for path in files
    }
    with ZipFile(zip_path) as archive:
        actual_names = archive.namelist()
        if actual_names != sorted(expected):
            raise ValueError("review bundle ZIP members do not match the manifest payload")
        for name, (byte_size, checksum) in expected.items():
            body = archive.read(name)
            if len(body) != byte_size or sha256(body).hexdigest() != checksum:
                raise ValueError("review bundle ZIP member integrity check failed")


def _existing_bundle_matches(target: Path, candidate: Path, *, bundle_name: str) -> bool:
    if not target.is_dir():
        return False
    target_entries = _bundle_entry_shapes(target)
    candidate_entries = _bundle_entry_shapes(candidate)
    if target_entries is None or candidate_entries is None or target_entries != candidate_entries:
        return False
    target_manifest = target / "manifest.json"
    candidate_manifest = candidate / "manifest.json"
    if (
        not target_manifest.is_file()
        or target_manifest.read_bytes() != candidate_manifest.read_bytes()
    ):
        return False
    try:
        manifest = json.loads(target_manifest.read_text(encoding="utf-8"))
        for item in manifest["files"]:
            relative = _safe_relative_path(str(item["path"]))
            path = target / relative
            if (
                not path.is_file()
                or path.stat().st_size != int(item["byte_size"])
                or _file_sha256(path) != item["sha256"]
            ):
                return False
        zip_path = target / f"{bundle_name}.zip"
        archive_files = tuple(
            [target / str(item["path"]) for item in manifest["files"]] + [target_manifest]
        )
        _verify_zip(
            zip_path,
            files=archive_files,
            root=target,
            archive_root=bundle_name,
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False
    return True


def _bundle_entry_shapes(root: Path) -> dict[str, Literal["file", "directory"]] | None:
    entries: dict[str, Literal["file", "directory"]] = {}
    try:
        for path in root.rglob("*"):
            if path.is_symlink():
                return None
            relative = _safe_relative_path(path.relative_to(root).as_posix())
            if path.is_file():
                entries[relative] = "file"
            elif path.is_dir():
                entries[relative] = "directory"
            else:
                return None
    except (OSError, ValueError):
        return None
    return entries


def _pretty_json(value: object) -> str:
    normalized: object
    if isinstance(value, BaseModel):
        normalized = value.model_dump(mode="json")
    elif isinstance(value, tuple):
        normalized = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value
        ]
    else:
        normalized = value
    return (
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=_json_default,
        )
        + "\n"
    )


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"unsupported review bundle JSON value: {type(value).__name__}")


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _png_dimensions(body: bytes) -> tuple[int, int] | None:
    if len(body) < 24 or body[:8] != b"\x89PNG\r\n\x1a\n" or body[12:16] != b"IHDR":
        return None
    width = int.from_bytes(body[16:20], "big")
    height = int.from_bytes(body[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def _image_dimensions(body: bytes) -> tuple[int, int] | None:
    try:
        with Image.open(BytesIO(body)) as image:
            width, height = image.size
            image.verify()
    except (OSError, UnidentifiedImageError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _detected_image_media_type(body: bytes) -> str | None:
    try:
        with Image.open(BytesIO(body)) as image:
            image_format = image.format
            image.verify()
    except (OSError, UnidentifiedImageError, ValueError):
        return None
    return {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }.get(image_format or "")


def _dimensions_value(dimensions: tuple[int, int] | None) -> str:
    return "unreadable" if dimensions is None else f"{dimensions[0]}x{dimensions[1]}"
