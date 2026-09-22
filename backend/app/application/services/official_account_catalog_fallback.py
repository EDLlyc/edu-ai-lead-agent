"""Pure, versioned catalog fallback; never fabricated native-generation evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from io import BytesIO
from typing import Literal, cast
from uuid import UUID

from PIL import Image

from app.application.ports.official_account_strict_visual import (
    resilient_visual_provider_request_fingerprint,
)
from app.application.services.official_account_strict_prepared import StrictPreparedProjection
from app.core.errors import ImageGenerationFailure
from app.domain.official_account_editor_handoff import EditorHandoffMediaAsset
from app.domain.official_account_editor_handoff_v2 import render_editor_handoff_v2_body
from app.domain.official_account_local import ArticlePackage, article_package_fingerprint
from app.domain.official_account_source_presentation import CURRENT_SOURCE_PRESENTATION_VERSION
from app.domain.official_account_strict_layout import (
    STRICT_LAYOUT_PROJECTION_V2_VERSION,
    compact_strict_xiaosai_html,
)
from app.domain.official_account_upload_media import normalize_official_account_upload_context
from app.domain.official_account_visual_pipeline import TOLERANT_VISUAL_PIPELINE_VERSION
from app.domain.official_account_xiaosai_footer import (
    ChengyueIntroductionHeaderAsset,
    XiaosaiMarketingFooterAsset,
    validate_chengyue_header,
    validate_xiaosai_footer,
)

CATALOG_FALLBACK_CHILD_VERSION = "wechat-draft-prepared-child-v6-approved-catalog-fallback"
CATALOG_FALLBACK_ORIGIN = "approved_catalog_fallback"


def fallback_failure_allowed(value: object) -> bool:
    diagnostic = ImageGenerationFailure.from_safe_metadata(value)
    if diagnostic is None:
        return False
    if diagnostic.error_code == "image_output_invalid":
        return (
            diagnostic.reason == "image_dimensions_invalid" and diagnostic.disposition == "terminal"
        )
    if diagnostic.error_code == "image_provider_rejected":
        return (
            diagnostic.http_status is not None
            and diagnostic.http_status >= 500
            and diagnostic.disposition == "unknown"
        )
    return (
        diagnostic.error_code
        in {
            "provider_unavailable",
            "provider_rate_limited",
            "image_provider_timeout",
            "official_account_generated_visual_result_unknown",
        }
        and diagnostic.reason
        in {
            "connect_failed",
            "connect_timeout",
            "pool_timeout",
            "post_rate_limited",
            "post_outcome_unknown",
            "provider_failure",
            "artifact_persistence_failed",
        }
        and diagnostic.disposition in {"unknown", "not_applied_retryable"}
    )


def validate_fallback_evidence(evidence: dict[str, object]) -> None:
    if (
        set(evidence)
        != {
            "version",
            "physical_attempt_count",
            "failed_slot",
            "logical_request_fingerprint",
            "attempts",
        }
        or evidence["version"] != "single-catalog-fallback-evidence-v1"
        or type(evidence["physical_attempt_count"]) is not int
        or evidence["physical_attempt_count"] != 3
        or type(evidence["failed_slot"]) is not int
        or not 0 <= evidence["failed_slot"] < 5
        or not isinstance(evidence["logical_request_fingerprint"], str)
        or not isinstance(evidence["attempts"], list)
        or len(evidence["attempts"]) != 3
    ):
        raise ValueError("single_catalog_fallback_evidence_invalid")
    for number, attempt in enumerate(evidence["attempts"], 1):
        if (
            not isinstance(attempt, dict)
            or set(attempt) != {"request_fingerprint", "diagnostic"}
            or attempt["request_fingerprint"]
            != resilient_visual_provider_request_fingerprint(
                evidence["logical_request_fingerprint"],
                number,
                policy=TOLERANT_VISUAL_PIPELINE_VERSION,
            )
            or not fallback_failure_allowed(attempt["diagnostic"])
        ):
            raise ValueError("single_catalog_fallback_attempt_invalid")


def _hash(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_catalog_fallback_projection(
    *,
    run_id: UUID,
    article_version_id: UUID,
    render_version_id: UUID,
    article: ArticlePackage,
    role: str,
    failure_evidence: dict[str, object],
    bodies: tuple[bytes, ...],
    contexts: Mapping[int, bytes],
    header: ChengyueIntroductionHeaderAsset,
    header_bytes: bytes,
    footer: XiaosaiMarketingFooterAsset,
    footer_bytes: bytes,
) -> StrictPreparedProjection:
    # Keep all five frozen originals so the consumer can independently reproduce
    # the catalog checksums, upload derivatives, HTML and content identity.
    from app.application.services.wechat_official_account_draft import (
        _normalize_cover_thumb,
        _normalize_inline_image,
    )

    selection = article.media_selection
    validate_fallback_evidence(failure_evidence)
    if (
        selection is None
        or len(bodies) != 5
        or [item.ordinal for item in selection.assignments] != list(range(5))
        or article_package_fingerprint(article) != article.content_fingerprint
        or role not in {"official_anchor", "industry_trend", "application_case"}
        or failure_evidence.get("version") != "single-catalog-fallback-evidence-v1"
        or failure_evidence.get("physical_attempt_count") != 3
    ):
        raise ValueError("single_catalog_fallback_identity_invalid")
    validate_chengyue_header(header, content=header_bytes)
    validate_xiaosai_footer(footer, article=article, content=footer_bytes)
    files = {header.path: header_bytes, footer.path: footer_bytes}
    assets: list[EditorHandoffMediaAsset] = []

    def asset(
        path: str,
        body: bytes,
        media_role: Literal["body", "context", "cover"],
        ordinal: int,
        section: int | None,
        alt: str,
        **extra: object,
    ) -> None:
        with Image.open(BytesIO(body)) as image:
            image.load()
            width, height = image.size
            media_type = "image/png" if image.format == "PNG" else "image/jpeg"
        files[path] = body
        assets.append(
            EditorHandoffMediaAsset.model_validate(
                {
                    "path": path,
                    "role": media_role,
                    "ordinal": ordinal,
                    "media_type": media_type,
                    "byte_size": len(body),
                    "sha256": sha256(body).hexdigest(),
                    "width": width,
                    "height": height,
                    "assigned_section_index": section,
                    "alt_text": alt,
                    **extra,
                }
            )
        )

    for assignment, original in zip(selection.assignments, bodies, strict=True):
        if sha256(original).hexdigest() != assignment.publication_checksum:
            raise ValueError("single_catalog_fallback_bytes_changed")
        files[f"assets/catalog-source-{assignment.ordinal:02d}.jpg"] = original
        asset(
            f"assets/body-{assignment.ordinal:02d}.jpg",
            _normalize_inline_image(original),
            "body",
            assignment.ordinal,
            assignment.section_index,
            "小赛科学教育品牌插画",
        )
    context_items = article.news_context_media.items if article.news_context_media else ()
    if set(contexts) != {item.ordinal for item in context_items}:
        raise ValueError("single_catalog_fallback_context_missing")
    for item in context_items:
        original = contexts[item.ordinal]
        if sha256(original).hexdigest() != item.sha256:
            raise ValueError("single_catalog_fallback_context_changed")
        files[f"assets/context-source-{item.ordinal:02d}.jpg"] = original
        derivative = normalize_official_account_upload_context(original)
        suffix = "png" if derivative.mime_type == "image/png" else "jpg"
        asset(
            f"assets/context-{item.ordinal:02d}.{suffix}",
            derivative.content,
            "context",
            item.ordinal,
            item.section_index,
            item.alt_text,
            source_page_url=item.source_page_url,
            caption=item.caption,
            credit=item.credit,
            rights_status=item.rights_status,
            context_only_not_evidence=True,
        )
    asset(
        "assets/cover-wide.jpg", _normalize_cover_thumb(bodies[0]), "cover", 0, None, article.title
    )
    rendered = render_editor_handoff_v2_body(
        article=article,
        media=tuple(assets),
        hide_body_captions=True,
        header=header,
        footer=footer,
        source_presentation=CURRENT_SOURCE_PRESENTATION_VERSION,
    )
    body_html = compact_strict_xiaosai_html(
        rendered.body_html,
        version=STRICT_LAYOUT_PROJECTION_V2_VERSION,
    )
    files["article-body.html"] = body_html.encode()
    identity: dict[str, object] = {
        "version": CATALOG_FALLBACK_CHILD_VERSION,
        "origin": CATALOG_FALLBACK_ORIGIN,
        "visual_pipeline_version": TOLERANT_VISUAL_PIPELINE_VERSION,
        "layout_projection_version": STRICT_LAYOUT_PROJECTION_V2_VERSION,
        "source_presentation_version": CURRENT_SOURCE_PRESENTATION_VERSION,
        "content_source_url": None,
        "run_id": str(run_id),
        "article_version_id": str(article_version_id),
        "render_version_id": str(render_version_id),
        "role": role,
        "article": article.model_dump(mode="json"),
        "article_fingerprint": article.content_fingerprint,
        "title": article.title,
        "author": article.author,
        "digest": article.digest,
        "failure_evidence": failure_evidence,
        "media": [
            header.model_dump(mode="json"),
            *(item.model_dump(mode="json") for item in assets),
            footer.model_dump(mode="json"),
        ],
        "files": [
            {"path": path, "sha256": sha256(body).hexdigest(), "byte_size": len(body)}
            for path, body in sorted(files.items())
        ],
        "draft_only": True,
        "published": False,
    }
    identity["content_fingerprint"] = _hash(identity)
    child = _hash(identity)
    return StrictPreparedProjection(files, {**identity, "child_fingerprint": child}, child)


def validate_catalog_fallback_projection(
    manifest: dict[str, object],
    files: Mapping[str, bytes],
) -> None:
    raw_media = manifest.get("media")
    if not isinstance(raw_media, list) or not raw_media:
        raise ValueError("single_catalog_fallback_media_missing")
    article = ArticlePackage.model_validate(manifest.get("article"))
    header = ChengyueIntroductionHeaderAsset.model_validate(raw_media[0])
    footer = XiaosaiMarketingFooterAsset.model_validate(raw_media[-1])
    evidence = manifest.get("failure_evidence")
    if not isinstance(evidence, dict):
        raise ValueError("single_catalog_fallback_evidence_missing")
    expected = build_catalog_fallback_projection(
        run_id=UUID(str(manifest.get("run_id"))),
        article_version_id=UUID(str(manifest.get("article_version_id"))),
        render_version_id=UUID(str(manifest.get("render_version_id"))),
        article=article,
        role=str(manifest.get("role")),
        failure_evidence=cast(dict[str, object], evidence),
        bodies=tuple(files[f"assets/catalog-source-{n:02d}.jpg"] for n in range(5)),
        contexts={
            item.ordinal: files[f"assets/context-source-{item.ordinal:02d}.jpg"]
            for item in (article.news_context_media.items if article.news_context_media else ())
        },
        header=header,
        header_bytes=files[header.path],
        footer=footer,
        footer_bytes=files[footer.path],
    )
    if expected.manifest != manifest or expected.files != dict(files):
        raise ValueError("single_catalog_fallback_projection_changed")
