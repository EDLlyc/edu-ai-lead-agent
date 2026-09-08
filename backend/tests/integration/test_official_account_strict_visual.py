from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from app.application.ports.image_validation import ImageQualityAuditIssue, ImageQualityAuditResult
from app.application.ports.official_account_local import (
    OfficialAccountDraftResult,
    OfficialAccountGeneratedVisualPlan,
    OfficialAccountGeneratedVisualResult,
    OfficialAccountMediaResult,
    OfficialAccountSourceMedia,
)
from app.application.ports.official_account_strict_visual import (
    StrictVisualAuditSubject,
    strict_visual_derivative_descriptor,
)
from app.application.services.official_account_visual_generation import (
    select_generated_visual_block_anchor,
)
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V2
from app.domain.official_account_local import fingerprint
from app.domain.official_account_upload_media import (
    OFFICIAL_ACCOUNT_UPLOAD_BODY_POLICY_VERSION,
    OFFICIAL_ACCOUNT_UPLOAD_COVER_POLICY_VERSION,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION,
    STRICT_VISUAL_PIPELINE_VERSION,
    strict_visual_audit_criteria,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleRunModel,
    OfficialAccountArticleVersionModel,
    OfficialAccountGeneratedVisualModel,
    OfficialAccountStrictVisualAuditModel,
)
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from .conftest import IntegrationContext
from .test_official_account_local import _executor, _FailBodyOnceMediaAdapter, _v10_identity

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def integration_context():
    # Strict rows deliberately forbid downgrade. Keep them out of the legacy migration suite DB.
    from .conftest import integration_context as context_fixture

    iterator = context_fixture.__wrapped__()
    context = await anext(iterator)
    try:
        yield context
    finally:
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)


async def _prime(context: IntegrationContext):
    repository = PostgresOfficialAccountRepository(context.session_factory)
    run, _ = await repository.enqueue_fixture(identity=_v10_identity(suffix=uuid4().hex[:8]))
    assert await _executor(repository, media_adapter=_FailBodyOnceMediaAdapter()).execute_next(
        "prime"
    )
    article = await repository.get_article(run.id)
    rendered = await repository.get_render(run.id)
    assert article is not None and rendered is not None
    assert article.article.media_selection is not None
    from app.domain.official_account_local import ArticleImageBlock, ArticlePackage

    original_selection = article.article.media_selection
    assignments = tuple(
        original_selection.assignments[i % len(original_selection.assignments)].model_copy(
            update={"ordinal": i, "section_index": i}
        )
        for i in range(5)
    )
    selection = original_selection.model_copy(
        update={
            "reference_policy_version": "official-account-reference-scenes-v1-native-strict",
            "assignments": assignments,
            "status": "semantic_unavailable",
            "closed_reason": "disabled",
        }
    )
    image = next(
        block
        for section in article.article.sections
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    )
    sections = tuple(
        article.article.sections[i % len(article.article.sections)].model_copy(
            update={
                "blocks": (
                    *(
                        block
                        for block in article.article.sections[
                            i % len(article.article.sections)
                        ].blocks
                        if not isinstance(block, ArticleImageBlock)
                    ),
                    image.model_copy(update={"slot_key": f"body-{i}"}),
                )
            }
        )
        for i in range(5)
    )
    package = article.article.model_copy(
        update={"media_selection": selection, "sections": sections}
    )
    article = replace(
        article, article=ArticlePackage.model_validate(package.model_dump(mode="json"))
    )
    claimed = await repository.claim(worker_id="strict-tests", lease_seconds=600, max_attempts=3)
    assert claimed is not None and claimed.run_id == run.id
    identity = replace(
        claimed.identity,
        provider="zhipu",
        model="glm-5.2",
        visual_pipeline_version=STRICT_VISUAL_PIPELINE_VERSION,
        generated_visual_plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
        generated_visual_prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION,
    )
    claimed = replace(claimed, identity=identity)
    async with context.session_factory() as session:
        await session.execute(
            update(OfficialAccountArticleRunModel)
            .where(OfficialAccountArticleRunModel.id == run.id)
            .values(version_bundle=asdict(identity))
        )
        await session.execute(
            update(OfficialAccountArticleVersionModel)
            .where(OfficialAccountArticleVersionModel.id == article.id)
            .values(article_payload=article.article.model_dump(mode="json"))
        )
        await session.commit()
    return repository, claimed, article, rendered


