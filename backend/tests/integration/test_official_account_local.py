from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in the boundary assertion.
import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from alembic import command
from alembic.config import Config
from app.api_main import app
from app.application.ports.image_validation import (
    IMAGE_QUALITY_AUDIT_PROMPT_VERSION,
    IMAGE_QUALITY_AUDITOR_VERSION,
)
from app.application.ports.official_account_local import (
    OfficialAccountArticleGenerator,
    OfficialAccountGeneratedVisualEvalResult,
    OfficialAccountGeneratedVisualPlan,
    OfficialAccountGeneratedVisualResult,
    OfficialAccountGenerationRequest,
    OfficialAccountMediaAdapter,
    OfficialAccountMediaRequest,
    OfficialAccountMediaResult,
    OfficialAccountSourceMedia,
    OfficialAccountVersionIdentity,
)
from app.application.services.official_account_local import (
    OfficialAccountLocalExecutor,
    generated_visual_eval_request_fingerprint,
)
from app.core.errors import AppError, ConflictError, LocalDraftResultUnknownError
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V2
from app.domain.image_quality_eval import (
    IMAGE_EVAL_DECISION_POLICY_VERSION,
    IMAGE_EVAL_RUBRIC_VERSION,
    IMAGE_EVAL_SINGLE_IMAGE_DIMENSIONS,
    ImageEvalDecisionKind,
    ImageEvalEvaluatorKind,
    ImageEvalObservationStatus,
    active_image_eval_rubric,
    build_image_eval_observation,
    decide_image_eval_batch,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
    OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION,
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V1_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
    OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V1_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_VERSION,
    OFFICIAL_ACCOUNT_RULE_V1_VERSION,
    OFFICIAL_ACCOUNT_RULE_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V1_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
    OFFICIAL_ACCOUNT_STYLE_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V1_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleAttemptModel,
    OfficialAccountArticleRunModel,
    OfficialAccountGeneratedVisualEvalModel,
    OfficialAccountLocalMediaModel,
)
from app.infrastructure.db.official_account_local import (
    PostgresOfficialAccountRepository,
    _adapter_v7_staging_attempt_ordinal,
    _add_workflow_attempt,
)
from app.infrastructure.official_account_local import (
    DeterministicFakeOfficialAccountArticleAuditor,
    DeterministicFakeOfficialAccountArticleGenerator,
    LocalOfficialAccountDraftAdapter,
    LocalOfficialAccountMediaAdapter,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from .conftest import IntegrationContext


def _identity(*, suffix: str = "v1") -> OfficialAccountVersionIdentity:
    # Exact historical version identifiers must stay closed; vary only a reader-visible
    # input when a test intentionally creates an independent run in the shared database.
    default_author = "赛先生" if suffix == "v1" else f"赛先生·{suffix}"
    return OfficialAccountVersionIdentity(
        provider="fake",
        model="official-account-fixture-v1",
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V1_VERSION,
        article_schema_version="official-account-article-schema-v1",
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION,
        audit_schema_version=OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_V1_VERSION,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V1_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V1_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V1_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
        default_author=default_author,
        min_characters=1_200 + len(suffix),
        target_min_characters=1_800,
        target_max_characters=2_600,
        max_characters=4_000,
    )


def _v7_identity(*, suffix: str = "v7") -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider="fake",
        model="official-account-fixture-v1",
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION,
        audit_schema_version=OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_VERSION,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
        visual_query_version=OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
        visual_selector_version=OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
        default_author="赛先生" if suffix == "v7" else f"赛先生·{suffix}",
        min_characters=1_200 + len(suffix),
        target_min_characters=1_800,
        target_max_characters=2_600,
        max_characters=4_000,
    )


def _v8_identity(*, suffix: str = "v8") -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider="fake",
        model="official-account-fixture-v1",
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
        audit_schema_version=OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_VERSION,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
        visual_query_version=OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
        visual_selector_version=OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
        default_author="赛先生" if suffix == "v8" else f"赛先生·{suffix}",
        min_characters=1_200 + len(suffix),
        target_min_characters=1_800,
        target_max_characters=2_600,
        max_characters=4_000,
    )


