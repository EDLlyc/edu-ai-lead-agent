"""Prospective five-generation/six-audit workflow with durable dispatch authority."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from hashlib import sha256
from typing import Literal, cast

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
    RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS,
    ObserveVisualAuditSubject,
    StrictVisualAuditSubject,
    resilient_visual_failure_retries,
    strict_audit_record_fingerprint,
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
from app.core.errors import (
    AppError,
    ImageGenerationFailure,
    ImageOutputValidationError,
    OfficialAccountGeneratedVisualResultUnknownError,
    ProviderAuthenticationError,
    ProviderIdentityMismatchError,
    ProviderRateLimitError,
    ProviderRejectedError,
    ProviderUnavailableError,
    StrictImageGenerationError,
    classify_image_generation_failure,
)
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
    OBSERVE_VISUAL_PIPELINE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION,
    STRICT_VISUAL_PIPELINE_VERSION,
    STRICT_VISUAL_POLICY,
    StrictVisualPipelineVersion,
    native_visual_audit_releases,
    native_visual_is_advisory,
    native_visual_is_resilient,
    native_visual_output_geometry_policy,
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


async def _reference_characters(
    catalog: OfficialAccountCatalogMediaProvider, reference: OfficialAccountSourceMedia
) -> tuple[str, ...]:
    if not callable(getattr(catalog, "reference_characters", None)):
        raise _missing_xiaosai_reference()
    try:
        return await catalog.reference_characters(reference)
    except ValueError as error:
        raise _missing_xiaosai_reference() from error


def _missing_xiaosai_reference() -> AppError:
    return AppError(
        "official_account_xiaosai_reference_unavailable",
        "a current approved Xiaosai-only reference is required",
        422,
        False,
    )


async def xiaosai_catalog_candidates(
    catalog: OfficialAccountCatalogMediaProvider,
    candidates: tuple[OfficialAccountSourceMedia, ...],
) -> tuple[OfficialAccountSourceMedia, ...]:
    """Filter only the V5 selection pool; callers retain the full comparison pool."""
    eligible = tuple(
        [
            candidate
            for candidate in candidates
            if set(await _reference_characters(catalog, candidate)) == {"xiao-sai"}
        ]
    )
    if not eligible:
        raise _missing_xiaosai_reference()
    return eligible


async def validate_xiaosai_references(
    catalog: OfficialAccountCatalogMediaProvider,
    references: tuple[OfficialAccountSourceMedia, ...],
) -> None:
    """Recheck the complete persisted/new five-reference batch before any paid intent."""
    if len(references) != 5:
        raise _missing_xiaosai_reference()
    for reference in references:
        if set(await _reference_characters(catalog, reference)) != {"xiao-sai"}:
            raise _missing_xiaosai_reference()


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
    visual_policy = claimed.identity.visual_pipeline_version
    observe = visual_policy == OBSERVE_VISUAL_PIPELINE_VERSION
    resilient = native_visual_is_resilient(visual_policy)
    advisory = native_visual_is_advisory(visual_policy)
    output_geometry_policy = native_visual_output_geometry_policy(visual_policy)
    if (
        claimed.identity.generated_visual_prompt_version
        == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION
    ):
        await validate_xiaosai_references(catalog, references)
    reference_bytes = tuple([await _read_reference(catalog, ref) for ref in references])
    preflight_strict_generated_visuals(
        article=article, references=references, reference_bytes=reference_bytes
    )
    catalog_bytes = tuple([await _read_reference(catalog, ref) for ref in catalog_candidates])
    catalog_hashes = tuple(sorted({perceptual_dhash(content) for content in catalog_bytes}))
    catalog_publication_hashes = (
        tuple(sorted({sha256(content).hexdigest() for content in catalog_bytes}))
        if advisory
        else ()
    )
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
            output_geometry_policy=output_geometry_policy,
        )
        while True:
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
                effective_output_geometry_policy = claim.output_geometry_policy
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
                            provider_request_fingerprint=claim.provider_request_fingerprint,
                            output_size=STRICT_VISUAL_POLICY.output_size,
                            output_geometry_policy=effective_output_geometry_policy,
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
                    diagnostic = classify_image_generation_failure(error)
                    unknown = diagnostic.disposition == "unknown"
                    if not await repository.fail_generated_visual(
                        claimed=claimed,
                        plan=plan,
                        error_code=(
                            "official_account_generated_visual_result_unknown"
                            if unknown
                            else diagnostic.error_code
                        ),
                        result_unknown=unknown,
                        diagnostic=diagnostic,
                        provider_request_fingerprint=claim.provider_request_fingerprint,
                        physical_attempt_number=claim.physical_attempt_number,
                    ):
                        return None
                    retry_allowed = resilient and resilient_visual_failure_retries(diagnostic)
                    if (
                        retry_allowed
                        and claim.physical_attempt_number is not None
                        and claim.physical_attempt_number < RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS
                    ):
                        continue
                    if retry_allowed:
                        raise _blocked("strict_visual_generation_attempts_exhausted") from None
                    if unknown:
                        raise OfficialAccountGeneratedVisualResultUnknownError(
                            diagnostic=diagnostic
                        ) from None
                    raise StrictImageGenerationError(diagnostic) from None
                # V2 retains its exact-copy veto. V3 records reuse as advisory below.
                if observe and sha256(result.image_bytes).hexdigest() in catalog_publication_hashes:
                    if not await repository.fail_generated_visual(
                        claimed=claimed,
                        plan=plan,
                        error_code="strict_visual_catalog_exact_reuse",
                    ):
                        return None
                    raise _blocked("strict_visual_catalog_exact_reuse")
                try:
                    prepared = prepare_generated_visual_result(
                        result=result,
                        plan=plan,
                        max_bytes=STRICT_VISUAL_POLICY.maximum_image_bytes,
                        output_geometry_policy=effective_output_geometry_policy,
                    )
                except (
                    ValueError,
                    ImageOutputValidationError,
                    ProviderIdentityMismatchError,
                ) as error:
                    diagnostic = classify_image_generation_failure(
                        ImageOutputValidationError() if isinstance(error, ValueError) else error
                    )
                    if not await repository.fail_generated_visual(
                        claimed=claimed,
                        plan=plan,
                        error_code=diagnostic.error_code,
                        diagnostic=diagnostic,
                        provider_request_fingerprint=claim.provider_request_fingerprint,
                        physical_attempt_number=claim.physical_attempt_number,
                    ):
                        return None
                    retry_allowed = resilient and resilient_visual_failure_retries(diagnostic)
                    if (
                        retry_allowed
                        and claim.physical_attempt_number is not None
                        and claim.physical_attempt_number < RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS
                    ):
                        continue
                    if retry_allowed:
                        raise _blocked("strict_visual_generation_attempts_exhausted") from None
                    raise StrictImageGenerationError(diagnostic) from None
                try:
                    await store.put_immutable(
                        prepared.image_bytes, media_type=prepared.result.media_type
                    )
                    saved = await repository.persist_generated_visual(
                        claimed=claimed,
                        plan=plan,
                        result=prepared.result,
                        provider_request_fingerprint=claim.provider_request_fingerprint,
                        physical_attempt_number=claim.physical_attempt_number,
                    )
                except Exception:
                    diagnostic = ImageGenerationFailure(
                        error_code="official_account_generated_visual_result_unknown",
                        disposition="unknown",
                        reason="artifact_persistence_failed",
                    )
                    if resilient:
                        if not await repository.fail_generated_visual(
                            claimed=claimed,
                            plan=plan,
                            error_code=diagnostic.error_code,
                            result_unknown=True,
                            diagnostic=diagnostic,
                            provider_request_fingerprint=claim.provider_request_fingerprint,
                            physical_attempt_number=claim.physical_attempt_number,
                        ):
                            return None
                        if (
                            claim.physical_attempt_number is not None
                            and claim.physical_attempt_number
                            < RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS
                        ):
                            continue
                    raise OfficialAccountGeneratedVisualResultUnknownError(
                        diagnostic=diagnostic
                    ) from None
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
            break
        if sha256(publication).hexdigest() != stored.sha256 or len(publication) != stored.byte_size:
            raise ValueError("strict generated publication checksum changed")
        generated.append((stored, publication))
    batch_issues = strict_visual_batch_checks(
        tuple(body for _, body in generated),
        catalog_images=catalog_bytes,
        policy_version=cast(
            StrictVisualPipelineVersion, visual_policy or STRICT_VISUAL_PIPELINE_VERSION
        ),
    )
    blocking_issues = tuple(
        code
        for code in batch_issues
        if (not advisory)
        or code
        not in (
            {
                "strict_visual_perceptual_repetition",
                "strict_visual_catalog_reuse",
            }
            if observe
            else {
                "strict_visual_exact_repetition",
                "strict_visual_perceptual_repetition",
                "strict_visual_catalog_exact_reuse",
                "strict_visual_catalog_reuse",
            }
        )
    )
    if blocking_issues:
        raise _blocked(blocking_issues[0])

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
        if advisory:
            from dataclasses import asdict

            subject = ObserveVisualAuditSubject(
                **asdict(subject),
                catalog_publication_sha256s=catalog_publication_hashes,
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
        if claim_audit.outcome == "result_unknown" and not advisory:
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
                code = "strict_visual_audit_result_unknown"
                status: Literal["accepted", "rejected", "unavailable", "result_unknown"] = (
                    "result_unknown"
                )
                if advisory and isinstance(
                    error,
                    (
                        ProviderAuthenticationError,
                        ProviderRejectedError,
                        ProviderRateLimitError,
                        ProviderUnavailableError,
                    ),
                ):
                    status, code = "unavailable", "strict_visual_audit_unavailable"
                if advisory and isinstance(error, ProviderIdentityMismatchError):
                    status, code = "rejected", "strict_visual_audit_identity_mismatch"
                audit = await repository.complete_strict_visual_audit(
                    claimed=claimed,
                    subject=subject,
                    status=status,
                    issue_codes=(code,),
                )
                if not advisory:
                    raise OfficialAccountGeneratedVisualResultUnknownError() from error
            else:
                accepted = strict_visual_audit_passes(
                    accepted=audit_result.accepted,
                    issues_present=bool(audit_result.issues),
                    provider=audit_result.provider,
                    model=audit_result.model,
                    request_fingerprint=audit_result.request_fingerprint,
                    expected_request_fingerprint=subject.request_fingerprint,
                )
                codes = () if accepted else ("strict_visual_audit_rejected",)
                if advisory and not accepted:
                    if (
                        audit_result.provider,
                        audit_result.model,
                        audit_result.request_fingerprint,
                    ) != ("openai-compatible", subject.model, subject.request_fingerprint):
                        codes = ("strict_visual_audit_identity_mismatch",)
                try:
                    audit = await repository.complete_strict_visual_audit(
                        claimed=claimed,
                        subject=subject,
                        status="accepted" if accepted else "rejected",
                        issue_codes=codes,
                        result=audit_result,
                    )
                except Exception as error:
                    raise OfficialAccountGeneratedVisualResultUnknownError() from error
            if audit is None:
                return None
        if audit is None or not native_visual_audit_releases(
            claimed.identity.visual_pipeline_version, audit.status, audit.issue_codes
        ):
            raise _blocked("strict_visual_audit_rejected")
        if advisory and (
            audit.subject != subject
            or audit.record_fingerprint
            != strict_audit_record_fingerprint(subject, audit.status, audit.issue_codes)
        ):
            raise _blocked("strict_visual_audit_identity_mismatch")
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
                selection_reason=(
                    "原生横版生成及最终上传字节审图建议性留痕"
                    if resilient
                    else "原生横版生成及最终上传字节审图观察"
                    if observe
                    else "原生横版生成及最终上传字节审图通过"
                ),
                alt_text=generated_visual_alt_text(article=article, plan=stored.plan),
                candidate_id=stored.plan.reference_asset_ref,
                assigned_section_index=stored.plan.section_index,
                selection_method="deterministic_tag",
                selection_reason_code="stable_fallback",
                upload_derivative=strict_visual_derivative_descriptor(subject),
            )
        )
    return tuple(result_sources[:5]), replace(result_sources[5], ordinal=0)
