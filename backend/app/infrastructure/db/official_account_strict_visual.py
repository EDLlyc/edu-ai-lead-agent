"""Fenced one-shot audit authority, independent of legacy image observation."""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.image_validation import ImageQualityAuditResult
from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    OfficialAccountGeneratedVisualPlan,
)
from app.application.ports.official_account_strict_visual import (
    ObserveVisualAuditSubject,
    ObserveVisualMediaEvidence,
    StoredStrictVisualAudit,
    StrictGeneratedVisualClaim,
    StrictVisualAuditClaim,
    StrictVisualAuditSubject,
    StrictVisualMediaEvidence,
    observe_quality_issue_codes,
    strict_audit_record_fingerprint,
)
from app.application.ports.official_account_strict_visual import (
    strict_visual_derivative_descriptor as derivative_descriptor,
)
from app.application.services.official_account_visual_generation import (
    select_generated_visual_block_anchor,
)
from app.domain.official_account_local import ArticlePackage, fingerprint
from app.domain.official_account_upload_media import (
    OFFICIAL_ACCOUNT_UPLOAD_BODY_POLICY_VERSION,
    OFFICIAL_ACCOUNT_UPLOAD_COVER_POLICY_VERSION,
)
from app.domain.official_account_visual_pipeline import (
    NATIVE_VISUAL_PIPELINE_VERSIONS,
    OBSERVE_VISUAL_PIPELINE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
    STRICT_VISUAL_POLICY,
    native_visual_audit_releases,
    observe_visual_audit_codes_valid,
    strict_visual_audit_criteria,
    strict_visual_audit_passes,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleRunModel,
    OfficialAccountArticleVersionModel,
    OfficialAccountGeneratedVisualModel,
    OfficialAccountLocalMediaModel,
    OfficialAccountStrictVisualAuditModel,
)

_SUBJECT_ADAPTER = TypeAdapter(StrictVisualAuditSubject)


def _subject_payload(subject: StrictVisualAuditSubject) -> dict[str, object]:
    return {
        key: str(value)
        if isinstance(value, UUID)
        else list(value)
        if isinstance(value, tuple)
        else value
        for key, value in asdict(subject).items()
    }


def _subject_from_payload(payload: dict[str, object]) -> StrictVisualAuditSubject:
    if "catalog_publication_sha256s" in payload:
        if set(payload) != {field.name for field in fields(ObserveVisualAuditSubject)}:
            raise ValueError("observe audit subject fields changed")
        return TypeAdapter(ObserveVisualAuditSubject).validate_json(
            json.dumps(payload, allow_nan=False, ensure_ascii=False), strict=True
        )
    if set(payload) != {field.name for field in fields(StrictVisualAuditSubject)}:
        raise ValueError("strict audit subject fields changed")
    return _SUBJECT_ADAPTER.validate_json(
        json.dumps(payload, allow_nan=False, ensure_ascii=False), strict=True
    )


def _stored(row: OfficialAccountStrictVisualAuditModel) -> StoredStrictVisualAudit:
    subject = _subject_from_payload(row.subject)
    if isinstance(subject, ObserveVisualAuditSubject) and not observe_visual_audit_codes_valid(
        row.status, tuple(row.issue_codes)
    ):
        raise ValueError("observe audit issue codes are unsupported")
    if (
        (
            subject.run_id,
            subject.article_version_id,
            subject.render_version_id,
            subject.generated_visual_id,
            subject.role,
            subject.ordinal,
            subject.upload_sha256,
            subject.request_fingerprint,
        )
        != (
            row.run_id,
            row.article_version_id,
            row.render_version_id,
            row.generated_visual_id,
            row.role,
            row.ordinal,
            row.upload_sha256,
            row.request_fingerprint,
        )
        or row.status not in {"calling", "accepted", "rejected", "unavailable", "result_unknown"}
        or tuple(sorted(set(row.issue_codes))) != tuple(row.issue_codes)
        or any(not code.startswith("strict_visual_") or len(code) > 80 for code in row.issue_codes)
        or (row.status == "accepted" and row.issue_codes)
        or (
            row.status != "calling"
            and row.record_fingerprint
            != strict_audit_record_fingerprint(subject, row.status, tuple(row.issue_codes))
        )
    ):
        raise ValueError("strict audit stored identity changed")
    return StoredStrictVisualAudit(
        id=row.id,
        subject=subject,
        status=cast(
            Literal["calling", "accepted", "rejected", "unavailable", "result_unknown"], row.status
        ),
        issue_codes=tuple(row.issue_codes),
        record_fingerprint=row.record_fingerprint,
    )


