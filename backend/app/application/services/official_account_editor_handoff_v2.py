"""Automatic, read-only V2 local WeChat editor handoff projection."""

# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional export copy.

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast
from uuid import UUID

from PIL import UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.official_account_local import (
    OfficialAccountMediaResult,
    StoredOfficialAccountArticle,
    StoredOfficialAccountGeneratedVisual,
    StoredOfficialAccountManualReview,
)
from app.application.services import official_account_editor_handoff as v1
from app.application.services.official_account_local import manual_review_request_fingerprint
from app.application.services.official_account_visual_generation import (
    select_generated_visual_block_anchor,
)
from app.core.errors import AppError
from app.domain.official_account_editor_handoff import (
    EditorHandoffCheck,
    EditorHandoffMediaAsset,
    canonical_theme_projection,
)
from app.domain.official_account_editor_handoff_v2 import (
    BodyVisualLineage,
    BodyVisualReferenceProjection,
    ContextBlockPlacement,
    EditorHandoffLayoutRecipe,
    EditorHandoffMobileValidation,
    EditorHandoffRelease,
    EditorHandoffV2Identity,
    EditorHandoffV2Preflight,
    SemanticEmphasisBlock,
    fingerprint_v2,
    render_editor_handoff_v2_body,
    run_editor_handoff_v2_preflight,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    ArticleBulletListBlock,
    ArticleImageBlock,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleQuoteBlock,
    article_package_fingerprint,
    article_version_bundle_kind,
    fingerprint,
    render_wechat_html,
)
from app.infrastructure.db.models import OfficialAccountLocalMediaModel
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from app.infrastructure.official_account_media import (
    OfficialAccountLocalMediaResolver,
    OfficialAccountMediaIntegrityError,
    OfficialAccountPersistedMedia,
    persisted_media_snapshot,
)

ReleasePolicy = Literal["manual_only", "quality_auto"]


@dataclass(frozen=True, slots=True)
class EditorHandoffV2Artifact:
    run_id: UUID
    content_fingerprint: str
    artifact_fingerprint: str
    identity: EditorHandoffV2Identity
    release: EditorHandoffRelease
    recipe: EditorHandoffLayoutRecipe
    placements: tuple[ContextBlockPlacement, ...]
    emphasis: tuple[SemanticEmphasisBlock, ...]
    body_visuals: tuple[BodyVisualLineage, ...]
    mobile_validation: EditorHandoffMobileValidation
    preflight: EditorHandoffV2Preflight
    eligibility_checks: tuple[EditorHandoffCheck, ...]
    media: tuple[EditorHandoffMediaAsset, ...]
    files: Mapping[str, bytes]
    zip_bytes: bytes
    zip_sha256: str
    bundle_filename: str

    @property
    def fingerprint(self) -> str:
        return self.artifact_fingerprint

    @property
    def body_html(self) -> bytes:
        return self.files["article-body.html"]

    @property
    def preview_html(self) -> bytes:
        return self.files["preview.html"]


@dataclass(frozen=True, slots=True)
class EditorHandoffV2Inspection:
    run_id: UUID
    state: Literal["blocked", "ready"]
    checks: tuple[EditorHandoffCheck, ...]
    artifact: EditorHandoffV2Artifact | None

    @property
    def blocking_codes(self) -> tuple[str, ...]:
        return tuple(
            item.code for item in self.checks if item.severity == "error" and not item.passed
        )

    @property
    def warning_codes(self) -> tuple[str, ...]:
        return tuple(
            item.code for item in self.checks if item.severity == "warning" and not item.passed
        )


