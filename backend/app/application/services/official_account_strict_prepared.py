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

from app.application.ports.official_account_strict_visual import (
    ObserveVisualAuditSubject,
    ObserveVisualMediaEvidence,
    StrictVisualMediaEvidence,
    observe_quality_issue_codes,
    strict_audit_record_fingerprint,
)
from app.domain.image_similarity import perceptual_dhash
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
    StrictLayoutProjectionVersion,
    compact_strict_xiaosai_html,
    strict_layout_projection_version,
    validate_strict_upload_html_headroom,
)
from app.domain.official_account_upload_media import (
    OFFICIAL_ACCOUNT_UPLOAD_BODY_POLICY_VERSION,
    OFFICIAL_ACCOUNT_UPLOAD_CONTEXT_POLICY_VERSION,
    OFFICIAL_ACCOUNT_UPLOAD_COVER_POLICY_VERSION,
    normalize_official_account_upload_context,
)
from app.domain.official_account_visual_pipeline import (
    NATIVE_VISUAL_PIPELINE_VERSIONS,
    OBSERVE_VISUAL_PIPELINE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION,
    STRICT_VISUAL_PIPELINE_VERSION,
    StrictVisualPipelineVersion,
    native_visual_audit_releases,
    native_visual_plan_prompt_valid,
)
from app.domain.official_account_xiaosai_footer import XiaosaiFooterAsset, validate_xiaosai_footer

