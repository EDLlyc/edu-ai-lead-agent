"""Prepare and execute the explicitly authorized Agent retrieval compatibility canary."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx
from app.agent_workbench_runtime import build_postgres_agent_tool_registry
from app.application.services.agent_retrieval import CachedBrandEmbeddingModel
from app.application.services.agent_tools import TypedToolRegistry
from app.application.services.agent_workbench_graph import BoundedAgentRunner
from app.core.config import Settings, get_settings
from app.domain.agent_workbench import AgentRunLimits
from app.infrastructure.ai.agent_retrieval import (
    ZhipuAgentQueryPlanner,
    ZhipuAgentTextReranker,
)
from app.infrastructure.ai.agent_workbench import OpenAICompatibleToolCallingModel
from app.infrastructure.ai.factory import create_brand_embedding_model
from app.infrastructure.db.session import create_engine, create_session_factory
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from .dataset import (
    DatasetBuildError,
    build_frozen_dataset,
    canonical_jsonl_bytes,
    require_canary_qrel_contract,
    require_dataset_contract,
)
from .harness import (
    AttemptPlan,
    BudgetedBrandEmbeddingModel,
    BudgetedQueryPlanner,
    BudgetedTextReranker,
    BudgetedToolCallingModel,
    CapabilityBudget,
    CapabilityFailureLedger,
    build_attempt_observation,
    build_failed_attempt,
    build_schedule,
    canary_attempt_passed,
    require_registry_equality,
)
from .io import (
    ArtifactError,
    create_run_directory,
    load_json_model,
    load_jsonl_models,
    load_raw_json,
    require_output_path,
    write_json_atomic,
    write_json_exclusive,
    write_jsonl_exclusive,
    write_text_exclusive,
)
from .metrics import build_paired_report
from .models import (
    AGENT_MODEL_TURNS_PER_ATTEMPT,
    AGENT_TOOL_CALLS_PER_ATTEMPT,
    AUTHORIZATION_SCHEMA_VERSION,
    CANARY_ATTEMPTS,
    EVALUATION_POLICY_VERSION,
    EXECUTION_MODE,
    LIVE_AUTHORIZATION_ACKNOWLEDGEMENT,
    MANIFEST_SCHEMA_VERSION,
    AttemptObservation,
    CapabilityLimits,
    CaseOracle,
    ExperimentArm,
    LiveAbCase,
    LiveAuthorization,
    ProviderIdentity,
    RunManifest,
    evidence_sha256,
)
from .reporting import render_markdown, safe_report_json

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FEATURE_ROOT = Path(__file__).resolve().parent


class PreflightError(RuntimeError):
    """The explicit live boundary is not safe to cross."""


@dataclass(slots=True)
class _ArmRuntime:
    registry: TypedToolRegistry
    model_client: httpx.AsyncClient
    retrieval_client: httpx.AsyncClient
    embedding_cache: CachedBrandEmbeddingModel

    async def close(self) -> None:
        await asyncio.gather(
            self.model_client.aclose(),
            self.retrieval_client.aclose(),
            return_exceptions=True,
        )


@dataclass(slots=True)
class _RuntimeBundle:
    engine: AsyncEngine
    arms: dict[ExperimentArm, _ArmRuntime]

    async def close(self) -> None:
        try:
            await asyncio.gather(
                *(arm.close() for arm in self.arms.values()),
                return_exceptions=True,
            )
        finally:
            await self.engine.dispose()


@dataclass(frozen=True, slots=True)
class _ExecutionOutcome:
    attempts: tuple[AttemptObservation, ...]
    circuit_breaker_reason: str | None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="freeze real data without provider calls")
    preflight.add_argument("--output-dir", type=Path, required=True)
    preflight.add_argument("--run-ref", required=True)
    preflight.add_argument("--valid-on", type=date.fromisoformat, default=date.today())

    live = subparsers.add_parser(
        "live", help="execute the explicitly authorized two-cell compatibility canary"
    )
    live.add_argument("--run-dir", type=Path, required=True)
    live.add_argument("--acknowledgement", required=True)
    live.add_argument("--approved-by-ref", default="user-session")

    report = subparsers.add_parser("report", help="recompute aggregate-safe metrics")
    report.add_argument("--run-dir", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            return asyncio.run(_preflight(args))
        if args.command == "live":
            return asyncio.run(_live(args))
        return _report(args)
    except (ArtifactError, DatasetBuildError, PreflightError, ValidationError, ValueError) as exc:
        print(f"agent retrieval live A/B blocked: {_safe_cli_error_code(exc)}", file=sys.stderr)
        return 2
    except Exception:
        print("agent retrieval live A/B blocked: unexpected_runtime_failure", file=sys.stderr)
        return 2


async def _preflight(args: argparse.Namespace) -> int:
    settings = get_settings()
    _validate_settings(settings)
    output_dir = create_run_directory(args.output_dir)
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        dataset = await build_frozen_dataset(
            session_factory,
            valid_on=args.valid_on,
            brand_embedding_provider=settings.brand_embedding_provider,
            brand_embedding_model=settings.brand_embedding_model,
        )
        budget = CapabilityBudget()
        failures = CapabilityFailureLedger()
        runtimes = await _compose_arms(
            settings=settings,
            engine=engine,
            session_factory=session_factory,
            budget=budget,
            failures=failures,
        )
        try:
            registry_hash = require_registry_equality(
                runtimes.arms[ExperimentArm.RAW].registry,
                runtimes.arms[ExperimentArm.ENHANCED].registry,
            )
        finally:
            for runtime in runtimes.arms.values():
                await runtime.close()
        if budget.snapshot().model_dump() != {
            "agent": 0,
            "planner": 0,
            "reranker": 0,
            "embedding": 0,
        }:
            raise PreflightError("provider-free preflight consumed a capability budget")
        source_hash = _source_hash()
        git_sha, dirty = _git_identity()
        manifest = _build_manifest(
            run_ref=args.run_ref,
            git_sha=git_sha,
            source_hash=source_hash,
            worktree_dirty=dirty,
            dataset_sha=dataset.dataset_sha256,
            oracle_sha=dataset.oracle_sha256,
            snapshot=dataset.snapshot,
            valid_on=args.valid_on,
            registry_hash=registry_hash,
            settings=settings,
            case_ids=tuple(item.case_id for item in dataset.cases),
        )
        write_jsonl_exclusive(output_dir / "dataset.private.jsonl", dataset.cases)
        write_jsonl_exclusive(output_dir / "oracle.private.jsonl", dataset.oracles)
        write_json_exclusive(output_dir / "manifest.json", manifest)
        write_json_exclusive(
            output_dir / "preflight-hashes.json",
            {
                "dataset_sha256": dataset.dataset_sha256,
                "oracle_sha256": dataset.oracle_sha256,
                "manifest_sha256": manifest.manifest_sha256,
                "registry_sha256": registry_hash,
                "source_sha256": source_hash,
            },
        )
    finally:
        await engine.dispose()
    print(
        "provider-free compatibility preflight passed; cases=12; repetitions=3; arms=2; "
        "authorized_agent_attempts=2; authorized_agent_decisions=8; max_planner=4; "
        "max_reranker=4; max_embedding=4; compatibility_canary_attempts=2; "
        "live_provider_calls=0"
    )
    return 0


async def _live(args: argparse.Namespace) -> int:
    run_dir = require_output_path(args.run_dir)
    manifest = load_json_model(run_dir / "manifest.json", RunManifest)
    cases = load_jsonl_models(run_dir / "dataset.private.jsonl", LiveAbCase)
    oracles = load_jsonl_models(run_dir / "oracle.private.jsonl", CaseOracle)
    require_dataset_contract(cases, oracles)
    require_canary_qrel_contract(oracles)
    if tuple(item.case_id for item in cases) != manifest.selected_case_ids:
        raise PreflightError("dataset case identities differ from the manifest")
    _require_hash(canonical_jsonl_bytes(cases), manifest.dataset_sha256, "dataset")
    _require_hash(canonical_jsonl_bytes(oracles), manifest.oracle_sha256, "oracle")
    if _source_hash() != manifest.source_sha256:
        raise PreflightError("evaluation source changed after preflight")
    if args.acknowledgement != LIVE_AUTHORIZATION_ACKNOWLEDGEMENT:
        raise PreflightError("exact live authorization acknowledgement is required")
    authorization = LiveAuthorization(
        schema_version=AUTHORIZATION_SCHEMA_VERSION,
        manifest_sha256=manifest.manifest_sha256,
        approved_at=datetime.now(UTC),
        approved_by_ref=args.approved_by_ref,
        acknowledgement=args.acknowledgement,
    )
    authorization_path = run_dir / "authorization.json"
    if authorization_path.exists():
        existing = load_json_model(authorization_path, LiveAuthorization)
        if existing.manifest_sha256 != manifest.manifest_sha256:
            raise PreflightError("existing authorization is bound to another manifest")
        authorization = existing
    else:
        write_json_exclusive(authorization_path, authorization)
    authorization_sha = evidence_sha256(authorization)

    settings = get_settings()
    _validate_settings(settings)
    _require_manifest_environment(manifest, settings)
    current_git_sha, _ = _git_identity()
    if current_git_sha != manifest.git_sha:
        raise PreflightError("repository commit changed after preflight")
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        current = await build_frozen_dataset(
            session_factory,
            valid_on=manifest.valid_on,
            brand_embedding_provider=settings.brand_embedding_provider,
            brand_embedding_model=settings.brand_embedding_model,
        )
        if (
            current.snapshot.fingerprint != manifest.database_snapshot.fingerprint
            or current.dataset_sha256 != manifest.dataset_sha256
            or current.oracle_sha256 != manifest.oracle_sha256
        ):
            raise PreflightError("database snapshot or frozen Seed drifted after preflight")

        budget = CapabilityBudget()
        failures = CapabilityFailureLedger()
        runtimes = await _compose_arms(
            settings=settings,
            engine=engine,
            session_factory=session_factory,
            budget=budget,
            failures=failures,
        )
        try:
            registry_hash = require_registry_equality(
                runtimes.arms[ExperimentArm.RAW].registry,
                runtimes.arms[ExperimentArm.ENHANCED].registry,
            )
            if registry_hash != manifest.registry_sha256:
                raise PreflightError("registry schema drifted after preflight")
            outcome = await _execute_schedule(
                run_dir=run_dir,
                manifest=manifest,
                authorization_sha=authorization_sha,
                cases=cases,
                oracles=oracles,
                runtimes=runtimes.arms,
                budget=budget,
                failures=failures,
            )
        finally:
            await runtimes.close()
    except BaseException:
        await engine.dispose()
        raise

    report = build_paired_report(
        run_ref=manifest.run_ref,
        manifest_sha256=manifest.manifest_sha256,
        cases=cases,
        attempts=outcome.attempts,
        capability_counts=budget.snapshot(),
        authorization_sha256=authorization_sha,
        circuit_breaker_reason=outcome.circuit_breaker_reason,
    )
    _write_report_artifacts(run_dir, report, outcome.attempts)
    print(
        f"live compatibility canary finished; attempts={len(outcome.attempts)}/2; "
        f"complete={str(report.complete).lower()}; "
        f"canary_passed={str(report.canary_passed).lower()}; "
        f"circuit={report.circuit_breaker_reason or 'none'}; "
        f"provider_failures={report.provider_failure_count}; "
        f"task_success_raw={report.arms[0].task_success_rate:.4f}; "
        f"task_success_enhanced={report.arms[1].task_success_rate:.4f}"
    )
    return 0 if report.canary_passed else 2


async def _execute_schedule(
    *,
    run_dir: Path,
    manifest: RunManifest,
    authorization_sha: str,
    cases: tuple[LiveAbCase, ...],
    oracles: tuple[CaseOracle, ...],
    runtimes: dict[ExperimentArm, _ArmRuntime],
    budget: CapabilityBudget,
    failures: CapabilityFailureLedger,
) -> _ExecutionOutcome:
    case_by_id = {item.case_id: item for item in cases}
    oracle_by_id = {item.case_id: item for item in oracles}
    observations: list[AttemptObservation] = []
    circuit_breaker_reason: str | None = None
    compatibility_schedule = _compatibility_schedule(tuple(item.case_id for item in cases))
    for plan in compatibility_schedule:
        runtime = runtimes[plan.arm]
        attempt_path = run_dir / "attempts" / f"{plan.attempt_ref}.json"
        if attempt_path.exists():
            raise PreflightError("attempt output already exists; implicit reruns are forbidden")
        write_json_atomic(
            attempt_path,
            {
                "attempt_ref": plan.attempt_ref,
                "manifest_sha256": manifest.manifest_sha256,
                "status": "started",
            },
        )
        before = budget.snapshot()
        failures_before = failures.snapshot()
        cache_hits = runtime.embedding_cache.cache_hits
        cache_misses = runtime.embedding_cache.cache_misses
        case = case_by_id[plan.case_id]
        oracle = oracle_by_id[plan.case_id]
        try:
            model = BudgetedToolCallingModel(
                OpenAICompatibleToolCallingModel(
                    client=runtime.model_client,
                    base_url=_required_base_url(get_settings()),
                    api_key=get_settings().ai_platform_api_key,
                    model=get_settings().ai_chat_model,
                    timeout_seconds=15,
                    max_output_tokens=min(get_settings().ai_max_output_tokens, 4_096),
                ),
                budget,
                failures,
            )
            runner = BoundedAgentRunner(
                registry=runtime.registry,
                model=model,
                limits=AgentRunLimits(
                    max_model_turns=AGENT_MODEL_TURNS_PER_ATTEMPT,
                    max_tool_calls=AGENT_TOOL_CALLS_PER_ATTEMPT,
                    model_timeout_seconds=15,
                    total_timeout_seconds=30,
                ),
            )
            result = await runner.run(
                case.query,
                run_id=uuid5(
                    NAMESPACE_URL,
                    f"agent-retrieval-ab:{manifest.manifest_sha256}:{plan.attempt_ref}",
                ),
            )
            observation = build_attempt_observation(
                plan=plan,
                case=case,
                oracle=oracle,
                result=result,
                manifest_sha256=manifest.manifest_sha256,
                authorization_sha256=authorization_sha,
                capability_counts=CapabilityBudget.delta(before, budget.snapshot()),
                capability_failure_counts=CapabilityFailureLedger.delta(
                    failures_before, failures.snapshot()
                ),
                embedding_cache=runtime.embedding_cache,
                cache_hits_before=cache_hits,
                cache_misses_before=cache_misses,
            )
        except Exception as exc:
            failure_code = (
                "capability_budget_exhausted"
                if "budget_exhausted" in str(exc)
                else f"executor_{type(exc).__name__.lower()}"
            )
            observation = build_failed_attempt(
                plan=plan,
                case=case,
                manifest_sha256=manifest.manifest_sha256,
                authorization_sha256=authorization_sha,
                capability_counts=CapabilityBudget.delta(before, budget.snapshot()),
                capability_failure_counts=CapabilityFailureLedger.delta(
                    failures_before, failures.snapshot()
                ),
                failure_code=failure_code,
            )
            write_json_atomic(attempt_path, observation)
            observations.append(observation)
            if budget.exhausted is not None:
                circuit_breaker_reason = "capability_budget_exhausted"
                break
            if plan.ordinal < 2:
                # The authorization binds cells 1-2 as one paired canary. Preserve the
                # failed first arm, then observe the other arm exactly once before closing.
                continue
            circuit_breaker_reason = "canary_failed" if plan.ordinal == 2 else "executor_failure"
            break
        write_json_atomic(attempt_path, observation)
        observations.append(observation)
        if plan.ordinal == 2:
            canary_pair = tuple(item for item in observations if item.canary)
            if len(canary_pair) != 2 or not all(
                canary_attempt_passed(item) for item in canary_pair
            ):
                circuit_breaker_reason = "canary_failed"
                break
        if budget.exhausted is not None:
            circuit_breaker_reason = "capability_budget_exhausted"
            break
    if len(observations) == CANARY_ATTEMPTS and circuit_breaker_reason is None:
        circuit_breaker_reason = (
            "compatibility_canary_complete"
            if all(canary_attempt_passed(item) for item in observations)
            else "canary_failed"
        )
    return _ExecutionOutcome(
        attempts=tuple(observations),
        circuit_breaker_reason=circuit_breaker_reason,
    )


def _compatibility_schedule(case_ids: tuple[str, ...]) -> tuple[AttemptPlan, ...]:
    selected = build_schedule(case_ids)[:CANARY_ATTEMPTS]
    if (
        len(selected) != CANARY_ATTEMPTS
        or not all(item.canary for item in selected)
        or len({(item.case_id, item.repetition) for item in selected}) != 1
        or {item.arm for item in selected} != set(ExperimentArm)
    ):
        raise PreflightError("compatibility canary schedule is invalid")
    return selected


def _report(args: argparse.Namespace) -> int:
    run_dir = require_output_path(args.run_dir)
    manifest = load_json_model(run_dir / "manifest.json", RunManifest)
    cases = load_jsonl_models(run_dir / "dataset.private.jsonl", LiveAbCase)
    oracles = load_jsonl_models(run_dir / "oracle.private.jsonl", CaseOracle)
    require_dataset_contract(cases, oracles)
    if tuple(item.case_id for item in cases) != manifest.selected_case_ids:
        raise PreflightError("dataset case identities differ from the manifest")
    _require_hash(canonical_jsonl_bytes(cases), manifest.dataset_sha256, "dataset")
    _require_hash(canonical_jsonl_bytes(oracles), manifest.oracle_sha256, "oracle")
    authorization = load_json_model(run_dir / "authorization.json", LiveAuthorization)
    if authorization.manifest_sha256 != manifest.manifest_sha256:
        raise PreflightError("authorization is bound to another manifest")
    authorization_sha = evidence_sha256(authorization)
    attempt_paths = sorted((run_dir / "attempts").glob("*.json"))
    attempts: list[AttemptObservation] = []
    started_attempt_count = 0
    for path in attempt_paths:
        if _is_started_journal(path):
            _validate_started_journal(path, manifest)
            started_attempt_count += 1
            continue
        attempt = load_json_model(path, AttemptObservation)
        if path.stem != attempt.attempt_ref:
            raise PreflightError("attempt filename differs from its bound identity")
        attempts.append(attempt)
    attempt_values = tuple(attempts)
    counts = _sum_capability_counts(attempt_values)
    report = build_paired_report(
        run_ref=manifest.run_ref,
        manifest_sha256=manifest.manifest_sha256,
        cases=cases,
        attempts=attempt_values,
        capability_counts=counts,
        authorization_sha256=authorization_sha,
        started_attempt_count=started_attempt_count,
        circuit_breaker_reason=_recomputed_circuit_reason(
            attempt_values,
            started_attempt_count=started_attempt_count,
        ),
    )
    _write_report_artifacts(run_dir, report, attempt_values, replace=True)
    print(
        f"compatibility report recomputed; attempts={len(attempts)}/2; "
        f"canary_passed={report.canary_passed}"
    )
    return 0 if report.canary_passed else 2


async def _compose_arms(
    *,
    settings: Settings,
    engine: AsyncEngine,
    session_factory: async_sessionmaker[Any],
    budget: CapabilityBudget,
    failures: CapabilityFailureLedger,
) -> _RuntimeBundle:
    arms: dict[ExperimentArm, _ArmRuntime] = {}
    try:
        for arm in ExperimentArm:
            model_client = httpx.AsyncClient(follow_redirects=False)
            retrieval_client = httpx.AsyncClient(follow_redirects=False)
            provider_embedding = create_brand_embedding_model(settings, client=retrieval_client)
            embedding_cache = CachedBrandEmbeddingModel(
                BudgetedBrandEmbeddingModel(provider_embedding, budget, failures),
                cache_namespace=(
                    f"agent-retrieval-ab:{arm.value}:{settings.brand_embedding_provider}:"
                    f"{settings.brand_embedding_model}:{settings.brand_embedding_input_version}"
                ),
            )
            kwargs: dict[str, Any] = {}
            if arm is ExperimentArm.ENHANCED:
                base_url = _required_base_url(settings)
                api_key = settings.ai_platform_api_key
                assert api_key is not None
                kwargs = {
                    "query_planner": BudgetedQueryPlanner(
                        ZhipuAgentQueryPlanner(
                            client=retrieval_client,
                            base_url=base_url,
                            api_key=api_key,
                            model=settings.ai_chat_model,
                            connect_timeout_seconds=0.5,
                            read_timeout_seconds=1.75,
                            total_timeout_seconds=2.0,
                            concurrency=min(settings.ai_provider_concurrency, 2),
                            max_attempts=1,
                        ),
                        budget,
                        failures,
                    ),
                    "text_reranker": BudgetedTextReranker(
                        ZhipuAgentTextReranker(
                            client=retrieval_client,
                            base_url=base_url,
                            api_key=api_key,
                            connect_timeout_seconds=0.5,
                            read_timeout_seconds=0.75,
                            total_timeout_seconds=1.0,
                            concurrency=min(settings.ai_provider_concurrency, 2),
                            max_attempts=1,
                        ),
                        budget,
                        failures,
                    ),
                }
            registry = build_postgres_agent_tool_registry(
                session_factory,
                brand_embeddings=embedding_cache,
                brand_retrieval_version=settings.brand_retrieval_version,
                **kwargs,
            )
            arms[arm] = _ArmRuntime(
                registry=registry,
                model_client=model_client,
                retrieval_client=retrieval_client,
                embedding_cache=embedding_cache,
            )
    except BaseException:
        pending_clients = tuple(
            client
            for name in ("model_client", "retrieval_client")
            if isinstance((client := locals().get(name)), httpx.AsyncClient)
        )
        await asyncio.gather(
            *(arm.close() for arm in arms.values()),
            *(client.aclose() for client in pending_clients),
            return_exceptions=True,
        )
        raise
    return _RuntimeBundle(engine=engine, arms=arms)


def _build_manifest(
    *,
    run_ref: str,
    git_sha: str,
    source_hash: str,
    worktree_dirty: bool,
    dataset_sha: str,
    oracle_sha: str,
    snapshot: Any,
    valid_on: date,
    registry_hash: str,
    settings: Settings,
    case_ids: tuple[str, ...],
) -> RunManifest:
    payload: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "evaluation_policy_version": EVALUATION_POLICY_VERSION,
        "execution_mode": EXECUTION_MODE,
        "run_ref": run_ref,
        "created_at": datetime.now(UTC),
        "git_sha": git_sha,
        "source_sha256": source_hash,
        "worktree_dirty": worktree_dirty,
        "dataset_sha256": dataset_sha,
        "oracle_sha256": oracle_sha,
        "database_snapshot": snapshot,
        "valid_on": valid_on,
        "registry_sha256": registry_hash,
        "selected_case_ids": case_ids,
        "arms": (ExperimentArm.RAW, ExperimentArm.ENHANCED),
        "agent_identity": ProviderIdentity(provider="zhipu", model=settings.ai_chat_model),
        "planner_identity": ProviderIdentity(provider="zhipu", model=settings.ai_chat_model),
        "reranker_identity": ProviderIdentity(provider="zhipu", model="rerank"),
        "embedding_identity": ProviderIdentity(
            provider="alibaba", model=settings.brand_embedding_model
        ),
        "brand_retrieval_version": settings.brand_retrieval_version,
        "limits": CapabilityLimits(),
    }
    provisional = RunManifest.model_construct(**payload, manifest_sha256="0" * 64)
    canonical = provisional.model_dump(mode="json", exclude={"manifest_sha256"})
    return RunManifest(**canonical, manifest_sha256=evidence_sha256(canonical))


def _validate_settings(settings: Settings) -> None:
    if settings.app_env != "development":
        raise PreflightError("live A/B is development-only")
    if settings.ai_provider_mode != "zhipu":
        raise PreflightError("live A/B requires the configured Zhipu provider")
    if settings.resolved_brand_embedding_provider_mode != "alibaba":
        raise PreflightError("live A/B requires Alibaba multimodal brand embedding")
    if settings.ai_platform_api_key is None or not settings.ai_platform_api_key.get_secret_value():
        raise PreflightError("Zhipu credentials are unavailable")
    if (
        settings.visual_embedding_api_key is None
        or not settings.visual_embedding_api_key.get_secret_value()
    ):
        raise PreflightError("Alibaba embedding credentials are unavailable")
    _require_local_postgres(settings.database_url.get_secret_value())
    _required_base_url(settings)


def _require_local_postgres(database_url: str) -> None:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgresql", "postgresql+asyncpg"} or parsed.hostname is None:
        raise PreflightError("live A/B requires a PostgreSQL database URL")
    hostname = parsed.hostname.casefold()
    if hostname == "localhost":
        return
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        raise PreflightError("live A/B requires a loopback PostgreSQL host") from None
    if not address.is_loopback:
        raise PreflightError("live A/B requires a loopback PostgreSQL host")


def _require_manifest_environment(manifest: RunManifest, settings: Settings) -> None:
    expected = {
        "agent": (manifest.agent_identity.provider, manifest.agent_identity.model),
        "planner": (manifest.planner_identity.provider, manifest.planner_identity.model),
        "reranker": (manifest.reranker_identity.provider, manifest.reranker_identity.model),
        "embedding": (manifest.embedding_identity.provider, manifest.embedding_identity.model),
    }
    current = {
        "agent": ("zhipu", settings.ai_chat_model),
        "planner": ("zhipu", settings.ai_chat_model),
        "reranker": ("zhipu", "rerank"),
        "embedding": ("alibaba", settings.brand_embedding_model),
    }
    if expected != current or manifest.brand_retrieval_version != settings.brand_retrieval_version:
        raise PreflightError("provider or retrieval configuration drifted after preflight")


def _required_base_url(settings: Settings) -> str:
    if settings.ai_platform_base_url is None:
        raise PreflightError("Zhipu base URL is unavailable")
    return settings.ai_platform_base_url


def _source_hash() -> str:
    digest = sha256()
    paths = tuple(FEATURE_ROOT.glob("*.py")) + tuple(
        REPOSITORY_ROOT / relative
        for relative in (
            "backend/app/agent_workbench_runtime.py",
            "backend/app/application/services/agent_retrieval.py",
            "backend/app/application/services/agent_tools.py",
            "backend/app/application/services/agent_workbench_graph.py",
            "backend/app/infrastructure/ai/agent_retrieval.py",
            "backend/app/infrastructure/ai/agent_workbench.py",
            "backend/app/infrastructure/db/agent_workbench.py",
        )
    )
    for path in sorted(paths):
        digest.update(str(path.relative_to(REPOSITORY_ROOT)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_identity() -> tuple[str, bool]:
    try:
        sha_value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PreflightError("git identity is unavailable") from exc
    return sha_value, dirty


def _require_hash(payload: bytes, expected: str, label: str) -> None:
    if sha256(payload).hexdigest() != expected:
        raise PreflightError(f"{label} hash does not match the manifest")


def _write_report_artifacts(
    run_dir: Path,
    report: Any,
    attempts: tuple[AttemptObservation, ...],
    *,
    replace: bool = False,
) -> None:
    json_text = safe_report_json(report)
    markdown = render_markdown(report)
    paths = {
        "metrics.json": json_text,
        "paired-report.md": markdown,
    }
    for name, value in paths.items():
        path = run_dir / name
        if replace and path.exists():
            path.unlink()
        write_text_exclusive(path, value)
    failure_path = run_dir / "failure-ledger.json"
    if (
        not report.complete
        or report.provider_failure_count
        or report.bounded_run_failure_count
        or report.executor_failure_count
    ):
        if replace and failure_path.exists():
            failure_path.unlink()
        write_json_exclusive(
            failure_path,
            {
                "status": "incomplete" if not report.complete else "completed_with_failures",
                "completed_attempts": report.completed_attempts,
                "started_attempts": report.started_attempt_count,
                "provider_failure_count": report.provider_failure_count,
                "bounded_run_failure_count": report.bounded_run_failure_count,
                "executor_failure_count": report.executor_failure_count,
                "resume_claims_allowed": False,
                "canary_passed": report.canary_passed,
                "circuit_breaker_reason": report.circuit_breaker_reason,
            },
        )
    elif replace and failure_path.exists():
        failure_path.unlink()
    artifact_hashes = {
        "attempt_count": len(attempts),
        "attempt_ledger_sha256": evidence_sha256(
            [
                item.model_dump(mode="json")
                for item in sorted(attempts, key=lambda row: row.attempt_ref)
            ]
        ),
        "metrics_sha256": sha256(json_text.encode("utf-8")).hexdigest(),
        "paired_report_sha256": sha256(markdown.encode("utf-8")).hexdigest(),
        "attempt_files_sha256": _attempt_files_hash(run_dir),
        "authorization_sha256": _file_hash(run_dir / "authorization.json"),
        "dataset_file_sha256": _file_hash(run_dir / "dataset.private.jsonl"),
        "manifest_file_sha256": _file_hash(run_dir / "manifest.json"),
        "oracle_file_sha256": _file_hash(run_dir / "oracle.private.jsonl"),
        "failure_ledger_sha256": (_file_hash(failure_path) if failure_path.exists() else None),
    }
    hash_path = run_dir / "artifact-hashes.json"
    if replace and hash_path.exists():
        hash_path.unlink()
    write_json_exclusive(hash_path, artifact_hashes)


def _attempt_files_hash(run_dir: Path) -> str:
    digest = sha256()
    for path in sorted((run_dir / "attempts").glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _sum_capability_counts(attempts: tuple[AttemptObservation, ...]) -> Any:
    from .models import CapabilityCounts

    return CapabilityCounts(
        agent=sum(item.capability_counts.agent for item in attempts),
        planner=sum(item.capability_counts.planner for item in attempts),
        reranker=sum(item.capability_counts.reranker for item in attempts),
        embedding=sum(item.capability_counts.embedding for item in attempts),
    )


def _is_started_journal(path: Path) -> bool:
    payload = load_raw_json(path)
    return isinstance(payload, dict) and payload.get("status") == "started"


def _recomputed_circuit_reason(
    attempts: tuple[AttemptObservation, ...],
    *,
    started_attempt_count: int,
) -> str | None:
    if len(attempts) + started_attempt_count > CANARY_ATTEMPTS or any(
        not item.canary for item in attempts
    ):
        raise PreflightError("compatibility artifact exceeds the two-cell authorization")
    canary = tuple(
        sorted(
            (item for item in attempts if item.canary),
            key=lambda item: item.schedule_ordinal,
        )
    )
    if len(canary) == CANARY_ATTEMPTS:
        return (
            "compatibility_canary_complete"
            if all(canary_attempt_passed(item) for item in canary)
            else "canary_failed"
        )
    if started_attempt_count:
        return "interrupted_attempt"
    if len(attempts) < 72:
        return "incomplete_artifact"
    return None


def _validate_started_journal(path: Path, manifest: RunManifest) -> None:
    payload = load_raw_json(path)
    expected = {
        "attempt_ref": path.stem,
        "manifest_sha256": manifest.manifest_sha256,
        "status": "started",
    }
    if payload != expected:
        raise PreflightError("started attempt journal failed its binding contract")


def _safe_cli_error_code(exc: Exception) -> str:
    if isinstance(exc, ArtifactError):
        return "artifact_contract_invalid"
    if isinstance(exc, DatasetBuildError):
        return "dataset_preflight_failed"
    if isinstance(exc, PreflightError):
        return "preflight_contract_failed"
    if isinstance(exc, ValidationError):
        return "schema_validation_failed"
    return "evaluation_contract_invalid"


if __name__ == "__main__":
    raise SystemExit(main())