async def _strict_fence(
    session: AsyncSession, claimed: ClaimedOfficialAccountRun
) -> OfficialAccountArticleRunModel | None:
    from app.infrastructure.db.official_account_local import _locked_fenced_run

    run = await _locked_fenced_run(session, claimed)
    if run is None or run.lease_expires_at is None or run.lease_expires_at <= datetime.now(UTC):
        return None
    if run.version_bundle.get("visual_pipeline_version") not in NATIVE_VISUAL_PIPELINE_VERSIONS:
        raise ValueError("strict audit requires frozen strict run")
    return run


async def _validate_subject(
    session: AsyncSession, run: OfficialAccountArticleRunModel, subject: StrictVisualAuditSubject
) -> OfficialAccountGeneratedVisualModel:
    observe = run.version_bundle.get("visual_pipeline_version") == OBSERVE_VISUAL_PIPELINE_VERSION
    if observe != isinstance(subject, ObserveVisualAuditSubject):
        raise ValueError("native visual subject policy changed")
    if isinstance(subject, ObserveVisualAuditSubject) and (
        subject.publication_sha256 in subject.catalog_publication_sha256s
        or subject.upload_sha256 in subject.catalog_publication_sha256s
    ):
        raise ValueError("observe output is an exact catalog copy")
    visual = await session.get(OfficialAccountGeneratedVisualModel, subject.generated_visual_id)
    article_row = await session.get(OfficialAccountArticleVersionModel, subject.article_version_id)
    if (
        (subject.run_id, subject.article_version_id, subject.render_version_id)
        != (run.id, run.active_article_version_id, run.active_render_version_id)
        or visual is None
        or article_row is None
        or article_row.run_id != run.id
        or visual.run_id != run.id
        or visual.article_version_id != subject.article_version_id
        or visual.render_version_id != subject.render_version_id
        or visual.status != "ready"
        or visual.plan_version != OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION
        or visual.output_size != "1536x1024"
        or (visual.width, visual.height) != (1536, 1024)
        or visual.provider != "comfly"
        or visual.model != "gpt-image-2"
        or visual.request_fingerprint != subject.generated_plan_request_fingerprint
        or visual.sha256 != subject.publication_sha256
        or visual.reference_asset_ref != subject.reference_asset_ref
        or visual.reference_publication_checksum != subject.reference_publication_sha256
        or (
            subject.role == "body"
            and (
                visual.ordinal != subject.ordinal
                or subject.upload_policy_version != OFFICIAL_ACCOUNT_UPLOAD_BODY_POLICY_VERSION
                or (subject.width, subject.height) != (1536, 1024)
            )
        )
        or (
            subject.role == "cover"
            and (
                visual.ordinal != 0
                or subject.upload_policy_version != OFFICIAL_ACCOUNT_UPLOAD_COVER_POLICY_VERSION
                or (subject.width, subject.height) != (1175, 500)
                or subject.byte_size >= 65536
            )
        )
    ):
        raise ValueError("strict visual subject active lineage changed")
    article = ArticlePackage.model_validate(article_row.article_payload)
    if (
        article.media_selection is None
        or article.media_selection.reference_policy_version
        != "official-account-reference-scenes-v1-native-strict"
    ):
        raise ValueError("strict visual article reference policy changed")
    from app.infrastructure.db.official_account_local import _stored_article

    anchor = select_generated_visual_block_anchor(
        article=_stored_article(article_row), section_index=visual.section_index
    )
    assignment = article.media_selection.assignments[visual.ordinal]
    if (visual.block_index, visual.block_kind, visual.block_fingerprint) != (
        anchor.block_index,
        anchor.block_kind,
        anchor.block_fingerprint,
    ) or (
        visual.section_index,
        visual.reference_asset_ref,
        visual.reference_source_checksum,
        visual.reference_publication_checksum,
    ) != (
        assignment.section_index,
        assignment.candidate_ref,
        assignment.source_checksum,
        assignment.publication_checksum,
    ):
        raise ValueError("strict generated visual article block binding changed")
    criteria = strict_visual_audit_criteria(
        article=article,
        section_index=visual.section_index,
        block_context=anchor.scene_text,
        cover=subject.role == "cover",
    )
    if subject.criteria_fingerprint != fingerprint("strict-visual-criteria-v1", criteria):
        raise ValueError("strict visual audit criteria changed")
    return visual


