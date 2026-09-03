from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from app.domain.agent_workbench import (
    AgentCitation,
    AgentCitationKind,
    AgentClaim,
    AgentClaimKind,
    AgentRunMetrics,
    AgentRunResult,
    AgentRunStatus,
    AgentTraceKind,
    AgentTraceStatus,
    AgentTraceStep,
)
from evals.agent_retrieval_live_ab.dataset import (
    DatasetBuildError,
    require_canary_qrel_contract,
    require_dataset_contract,
)
from evals.agent_retrieval_live_ab.harness import (
    CapabilityBudget,
    CapabilityBudgetExhausted,
    build_schedule,
    canary_attempt_passed,
    score_result,
)
from evals.agent_retrieval_live_ab.io import (
    ArtifactError,
    create_run_directory,
    load_json_model,
    require_output_path,
    write_json_exclusive,
)
from evals.agent_retrieval_live_ab.metrics import _paired_estimate, build_paired_report
from evals.agent_retrieval_live_ab.models import (
    AGENT_MODEL_TURNS_PER_ATTEMPT,
    AGENT_TOOL_CALLS_PER_ATTEMPT,
    ATTEMPT_SCHEMA_VERSION,
    AUTHORIZATION_SCHEMA_VERSION,
    CASE_SCHEMA_VERSION,
    LIVE_AUTHORIZATION_ACKNOWLEDGEMENT,
    MAX_AGENT_ATTEMPTS,
    MAX_AGENT_DECISIONS,
    ORACLE_SCHEMA_VERSION,
    AttemptExecutionStatus,
    AttemptObservation,
    AttemptScore,
    Capability,
    CapabilityCounts,
    CapabilityLimits,
    CaseCategory,
    CaseOracle,
    ExpectedTerminal,
    ExperimentArm,
    LiveAbCase,
    LiveAuthorization,
    RelevanceQrel,
    SafeClaimObservation,
    SafeToolObservation,
    TargetKind,
)
from evals.agent_retrieval_live_ab.privacy import (
    PrivacyScanError,
    require_aggregate_safe,
)
from evals.agent_retrieval_live_ab.reporting import render_markdown
from evals.agent_retrieval_live_ab.runner import (
    PreflightError,
    _compatibility_schedule,
    _recomputed_circuit_reason,
)

_HASH = "a" * 64


def _cases_and_oracles() -> tuple[tuple[LiveAbCase, ...], tuple[CaseOracle, ...]]:
    categories = (
        CaseCategory.EVIDENCE,
        CaseCategory.EVENT,
        CaseCategory.BRAND,
        CaseCategory.MULTI_TOOL,
        CaseCategory.COPY_VALIDATION,
        CaseCategory.SAFETY,
    )
    cases: list[LiveAbCase] = []
    oracles: list[CaseOracle] = []
    for category in categories:
        for index in range(2):
            case_id = f"{category.value}-{index}"
            retrieval = category not in {
                CaseCategory.COPY_VALIDATION,
                CaseCategory.SAFETY,
            }
            expected = (
                ExpectedTerminal.REFUSED
                if category is CaseCategory.SAFETY
                else ExpectedTerminal.COMPLETED
            )
            cases.append(
                LiveAbCase(
                    schema_version=CASE_SCHEMA_VERSION,
                    case_id=case_id,
                    category=category,
                    query=f"question {case_id}",
                    retrieval_sensitive=retrieval,
                )
            )
            oracles.append(
                CaseOracle(
                    schema_version=ORACLE_SCHEMA_VERSION,
                    case_id=case_id,
                    expected_terminal=expected,
                    expect_refusal=expected is ExpectedTerminal.REFUSED,
                    qrels=(
                        (
                            RelevanceQrel(
                                target_kind=TargetKind.EVIDENCE,
                                target_id=f"evidence-{case_id}",
                                relevance=3,
                            ),
                        )
                        if category in {CaseCategory.EVIDENCE, CaseCategory.EVENT}
                        else (
                            (
                                RelevanceQrel(
                                    target_kind=TargetKind.BRAND,
                                    target_id=f"brand-{case_id}",
                                    relevance=3,
                                ),
                            )
                            if category is CaseCategory.BRAND
                            else (
                                (
                                    RelevanceQrel(
                                        target_kind=TargetKind.EVIDENCE,
                                        target_id=f"evidence-{case_id}",
                                        relevance=3,
                                    ),
                                    RelevanceQrel(
                                        target_kind=TargetKind.BRAND,
                                        target_id=f"brand-{case_id}",
                                        relevance=3,
                                    ),
                                )
                                if category is CaseCategory.MULTI_TOOL
                                else ()
                            )
                        )
                    ),
                )
            )
    return tuple(cases), tuple(oracles)