def _plan(claimed, article, rendered, ordinal=0):
    item = article.article.media_selection.assignments[ordinal]
    anchor = select_generated_visual_block_anchor(article=article, section_index=item.section_index)
    return OfficialAccountGeneratedVisualPlan(
        run_id=claimed.run_id,
        article_version_id=article.id,
        render_version_id=rendered.id,
        ordinal=ordinal,
        section_index=item.section_index,
        block_index=anchor.block_index,
        block_kind=anchor.block_kind,
        block_fingerprint=anchor.block_fingerprint,
        reference_asset_ref=item.candidate_ref,
        reference_catalog_version="brand-visual-catalog-v1",
        reference_source_checksum=item.source_checksum,
        reference_publication_checksum=item.publication_checksum,
        reference_input_version=IMAGE_REFERENCE_INPUT_V2,
        reference_input_checksum="3" * 64,
        selection_method="deterministic_tag",
        similarity_band=None,
        request_fingerprint=fingerprint(claimed.run_id, ordinal),
        plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
        prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION,
        output_profile_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_V4_VERSION,
        output_size="1536x1024",
        provider="comfly",
        model="gpt-image-2",
    )


async def _generated(repository, claimed, article, rendered, ordinal=0):
    plan = _plan(claimed, article, rendered, ordinal)
    claim = await repository.claim_strict_generated_visual(claimed=claimed, plan=plan)
    assert claim.outcome == "newly_claimed"
    stored = await repository.persist_generated_visual(
        claimed=claimed,
        plan=plan,
        result=OfficialAccountGeneratedVisualResult(
            media_type="image/jpeg",
            byte_size=100,
            sha256=fingerprint("synthetic-generated", claimed.run_id, ordinal),
            width=1536,
            height=1024,
        ),
    )
    assert stored is not None
    return stored


def _subject(stored, article, cover=False):
    plan = stored.plan
    anchor = select_generated_visual_block_anchor(article=article, section_index=plan.section_index)
    criteria = strict_visual_audit_criteria(
        article=article.article,
        section_index=plan.section_index,
        block_context=anchor.scene_text,
        cover=cover,
    )
    return StrictVisualAuditSubject(
        run_id=plan.run_id,
        article_version_id=article.id,
        render_version_id=plan.render_version_id,
        role="cover" if cover else "body",
        ordinal=0 if cover else plan.ordinal,
        generated_visual_id=stored.id,
        generated_plan_request_fingerprint=plan.request_fingerprint,
        reference_asset_ref=plan.reference_asset_ref,
        reference_publication_sha256=plan.reference_publication_checksum,
        publication_sha256=stored.sha256,
        upload_sha256=fingerprint("synthetic-upload", stored.id, cover),
        upload_policy_version=OFFICIAL_ACCOUNT_UPLOAD_COVER_POLICY_VERSION
        if cover
        else OFFICIAL_ACCOUNT_UPLOAD_BODY_POLICY_VERSION,
        media_type="image/jpeg",
        byte_size=100,
        width=1175 if cover else 1536,
        height=500 if cover else 1024,
        criteria_fingerprint=fingerprint("strict-visual-criteria-v1", criteria),
        perceptual_hash=(
            "ffffffff00000000",
            "00000000ffffffff",
            "aaaaaaaaaaaaaaaa",
            "5555555555555555",
            "ffff0000ffff0000",
        )[plan.ordinal],
        catalog_perceptual_hashes=("0000000000000000",),
    )


def _accepted(subject, **changes):
    return ImageQualityAuditResult(
        **{
            "accepted": True,
            "provider": "openai-compatible",
            "model": "glm-5v-turbo",
            "request_fingerprint": subject.request_fingerprint,
            **changes,
        }
    )


async def _accept(repository, claimed, subject):
    call = await repository.claim_strict_visual_audit(claimed=claimed, subject=subject)
    assert call.outcome == "newly_claimed"
    result = await repository.complete_strict_visual_audit(
        claimed=claimed,
        subject=subject,
        status="accepted",
        issue_codes=(),
        result=_accepted(subject),
    )
    assert result is not None and result.status == "accepted"
    return result