class PostgresStrictVisualRepositoryMixin:
    _session_factory: async_sessionmaker[AsyncSession]

    async def claim_strict_generated_visual(
        self, *, claimed: ClaimedOfficialAccountRun, plan: OfficialAccountGeneratedVisualPlan
    ) -> StrictGeneratedVisualClaim:
        from app.infrastructure.db.official_account_local import (
            _assert_generated_visual_plan,
            _stored_generated_visual,
            _validate_generated_visual_plan,
        )

        _validate_generated_visual_plan(plan)
        async with self._session_factory() as session:
            run = await _strict_fence(session, claimed)
            if run is None:
                return StrictGeneratedVisualClaim("lease_lost", None)
            if (plan.run_id, plan.article_version_id, plan.render_version_id) != (
                run.id,
                run.active_article_version_id,
                run.active_render_version_id,
            ) or plan.plan_version != OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION:
                raise ValueError("strict generation plan changed")
            row = await session.scalar(
                select(OfficialAccountGeneratedVisualModel)
                .where(
                    OfficialAccountGeneratedVisualModel.run_id == run.id,
                    OfficialAccountGeneratedVisualModel.ordinal == plan.ordinal,
                )
                .with_for_update()
            )
            if row is not None:
                _assert_generated_visual_plan(row, plan)
                if row.status == "generating":
                    if (row.intent_lease_token, row.intent_attempt_number) == (
                        claimed.lease_token,
                        claimed.attempt_number,
                    ):
                        return StrictGeneratedVisualClaim(
                            "in_flight", _stored_generated_visual(row)
                        )
                    row.status = "result_unknown"
                    row.error_code = "official_account_generated_visual_result_unknown"
                    row.completed_at = datetime.now(UTC)
                    await session.commit()
                outcome: Literal["result_unknown", "completed"] = (
                    "result_unknown" if row.status == "result_unknown" else "completed"
                )
                return StrictGeneratedVisualClaim(outcome, _stored_generated_visual(row))
            row = OfficialAccountGeneratedVisualModel(
                id=uuid4(),
                **asdict(plan),
                status="generating",
                intent_lease_token=claimed.lease_token,
                intent_attempt_number=claimed.attempt_number,
            )
            session.add(row)
            run.current_stage = "generating_body_visuals"
            await session.commit()
            return StrictGeneratedVisualClaim("newly_claimed", _stored_generated_visual(row))

    async def claim_strict_visual_audit(
        self, *, claimed: ClaimedOfficialAccountRun, subject: StrictVisualAuditSubject
    ) -> StrictVisualAuditClaim:
        async with self._session_factory() as session:
            run = await _strict_fence(session, claimed)
            if run is None:
                return StrictVisualAuditClaim("lease_lost", None)
            await _validate_subject(session, run, subject)
            row = await session.scalar(
                select(OfficialAccountStrictVisualAuditModel)
                .where(
                    OfficialAccountStrictVisualAuditModel.run_id == run.id,
                    OfficialAccountStrictVisualAuditModel.role == subject.role,
                    OfficialAccountStrictVisualAuditModel.ordinal == subject.ordinal,
                )
                .with_for_update()
            )
            if row is not None:
                stored = _stored(row)
                if stored.subject != subject:
                    raise ValueError("strict audit recovery subject changed")
                if row.status == "calling":
                    if (row.lease_token, row.attempt_number) == (
                        claimed.lease_token,
                        claimed.attempt_number,
                    ):
                        return StrictVisualAuditClaim("in_flight", stored)
                    row.status = "result_unknown"
                    row.issue_codes = ["strict_visual_orphaned_call"]
                    row.record_fingerprint = strict_audit_record_fingerprint(
                        subject, row.status, tuple(row.issue_codes)
                    )
                    row.completed_at = datetime.now(UTC)
                    await session.commit()
                return StrictVisualAuditClaim(
                    "result_unknown" if row.status == "result_unknown" else "completed",
                    _stored(row),
                )
            row = OfficialAccountStrictVisualAuditModel(
                id=uuid4(),
                run_id=subject.run_id,
                article_version_id=subject.article_version_id,
                render_version_id=subject.render_version_id,
                generated_visual_id=subject.generated_visual_id,
                role=subject.role,
                ordinal=subject.ordinal,
                upload_sha256=subject.upload_sha256,
                request_fingerprint=subject.request_fingerprint,
                subject=_subject_payload(subject),
                lease_token=claimed.lease_token,
                attempt_number=claimed.attempt_number,
                status="calling",
                issue_codes=[],
            )
            session.add(row)
            await session.commit()
            return StrictVisualAuditClaim("newly_claimed", _stored(row))

    async def complete_strict_visual_audit(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        subject: StrictVisualAuditSubject,
        status: Literal["accepted", "rejected", "unavailable", "result_unknown"],
        issue_codes: tuple[str, ...],
        result: ImageQualityAuditResult | None = None,
    ) -> StoredStrictVisualAudit | None:
        if isinstance(subject, ObserveVisualAuditSubject) and not observe_visual_audit_codes_valid(
            status, issue_codes
        ):
            raise ValueError("observe audit issue codes are unsupported")
        if (
            status not in {"accepted", "rejected", "unavailable", "result_unknown"}
            or tuple(sorted(set(issue_codes))) != issue_codes
            or any(not code.startswith("strict_visual_") or len(code) > 80 for code in issue_codes)
            or (status == "accepted" and issue_codes)
        ):
            raise ValueError("strict audit result is invalid")
        if status == "accepted" and (
            result is None
            or not strict_visual_audit_passes(
                accepted=result.accepted,
                issues_present=bool(result.issues),
                provider=result.provider,
                model=result.model,
                request_fingerprint=result.request_fingerprint,
                expected_request_fingerprint=subject.request_fingerprint,
            )
        ):
            raise ValueError("strict audit accepted result identity is invalid")
        async with self._session_factory() as session:
            run = await _strict_fence(session, claimed)
            if run is None:
                return None
            await _validate_subject(session, run, subject)
            row = await session.scalar(
                select(OfficialAccountStrictVisualAuditModel)
                .where(
                    OfficialAccountStrictVisualAuditModel.request_fingerprint
                    == subject.request_fingerprint
                )
                .with_for_update()
            )
            if row is None or _stored(row).subject != subject:
                raise ValueError("strict audit intent is missing")
            if row.status != "calling" or (row.lease_token, row.attempt_number) != (
                claimed.lease_token,
                claimed.attempt_number,
            ):
                return None
            row.status = status
            row.issue_codes = list(issue_codes)
            row.record_fingerprint = strict_audit_record_fingerprint(subject, status, issue_codes)
            row.completed_at = datetime.now(UTC)
            await session.commit()
            return _stored(row)

    async def load_strict_visual_evidence(
        self, run_id: UUID
    ) -> tuple[StrictVisualMediaEvidence, ...]:
        async with self._session_factory() as session:
            run = await session.get(OfficialAccountArticleRunModel, run_id)
            if run is None or run.status != "ready":
                raise ValueError("strict visual run is not ready")
            return await validate_strict_visual_ready(session, run)


