"""Task-local, release-bound copy diagnostic. No queue, package, image or send path.

This intentionally does not run CopyGenerationExecutor: its durable lease/repair workflow is
not a read-only diagnostic. Reuse the deployed input loaders, factories, prompts and policies.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from time import perf_counter_ns
from typing import Literal, NoReturn
from uuid import UUID

import app
import httpx
import structlog
from app.application.ports.brand_knowledge import (
    BrandEmbeddingModel,
    BrandEmbeddingRequest,
    BrandEmbeddingResult,
)
from app.application.ports.copy_generation import DraftAuditRequest, DraftGenerationRequest
from app.application.services.copy_generation import (
    BrandRagContextRetriever,
    build_auditor_prompt,
    build_copy_version_bundle,
    build_generator_prompt,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.brand_knowledge import BrandAudience, BrandDocumentKind
from app.domain.copy_generation import (
    COPY_CONTENT_WARNING_CODES,
    COPY_QUALITY_WARNING_CODES,
    ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION,
    ContentSlotTopicOrigin,
    CopyVersionBundle,
    LockedTopicContext,
    apply_copy_audit_policy,
    copy_repair_codes_for_rule,
    validate_material_draft,
)
from app.infrastructure.ai.copy_generation import create_zhipu_copy_models
from app.infrastructure.ai.factory import (
    create_brand_embedding_model,
    select_brand_embedding_client,
)
from app.infrastructure.ai.zhipu import _read_bounded_response
from app.infrastructure.db.brand_knowledge import (
    PostgresBrandKnowledgeRepository,
    active_brand_context_filters,
)
from app.infrastructure.db.copy_generation import (
    load_governed_event_evidence,
    load_locked_topic_origin,
)
from app.infrastructure.db.models import (
    BrandChunkEmbeddingModel,
    BrandChunkModel,
    BrandDocumentModel,
    BrandDocumentVersionModel,
    ContentSlotRunModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    EventClusterVersionModel,
)
from app.schemas.copy_generation import CopyIssue, append_copy_news_source_footer
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

RELEASE = "5c560da71bcbb61b765d3fe82c742cf2d5e676e1"
APP_SOURCE_SHA256 = "70105e3d9fcbc4db75a879d1e44af357f3d182b2cbdbcebbddcae6bbbe51ec86"
APP_SOURCE_COUNT = 253
MAX_ERROR_RESPONSE_BYTES = 32768
# Same reviewed standalone-stdin contract as zhipu-chat-parameter-probe.py. No new provider policy.
# Official source: https://docs.bigmodel.cn/cn/api/api-code, verified 2026-09-05.
OFFICIAL_ERROR_CODES = frozenset(
    {
        "1000",
        "1001",
        "1003",
        "1005",
        "1113",
        "1200",
        "1210",
        "1211",
        "1212",
        "1213",
        "1214",
        "1215",
        "1220",
        "1221",
        "1222",
        "1230",
        "1234",
        "1261",
        "1301",
        "1302",
        "1305",
        "1308",
        "1309",
        "1310",
        "1311",
        "1313",
        "1314",
        "1315",
        "1316",
        "1317",
        "1318",
        "1319",
        "1320",
        "1321",
    }
)
Stage = Literal["preflight", "embedding", "generation", "audit", "complete"]
PROVIDER_ERRORS = frozenset(
    {
        "provider_input_limit",
        "provider_request_rejected",
        "provider_authentication_failed",
        "provider_rate_limited",
        "provider_timeout",
        "provider_unavailable",
        "invalid_provider_output",
        "provider_dimension_mismatch",
        "provider_identity_mismatch",
    }
)
CANARY_ERRORS = frozenset(
    {
        "release_mismatch",
        "selector_invalid",
        "call_cap_invalid",
        "fingerprint_invalid",
        "live_identity_required",
        "source_mismatch",
        "config_mismatch",
        "provider_config_unavailable",
        "provider_endpoint_invalid",
        "database_statement_denied",
        "database_driver_invalid",
        "database_not_readonly",
        "run_not_found",
        "run_not_eligible_for_diagnostic",
        "selector_mismatch",
        "selection_not_succeeded",
        "copy_version_mismatch",
        "event_version_mismatch",
        "missing_eligible_evidence",
        "missing_active_brand_vectors",
        "live_calls_disabled",
        "http_call_cap_exceeded",
        "http_request_not_allowed",
        "http_model_mismatch",
        "provider_input_limit",
        "missing_brand_context",
        "provider_identity_mismatch",
        "arguments_invalid",
    }
)
SAFE_ISSUE_CODES = (
    COPY_CONTENT_WARNING_CODES
    | COPY_QUALITY_WARNING_CODES
    | frozenset(
        {
            "brand_as_fact_evidence",
            "evidence_as_brand_binding",
            "evidence_text_mismatch",
            "missing_source_note",
            "opinion_has_binding",
            "opinion_smuggles_fact",
            "unbound_brand_statement",
            "unbound_date",
            "unbound_external_fact",
            "unknown_brand_chunk_id",
            "unknown_evidence_id",
            "unverified_superlative",
            "copy_news_source_footer",
            "unsafe_image_prompt",
            "automatic_publishing",
        }
    )
)


class CanaryError(Exception):
    """Only locally defined literals may be supplied; never exception/provider text."""


class DryRunStop(Exception):
    pass


@dataclass(frozen=True)
class Selection:
    release: str
    run_id: UUID
    selection_id: UUID
    business_date: date
    slot: str
    ordinal: int
    live: bool = False
    max_http_calls: int = 0
    expected_config: str | None = None
    expected_copy_version: str | None = None
    capture_provider_error_codes: bool = False

    def validate(self) -> None:
        if self.release != RELEASE:
            raise CanaryError("release_mismatch")
        if self.slot not in {"morning", "noon", "evening"} or not 1 <= self.ordinal <= 3:
            raise CanaryError("selector_invalid")
        if self.max_http_calls != (3 if self.live else 0):
            raise CanaryError("call_cap_invalid")
        for digest in (self.expected_config, self.expected_copy_version):
            if digest is not None and not re.fullmatch("[0-9a-f]{64}", digest):
                raise CanaryError("fingerprint_invalid")
        if self.live and (self.expected_config is None or self.expected_copy_version is None):
            raise CanaryError("live_identity_required")


@dataclass
class Report:
    schema: str = "production-recovery-no-send-v1"
    release: str = RELEASE
    mode: str = "dry_run"
    stage: Stage = "preflight"
    outcome: str = "not_started"
    error_code: str | None = None
    run_id: str | None = None
    selection_id: str | None = None
    config_sha256: str | None = None
    copy_version_sha256: str | None = None
    evidence_count: int = 0
    active_brand_vector_count: int = 0
    brand_hit_count: int = 0
    embedding_query_characters: int = 0
    generator_prompt_min_characters: int = 0
    generator_prompt_characters: int = 0
    auditor_prompt_characters: int = 0
    input_character_limit: int = 0
    deterministic_error_count: int = 0
    deterministic_warning_count: int = 0
    deterministic_issue_counts: dict[str, int] = field(default_factory=dict)
    audit_issue_counts: dict[str, int] = field(default_factory=dict)
    audit_accepted: bool | None = None
    repair_issue_count: int = 0
    http_calls: dict[str, int] = field(
        default_factory=lambda: {"embedding": 0, "generation": 0, "audit": 0}
    )
    http_status_codes: dict[str, int] = field(default_factory=dict)
    transport_errors: dict[str, str] = field(default_factory=dict)
    capture_provider_error_codes: bool = False
    provider_business_error_codes: dict[str, str] = field(default_factory=dict)
    latency_ms: int = 0
    database_writes: int = 0
    packages_created: int = 0
    send_calls: int = 0
    delivery_verified: bool = False


def safe_issue_counts(issues: tuple[CopyIssue, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for issue in issues:
        code = issue.code if issue.code in SAFE_ISSUE_CODES else "other_issue"
        counts[code] = counts.get(code, 0) + 1
    return counts


def official_error_code(body: bytes) -> str:
    # Reject ambiguous JSON; only allowlisted error.code can leave the bounded ephemeral body.
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("ambiguous_json")
            result[key] = value
        return result

    def constant(value: str) -> NoReturn:
        raise ValueError("invalid_json")

    try:
        value = json.loads(body, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError):
        return "other_code"
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        return "other_code"
    code = value["error"].get("code")
    if type(code) is int:
        code = str(code)
    return code if isinstance(code, str) and code in OFFICIAL_ERROR_CODES else "other_code"


def verify_source(root: Path) -> None:
    rows: list[str] = []
    for path in sorted(root.rglob("*.py"), key=lambda p: p.relative_to(root).as_posix()):
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise CanaryError("source_mismatch")
        relative = path.relative_to(root).as_posix()
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", relative) or path.stat().st_size > 2_000_000:
            raise CanaryError("source_mismatch")
        rows.append(f"{relative} {hashlib.sha256(path.read_bytes()).hexdigest()}\n")
    if len(rows) != APP_SOURCE_COUNT or (
        hashlib.sha256("".join(rows).encode()).hexdigest() != APP_SOURCE_SHA256
    ):
        raise CanaryError("source_mismatch")


def config_fingerprint(settings: Settings) -> str:
    # Secrets are not hashed, serialized or emitted. Operator independently binds the protected env.
    fields = (
        "app_env",
        "business_timezone",
        "content_enabled",
        "content_slot_mode_enabled",
        "content_copy_provider_required",
        "content_scoring_profile",
        "ai_provider_mode",
        "ai_chat_model",
        "ai_embedding_model",
        "ai_embedding_dimensions",
        "ai_connect_timeout_seconds",
        "ai_read_timeout_seconds",
        "ai_total_timeout_seconds",
        "ai_provider_concurrency",
        "ai_max_attempts",
        "ai_max_validation_corrections",
        "ai_max_input_characters",
        "brand_embedding_provider_mode",
        "brand_retrieval_version",
        "copy_pipeline_version",
        "copy_generator_prompt_version",
        "copy_draft_schema_version",
        "copy_auditor_prompt_version",
        "copy_audit_schema_version",
        "copy_rule_version",
        "copy_preview_policy_version",
        "copy_max_output_tokens",
        "copy_audit_max_output_tokens",
        "copy_brand_context_limit",
        "visual_embedding_provider_mode",
    )
    values = {name: getattr(settings, name) for name in fields}
    values["resolved_brand_identity"] = [
        settings.brand_embedding_provider,
        settings.brand_embedding_model,
        settings.brand_embedding_dimensions,
    ]
    # Endpoint is non-secret validated configuration; only its digest enters the final digest.
    values["endpoint_sha256"] = hashlib.sha256(
        (settings.ai_platform_base_url or "").encode()
    ).hexdigest()
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def validate_settings(settings: Settings, selection: Selection, report: Report) -> None:
    report.config_sha256 = config_fingerprint(settings)
    if selection.expected_config and selection.expected_config != report.config_sha256:
        raise CanaryError("config_mismatch")
    if (
        settings.app_env != "production"
        or not settings.content_enabled
        or not settings.content_slot_mode_enabled
        or not settings.content_copy_provider_required
        or settings.ai_provider_mode != "zhipu"
        or settings.resolved_brand_embedding_provider_mode != "zhipu"
        or settings.brand_embedding_model != "embedding-3"
        or settings.brand_embedding_dimensions != 2048
        or not settings.ai_platform_api_key
        or not settings.ai_platform_base_url
    ):
        raise CanaryError("provider_config_unavailable")
    # No alternate endpoint/account supplied through diagnostic flags.
    url = httpx.URL(settings.ai_platform_base_url)
    if url.scheme != "https" or url.query or url.fragment or url.userinfo:
        raise CanaryError("provider_endpoint_invalid")
    report.input_character_limit = settings.ai_max_input_characters


def guard_statement(statement: str) -> None:
    command = statement.strip().upper()
    if command == "SET TRANSACTION READ ONLY" or command.startswith(("SELECT ", "SHOW ")):
        return
    raise CanaryError("database_statement_denied")


def readonly_engine(settings: Settings) -> AsyncEngine:
    database_url = settings.database_url.get_secret_value()
    if make_url(database_url).drivername != "postgresql+asyncpg":
        raise CanaryError("database_driver_invalid")
    engine = create_async_engine(
        database_url,
        poolclass=NullPool,
        echo=False,
        hide_parameters=True,
        connect_args={
            "server_settings": {
                "default_transaction_read_only": "on",
                "statement_timeout": "10000",
                "lock_timeout": "1000",
                "idle_in_transaction_session_timeout": "15000",
                "application_name": "production-recovery-no-send-v1",
            }
        },
    )

    @event.listens_for(engine.sync_engine, "begin")
    def begin(connection: Connection) -> None:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def before_cursor_execute(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        guard_statement(statement)

    return engine


async def load_topic(
    factory: async_sessionmaker[AsyncSession],
    selection: Selection,
    settings: Settings,
    report: Report,
) -> tuple[LockedTopicContext, CopyVersionBundle]:
    async with factory() as session:
        if await session.scalar(text("SHOW transaction_read_only")) != "on":
            raise CanaryError("database_not_readonly")
        run = await session.get(CopyGenerationRunModel, selection.run_id)
        if run is None:
            raise CanaryError("run_not_found")
        if (
            run.content_slot_selection_id != selection.selection_id
            or run.business_date != selection.business_date
            or run.decision_kind != "selected"
            or run.status != "review_required"
            or run.error_code != "copy_provider_unavailable"
            or run.active_draft_version_id is not None
            or run.repair_count != 0
        ):
            raise CanaryError("run_not_eligible_for_diagnostic")
        origin = await load_locked_topic_origin(session, run)
        if not isinstance(origin, ContentSlotTopicOrigin) or (
            origin.content_slot.value != selection.slot or origin.ordinal != selection.ordinal
        ):
            raise CanaryError("selector_mismatch")
        slot_selection = await session.get(ContentSlotSelectionModel, selection.selection_id)
        if slot_selection is None:
            raise CanaryError("selector_mismatch")
        slot_run = await session.get(ContentSlotRunModel, slot_selection.run_id)
        if slot_run is None or slot_run.status != "succeeded":
            raise CanaryError("selection_not_succeeded")
        bundle = CopyVersionBundle(**run.version_bundle)
        if bundle.fingerprint != run.version_fingerprint or (
            build_copy_version_bundle(settings, scoring_profile=run.scoring_profile) != bundle
        ):
            raise CanaryError("copy_version_mismatch")
        report.copy_version_sha256 = bundle.fingerprint
        if (
            selection.expected_copy_version
            and selection.expected_copy_version != bundle.fingerprint
        ):
            raise CanaryError("copy_version_mismatch")
        version = await session.get(EventClusterVersionModel, run.selected_event_version_id)
        if version is None or version.event_id != run.selected_event_id:
            raise CanaryError("event_version_mismatch")
        evidence = await load_governed_event_evidence(
            session,
            version,
            include_governed_statement=(
                bundle.pipeline_version == ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION
            ),
        )
        if not evidence:
            raise CanaryError("missing_eligible_evidence")
        summary = version.summary_projection.get("summary")
        topic = LockedTopicContext(
            origin=origin,
            business_date=run.business_date,
            timezone=run.timezone,
            scoring_profile=run.scoring_profile,
            decision_kind=run.decision_kind,
            selected_event_id=run.selected_event_id,
            selected_event_version_id=run.selected_event_version_id,
            no_topic_code=None,
            title=version.representative_title,
            summary=summary if isinstance(summary, str) else None,
            evidence=evidence,
        )
        report.active_brand_vector_count = int(
            await session.scalar(
                select(func.count(BrandChunkEmbeddingModel.id))
                .join(BrandChunkModel, BrandChunkModel.id == BrandChunkEmbeddingModel.chunk_id)
                .join(
                    BrandDocumentVersionModel,
                    BrandDocumentVersionModel.id == BrandChunkModel.version_id,
                )
                .join(
                    BrandDocumentModel,
                    BrandDocumentModel.id == BrandDocumentVersionModel.document_id,
                )
                .where(
                    *active_brand_context_filters(
                        audience=BrandAudience.PARENTS,
                        document_kinds=tuple(BrandDocumentKind),
                        valid_on=topic.business_date,
                    ),
                    BrandDocumentVersionModel.embedding_provider
                    == settings.brand_embedding_provider,
                    BrandDocumentVersionModel.embedding_model == settings.brand_embedding_model,
                    BrandChunkEmbeddingModel.provider == settings.brand_embedding_provider,
                    BrandChunkEmbeddingModel.model == settings.brand_embedding_model,
                    BrandChunkEmbeddingModel.dimensions == settings.brand_embedding_dimensions,
                )
            )
            or 0
        )
        if not report.active_brand_vector_count:
            raise CanaryError("missing_active_brand_vectors")
        report.evidence_count = len(evidence)
    return topic, bundle


class CappedTransport(httpx.AsyncBaseTransport):
    """Physical request guard: retries/corrections cannot exceed one request in each stage."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        settings: Settings,
        selection: Selection,
        report: Report,
    ) -> None:
        self.inner, self.settings, self.selection, self.report = inner, settings, selection, report

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        stage = self.report.stage
        if not self.selection.live:
            raise CanaryError("live_calls_disabled")
        if (
            stage not in self.report.http_calls
            or self.report.http_calls[stage] >= 1
            or (sum(self.report.http_calls.values()) >= self.selection.max_http_calls)
        ):
            raise CanaryError("http_call_cap_exceeded")
        suffix = "embeddings" if stage == "embedding" else "chat/completions"
        expected_url = httpx.URL(
            f"{(self.settings.ai_platform_base_url or '').rstrip('/')}/{suffix}"
        )
        if request.method != "POST" or request.url != expected_url:
            raise CanaryError("http_request_not_allowed")
        payload = json.loads(request.content)
        expected_model = (
            self.settings.ai_embedding_model
            if stage == "embedding"
            else self.settings.ai_chat_model
        )
        if payload.get("model") != expected_model:
            raise CanaryError("http_model_mismatch")
        self.report.http_calls[stage] += (
            1  # Charge before transport, including timeout/unknown result.
        )
        try:
            response = await self.inner.handle_async_request(request)
        except httpx.TimeoutException:
            self.report.transport_errors[stage] = "provider_timeout"
            raise
        except httpx.RequestError:
            self.report.transport_errors[stage] = "provider_unavailable"
            raise
        self.report.http_status_codes[stage] = response.status_code
        if self.selection.capture_provider_error_codes and not 200 <= response.status_code < 300:
            response.request = request
            try:
                bounded = await _read_bounded_response(
                    response, max_response_bytes=MAX_ERROR_RESPONSE_BYTES
                )
                self.report.provider_business_error_codes[stage] = official_error_code(
                    bounded.content
                )
            finally:
                await response.aclose()
            # Preserve status classification, discard all body/headers after code observation.
            return httpx.Response(response.status_code, content=b"", request=request)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


