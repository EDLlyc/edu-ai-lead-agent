from __future__ import annotations

from app.domain.brand_knowledge import (
    BrandAudience,
    BrandDocumentKind,
    BrandRetrievalHit,
    BrandVersionStatus,
)
from app.domain.digital_ip import (
    DigitalIpDocumentBinding,
    DigitalIpProfile,
)
from app.infrastructure.db.brand_knowledge import BrandDocumentProjection
from app.infrastructure.db.models import BrandDocumentVersionModel, BrandIngestionJobModel
from app.schemas.brand_knowledge import (
    BrandContextChunkResponse,
    BrandDocumentResponse,
    BrandIngestionJobResponse,
    BrandVersionResponse,
    DigitalIpCharacterResponse,
    DigitalIpDocumentBindingResponse,
    DigitalIpProfileResponse,
    DigitalIpVisualAssetResponse,
)


def brand_document_response(projection: BrandDocumentProjection) -> BrandDocumentResponse:
    document = projection.document
    return BrandDocumentResponse(
        id=document.id,
        brand_slug="sai-xiansheng",
        title=document.title,
        document_kind=BrandDocumentKind(document.document_kind),
        audience=BrandAudience(document.audience),
        language="zh-CN",
        status="active" if document.status == "active" else "inactive",
        active_version_id=document.active_version_id,
        versions=[
            brand_version_response(version, projection.jobs_by_version.get(version.id))
            for version in projection.versions
        ],
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def brand_version_response(
    version: BrandDocumentVersionModel, job: BrandIngestionJobModel | None
) -> BrandVersionResponse:
    return BrandVersionResponse(
        id=version.id,
        document_id=version.document_id,
        version=version.version,
        safe_filename=version.safe_filename,
        media_type=version.media_type,
        byte_size=version.byte_size,
        status=version.status,
        active=version.active,
        valid_from=version.valid_from,
        valid_until=version.valid_until,
        tone_tags=_strings(version.tone_tags),
        safety_tags=_strings(version.safety_tags),
        visual_tags=_strings(version.visual_tags),
        extraction_method=version.extraction_method,
        ocr_provider=version.ocr_provider,
        ocr_model=version.ocr_model,
        ocr_request_fingerprint=version.ocr_request_fingerprint,
        ocr_provider_request_id=version.ocr_provider_request_id,
        ocr_page_count=version.ocr_page_count,
        ocr_prompt_tokens=version.ocr_prompt_tokens,
        ocr_completion_tokens=version.ocr_completion_tokens,
        ocr_latency_ms=version.ocr_latency_ms,
        parser_version=version.parser_version,
        chunk_version=version.chunk_version,
        embedding_input_version=version.embedding_input_version,
        embedding_provider=version.embedding_provider,
        embedding_model=version.embedding_model,
        embedding_dimensions=version.embedding_dimensions,
        page_count=version.page_count,
        character_count=version.character_count,
        chunk_count=version.chunk_count,
        error_code=version.error_code,
        created_at=version.created_at,
        completed_at=version.completed_at,
        activated_at=version.activated_at,
        deactivated_at=version.deactivated_at,
        ingestion_job_id=job.id if job is not None else None,
        ingestion_job_status=job.status if job is not None else None,
    )


def brand_ingestion_job_response(job: BrandIngestionJobModel) -> BrandIngestionJobResponse:
    return BrandIngestionJobResponse(
        id=job.id,
        version_id=job.version_id,
        status=job.status,
        attempt_count=job.attempt_count,
        error_code=job.error_code,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def brand_context_chunk_response(hit: BrandRetrievalHit) -> BrandContextChunkResponse:
    return BrandContextChunkResponse(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        version_id=hit.version_id,
        document_title=hit.document_title,
        document_kind=hit.document_kind,
        audience=hit.audience,
        text=hit.text,
        tone_tags=list(hit.tone_tags),
        safety_tags=list(hit.safety_tags),
        visual_tags=list(hit.visual_tags),
        full_text_score=hit.full_text_score,
        vector_score=hit.vector_score,
        fused_score=hit.fused_score,
    )


def digital_ip_document_bindings(
    projections: tuple[BrandDocumentProjection, ...],
) -> tuple[DigitalIpDocumentBinding, ...]:
    """Select only the authoritative active-ready version from each active document."""

    bindings: list[DigitalIpDocumentBinding] = []
    for projection in projections:
        document = projection.document
        if document.status != "active" or document.active_version_id is None:
            continue
        active_version = next(
            (
                version
                for version in projection.versions
                if version.id == document.active_version_id
                and version.active
                and version.status == BrandVersionStatus.READY.value
            ),
            None,
        )
        if active_version is None:
            continue
        bindings.append(
            DigitalIpDocumentBinding(
                document_id=document.id,
                version_id=active_version.id,
                version=active_version.version,
                title=document.title,
                document_kind=BrandDocumentKind(document.document_kind),
                audience=BrandAudience(document.audience),
                valid_from=active_version.valid_from,
                valid_until=active_version.valid_until,
                tone_tags=tuple(_strings(active_version.tone_tags)),
                safety_tags=tuple(_strings(active_version.safety_tags)),
                visual_tags=tuple(_strings(active_version.visual_tags)),
            )
        )
    return tuple(bindings)


def digital_ip_profile_response(profile: DigitalIpProfile) -> DigitalIpProfileResponse:
    return DigitalIpProfileResponse(
        profile_id="sai-xiansheng-xiao-sai",
        profile_version="digital-ip-profile-v1",
        display_name=profile.display_name,
        brand_slug="sai-xiansheng",
        identity_summary=profile.identity_summary,
        characters=[
            DigitalIpCharacterResponse(
                character_id=character.character_id,
                display_name=character.display_name,
                role=character.role,
            )
            for character in profile.characters
        ],
        audiences=list(profile.audiences),
        channels=list(profile.channels),
        content_scenarios=list(profile.content_scenarios),
        document_bindings=[
            DigitalIpDocumentBindingResponse(
                document_id=binding.document_id,
                version_id=binding.version_id,
                version=binding.version,
                title=binding.title,
                document_kind=binding.document_kind,
                audience=binding.audience,
                valid_from=binding.valid_from,
                valid_until=binding.valid_until,
                tone_tags=list(binding.tone_tags),
                safety_tags=list(binding.safety_tags),
                visual_tags=list(binding.visual_tags),
            )
            for binding in profile.document_bindings
        ],
        active_document_count=profile.active_document_count,
        active_version_ids=list(profile.active_version_ids),
        document_kinds=list(profile.document_kinds),
        tone_tags=list(profile.tone_tags),
        safety_tags=list(profile.safety_tags),
        visual_tags=list(profile.visual_tags),
        visual_catalog_status=profile.visual_catalog_status,
        visual_catalog_version=profile.visual_catalog_version,
        visual_assets=[
            DigitalIpVisualAssetResponse(
                asset_ref=asset.asset_ref,
                checksum_ref=asset.checksum_ref,
                display_name=asset.display_name,
                asset_kind=asset.asset_kind,
                characters=list(asset.characters),
                roles=list(asset.roles),
                topics=list(asset.topics),
                poses=list(asset.poses),
                scene_tags=list(asset.scene_tags),
                width=asset.width,
                height=asset.height,
                approved=True,
                priority=asset.priority,
            )
            for asset in profile.visual_assets
        ],
        profile_fingerprint=profile.profile_fingerprint,
        evidence_eligible=False,
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
