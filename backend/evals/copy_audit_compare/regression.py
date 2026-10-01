"""Scheduled regression for the production copy auditor.

Runs the seeded-defect auditor check (evals.copy_audit_compare.runner) with the auditor version and
model production uses now, each draft audited three times. It runs when the production copy
bundle changed since the last regression, or when the last one is a week old; otherwise it only
logs that nothing is due. Each run writes a dated report and appends one row to trend.csv, so
block rate, false blocks and verdict consistency can be followed over time. Model calls are capped.
"""


from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
TREND_FIELDS = (
    "date",
    "generator",
    "auditor",
    "rule",
    "model",
    "defects_blocked",
    "defects",
    "controls_blocked",
    "controls",
    "inconsistent",
    "judged",
    "failures",
    "calls",
)
MAX_AGE = timedelta(days=7)


def last_row(trend: Path) -> dict[str, str] | None:
    if not trend.exists():
        return None
    rows = list(csv.DictReader(trend.read_text(encoding="utf-8").splitlines()))
    return rows[-1] if rows else None


def is_due(previous: dict[str, str] | None, bundle: dict[str, str], today: date) -> str | None:
    """Why a regression is due, or None."""

    if previous is None:
        return "first run"
    for key in ("generator", "auditor", "rule", "model"):
        if previous.get(key) != bundle[key]:
            return f"{key} changed: {previous.get(key)} -> {bundle[key]}"
    if today - date.fromisoformat(previous["date"]) >= MAX_AGE:
        return "weekly"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=160)
    args = parser.parse_args(argv)

    from app.application.services.copy_generation import build_copy_version_bundle
    from app.core.config import get_settings

    from evals.copy_audit_compare import runner

    settings = get_settings()
    bundle = build_copy_version_bundle(settings, scoring_profile=settings.content_scoring_profile)
    current = {
        "generator": bundle.generator_prompt_version,
        "auditor": bundle.auditor_prompt_version,
        "rule": bundle.rule_version,
        "model": bundle.model,
    }
    today = datetime.now(UTC).astimezone(TZ).date()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    trend = args.output_dir / "trend.csv"
    reason = "forced" if args.force else is_due(last_row(trend), current, today)
    if reason is None:
        print(json.dumps({"event": "eval_regression_not_due", **current}, ensure_ascii=False))
        return 0
    print(
        json.dumps(
            {"event": "eval_regression_start", "reason": reason, **current}, ensure_ascii=False
        ),
        file=sys.stderr,
    )
    namespace = argparse.Namespace(
        date_from=today - timedelta(days=3),
        date_to=today,
        limit=args.limit,
        max_calls=args.max_calls,
        repeats=args.repeats,
        config=[f"prod:{bundle.auditor_prompt_version}:{bundle.model}"],
        output_dir=None,
        plan=False,
    )
    report, raw = asyncio.run(runner.run(namespace))
    (args.output_dir / f"{today.isoformat()}.md").write_text(
        f"<!-- reason: {reason} -->\n" + report, encoding="utf-8"
    )
    summary = raw.get("summary", {}).get("prod", {})
    row = {"date": today.isoformat(), **current, **summary, "calls": raw.get("calls", 0)}
    new_file = not trend.exists()
    with trend.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TREND_FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