def _attempt(
    case: LiveAbCase,
    *,
    arm: ExperimentArm,
    repetition: int,
    passed: bool,
) -> AttemptObservation:
    cases, _ = _cases_and_oracles()
    plan = next(
        item
        for item in build_schedule(tuple(row.case_id for row in cases))
        if item.case_id == case.case_id and item.repetition == repetition and item.arm is arm
    )
    retrieval_value = float(passed) if case.retrieval_sensitive else None
    score = AttemptScore(
        task_success=passed,
        terminal_match=True,
        tool_precision=1,
        tool_recall=1,
        argument_valid_rate=1,
        citation_precision=1,
        citation_coverage=retrieval_value or 1,
        unsupported_claim_rate=0,
        refusal_correct=True,
        hit_at_3=retrieval_value,
        recall_at_3=retrieval_value,
        mrr_at_3=retrieval_value,
        ndcg_at_3=retrieval_value,
        target_citation_coverage=retrieval_value,
        failure_codes=() if passed else ("target_not_retrieved_at_3",),
    )
    return AttemptObservation(
        schema_version=ATTEMPT_SCHEMA_VERSION,
        attempt_ref=f"{case.case_id}.r{repetition}.{arm.value}",
        schedule_ordinal=plan.ordinal,
        canary=plan.canary,
        manifest_sha256=_HASH,
        authorization_sha256="b" * 64,
        case_id=case.case_id,
        repetition=repetition,
        arm=arm,
        execution_status=AttemptExecutionStatus.COMPLETED,
        terminal_status="completed",
        summary_sha256="c" * 64,
        tools=(
            SafeToolObservation(
                name="search_evidence",
                succeeded=True,
                citation_ids=("target",),
            ),
        ),
        claims=(
            SafeClaimObservation(
                kind="external_fact",
                text_sha256="d" * 64,
                citation_ids=("target",),
            ),
        ),
        observed_citation_ids=("target",),
        duration_ms=10,
        model_latency_ms=5,
        tool_latency_ms=5,
        prompt_tokens=10,
        completion_tokens=4,
        reasoning_tokens=0,
        capability_counts=CapabilityCounts(agent=2),
        embedding_cache_hits=0,
        embedding_cache_misses=0,
        score=score,
    )


def test_dataset_contract_requires_twelve_balanced_cases() -> None:
    cases, oracles = _cases_and_oracles()

    require_dataset_contract(cases, oracles)

    with pytest.raises(DatasetBuildError, match="exactly twelve"):
        require_dataset_contract(cases[:-1], oracles[:-1])

    oversized = oracles[0].model_copy(
        update={
            "qrels": tuple(
                RelevanceQrel(
                    target_kind=TargetKind.EVIDENCE,
                    target_id=f"evidence-overflow-{index}",
                    relevance=3,
                )
                for index in range(4)
            )
        }
    )
    with pytest.raises(DatasetBuildError, match="Top-3 oracle"):
        require_canary_qrel_contract((oversized, *oracles[1:]))


def test_schedule_is_deterministic_paired_and_bounded() -> None:
    cases, _ = _cases_and_oracles()
    case_ids = tuple(case.case_id for case in cases)

    first = build_schedule(case_ids)
    second = build_schedule(case_ids)

    assert first == second
    assert len(first) == 72
    cells = Counter((item.case_id, item.repetition) for item in first)
    assert set(cells.values()) == {2}
    assert [item.ordinal for item in first] == list(range(1, 73))
    assert tuple(item.canary for item in first[:3]) == (True, True, False)
    assert first[0].case_id == first[1].case_id
    assert first[0].repetition == first[1].repetition == 1
    for offset in range(0, len(first), 2):
        assert {first[offset].arm, first[offset + 1].arm} == set(ExperimentArm)


