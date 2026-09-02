"""Validate and report the grounded 41-image IP retrieval Codex seed."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .authoring import DEFAULT_MANIFEST_PATH, REPO_ROOT
from .dataset import GroundedDatasetError, load_grounded_bundle
from .metrics import compare_runs
from .models import GroundedRetrievalRun
from .reporting import (
    build_run_report,
    build_seed_report,
    canonical_json,
    render_comparison_markdown,
    render_run_markdown,
    render_seed_markdown,
)

if TYPE_CHECKING:
    from app.core.config import Settings

FEATURE_ROOT = Path(__file__).resolve().parent
CANONICAL_JSON_PATH = FEATURE_ROOT / "canonical-seed-report.json"
CANONICAL_MARKDOWN_PATH = FEATURE_ROOT / "canonical-seed-report.md"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-seed")
    subparsers.add_parser("check-canonical")
    subparsers.add_parser("write-canonical")
    review = subparsers.add_parser("export-review-template")
    review.add_argument("--output", type=Path, required=True)
    compare = subparsers.add_parser("compare-runs")
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output-json", type=Path, required=True)
    compare.add_argument("--output-markdown", type=Path, required=True)
    run_report = subparsers.add_parser("report-run")
    run_report.add_argument("--run", type=Path, required=True)
    run_report.add_argument("--output-json", type=Path, required=True)
    run_report.add_argument("--output-markdown", type=Path, required=True)
    live_preflight = subparsers.add_parser("preflight-live")
    live_preflight.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    live = subparsers.add_parser("run-live")
    live.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    live.add_argument(
        "--search-version",
        choices=("ip-asset-hybrid-v2", "ip-asset-hybrid-v3-rrf"),
        required=True,
    )
    live.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bundle = load_grounded_bundle()
        report = build_seed_report(bundle)
        if args.command == "validate-seed":
            print(
                "Grounded IP retrieval seed valid: "
                f"{report['dataset']['query_count']} queries; "
                f"{report['dataset']['judgment_count']} Codex grades; maturity=seed"
            )
            return 0
        if args.command == "write-canonical":
            CANONICAL_JSON_PATH.write_text(canonical_json(report), encoding="utf-8")
            CANONICAL_MARKDOWN_PATH.write_text(render_seed_markdown(report), encoding="utf-8")
            print("Grounded IP retrieval seed canonical report written")
            return 0
        if args.command == "check-canonical":
            if not _canonical_matches(report):
                print("Grounded IP retrieval seed canonical report drifted", file=sys.stderr)
                return 1
            print("Grounded IP retrieval seed canonical report matches")
            return 0
        if args.command == "export-review-template":
            _write_review_template(args.output, bundle)
            print("Grounded IP retrieval offline review template written")
            return 0
        if args.command == "compare-runs":
            baseline = _load_run(args.baseline)
            candidate = _load_run(args.candidate)
            comparison = compare_runs(bundle, baseline, candidate)
            args.output_json.write_text(canonical_json(comparison), encoding="utf-8")
            args.output_markdown.write_text(
                render_comparison_markdown(comparison), encoding="utf-8"
            )
            print("Grounded IP retrieval paired comparison written")
            return 0
        if args.command == "report-run":
            run = _load_run(args.run)
            run_report_body = build_run_report(bundle, run)
            _write_report_pair(
                json_path=args.output_json,
                markdown_path=args.output_markdown,
                report=run_report_body,
                markdown=render_run_markdown(run_report_body),
            )
            print("Grounded IP retrieval run report written")
            return 0
        if args.command == "preflight-live":
            from .live import preflight_live_grounded

            asyncio.run(
                preflight_live_grounded(
                    settings=_live_settings(),
                    bundle=bundle,
                    manifest_path=args.manifest,
                )
            )
            print(
                "Grounded IP retrieval live preflight passed: "
                f"{len(bundle.assets.assets)} approved searchable assets"
            )
            return 0
        if args.command == "run-live":
            from .live import run_live_grounded

            live_run = asyncio.run(
                run_live_grounded(
                    settings=_live_settings(),
                    bundle=bundle,
                    manifest_path=args.manifest,
                    search_version=args.search_version,
                )
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                canonical_json(live_run.model_dump(mode="json")), encoding="utf-8"
            )
            print(
                "Grounded IP retrieval live run written: "
                f"{live_run.run_ref} {live_run.search_version} "
                f"embedding_mode={live_run.embedding_execution_mode}"
            )
            return 0
    except SQLAlchemyError:
        print(
            "Grounded IP retrieval evaluation failed: database_unavailable",
            file=sys.stderr,
        )
        return 1
    except (GroundedDatasetError, OSError, ValidationError, ValueError) as error:
        print(f"Grounded IP retrieval evaluation failed: {error}", file=sys.stderr)
        return 1
    return 2


def _canonical_matches(report: dict[str, object]) -> bool:
    try:
        return CANONICAL_JSON_PATH.read_text(encoding="utf-8") == canonical_json(
            report
        ) and CANONICAL_MARKDOWN_PATH.read_text(encoding="utf-8") == render_seed_markdown(report)
    except OSError:
        return False


def _load_run(path: Path) -> GroundedRetrievalRun:
    try:
        body = path.read_bytes()
        raw = json.loads(body)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("grounded retrieval run could not be read") from error
    prohibited = {
        "vector",
        "provider_body",
        "provider_request_id",
        "filename",
        "path",
        "object_key",
        "profile_id",
        "profile_token",
        "user_id",
        "session_id",
        "ip",
        "user_agent",
        "cookie",
        "query",
        "grade",
        "label",
        "similarity",
        "score",
        "rank",
    }
    if _find_keys(raw, prohibited):
        raise ValueError("grounded retrieval run contains prohibited fields")
    return GroundedRetrievalRun.model_validate_json(body, strict=True)


def _find_keys(value: object, prohibited: set[str]) -> set[str]:
    if isinstance(value, dict):
        found = {str(key).casefold() for key in value if str(key).casefold() in prohibited}
        for child in value.values():
            found.update(_find_keys(child, prohibited))
        return found
    if isinstance(value, list):
        list_found: set[str] = set()
        for child in value:
            list_found.update(_find_keys(child, prohibited))
        return list_found
    return set()


def _write_review_template(output: Path, bundle: object) -> None:
    from .dataset import GroundedDatasetBundle

    if not isinstance(bundle, GroundedDatasetBundle):
        raise TypeError("grounded review template needs a dataset bundle")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("query_ref", "query", "catalog_ref", "grade_0_to_3", "note"))
        for query in bundle.queries:
            for asset in bundle.assets.assets:
                writer.writerow((query.query_ref, query.query, asset.catalog_ref, "", ""))


def _write_report_pair(
    *,
    json_path: Path,
    markdown_path: Path,
    report: dict[str, object],
    markdown: str,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(canonical_json(report), encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")


def _live_settings() -> Settings:
    from app.core.config import Settings

    settings_factory = cast(Any, Settings)
    return cast(Settings, settings_factory(_env_file=REPO_ROOT / ".env"))


if __name__ == "__main__":
    raise SystemExit(main())
