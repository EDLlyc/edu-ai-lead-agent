"""Evaluate topic selection against operator-labelled "should / should not select" news."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from app.application.services.topic_selection import build_topic_scoring_config
from app.core.config import Settings
from app.domain.editorial_relevance import (
    SCIENCE_TECH_EDITORIAL_RULE_VERSION,
    ScienceTechEditorialCohort,
    evaluate_product_matrix_fit_v2,
    evaluate_science_tech_editorial_relevance,
)
from app.domain.education_policy_signal import is_education_policy_title
from app.domain.topic_safety_signals import is_industrial_technology_title
from app.domain.topic_selection import (
    EDUCATION_POLICY_TOPIC_SCORING_VERSION,
    GOV_YAOWEN_TOPIC_SCORING_VERSION,
    QUALIFIED_AUTHORITATIVE_TOPIC_SCORING_VERSION,
    SAFETY_INDUSTRY_TOPIC_SCORING_VERSION,
    TopicCandidate,
    TopicScore,
    TopicScoringConfig,
    score_topic_candidate,
)
from app.infrastructure.db.topic_selection import _EDITORIAL_CATEGORY_TEXT

FEATURE_ROOT = Path(__file__).resolve().parent
CASES_PATH = FEATURE_ROOT / "cases.v1.jsonl"
CANONICAL_JSON_PATH = FEATURE_ROOT / "canonical-report.json"
CANONICAL_MARKDOWN_PATH = FEATURE_ROOT / "canonical-report.md"
REPORT_VERSION = "topic-golden-v1"
AS_OF = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
# `.11` pre-education-policy baseline, `.13` education policy, `.14` safety/industry,
# `.15` current default.
COMPARED_VERSIONS = (
    QUALIFIED_AUTHORITATIVE_TOPIC_SCORING_VERSION,
    EDUCATION_POLICY_TOPIC_SCORING_VERSION,
    SAFETY_INDUSTRY_TOPIC_SCORING_VERSION,
    GOV_YAOWEN_TOPIC_SCORING_VERSION,
)
_SOURCE_TRUST_WEIGHTS = {"A": 1.0, "B": 0.75}

Label = Literal["must_select", "should_not_select"]
# "eligibility": a rejected case must leave the pool. "priority": it may stay in the pool as a
# low-ranked filler but must not jump ahead through a priority rule (e.g. gov.cn 要闻 diplomacy).
RejectScope = Literal["eligibility", "priority"]


@dataclass(frozen=True, slots=True)
class GoldenCase:
    case_id: str
    label: Label
    expect_priority: bool
    category: str
    label_source: str
    synthetic: bool
    source_tiers: tuple[str, ...]
    topic_priority_policy: str | None
    title: str
    summary: str
    source_url: str | None
    facts: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    reject_scope: RejectScope = "eligibility"


def load_cases(path: Path = CASES_PATH) -> tuple[GoldenCase, ...]:
    cases: list[GoldenCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        label = raw["label"]
        if label not in {"must_select", "should_not_select"}:
            raise ValueError(f"line {line_number}: unsupported label {label!r}")
        tiers = tuple(raw["source_tiers"])
        if not tiers or any(tier not in _SOURCE_TRUST_WEIGHTS for tier in tiers):
            raise ValueError(f"line {line_number}: source tiers must be A/B")
        if label == "should_not_select" and raw["expect_priority"]:
            raise ValueError(f"line {line_number}: a rejected case cannot expect priority")
        reject_scope = raw.get("reject_scope", "eligibility")
        if reject_scope not in {"eligibility", "priority"} or (
            reject_scope != "eligibility" and label != "should_not_select"
        ):
            raise ValueError(f"line {line_number}: unsupported reject scope {reject_scope!r}")
        cases.append(
            GoldenCase(
                case_id=raw["case_id"],
                label=label,
                expect_priority=bool(raw["expect_priority"]),
                category=raw["category"],
                label_source=raw["label_source"],
                synthetic=bool(raw["synthetic"]),
                source_tiers=tiers,
                topic_priority_policy=raw["topic_priority_policy"],
                title=raw["title"],
                summary=raw["summary"],
                source_url=raw["source_url"],
                facts=tuple(raw.get("facts", ())),
                categories=tuple(raw.get("categories", ())),
                reject_scope=reject_scope,
            )
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("golden case IDs must be unique")
    return tuple(cases)


def build_candidate(case: GoldenCase, config: TopicScoringConfig) -> TopicCandidate:
    """Project a labelled headline the way the governed loader would, with neutral extras.

    The case is fresh (one day old), verified and backed by its listed A/B sources, so any
    rejection comes from the editorial/selection rules under test rather than a veto.
    """

    editorial_rule = config.effective_science_tech_editorial_rule_version
    # Same body the governed loader scores for `.11`/`.13`: summary, facts, category text.
    category_text = " ".join(_EDITORIAL_CATEGORY_TEXT.get(c, c) for c in case.categories)
    body = f"{case.summary}\n{' '.join(case.facts)}\n{category_text}"
    editorial = evaluate_science_tech_editorial_relevance(
        case.title,
        body,
        rule_version=editorial_rule or SCIENCE_TECH_EDITORIAL_RULE_VERSION,
    )
    product_fit = evaluate_product_matrix_fit_v2(case.title, body)
    trust = sum(_SOURCE_TRUST_WEIGHTS[tier] for tier in case.source_tiers) / len(case.source_tiers)
    return TopicCandidate(
        event_id=uuid5(NAMESPACE_URL, f"topic-golden:{case.case_id}"),
        event_version_id=uuid5(NAMESPACE_URL, f"topic-golden-version:{case.case_id}"),
        event_time=AS_OF - timedelta(days=1),
        source_trust=trust,
        source_diversity=len(case.source_tiers),
        ai_relevance=0.0,
        parent_relevance=0.0,
        communication_potential=min(
            1.0,
            0.35 + min(len(case.source_tiers), 4) * 0.12 + min(len(case.facts), 4) * 0.06,
        ),
        editorial_priority=editorial.editorial_priority_score,
        science_tech_editorial_cohort=editorial.cohort,
        science_tech_education_relevance=editorial.education_relevance_score,
        frontier_significance=editorial.frontier_significance_score,
        science_tech_editorial_reason_codes=editorial.reason_codes,
        science_tech_content_signals=editorial.content_signals,
        product_matrix_fit_v2=product_fit.score,
        product_matrix_v2_direction_ids=product_fit.direction_ids,
        topic_priority_policy=case.topic_priority_policy,
        priority_title=case.title,
        priority_summary=case.summary,
    )


def title_fetch_priority(title: str) -> str:
    """How the current acquisition would order this headline for a detail fetch."""

    cohort = evaluate_science_tech_editorial_relevance(title).cohort
    if cohort is ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY:
        return "education_title"
    if is_education_policy_title(title) or is_industrial_technology_title(title):
        return "policy_or_industry_title"
    if cohort is ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY:
        return "frontier_title"
    return "neutral_leftover"


def _case_passes(case: GoldenCase, score: TopicScore) -> bool:
    if case.label == "should_not_select":
        if case.reject_scope == "priority":
            return not score.priority_applied
        return not score.eligible
    return score.eligible and (score.priority_applied or not case.expect_priority)


def evaluate_version(cases: Sequence[GoldenCase], version: str) -> dict[str, object]:
    config = build_topic_scoring_config(Settings(_env_file=None, content_scoring_version=version))
    rows: list[dict[str, object]] = []
    for case in cases:
        score = score_topic_candidate(build_candidate(case, config), as_of=AS_OF, config=config)
        rows.append(
            {
                "case_id": case.case_id,
                "label": case.label,
                "expect_priority": case.expect_priority,
                "eligible": score.eligible,
                "priority_applied": score.priority_applied,
                "priority_reason": score.priority_reason,
                "cohort": (
                    score.science_tech_editorial_cohort.value
                    if score.science_tech_editorial_cohort is not None
                    else None
                ),
                "total": round(score.total, 6),
                "passed": _case_passes(case, score),
            }
        )
    must = [row for row in rows if row["label"] == "must_select"]
    must_priority = [row for row in must if row["expect_priority"]]
    rejected = [row for row in rows if row["label"] == "should_not_select"]
    return {
        "scoring_version": version,
        "must_select_eligible": f"{sum(bool(r['eligible']) for r in must)}/{len(must)}",
        "must_select_priority": (
            f"{sum(bool(r['priority_applied']) for r in must_priority)}/{len(must_priority)}"
        ),
        "should_not_select_rejected": (
            f"{sum(bool(r['passed']) for r in rejected)}/{len(rejected)}"
        ),
        "passed": f"{sum(bool(r['passed']) for r in rows)}/{len(rows)}",
        "failed_case_ids": [str(row["case_id"]) for row in rows if not row["passed"]],
        "cases": rows,
    }


def build_report(cases: Sequence[GoldenCase]) -> dict[str, object]:
    fetch = [
        {
            "case_id": case.case_id,
            "label": case.label,
            "fetch_priority": title_fetch_priority(case.title),
        }
        for case in cases
    ]
    must_fetch = [row for row in fetch if row["label"] == "must_select"]
    return {
        "report_version": REPORT_VERSION,
        "cases_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
        "case_count": len(cases),
        "operator_labelled_count": sum(not case.synthetic for case in cases),
        "acquisition": {
            "must_select_fetched_with_priority": (
                f"{sum(r['fetch_priority'] != 'neutral_leftover' for r in must_fetch)}"
                f"/{len(must_fetch)}"
            ),
            "cases": fetch,
        },
        "versions": [evaluate_version(cases, version) for version in COMPARED_VERSIONS],
    }


def canonical_json(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_markdown(report: dict[str, object], cases: Sequence[GoldenCase]) -> str:
    titles = {case.case_id: case.title for case in cases}
    acquisition = report["acquisition"]
    assert isinstance(acquisition, dict)
    lines = [
        "# Topic golden set",
        "",
        f"- Cases: {report['case_count']} ({report['operator_labelled_count']} operator-labelled "
        "real headlines, the rest rule-derived examples)",
        "- Must-select headlines fetched ahead of leftover capacity: "
        f"{acquisition['must_select_fetched_with_priority']}",
        "",
        "| Scoring version | Must select eligible | Must select with priority | "
        "Should-not rejected | Passed | Failing cases |",
        "|---|---|---|---|---|---|",
    ]
    versions = report["versions"]
    assert isinstance(versions, list)
    for version in versions:
        failing = ", ".join(version["failed_case_ids"]) or "none"
        lines.append(
            f"| `{version['scoring_version']}` | {version['must_select_eligible']} | "
            f"{version['must_select_priority']} | {version['should_not_select_rejected']} | "
            f"{version['passed']} | {failing} |"
        )
    lines += ["", "## Failing cases in the current default", ""]
    current = versions[-1]
    failing_rows = [row for row in current["cases"] if not row["passed"]]
    if not failing_rows:
        lines.append("None.")
    for row in failing_rows:
        lines.append(
            f"- `{row['case_id']}` {titles[str(row['case_id'])]} — expected {row['label']}"
            f"{' with priority' if row['expect_priority'] else ''}; got eligible="
            f"{row['eligible']}, priority={row['priority_applied']} ({row['priority_reason']}), "
            f"cohort={row['cohort']}"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="fail on report drift from the canonical copy"
    )
    mode.add_argument("--write-canonical", action="store_true")
    args = parser.parse_args(argv)

    cases = load_cases()
    report = build_report(cases)
    generated_json = canonical_json(report)
    generated_markdown = render_markdown(report, cases)
    if args.write_canonical:
        CANONICAL_JSON_PATH.write_text(generated_json, encoding="utf-8")
        CANONICAL_MARKDOWN_PATH.write_text(generated_markdown, encoding="utf-8")
    elif args.check:
        if CANONICAL_JSON_PATH.read_text(encoding="utf-8") != generated_json:
            print(
                "topic golden report drifted; review the change, then run --write-canonical",
                file=sys.stderr,
            )
            return 1
    print(generated_markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