def test_compatibility_capability_budget_denies_before_the_ninth_agent_call() -> None:
    assert AGENT_MODEL_TURNS_PER_ATTEMPT == 4
    assert AGENT_TOOL_CALLS_PER_ATTEMPT == 4
    assert MAX_AGENT_DECISIONS == MAX_AGENT_ATTEMPTS * AGENT_MODEL_TURNS_PER_ATTEMPT
    limits = CapabilityLimits()
    assert limits.agent_attempts == 2
    assert limits.agent_decisions == 8
    budget = CapabilityBudget()
    for _ in range(limits.agent_decisions):
        budget.consume(Capability.AGENT)

    with pytest.raises(CapabilityBudgetExhausted):
        budget.consume(Capability.AGENT)

    assert budget.snapshot().agent == limits.agent_decisions


def test_v3_compatibility_schedule_hard_stops_at_one_ab_pair() -> None:
    cases, _ = _cases_and_oracles()

    selected = _compatibility_schedule(tuple(case.case_id for case in cases))

    assert len(selected) == 2
    assert {item.arm for item in selected} == set(ExperimentArm)
    assert {item.ordinal for item in selected} == {1, 2}
    assert len({(item.case_id, item.repetition) for item in selected}) == 1


def test_v3_authorization_is_hash_bound_and_limited_to_two_attempts() -> None:
    authorization = LiveAuthorization(
        schema_version=AUTHORIZATION_SCHEMA_VERSION,
        manifest_sha256=_HASH,
        approved_at=datetime.now(UTC),
        approved_by_ref="unit-test",
        acknowledgement=LIVE_AUTHORIZATION_ACKNOWLEDGEMENT,
    )

    assert authorization.agent_attempt_limit == 2
    with pytest.raises(ValueError):
        LiveAuthorization.model_validate(
            {
                **authorization.model_dump(mode="json"),
                "schema_version": "agent-retrieval-live-ab-authorization-v2",
                "agent_attempt_limit": 72,
                "acknowledgement": "I_AUTHORIZE_AGENT_RETRIEVAL_LIVE_AB_V2",
            }
        )


def test_canary_requires_complete_terminal_tool_retrieval_and_citation_contract() -> None:
    cases, _ = _cases_and_oracles()
    passed = _attempt(cases[0], arm=ExperimentArm.RAW, repetition=1, passed=True)
    missed_target = _attempt(cases[0], arm=ExperimentArm.RAW, repetition=1, passed=False)

    assert passed.canary is True
    assert canary_attempt_passed(passed) is True
    assert canary_attempt_passed(missed_target) is False
    partial_citation = passed.model_copy(
        update={"score": passed.score.model_copy(update={"target_citation_coverage": 0.5})}
    )
    assert canary_attempt_passed(partial_citation) is False


def test_paired_estimate_uses_cases_not_attempts_as_bootstrap_units() -> None:
    cases, _ = _cases_and_oracles()
    attempts = tuple(
        _attempt(
            case,
            arm=arm,
            repetition=repetition,
            passed=(
                not case.retrieval_sensitive or arm is ExperimentArm.ENHANCED or case is cases[0]
            ),
        )
        for case in cases
        for repetition in range(1, 4)
        for arm in ExperimentArm
    )

    estimate = _paired_estimate(
        attempts=attempts,
        case_ids=tuple(case.case_id for case in cases if case.retrieval_sensitive),
        getter=lambda item: item.score.recall_at_3 or 0.0,
        complete=True,
        seed=20260902,
    )

    assert estimate.delta == pytest.approx(0.875)
    assert estimate.ci_low is not None
    assert estimate.ci_low > 0


def test_incomplete_report_does_not_zero_impute_missing_paired_cases() -> None:
    cases, _ = _cases_and_oracles()
    first = build_schedule(tuple(case.case_id for case in cases))[0]
    attempts = (
        _attempt(
            cases[0],
            arm=first.arm,
            repetition=first.repetition,
            passed=True,
        ),
    )

    report = build_paired_report(
        run_ref="incomplete-run",
        manifest_sha256=_HASH,
        cases=cases,
        attempts=attempts,
        capability_counts=CapabilityCounts(agent=2),
        started_attempt_count=1,
    )

    estimate = report.retrieval_estimates["recall_at_3"]
    assert report.complete is False
    assert report.canary_passed is False
    assert report.capability_counts_complete is False
    assert estimate.paired_case_count == 0
    assert estimate.expected_case_count == 8
    assert estimate.raw is None
    assert estimate.delta is None
    assert estimate.ci_low is None
    assert "| recall_at_3 | N/A | N/A | N/A | N/A | 0/8 |" in render_markdown(report)


