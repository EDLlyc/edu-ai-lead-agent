from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in safe UI explanations.
from typing import Annotated, Any, cast
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.application.ports.official_account_local import OfficialAccountVersionIdentity
from app.application.services.official_account_editor_handoff import (
    PREVIEW_SCRIPT_CSP_HASH,
    EditorHandoffArtifact,
    OfficialAccountEditorHandoffService,
)
from app.application.services.official_account_editor_handoff_v2 import (
    EditorHandoffV2Artifact,
    OfficialAccountEditorHandoffV2Service,
)
from app.core.errors import AppError, ConflictError, NotFoundError
from app.domain.official_account_editor_handoff_v2 import ContextBlockPlacement
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
    ArticlePackage,
)
from app.infrastructure.db.models import (
    ImageArtifactModel,
    MaterialPackageModel,
    OfficialAccountArticleRunModel,
    OfficialAccountLocalDraftModel,
    OfficialAccountLocalMediaModel,
)
from app.infrastructure.db.official_account_local import (
    PostgresOfficialAccountRepository,
    material_package_source_snapshot,
)
from app.infrastructure.official_account_media import (
    OfficialAccountLocalMediaResolver,
    OfficialAccountMediaIntegrityError,
    persisted_media_snapshot,
)
from app.schemas.official_account_local import (
    EligibleMaterialPackageResponse,
    OfficialAccountArticleResponse,
    OfficialAccountCapabilitiesResponse,
    OfficialAccountDraftResponse,
    OfficialAccountEditorHandoffCheckResponse,
    OfficialAccountEditorHandoffIdentityResponse,
    OfficialAccountEditorHandoffMediaResponse,
    OfficialAccountEditorHandoffMobileResponse,
    OfficialAccountEditorHandoffPlacementResponse,
    OfficialAccountEditorHandoffReleaseResponse,
    OfficialAccountEditorHandoffResponse,
    OfficialAccountEmbeddingIdentityResponse,
    OfficialAccountGeneratedVisualResponse,
    OfficialAccountManualReviewRequest,
    OfficialAccountManualReviewResponse,
    OfficialAccountMediaResponse,
    OfficialAccountMediaSelectionResponse,
    OfficialAccountRunCreateRequest,
    OfficialAccountRunDetailResponse,
    OfficialAccountRunListResponse,
    OfficialAccountRunSummaryResponse,
    OfficialAccountUsageResponse,
    OfficialAccountValidationResponse,
)

router = APIRouter(prefix="/official-account-local", tags=["official-account-local"])