class OfficialAccountEditorHandoffV2Service:
    """Build V2 artifacts from durable local state without provider or publish clients."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        resolver: OfficialAccountLocalMediaResolver,
        release_policy: ReleasePolicy,
    ) -> None:
        self._session_factory = session_factory
        self._repository = PostgresOfficialAccountRepository(session_factory)
        self._resolver = resolver
        self._release_policy = release_policy

    async def inspect(self, run_id: UUID) -> EditorHandoffV2Inspection:
        run = await self._repository.get_run(run_id)
        checks: list[EditorHandoffCheck] = []

        def gate(code: str, passed: bool, field: str, detail: str) -> None:
            checks.append(
                EditorHandoffCheck(
                    code=code,
                    severity="info" if passed else "error",
                    passed=passed,
                    field=field,
                    detail=detail,
                )
            )

        gate("run_ready", run.status == "ready", "run.status", "运行状态必须为 ready")
        article = await self._repository.get_article(run_id)
        gate("article_present", article is not None, "article", "结构化文章必须存在")
        article_version_supported = False
        if article is not None:
            article_version_supported = (
                article_version_bundle_kind(article.article.versions) is not None
            )
            gate(
                "article_version_supported",
                article_version_supported,
                "article.versions",
                "文章版本身份必须可重放",
            )
            gate(
                "article_fingerprint_valid",
                article.article.content_fingerprint == article_package_fingerprint(article.article),
                "article.content_fingerprint",
                "文章内容指纹必须匹配",
            )
            gate(
                "deterministic_validation_passed",
                article.validation_passed,
                "article.validation",
                "确定性文章校验必须通过",
            )
            gate(
                "model_audit_accepted",
                article.audit is not None and article.audit.accepted,
                "article.audit",
                "模型审校必须接受文章",
            )
            gate(
                "image_validation_passed",
                article.article.quality.inherited_image_validation_passed,
                "article.quality.inherited_image_validation_passed",
                "继承的图片确定性质量校验必须通过",
            )
            gate(
                "image_audit_accepted",
                article.article.quality.inherited_image_audit_status
                in {"accepted", "not_applicable"},
                "article.quality.inherited_image_audit_status",
                "图片审校必须接受或明确不适用",
            )

        draft = await self._repository.get_draft(run_id)
        render = await self._repository.get_render(run_id)
        gate("render_present", render is not None, "render", "固定渲染必须存在")
        if article is not None and render is not None and article_version_supported:
            gate(
                "render_article_lineage_valid",
                render.article_version_id == article.id,
                "render.article_version_id",
                "固定渲染必须属于当前结构化文章版本",
            )
            try:
                expected_render = render_wechat_html(article.article)
            except ValueError:
                render_valid = False
            else:
                render_valid = (
                    render.canonical_html == expected_render.canonical_html
                    and render.render_fingerprint == expected_render.render_fingerprint
                )
            gate(
                "render_fingerprint_valid",
                render_valid,
                "render.render_fingerprint",
                "固定渲染正文和指纹必须匹配文章版本",
            )
        draft_ready = bool(
            draft is not None
            and getattr(draft, "state", None) == "ready"
            and getattr(draft, "simulation", None) is True
        )
        gate("simulated_draft_ready", draft_ready, "draft", "本地模拟草稿必须就绪")
        if draft is not None and render is not None:
            gate(
                "draft_fingerprint_valid",
                draft.resolved_fingerprint
                == fingerprint(
                    render.render_fingerprint,
                    draft.request_fingerprint,
                    draft.resolved_html,
                ),
                "draft.resolved_fingerprint",
                "本地草稿必须匹配不可变渲染谱系",
            )

        review = await self._repository.get_manual_review(run_id)
        review_valid = review is not None and review.request_fingerprint == (
            manual_review_request_fingerprint(
                run_id=run_id,
                decision=review.decision,
                reviewer_label=review.reviewer_label,
                note=review.note,
            )
            if review is not None
            else ""
        )
        if review is not None:
            gate(
                "manual_review_not_rejected",
                review.decision != "rejected",
                "manual_review.decision",
                "已有人工拒绝始终优先阻断自动放行",
            )
            gate(
                "review_fingerprint_valid",
                review_valid,
                "manual_review.request_fingerprint",
                "人工审稿指纹必须匹配不可变审稿输入",
            )
        if self._release_policy == "manual_only":
            gate(
                "immutable_review_approved",
                review is not None and review.decision == "approved" and review_valid,
                "manual_review",
                "manual_only 策略要求不可变人工批准",
            )

        generated_visuals = await self._repository.list_generated_visuals(run_id=run_id)
        body_slot_count = (
            sum(
                isinstance(block, ArticleImageBlock)
                for section in article.article.sections
                for block in section.blocks
            )
            if article is not None
            else 0
        )
        generated_visuals_ready = (
            body_slot_count > 0
            and len(generated_visuals) == body_slot_count
            and tuple(item.plan.ordinal for item in generated_visuals)
            == tuple(range(body_slot_count))
            and all(
                item.status == "ready"
                and item.plan.plan_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION
                and item.plan.prompt_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION
                and item.plan.output_profile_version
                == OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION
                and item.plan.block_index is not None
                and item.plan.block_kind is not None
                and item.plan.block_fingerprint is not None
                and item.plan.reference_input_checksum is not None
                and item.media_type == "image/jpeg"
                and item.width == 1_536
                and item.height == 1_024
                and item.sha256 is not None
                for item in generated_visuals
            )
        )
        gate(
            "generated_visuals_ready",
            generated_visuals_ready,
            "generated_visuals",
            "每个正文图位都必须有当前 V3 正文块参考生图的 ready 持久化结果",
        )

        if any(item.severity == "error" and not item.passed for item in checks):
            return EditorHandoffV2Inspection(
                run_id=run_id, state="blocked", checks=tuple(checks), artifact=None
            )
        if article is None or draft is None or render is None:
            raise RuntimeError("V2 editor handoff gate narrowing failed")

        release_kind: Literal["manual", "machine"] = (
            "manual" if review is not None and review.decision == "approved" else "machine"
        )
        release_fingerprint = fingerprint_v2(
            self._release_policy,
            run.request_fingerprint,
            article.article.content_fingerprint,
            render.render_fingerprint,
            draft.resolved_fingerprint,
            tuple((item.code, item.passed) for item in checks),
            review.request_fingerprint if release_kind == "manual" and review is not None else None,
            tuple(
                (item.plan.request_fingerprint, item.status, item.sha256)
                for item in generated_visuals
            ),
        )
        release = EditorHandoffRelease(
            policy=self._release_policy,
            kind=release_kind,
            input_fingerprint=release_fingerprint,
            gate_codes=tuple(item.code for item in checks if item.passed),
            manual_review_fingerprint=(
                review.request_fingerprint
                if release_kind == "manual" and review is not None
                else None
            ),
        )

        try:
            media_rows = await self._load_media_rows(run_id)
            body_visuals = _durable_body_visual_lineages(
                article=article,
                generated_visuals=generated_visuals,
                media_rows=media_rows,
            )
            verified = await self._resolve_media(media_rows)
            artifact = build_editor_handoff_v2_artifact(
                run_id=run_id,
                run_request_fingerprint=run.request_fingerprint,
                article=article.article,
                release=release,
                review=review if release_kind == "manual" else None,
                draft_resolved_fingerprint=draft.resolved_fingerprint,
                media=verified,
                body_visuals=body_visuals,
                eligibility_checks=tuple(checks),
            )
        except (
            KeyError,
            OfficialAccountMediaIntegrityError,
            RuntimeError,
            UnidentifiedImageError,
            ValueError,
        ):
            failed = EditorHandoffCheck(
                code="handoff_v2_integrity_failed",
                severity="error",
                passed=False,
                field="handoff",
                detail="V2 媒体、正文、定位或交接包完整性校验失败",
            )
            return EditorHandoffV2Inspection(
                run_id=run_id,
                state="blocked",
                checks=tuple([*checks, failed]),
                artifact=None,
            )
        return EditorHandoffV2Inspection(
            run_id=run_id,
            state="ready",
            checks=artifact.preflight.checks,
            artifact=artifact,
        )

    async def require_artifact(self, run_id: UUID) -> EditorHandoffV2Artifact:
        inspection = await self.inspect(run_id)
        if inspection.artifact is None:
            code = inspection.blocking_codes[0] if inspection.blocking_codes else "handoff_blocked"
            raise AppError(code, "official-account V2 editor handoff is blocked", 409)
        return inspection.artifact

    async def _load_media_rows(
        self, run_id: UUID
    ) -> tuple[tuple[OfficialAccountPersistedMedia, OfficialAccountMediaResult], ...]:
        async with self._session_factory() as session:
            rows = tuple(
                (
                    await session.scalars(
                        select(OfficialAccountLocalMediaModel)
                        .where(
                            OfficialAccountLocalMediaModel.run_id == run_id,
                            OfficialAccountLocalMediaModel.status == "ready",
                        )
                        .order_by(
                            OfficialAccountLocalMediaModel.role,
                            OfficialAccountLocalMediaModel.ordinal,
                        )
                    )
                ).all()
            )
        results = await self._repository.list_media(run_id)
        by_identity = {(item.role, item.ordinal): item for _row_id, item in results}
        return tuple(
            (
                persisted_media_snapshot(row),
                by_identity[(cast(Literal["body", "cover", "context"], row.role), row.ordinal)],
            )
            for row in rows
        )

    async def _resolve_media(
        self,
        rows: tuple[tuple[OfficialAccountPersistedMedia, OfficialAccountMediaResult], ...],
    ) -> tuple[tuple[OfficialAccountMediaResult, bytes], ...]:
        verified: list[tuple[OfficialAccountMediaResult, bytes]] = []
        for snapshot, result in rows:
            async with self._session_factory() as session:
                body = await self._resolver.read_verified_bytes(session=session, media=snapshot)
            if len(body) != result.byte_size or sha256(body).hexdigest() != result.sha256:
                raise OfficialAccountMediaIntegrityError("V2 editor handoff media bytes changed")
            verified.append((result, body))
        return tuple(verified)


def _durable_body_visual_lineages(
    *,
    article: StoredOfficialAccountArticle,
    generated_visuals: tuple[StoredOfficialAccountGeneratedVisual, ...],
    media_rows: tuple[tuple[OfficialAccountPersistedMedia, OfficialAccountMediaResult], ...],
) -> tuple[BodyVisualLineage, ...]:
    """Project only safe V3 reference-conditioned lineage from durable ready rows."""

    body_rows = tuple(
        sorted(
            (item for item in media_rows if item[0].role == "body"),
            key=lambda item: item[0].ordinal,
        )
    )
    if len(body_rows) != len(generated_visuals):
        raise ValueError("V2 durable body media and generated visuals are incomplete")
    projected: list[BodyVisualLineage] = []
    for visual, (snapshot, result) in zip(generated_visuals, body_rows, strict=True):
        plan = visual.plan
        if (
            visual.status != "ready"
            or snapshot.generated_visual_id != visual.id
            or snapshot.descriptor.get("source_kind") != "generated_visual"
            or snapshot.ordinal != plan.ordinal
            or result.role != "body"
            or result.ordinal != plan.ordinal
            or result.sha256 != visual.sha256
            or result.media_type != visual.media_type
            or result.byte_size != visual.byte_size
            or result.assigned_section_index != plan.section_index
            or plan.block_index is None
            or plan.block_kind is None
            or plan.block_fingerprint is None
            or plan.reference_input_checksum is None
        ):
            raise ValueError("V2 durable generated body-visual lineage changed")
        anchor = select_generated_visual_block_anchor(
            article=article,
            section_index=plan.section_index,
        )
        if (
            anchor.block_index != plan.block_index
            or anchor.block_kind != plan.block_kind
            or anchor.block_fingerprint != plan.block_fingerprint
        ):
            raise ValueError("V2 durable generated visual is not bound to the current text block")
        if (
            visual.sha256 is None
            or visual.media_type != "image/jpeg"
            or visual.byte_size is None
            or visual.width != 1_536
            or visual.height != 1_024
        ):
            raise ValueError("V2 durable generated visual output is incomplete")
        projected.append(
            BodyVisualLineage(
                ordinal=plan.ordinal,
                section_index=plan.section_index,
                block_index=anchor.block_index,
                block_kind=anchor.block_kind,
                block_fingerprint=anchor.block_fingerprint,
                scene_brief=anchor.scene_text,
                scene_brief_fingerprint=fingerprint_v2(
                    "editor-handoff-body-visual-scene-brief-v1",
                    plan.section_index,
                    anchor.block_index,
                    anchor.block_kind,
                    anchor.scene_text,
                ),
                reference=BodyVisualReferenceProjection(
                    public_ref=plan.reference_asset_ref,
                    catalog_version=plan.reference_catalog_version,
                    role="identity_reference",
                    # V3 is the explicit visible Xiaosai / Sai Xiansheng prompt contract.
                    # Durable storage intentionally keeps no catalog raw IDs or private metadata.
                    character_labels=("xiao-sai", "sai-xiansheng"),
                    source_checksum=plan.reference_source_checksum,
                    publication_checksum=plan.reference_publication_checksum,
                    input_version=cast(
                        Literal["image-reference-input-v2-png-preserve-jpeg-normalize"],
                        plan.reference_input_version,
                    ),
                    input_checksum=plan.reference_input_checksum,
                ),
                selection_method=plan.selection_method,
                similarity_band=plan.similarity_band,
                generation_kind="persisted_reference_conditioned_output",
                provider_execution="persisted_result",
                plan_version=cast(
                    Literal["official-account-generated-visual-plan-v3-visible-ip"],
                    plan.plan_version,
                ),
                prompt_version=cast(
                    Literal["official-account-generated-visual-prompt-v3-visible-ip-block-scene"],
                    plan.prompt_version,
                ),
                output_profile_version=cast(
                    Literal["official-account-generated-body-publication-v2-3x2-jpeg"],
                    plan.output_profile_version,
                ),
                plan_fingerprint=plan.request_fingerprint,
                output_sha256=visual.sha256,
                output_byte_size=visual.byte_size,
                visible_character_labels=("xiao-sai", "sai-xiansheng"),
                visibility_status="durable_image_audit_accepted",
            )
        )
    return tuple(projected)


def build_editor_handoff_v2_artifact(
    *,
    run_id: UUID,
    run_request_fingerprint: str,
    article: ArticlePackage,
    release: EditorHandoffRelease,
    review: StoredOfficialAccountManualReview | None,
    draft_resolved_fingerprint: str,
    media: tuple[tuple[OfficialAccountMediaResult, bytes], ...],
    body_visuals: tuple[BodyVisualLineage, ...],
    eligibility_checks: tuple[EditorHandoffCheck, ...],
    mobile_validation: EditorHandoffMobileValidation | None = None,
) -> EditorHandoffV2Artifact:
    identity = EditorHandoffV2Identity()
    media_assets, asset_bodies = v1._build_media_assets(article=article, media=media)
    rendered = render_editor_handoff_v2_body(article=article, media=media_assets)
    preview = v1._preview_document(rendered.body_html)
    content_fingerprint = fingerprint_v2(
        identity.model_dump(mode="json"),
        release.model_dump(mode="json"),
        run_id,
        run_request_fingerprint,
        article.content_fingerprint,
        draft_resolved_fingerprint,
        rendered.body_sha256,
        rendered.recipe.model_dump(mode="json"),
        tuple(item.model_dump(mode="json") for item in rendered.placements),
        tuple(
            (item.path, item.sha256, item.byte_size, item.width, item.height)
            for item in media_assets
        ),
        tuple(item.model_dump(mode="json") for item in body_visuals),
    )
    mobile = mobile_validation or EditorHandoffMobileValidation(status="not_run")
    artifact_fingerprint = fingerprint_v2(content_fingerprint, mobile.model_dump(mode="json"))
    preflight = run_editor_handoff_v2_preflight(
        article=article,
        body_html=rendered.body_html,
        preview_html=preview,
        media=media_assets,
        body_visuals=body_visuals,
        release=release,
        placements=rendered.placements,
        emphasis=rendered.emphasis,
        mobile_validation=mobile,
        content_fingerprint=content_fingerprint,
        extra_checks=eligibility_checks,
    )
    if not preflight.passed:
        raise ValueError("V2 editor handoff preflight failed")
    return _assemble_artifact(
        run_id=run_id,
        run_request_fingerprint=run_request_fingerprint,
        article=article,
        review=review,
        release=release,
        identity=identity,
        recipe=rendered.recipe,
        placements=rendered.placements,
        emphasis=rendered.emphasis,
        body_visuals=body_visuals,
        media=media_assets,
        asset_bodies=asset_bodies,
        body_html=rendered.body_html,
        preview_html=preview,
        content_fingerprint=content_fingerprint,
        artifact_fingerprint=artifact_fingerprint,
        draft_resolved_fingerprint=draft_resolved_fingerprint,
        mobile_validation=mobile,
        preflight=preflight,
        eligibility_checks=eligibility_checks,
    )


def bind_editor_handoff_v2_mobile_validation(
    artifact: EditorHandoffV2Artifact,
    report: EditorHandoffMobileValidation,
) -> EditorHandoffV2Artifact:
    """Create a new artifact identity only for an exact passed browser report."""
    if report.status != "passed":
        raise ValueError("only a passed browser report can finalize a V2 artifact")
    if (
        report.content_fingerprint != artifact.content_fingerprint
        or report.body_sha256 != sha256(artifact.body_html).hexdigest()
        or report.media_sha256s != tuple(item.sha256 for item in artifact.media)
    ):
        raise ValueError("browser report does not match the V2 content identity")
    article = ArticlePackage.model_validate(json.loads(artifact.files["article.json"]))
    body_visual_payload = json.loads(artifact.files["body-visuals.json"])
    if body_visual_payload.get("version") != artifact.identity.body_visual_lineage_version:
        raise ValueError("V2 body-visual lineage version changed")
    body_visual_rows = body_visual_payload.get("items")
    if not isinstance(body_visual_rows, list):
        raise ValueError("V2 body-visual lineage is invalid")
    body_visuals = tuple(BodyVisualLineage.model_validate(item) for item in body_visual_rows)
    if body_visuals != artifact.body_visuals:
        raise ValueError("V2 body-visual lineage changed")
    asset_bodies = {item.path: artifact.files[item.path] for item in artifact.media}
    preview = artifact.preview_html.decode("utf-8")
    body = artifact.body_html.decode("utf-8")
    preflight = run_editor_handoff_v2_preflight(
        article=article,
        body_html=body,
        preview_html=preview,
        media=artifact.media,
        body_visuals=body_visuals,
        release=artifact.release,
        placements=artifact.placements,
        emphasis=artifact.emphasis,
        mobile_validation=report,
        content_fingerprint=artifact.content_fingerprint,
        extra_checks=artifact.eligibility_checks,
    )
    if not preflight.passed:
        raise ValueError("passed browser report failed V2 preflight binding")
    review_payload = json.loads(artifact.files["review.json"])
    review = None
    if review_payload.get("status") == "approved":
        review = StoredOfficialAccountManualReview(
            id=UUID(review_payload["review_id"]),
            run_id=artifact.run_id,
            decision="approved",
            reviewer_label=review_payload["reviewer_label"],
            note=review_payload.get("note"),
            request_fingerprint=review_payload["request_fingerprint"],
            reviewed_at=datetime.fromisoformat(review_payload["reviewed_at"]),
        )
    artifact_fingerprint = fingerprint_v2(
        artifact.content_fingerprint, report.model_dump(mode="json")
    )
    manifest = json.loads(artifact.files["manifest.json"])
    return _assemble_artifact(
        run_id=artifact.run_id,
        run_request_fingerprint=manifest["lineage"]["run_request_fingerprint"],
        article=article,
        review=review,
        release=artifact.release,
        identity=artifact.identity,
        recipe=artifact.recipe,
        placements=artifact.placements,
        emphasis=artifact.emphasis,
        body_visuals=body_visuals,
        media=artifact.media,
        asset_bodies=asset_bodies,
        body_html=body,
        preview_html=preview,
        content_fingerprint=artifact.content_fingerprint,
        artifact_fingerprint=artifact_fingerprint,
        draft_resolved_fingerprint=manifest["lineage"]["draft_resolved_fingerprint"],
        mobile_validation=report,
        preflight=preflight,
        eligibility_checks=artifact.eligibility_checks,
    )


def write_editor_handoff_v2_artifact(artifact: EditorHandoffV2Artifact, output_root: Path) -> Path:
    root = output_root.expanduser().resolve()
    if root == Path(root.anchor):
        raise ValueError("V2 editor handoff output cannot be a filesystem root")
    target = root / f"wechat-editor-handoff-v2-{artifact.artifact_fingerprint[:16]}"
    if target.exists():
        raise FileExistsError("V2 editor handoff destination already exists")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / f".{target.name}.tmp"
    if temporary.exists():
        raise FileExistsError("V2 editor handoff temporary destination already exists")
    try:
        temporary.mkdir()
        for relative, body in artifact.files.items():
            safe = v1._safe_path(relative)
            path = temporary / safe
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        (temporary / artifact.bundle_filename).write_bytes(artifact.zip_bytes)
        temporary.rename(target)
    except BaseException:
        if temporary.exists():
            import shutil

            shutil.rmtree(temporary)
        raise
    return target


def _assemble_artifact(
    *,
    run_id: UUID,
    run_request_fingerprint: str,
    article: ArticlePackage,
    review: StoredOfficialAccountManualReview | None,
    release: EditorHandoffRelease,
    identity: EditorHandoffV2Identity,
    recipe: EditorHandoffLayoutRecipe,
    placements: tuple[ContextBlockPlacement, ...],
    emphasis: tuple[SemanticEmphasisBlock, ...],
    body_visuals: tuple[BodyVisualLineage, ...],
    media: tuple[EditorHandoffMediaAsset, ...],
    asset_bodies: Mapping[str, bytes],
    body_html: str,
    preview_html: str,
    content_fingerprint: str,
    artifact_fingerprint: str,
    draft_resolved_fingerprint: str,
    mobile_validation: EditorHandoffMobileValidation,
    preflight: EditorHandoffV2Preflight,
    eligibility_checks: tuple[EditorHandoffCheck, ...],
) -> EditorHandoffV2Artifact:
    files: dict[str, bytes] = {
        "article-body.html": body_html.encode("utf-8"),
        "preview.html": preview_html.encode("utf-8"),
        "article.md": _article_markdown_v2(article, media, placements).encode("utf-8"),
        "article.json": v1._json_bytes(article.model_dump(mode="json")),
        "sources.json": v1._json_bytes(v1._sources_projection(article)),
        "rights.json": v1._json_bytes(v1._rights_projection(media)),
        "release.json": v1._json_bytes(release.model_dump(mode="json")),
        "review.json": v1._json_bytes(_review_projection(review)),
        "placements.json": v1._json_bytes(
            {
                "version": identity.placement_version,
                "items": [item.model_dump(mode="json") for item in placements],
            }
        ),
        "emphasis.json": v1._json_bytes(
            {
                "version": identity.emphasis_version,
                "items": [item.model_dump(mode="json") for item in emphasis],
            }
        ),
        "body-visuals.json": v1._json_bytes(
            {
                "version": identity.body_visual_lineage_version,
                "items": [item.model_dump(mode="json") for item in body_visuals],
            }
        ),
        "recipe.json": v1._json_bytes(recipe.model_dump(mode="json")),
        "preflight.json": v1._json_bytes(preflight.model_dump(mode="json")),
        "mobile-validation.json": v1._json_bytes(mobile_validation.model_dump(mode="json")),
        "theme.json": v1._json_bytes(canonical_theme_projection()),
        "README.md": _readme_v2(
            run_id=run_id,
            content_fingerprint=content_fingerprint,
            artifact_fingerprint=artifact_fingerprint,
            release=release,
            mobile=mobile_validation,
        ).encode("utf-8"),
        **asset_bodies,
    }
    manifest = {
        "bundle_version": identity.bundle_version,
        "fingerprint": artifact_fingerprint,
        "artifact_fingerprint": artifact_fingerprint,
        "content_fingerprint": content_fingerprint,
        "run_id": str(run_id),
        "simulation": True,
        "local_only": True,
        "copy_ready": True,
        "published": False,
        "identity": identity.model_dump(mode="json"),
        "release": release.model_dump(mode="json"),
        "recipe": recipe.model_dump(mode="json"),
        "placements": [item.model_dump(mode="json") for item in placements],
        "body_visuals": [item.model_dump(mode="json") for item in body_visuals],
        "mobile_validation": mobile_validation.model_dump(mode="json"),
        "lineage": {
            "run_request_fingerprint": run_request_fingerprint,
            "article_content_fingerprint": article.content_fingerprint,
            "release_input_fingerprint": release.input_fingerprint,
            "draft_resolved_fingerprint": draft_resolved_fingerprint,
            "body_sha256": sha256(body_html.encode("utf-8")).hexdigest(),
        },
        "media": [item.model_dump(mode="json") for item in media],
        "files": [v1._file_projection(path, body) for path, body in sorted(files.items())],
        "archive": {
            "timestamp": "1980-01-01T00:00:00Z",
            "mode": "0644",
            "compression": "deflate-9",
        },
    }
    files["manifest.json"] = v1._json_bytes(manifest)
    archive_root = f"wechat-editor-handoff-v2-{artifact_fingerprint[:16]}"
    zip_bytes = v1._deterministic_zip(files, archive_root=archive_root)
    v1._verify_zip(zip_bytes, files=files, archive_root=archive_root)
    return EditorHandoffV2Artifact(
        run_id=run_id,
        content_fingerprint=content_fingerprint,
        artifact_fingerprint=artifact_fingerprint,
        identity=identity,
        release=release,
        recipe=recipe,
        placements=placements,
        emphasis=emphasis,
        body_visuals=body_visuals,
        mobile_validation=mobile_validation,
        preflight=preflight,
        eligibility_checks=eligibility_checks,
        media=media,
        files=MappingProxyType(files),
        zip_bytes=zip_bytes,
        zip_sha256=sha256(zip_bytes).hexdigest(),
        bundle_filename=f"{archive_root}.zip",
    )


def _review_projection(review: StoredOfficialAccountManualReview | None) -> dict[str, object]:
    if review is None:
        return {"status": "not_present", "review": None, "immutable": True}
    return {
        "status": review.decision,
        "review_id": str(review.id),
        "reviewer_label": review.reviewer_label,
        "note": review.note,
        "request_fingerprint": review.request_fingerprint,
        "reviewed_at": review.reviewed_at.isoformat(),
        "immutable": True,
    }


def _article_markdown_v2(
    article: ArticlePackage,
    media: tuple[EditorHandoffMediaAsset, ...],
    placements: tuple[ContextBlockPlacement, ...],
) -> str:
    body_by_ordinal = {item.ordinal: item for item in media if item.role == "body"}
    context_by_target = {
        (item.section_index, item.target_block_index): (
            next(media_item for media_item in media if media_item.path == item.media_path),
            item,
        )
        for item in placements
    }
    lines = [f"# {article.title}", "", f"> {article.lead}", ""]
    for section_index, section in enumerate(article.sections):
        lines.extend((f"## {section.heading}", ""))
        for block_index, block in enumerate(section.blocks):
            if isinstance(block, ArticleImageBlock):
                ordinal = int(block.slot_key.removeprefix("body-"))
                lines.extend((f"![{block.alt_text}]({body_by_ordinal[ordinal].path})", ""))
            elif isinstance(block, ArticleBulletListBlock):
                lines.extend(f"- {item}" for item in block.items)
                lines.append("")
            elif isinstance(block, (ArticleParagraphBlock, ArticleQuoteBlock)):
                lines.extend((block.text, ""))
            context_entry = context_by_target.get((section_index, block_index))
            if context_entry is not None:
                context, placement = context_entry
                lines.extend(
                    (
                        f"![{context.alt_text}]({context.path})",
                        f"新闻上下文：{context.caption or context.alt_text}",
                        (
                            f"定位：第 {placement.section_index + 1} 节 · "
                            f"正文块 {placement.target_block_index + 1} 后"
                        ),
                        f"来源：{context.source_page_url or '未提供'}",
                        f"署名：{context.credit or '未提供'}",
                        "权利说明：发布权未验证；仅作上下文参考，不是事实证据。",
                        "",
                    )
                )
    lines.extend(("## 写在最后", "", article.conclusion, ""))
    return "\n".join(lines)


def _readme_v2(
    *,
    run_id: UUID,
    content_fingerprint: str,
    artifact_fingerprint: str,
    release: EditorHandoffRelease,
    mobile: EditorHandoffMobileValidation,
) -> str:
    return (
        "# WeChat editor local handoff V2\n\n"
        "This development-only bundle was derived from persisted article, audit and media state. "
        "It never uploads, publishes, or calls WeChat/WeCom.\n\n"
        f"- Run ID: `{run_id}`\n"
        f"- Release: `{release.kind}` via `{release.policy}`\n"
        f"- Content fingerprint: `{content_fingerprint}`\n"
        f"- Artifact fingerprint: `{artifact_fingerprint}`\n"
        f"- Mobile validation: `{mobile.status}`\n"
        "- Simulation/local only: `true`\n"
        "- Published: `false`\n\n"
        "News context images supplement company-IP body images and are placed after exact article "
        "blocks. `publish_permission_unverified` is a disclosure, never evidence or "
        "authorization. Each company-IP body image is a new reference-conditioned output bound "
        "to one exact article block; `body-visuals.json` exposes only replay-safe lineage.\n"
    )