async def test_empty_schema_downgrade_and_reupgrade(integration_context):
    from alembic import command
    from alembic.config import Config

    config = Config("backend/alembic.ini")
    await asyncio.to_thread(command.downgrade, config, "20260901_0042")
    async with integration_context.session_factory() as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version")) == "20260901_0042"
        )
    await asyncio.to_thread(command.upgrade, config, "head")


async def test_concurrent_one_shot_claims_and_completed_replay(integration_context):
    repo, claimed, article, rendered = await _prime(integration_context)
    plan = _plan(claimed, article, rendered)
    claims = await asyncio.gather(
        *(repo.claim_strict_generated_visual(claimed=claimed, plan=plan) for _ in range(4))
    )
    assert sorted(claim.outcome for claim in claims) == ["in_flight"] * 3 + ["newly_claimed"]
    stored = await repo.persist_generated_visual(
        claimed=claimed,
        plan=plan,
        result=OfficialAccountGeneratedVisualResult("image/jpeg", 100, "b" * 64, 1536, 1024),
    )
    subject = _subject(stored, article)
    claims = await asyncio.gather(
        *(repo.claim_strict_visual_audit(claimed=claimed, subject=subject) for _ in range(4))
    )
    assert sorted(claim.outcome for claim in claims) == ["in_flight"] * 3 + ["newly_claimed"]
    await repo.complete_strict_visual_audit(
        claimed=claimed,
        subject=subject,
        status="accepted",
        issue_codes=(),
        result=_accepted(subject),
    )
    replay = await repo.claim_strict_visual_audit(claimed=claimed, subject=subject)
    assert replay.outcome == "completed" and replay.audit.status == "accepted"
    assert (
        await repo.complete_strict_visual_audit(
            claimed=claimed,
            subject=subject,
            status="rejected",
            issue_codes=("strict_visual_rejected",),
        )
        is None
    )