@router.get("/capabilities", response_model=OfficialAccountCapabilitiesResponse)
async def capabilities(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OfficialAccountCapabilitiesResponse:
    settings = request.app.state.settings
    enabled = bool(settings.official_account_local_enabled)
    live_available = enabled and _live_provider_available(settings)
    eligible: list[EligibleMaterialPackageResponse] = []
    if enabled:
        rows = (
            await session.execute(
                select(MaterialPackageModel, ImageArtifactModel)
                .join(
                    ImageArtifactModel,
                    ImageArtifactModel.id == MaterialPackageModel.image_artifact_id,
                )
                .order_by(MaterialPackageModel.created_at.desc())
                .limit(100)
            )
        ).all()
        for package, image in rows:
            try:
                source = material_package_source_snapshot(package, image)
            except AppError:
                continue
            eligible.append(
                EligibleMaterialPackageResponse(
                    id=package.id,
                    title=source.topic_title,
                    status=package.status,
                    review_status=package.review_status,
                )
            )
    reason: str | None = None
    if not enabled:
        reason = "公众号本地草稿功能未启用"
    elif not live_available:
        reason = "真实模型未在服务器端完整配置"
    return OfficialAccountCapabilitiesResponse(
        enabled=enabled,
        fixture_available=enabled,
        live_available=live_available,
        live_unavailable_reason=reason,
        eligible_material_packages=eligible,
        visual_semantic_enabled=bool(
            getattr(settings, "official_account_local_visual_semantic_enabled", False)
        ),
        visual_semantic_provider_mode=getattr(
            settings,
            "visual_embedding_provider_mode",
            "disabled",
        ),
        generated_visuals_enabled=bool(
            getattr(settings, "official_account_local_generated_visuals_enabled", False)
        ),
        editor_handoff_enabled=_editor_handoff_available(settings),
        editor_handoff_v2_enabled=bool(
            _editor_handoff_available(settings)
            and getattr(settings, "official_account_editor_handoff_v2_enabled", False)
        ),
        editor_handoff_release_policy=getattr(
            settings, "official_account_editor_handoff_release_policy", "manual_only"
        ),
    )


@router.get("/article-runs", response_model=OfficialAccountRunListResponse)
async def list_article_runs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> OfficialAccountRunListResponse:
    _require_enabled(request)
    repository = PostgresOfficialAccountRepository(request.app.state.session_factory)
    runs = await repository.list_runs(limit=limit)
    return OfficialAccountRunListResponse(
        items=[_summary(run) for run in runs],
        count=len(runs),
    )


@router.post(
    "/article-runs",
    response_model=OfficialAccountRunSummaryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_article_run(
    payload: OfficialAccountRunCreateRequest,
    request: Request,
    response: Response,
) -> OfficialAccountRunSummaryResponse:
    _require_enabled(request)
    settings = request.app.state.settings
    repository = PostgresOfficialAccountRepository(request.app.state.session_factory)
    if payload.source.kind == "fixture":
        if getattr(settings, "official_account_reviewer_mode", "off") == "enforce":
            raise ConflictError("Reviewer enforce cannot be activated by a fixture run")
        run, _created = await repository.enqueue_fixture(identity=_fixture_identity(settings))
    else:
        if not _live_provider_available(settings):
            raise ConflictError("real article model is not configured on the server")
        run, _created = await repository.enqueue_material_package(
            material_package_id=payload.source.material_package_id,
            identity=_live_identity(settings),
        )
    response.headers["Location"] = _detail_url(run.id)
    return _summary(run)


@router.get(
    "/article-runs/{run_id}",
    response_model=OfficialAccountRunDetailResponse,
)
async def read_article_run(
    run_id: UUID,
    request: Request,
) -> OfficialAccountRunDetailResponse:
    _require_enabled(request)
    repository = PostgresOfficialAccountRepository(request.app.state.session_factory)
    run = await repository.get_run(run_id)
    article = await repository.get_article(run_id)
    media_rows = await repository.list_media(run_id)
    body_rows = tuple(item for item in media_rows if item[1].role == "body")
    context_rows = tuple(item for item in media_rows if item[1].role == "context")
    cover_row = next((item for item in media_rows if item[1].role == "cover"), None)
    draft = await repository.get_draft(run_id)
    manual_review = await repository.get_manual_review(run_id)
    generated_visuals = await repository.list_generated_visuals(run_id=run_id)
    summary = _summary(run)
    return OfficialAccountRunDetailResponse(
        **summary.model_dump(),
        article=(
            OfficialAccountArticleResponse.from_domain(article.article)
            if article is not None
            else None
        ),
        validation=(
            OfficialAccountValidationResponse(
                passed=article.validation_passed,
                issues=list(article.validation_issues),
            )
            if article is not None
            else None
        ),
        audit=article.audit if article is not None else None,
        usage=(
            OfficialAccountUsageResponse(
                prompt_tokens=article.prompt_tokens,
                completion_tokens=article.completion_tokens,
                reasoning_tokens=article.reasoning_tokens,
                latency_ms=article.latency_ms,
                safe_provider_request_id=article.provider_request_id,
            )
            if article is not None
            else None
        ),
        media=[_media(result) for _media_id, result in media_rows],
        body_image=_media(body_rows[0][1]) if body_rows else None,
        body_images=[_media(result) for _media_id, result in body_rows],
        context_images=[_media(result) for _media_id, result in context_rows],
        context_media_status=(
            article.article.news_context_media.status
            if article is not None and article.article.news_context_media is not None
            else "not_present"
        ),
        cover_image=_media(cover_row[1]) if cover_row is not None else None,
        media_selection=_media_selection(
            run,
            body_count=len(body_rows),
            article=article.article if article is not None else None,
        ),
        generated_visuals=[_generated_visual(item) for item in generated_visuals],
        draft=_draft(draft) if draft is not None else None,
        manual_review=_manual_review(manual_review),
    )


@router.post(
    "/article-runs/{run_id}/manual-review",
    response_model=OfficialAccountManualReviewResponse,
)
async def record_manual_review(
    run_id: UUID,
    payload: OfficialAccountManualReviewRequest,
    request: Request,
) -> OfficialAccountManualReviewResponse:
    _require_enabled(request)
    repository = PostgresOfficialAccountRepository(request.app.state.session_factory)
    review, created = await repository.record_manual_review(
        run_id=run_id,
        decision=payload.decision,
        reviewer_label=payload.reviewer_label,
        note=payload.note,
    )
    return _manual_review(review, idempotent_replay=not created)


@router.get(
    "/article-runs/{run_id}/editor-handoff",
    response_model=OfficialAccountEditorHandoffResponse,
)
async def read_editor_handoff(
    run_id: UUID,
    request: Request,
    response: Response,
) -> OfficialAccountEditorHandoffResponse:
    _require_editor_handoff_enabled(request)
    response.headers.update(_private_headers())
    inspection = await _editor_handoff_service(request).inspect(run_id)
    artifact = inspection.artifact
    base = _editor_handoff_base(run_id)
    v2_artifact = artifact if isinstance(artifact, EditorHandoffV2Artifact) else None
    placements_by_path = (
        {item.media_path: item for item in v2_artifact.placements}
        if v2_artifact is not None
        else {}
    )
    return OfficialAccountEditorHandoffResponse(
        state=inspection.state,
        copy_ready=artifact is not None,
        fingerprint=artifact.fingerprint if artifact is not None else None,
        content_fingerprint=(v2_artifact.content_fingerprint if v2_artifact is not None else None),
        artifact_fingerprint=(
            v2_artifact.artifact_fingerprint if v2_artifact is not None else None
        ),
        identity=(
            OfficialAccountEditorHandoffIdentityResponse.model_validate(
                artifact.identity.model_dump(mode="json")
            )
            if artifact is not None
            else None
        ),
        release=(
            OfficialAccountEditorHandoffReleaseResponse.model_validate(
                v2_artifact.release.model_dump(mode="json")
            )
            if v2_artifact is not None
            else None
        ),
        recipe=v2_artifact.recipe.kind if v2_artifact is not None else None,
        placements=(
            [_placement_response(item) for item in v2_artifact.placements]
            if v2_artifact is not None
            else []
        ),
        checks=[
            OfficialAccountEditorHandoffCheckResponse.model_validate(item.model_dump(mode="json"))
            for item in inspection.checks
        ],
        blocking_codes=list(inspection.blocking_codes),
        warning_codes=list(inspection.warning_codes),
        media=(
            [
                OfficialAccountEditorHandoffMediaResponse(
                    name=item.path.removeprefix("assets/"),
                    role=item.role,
                    ordinal=item.ordinal,
                    download_url=f"{base}/assets/{item.path.removeprefix('assets/')}",
                    media_type=item.media_type,
                    byte_size=item.byte_size,
                    sha256=item.sha256,
                    width=item.width,
                    height=item.height,
                    alt_text=item.alt_text,
                    assigned_section_index=item.assigned_section_index,
                    source_page_url=item.source_page_url,
                    credit=item.credit,
                    rights_status=item.rights_status,
                    context_only_not_evidence=item.context_only_not_evidence,
                    placement=(
                        _placement_response(placements_by_path[item.path])
                        if item.path in placements_by_path
                        else None
                    ),
                )
                for item in artifact.media
            ]
            if artifact is not None
            else []
        ),
        mobile_validation=(
            OfficialAccountEditorHandoffMobileResponse.model_validate(
                v2_artifact.mobile_validation.model_dump(mode="json")
            )
            if v2_artifact is not None
            else OfficialAccountEditorHandoffMobileResponse(status="not_run")
        ),
        body_url=f"{base}/body" if artifact is not None else None,
        preview_url=f"{base}/preview" if artifact is not None else None,
        bundle_url=f"{base}/bundle" if artifact is not None else None,
        bundle_filename=artifact.bundle_filename if artifact is not None else None,
        bundle_sha256=artifact.zip_sha256 if artifact is not None else None,
    )


@router.get("/article-runs/{run_id}/editor-handoff/body", response_class=HTMLResponse)
async def read_editor_handoff_body(run_id: UUID, request: Request) -> Response:
    artifact = await _require_editor_handoff_artifact(run_id, request)
    return Response(
        content=artifact.body_html,
        media_type="text/html",
        headers={
            **_private_headers(),
            "Content-Security-Policy": (
                "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'self'; object-src 'none'"
            ),
            "X-Content-SHA256": _sha256_hex(artifact.body_html),
        },
    )


@router.get("/article-runs/{run_id}/editor-handoff/preview", response_class=HTMLResponse)
async def preview_editor_handoff(run_id: UUID, request: Request) -> Response:
    artifact = await _require_editor_handoff_artifact(run_id, request)
    return Response(
        content=artifact.preview_html,
        media_type="text/html",
        headers={
            **_private_headers(),
            "Content-Security-Policy": (
                "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
                f"script-src 'sha256-{PREVIEW_SCRIPT_CSP_HASH}'; connect-src 'none'; "
                "base-uri 'none'; form-action 'none'; "
                f"frame-ancestors {_editor_handoff_frame_ancestors(request)}; object-src 'none'"
            ),
            "X-Content-SHA256": _sha256_hex(artifact.preview_html),
        },
    )


@router.get(
    "/article-runs/{run_id}/editor-handoff/assets/{asset_name}",
    response_class=Response,
)
async def read_editor_handoff_asset(
    run_id: UUID,
    asset_name: str,
    request: Request,
) -> Response:
    artifact = await _require_editor_handoff_artifact(run_id, request)
    asset = next(
        (item for item in artifact.media if item.path == f"assets/{asset_name}"),
        None,
    )
    if asset is None:
        raise NotFoundError("official-account editor handoff asset")
    body = artifact.files.get(asset.path)
    if body is None or _sha256_hex(body) != asset.sha256:
        raise AppError(
            "handoff_asset_integrity_failed",
            "official-account editor handoff asset integrity failed",
            409,
        )
    return Response(
        content=body,
        media_type=asset.media_type,
        headers={
            **_private_headers(),
            "Content-Disposition": f'attachment; filename="{asset_name}"',
            "X-Content-SHA256": asset.sha256,
        },
    )


@router.get("/article-runs/{run_id}/editor-handoff/bundle", response_class=Response)
async def download_editor_handoff_bundle(run_id: UUID, request: Request) -> Response:
    artifact = await _require_editor_handoff_artifact(run_id, request)
    return Response(
        content=artifact.zip_bytes,
        media_type="application/zip",
        headers={
            **_private_headers(),
            "Content-Disposition": f'attachment; filename="{artifact.bundle_filename}"',
            "X-Content-SHA256": artifact.zip_sha256,
        },
    )


@router.post(
    "/article-runs/{run_id}/retry",
    response_model=OfficialAccountRunSummaryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_article_run(
    run_id: UUID,
    request: Request,
    response: Response,
) -> OfficialAccountRunSummaryResponse:
    _require_enabled(request)
    settings = request.app.state.settings
    repository = PostgresOfficialAccountRepository(request.app.state.session_factory)
    run = await repository.retry(
        run_id=run_id,
        max_attempts=settings.official_account_local_max_attempts,
    )
    response.headers["Location"] = _detail_url(run.id)
    return _summary(run)


@router.get("/media/{local_media_id}", response_class=Response)
async def read_local_media(
    local_media_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    _require_enabled(request)
    row = await session.scalar(
        select(OfficialAccountLocalMediaModel).where(
            OfficialAccountLocalMediaModel.local_media_id == local_media_id,
            OfficialAccountLocalMediaModel.status == "ready",
        )
    )
    if row is None:
        raise NotFoundError("official-account local media")
    resolver = OfficialAccountLocalMediaResolver(
        image_asset_manifest=getattr(request.app.state.settings, "image_asset_manifest", None),
        image_store=getattr(request.app.state, "image_store", None),
        snapshot_store=getattr(request.app.state, "snapshot_store", None),
    )
    try:
        persisted_media = persisted_media_snapshot(row)
        body = await resolver.read_verified_bytes(session=session, media=persisted_media)
    except OfficialAccountMediaIntegrityError as error:
        raise ConflictError("official-account local media integrity check failed") from error
    return Response(
        content=body,
        media_type=persisted_media.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/drafts/{local_draft_id}/preview", response_class=Response)
async def preview_local_draft(
    local_draft_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    _require_enabled(request)
    draft = await session.scalar(
        select(OfficialAccountLocalDraftModel).where(
            OfficialAccountLocalDraftModel.local_draft_id == local_draft_id,
            OfficialAccountLocalDraftModel.state == "ready",
            OfficialAccountLocalDraftModel.simulation.is_(True),
        )
    )
    if draft is None:
        raise NotFoundError("official-account local draft")
    document = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>公众号本地草稿预览</title></head>"
        f"<body>{draft.resolved_html}</body></html>"
    )
    return Response(
        content=document.encode("utf-8"),
        media_type="text/html",
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'self'; "
                "object-src 'none'"
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )


def _require_enabled(request: Request) -> None:
    if not request.app.state.settings.official_account_local_enabled:
        raise ConflictError("official-account local drafting is disabled")


def _editor_handoff_available(settings: Any) -> bool:
    return bool(
        settings.official_account_local_enabled
        and getattr(settings, "official_account_editor_handoff_enabled", False)
        and getattr(settings, "app_env", None) == "development"
    )


def _require_editor_handoff_enabled(request: Request) -> None:
    _require_enabled(request)
    if not _editor_handoff_available(request.app.state.settings):
        raise AppError(
            "editor_handoff_disabled",
            "official-account editor handoff is development-only and disabled",
            409,
        )


def _editor_handoff_service(
    request: Request,
) -> OfficialAccountEditorHandoffService | OfficialAccountEditorHandoffV2Service:
    settings = request.app.state.settings
    resolver = OfficialAccountLocalMediaResolver(
        image_asset_manifest=getattr(settings, "image_asset_manifest", None),
        image_store=getattr(request.app.state, "image_store", None),
        snapshot_store=getattr(request.app.state, "snapshot_store", None),
    )
    if _editor_handoff_uses_v2(settings):
        return OfficialAccountEditorHandoffV2Service(
            session_factory=request.app.state.session_factory,
            resolver=resolver,
            release_policy=getattr(
                settings, "official_account_editor_handoff_release_policy", "manual_only"
            ),
        )
    return OfficialAccountEditorHandoffService(
        session_factory=request.app.state.session_factory, resolver=resolver
    )


async def _require_editor_handoff_artifact(
    run_id: UUID,
    request: Request,
) -> EditorHandoffArtifact | EditorHandoffV2Artifact:
    _require_editor_handoff_enabled(request)
    return await _editor_handoff_service(request).require_artifact(run_id)


def _editor_handoff_base(run_id: UUID) -> str:
    return f"/api/v1/official-account-local/article-runs/{run_id}/editor-handoff"


def _editor_handoff_uses_v2(settings: Any) -> bool:
    return bool(
        getattr(settings, "official_account_editor_handoff_v2_enabled", False)
        and getattr(settings, "official_account_editor_handoff_release_policy", "manual_only")
        == "quality_auto"
    )


def _placement_response(
    item: ContextBlockPlacement,
) -> OfficialAccountEditorHandoffPlacementResponse:
    return OfficialAccountEditorHandoffPlacementResponse(
        media_name=item.media_path.removeprefix("assets/"),
        section_index=item.section_index,
        target_block_index=item.target_block_index,
        insertion=item.insertion,
        reason_code=item.reason_code,
        algorithm_version=item.algorithm_version,
        matched_terms=item.matched_terms,
    )


def _private_headers() -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def _editor_handoff_frame_ancestors(request: Request) -> str:
    sources = ["'self'"]
    for origin in getattr(request.app.state.settings, "browser_origins", ()):
        parsed = urlsplit(origin)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.netloc
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        ):
            sources.append(f"{parsed.scheme}://{parsed.netloc}")
    return " ".join(dict.fromkeys(sources))


def _sha256_hex(body: bytes) -> str:
    from hashlib import sha256

    return sha256(body).hexdigest()


def _live_provider_available(settings: Any) -> bool:
    return bool(
        settings.ai_provider_mode == "zhipu"
        and settings.ai_platform_base_url is not None
        and settings.ai_platform_api_key is not None
        and settings.ai_platform_api_key.get_secret_value().strip()
    )


def _fixture_identity(settings: Any) -> OfficialAccountVersionIdentity:
    return _identity(settings, provider="fake", model="official-account-fixture-v1")


def _live_identity(settings: Any) -> OfficialAccountVersionIdentity:
    return _identity(settings, provider="zhipu", model=settings.ai_chat_model)


def _identity(
    settings: Any,
    *,
    provider: Any,
    model: str,
) -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider=provider,
        model=model,
        generator_prompt_version=settings.official_account_local_generator_prompt_version,
        article_schema_version=settings.official_account_local_article_schema_version,
        media_plan_version=settings.official_account_local_media_plan_version,
        auditor_prompt_version=settings.official_account_local_auditor_prompt_version,
        audit_schema_version=settings.official_account_local_audit_schema_version,
        rule_version=settings.official_account_local_rule_version,
        renderer_version=settings.official_account_local_renderer_version,
        style_version=settings.official_account_local_style_version,
        template_version=settings.official_account_local_template_version,
        local_adapter_version=settings.official_account_local_adapter_version,
        visual_query_version=settings.official_account_local_visual_query_version,
        visual_selector_version=settings.official_account_local_visual_selector_version,
        context_media_plan_version=settings.official_account_local_context_media_plan_version,
        generated_visual_plan_version=(
            settings.official_account_local_generated_visual_plan_version
            if provider == "zhipu" and settings.official_account_local_generated_visuals_enabled
            else None
        ),
        generated_visual_prompt_version=(
            settings.official_account_local_generated_visual_prompt_version
            if provider == "zhipu" and settings.official_account_local_generated_visuals_enabled
            else None
        ),
        default_author=settings.official_account_local_default_author,
        min_characters=settings.official_account_local_min_characters,
        target_min_characters=settings.official_account_local_target_min_characters,
        target_max_characters=settings.official_account_local_target_max_characters,
        max_characters=settings.official_account_local_max_characters,
        reviewer_mode=getattr(settings, "official_account_reviewer_mode", "off"),
        reviewer_version=getattr(
            settings, "official_account_reviewer_version", "official-account-reviewer-v1"
        ),
        reviewer_prompt_version=getattr(
            settings,
            "official_account_reviewer_prompt_version",
            "official-account-reviewer-prompt-v1",
        ),
        reviewer_request_schema_version=getattr(
            settings,
            "official_account_reviewer_request_schema_version",
            "official-account-review-request-v1",
        ),
        reviewer_verdict_schema_version=getattr(
            settings,
            "official_account_reviewer_verdict_schema_version",
            "official-account-review-verdict-v1",
        ),
        reviewer_rubric_version=getattr(
            settings,
            "official_account_reviewer_rubric_version",
            "official-account-editorial-rubric-v1",
        ),
        reviewer_review_policy_version=getattr(
            settings,
            "official_account_reviewer_review_policy_version",
            "official-account-review-policy-v1",
        ),
        reviewer_repair_policy_version=getattr(
            settings,
            "official_account_reviewer_repair_policy_version",
            "official-account-repair-policy-v1",
        ),
        reviewer_budget_policy_version=getattr(
            settings,
            "official_account_reviewer_budget_policy_version",
            "official-account-review-budget-v1",
        ),
        reviewer_provider=provider,
        reviewer_model=model,
        reviewer_writer_timeout_ms=getattr(
            settings,
            "official_account_reviewer_writer_timeout_ms",
            180_000,
        ),
        reviewer_timeout_ms=getattr(
            settings,
            "official_account_reviewer_timeout_ms",
            180_000,
        ),
        reviewer_writer_max_output_tokens=getattr(
            settings,
            "official_account_local_max_output_tokens",
            16_384,
        ),
        reviewer_max_output_tokens=getattr(
            settings, "official_account_reviewer_max_output_tokens", 2_048
        ),
        reviewer_repair_timeout_ms=getattr(
            settings, "official_account_reviewer_repair_timeout_ms", 180_000
        ),
        reviewer_repair_max_output_tokens=getattr(
            settings, "official_account_reviewer_repair_max_output_tokens", 16_384
        ),
        reviewer_enforce_policy_version=getattr(
            settings,
            "official_account_reviewer_enforce_policy_version",
            "official-account-review-enforce-v1",
        ),
        reviewer_enforce_acknowledgement=(
            getattr(settings, "official_account_reviewer_enforce_acknowledgement", "")
            == "I_ACKNOWLEDGE_REVIEWER_ENFORCE_V1"
        ),
        reviewer_calibration_report_sha256=getattr(
            settings, "official_account_reviewer_calibration_report_sha256", None
        )
        or None,
    )


def _summary(run: OfficialAccountArticleRunModel) -> OfficialAccountRunSummaryResponse:
    return OfficialAccountRunSummaryResponse(
        id=run.id,
        source_kind="fixture" if run.fixture_id is not None else "material_package",
        material_package_id=run.material_package_id,
        fixture_id=run.fixture_id,
        generation_mode=cast(Any, run.generation_mode),
        provider=cast(Any, run.provider),
        model=run.model,
        request_fingerprint=run.request_fingerprint,
        status=cast(Any, run.status),
        current_stage=cast(Any, run.current_stage),
        attempt_count=run.attempt_count,
        error_code=run.error_code,
        error_retryable=run.error_retryable,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        detail_url=_detail_url(run.id),
        retry_url=f"{_detail_url(run.id)}/retry",
    )


def _media(result: Any) -> OfficialAccountMediaResponse:
    return OfficialAccountMediaResponse(
        local_media_id=result.local_media_id,
        role=result.role,
        ordinal=result.ordinal,
        media_url=result.media_url,
        media_type=result.media_type,
        byte_size=result.byte_size,
        sha256=result.sha256,
        semantic_label=result.semantic_label,
        assigned_section_index=result.assigned_section_index,
        score_band=result.score_band,
        selection_reason_code=result.selection_reason_code,
        selection_method=result.selection_method,
        similarity_band=result.similarity_band,
        alt_text=result.alt_text,
        provenance_kind=result.provenance_kind,
        source_page_url=result.source_page_url,
        caption=result.caption,
        credit=result.credit,
        rights_status=result.rights_status,
        context_only_not_evidence=result.context_only_not_evidence,
    )


def _draft(draft: OfficialAccountLocalDraftModel) -> OfficialAccountDraftResponse:
    return OfficialAccountDraftResponse(
        local_draft_id=draft.local_draft_id,
        state=cast(Any, draft.state),
        simulation=True,
        preview_url=(f"/api/v1/official-account-local/drafts/{draft.local_draft_id}/preview"),
        resolved_fingerprint=draft.resolved_fingerprint,
        created_at=draft.created_at,
    )


def _generated_visual(item: Any) -> OfficialAccountGeneratedVisualResponse:
    return OfficialAccountGeneratedVisualResponse(
        ordinal=item.plan.ordinal,
        section_index=item.plan.section_index,
        block_index=item.plan.block_index,
        block_kind=item.plan.block_kind,
        reference_asset_ref=item.plan.reference_asset_ref,
        selection_method=item.plan.selection_method,
        similarity_band=item.plan.similarity_band,
        status=item.status,
        request_fingerprint=item.plan.request_fingerprint,
        plan_version=item.plan.plan_version,
        prompt_version=item.plan.prompt_version,
        output_profile_version=item.plan.output_profile_version,
        provider=item.plan.provider,
        model=item.plan.model,
        media_type=item.media_type,
        byte_size=item.byte_size,
        sha256=item.sha256,
        width=item.width,
        height=item.height,
        error_code=item.error_code,
    )


def _manual_review(
    review: Any | None,
    *,
    idempotent_replay: bool = False,
) -> OfficialAccountManualReviewResponse:
    if review is None:
        return OfficialAccountManualReviewResponse(status="pending")
    return OfficialAccountManualReviewResponse(
        status=review.decision,
        review_id=review.id,
        reviewer_label=review.reviewer_label,
        note=review.note,
        reviewed_at=review.reviewed_at,
        request_fingerprint=review.request_fingerprint,
        idempotent_replay=idempotent_replay,
        editorially_approved=review.decision == "approved",
    )


def _media_selection(
    run: OfficialAccountArticleRunModel,
    *,
    body_count: int,
    article: ArticlePackage | None,
) -> OfficialAccountMediaSelectionResponse:
    current_plan = run.version_bundle.get("media_plan_version")
    if current_plan in {
        OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
        OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    }:
        snapshot = article.media_selection if article is not None else None
        planned_body_count = len(snapshot.assignments) if snapshot is not None else body_count
        semantic_ready = snapshot is not None and snapshot.status == "semantic_ready"
        explanation = [
            (
                "多模态模型只对已经过清单审批和完整性校验的品牌图库排序，不会引入新图片。"
                if semantic_ready
                else "多模态排序未生效，本次使用确定性的章节标签回退结果。"
            ),
            "正文图片保持一对一且均衡分布；素材包主图只作为独立封面。",
            "相似度不是审稿结论，最终仍需由人工明确批准或退回。",
        ]
        return OfficialAccountMediaSelectionResponse(
            policy_version=str(current_plan),
            # The selection snapshot is persisted before generated-image provider I/O.  It is
            # therefore the safe target count while no body-media rows have been staged yet.
            body_image_count=planned_body_count,
            target_body_image_count="3–5（候选不足时允许 1–2）",
            safely_degraded=planned_body_count < 3 or not semantic_ready,
            explanation=explanation,
            selection_mode=("multimodal_embedding" if semantic_ready else "deterministic_fallback"),
            semantic_status=snapshot.status if snapshot is not None else "semantic_unavailable",
            semantic_unavailable_reason=(
                snapshot.closed_reason if snapshot is not None else "selection_pending"
            ),
            visual_query_version=(snapshot.visual_query_version if snapshot is not None else None),
            visual_selector_version=(
                snapshot.visual_selector_version if snapshot is not None else None
            ),
            embedding_identity=(
                OfficialAccountEmbeddingIdentityResponse.model_validate(
                    snapshot.embedding_identity.model_dump()
                )
                if snapshot is not None and snapshot.embedding_identity is not None
                else None
            ),
        )
    if current_plan in {
        OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
        OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
    }:
        return OfficialAccountMediaSelectionResponse(
            policy_version=str(current_plan),
            body_image_count=body_count,
            target_body_image_count="3–5（历史多图）",
            safely_degraded=False,
            explanation=["该历史运行按原确定性多图顺序和 PNG 素材恢复。"],
            selection_mode="historical",
        )
    return OfficialAccountMediaSelectionResponse(
        policy_version="historical-single-body",
        body_image_count=body_count,
        target_body_image_count="1（历史兼容）",
        safely_degraded=False,
        explanation=["该历史运行按原单图版本身份恢复，不应用新版多图计划。"],
    )


def _detail_url(run_id: UUID) -> str:
    return f"/api/v1/official-account-local/article-runs/{run_id}"
