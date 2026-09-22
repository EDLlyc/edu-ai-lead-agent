"""Read-only proof that a current single edition exhausted its paid visual budget."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.official_account_local import (
    StoredOfficialAccountArticle,
    StoredOfficialAccountRender,
)
from app.application.ports.official_account_single_edition import SingleEdition
from app.application.ports.official_account_strict_visual import (
    resilient_visual_attempt_ordinal,
    resilient_visual_provider_request_fingerprint,
)
from app.application.services.official_account_catalog_fallback import fallback_failure_allowed
from app.domain.official_account_local import official_account_audit_releases
from app.domain.official_account_single_edition import SINGLE_EDITION_TIMEZONE
from app.domain.official_account_visual_pipeline import TOLERANT_VISUAL_PIPELINE_VERSION
from app.infrastructure.db.models import (
    OfficialAccountArticleAttemptModel as Attempt,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleRunModel as Run,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleVersionModel as Article,
)
from app.infrastructure.db.models import (
    OfficialAccountGeneratedVisualModel as Visual,
)
from app.infrastructure.db.models import (
    OfficialAccountRenderVersionModel as Render,
)
from app.infrastructure.db.models import (
    OfficialAccountSingleEditionModel as Edition,
)
from app.infrastructure.db.official_account_local import (
    _frozen_retry_policy,
    _stored_article,
    _stored_render,
)


@dataclass(frozen=True, slots=True)
class CatalogFallbackSource:
    article: StoredOfficialAccountArticle
    render: StoredOfficialAccountRender
    evidence: dict[str, object]


async def load_catalog_fallback_source(
    sessions: async_sessionmaker[AsyncSession],
    edition: SingleEdition,
    *,
    now: datetime,
) -> CatalogFallbackSource:
    if now.utcoffset() is None:
        raise ValueError("single_catalog_fallback_clock_invalid")
    async with sessions() as session:
        row = await session.get(Edition, edition.id)
        run = await session.get(Run, edition.article_run_id) if edition.article_run_id else None
        if (
            row is None
            or run is None
            or row.status != "generating"
            or row.lease_token != edition.lease_token
            or row.lease_token is None
            or row.lease_expires_at is None
            or row.lease_expires_at <= now
            or not row.prepare_at <= now < row.expires_at
            or row.business_date != now.astimezone(ZoneInfo(SINGLE_EDITION_TIMEZONE)).date()
            or row.business_date != edition.business_date
            or row.account_fingerprint != edition.account
            or row.role != edition.role
            or row.prepared_artifact is not None
            or row.receipt_fingerprint is not None
            or row.article_identity != asdict(edition.identity)
            or row.article_run_id != run.id
            or row.material_package_id != run.material_package_id
            or edition.identity.visual_pipeline_version != TOLERANT_VISUAL_PIPELINE_VERSION
            or run.version_bundle.get("visual_pipeline_version") != TOLERANT_VISUAL_PIPELINE_VERSION
            or any(
                run.version_bundle.get(key) != value
                for key, value in asdict(edition.identity).items()
            )
            or run.generation_mode != "live"
            or run.status not in {"failed", "result_unknown"}
            or run.error_code
            not in {
                "strict_visual_generation_attempts_exhausted",
                "strict_visual_generation_failed",
                "official_account_generated_visual_result_unknown",
            }
            or run.lease_token is not None
            or run.lease_expires_at is not None
            or run.active_draft_id is not None
        ):
            raise ValueError("single_catalog_fallback_ineligible")
        _, _, expiry = _frozen_retry_policy(run.version_bundle.get("execution_retry_policy"))
        if expiry != edition.expires_at or now >= expiry:
            raise ValueError("single_catalog_fallback_expired")
        article_row = await session.get(Article, run.active_article_version_id)
        render_row = await session.get(Render, run.active_render_version_id)
        if (
            article_row is None
            or render_row is None
            or article_row.run_id != run.id
            or render_row.run_id != run.id
            or render_row.article_version_id != article_row.id
        ):
            raise ValueError("single_catalog_fallback_content_missing")
        article, render = _stored_article(article_row), _stored_render(render_row)
        if (
            not article.validation_passed
            or article.audit is None
            or not official_account_audit_releases(
                article.audit, rule_version=article.article.versions.rule_version
            )
        ):
            raise ValueError("single_catalog_fallback_audit_failed")
        visuals = tuple(
            await session.scalars(
                select(Visual).where(Visual.run_id == run.id).order_by(Visual.ordinal)
            )
        )
        if (
            not 1 <= len(visuals) <= 5
            or [v.ordinal for v in visuals] != list(range(len(visuals)))
            or any(v.status != "ready" for v in visuals[:-1])
            or visuals[-1].status not in {"failed", "result_unknown"}
            or any(
                v.article_version_id != article.id or v.render_version_id != render.id
                for v in visuals
            )
        ):
            raise ValueError("single_catalog_fallback_visual_identity_invalid")
        visual = visuals[-1]
        selection = article.article.media_selection
        if selection is None or len(selection.assignments) != 5:
            raise ValueError("single_catalog_fallback_selection_missing")
        assignment = selection.assignments[visual.ordinal]
        if (
            visual.reference_asset_ref,
            visual.reference_catalog_version,
            visual.reference_source_checksum,
            visual.reference_publication_checksum,
        ) != (
            assignment.candidate_ref,
            selection.catalog_version,
            assignment.source_checksum,
            assignment.publication_checksum,
        ):
            raise ValueError("single_catalog_fallback_reference_changed")
        attempts = tuple(
            await session.scalars(
                select(Attempt)
                .where(
                    Attempt.run_id == run.id,
                    Attempt.capability == "visual_generation",
                    or_(
                        Attempt.ordinal.in_(
                            [
                                resilient_visual_attempt_ordinal(visual.ordinal, n)
                                for n in range(1, 4)
                            ]
                        ),
                        Attempt.safe_metadata["logical_request_fingerprint"].astext
                        == visual.request_fingerprint,
                        Attempt.safe_metadata["ordinal"].astext == str(visual.ordinal),
                    ),
                )
                .order_by(Attempt.ordinal)
            )
        )
        if len(attempts) != 3:
            raise ValueError("single_catalog_fallback_budget_not_exhausted")
        proofs: list[dict[str, object]] = []
        for number, attempt in enumerate(attempts, 1):
            metadata = attempt.safe_metadata
            request = resilient_visual_provider_request_fingerprint(
                visual.request_fingerprint,
                number,
                policy=TOLERANT_VISUAL_PIPELINE_VERSION,
            )
            if (
                attempt.status != "failed"
                or attempt.stage != "generating_body_visuals"
                or attempt.article_version_id != article.id
                or (attempt.provider, attempt.model) != (visual.provider, visual.model)
                or attempt.ordinal != resilient_visual_attempt_ordinal(visual.ordinal, number)
                or attempt.request_fingerprint != request
                or attempt.completed_at is None
                or metadata.get("physical_attempt_number") != number
                or metadata.get("ordinal") != visual.ordinal
                or metadata.get("provider_request_fingerprint") != request
                or metadata.get("logical_request_fingerprint") != visual.request_fingerprint
                or metadata.get("visual_pipeline_version") != TOLERANT_VISUAL_PIPELINE_VERSION
                or not fallback_failure_allowed(metadata.get("image_failure"))
            ):
                raise ValueError("single_catalog_fallback_attempt_proof_invalid")
            proofs.append(
                {
                    "request_fingerprint": request,
                    "diagnostic": cast(dict[str, object], metadata["image_failure"]),
                }
            )
        return CatalogFallbackSource(
            article,
            render,
            {
                "version": "single-catalog-fallback-evidence-v1",
                "physical_attempt_count": 3,
                "failed_slot": visual.ordinal,
                "logical_request_fingerprint": visual.request_fingerprint,
                "attempts": proofs,
            },
        )
