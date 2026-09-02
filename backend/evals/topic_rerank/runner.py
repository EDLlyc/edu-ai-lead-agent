"""Run the provider-free topic-rerank fixture contract evaluation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.application.services.topic_reranking import execute_topic_rerank
from app.domain.content_slots import (
    ContentSlot,
    ContentSlotDecision,
    SlotRankingPolicy,
    select_slot_topics,
)
from app.domain.editorial_relevance import ScienceTechEditorialCohort
from app.domain.ministry_education_priority import (
    MOE_SCIENCE_TOP1_PRIORITY_POLICY,
)
from app.domain.topic_rerank import (
    TopicRerankCandidate,
    TopicRerankConfig,
    TopicRerankOutcomeKind,
    TopicRerankRequest,
    build_daily_rerank_pool,
    build_slot_rerank_pool,
    finalize_content_slot_rerank,
    finalize_daily_topic_rerank,
)
from app.domain.topic_selection import (
    QUALIFIED_AUTHORITATIVE_PRIORITY_RULE_VERSION,
    DailyTopicDecision,
    TopicCandidate,
    TopicScoringConfig,
    select_daily_topic,
)
from app.infrastructure.ai.topic_rerank import DeterministicFakeTopicReranker
from pydantic import BaseModel, ConfigDict, Field, ValidationError

FEATURE_ROOT = Path(__file__).resolve().parent
CASES_PATH = FEATURE_ROOT / "cases.v1.jsonl"
CANONICAL_JSON_PATH = FEATURE_ROOT / "canonical-report.json"
CANONICAL_MARKDOWN_PATH = FEATURE_ROOT / "canonical-report.md"
NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)
CONFIG = TopicScoringConfig(
    selection_priority_rule_version=QUALIFIED_AUTHORITATIVE_PRIORITY_RULE_VERSION
)
RERANK_CONFIG = TopicRerankConfig(
    enabled=True,
    provider="fake",
    model="fake-rerank-v1",
)

EvalContext = Literal["daily", "morning", "noon", "evening"]
EvalScenario = Literal["reorder", "priority", "hard_veto", "same_day", "fallback"]
ExpectedOutcome = Literal["applied", "fallback"]


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=r"^[a-z0-9-]+$", min_length=1, max_length=80)
    context: EvalContext
    scenario: EvalScenario
    expected_outcome: ExpectedOutcome
    expected_candidate_count: int = Field(ge=0, le=8)
    expected_final_suffixes: tuple[int, ...] = Field(max_length=8)
    expected_excluded_suffixes: tuple[int, ...] = Field(max_length=8)


def _candidate(
    suffix: int,
    *,
    editorial: float = 1.0,
    product: float = 1.0,
    communication: float = 0.0,
    priority: bool = False,
    veto: bool = False,
) -> TopicCandidate:
    return TopicCandidate(
        event_id=UUID(f"00000000-0000-4000-8000-{suffix:012d}"),
        event_version_id=UUID(f"10000000-0000-4000-8000-{suffix:012d}"),
        event_time=NOW,
        source_trust=1.0,
        source_diversity=4,
        ai_relevance=1.0,
        parent_relevance=1.0,
        communication_potential=communication,
        editorial_priority=editorial,
        science_tech_editorial_cohort=(
            ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY
        ),
        science_tech_education_relevance=1.0,
        frontier_significance=0.5,
        science_tech_editorial_reason_codes=("explicit_science_technology_education",),
        product_matrix_fit_v2=product,
        product_matrix_v2_direction_ids=("science_exploration_courses_and_camps",),
        topic_priority_policy=(MOE_SCIENCE_TOP1_PRIORITY_POLICY if priority else None),
        priority_title=("人工智能教育课程实施方案" if priority else f"合成候选 {suffix}"),
        priority_summary=(
            "推动中小学人工智能课程教学实践。"
            if priority
            else "仅用于离线契约检查的治理后合成摘要。"
        ),
        prohibited_marketing_risk=veto,
    )


def _fixture_candidates(case: EvalCase) -> tuple[TopicCandidate, ...]:
    candidates = [
        _candidate(1, priority=case.scenario == "priority"),
        _candidate(2, editorial=0.8, product=0.8, communication=1.0),
    ]
    if case.scenario == "hard_veto":
        candidates.append(_candidate(3, communication=1.0, veto=True))
    elif case.scenario == "same_day":
        candidates.append(_candidate(3, communication=1.0))
    return tuple(candidates)


async def _evaluate_case(case: EvalCase) -> dict[str, object]:
    candidates = _fixture_candidates(case)
    daily_decision: DailyTopicDecision | None = None
    slot_decision: ContentSlotDecision | None = None
    pool: tuple[TopicRerankCandidate, ...]
    if case.context == "daily":
        daily_decision = select_daily_topic(candidates, as_of=NOW, config=CONFIG)
        pool = build_daily_rerank_pool(daily_decision, candidates, limit=8)
    else:
        slot = ContentSlot(case.context)
        same_day_ids = (
            frozenset({candidates[-1].event_id}) if case.scenario == "same_day" else frozenset()
        )
        slot_decision = select_slot_topics(
            candidates,
            as_of=NOW,
            config=CONFIG,
            slot=slot,
            policy=SlotRankingPolicy(),
            max_items=3,
            same_day_selected_event_ids=same_day_ids,
        )
        pool = build_slot_rerank_pool(slot_decision, candidates, limit=8)
    request = TopicRerankRequest(
        run_id=UUID("20000000-0000-4000-8000-000000000001"),
        cutoff_at=NOW,
        context=case.context,
        policy_version=RERANK_CONFIG.policy_version,
        max_output_tokens=RERANK_CONFIG.max_output_tokens,
        candidates=pool,
    )
    reranker = (
        None
        if case.scenario == "fallback"
        else DeterministicFakeTopicReranker(model=RERANK_CONFIG.model)
    )
    outcome = await execute_topic_rerank(
        config=RERANK_CONFIG,
        reranker=reranker,
        request=request,
    )
    selected_ids: tuple[UUID, ...]
    if case.context == "daily":
        if daily_decision is None:
            raise RuntimeError("daily eval decision is missing")
        final, outcome = finalize_daily_topic_rerank(
            daily_decision,
            pool,
            outcome,
            request=request,
            candidate_limit=RERANK_CONFIG.candidate_limit,
        )
        selected_ids = (final.selected_event_id,) if final.selected_event_id is not None else ()
    else:
        if slot_decision is None:
            raise RuntimeError("slot eval decision is missing")
        final_slot, outcome = finalize_content_slot_rerank(
            slot_decision,
            pool,
            outcome,
            request=request,
            candidate_limit=RERANK_CONFIG.candidate_limit,
            max_items=3,
        )
        selected_ids = final_slot.selected_event_ids

    final_suffixes = tuple(_suffix(event_id) for event_id in outcome.final_order)
    pool_ids = frozenset(candidate.event_id for candidate in pool)
    excluded_absent = all(
        _event_id(suffix) not in pool_ids for suffix in case.expected_excluded_suffixes
    )
    groups = tuple(candidate.priority_group for candidate in pool)
    final_groups = tuple(
        {candidate.event_id: candidate.priority_group for candidate in pool}[event_id]
        for event_id in outcome.final_order
    )
    priority_fixture_groups_are_distinct = case.scenario != "priority" or len(set(groups)) >= 2
    priority_barrier_preserved = final_groups == tuple(sorted(final_groups))
    exact_permutation = len(outcome.final_order) == len(pool) and set(outcome.final_order) == set(
        pool_ids
    )
    fallback_preserved = (
        outcome.base_order == outcome.final_order
        if outcome.kind is TopicRerankOutcomeKind.FALLBACK
        else True
    )
    selected_respects_pool = set(selected_ids).issubset(
        {candidate.event_id for candidate in candidates if candidate.event_id in pool_ids}
    )
    checks = {
        "outcome": outcome.kind.value == case.expected_outcome,
        "candidate_count": outcome.candidate_count == case.expected_candidate_count,
        "final_order": final_suffixes == case.expected_final_suffixes,
        "exact_permutation": exact_permutation,
        "priority_fixture_groups_are_distinct": priority_fixture_groups_are_distinct,
        "priority_barrier": priority_barrier_preserved,
        "hard_exclusions": excluded_absent,
        "fallback_parity": fallback_preserved,
        "selection_boundary": selected_respects_pool,
    }
    return {
        "case_id": case.case_id,
        "context": case.context,
        "scenario": case.scenario,
        "outcome": outcome.kind.value,
        "candidate_count": outcome.candidate_count,
        "base_order_suffixes": [_suffix(event_id) for event_id in outcome.base_order],
        "final_order_suffixes": list(final_suffixes),
        "priority_groups": list(groups),
        "final_priority_groups": list(final_groups),
        "failure_code": outcome.failure_code.value if outcome.failure_code else None,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _event_id(suffix: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{suffix:012d}")


def _suffix(event_id: UUID) -> int:
    return int(str(event_id).rsplit("-", maxsplit=1)[1])


def load_cases(path: Path = CASES_PATH) -> tuple[tuple[EvalCase, ...], bytes]:
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("topic rerank eval dataset is unreadable") from exc
    cases: list[EvalCase] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"blank topic rerank eval record at line {line_number}")
        try:
            raw = json.loads(line)
            cases.append(EvalCase.model_validate(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"invalid topic rerank eval record at line {line_number}") from exc
    if len(cases) < 8 or len({case.case_id for case in cases}) != len(cases):
        raise ValueError("topic rerank eval requires eight unique contract cases")
    required_contexts = {"daily", "morning", "noon", "evening"}
    required_scenarios = {"priority", "hard_veto", "same_day", "fallback"}
    if not required_contexts.issubset({case.context for case in cases}):
        raise ValueError("topic rerank eval is missing a required context")
    if not required_scenarios.issubset({case.scenario for case in cases}):
        raise ValueError("topic rerank eval is missing a required safety scenario")
    return tuple(sorted(cases, key=lambda case: case.case_id)), payload


async def build_report(path: Path = CASES_PATH) -> dict[str, object]:
    cases, payload = load_cases(path)
    results = [await _evaluate_case(case) for case in cases]
    failed = [str(result["case_id"]) for result in results if result["passed"] is not True]
    return {
        "claim": "fixture_contract_conformance_only",
        "disclaimer": (
            "Provider-free synthetic fixtures verify safety and structure contracts only; "
            "this is not evidence of live-model editorial quality or production accuracy."
        ),
        "dataset_sha256": hashlib.sha256(payload).hexdigest(),
        "policy_version": RERANK_CONFIG.policy_version,
        "case_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_case_ids": failed,
        "cases": results,
    }


def canonical_json(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_markdown(report: dict[str, object]) -> str:
    cases = report["cases"]
    if not isinstance(cases, list):
        raise ValueError("topic rerank eval report cases are invalid")
    lines = [
        "# Topic rerank fixture contract conformance",
        "",
        f"> {report['disclaimer']}",
        "",
        f"- Policy: `{report['policy_version']}`",
        f"- Dataset SHA-256: `{report['dataset_sha256']}`",
        f"- Result: {report['passed_count']}/{report['case_count']} passing",
        "- Volatile latency and token counts are intentionally excluded.",
        "",
        "| Case | Context | Scenario | Outcome | Candidates | Pass |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for raw_case in cases:
        if not isinstance(raw_case, dict):
            raise ValueError("topic rerank eval case report is invalid")
        lines.append(
            f"| `{raw_case['case_id']}` | `{raw_case['context']}` | "
            f"`{raw_case['scenario']}` | `{raw_case['outcome']}` | "
            f"{raw_case['candidate_count']} | "
            f"{'yes' if raw_case['passed'] is True else 'no'} |"
        )
    lines.extend(
        [
            "",
            "These checked fixtures demonstrate bounded permutations, hard-rule exclusion, "
            "priority barriers, daily/slot sharing, and deterministic fallback only.",
            "",
        ]
    )
    return "\n".join(lines)


def _artifacts_match(generated_json: str, generated_markdown: str) -> bool:
    try:
        return (
            CANONICAL_JSON_PATH.read_text(encoding="utf-8") == generated_json
            and CANONICAL_MARKDOWN_PATH.read_text(encoding="utf-8") == generated_markdown
        )
    except OSError:
        return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-canonical", action="store_true")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(build_report(args.cases))
        generated_json = canonical_json(report)
        generated_markdown = render_markdown(report)
    except (RuntimeError, ValueError) as exc:
        print(f"topic rerank eval failed: {exc}", file=sys.stderr)
        return 1
    failed = report["failed_case_ids"]
    if failed:
        print(f"topic rerank eval failed cases: {failed}", file=sys.stderr)
        return 1
    if args.write_canonical:
        CANONICAL_JSON_PATH.write_text(generated_json, encoding="utf-8")
        CANONICAL_MARKDOWN_PATH.write_text(generated_markdown, encoding="utf-8")
    elif args.check and not _artifacts_match(generated_json, generated_markdown):
        print("topic rerank eval canonical report drifted", file=sys.stderr)
        return 1
    print(f"topic rerank eval passed: {report['passed_count']}/{report['case_count']} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