STRICT_PREPARED_CHILD_VERSION: Final = "wechat-draft-prepared-child-v2-native-strict"
OBSERVE_PREPARED_CHILD_VERSION: Final = "wechat-draft-prepared-child-v3-native-observe"
NATIVE_PREPARED_CHILD_VERSIONS = (STRICT_PREPARED_CHILD_VERSION, OBSERVE_PREPARED_CHILD_VERSION)


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
    *,
    policy_version: StrictVisualPipelineVersion = STRICT_VISUAL_PIPELINE_VERSION,
) -> None:
    """Consumer verifies the complete closed accepted projection; exporter owns DB proof."""
    expected = (("body", 0), ("body", 1), ("body", 2), ("body", 3), ("body", 4), ("cover", 0))
    if tuple((item.role, item.ordinal) for item in evidence) != expected:
        raise ValueError("strict prepared audit subjects are incomplete")
    if len({(item.plan_version, item.prompt_version) for item in evidence}) != 1:
        raise ValueError("native prepared generation prompt bundle is mixed")
    by_slot = {(item.role, item.ordinal): item for item in media}
    if len(by_slot) != len(media):
        raise ValueError("strict prepared media slots are duplicated")
    for item in evidence:
        observe = policy_version == OBSERVE_VISUAL_PIPELINE_VERSION
        if observe != isinstance(item, ObserveVisualMediaEvidence):
            raise ValueError("native prepared evidence policy changed")
        if isinstance(item, ObserveVisualMediaEvidence):
            subject = item.audit_subject
            if (
                not native_visual_audit_releases(
                    policy_version, item.audit_status, item.audit_issue_codes
                )
                or tuple(sorted(set(item.audit_issue_codes))) != item.audit_issue_codes
                or len(item.audit_issue_codes) > 16
                or any(
                    not code.startswith("strict_visual_") or len(code) > 80
                    for code in item.audit_issue_codes
                )
                or (item.audit_status == "accepted" and item.audit_issue_codes)
                or subject.request_fingerprint != item.audit_request_fingerprint
                or strict_audit_record_fingerprint(
                    subject, item.audit_status, item.audit_issue_codes
                )
                != item.audit_record_fingerprint
                or any(
                    getattr(item, field.name) != getattr(subject, field.name)
                    for field in fields(StrictVisualMediaEvidence)
                    if hasattr(subject, field.name) and field.name != "prompt_version"
                )
                or subject.publication_sha256 in subject.catalog_publication_sha256s
                or subject.upload_sha256 in subject.catalog_publication_sha256s
            ):
                raise ValueError("observe prepared audit identity changed")
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
            or not native_visual_plan_prompt_valid(item.plan_version, item.prompt_version)
            or item.native_output_size != "1536x1024"
            or item.upload_policy_version != policy
            or (item.upload_sha256, item.media_type, item.byte_size, item.width, item.height)
            != (asset.sha256, asset.media_type, asset.byte_size, asset.width, asset.height)
            or item.audit_record_fingerprint
            != fingerprint(
                "official-account-strict-visual-audit-record-v1",
                item.audit_request_fingerprint,
                item.audit_status if isinstance(item, ObserveVisualMediaEvidence) else "accepted",
                item.audit_issue_codes if isinstance(item, ObserveVisualMediaEvidence) else (),
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
    if policy_version == OBSERVE_VISUAL_PIPELINE_VERSION:
        observations = tuple(
            item for item in evidence if isinstance(item, ObserveVisualMediaEvidence)
        )
        subjects = tuple(item.audit_subject for item in observations)
        if len(observations) != 6 or len({item.publication_sha256 for item in bodies}) != 5:
            raise ValueError("observe prepared subjects are incomplete or repeated")
        for item in observations:
            if (
                item.audit_subject.catalog_publication_sha256s
                != subjects[0].catalog_publication_sha256s
                or item.audit_subject.catalog_perceptual_hashes
                != subjects[0].catalog_perceptual_hashes
                or item.quality_issue_codes
                != observe_quality_issue_codes(item.audit_subject, subjects[:5])
            ):
                raise ValueError("observe prepared quality observations changed")
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
    layout_projection_version: StrictLayoutProjectionVersion = STRICT_LAYOUT_PROJECTION_VERSION,
    visual_pipeline_version: StrictVisualPipelineVersion = STRICT_VISUAL_PIPELINE_VERSION,
    footer: XiaosaiFooterAsset | None = None,
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
    if visual_pipeline_version not in NATIVE_VISUAL_PIPELINE_VERSIONS:
        raise ValueError("native prepared visual policy is unsupported")
    validate_strict_visual_evidence(evidence, media, policy_version=visual_pipeline_version)
    v5_presentation = (
        evidence[0].prompt_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION
    )
    if v5_presentation != (footer is not None):
        raise ValueError("native prepared footer does not match frozen V5 policy")
    for proof in evidence:
        if isinstance(proof, ObserveVisualMediaEvidence) and (
            (
                proof.audit_subject.run_id,
                proof.audit_subject.article_version_id,
                proof.audit_subject.render_version_id,
            )
            != (run_id, article_version_id, render_version_id)
        ):
            raise ValueError("observe prepared relational identity changed")
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
    expected_paths = {item.path for item in media}
    if footer is not None:
        expected_paths.add(footer.path)
    if set(output_files) != expected_paths:
        raise ValueError("strict prepared media file set changed")
    if footer is not None:
        validate_xiaosai_footer(footer, article=article, content=output_files[footer.path])
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
        media_proof = next(
            (item for item in evidence if (item.role, item.ordinal) == (asset.role, asset.ordinal)),
            None,
        )
        if isinstance(media_proof, ObserveVisualMediaEvidence) and (
            media_proof.audit_subject.perceptual_hash != perceptual_dhash(body)
        ):
            raise ValueError("observe prepared perceptual subject changed")
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
    rendered = render_editor_handoff_v2_body(
        article=article,
        media=media,
        hide_body_captions=v5_presentation,
        hide_context_rights_notice=v5_presentation,
        footer=footer,
    )
    body_html = compact_strict_xiaosai_html(rendered.body_html, version=layout_projection_version)
    validate_strict_upload_html_headroom(
        body_html,
        (
            *tuple(item.path for item in media if item.role != "cover"),
            *((footer.path,) if footer is not None else ()),
        ),
    )
    output_files["article-body.html"] = body_html.encode("utf-8")
    identity: dict[str, object] = {
        "version": (
            OBSERVE_PREPARED_CHILD_VERSION
            if visual_pipeline_version == OBSERVE_VISUAL_PIPELINE_VERSION
            else STRICT_PREPARED_CHILD_VERSION
        ),
        "visual_pipeline_version": visual_pipeline_version,
        "role": role,
        "run_id": str(run_id),
        "article_version_id": str(article_version_id),
        "render_version_id": str(render_version_id),
        "article": article.model_dump(mode="json"),
        "article_fingerprint": article.content_fingerprint,
        "title": article.title,
        "author": article.author,
        "digest": article.digest,
        "media": [
            *(item.model_dump(mode="json") for item in media),
            *((footer.model_dump(mode="json"),) if footer is not None else ()),
        ],
        "visual_evidence": [json.loads(_canonical(asdict(item))) for item in evidence],
        "context_derivatives": derivatives,
        "renderer": EditorHandoffV2Identity().model_dump(mode="json"),
        "layout_projection_version": layout_projection_version,
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
    observe = manifest.get("version") == OBSERVE_PREPARED_CHILD_VERSION
    policy = OBSERVE_VISUAL_PIPELINE_VERSION if observe else STRICT_VISUAL_PIPELINE_VERSION
    if manifest.get("visual_pipeline_version") != policy:
        raise ValueError("native prepared policy/envelope mismatch")
    if (
        not isinstance(raw_media, list)
        or not isinstance(raw_evidence, list)
        or not isinstance(raw_derivatives, list)
    ):
        raise ValueError("strict prepared typed projections are missing")
    footer_items = [
        item for item in raw_media if isinstance(item, dict) and item.get("role") == "footer"
    ]
    if len(footer_items) > 1:
        raise ValueError("strict prepared footer media is duplicated")
    footer = XiaosaiFooterAsset.model_validate(footer_items[0]) if footer_items else None
    media = tuple(
        EditorHandoffMediaAsset.model_validate(item)
        for item in raw_media
        if not isinstance(item, dict) or item.get("role") != "footer"
    )
    evidence_fields = {
        item.name
        for item in fields(ObserveVisualMediaEvidence if observe else StrictVisualMediaEvidence)
    }
    if any(not isinstance(item, dict) or set(item) != evidence_fields for item in raw_evidence):
        raise ValueError("strict prepared audit field set changed")
    for item in raw_evidence:
        for name, value in item.items():
            if observe and name in {"audit_issue_codes", "quality_issue_codes"}:
                if not isinstance(value, list) or any(not isinstance(code, str) for code in value):
                    raise ValueError("observe prepared issue code type changed")
            elif observe and name == "audit_subject":
                if not isinstance(value, dict) or set(value) != {
                    field.name for field in fields(ObserveVisualAuditSubject)
                }:
                    raise ValueError("observe prepared subject field set changed")
            elif name in {"ordinal", "byte_size", "width", "height"}:
                if type(value) is not int:
                    raise ValueError("strict prepared audit numeric type changed")
            elif not isinstance(value, str):
                raise ValueError("strict prepared audit text type changed")
    evidence: tuple[StrictVisualMediaEvidence, ...] = tuple(
        TypeAdapter(ObserveVisualMediaEvidence).validate_json(_canonical(item), strict=True)
        if observe
        else TypeAdapter(StrictVisualMediaEvidence).validate_json(_canonical(item))
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
        files={
            **{asset.path: files[asset.path] for asset in media},
            **({footer.path: files[footer.path]} if footer is not None else {}),
        },
        context_originals={item.ordinal: files[item.source_path] for item in derivatives},
        layout_projection_version=strict_layout_projection_version(
            manifest.get("layout_projection_version")
        ),
        visual_pipeline_version=policy,
        footer=footer,
    )
    if _canonical(expected.manifest) != _canonical(manifest) or expected.files != dict(files):
        raise ValueError("strict prepared canonical projection changed")
