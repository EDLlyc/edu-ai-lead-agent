"""PostgreSQL reader for the read-only operations tools.

Every query runs in a READ ONLY transaction that is rolled back, selects named columns only
(never a WeCom recipient), and is bounded by LIMIT. The connecting role is expected to hold
SELECT on the tables in OPS_READ_TABLES and nothing else; `verify_read_only_role` refuses to
serve with a role that can write.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.application.services.ops_tools import (
    CopyIssueItem,
    CopyRunDetail,
    CopyRunItem,
    CopyRunsResult,
    DayTraceResult,
    DeliveriesResult,
    DeliveryItem,
    DraftItem,
    PostTrace,
    SlotRunItem,
    SlotRunsResult,
    StageSpan,
    UsageRow,
)
from app.core.errors import NotFoundError
from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotSelectionModel,
    CopyAuditModel,
    CopyDraftClaimModel,
    CopyDraftVersionModel,
    CopyGenerationAttemptModel,
    CopyGenerationJobModel,
    CopyGenerationRunModel,
    CopyIssueModel,
    EventClusterVersionModel,
    ImageArtifactModel,
    ModelInvocationModel,
    NewsInfographicJobModel,
    TopicRerankRecordModel,
    WeComDeliveryAttemptModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
)
from app.schemas.copy_generation import extract_headline_hook

# Tables the ops role may read: the four ops tools plus the copy repair workspace loader.
# WeCom delivery tables are granted column by column in scripts/ops, without recipient_id.
OPS_READ_TABLES = (
    "analysis_facts",
    "article_occurrences",
    "brand_chunks",
    "brand_document_versions",
    "brand_documents",
    "brand_sections",
    "candidate_analyses",
    "content_slot_runs",
    "content_slot_selections",
    "copy_audits",
    "copy_claim_brand_bindings",
    "copy_claim_evidence_bindings",
    "copy_draft_claims",
    "copy_draft_versions",
    "copy_generation_attempts",
    "copy_generation_jobs",
    "copy_generation_runs",
    "copy_issues",
    "daily_topic_selections",
    "event_cluster_versions",
    "event_memberships",
    "evidence_bindings",
    "model_invocations",
    "normalized_articles",
    "topic_selection_runs",
)
_SLOT_ORDER = {"morning": 0, "noon": 1, "evening": 2}


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def ops_database_url(environ: Mapping[str, str]) -> str:
    url = environ.get("OPS_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("OPS_DATABASE_URL is required (a read-only role; see scripts/ops)")
    if not url.startswith("postgresql+asyncpg://"):
        raise RuntimeError("OPS_DATABASE_URL must use the postgresql+asyncpg driver")
    return url


def create_ops_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"server_settings": {"application_name": "edu-ai-ops-mcp"}},
    )


async def verify_read_only_role(engine: AsyncEngine) -> str:
    """Fail closed unless the connected role is a non-superuser that cannot write any table."""

    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT current_user, r.rolsuper, r.rolcreaterole, r.rolcreatedb, "
                    "r.rolbypassrls, "
                    "EXISTS (SELECT 1 FROM information_schema.table_privileges p "
                    "        WHERE p.grantee = current_user "
                    "        AND p.privilege_type IN "
                    "            ('INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER')), "
                    "has_database_privilege(current_database(), 'CREATE') "
                    "OR has_database_privilege(current_database(), 'TEMP'), "
                    "has_schema_privilege('public', 'CREATE') "
                    "FROM pg_roles r WHERE r.rolname = current_user"
                )
            )
        ).one()
        await connection.rollback()
    user, superuser, create_role, create_db, bypass_rls, writes, db_create, schema_create = row
    if superuser or create_role or create_db or bypass_rls or writes or db_create:
        raise RuntimeError("the ops database role must be read-only; refusing to serve")
    if schema_create:
        raise RuntimeError("the ops database role can create tables; refusing to serve")
    return str(user)


class PostgresOpsReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def _read(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            try:
                yield session
            finally:
                await session.rollback()

    async def list_slot_runs(self, business_date: date) -> SlotRunsResult:
        async with self._read() as session:
            rows = (
                await session.scalars(
                    select(ContentSlotRunModel)
                    .where(ContentSlotRunModel.business_date == business_date)
                    .order_by(ContentSlotRunModel.target_at, ContentSlotRunModel.created_at)
                    .limit(12)
                )
            ).all()
            return SlotRunsResult(
                runs=tuple(
                    SlotRunItem(
                        content_slot=row.content_slot,
                        status=row.status,
                        target_at=row.target_at,
                        total_scores=row.total_scores,
                        eligible_scores=row.eligible_scores,
                        selected_count=row.selected_count,
                        unfilled_count=row.unfilled_count,
                        unfilled_reason_codes=tuple(row.unfilled_reason_codes or ())[:12],
                        error_code=row.error_code,
                    )
                    for row in rows
                )
            )

    async def list_copy_runs(self, business_date: date, limit: int) -> CopyRunsResult:
        run = CopyGenerationRunModel
        selection = ContentSlotSelectionModel
        version = EventClusterVersionModel
        slot_order = case(_SLOT_ORDER, value=selection.content_slot, else_=len(_SLOT_ORDER))
        statement = (
            select(
                run.id,
                selection.content_slot,
                selection.ordinal,
                version.representative_title,
                run.status,
                run.decision_kind,
                run.repair_count,
                run.error_code,
                run.version_bundle,
                run.created_at,
                run.completed_at,
            )
            .outerjoin(selection, run.content_slot_selection_id == selection.id)
            .outerjoin(version, run.selected_event_version_id == version.id)
            .where(run.business_date == business_date)
            .order_by(slot_order, selection.ordinal, run.created_at)
            .limit(min(limit, 30))
        )
        async with self._read() as session:
            rows = (await session.execute(statement)).all()
        return CopyRunsResult(
            runs=tuple(
                CopyRunItem(
                    run_id=row.id,
                    content_slot=row.content_slot,
                    ordinal=row.ordinal,
                    title=_clip(row.representative_title, 120),
                    status=row.status,
                    decision_kind=row.decision_kind,
                    repair_count=row.repair_count,
                    error_code=row.error_code,
                    generator_prompt_version=_bundle_text(row.version_bundle, "generator"),
                    auditor_prompt_version=_bundle_text(row.version_bundle, "auditor"),
                    created_at=row.created_at,
                    completed_at=row.completed_at,
                )
                for row in rows
            )
        )

    async def get_copy_run(self, run_id: UUID) -> CopyRunDetail:
        async with self._read() as session:
            run = await session.get(CopyGenerationRunModel, run_id)
            if run is None:
                raise NotFoundError("copy generation run")
            title = None
            if run.selected_event_version_id is not None:
                title = await session.scalar(
                    select(EventClusterVersionModel.representative_title).where(
                        EventClusterVersionModel.id == run.selected_event_version_id
                    )
                )
            job = (
                await session.scalars(
                    select(CopyGenerationJobModel)
                    .where(CopyGenerationJobModel.run_id == run_id)
                    .order_by(CopyGenerationJobModel.created_at.desc())
                    .limit(1)
                )
            ).first()
            versions = (
                await session.scalars(
                    select(CopyDraftVersionModel)
                    .where(CopyDraftVersionModel.run_id == run_id)
                    .order_by(CopyDraftVersionModel.version)
                    .limit(4)
                )
            ).all()
            drafts: list[DraftItem] = []
            for draft in versions:
                claim_count = await session.scalar(
                    select(func.count())
                    .select_from(CopyDraftClaimModel)
                    .where(CopyDraftClaimModel.draft_version_id == draft.id)
                )
                audit = (
                    await session.scalars(
                        select(CopyAuditModel)
                        .where(CopyAuditModel.draft_version_id == draft.id)
                        .order_by(CopyAuditModel.created_at.desc())
                        .limit(1)
                    )
                ).first()
                issues = (
                    await session.scalars(
                        select(CopyIssueModel)
                        .where(CopyIssueModel.draft_version_id == draft.id)
                        .order_by(CopyIssueModel.stage, CopyIssueModel.ordinal)
                        .limit(16)
                    )
                ).all()
                drafts.append(
                    DraftItem(
                        version=draft.version,
                        created_at=draft.created_at,
                        hook=_clip(extract_headline_hook(draft.copywriting, title=title or ""), 200)
                        or "",
                        claim_count=int(claim_count or 0),
                        audit_accepted=audit.accepted if audit is not None else None,
                        audit_prompt_version=audit.prompt_version if audit is not None else None,
                        issues=tuple(
                            CopyIssueItem(
                                stage=issue.stage,
                                code=issue.code,
                                severity=issue.severity,
                                claim_key=issue.claim_key,
                                message=_clip(issue.safe_message, 240) or "",
                            )
                            for issue in issues
                        ),
                    )
                )
            return CopyRunDetail(
                run_id=run.id,
                title=_clip(title, 120),
                status=run.status,
                error_code=run.error_code,
                repair_count=run.repair_count,
                job_status=job.status if job is not None else None,
                job_attempts=job.attempt_count if job is not None else None,
                job_error_code=job.error_code if job is not None else None,
                drafts=tuple(drafts),
            )

    async def list_deliveries(self, business_date: date) -> DeliveriesResult:
        job = WeComDeliveryJobModel
        window = WeComDeliveryWindowModel
        slot_order = case(_SLOT_ORDER, value=window.content_slot, else_=len(_SLOT_ORDER))
        # Named columns only: the recipient columns are not granted to the ops role.
        statement = (
            select(
                window.content_slot,
                job.sequence_ordinal,
                job.status,
                job.text_status,
                job.image_status,
                job.attempt_count,
                job.last_error_code,
                job.not_before,
                job.completed_at,
            )
            .join(window, job.delivery_window_id == window.id)
            .where(window.business_date == business_date)
            .order_by(slot_order, job.sequence_ordinal, job.created_at)
            .limit(40)
        )
        async with self._read() as session:
            rows = (await session.execute(statement)).all()
        return DeliveriesResult(
            deliveries=tuple(
                DeliveryItem(
                    content_slot=row.content_slot,
                    sequence_ordinal=row.sequence_ordinal,
                    status=row.status,
                    text_status=row.text_status,
                    image_status=row.image_status,
                    attempt_count=row.attempt_count,
                    last_error_code=row.last_error_code,
                    not_before=row.not_before,
                    completed_at=row.completed_at,
                )
                for row in rows
            )
        )

    async def get_day_trace(self, business_date: date) -> DayTraceResult:
        selection, slot_run = ContentSlotSelectionModel, ContentSlotRunModel
        version, run = EventClusterVersionModel, CopyGenerationRunModel
        attempt, job, draft = (
            CopyGenerationAttemptModel,
            CopyGenerationJobModel,
            CopyDraftVersionModel,
        )
        rerank, image, infographic = (
            TopicRerankRecordModel,
            ImageArtifactModel,
            NewsInfographicJobModel,
        )
        delivery, delivery_attempt = WeComDeliveryJobModel, WeComDeliveryAttemptModel
        slot_order = case(_SLOT_ORDER, value=selection.content_slot, else_=len(_SLOT_ORDER))
        day_start = datetime.combine(business_date, time(), _BUSINESS_TZ)
        async with self._read() as session:
            posts = (
                await session.execute(
                    select(
                        selection.id,
                        selection.content_slot,
                        selection.ordinal,
                        selection.run_id,
                        version.representative_title,
                        slot_run.preparation_at,
                        slot_run.target_at,
                    )
                    .join(slot_run, slot_run.id == selection.run_id)
                    .outerjoin(version, version.id == selection.selected_event_version_id)
                    .where(selection.business_date == business_date)
                    .order_by(slot_order, selection.ordinal)
                    .limit(12)
                )
            ).all()
            selection_ids = [row.id for row in posts]
            slot_run_ids = list({row.run_id for row in posts})
            copy_runs = (
                await session.execute(
                    select(run.id, run.content_slot_selection_id)
                    .where(run.content_slot_selection_id.in_(selection_ids))
                    .order_by(run.created_at)
                )
            ).all()
            # A selection re-run keeps the newest copy run.
            run_by_selection = {row.content_slot_selection_id: row.id for row in copy_runs}
            run_ids = list(run_by_selection.values())
            attempts = (
                await session.execute(
                    select(
                        job.run_id,
                        attempt.capability,
                        attempt.model,
                        attempt.status,
                        attempt.prompt_tokens,
                        attempt.completion_tokens,
                        attempt.latency_ms,
                        attempt.created_at,
                        attempt.completed_at,
                        draft.version,
                    )
                    .join(job, job.id == attempt.job_id)
                    .outerjoin(draft, draft.id == attempt.draft_version_id)
                    .where(job.run_id.in_(run_ids))
                )
            ).all()
            reranks = (
                await session.execute(
                    select(
                        rerank.content_slot_run_id,
                        rerank.model,
                        rerank.outcome,
                        rerank.prompt_tokens,
                        rerank.completion_tokens,
                        rerank.latency_ms,
                        rerank.created_at,
                    ).where(rerank.content_slot_run_id.in_(slot_run_ids))
                )
            ).all()
            images = (
                await session.execute(
                    select(
                        image.run_id,
                        image.model,
                        image.status,
                        image.attempt_count,
                        image.created_at,
                        image.completed_at,
                    ).where(image.run_id.in_(run_ids))
                )
            ).all()
            infographics = (
                await session.execute(
                    select(
                        infographic.copy_generation_run_id,
                        infographic.provider,
                        infographic.status,
                        infographic.created_at,
                        infographic.completed_at,
                    ).where(infographic.copy_generation_run_id.in_(run_ids))
                )
            ).all()
            deliveries = (
                await session.execute(
                    select(
                        delivery.id,
                        delivery.content_slot_selection_id,
                        delivery.status,
                        delivery.created_at,
                        delivery.completed_at,
                    ).where(delivery.content_slot_selection_id.in_(selection_ids))
                )
            ).all()
            delivery_attempts = (
                await session.execute(
                    select(
                        delivery_attempt.job_id,
                        delivery_attempt.result_state,
                        delivery_attempt.latency_ms,
                        delivery_attempt.created_at,
                    ).where(delivery_attempt.job_id.in_([row.id for row in deliveries]))
                )
            ).all()
            invocation = ModelInvocationModel
            governance = (
                await session.execute(
                    select(
                        invocation.capability,
                        invocation.model,
                        func.count(),
                        func.count().filter(invocation.status != "succeeded"),
                        func.coalesce(func.sum(invocation.prompt_tokens), 0),
                        func.coalesce(func.sum(invocation.completion_tokens), 0),
                        func.percentile_cont(0.5).within_group(invocation.latency_ms),
                        func.percentile_cont(0.95).within_group(invocation.latency_ms),
                    )
                    .where(
                        invocation.created_at >= day_start,
                        invocation.created_at < day_start + timedelta(days=1),
                    )
                    .group_by(invocation.capability, invocation.model)
                    .order_by(func.count().desc())
                    .limit(8)
                )
            ).all()

        spans: dict[object, list[_Span]] = {}
        usage: dict[tuple[str, str], _Usage] = {}
        for copy_row in attempts:
            stage = _copy_stage(copy_row.capability, copy_row.version)
            copy_ok = copy_row.status == "succeeded"
            _add(spans, copy_row.run_id, stage, copy_row.model, copy_ok, copy_row)
            _use(usage, stage, copy_row.model, copy_ok, copy_row)
        for rerank_row in reranks:
            rerank_ok = rerank_row.outcome not in ("failed", "error")
            slot_key = ("slot", rerank_row.content_slot_run_id)
            _add(spans, slot_key, "rerank", rerank_row.model, rerank_ok, rerank_row)
            _use(usage, "rerank", rerank_row.model, rerank_ok, rerank_row)
        for image_row in images:
            span = _span(spans, image_row.run_id, "image", image_row.model)
            span.calls += max(image_row.attempt_count, 1)
            span.failures += int(image_row.status != "succeeded")
            span.touch(image_row.created_at, image_row.completed_at, image_row.status)
        for info_row in infographics:
            span = _span(spans, info_row.copy_generation_run_id, "long_image", info_row.provider)
            span.calls += 1
            span.failures += int(info_row.status in ("failed", "error"))
            span.touch(info_row.created_at, info_row.completed_at, info_row.status)
        attempts_by_job: dict[object, list[Any]] = {}
        for attempt_row in delivery_attempts:
            attempts_by_job.setdefault(attempt_row.job_id, []).append(attempt_row)
        delivered_at: dict[object, datetime | None] = {}
        for delivery_row in deliveries:
            span = _span(
                spans, ("delivery", delivery_row.content_slot_selection_id), "delivery", None
            )
            sends = attempts_by_job.get(delivery_row.id, [])
            for attempt_row in sends:
                span.calls += 1
                span.failures += int(attempt_row.result_state != "succeeded")
                span.latency_ms += int(attempt_row.latency_ms or 0)
            # The job waits in the queue until the slot time; the span is the sending itself.
            first_send = min((item.created_at for item in sends), default=None)
            span.touch(
                first_send or delivery_row.created_at,
                delivery_row.completed_at,
                delivery_row.status,
            )
            if delivery_row.completed_at is not None:
                previous = delivered_at.get(delivery_row.content_slot_selection_id)
                delivered_at[delivery_row.content_slot_selection_id] = max(
                    filter(None, (previous, delivery_row.completed_at))
                )
        traces = []
        for post in posts:
            copy_run_id = run_by_selection.get(post.id)
            items = [
                *spans.get(("slot", post.run_id), []),
                *(spans.get(copy_run_id, []) if copy_run_id is not None else []),
                *spans.get(("delivery", post.id), []),
            ]
            traces.append(
                PostTrace(
                    content_slot=post.content_slot,
                    ordinal=post.ordinal,
                    title=_clip(post.representative_title, 120),
                    copy_run_id=copy_run_id,
                    prepared_at=post.preparation_at,
                    target_at=post.target_at,
                    delivered_at=delivered_at.get(post.id),
                    stages=tuple(
                        item.result() for item in sorted(items, key=lambda item: item.sort_key())
                    )[:10],
                )
            )
        rows = [item.result() for item in usage.values()]
        rows += [
            UsageRow(
                stage="news_analysis" if capability == "factual_analysis" else capability,
                model=model,
                calls=int(calls),
                failures=int(failures),
                prompt_tokens=int(prompt),
                completion_tokens=int(completion),
                p50_latency_ms=int(p50 or 0),
                p95_latency_ms=int(p95 or 0),
            )
            for capability, model, calls, failures, prompt, completion, p50, p95 in governance
        ]
        return DayTraceResult(
            business_date=business_date, posts=tuple(traces), usage=tuple(rows[:24])
        )


def _bundle_text(bundle: object, role: str) -> str | None:
    if not isinstance(bundle, dict):
        return None
    value = bundle.get(f"{role}_prompt_version")
    return _clip(value, 120) if isinstance(value, str) else None


# Tables the ops role may read column by column: no recipient identifiers, no raw payloads.
OPS_READ_COLUMNS: dict[str, tuple[str, ...]] = {
    "image_artifacts": (
        "id",
        "run_id",
        "provider",
        "model",
        "status",
        "attempt_count",
        "error_code",
        "created_at",
        "completed_at",
    ),
    # copy_snapshot carries the operator edit history (before/after pairs) of human picks.
    "material_packages": (
        "id",
        "run_id",
        "draft_version_id",
        "review_status",
        "copy_snapshot",
        "created_at",
    ),
    "news_infographic_jobs": (
        "id",
        "copy_generation_run_id",
        "content_slot_selection_id",
        "provider",
        "status",
        "stage",
        "safe_error_code",
        "created_at",
        "completed_at",
    ),
    "topic_rerank_records": (
        "id",
        "content_slot_run_id",
        "provider",
        "model",
        "outcome",
        "failure_code",
        "candidate_count",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "created_at",
    ),
    "wecom_delivery_attempts": (
        "id",
        "job_id",
        "message_kind",
        "attempt_number",
        "result_state",
        "latency_ms",
        "created_at",
    ),
    "wecom_delivery_jobs": (
        "id",
        "delivery_window_id",
        "content_slot_selection_id",
        "sequence_ordinal",
        "status",
        "text_status",
        "image_status",
        "attempt_count",
        "last_error_code",
        "not_before",
        "created_at",
        "completed_at",
    ),
    "wecom_delivery_windows": ("id", "business_date", "content_slot", "target_at", "expires_at"),
}


_BUSINESS_TZ = ZoneInfo("Asia/Shanghai")


def _copy_stage(capability: str, version: int | None) -> str:
    if capability == "generation" and version is not None and version >= 2:
        return "repair"
    return capability


@dataclass(slots=True)
class _Span:
    stage: str
    model: str | None
    calls: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str | None = None

    def touch(self, started: datetime | None, ended: datetime | None, status: str | None) -> None:
        if started is not None and (self.started_at is None or started < self.started_at):
            self.started_at = started
        end = ended or started
        if end is not None and (self.ended_at is None or end > self.ended_at):
            self.ended_at = end
            self.status = status
        elif self.status is None:
            self.status = status

    def sort_key(self) -> tuple[datetime, str]:
        return (self.started_at or datetime.max.replace(tzinfo=_BUSINESS_TZ), self.stage)

    def result(self) -> StageSpan:
        return StageSpan(
            stage=self.stage,
            model=self.model,
            calls=self.calls,
            failures=self.failures,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            latency_ms=self.latency_ms,
            started_at=self.started_at,
            ended_at=self.ended_at,
            status=self.status,
        )


@dataclass(slots=True)
class _Usage:
    stage: str
    model: str
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latencies: list[int] = field(default_factory=list)

    def result(self) -> UsageRow:
        ordered = sorted(self.latencies)
        return UsageRow(
            stage=self.stage,
            model=self.model,
            calls=len(ordered),
            failures=self.failures,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            p50_latency_ms=_nearest_rank(ordered, 0.5),
            p95_latency_ms=_nearest_rank(ordered, 0.95),
        )


def _nearest_rank(ordered: list[int], quantile: float) -> int:
    if not ordered:
        return 0
    index = max(0, min(len(ordered) - 1, int(-(-quantile * len(ordered) // 1)) - 1))
    return ordered[index]


def _span(spans: dict[object, list[_Span]], key: object, stage: str, model: str | None) -> _Span:
    items = spans.setdefault(key, [])
    for item in items:
        if item.stage == stage:
            if item.model is None:
                item.model = model
            return item
    item = _Span(stage=stage, model=model)
    items.append(item)
    return item


def _add(
    spans: dict[object, list[_Span]],
    key: object,
    stage: str,
    model: str,
    ok: bool,
    row: object,
) -> None:
    span = _span(spans, key, stage, model)
    span.calls += 1
    span.failures += int(not ok)
    span.prompt_tokens += int(getattr(row, "prompt_tokens", 0) or 0)
    span.completion_tokens += int(getattr(row, "completion_tokens", 0) or 0)
    span.latency_ms += int(getattr(row, "latency_ms", 0) or 0)
    started = getattr(row, "created_at", None)
    ended = getattr(row, "completed_at", None)
    latency = int(getattr(row, "latency_ms", 0) or 0)
    if started is not None and latency:
        by_latency = started + timedelta(milliseconds=latency)
        ended = by_latency if ended is None or ended < by_latency else ended
    span.touch(started, ended, None)
    span.status = "succeeded" if ok and span.failures == 0 else "has_failures"


def _use(
    usage: dict[tuple[str, str], _Usage], stage: str, model: str, ok: bool, row: object
) -> None:
    item = usage.setdefault((stage, model), _Usage(stage=stage, model=model))
    item.failures += int(not ok)
    item.prompt_tokens += int(getattr(row, "prompt_tokens", 0) or 0)
    item.completion_tokens += int(getattr(row, "completion_tokens", 0) or 0)
    item.latencies.append(int(getattr(row, "latency_ms", 0) or 0))