def _v10_identity(*, suffix: str = "v10") -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider="fake",
        model="official-account-fixture-v1",
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
        audit_schema_version=OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_VERSION,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
        visual_query_version=OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
        visual_selector_version=OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
        context_media_plan_version=OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
        default_author="赛先生" if suffix == "v10" else f"赛先生·{suffix}",
        min_characters=1_200 + len(suffix),
        target_min_characters=1_800,
        target_max_characters=2_600,
        max_characters=4_000,
    )


def _executor(
    repository: PostgresOfficialAccountRepository,
    *,
    draft_adapter: LocalOfficialAccountDraftAdapter | None = None,
    generator: OfficialAccountArticleGenerator | None = None,
    media_adapter: OfficialAccountMediaAdapter | None = None,
) -> OfficialAccountLocalExecutor:
    return OfficialAccountLocalExecutor(
        repository=repository,
        fixture_generator=generator or DeterministicFakeOfficialAccountArticleGenerator(),
        fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        live_generator=None,
        live_auditor=None,
        media_adapter=media_adapter or LocalOfficialAccountMediaAdapter(),
        draft_adapter=draft_adapter or LocalOfficialAccountDraftAdapter(),
        lease_seconds=60,
        heartbeat_seconds=10,
        max_attempts=3,
        retry_base_seconds=0,
        generation_max_output_tokens=8_192,
        audit_max_output_tokens=1_024,
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_fixture_enqueue_is_concurrent_idempotent_and_pipeline_is_durable(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    results = await asyncio.gather(
        *(repository.enqueue_fixture(identity=_identity()) for _ in range(6))
    )

    run_ids = {run.id for run, _created in results}
    assert len(run_ids) == 1
    assert sum(created for _run, created in results) == 1
    run_id = run_ids.pop()

    assert await _executor(repository).execute_next("fixture-worker") is True
    run = await repository.get_run(run_id)
    assert run.status == "ready"
    assert run.current_stage == "ready"
    assert run.provider == "fake"
    assert run.model == "official-account-fixture-v1"
    assert run.active_article_version_id is not None
    assert run.active_render_version_id is not None
    assert run.active_draft_id is not None

    article = await repository.get_article(run_id)
    render = await repository.get_render(run_id)
    body = await repository.get_media(run_id, "body")
    cover = await repository.get_media(run_id, "cover")
    draft = await repository.get_draft(run_id)
    assert article is not None and article.audit is not None and article.audit.accepted
    assert render is not None
    assert body is not None and cover is not None
    assert body[0] != cover[0]
    assert body[1].local_media_id != cover[1].local_media_id
    assert body[1].sha256 != cover[1].sha256
    assert body[1].byte_size != cover[1].byte_size
    assert draft is not None and draft.simulation is True
    assert "official-account-media-slot:body:0" not in draft.resolved_html
    assert await _executor(repository).execute_next("fixture-worker") is False


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_manual_review_ready_gate_concurrent_replay_and_final_conflict(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    run, created = await repository.enqueue_fixture(identity=_identity(suffix="review-gate-v1"))
    assert created is True

    with pytest.raises(ConflictError, match="ready local draft"):
        await repository.record_manual_review(
            run_id=run.id,
            decision="approved",
            reviewer_label="审稿人",
            note="完成核对。",
        )

    assert await _executor(repository).execute_next("manual-review-worker") is True
    results = await asyncio.gather(
        *(
            repository.record_manual_review(
                run_id=run.id,
                decision="approved",
                reviewer_label="审稿人",
                note="完成核对。",
            )
            for _ in range(4)
        )
    )
    assert len({review.id for review, _created in results}) == 1
    assert sum(created for _review, created in results) == 1
    assert len({review.request_fingerprint for review, _created in results}) == 1

    with pytest.raises(ConflictError, match="final and cannot be changed"):
        await repository.record_manual_review(
            run_id=run.id,
            decision="rejected",
            reviewer_label="审稿人",
            note="冲突决定。",
        )
    stored = await repository.get_manual_review(run.id)
    assert stored is not None
    assert stored.decision == "approved"
    assert stored.note == "完成核对。"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_expired_lease_is_reclaimed_and_stale_worker_is_fenced(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    run, created = await repository.enqueue_fixture(identity=_identity(suffix="lease-v1"))
    assert created is True
    first = await repository.claim(worker_id="worker-a", lease_seconds=60, max_attempts=3)
    assert first is not None and first.run_id == run.id

    async with integration_context.session_factory() as session:
        stored = await session.scalar(
            select(OfficialAccountArticleRunModel)
            .where(OfficialAccountArticleRunModel.id == run.id)
            .with_for_update()
        )
        assert stored is not None
        stored.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    second = await repository.claim(worker_id="worker-b", lease_seconds=60, max_attempts=3)
    assert second is not None
    assert second.run_id == run.id
    assert second.attempt_number == 2
    assert second.lease_token != first.lease_token
    assert await repository.heartbeat(claimed=first, lease_seconds=60) is False
    assert await repository.heartbeat(claimed=second, lease_seconds=60) is True


class _UnknownDraftAdapter(LocalOfficialAccountDraftAdapter):
    async def create(self, request):
        del request
        raise LocalDraftResultUnknownError()


class _CountingGenerator(DeterministicFakeOfficialAccountArticleGenerator):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def generate(self, request: OfficialAccountGenerationRequest):
        self.calls += 1
        return await super().generate(request)


class _FailBodyOnceMediaAdapter(LocalOfficialAccountMediaAdapter):
    def __init__(self) -> None:
        self.body_calls = 0
        self.cover_calls = 0

    async def stage(self, request: OfficialAccountMediaRequest):
        if request.role == "body":
            self.body_calls += 1
            if self.body_calls == 1:
                raise AppError(
                    "official_account_media_unavailable",
                    "local media staging failed transiently",
                    503,
                    True,
                )
        else:
            self.cover_calls += 1
        return await super().stage(request)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_result_unknown_preserves_artifacts_and_refuses_retry(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    run, created = await repository.enqueue_fixture(identity=_identity(suffix="unknown-v1"))
    assert created is True

    assert (
        await _executor(repository, draft_adapter=_UnknownDraftAdapter()).execute_next(
            "unknown-worker"
        )
        is True
    )
    stored = await repository.get_run(run.id)
    assert stored.status == "result_unknown"
    assert stored.active_article_version_id is not None
    assert stored.active_render_version_id is not None
    assert stored.active_body_media_id is not None
    assert stored.active_cover_media_id is not None
    assert stored.active_draft_id is None
    assert await repository.get_draft(run.id) is None

    with pytest.raises(ConflictError, match="not retryable"):
        await repository.retry(run_id=run.id, max_attempts=3)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_retryable_media_failure_resumes_after_render_without_regeneration(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    run, created = await repository.enqueue_fixture(identity=_identity(suffix="resume-v1"))
    assert created is True
    generator = _CountingGenerator()
    media_adapter = _FailBodyOnceMediaAdapter()
    executor = _executor(
        repository,
        generator=generator,
        media_adapter=media_adapter,
    )

    assert await executor.execute_next("resume-worker") is True
    after_failure = await repository.get_run(run.id)
    assert after_failure.status == "queued"
    assert after_failure.active_article_version_id is not None
    assert after_failure.active_render_version_id is not None
    assert after_failure.active_body_media_id is None

    assert await executor.execute_next("resume-worker") is True
    ready = await repository.get_run(run.id)
    assert ready.status == "ready"
    assert ready.attempt_count == 2
    assert generator.calls == 1
    assert media_adapter.body_calls == 2
    assert media_adapter.cover_calls == 1


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_explicit_retry_reopens_confirmed_retryable_failure(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    run, created = await repository.enqueue_fixture(identity=_identity(suffix="manual-retry-v1"))
    assert created is True
    claimed = await repository.claim(
        worker_id="manual-retry-worker",
        lease_seconds=60,
        max_attempts=1,
    )
    assert claimed is not None and claimed.run_id == run.id
    assert await repository.fail(
        claimed=claimed,
        error_code="official_account_provider_unavailable",
        retryable=True,
        retry_base_seconds=0,
        max_attempts=1,
    )
    failed = await repository.get_run(run.id)
    assert failed.status == "failed"
    assert failed.error_retryable is True

    reopened = await repository.retry(run_id=run.id, max_attempts=1)
    assert reopened.status == "queued"
    assert await _executor(repository).execute_next("manual-retry-worker") is True
    ready = await repository.get_run(run.id)
    assert ready.status == "ready"
    assert ready.attempt_count == 2


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_adapter_v7_body_context_and_failure_attempt_namespaces_do_not_collide(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    run, created = await repository.enqueue_fixture(
        identity=_v10_identity(suffix="attempt-namespace-v10")
    )
    assert created is True
    claimed = await repository.claim(
        worker_id="attempt-namespace-worker",
        lease_seconds=60,
        max_attempts=1,
    )
    assert claimed is not None and claimed.run_id == run.id
    body_ordinal = _adapter_v7_staging_attempt_ordinal(
        attempt_number=claimed.attempt_number,
        role="body",
        ordinal=0,
    )
    context_ordinal = _adapter_v7_staging_attempt_ordinal(
        attempt_number=claimed.attempt_number,
        role="context",
        ordinal=0,
    )
    failure_ordinal = _adapter_v7_staging_attempt_ordinal(
        attempt_number=claimed.attempt_number,
        role="failure",
    )
    assert len({body_ordinal, context_ordinal, failure_ordinal}) == 3

    async with integration_context.session_factory() as session:
        stored_run = await session.get(OfficialAccountArticleRunModel, run.id)
        assert stored_run is not None
        stored_run.current_stage = "staging_body_media"
        _add_workflow_attempt(
            session,
            claimed=claimed,
            stage="staging_body_media",
            request_fingerprint="a" * 64,
            ordinal=body_ordinal,
            safe_metadata={"role": "body", "ordinal": 0},
        )
        _add_workflow_attempt(
            session,
            claimed=claimed,
            stage="staging_body_media",
            request_fingerprint="b" * 64,
            ordinal=context_ordinal,
            safe_metadata={"role": "context", "ordinal": 0},
        )
        await session.commit()

    assert await repository.fail(
        claimed=claimed,
        error_code="official_account_media_stage_failed",
        retryable=False,
        retry_base_seconds=0,
        max_attempts=1,
    )
    async with integration_context.session_factory() as session:
        attempts = tuple(
            await session.scalars(
                select(OfficialAccountArticleAttemptModel)
                .where(
                    OfficialAccountArticleAttemptModel.run_id == run.id,
                    OfficialAccountArticleAttemptModel.stage == "staging_body_media",
                )
                .order_by(OfficialAccountArticleAttemptModel.ordinal)
            )
        )

    assert tuple(item.ordinal for item in attempts) == (
        body_ordinal,
        context_ordinal,
        failure_ordinal,
    )
    assert tuple(item.safe_metadata.get("role") for item in attempts[:2]) == (
        "body",
        "context",
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_editorial_review_migration_refuses_lossy_downgrade(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    run, created = await repository.enqueue_fixture(
        identity=_identity(suffix="downgrade-review-v1")
    )
    assert created is True
    assert await _executor(repository).execute_next("downgrade-review-worker") is True
    await repository.record_manual_review(
        run_id=run.id,
        decision="rejected",
        reviewer_label="迁移门禁测试",
        note="存在人工决定时不得丢失记录。",
    )

    try:
        with pytest.raises(
            Exception, match="cannot downgrade official-account editorial artifacts"
        ):
            await asyncio.to_thread(
                command.downgrade,
                Config("backend/alembic.ini"),
                "20260822_0027",
            )

        async with integration_context.engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "20260901_0042"
    finally:
        await asyncio.to_thread(command.upgrade, Config("backend/alembic.ini"), "head")

    async with integration_context.engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "20260901_0042"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_local_api_fixture_flow_preview_and_media_are_safe(
    integration_context: IntegrationContext,
) -> None:
    previous_settings = app.state.settings
    previous_factory = app.state.session_factory
    settings = integration_context.settings.model_copy(
        update={
            "official_account_local_enabled": True,
            "ai_provider_mode": "disabled",
            "ai_platform_base_url": None,
            "ai_platform_api_key": None,
        }
    )
    app.state.settings = settings
    app.state.session_factory = integration_context.session_factory
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            capabilities = await client.get("/api/v1/official-account-local/capabilities")
            live_rejected = await client.post(
                "/api/v1/official-account-local/article-runs",
                json={
                    "source": {
                        "kind": "material_package",
                        "material_package_id": "00000000-0000-4000-8000-000000000001",
                    },
                    "generation_mode": "live",
                },
            )
            created = await client.post(
                "/api/v1/official-account-local/article-runs",
                json={
                    "source": {
                        "kind": "fixture",
                        "fixture_id": "official-account-article-v1",
                    },
                    "generation_mode": "fixture",
                },
            )
            replay = await client.post(
                "/api/v1/official-account-local/article-runs",
                json={
                    "source": {
                        "kind": "fixture",
                        "fixture_id": "official-account-article-v1",
                    },
                    "generation_mode": "fixture",
                },
            )

        assert capabilities.status_code == 200
        assert capabilities.json()["fixture_available"] is True
        assert capabilities.json()["live_available"] is False
        assert capabilities.json()["boundary_label"] == "本地模拟，未同步公众号"
        assert live_rejected.status_code == 409
        assert created.status_code == 202
        assert created.headers["location"].endswith(created.json()["id"])
        assert replay.status_code == 202
        assert replay.json()["id"] == created.json()["id"]
        run_id = created.json()["id"]

        repository = PostgresOfficialAccountRepository(integration_context.session_factory)
        assert await _executor(repository).execute_next("api-fixture-worker") is True

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            detail = await client.get(f"/api/v1/official-account-local/article-runs/{run_id}")
            assert detail.status_code == 200
            payload = detail.json()
            assert payload["status"] == "ready"
            assert payload["simulation"] is True
            assert payload["article"]["author"] == "赛先生"
            assert payload["validation"]["passed"] is True
            assert payload["audit"]["accepted"] is True
            assert payload["usage"]["safe_provider_request_id"] is None
            assert {item["role"] for item in payload["media"]} == {"body", "cover"}
            assert len(payload["body_images"]) == 3
            assert [item["ordinal"] for item in payload["body_images"]] == [0, 1, 2]
            assert len({item["sha256"] for item in payload["body_images"]}) == 3
            assert payload["body_image"] == payload["body_images"][0]
            assert payload["media_selection"]["body_image_count"] == 3
            assert payload["media_selection"]["safely_degraded"] is True
            assert payload["media_selection"]["selection_mode"] == "deterministic_fallback"
            assert payload["media_selection"]["semantic_unavailable_reason"] == "disabled"
            assert payload["draft"]["simulation"] is True
            assert payload["manual_review"]["status"] == "pending"
            assert payload["manual_review"]["editorially_approved"] is False
            serialized = str(payload).lower()
            assert "resolved_html" not in serialized
            assert "canonical_html" not in serialized
            assert "object_key" not in serialized
            assert "bucket" not in serialized

            body_media = next(item for item in payload["media"] if item["role"] == "body")
            cover_media = next(item for item in payload["media"] if item["role"] == "cover")
            body_response = await client.get(body_media["media_url"])
            cover_response = await client.get(cover_media["media_url"])
            preview = await client.get(payload["draft"]["preview_url"])
            retry_ready = await client.post(
                f"/api/v1/official-account-local/article-runs/{run_id}/retry"
            )
            approved = await client.post(
                f"/api/v1/official-account-local/article-runs/{run_id}/manual-review",
                json={
                    "decision": "approved",
                    "reviewer_label": "集成测试审稿",
                    "note": "仅验证不可变人工审稿门禁。",
                },
            )
            approval_replay = await client.post(
                f"/api/v1/official-account-local/article-runs/{run_id}/manual-review",
                json={
                    "decision": "approved",
                    "reviewer_label": "集成测试审稿",
                    "note": "仅验证不可变人工审稿门禁。",
                },
            )
            conflicting_review = await client.post(
                f"/api/v1/official-account-local/article-runs/{run_id}/manual-review",
                json={
                    "decision": "rejected",
                    "reviewer_label": "集成测试审稿",
                    "note": "冲突决定不得覆盖。",
                },
            )

        assert body_response.status_code == 200
        assert body_response.headers["content-type"].startswith("image/jpeg")
        assert len(body_response.content) < 500_000
        assert cover_response.status_code == 200
        assert cover_response.headers["content-type"].startswith("image/jpeg")
        assert cover_response.content != body_response.content
        assert preview.status_code == 200
        assert preview.headers["cache-control"] == "private, no-store"
        assert "default-src 'none'" in preview.headers["content-security-policy"]
        assert "<iframe" not in preview.text.lower()
        assert "<script" not in preview.text.lower()
        assert retry_ready.status_code == 409
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        assert approved.json()["editorially_approved"] is True
        assert approved.json()["idempotent_replay"] is False
        assert approval_replay.status_code == 200
        assert (
            approval_replay.json()["request_fingerprint"] == approved.json()["request_fingerprint"]
        )
        assert approval_replay.json()["idempotent_replay"] is True
        assert conflicting_review.status_code == 409
    finally:
        app.state.settings = previous_settings
        app.state.session_factory = previous_factory


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_multimodal_article_migration_refuses_v4_lossy_downgrade(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    run, created = await repository.enqueue_fixture(
        identity=_v7_identity(suffix="downgrade-multimodal-v7")
    )
    assert created is True
    assert await _executor(repository).execute_next("multimodal-downgrade-worker") is True
    stored = await repository.get_article(run.id)
    assert stored is not None
    assert stored.article.media_selection is not None

    try:
        # A newer selected-news v9/v10 artifact or a prior v8 artifact in the shared
        # integration database is an earlier, equally lossless-refusing boundary.  A v7
        # artifact reaches the v4 fence on a clean database; none may permit a destructive
        # downgrade.
        with pytest.raises(
            Exception,
            match=(
                r"cannot downgrade (?:selected-news source-image artifacts|"
                r"official-account (?:structured-output|multimodal))"
            ),
        ):
            await asyncio.to_thread(
                command.downgrade,
                Config("backend/alembic.ini"),
                "20260823_0028",
            )
    finally:
        await asyncio.to_thread(command.upgrade, Config("backend/alembic.ini"), "head")

    async with integration_context.engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "20260901_0042"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_structured_output_article_migration_refuses_v5_lossy_downgrade(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    run, created = await repository.enqueue_fixture(
        identity=_v8_identity(suffix="downgrade-structured-v8")
    )
    assert created is True
    assert await _executor(repository).execute_next("structured-downgrade-worker") is True
    stored = await repository.get_article(run.id)
    assert stored is not None
    assert stored.article.media_selection is not None

    async with integration_context.engine.connect() as connection:
        artifact_version = await connection.scalar(
            text("SELECT version FROM official_account_article_versions WHERE run_id = :run_id"),
            {"run_id": run.id},
        )
    assert artifact_version == 5

    try:
        # Downgrade from the current 0040 head can refuse first when selected-news v9/v10
        # artifacts share the integration database. Both guards preserve the immutable v5 row.
        with pytest.raises(
            Exception,
            match=(
                r"cannot downgrade (?:selected-news source-image artifacts|"
                r"official-account structured-output)"
            ),
        ):
            await asyncio.to_thread(
                command.downgrade,
                Config("backend/alembic.ini"),
                "20260823_0029",
            )
    finally:
        await asyncio.to_thread(command.upgrade, Config("backend/alembic.ini"), "head")

    async with integration_context.engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == "20260901_0042"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_generated_visual_repository_fences_intent_and_ready_media_lineage(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    run, created = await repository.enqueue_fixture(
        identity=_v8_identity(suffix="generated-visual-repository-v1")
    )
    assert created is True

    # Stop after the render is committed so the repository can be exercised under a fresh lease.
    media_adapter = _FailBodyOnceMediaAdapter()
    assert (
        await _executor(repository, media_adapter=media_adapter).execute_next(
            "generated-visual-prime-worker"
        )
        is True
    )
    primed = await repository.get_run(run.id)
    assert primed.status == "queued"
    assert primed.active_article_version_id is not None
    assert primed.active_render_version_id is not None

    claimed = await repository.claim(
        worker_id="generated-visual-repository-worker",
        lease_seconds=60,
        max_attempts=3,
    )
    assert claimed is not None and claimed.run_id == run.id
    article = await repository.get_article(run.id)
    render = await repository.get_render(run.id)
    assert article is not None and render is not None
    output = b"repository-generated-visual"
    output_checksum = sha256(output).hexdigest()
    plan = OfficialAccountGeneratedVisualPlan(
        run_id=run.id,
        article_version_id=article.id,
        render_version_id=render.id,
        ordinal=0,
        section_index=0,
        block_index=0,
        block_kind="paragraph",
        block_fingerprint="2" * 64,
        reference_asset_ref="a" * 16,
        reference_catalog_version="brand-visual-catalog-v1",
        reference_source_checksum="b" * 64,
        reference_publication_checksum="c" * 64,
        reference_input_version=IMAGE_REFERENCE_INPUT_V2,
        reference_input_checksum="3" * 64,
        selection_method="deterministic_tag",
        similarity_band=None,
        request_fingerprint="d" * 64,
        plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
        prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
        output_profile_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION,
        provider="fake",
        model="gpt-image-2",
    )
    intent = await repository.create_generated_visual_intent(claimed=claimed, plan=plan)
    assert intent is not None and intent.status == "generating"
    replay = await repository.create_generated_visual_intent(claimed=claimed, plan=plan)
    assert replay == intent
    with pytest.raises(RuntimeError, match="plan changed"):
        await repository.create_generated_visual_intent(
            claimed=claimed,
            plan=replace(plan, request_fingerprint="e" * 64),
        )

    source = OfficialAccountSourceMedia(
        source_image_artifact_id=None,
        fixture_id=None,
        generated_visual_id=intent.id,
        media_type="image/jpeg",
        byte_size=len(output),
        sha256=output_checksum,
        ordinal=0,
        assigned_section_index=0,
        selection_reason_code="stable_fallback",
    )
    staged = OfficialAccountMediaResult(
        local_media_id="local-media-generated-repository-test",
        role="body",
        ordinal=0,
        media_url="/api/v1/official-account-local/media/local-media-generated-repository-test",
        media_type="image/jpeg",
        byte_size=len(output),
        sha256=output_checksum,
    )
    with pytest.raises(RuntimeError, match="generated visual media lineage"):
        await repository.persist_media(
            claimed=claimed,
            render=render,
            source_media=source,
            request_fingerprint="f" * 64,
            result=staged,
        )

    assert plan.reference_input_checksum is not None
    eval_request_fingerprint = generated_visual_eval_request_fingerprint(
        generated_visual_id=intent.id,
        plan_request_fingerprint=plan.request_fingerprint,
        publication_sha256=output_checksum,
        reference_input_checksum=plan.reference_input_checksum,
    )
    observations = tuple(
        build_image_eval_observation(
            observation_id=f"provider-audit:{dimension.value}",
            subject_ref=f"generated-visual:{intent.id}",
            publication_sha256=output_checksum,
            dimension=dimension,
            status=ImageEvalObservationStatus.AVAILABLE,
            evaluator_kind=ImageEvalEvaluatorKind.PROVIDER_AUDIT,
            evaluator_version=IMAGE_QUALITY_AUDITOR_VERSION,
            provider="openai-compatible",
            model="vision-model",
            request_fingerprint=eval_request_fingerprint,
        )
        for dimension in IMAGE_EVAL_SINGLE_IMAGE_DIMENSIONS
    )
    eval_result = OfficialAccountGeneratedVisualEvalResult(
        publication_sha256=output_checksum,
        evaluator_version=IMAGE_QUALITY_AUDITOR_VERSION,
        audit_prompt_version=IMAGE_QUALITY_AUDIT_PROMPT_VERSION,
        rubric_version=IMAGE_EVAL_RUBRIC_VERSION,
        decision_policy_version=IMAGE_EVAL_DECISION_POLICY_VERSION,
        request_fingerprint=eval_request_fingerprint,
        observations=observations,
        decision=decide_image_eval_batch(observations, active_image_eval_rubric()),
        provider="openai-compatible",
        model="vision-model",
    )

    mismatched_observations = tuple(
        observation.model_copy(update={"request_fingerprint": "9" * 64})
        for observation in observations
    )
    mismatched_eval = replace(
        eval_result,
        request_fingerprint="9" * 64,
        observations=mismatched_observations,
        decision=decide_image_eval_batch(mismatched_observations, active_image_eval_rubric()),
    )
    with pytest.raises(ValueError, match="request fingerprint changed"):
        await repository.persist_generated_visual(
            claimed=claimed,
            plan=plan,
            result=OfficialAccountGeneratedVisualResult(
                media_type="image/jpeg",
                byte_size=len(output),
                sha256=output_checksum,
                width=1536,
                height=1024,
            ),
            eval_result=mismatched_eval,
        )

    ready = await repository.persist_generated_visual(
        claimed=claimed,
        plan=plan,
        result=OfficialAccountGeneratedVisualResult(
            media_type="image/jpeg",
            byte_size=len(output),
            sha256=output_checksum,
            width=1536,
            height=1024,
        ),
        eval_result=eval_result,
    )
    assert ready is not None and ready.status == "ready"
    stored_evals = await repository.list_generated_visual_evals(run_id=run.id)
    assert len(stored_evals) == 1
    assert stored_evals[0].generated_visual_id == intent.id
    assert stored_evals[0].result == eval_result
    assert stored_evals[0].result.decision.decision is ImageEvalDecisionKind.ACCEPTED
    assert len(stored_evals[0].record_fingerprint) == 64
    persisted = await repository.persist_media(
        claimed=claimed,
        render=render,
        source_media=source,
        request_fingerprint="f" * 64,
        result=staged,
    )
    assert persisted is not None
    async with integration_context.session_factory() as session:
        media_row = await session.scalar(
            select(OfficialAccountLocalMediaModel).where(
                OfficialAccountLocalMediaModel.id == persisted[0]
            )
        )
        assert media_row is not None
        assert media_row.generated_visual_id == intent.id
        assert media_row.source_image_artifact_id is None
        assert media_row.fixture_id is None
        assert media_row.descriptor["source_kind"] == "generated_visual"

        await session.execute(
            OfficialAccountGeneratedVisualEvalModel.__table__.delete().where(
                OfficialAccountGeneratedVisualEvalModel.run_id == run.id
            )
        )
        await session.commit()

    unknown_plan = replace(
        plan,
        ordinal=1,
        section_index=1,
        request_fingerprint="1" * 64,
    )
    unknown_intent = await repository.create_generated_visual_intent(
        claimed=claimed,
        plan=unknown_plan,
    )
    assert unknown_intent is not None and unknown_intent.status == "generating"
    assert await repository.fail_generated_visual(
        claimed=claimed,
        plan=unknown_plan,
        error_code="official_account_generated_visual_result_unknown",
        result_unknown=True,
    )
    recovered = await repository.get_generated_visual(run_id=run.id, ordinal=1)
    assert recovered is not None
    assert recovered.status == "result_unknown"
    assert recovered.error_code == "official_account_generated_visual_result_unknown"