def test_failed_canary_emits_incomplete_no_uplift_evidence() -> None:
    cases, _ = _cases_and_oracles()
    schedule = build_schedule(tuple(case.case_id for case in cases))
    first_pair = tuple(
        _attempt(
            cases[0],
            arm=plan.arm,
            repetition=plan.repetition,
            passed=False,
        ).model_copy(
            update={
                "terminal_status": "failed",
                "error_code": (
                    "agent_model_unavailable"
                    if plan.arm is ExperimentArm.RAW
                    else "agent_model_invalid_output"
                ),
            }
        )
        for plan in schedule[:2]
    )

    report = build_paired_report(
        run_ref="canary-failed",
        manifest_sha256=_HASH,
        cases=cases,
        attempts=first_pair,
        capability_counts=CapabilityCounts(agent=4),
        circuit_breaker_reason="canary_failed",
    )

    assert report.complete is False
    assert report.canary_passed is False
    assert report.circuit_breaker_reason == "canary_failed"
    assert report.terminal_failure_counts_by_arm == {
        "raw_query": {"agent_model_unavailable": 1},
        "rewrite_rrf_rerank": {"agent_model_invalid_output": 1},
    }
    assert all(
        not estimate.supports_uplift_claim for estimate in report.retrieval_estimates.values()
    )
    assert "remaining cells were not executed" in report.conclusion
    markdown = render_markdown(report)
    assert "Completed authorized compatibility attempts: 2/2" in markdown
    assert "Full paired-matrix coverage: 2/72" in markdown
    assert "Mandatory first-pair canary passed: `false`" in markdown
    assert "Circuit breaker: `canary_failed`" in markdown
    assert "`raw_query` / `agent_model_unavailable`: 1" in markdown
    assert "`rewrite_rrf_rerank` / `agent_model_invalid_output`: 1" in markdown


def test_report_rejects_schedule_ordinal_or_canary_tampering() -> None:
    cases, _ = _cases_and_oracles()
    attempt = _attempt(cases[0], arm=ExperimentArm.RAW, repetition=1, passed=True)
    tampered = attempt.model_copy(update={"schedule_ordinal": 72, "canary": False})

    with pytest.raises(ValueError, match="manifest-bound schedule"):
        build_paired_report(
            run_ref="tampered-schedule",
            manifest_sha256=_HASH,
            cases=cases,
            attempts=(tampered,),
            capability_counts=CapabilityCounts(agent=2),
        )


def test_v3_report_rejects_attempts_beyond_the_compatibility_pair() -> None:
    cases, _ = _cases_and_oracles()
    schedule = build_schedule(tuple(case.case_id for case in cases))
    attempts: list[AttemptObservation] = []
    for plan in schedule[:6]:
        base = _attempt(
            cases[0],
            arm=plan.arm,
            repetition=plan.repetition,
            passed=True,
        )
        if plan.ordinal > 2:
            base = base.model_copy(
                update={
                    "execution_status": AttemptExecutionStatus.FAILED,
                    "terminal_status": "failed",
                    "error_code": "agent_model_unavailable",
                    "score": base.score.model_copy(update={"task_success": False}),
                }
            )
        attempts.append(base)

    with pytest.raises(PreflightError, match="two-cell authorization"):
        _recomputed_circuit_reason(tuple(attempts), started_attempt_count=0)
    with pytest.raises(ValueError, match="two-cell compatibility authorization"):
        build_paired_report(
            run_ref="over-authorized",
            manifest_sha256=_HASH,
            cases=cases,
            attempts=tuple(attempts),
            capability_counts=CapabilityCounts(agent=8),
        )


def test_v3_report_rejects_capability_count_drift() -> None:
    cases, _ = _cases_and_oracles()
    schedule = build_schedule(tuple(case.case_id for case in cases))
    first_pair = tuple(
        _attempt(
            cases[0],
            arm=plan.arm,
            repetition=plan.repetition,
            passed=True,
        )
        for plan in schedule[:2]
    )

    with pytest.raises(ValueError, match="terminal attempt ledger"):
        build_paired_report(
            run_ref="count-drift",
            manifest_sha256=_HASH,
            cases=cases,
            attempts=first_pair,
            capability_counts=CapabilityCounts(agent=3),
        )
    with pytest.raises(ValueError, match="exceed the authorization"):
        build_paired_report(
            run_ref="count-overflow",
            manifest_sha256=_HASH,
            cases=cases,
            attempts=first_pair,
            capability_counts=CapabilityCounts(agent=9),
        )


