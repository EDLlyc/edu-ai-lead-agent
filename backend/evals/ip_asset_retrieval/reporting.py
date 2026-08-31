from __future__ import annotations

import json
from typing import Any


def canonical_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    lines = [
        "# IP asset retrieval deterministic baseline",
        "",
        "> This provider-free report measures frozen, sanitized rank observations. "
        "It is not a live embedding, private-library, user-conversion, or "
        "production-effectiveness claim.",
        "",
        f"- Dataset: `{report['dataset_version']}` ({aggregate['case_count']} cases)",
        "- Top K: 5",
        "",
        "## Retrieval-policy comparison",
        "",
        "| Metric | V2 direct blend | V3 weighted RRF |",
        "| --- | ---: | ---: |",
    ]
    for label, key in (
        ("Recall@5", "macro_recall_at_5"),
        ("MRR@5", "macro_mrr_at_5"),
        ("nDCG@5", "macro_ndcg_at_5"),
        ("Zero-result rate", "zero_result_rate"),
    ):
        lines.append(f"| {label} | {aggregate['v2'][key]:.2%} | {aggregate['v3'][key]:.2%} |")
    lines.extend(
        [
            "",
            "## Category breakdown",
            "",
            "| Category | Cases | V2 R/M/N | V3 R/M/N |",
            "| --- | ---: | --- | --- |",
        ]
    )
    for category, values in sorted(report["categories"].items()):
        v2 = values["v2"]
        v3 = values["v3"]
        lines.append(
            f"| `{category}` | {values['case_count']} | "
            f"{v2['macro_recall_at_5']:.3f}/{v2['macro_mrr_at_5']:.3f}/"
            f"{v2['macro_ndcg_at_5']:.3f} | "
            f"{v3['macro_recall_at_5']:.3f}/{v3['macro_mrr_at_5']:.3f}/"
            f"{v3['macro_ndcg_at_5']:.3f} |"
        )
    lines.extend(
        [
            "",
            "Graded relevance is used only after the production rank selector returns an "
            "order; it is never supplied to ranking.",
            "",
        ]
    )
    return "\n".join(lines)