class InspectEmbedding:
    def __init__(self, model: BrandEmbeddingModel, selection: Selection, report: Report) -> None:
        self.model, self.selection, self.report = model, selection, report

    async def embed_brand(self, request: BrandEmbeddingRequest) -> BrandEmbeddingResult:
        self.report.embedding_query_characters = len(request.text)
        if not self.selection.live:
            raise DryRunStop()
        return await self.model.embed_brand(request)


async def exercise(
    settings: Settings,
    selection: Selection,
    report: Report,
    factory: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient,
) -> None:
    topic, bundle = await load_topic(factory, selection, settings, report)
    embedding = create_brand_embedding_model(
        settings,
        client=select_brand_embedding_client(settings, zhipu_client=client, alibaba_client=None),
    )
    if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
        raise CanaryError("provider_config_unavailable")
    generator, auditor = create_zhipu_copy_models(
        client=client,
        base_url=settings.ai_platform_base_url,
        api_key=settings.ai_platform_api_key,
        model=settings.ai_chat_model,
        connect_timeout_seconds=settings.ai_connect_timeout_seconds,
        read_timeout_seconds=settings.ai_read_timeout_seconds,
        total_timeout_seconds=settings.ai_total_timeout_seconds,
        concurrency=settings.ai_provider_concurrency,
        max_attempts=1,
        max_input_characters=settings.ai_max_input_characters,
        max_output_tokens=settings.copy_max_output_tokens,
        max_validation_corrections=0,
    )
    # Non-mutating diagnostic-only reduction in retry budget, not relaxed generation/quality rules.
    # Embedding uses the unchanged factory settings; CappedTransport stops any retry before HTTP.
    request = DraftGenerationRequest(
        run_id=selection.run_id,
        topic=topic,
        brand_context=(),
        version_bundle=bundle,
        draft_version=1,
        max_output_tokens=settings.copy_max_output_tokens,
    )
    report.generator_prompt_min_characters = len(build_generator_prompt(request))
    if report.generator_prompt_min_characters > settings.ai_max_input_characters:
        raise CanaryError("provider_input_limit")
    report.stage = "embedding"
    brand = await BrandRagContextRetriever(
        repository=PostgresBrandKnowledgeRepository(factory),
        embeddings=InspectEmbedding(embedding, selection, report),
        limit=settings.copy_brand_context_limit,
        retrieval_version=settings.brand_retrieval_version,
    ).retrieve_for_copy(topic)
    report.brand_hit_count = len(brand)
    if not brand:
        raise CanaryError("missing_brand_context")
    request = DraftGenerationRequest(
        run_id=selection.run_id,
        topic=topic,
        brand_context=brand,
        version_bundle=bundle,
        draft_version=1,
        max_output_tokens=settings.copy_max_output_tokens,
    )
    report.stage = "generation"
    report.generator_prompt_characters = len(build_generator_prompt(request))
    result = await generator.generate(request)
    if (result.provider, result.model) != (bundle.provider, bundle.model):
        raise CanaryError("provider_identity_mismatch")
    evidence = topic.evidence[0]
    draft = result.draft.model_copy(
        update={
            "copywriting": append_copy_news_source_footer(
                result.draft.copywriting,
                source_name=evidence.source_name,
                source_url=evidence.source_url,
            )
        }
    )
    issues = validate_material_draft(
        draft, topic=topic, brand_context=brand, rule_version=bundle.rule_version
    )
    report.deterministic_error_count = sum(issue.severity == "error" for issue in issues)
    report.deterministic_warning_count = sum(issue.severity == "warning" for issue in issues)
    report.deterministic_issue_counts = safe_issue_counts(issues)
    if report.deterministic_error_count:
        report.outcome = "deterministic_validation_failed"
        return
    report.stage = "audit"
    audit_request = DraftAuditRequest(
        run_id=selection.run_id,
        draft_version_id=selection.run_id,
        topic=topic,
        brand_context=brand,
        draft=draft,
        version_bundle=bundle,
        max_output_tokens=settings.copy_audit_max_output_tokens,
    )
    # Ephemeral draft identity is deliberately not a new durable row or usable package.
    report.auditor_prompt_characters = len(build_auditor_prompt(audit_request))
    audited = await auditor.audit(audit_request)
    if (audited.provider, audited.model) != (bundle.provider, bundle.model):
        raise CanaryError("provider_identity_mismatch")
    verdict = apply_copy_audit_policy(audited.verdict, rule_version=bundle.rule_version)
    report.audit_accepted = verdict.accepted
    report.audit_issue_counts = safe_issue_counts(verdict.issues)
    repair_codes = copy_repair_codes_for_rule(bundle.rule_version)
    report.repair_issue_count = len(
        {
            (issue.code, issue.field, issue.claim_id)
            for issue in (*issues, *verdict.issues)
            if issue.code in repair_codes
        }
    )
    report.stage = "complete"
    report.outcome = (
        "first_draft_passed"
        if verdict.accepted and not report.repair_issue_count
        else "repair_needed_not_attempted"
        if verdict.accepted
        else "audit_rejected"
    )