def test_aggregate_privacy_scanner_rejects_uuid_and_secret_shapes() -> None:
    with pytest.raises(PrivacyScanError):
        require_aggregate_safe("event=10000000-0000-4000-8000-000000000001")
    with pytest.raises(PrivacyScanError):
        require_aggregate_safe("api_key=secret-value")


def test_multi_tool_top_three_is_scored_per_retrieval_namespace() -> None:
    case = LiveAbCase(
        schema_version=CASE_SCHEMA_VERSION,
        case_id="multi-tool",
        category=CaseCategory.MULTI_TOOL,
        query="combine evidence and brand context",
        retrieval_sensitive=True,
    )
    oracle = CaseOracle(
        schema_version=ORACLE_SCHEMA_VERSION,
        case_id=case.case_id,
        required_tools=("search_evidence", "retrieve_brand_context"),
        allowed_tools=("search_evidence", "retrieve_brand_context"),
        qrels=(
            RelevanceQrel(target_kind=TargetKind.EVIDENCE, target_id="e1", relevance=3),
            RelevanceQrel(target_kind=TargetKind.BRAND, target_id="b1", relevance=3),
        ),
        expected_terminal=ExpectedTerminal.COMPLETED,
        expect_refusal=False,
    )
    result = AgentRunResult(
        run_id=UUID("10000000-0000-4000-8000-000000000001"),
        status=AgentRunStatus.COMPLETED,
        summary="grounded",
        claims=(
            AgentClaim("fact", AgentClaimKind.EXTERNAL_FACT, ("e1",)),
            AgentClaim("brand", AgentClaimKind.BRAND_STATEMENT, ("b1",)),
        ),
        citations=(
            AgentCitation(
                "e1",
                AgentCitationKind.EVIDENCE,
                "source",
                "evidence",
                "https://example.com/e1",
                True,
            ),
            AgentCitation(
                "b1",
                AgentCitationKind.BRAND_CONTEXT,
                "brand",
                "context",
                None,
                False,
            ),
        ),
        steps=(
            AgentTraceStep(
                1,
                AgentTraceKind.TOOL_CALL,
                AgentTraceStatus.SUCCEEDED,
                tool_name="search_evidence",
                call_id="c1",
            ),
            AgentTraceStep(
                2,
                AgentTraceKind.TOOL_RESULT,
                AgentTraceStatus.SUCCEEDED,
                tool_name="search_evidence",
                call_id="c1",
                citation_ids=("e1", "e2", "e3"),
            ),
            AgentTraceStep(
                3,
                AgentTraceKind.TOOL_CALL,
                AgentTraceStatus.SUCCEEDED,
                tool_name="retrieve_brand_context",
                call_id="c2",
            ),
            AgentTraceStep(
                4,
                AgentTraceKind.TOOL_RESULT,
                AgentTraceStatus.SUCCEEDED,
                tool_name="retrieve_brand_context",
                call_id="c2",
                citation_ids=("b1", "b2", "b3"),
            ),
        ),
        metrics=AgentRunMetrics(2, 2, 2, 10, 5, 0, 10, 4, 15),
    )

    score = score_result(case, oracle, result)

    assert score.hit_at_3 == 1
    assert score.recall_at_3 == 1
    assert score.ndcg_at_3 == 1
    assert score.target_citation_coverage == 1
    assert score.task_success is True


def test_private_artifact_io_rejects_symlinks_and_broad_permissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evals.agent_retrieval_live_ab import io

    output_root = tmp_path / "private-output"
    output_root.mkdir(mode=0o700)
    monkeypatch.setattr(io, "OUTPUT_ROOT", output_root)
    run_dir = create_run_directory(output_root / "run")
    artifact = run_dir / "manifest.json"
    write_json_exclusive(artifact, {"ok": True})
    artifact.chmod(0o644)

    with pytest.raises(ArtifactError, match="private regular files"):
        load_json_model(artifact, CapabilityCounts)

    target = output_root / "target"
    target.mkdir(mode=0o700)
    link = run_dir / "linked"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ArtifactError, match="symbolic links"):
        require_output_path(link / "attempt.json")