async def test_expired_orphan_audit_unknown_and_stale_result_fenced(integration_context):
    repo, claimed, article, rendered = await _prime(integration_context)
    stored = await _generated(repo, claimed, article, rendered)
    subject = _subject(stored, article)
    assert (
        await repo.claim_strict_visual_audit(claimed=claimed, subject=subject)
    ).outcome == "newly_claimed"
    async with integration_context.session_factory() as session:
        await session.execute(
            update(OfficialAccountArticleRunModel)
            .where(OfficialAccountArticleRunModel.id == claimed.run_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert (
        await repo.claim_strict_visual_audit(claimed=claimed, subject=subject)
    ).outcome == "lease_lost"
    newer = await repo.claim(worker_id="reclaim", lease_seconds=600, max_attempts=5)
    assert newer.run_id == claimed.run_id
    assert (
        await repo.claim_strict_visual_audit(claimed=newer, subject=subject)
    ).outcome == "result_unknown"
    assert (
        await repo.complete_strict_visual_audit(
            claimed=claimed,
            subject=subject,
            status="accepted",
            issue_codes=(),
            result=_accepted(subject),
        )
        is None
    )
    assert (await repo.get_generated_visual(run_id=claimed.run_id, ordinal=0)).status == "ready"


@pytest.mark.parametrize(
    "change",
    [
        {"accepted": False},
        {"model": "other"},
        {"provider": "other"},
        {"request_fingerprint": "f" * 64},
        {"issues": (ImageQualityAuditIssue(code="aesthetics_low", severity="warning"),)},
    ],
)
async def test_repository_rejects_forged_acceptance(integration_context, change):
    repo, claimed, article, rendered = await _prime(integration_context)
    subject = _subject(await _generated(repo, claimed, article, rendered), article)
    await repo.claim_strict_visual_audit(claimed=claimed, subject=subject)
    with pytest.raises(ValueError, match="accepted result identity"):
        await repo.complete_strict_visual_audit(
            claimed=claimed,
            subject=subject,
            status="accepted",
            issue_codes=(),
            result=_accepted(subject, **change),
        )
    assert (
        await repo.claim_strict_visual_audit(claimed=claimed, subject=subject)
    ).outcome == "in_flight"


async def _stage(repository, claimed, rendered, subject):
    source = OfficialAccountSourceMedia(
        source_image_artifact_id=None,
        fixture_id=None,
        generated_visual_id=subject.generated_visual_id,
        media_type=subject.media_type,
        byte_size=subject.byte_size,
        sha256=subject.upload_sha256,
        ordinal=subject.ordinal,
        upload_derivative=strict_visual_derivative_descriptor(subject),
    )
    media = OfficialAccountMediaResult(
        local_media_id="strict-test-" + uuid4().hex,
        role=subject.role,
        ordinal=subject.ordinal,
        media_url="/local/strict",
        media_type=subject.media_type,
        byte_size=subject.byte_size,
        sha256=subject.upload_sha256,
    )
    return await repository.persist_media(
        claimed=claimed,
        render=rendered,
        source_media=source,
        request_fingerprint=fingerprint(subject.request_fingerprint, "media"),
        result=media,
    )


async def test_ready_requires_all_six_exact_audits_and_retains_siblings(integration_context):
    repo, claimed, article, rendered = await _prime(integration_context)
    visuals = [await _generated(repo, claimed, article, rendered, i) for i in range(5)]
    subjects = [_subject(visual, article) for visual in visuals] + [
        _subject(visuals[0], article, True)
    ]
    staged = []
    for subject in subjects:
        await _accept(repo, claimed, subject)
        staged.append(await _stage(repo, claimed, rendered, subject))
    async with integration_context.session_factory() as session:
        row = await session.scalar(
            select(OfficialAccountStrictVisualAuditModel).where(
                OfficialAccountStrictVisualAuditModel.run_id == claimed.run_id,
                OfficialAccountStrictVisualAuditModel.role == "cover",
            )
        )
        original_record = row.record_fingerprint
        row.record_fingerprint = "e" * 64
        await session.commit()
    kwargs = dict(
        claimed=claimed,
        render=rendered,
        body_media_id=staged[0][0],
        body_media_ids=tuple(item[0] for item in staged[:5]),
        cover_media_id=staged[-1][0],
        request_fingerprint=fingerprint("strict-draft", claimed.run_id),
        result=OfficialAccountDraftResult(
            local_draft_id="strict-draft-test", simulation=True, resolved_html="<p>test</p>"
        ),
    )
    with pytest.raises(ValueError, match="stored identity"):
        await repo.persist_draft(**kwargs)
    assert (await repo.get_run(claimed.run_id)).status == "running"
    assert all(
        [
            (await repo.get_generated_visual(run_id=claimed.run_id, ordinal=i)).status == "ready"
            for i in range(5)
        ]
    )
    async with integration_context.session_factory() as session:
        await session.execute(
            update(OfficialAccountStrictVisualAuditModel)
            .where(
                OfficialAccountStrictVisualAuditModel.run_id == claimed.run_id,
                OfficialAccountStrictVisualAuditModel.role == "cover",
            )
            .values(record_fingerprint=original_record)
        )
        await session.commit()
    assert await repo.persist_draft(**kwargs) is not None
    assert len(await repo.load_strict_visual_evidence(claimed.run_id)) == 6


@pytest.mark.parametrize(
    "column", ["output_size", "intent_attempt_number", "block_index", "reference_input_checksum"]
)
async def test_native_sql_constraints_reject_nulls(integration_context, column):
    repo, claimed, article, rendered = await _prime(integration_context)
    stored = await _generated(repo, claimed, article, rendered)
    async with integration_context.session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                update(OfficialAccountGeneratedVisualModel)
                .where(OfficialAccountGeneratedVisualModel.id == stored.id)
                .values(**{column: None})
            )
        await session.rollback()


async def test_terminal_audit_requires_nonnull_record(integration_context):
    repo, claimed, article, rendered = await _prime(integration_context)
    subject = _subject(await _generated(repo, claimed, article, rendered), article)
    await repo.claim_strict_visual_audit(claimed=claimed, subject=subject)
    async with integration_context.session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                update(OfficialAccountStrictVisualAuditModel)
                .where(OfficialAccountStrictVisualAuditModel.run_id == claimed.run_id)
                .values(status="accepted", completed_at=datetime.now(UTC), record_fingerprint=None)
            )
        await session.rollback()


