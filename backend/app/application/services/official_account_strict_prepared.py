"""Provider-free strict prepared-child projection and independent consumer validation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from hashlib import sha256
from io import BytesIO
from typing import Final, Literal
from uuid import UUID

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.application.ports.official_account_strict_visual import StrictVisualMediaEvidence
from app.domain.official_account_editor_handoff import EditorHandoffMediaAsset, media_asset_path
from app.domain.official_account_editor_handoff_v2 import (
    EditorHandoffV2Identity,
    render_editor_handoff_v2_body,
)
from app.domain.official_account_local import (
    STRICT_VISUAL_REFERENCE_POLICY_VERSION,
    ArticleImageBlock,
    ArticlePackage,
    article_package_fingerprint,
    fingerprint,
)
from app.domain.official_account_strict_layout import (
    STRICT_ESCAPED_UPLOAD_URL_MAX_CHARACTERS,
    STRICT_LAYOUT_PROJECTION_VERSION,
    compact_strict_xiaosai_html,
    validate_strict_upload_html_headroom,
)
from app.domain.official_account_upload_media import (
    OFFICIAL_ACCOUNT_UPLOAD_BODY_POLICY_VERSION,
    OFFICIAL_ACCOUNT_UPLOAD_CONTEXT_POLICY_VERSION,
    OFFICIAL_ACCOUNT_UPLOAD_COVER_POLICY_VERSION,
    normalize_official_account_upload_context,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION,
    STRICT_VISUAL_PIPELINE_VERSION,
)

STRICT_PREPARED_CHILD_VERSION: Final = "wechat-draft-prepared-child-v2-native-strict"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StrictPreparedFile(_Frozen):
    path: str = Field(pattern=r"^(?:article-body\.html|assets/[a-z0-9-]+\.(?:jpg|png|webp))$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=1, le=10 * 1024 * 1024)


class StrictContextDerivative(_Frozen):
    ordinal: int = Field(ge=0, le=1)
    source_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    upload_path: str
    upload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_version: Literal["official-account-upload-context-v1"] = (
        OFFICIAL_ACCOUNT_UPLOAD_CONTEXT_POLICY_VERSION
    )


@dataclass(frozen=True, slots=True)
class StrictPreparedProjection:
    files: dict[str, bytes]
    manifest: dict[str, object]
    child_fingerprint: str


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")


def _hash(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


def validate_strict_visual_evidence(
    evidence: tuple[StrictVisualMediaEvidence, ...],
    media: tuple[EditorHandoffMediaAsset, ...],
) -> None:
    """Consumer verifies the complete closed accepted projection; exporter owns DB proof."""
    expected = (("body", 0), ("body", 1), ("body", 2), ("body", 3), ("body", 4), ("cover", 0))
    if tuple((item.role, item.ordinal) for item in evidence) != expected:
        raise ValueError("strict prepared audit subjects are incomplete")
    by_slot = {(item.role, item.ordinal): item for item in media}
    if len(by_slot) != len(media):
        raise ValueError("strict prepared media slots are duplicated")
    for item in evidence:
        asset = by_slot.get((item.role, item.ordinal))
        if asset is None:
            raise ValueError("strict prepared audit asset is missing")
        policy = (
            OFFICIAL_ACCOUNT_UPLOAD_BODY_POLICY_VERSION
            if item.role == "body"
            else OFFICIAL_ACCOUNT_UPLOAD_COVER_POLICY_VERSION
        )
        if (
            item.provider != "zhipu"
            or item.model != "glm-5v-turbo"
            or item.plan_version != OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION
            or item.prompt_version != OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION
            or item.native_output_size != "1536x1024"
            or item.upload_policy_version != policy
            or (item.upload_sha256, item.media_type, item.byte_size, item.width, item.height)
            != (asset.sha256, asset.media_type, asset.byte_size, asset.width, asset.height)
            or item.audit_record_fingerprint
            != fingerprint(
                "official-account-strict-visual-audit-record-v1",
                item.audit_request_fingerprint,
                "accepted",
                (),
            )
        ):
            raise ValueError("strict prepared final-byte audit identity changed")
        for value in (
            item.generated_plan_request_fingerprint,
            item.reference_publication_sha256,
            item.publication_sha256,
            item.upload_sha256,
            item.audit_request_fingerprint,
        ):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("strict prepared audit hash is invalid")
        if len(item.reference_asset_ref) != 16 or any(
            c not in "0123456789abcdef" for c in item.reference_asset_ref
        ):
            raise ValueError("strict prepared public reference is invalid")
        if item.upload_sha256 == item.reference_publication_sha256:
            raise ValueError("strict prepared output cannot reuse a catalog publication")
        if (asset.width, asset.height) != ((1536, 1024) if item.role == "body" else (1175, 500)):
            raise ValueError("strict prepared upload geometry changed")
        if asset.media_type != "image/jpeg" or asset.byte_size >= (
            1024 * 1024 if item.role == "body" else 64 * 1024
        ):
            raise ValueError("strict prepared upload byte bound changed")
    bodies = evidence[:5]
    if (
        len({item.upload_sha256 for item in bodies}) != 5
        or len({item.generated_visual_id for item in bodies}) != 5
        or len({item.audit_id for item in evidence}) != 6
        or evidence[-1].generated_visual_id != bodies[0].generated_visual_id
        or evidence[-1].publication_sha256 != bodies[0].publication_sha256
        or evidence[-1].reference_asset_ref != bodies[0].reference_asset_ref
    ):
        raise ValueError("strict prepared body/cover lineage is invalid")


def build_strict_prepared_projection(
    *,
    run_id: UUID,
    article_version_id: UUID,
    render_version_id: UUID,
    role: str,
    article: ArticlePackage,
    media: tuple[EditorHandoffMediaAsset, ...],
    evidence: tuple[StrictVisualMediaEvidence, ...],
    files: Mapping[str, bytes],
    context_originals: Mapping[int, bytes],
) -> StrictPreparedProjection:
    """Render frozen Article and final upload media; retain separate exact news originals."""
    if role not in {"official_anchor", "industry_trend", "application_case"}:
        raise ValueError("strict prepared article role is invalid")
    if article.content_fingerprint != article_package_fingerprint(article):
        raise ValueError("strict prepared article content fingerprint changed")
    if article.media_selection is None or (
        article.media_selection.reference_policy_version != STRICT_VISUAL_REFERENCE_POLICY_VERSION
    ):
        raise ValueError("strict prepared reference selection policy changed")
    validate_strict_visual_evidence(evidence, media)
    if len(article.media_selection.assignments) != 5:
        raise ValueError("strict prepared reference assignments are incomplete")
    for assignment, proof in zip(article.media_selection.assignments, evidence[:5], strict=True):
        if (assignment.ordinal, assignment.candidate_ref, assignment.publication_checksum) != (
            proof.ordinal,
            proof.reference_asset_ref,
            proof.reference_publication_sha256,
        ):
            raise ValueError("strict prepared generated reference binding changed")
    expected_body = tuple(
        (int(block.slot_key.removeprefix("body-")), index, block.alt_text)
        for index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    bodies = tuple(item for item in media if item.role == "body")
    if (
        tuple((item.ordinal, item.assigned_section_index, item.alt_text) for item in bodies)
        != expected_body
    ):
        raise ValueError("strict prepared article image bindings changed")
    original_context = article.news_context_media.items if article.news_context_media else ()
    contexts = tuple(item for item in media if item.role == "context")
    if len(contexts) != len(original_context) or set(context_originals) != {
        item.ordinal for item in original_context
    }:
        raise ValueError("strict prepared source image count changed")
    output_files = dict(files)
    if set(output_files) != {item.path for item in media}:
        raise ValueError("strict prepared media file set changed")
    for asset in media:
        body = output_files[asset.path]
        if asset.path != media_asset_path(asset.role, asset.ordinal, asset.media_type):
            raise ValueError("strict prepared canonical media path changed")
        if len(body) != asset.byte_size or sha256(body).hexdigest() != asset.sha256:
            raise ValueError("strict prepared upload bytes changed")
        with Image.open(BytesIO(body)) as opened:
            if opened.size != (asset.width, asset.height):
                raise ValueError("strict prepared decoded media geometry changed")
            opened.load()
    derivatives: list[dict[str, object]] = []
    for source, asset in zip(original_context, contexts, strict=True):
        original = context_originals[source.ordinal]
        derivative = normalize_official_account_upload_context(original)
        if (
            derivative.source_sha256 != source.sha256
            or derivative.sha256 != asset.sha256
            or (derivative.width, derivative.height) != (source.width, source.height)
            or (
                asset.ordinal,
                asset.assigned_section_index,
                asset.alt_text,
                asset.source_page_url,
                asset.caption,
                asset.credit,
                asset.rights_status,
                asset.context_only_not_evidence,
            )
            != (
                source.ordinal,
                source.section_index,
                source.alt_text,
                source.source_page_url,
                source.caption,
                source.credit,
                source.rights_status,
                True,
            )
        ):
            raise ValueError("strict prepared news provenance changed")
        suffix = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[source.media_type]
        path = f"assets/source-context-{source.ordinal:02d}.{suffix}"
        output_files[path] = original
        derivatives.append(
            StrictContextDerivative(
                ordinal=source.ordinal,
                source_path=path,
                source_sha256=source.sha256,
                upload_path=asset.path,
                upload_sha256=asset.sha256,
            ).model_dump(mode="json")
        )
    rendered = render_editor_handoff_v2_body(article=article, media=media)
    body_html = compact_strict_xiaosai_html(rendered.body_html)
    validate_strict_upload_html_headroom(
        body_html, tuple(item.path for item in media if item.role != "cover")
    )
    output_files["article-body.html"] = body_html.encode("utf-8")
    identity: dict[str, object] = {
        "version": STRICT_PREPARED_CHILD_VERSION,
        "visual_pipeline_version": STRICT_VISUAL_PIPELINE_VERSION,
        "role": role,
        "run_id": str(run_id),
        "article_version_id": str(article_version_id),
        "render_version_id": str(render_version_id),
        "article": article.model_dump(mode="json"),
        "article_fingerprint": article.content_fingerprint,
        "title": article.title,
        "author": article.author,
        "digest": article.digest,
        "media": [item.model_dump(mode="json") for item in media],
        "visual_evidence": [json.loads(_canonical(asdict(item))) for item in evidence],
        "context_derivatives": derivatives,
        "renderer": EditorHandoffV2Identity().model_dump(mode="json"),
        "layout_projection_version": STRICT_LAYOUT_PROJECTION_VERSION,
        "escaped_upload_url_max_characters": STRICT_ESCAPED_UPLOAD_URL_MAX_CHARACTERS,
        "recipe": rendered.recipe.model_dump(mode="json"),
        "placements": [item.model_dump(mode="json") for item in rendered.placements],
        "files": [
            StrictPreparedFile(
                path=path, byte_size=len(body), sha256=sha256(body).hexdigest()
            ).model_dump(mode="json")
            for path, body in sorted(output_files.items())
        ],
        "published": False,
        "draft_only": True,
        "mobile_validation": "not_run",
    }
    identity["content_fingerprint"] = _hash(identity)
    child_fingerprint = _hash(identity)
    manifest = {**identity, "child_fingerprint": child_fingerprint}
    return StrictPreparedProjection(
        files=output_files, manifest=manifest, child_fingerprint=child_fingerprint
    )


def validate_strict_prepared_projection(
    manifest: dict[str, object],
    files: Mapping[str, bytes],
) -> None:
    """Rebuild exact pure projection, including source, placement and audit identities."""
    raw_media = manifest.get("media")
    raw_evidence = manifest.get("visual_evidence")
    raw_derivatives = manifest.get("context_derivatives")
    if (
        not isinstance(raw_media, list)
        or not isinstance(raw_evidence, list)
        or not isinstance(raw_derivatives, list)
    ):
        raise ValueError("strict prepared typed projections are missing")
    media = tuple(EditorHandoffMediaAsset.model_validate(item) for item in raw_media)
    evidence_fields = {item.name for item in fields(StrictVisualMediaEvidence)}
    if any(not isinstance(item, dict) or set(item) != evidence_fields for item in raw_evidence):
        raise ValueError("strict prepared audit field set changed")
    for item in raw_evidence:
        for name, value in item.items():
            if name in {"ordinal", "byte_size", "width", "height"}:
                if type(value) is not int:
                    raise ValueError("strict prepared audit numeric type changed")
            elif not isinstance(value, str):
                raise ValueError("strict prepared audit text type changed")
    evidence = tuple(
        TypeAdapter(StrictVisualMediaEvidence).validate_json(_canonical(item))
        for item in raw_evidence
    )
    derivatives = tuple(StrictContextDerivative.model_validate(item) for item in raw_derivatives)
    expected = build_strict_prepared_projection(
        run_id=UUID(str(manifest.get("run_id"))),
        article_version_id=UUID(str(manifest.get("article_version_id"))),
        render_version_id=UUID(str(manifest.get("render_version_id"))),
        role=str(manifest.get("role")),
        article=ArticlePackage.model_validate(manifest.get("article")),
        media=media,
        evidence=evidence,
        files={asset.path: files[asset.path] for asset in media},
        context_originals={item.ordinal: files[item.source_path] for item in derivatives},
    )
    if _canonical(expected.manifest) != _canonical(manifest) or expected.files != dict(files):
        raise ValueError("strict prepared canonical projection changed")
