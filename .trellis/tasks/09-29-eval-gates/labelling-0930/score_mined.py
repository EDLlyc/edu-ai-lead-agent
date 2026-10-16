"""Score every mined headline with the golden projection under the current default rules."""

import json
import sys
from collections import Counter
from pathlib import Path

from app.application.services.topic_selection import build_topic_scoring_config
from app.core.config import Settings
from app.domain.topic_selection import score_topic_candidate
from evals.topic_golden.runner import AS_OF, GoldenCase, build_candidate

POLICY = {
    "moe-science-news": "moe-science-top1-v1",
    "china-government-news": "gov-cn-qualified-science-tech-v1",
}
source = Path(sys.argv[1])
config = build_topic_scoring_config(Settings(_env_file=None))
out = []
for line in source.read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    summary = row["summary_projection"] or {}
    tiers = tuple(sorted({t for t in (row["tiers"] or []) if t in {"A", "B"}})) or ("B",)
    slugs = row["source_slugs"] or []
    policy = next((POLICY[s] for s in slugs if s in POLICY), None)
    case = GoldenCase(
        case_id=row["event_id"],
        label="must_select",
        expect_priority=False,
        category="mined",
        label_source="",
        synthetic=False,
        source_tiers=tiers,
        topic_priority_policy=policy,
        title=row["title"],
        summary=summary.get("summary") if isinstance(summary.get("summary"), str) else "",
        source_url=row["source_url"],
        facts=tuple(f for f in summary.get("facts", []) if isinstance(f, str)),
        categories=tuple(c for c in (row["categories"] or []) if isinstance(c, str)),
    )
    score = score_topic_candidate(build_candidate(case, config), as_of=AS_OF, config=config)
    row["rule_eligible"] = score.eligible
    row["rule_priority"] = score.priority_applied
    row["rule_cohort"] = (
        score.science_tech_editorial_cohort.value if score.science_tech_editorial_cohort else None
    )
    row["rule_reasons"] = list(score.veto_codes) if hasattr(score, "veto_codes") else []
    row["summary"] = case.summary
    row["facts"] = list(case.facts)
    row["source_tiers"] = list(tiers)
    row["topic_priority_policy"] = policy
    out.append(row)
Path(sys.argv[2]).write_text(
    "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in out), encoding="utf-8"
)
print(Counter((r["rule_eligible"], r["delivered"]) for r in out))
print(Counter(r["rule_cohort"] for r in out).most_common())