async def validate_strict_visual_ready(
    session: AsyncSession, run: OfficialAccountArticleRunModel
) -> tuple[StrictVisualMediaEvidence, ...]:
    policy = run.version_bundle.get("visual_pipeline_version")
    observe = policy == OBSERVE_VISUAL_PIPELINE_VERSION
    if policy not in NATIVE_VISUAL_PIPELINE_VERSIONS:
        raise ValueError("strict visual policy is absent")
    rows = tuple(
        (
            await session.scalars(
                select(OfficialAccountStrictVisualAuditModel)
                .where(OfficialAccountStrictVisualAuditModel.run_id == run.id)
                .order_by(
                    OfficialAccountStrictVisualAuditModel.role,
                    OfficialAccountStrictVisualAuditModel.ordinal,
                )
            )
        ).all()
    )
    if tuple((row.role, row.ordinal) for row in rows) != (
        *(("body", index) for index in range(5)),
        ("cover", 0),
    ):
        raise ValueError("strict visual six audit subjects are incomplete")
    media = tuple(
        (
            await session.scalars(
                select(OfficialAccountLocalMediaModel)
                .where(
                    OfficialAccountLocalMediaModel.run_id == run.id,
                    OfficialAccountLocalMediaModel.role.in_(("body", "cover")),
                )
                .order_by(
                    OfficialAccountLocalMediaModel.role, OfficialAccountLocalMediaModel.ordinal
                )
            )
        ).all()
    )
    if len(media) != 6:
        raise ValueError("strict visual final media are incomplete")
    evidence: list[StrictVisualMediaEvidence] = []
    subjects: list[StrictVisualAuditSubject] = []
    for row, final_media in zip(rows, media, strict=True):
        audit = _stored(row)
        subject = audit.subject
        visual = await _validate_subject(session, run, subject)
        if (
            not native_visual_audit_releases(policy, audit.status, audit.issue_codes)
            or audit.record_fingerprint is None
            or (
                final_media.role,
                final_media.ordinal,
                final_media.generated_visual_id,
                final_media.render_version_id,
                final_media.sha256,
                final_media.media_type,
                final_media.byte_size,
                final_media.status,
            )
            != (
                subject.role,
                subject.ordinal,
                subject.generated_visual_id,
                subject.render_version_id,
                subject.upload_sha256,
                subject.media_type,
                subject.byte_size,
                "ready",
            )
            or final_media.descriptor.get("upload_derivative") != derivative_descriptor(subject)
        ):
            raise ValueError("strict visual final audit gate rejected")
        subjects.append(subject)
        proof = StrictVisualMediaEvidence(
            **{
                key: getattr(subject, key)
                for key in (
                    "role",
                    "ordinal",
                    "generated_visual_id",
                    "generated_plan_request_fingerprint",
                    "reference_asset_ref",
                    "reference_publication_sha256",
                    "publication_sha256",
                    "upload_sha256",
                    "upload_policy_version",
                    "media_type",
                    "byte_size",
                    "width",
                    "height",
                    "provider",
                    "model",
                )
            },
            audit_id=audit.id,
            audit_request_fingerprint=subject.request_fingerprint,
            audit_record_fingerprint=audit.record_fingerprint,
            plan_version=visual.plan_version,
            prompt_version=visual.prompt_version,
            native_output_size=visual.output_size or "",
        )
        if observe:
            if not isinstance(subject, ObserveVisualAuditSubject) or audit.status == "calling":
                raise ValueError("observe evidence is incomplete")
            proof = ObserveVisualMediaEvidence(
                **asdict(proof),
                audit_status=audit.status,
                audit_issue_codes=audit.issue_codes,
                audit_subject=subject,
                quality_issue_codes=(),
            )
        evidence.append(proof)
    # Deterministic batch gate is recomputed here, never an executor-supplied 'passed' flag.
    bodies = subjects[:5]
    if len({item.upload_sha256 for item in bodies}) != 5 or (
        observe and len({item.publication_sha256 for item in bodies}) != 5
    ):
        raise ValueError("strict visual exact repeats rejected")
    for index, subject in enumerate(bodies):
        if subject.catalog_perceptual_hashes != bodies[0].catalog_perceptual_hashes:
            raise ValueError("strict visual catalog batch changed")
        if observe:
            first = bodies[0]
            if (
                not isinstance(subject, ObserveVisualAuditSubject)
                or not isinstance(first, ObserveVisualAuditSubject)
                or subject.catalog_publication_sha256s != first.catalog_publication_sha256s
            ):
                raise ValueError("observe catalog byte set changed")
            continue
        comparisons = (
            *subject.catalog_perceptual_hashes,
            *(other.perceptual_hash for other in bodies[:index]),
        )
        if any(
            (int(subject.perceptual_hash, 16) ^ int(other, 16)).bit_count()
            <= STRICT_VISUAL_POLICY.maximum_duplicate_distance
            for other in comparisons
        ):
            raise ValueError("strict visual perceptual repeats rejected")
    if observe:
        from dataclasses import replace

        evidence = [
            replace(
                item,
                quality_issue_codes=observe_quality_issue_codes(item.audit_subject, tuple(bodies)),
            )
            if isinstance(item, ObserveVisualMediaEvidence)
            else item
            for item in evidence
        ]
    return tuple(evidence)
