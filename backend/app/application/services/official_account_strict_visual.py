"""Prospective five-generation/six-audit workflow with durable dispatch authority."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from hashlib import sha256

from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerator,
    ImageReference,
)
from app.application.ports.image_validation import ImageQualityAuditor, ImageQualityAuditRequest
from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    OfficialAccountCatalogMediaProvider,
    OfficialAccountGeneratedVisualStore,
    OfficialAccountRunRepository,
    OfficialAccountSourceMedia,
    StoredOfficialAccountArticle,
    StoredOfficialAccountGeneratedVisual,
    StoredOfficialAccountRender,
)
from app.application.ports.official_account_strict_visual import (
    StrictVisualAuditSubject,
    strict_visual_derivative_descriptor,
)
from app.application.services.official_account_visual_generation import (
    build_generated_visual_prompt,
    generated_visual_alt_text,
    plan_generated_body_visual,
    preflight_strict_generated_visuals,
    prepare_generated_visual_result,
    select_generated_visual_block_anchor,
    validate_strict_visual_reference,
)
from app.core.errors import AppError, OfficialAccountGeneratedVisualResultUnknownError
from app.domain.image_provider_input import (
    IMAGE_REFERENCE_INPUT_V2,
    normalize_image_provider_reference,
)
from app.domain.image_similarity import perceptual_dhash
from app.domain.official_account_local import fingerprint
from app.domain.official_account_upload_media import (
    normalize_official_account_upload_body,
    normalize_official_account_upload_cover,
)
from app.domain.official_account_visual_pipeline import (
    STRICT_VISUAL_POLICY,
    strict_visual_audit_criteria,
    strict_visual_audit_passes,
    strict_visual_batch_checks,
)


async def strict_catalog_candidates(
    catalog: OfficialAccountCatalogMediaProvider,
    candidates: tuple[OfficialAccountSourceMedia, ...],
) -> tuple[OfficialAccountSourceMedia, ...]:
    """Read/decode before text generation; do not change the legacy catalog contract."""
    if not 1 <= len(candidates) <= 41:
        raise ValueError("strict visual catalog is outside the bounded policy")
    eligible: list[OfficialAccountSourceMedia] = []
    for candidate in candidates:
        revalidated = await catalog.revalidate_candidate(candidate)
        content = await _read_reference(catalog, revalidated)
        try:
            # This phase has no article yet; only byte/reference eligibility is checked.
            # Real section anchors are assigned and validated before generation below.
            validate_strict_visual_reference(
                replace(revalidated, assigned_section_index=0), content
            )
        except ValueError:
            continue
        eligible.append(revalidated)
    if not eligible:
        raise ValueError("strict visual catalog has no eligible complete references")
    return tuple(eligible)


async def _read_reference(
    catalog: OfficialAccountCatalogMediaProvider, reference: OfficialAccountSourceMedia
) -> bytes:
    return await catalog.read_publication_bytes(
        catalog_asset_ref=reference.catalog_asset_ref or "",
        catalog_version=reference.catalog_version or "",
        source_master_sha256=reference.source_master_sha256 or "",
        publication_sha256=reference.sha256,
    )


def _blocked(code: str) -> AppError:
    return AppError(code, "strict final visual quality gate did not pass", 422, False)


async def execute_strict_visuals(
    *,
    repository: OfficialAccountRunRepository,
    claimed: ClaimedOfficialAccountRun,
    article: StoredOfficialAccountArticle,
    rendered: StoredOfficialAccountRender,
    references: tuple[OfficialAccountSourceMedia, ...],
    catalog_candidates: tuple[OfficialAccountSourceMedia, ...],
    catalog: OfficialAccountCatalogMediaProvider,
    store: OfficialAccountGeneratedVisualStore,
    generator: ImageGenerator,
    auditor: ImageQualityAuditor,
    lease_lost: asyncio.Event | None = None,
) -> tuple[tuple[OfficialAccountSourceMedia, ...], OfficialAccountSourceMedia] | None:
    """Only newly_claimed can cross a paid boundary; successful artifacts never roll back."""
    reference_bytes = tuple([await _read_reference(catalog, ref) for ref in references])
    preflight_strict_generated_visuals(
        article=article, references=references, reference_bytes=reference_bytes
    )
    catalog_bytes = tuple([await _read_reference(catalog, ref) for ref in catalog_candidates])
    catalog_hashes = tuple(sorted({perceptual_dhash(content) for content in catalog_bytes}))
    generated: list[tuple[StoredOfficialAccountGeneratedVisual, bytes]] = []
    for ordinal, (reference, content) in enumerate(zip(references, reference_bytes, strict=True)):
        if lease_lost is not None and lease_lost.is_set():
            return None
        plan = plan_generated_body_visual(
            run_id=claimed.run_id,
            article=article,
            render=rendered,
            ordinal=ordinal,
            reference=reference,
            reference_bytes=content,
            provider=STRICT_VISUAL_POLICY.generation_provider,
            model=STRICT_VISUAL_POLICY.generation_model,
            plan_version=claimed.identity.generated_visual_plan_version or "",
            prompt_version=claimed.identity.generated_visual_prompt_version or "",
        )
        claim = await repository.claim_strict_generated_visual(claimed=claimed, plan=plan)
        if claim.outcome in {"lease_lost", "in_flight"}:
            return None
        if claim.outcome == "result_unknown":
            raise OfficialAccountGeneratedVisualResultUnknownError()
        stored = claim.visual
        if stored is None:
            raise ValueError("strict generated visual claim is incomplete")
        if claim.outcome == "newly_claimed":
            if lease_lost is not None and lease_lost.is_set():
                return None
            prompt = build_generated_visual_prompt(
                article=article,
                section_index=plan.section_index,
                reference=reference,
                prompt_version=plan.prompt_version,
                block_index=plan.block_index,
            )
            try:
                result = await generator.generate(
                    ImageGenerationRequest(
                        run_id=claimed.run_id,
                        draft_version_id=article.id,
                        prompt=prompt,
                        request_fingerprint=plan.request_fingerprint,
                        output_size=STRICT_VISUAL_POLICY.output_size,
                        references=(
                            ImageReference(
                                role="approved_ip_reference",
                                asset_id=plan.reference_asset_ref,
                                filename=f"reference-{plan.reference_asset_ref}.jpg",
                                sha256=reference.sha256,
                                image_bytes=content,
                                selection_reason="approved_catalog_semantic_reference",
                                input_normalization_version=IMAGE_REFERENCE_INPUT_V2,
                                provider_input_sha256=plan.reference_input_checksum,
                            ),
                        ),
                        reference_mode="single_reference",
                    )
                )
            except Exception as error:
                # A dispatch without a trustworthy completion is never submitted again.
                await repository.fail_generated_visual(
                    claimed=claimed,
                    plan=plan,
                    error_code="official_account_generated_visual_result_unknown",
                    result_unknown=True,
                )
                raise OfficialAccountGeneratedVisualResultUnknownError() from error
            # Keep the intent ambiguous on storage/DB failure; no misleading 'generation failed'.
            try:
                prepared = prepare_generated_visual_result(
                    result=result, plan=plan, max_bytes=STRICT_VISUAL_POLICY.maximum_image_bytes
                )
                await store.put_immutable(
                    prepared.image_bytes, media_type=prepared.result.media_type
                )
                saved = await repository.persist_generated_visual(
                    claimed=claimed, plan=plan, result=prepared.result
                )
            except Exception as error:
                raise OfficialAccountGeneratedVisualResultUnknownError() from error
            if saved is None:
                return None
            stored = saved
            publication = prepared.image_bytes
        elif stored.status == "ready":
            publication = await store.get_content_addressed_bytes(
                media_type=stored.media_type or "",
                byte_size=stored.byte_size or 0,
                sha256=stored.sha256 or "",
            )
        else:
            raise _blocked("strict_visual_generation_failed")
        if sha256(publication).hexdigest() != stored.sha256 or len(publication) != stored.byte_size:
            raise ValueError("strict generated publication checksum changed")
        generated.append((stored, publication))
    batch_issues = strict_visual_batch_checks(
        tuple(body for _, body in generated), catalog_images=catalog_bytes
    )
    if batch_issues:
        raise _blocked(batch_issues[0])

    subjects: list[
        tuple[StrictVisualAuditSubject, bytes, bytes, StoredOfficialAccountGeneratedVisual]
    ] = []
    for index in range(6):
        cover = index == 5
        stored, publication = generated[0 if cover else index]
        derivative = (
            normalize_official_account_upload_cover(publication)
            if cover
            else normalize_official_account_upload_body(publication)
        )
        await store.put_immutable(derivative.content, media_type=derivative.mime_type)
        anchor = select_generated_visual_block_anchor(
            article=article, section_index=stored.plan.section_index
        )
        criteria = strict_visual_audit_criteria(
            article=article.article,
            section_index=stored.plan.section_index,
            block_context=anchor.scene_text,
            cover=cover,
        )
        subject = StrictVisualAuditSubject(
            run_id=claimed.run_id,
            article_version_id=article.id,
            render_version_id=rendered.id,
            role="cover" if cover else "body",
            ordinal=0 if cover else index,
            generated_visual_id=stored.id,
            generated_plan_request_fingerprint=stored.plan.request_fingerprint,
            reference_asset_ref=stored.plan.reference_asset_ref,
            reference_publication_sha256=stored.plan.reference_publication_checksum,
            publication_sha256=stored.sha256 or "",
            upload_sha256=derivative.sha256,
            upload_policy_version=derivative.policy_version,
            media_type=derivative.mime_type,
            byte_size=derivative.byte_size,
            width=derivative.width,
            height=derivative.height,
            criteria_fingerprint=fingerprint("strict-visual-criteria-v1", criteria),
            perceptual_hash=perceptual_dhash(derivative.content),
            catalog_perceptual_hashes=catalog_hashes,
        )
        subjects.append(
            (subject, derivative.content, reference_bytes[0 if cover else index], stored)
        )
    result_sources: list[OfficialAccountSourceMedia] = []
    for subject, content, audit_reference_bytes, stored in subjects:
        if lease_lost is not None and lease_lost.is_set():
            return None
        claim_audit = await repository.claim_strict_visual_audit(claimed=claimed, subject=subject)
        if claim_audit.outcome in {"lease_lost", "in_flight"}:
            return None
        if claim_audit.outcome == "result_unknown":
            raise OfficialAccountGeneratedVisualResultUnknownError()
        audit = claim_audit.audit
        if claim_audit.outcome == "newly_claimed":
            if lease_lost is not None and lease_lost.is_set():
                return None
            normalized = normalize_image_provider_reference(
                audit_reference_bytes, version=IMAGE_REFERENCE_INPUT_V2
            )
            if normalized.sha256 != stored.plan.reference_input_checksum:
                raise ValueError("strict audit normalized reference changed")
            anchor = select_generated_visual_block_anchor(
                article=article, section_index=stored.plan.section_index
            )
            criteria = strict_visual_audit_criteria(
                article=article.article,
                section_index=stored.plan.section_index,
                block_context=anchor.scene_text,
                cover=subject.role == "cover",
            )
            request = ImageQualityAuditRequest(
                image_bytes=content,
                media_type=subject.media_type,
                request_fingerprint=subject.request_fingerprint,
                criteria=criteria,
                prompt_version=subject.prompt_version,
                rubric_version=subject.rubric_version,
                references=(
                    ImageReference(
                        role="approved_ip_reference",
                        asset_id=subject.reference_asset_ref,
                        filename="approved-reference.png",
                        sha256=normalized.sha256,
                        image_bytes=normalized.image_png,
                        selection_reason="approved_catalog_semantic_reference",
                    ),
                ),
            )
            try:
                audit_result = await auditor.audit(request)
            except Exception as error:
                await repository.complete_strict_visual_audit(
                    claimed=claimed,
                    subject=subject,
                    status="result_unknown",
                    issue_codes=("strict_visual_audit_result_unknown",),
                )
                raise OfficialAccountGeneratedVisualResultUnknownError() from error
            accepted = strict_visual_audit_passes(
                accepted=audit_result.accepted,
                issues_present=bool(audit_result.issues),
                provider=audit_result.provider,
                model=audit_result.model,
                request_fingerprint=audit_result.request_fingerprint,
                expected_request_fingerprint=subject.request_fingerprint,
            )
            try:
                audit = await repository.complete_strict_visual_audit(
                    claimed=claimed,
                    subject=subject,
                    status="accepted" if accepted else "rejected",
                    issue_codes=() if accepted else ("strict_visual_audit_rejected",),
                    result=audit_result,
                )
            except Exception as error:
                raise OfficialAccountGeneratedVisualResultUnknownError() from error
            if audit is None:
                return None
        if audit is None or audit.status != "accepted" or audit.issue_codes:
            raise _blocked("strict_visual_audit_rejected")
        result_sources.append(
            OfficialAccountSourceMedia(
                source_image_artifact_id=None,
                fixture_id=None,
                generated_visual_id=stored.id,
                media_type=subject.media_type,
                byte_size=subject.byte_size,
                sha256=subject.upload_sha256,
                width=subject.width,
                height=subject.height,
                ordinal=subject.ordinal,
                semantic_label="按正文语义生成的插画",
                selection_reason="原生横版生成及最终上传字节审图通过",
                alt_text=generated_visual_alt_text(article=article, plan=stored.plan),
                candidate_id=stored.plan.reference_asset_ref,
                assigned_section_index=stored.plan.section_index,
                selection_method="deterministic_tag",
                selection_reason_code="stable_fallback",
                upload_derivative=strict_visual_derivative_descriptor(subject),
            )
        )
    return tuple(result_sources[:5]), replace(result_sources[5], ordinal=0)