async def test_schema_upgrade_and_populated_downgrade_fence(integration_context):
    from alembic import command
    from alembic.config import Config

    await _prime(integration_context)
    with pytest.raises(Exception, match="cannot downgrade populated strict visual pipeline"):
        await asyncio.to_thread(command.downgrade, Config("backend/alembic.ini"), "20260901_0042")
    async with integration_context.session_factory() as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version")) == "20260907_0043"
        )


@pytest_asyncio.fixture(loop_scope="session")
async def native_path_context():
    # Each case executes the same frozen synthetic text; render fingerprints are globally
    # unique in production. Isolate cases instead of changing that production constraint.
    from .conftest import integration_context as context_fixture

    iterator = context_fixture.__wrapped__()
    context = await anext(iterator)
    try:
        yield context
    finally:
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)


@pytest.mark.parametrize(
    "visual_case",
    [
        "strict",
        "observe",
        "observe_mixed",
        "observe_perceptual",
        "observe_orphan",
        "observe_exact_echo",
    ],
)
async def test_normal_material_enqueue_executor_durable_ready_and_prepared_consumer(
    native_path_context, tmp_path, monkeypatch, visual_case
):
    """Real PG/MinIO normal path; synthetic models, no historical Article row mutation."""
    from hashlib import sha256
    from pathlib import Path
    from types import SimpleNamespace

    # Reuse the synthetic adapters without copying them into this integration suite.
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "unit"))

    from app.application.ports.official_account_strict_visual import ObserveVisualMediaEvidence
    from app.application.services.official_account_local import OfficialAccountLocalExecutor
    from app.application.services.wechat_official_account_draft import (
        WeChatDraftLocalSource,
        WeChatOfficialAccountDraftPreparer,
    )
    from app.core.errors import ProviderUnavailableError
    from app.domain.official_account_visual_pipeline import OBSERVE_VISUAL_PIPELINE_VERSION
    from app.domain.official_account_weekly_edition import WeeklyArticleRole
    from app.infrastructure.db.models import MaterialPackageModel, WeComDeliveryJobModel
    from app.infrastructure.db.official_account_strict_visual import _stored
    from app.infrastructure.official_account_local import (
        LocalOfficialAccountDraftAdapter,
        LocalOfficialAccountMediaAdapter,
        fixture_source_snapshot,
    )
    from app.infrastructure.official_account_media import OfficialAccountLocalMediaResolver
    from app.infrastructure.official_account_runtime import official_account_identity_from_settings
    from app.infrastructure.storage.minio_image_store import MinioImageStore
    from app.infrastructure.wechat_official_account.prepared_artifacts import (
        PreparedWeeklyDraftArtifactOwner,
    )
    from test_official_account_strict_visual_policy import _settings
    from test_official_account_strict_visual_worker import (
        _Auditor,
        _Generator,
        _TextAuditor,
        _TextGenerator,
    )
    from test_official_account_worker import _ApprovedCatalog

    from .test_wecom_slot_delivery_concurrency import _seed_slot_delivery_lane

    context = native_path_context
    _, job_ids, _, _ = await _seed_slot_delivery_lane(context, target_at=datetime.now(UTC))
    fixture_source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    async with context.session_factory() as session:
        job = await session.get(WeComDeliveryJobModel, job_ids[0])
        package = await session.get(MaterialPackageModel, job.material_package_id)
        package.topic_snapshot = {
            "title": fixture_source.topic_title,
            "summary": fixture_source.topic_summary,
        }
        package.copy_snapshot = {"copywriting": fixture_source.existing_copy}
        package.source_snapshot = [
            {
                "evidence_binding_id": str(item.evidence_id),
                "source_url": item.source_url,
                "source_tier": item.source_tier,
                "exact_quote": item.exact_quote,
            }
            for item in fixture_source.evidence
        ]
        package.brand_snapshot = [
            {
                "brand_chunk_id": str(item.brand_chunk_id),
                "document_title": item.document_title,
                "text": item.text,
                "tone_tags": list(item.tone_tags),
                "safety_tags": list(item.safety_tags),
            }
            for item in fixture_source.brand_context
        ]
        package_id = package.id
        await session.commit()
    settings = _settings()
    if visual_case != "strict":
        settings = settings.model_copy(
            update={
                "official_account_local_visual_pipeline_version": OBSERVE_VISUAL_PIPELINE_VERSION,
            }
        )
    identity = official_account_identity_from_settings(settings, provider="zhipu", model="glm-5.2")
    repository = PostgresOfficialAccountRepository(context.session_factory)
    run, created = await repository.enqueue_material_package(
        material_package_id=package_id, identity=identity
    )
    assert created
    assert (
        await repository.enqueue_material_package(material_package_id=package_id, identity=identity)
    )[0].id == run.id
    proxy = SimpleNamespace(generated={}, audits={})
    claims = []
    original_claim = repository.claim

    async def capture_claim(**kwargs):
        claimed = await original_claim(**kwargs)
        if claimed is not None:
            claims.append(claimed)
        return claimed

    monkeypatch.setattr(repository, "claim", capture_claim)

    class Generator(_Generator):
        async def generate(self, request):
            async with context.session_factory() as session:
                rows = (
                    await session.scalars(
                        select(OfficialAccountGeneratedVisualModel).where(
                            OfficialAccountGeneratedVisualModel.run_id == request.run_id
                        )
                    )
                ).all()
                self.repository.generated = {row.ordinal: row for row in rows}
                assert any(
                    row.status == "generating"
                    and row.request_fingerprint == request.request_fingerprint
                    for row in rows
                )
            result = await super().generate(request)
            if visual_case == "observe_exact_echo" and len(self.calls) == 3:
                return replace(result, image_bytes=request.references[0].image_bytes)
            if visual_case == "observe_perceptual":
                from io import BytesIO

                from PIL import Image

                output = BytesIO()
                Image.new("RGB", (1536, 1024), (len(self.calls) * 40, 20, 30)).save(output, "JPEG")
                return replace(result, image_bytes=output.getvalue())
            return result

    class Auditor(_Auditor):
        async def audit(self, request):
            async with context.session_factory() as session:
                rows = (
                    await session.scalars(
                        select(OfficialAccountGeneratedVisualModel).where(
                            OfficialAccountGeneratedVisualModel.run_id == run.id
                        )
                    )
                ).all()
                self.repository.generated = {row.ordinal: row for row in rows}
                audit_rows = (
                    await session.scalars(
                        select(OfficialAccountStrictVisualAuditModel).where(
                            OfficialAccountStrictVisualAuditModel.run_id == run.id
                        )
                    )
                ).all()
                self.repository.audits = {
                    (row.role, row.ordinal): _stored(row) for row in audit_rows
                }
            result = await super().audit(request)
            if visual_case == "observe_orphan" and len(self.calls) == 3:
                raise asyncio.CancelledError()
            if visual_case == "observe_mixed":
                if len(self.calls) == 2:
                    return replace(result, accepted=False)
                if len(self.calls) == 3:
                    raise ProviderUnavailableError()
                if len(self.calls) == 4:
                    raise TimeoutError("synthetic unknown audit")
            return result

    catalog = _ApprovedCatalog()
    catalog.candidates = catalog.candidates[:3]
    store = MinioImageStore(context.settings)
    generator, auditor = Generator(proxy), Auditor(proxy)
    executor = OfficialAccountLocalExecutor(
        repository=repository,
        fixture_generator=_TextGenerator(),
        fixture_auditor=_TextAuditor(),
        live_generator=_TextGenerator(),
        live_auditor=_TextAuditor(),
        media_adapter=LocalOfficialAccountMediaAdapter(catalog),
        draft_adapter=LocalOfficialAccountDraftAdapter(),
        lease_seconds=600,
        heartbeat_seconds=30,
        max_attempts=3,
        retry_base_seconds=0,
        generation_max_output_tokens=8192,
        audit_max_output_tokens=1024,
        catalog_media_provider=catalog,
        generated_visual_store=store,
        strict_image_generator=generator,
        strict_image_quality_auditor=auditor,
    )
    if visual_case == "observe_orphan":
        with pytest.raises(asyncio.CancelledError):
            await executor.execute_next("normal-observe-interrupted")
        assert len(generator.calls) == 5 and len(auditor.calls) == 3
        assert (await repository.get_run(run.id)).status == "running"
        async with context.session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountStrictVisualAuditModel).where(
                    OfficialAccountStrictVisualAuditModel.run_id == run.id,
                    OfficialAccountStrictVisualAuditModel.role == "body",
                    OfficialAccountStrictVisualAuditModel.ordinal == 2,
                )
            )
            orphan = _stored(row)
            assert orphan.status == "calling" and orphan.record_fingerprint is None
            await session.execute(
                update(OfficialAccountArticleRunModel)
                .where(OfficialAccountArticleRunModel.id == run.id)
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()
        assert (
            await repository.complete_strict_visual_audit(
                claimed=claims[0],
                subject=orphan.subject,
                status="rejected",
                issue_codes=("strict_visual_audit_rejected",),
            )
            is None
        )
    assert await executor.execute_next("normal-strict-pg")
    completed = await repository.get_run(run.id)
    if visual_case == "observe_exact_echo":
        assert completed.status == "failed"
        assert completed.error_code == "strict_visual_catalog_exact_reuse"
        assert len(generator.calls) == 3 and not auditor.calls
        retained = tuple(
            [
                await repository.get_generated_visual(run_id=run.id, ordinal=index)
                for index in range(3)
            ]
        )
        assert [item.status for item in retained] == ["ready", "ready", "failed"]
        assert retained[2].error_code == "strict_visual_catalog_exact_reuse"
        for item in retained[:2]:
            body = await store.get_content_addressed_bytes(
                media_type=item.media_type, byte_size=item.byte_size, sha256=item.sha256
            )
            assert sha256(body).hexdigest() == item.sha256
        assert await executor.execute_next("known-exact-echo-no-replay") is False
        assert len(generator.calls) == 3 and not auditor.calls
        return
    assert completed.status == "ready", completed.error_code
    assert len(generator.calls) == 5 and len(auditor.calls) == 6
    proofs = await repository.load_strict_visual_evidence(run.id)
    assert len(proofs) == 6
    owner = PreparedWeeklyDraftArtifactOwner(
        session_factory=context.session_factory,
        resolver=OfficialAccountLocalMediaResolver(image_asset_manifest=None, image_store=store),
        work_root=tmp_path / "strict-work",
        inbox_root=tmp_path / "strict-inbox",
        max_image_bytes=10 * 1024 * 1024,
    )
    artifact = await owner.build_child(run_id=run.id, role=WeeklyArticleRole.APPLICATION_CASE)
    child = next((tmp_path / "strict-work" / "children").glob("wechat-draft-prepared-child-*"))
    prepared = WeChatOfficialAccountDraftPreparer(max_image_bytes=10 * 1024 * 1024).prepare(
        WeChatDraftLocalSource(directory=child, role="application_case")
    )
    assert prepared.visual_pipeline_version == identity.visual_pipeline_version
    if visual_case != "strict":
        assert all(isinstance(item, ObserveVisualMediaEvidence) for item in proofs)
    if visual_case == "observe_mixed":
        assert [item.audit_status for item in proofs] == [
            "accepted",
            "rejected",
            "unavailable",
            "result_unknown",
            "accepted",
            "accepted",
        ]
    if visual_case == "observe_orphan":
        assert [item.audit_status for item in proofs] == [
            "accepted",
            "accepted",
            "result_unknown",
            "accepted",
            "accepted",
            "accepted",
        ]
        assert proofs[2].audit_issue_codes == ("strict_visual_orphaned_call",)
        assert claims[1].attempt_number == claims[0].attempt_number + 1
        assert claims[1].lease_token != claims[0].lease_token
        assert len({item.request_fingerprint for item in auditor.calls}) == 6
        assert (
            await repository.complete_strict_visual_audit(
                claimed=claims[0],
                subject=orphan.subject,
                status="rejected",
                issue_codes=("strict_visual_audit_rejected",),
            )
            is None
        )
    if visual_case == "observe_perceptual":
        assert all(
            "strict_visual_perceptual_repetition" in item.quality_issue_codes
            for item in proofs[1:5]
        )
    assert sha256(prepared.cover.body).hexdigest() == proofs[-1].upload_sha256
    assert (
        await owner.build_child(run_id=run.id, role=WeeklyArticleRole.APPLICATION_CASE) == artifact
    )
    assert await executor.execute_next("normal-strict-repeat") is False
    assert len(generator.calls) == 5 and len(auditor.calls) == 6