async def run(selection: Selection) -> Report:
    report = Report()
    started = perf_counter_ns()
    try:
        selection.validate()
        report.mode = "live_no_send" if selection.live else "dry_run"
        if selection.capture_provider_error_codes:
            report.schema = "production-recovery-no-send-v2-error-observation"
            report.mode = "live_no_send_error_codes" if selection.live else "dry_run_error_codes"
            report.capture_provider_error_codes = True
        report.run_id, report.selection_id = str(selection.run_id), str(selection.selection_id)
        verify_source(Path(app.__file__).parent)
        settings = Settings()  # Same consumer environment; no alternate secrets or provider flags.
        validate_settings(settings, selection, report)
        engine = readonly_engine(settings)
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            # Explicit transport suppresses ambient proxy mounts, redirects and hidden TCP retries.
            transport = CappedTransport(
                httpx.AsyncHTTPTransport(retries=0, trust_env=False), settings, selection, report
            )
            async with httpx.AsyncClient(
                transport=transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with asyncio.timeout(180):
                    await exercise(settings, selection, report, factory, client)
        finally:
            await engine.dispose()
    except DryRunStop:
        report.outcome = "preflight_passed_live_unverified"
    except CanaryError as error:
        report.outcome = "failed"
        report.error_code = (
            str(error) if str(error) in CANARY_ERRORS else "diagnostic_internal_error"
        )
    except AppError as error:
        report.outcome = "failed"
        report.error_code = error.code if error.code in PROVIDER_ERRORS else "provider_failure"
    except TimeoutError:
        report.outcome, report.error_code = "failed", "diagnostic_timeout"
    except Exception:
        report.outcome, report.error_code = "failed", "diagnostic_internal_error"
    report.latency_ms = max(0, (perf_counter_ns() - started) // 1_000_000)
    return report


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise CanaryError("arguments_invalid")


def parse_args(argv: list[str]) -> Selection:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--copy-run-id", required=True, type=UUID)
    parser.add_argument("--selection-id", required=True, type=UUID)
    parser.add_argument("--business-date", required=True, type=date.fromisoformat)
    parser.add_argument("--slot", required=True, choices=("morning", "noon", "evening"))
    parser.add_argument("--ordinal", required=True, type=int)
    parser.add_argument("--live-no-send", action="store_true")
    parser.add_argument("--max-http-calls", type=int, default=0)
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--expected-copy-version")
    parser.add_argument("--capture-provider-error-codes", action="store_true")
    args = parser.parse_args(argv)
    selection = Selection(
        release=args.expected_release,
        run_id=args.copy_run_id,
        selection_id=args.selection_id,
        business_date=args.business_date,
        slot=args.slot,
        ordinal=args.ordinal,
        live=args.live_no_send,
        max_http_calls=args.max_http_calls,
        expected_config=args.expected_config_sha256,
        expected_copy_version=args.expected_copy_version,
        capture_provider_error_codes=args.capture_provider_error_codes,
    )
    selection.validate()
    return selection


def main(argv: list[str] | None = None) -> int:
    # No raw settings, SQL parameters, authenticated URLs, exceptions or provider logs.
    logging.disable(logging.CRITICAL)
    structlog.configure(processors=[lambda *args: (_ for _ in ()).throw(structlog.DropEvent())])
    try:
        report = asyncio.run(run(parse_args(sys.argv[1:] if argv is None else argv)))
    except CanaryError:
        report = Report(outcome="failed", error_code="arguments_invalid")
    print(json.dumps(asdict(report), sort_keys=True))
    return 0 if report.outcome in {"preflight_passed_live_unverified", "first_draft_passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
