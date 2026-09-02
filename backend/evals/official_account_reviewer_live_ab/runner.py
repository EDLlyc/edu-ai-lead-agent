"""Prepare and verify Reviewer live A/B evidence without shipping a provider adapter."""

from __future__ import annotations

import argparse
import secrets
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .dataset import DEFAULT_CASES_PATH, LiveAbDatasetError, load_live_ab_dataset
from .harness import (
    LiveAbHarnessError,
    build_blinded_worksheet,
    build_failure_ledger,
    build_manifest,
    create_live_artifact_dir,
    ensure_live_artifact_path,
    load_json_model,
    load_jsonl_models,
    preflight_failure_ledger,
    provider_call_was_attempted,
    read_blinding_secret,
    write_blinding_secret_exclusive,
    write_json_exclusive,
    write_text_exclusive,
)
from .metrics import LiveAbReport, build_live_ab_report, build_report_failure_ledger
from .models import (
    AttemptObservation,
    BlindMapRow,
    ExperimentVersions,
    FailureCode,
    HumanAdjudication,
    HumanJudgment,
    LiveAuthorization,
    PricingSnapshot,
    RunManifest,
    WorksheetRow,
)
from .reporting import (
    build_calibration_candidate,
    canonical_jsonl,
    render_markdown,
    render_worksheet_csv,
    report_sha256,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_prepare_parser(subparsers)
    _add_preflight_parser(subparsers)
    _add_live_parser(subparsers)
    _add_worksheet_parser(subparsers)
    _add_report_parser(subparsers)
    _add_confirm_parser(subparsers)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            return _prepare(args)
        if args.command == "preflight":
            return _preflight(args)
        if args.command == "live":
            return _live_fail_closed(args)
        if args.command == "worksheet":
            return _worksheet(args)
        if args.command == "report":
            return _report(args)
        if args.command == "confirm-report":
            return _confirm_report(args)
    except LiveAbDatasetError:
        print("Reviewer live A/B harness failed: dataset_invalid", file=sys.stderr)
        return 1
    except LiveAbHarnessError:
        print("Reviewer live A/B harness failed: evidence_rejected", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Reviewer live A/B harness failed: artifact_invalid", file=sys.stderr)
        return 1
    raise AssertionError("unreachable command")


def _add_prepare_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("prepare", help="provider-free dry run and manifest creation")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--run-ref", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--window-start", type=_parse_datetime, required=True)
    parser.add_argument("--window-end", type=_parse_datetime, required=True)
    parser.add_argument("--sample-count", type=int, default=12)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--max-input-tokens", type=int, default=8_192)
    parser.add_argument("--max-output-tokens", type=int, default=4_096)
    parser.add_argument("--max-cost-per-call-usd", type=float, required=True)
    parser.add_argument("--minimum-evidence-pairs", type=int, default=10)
    parser.add_argument("--minimum-double-annotated-pairs", type=int, default=5)
    parser.add_argument("--bootstrap-samples", type=int, default=5_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20_260_902)
    parser.add_argument("--pricing-effective-date", required=True)
    parser.add_argument("--input-usd-per-million", type=float, required=True)
    parser.add_argument("--output-usd-per-million", type=float, required=True)
    parser.add_argument("--reasoning-usd-per-million", type=float, required=True)
    parser.add_argument("--pricing-source-sha256", required=True)
    parser.add_argument("--registry-sha256", required=True)
    parser.add_argument("--writer-version", default="official.writer.initial")
    parser.add_argument("--reviewer-r1-version", default="official.reviewer.r1")
    parser.add_argument("--repair-writer-version", default="official.writer.repair")
    parser.add_argument("--reviewer-r2-version", default="official.reviewer.r2")
    parser.add_argument("--prompt-version", default="official-account-reviewer-prompt-v1")
    parser.add_argument("--rubric-version", default="official-account-editorial-rubric-v1")
    parser.add_argument("--review-policy-version", default="official-account-review-policy-v1")
    parser.add_argument("--repair-policy-version", default="official-account-repair-policy-v1")
    parser.add_argument("--enforce-policy-version", default="official-account-review-enforce-v1")


def _add_preflight_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("preflight", help="validate exact authorization without calls")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--failure-ledger", type=Path, required=True)
    parser.add_argument("--at", type=_parse_datetime)


def _add_live_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("live", help="explicit fail-closed provider boundary")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--failure-ledger", type=Path, required=True)
    parser.add_argument("--at", type=_parse_datetime)


def _add_worksheet_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser("worksheet", help="blind completed attempt artifacts")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--attempts", type=Path, required=True)
    parser.add_argument("--blinding-key", type=Path, required=True)
    parser.add_argument("--worksheet-jsonl", type=Path, required=True)
    parser.add_argument("--worksheet-csv", type=Path, required=True)
    parser.add_argument("--blind-map-jsonl", type=Path, required=True)


def _add_report_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("report", help="recompute human-gold paired evidence")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--attempts", type=Path, required=True)
    parser.add_argument("--worksheet", type=Path, required=True)
    parser.add_argument("--blind-map", type=Path, required=True)
    parser.add_argument("--blinding-key", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--adjudications", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--report-markdown", type=Path, required=True)
    parser.add_argument("--failure-ledger", type=Path, required=True)


def _add_confirm_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "confirm-report",
        help="create a non-activating calibration candidate from an eligible report",
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--confirmed-at", type=_parse_datetime, required=True)
    parser.add_argument("--confirmed-by-ref", required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--expected-report-sha256", required=True)
    parser.add_argument("--candidate", type=Path, required=True)


def _prepare(args: argparse.Namespace) -> int:
    dataset = load_live_ab_dataset(args.cases)
    secret = secrets.token_bytes(32)
    versions = ExperimentVersions(
        writer_version=args.writer_version,
        reviewer_r1_version=args.reviewer_r1_version,
        repair_writer_version=args.repair_writer_version,
        reviewer_r2_version=args.reviewer_r2_version,
        prompt_version=args.prompt_version,
        rubric_version=args.rubric_version,
        review_policy_version=args.review_policy_version,
        repair_policy_version=args.repair_policy_version,
        enforce_policy_version=args.enforce_policy_version,
        registry_sha256=args.registry_sha256,
    )
    pricing = PricingSnapshot(
        effective_date=args.pricing_effective_date,
        input_usd_per_million_tokens=args.input_usd_per_million,
        output_usd_per_million_tokens=args.output_usd_per_million,
        reasoning_usd_per_million_tokens=args.reasoning_usd_per_million,
        pricing_source_sha256=args.pricing_source_sha256,
    )
    now = datetime.now(UTC)
    manifest = build_manifest(
        dataset=dataset,
        run_ref=args.run_ref,
        created_at=now,
        execution_window_start=args.window_start,
        execution_window_end=args.window_end,
        git_sha=args.git_sha,
        provider=args.provider,
        model=args.model,
        temperature=args.temperature,
        seed=args.seed,
        versions=versions,
        pricing=pricing,
        sample_count=args.sample_count,
        repetitions=args.repetitions,
        max_input_tokens_per_call=args.max_input_tokens,
        max_output_tokens_per_call=args.max_output_tokens,
        max_cost_per_provider_call_usd=args.max_cost_per_call_usd,
        minimum_evidence_pairs=args.minimum_evidence_pairs,
        minimum_double_annotated_pairs=args.minimum_double_annotated_pairs,
        blinding_secret=secret,
        bootstrap_samples=args.bootstrap_samples,
        bootstrap_seed=args.bootstrap_seed,
    )
    ensure_live_artifact_path(args.output_dir)
    create_live_artifact_dir(args.output_dir)
    write_blinding_secret_exclusive(args.output_dir / ".blinding-key", secret)
    write_json_exclusive(args.output_dir / "manifest.json", manifest)
    ledger = preflight_failure_ledger(manifest, authorization=None, now=now)
    assert ledger is not None
    write_json_exclusive(args.output_dir / "failure-ledger.json", ledger)
    print(
        "provider-free dry run prepared; "
        f"max_provider_calls={manifest.max_provider_calls}; "
        f"max_total_cost_usd={manifest.max_total_cost_usd:.6f}; "
        "live_model_calls=0; authorization=missing"
    )
    return 0


def _preflight(args: argparse.Namespace) -> int:
    manifest = load_json_model(args.manifest, RunManifest)
    authorization = load_json_model(args.authorization, LiveAuthorization)
    now = args.at or datetime.now(UTC)
    ensure_live_artifact_path(args.failure_ledger)
    ledger = preflight_failure_ledger(manifest, authorization=authorization, now=now)
    if ledger is not None:
        write_json_exclusive(args.failure_ledger, ledger)
        print(
            f"live preflight blocked: {ledger.reason.value}; live_model_calls=0",
            file=sys.stderr,
        )
        return 2
    print(
        "live preflight authorization matched; no provider was contacted; "
        f"max_provider_calls={manifest.max_provider_calls}; "
        f"max_total_cost_usd={manifest.max_total_cost_usd:.6f}"
    )
    return 0


def _live_fail_closed(args: argparse.Namespace) -> int:
    manifest = load_json_model(args.manifest, RunManifest)
    authorization = load_json_model(args.authorization, LiveAuthorization)
    now = args.at or datetime.now(UTC)
    ensure_live_artifact_path(args.failure_ledger)
    ledger = preflight_failure_ledger(manifest, authorization=authorization, now=now)
    if ledger is None:
        ledger = build_failure_ledger(
            manifest,
            reason=FailureCode.EXECUTOR_NOT_INSTALLED,
            created_at=now,
            live_model_calls=0,
            authorization=authorization,
        )
    write_json_exclusive(args.failure_ledger, ledger)
    print(
        f"live execution blocked: {ledger.reason.value}; live_model_calls=0; "
        "this provider-free build ships no provider adapter",
        file=sys.stderr,
    )
    return 2


def _worksheet(args: argparse.Namespace) -> int:
    manifest = load_json_model(args.manifest, RunManifest)
    authorization = load_json_model(args.authorization, LiveAuthorization)
    attempts = load_jsonl_models(args.attempts, AttemptObservation)
    secret = read_blinding_secret(args.blinding_key)
    _require_distinct_outputs((args.worksheet_jsonl, args.worksheet_csv, args.blind_map_jsonl))
    for path in (args.worksheet_jsonl, args.worksheet_csv, args.blind_map_jsonl):
        ensure_live_artifact_path(path)
    rows, mapping = build_blinded_worksheet(
        manifest=manifest,
        authorization=authorization,
        observations=attempts,
        blinding_secret=secret,
    )
    write_text_exclusive(args.worksheet_jsonl, canonical_jsonl(rows))
    write_text_exclusive(args.worksheet_csv, render_worksheet_csv(rows))
    write_text_exclusive(args.blind_map_jsonl, canonical_jsonl(mapping))
    print(f"blinded worksheet prepared: rows={len(rows)}; labels_hidden=true")
    return 0


def _report(args: argparse.Namespace) -> int:
    manifest = load_json_model(args.manifest, RunManifest)
    _require_distinct_outputs((args.report_json, args.report_markdown, args.failure_ledger))
    for path in (args.report_json, args.report_markdown, args.failure_ledger):
        ensure_live_artifact_path(path)
    authorization: LiveAuthorization | None = None
    observations: tuple[AttemptObservation, ...] | None = None
    try:
        authorization = load_json_model(args.authorization, LiveAuthorization)
        dataset = load_live_ab_dataset(args.cases)
        observations = load_jsonl_models(args.attempts, AttemptObservation)
        worksheet = load_jsonl_models(args.worksheet, WorksheetRow)
        mapping = load_jsonl_models(args.blind_map, BlindMapRow)
        blinding_secret = read_blinding_secret(args.blinding_key)
        judgments = load_jsonl_models(args.judgments, HumanJudgment)
        adjudications = load_jsonl_models(args.adjudications, HumanAdjudication)
        report = build_live_ab_report(
            manifest=manifest,
            authorization=authorization,
            dataset=dataset,
            observations=observations,
            worksheet=worksheet,
            blind_map=mapping,
            blinding_secret=blinding_secret,
            judgments=judgments,
            adjudications=adjudications,
        )
    except (LiveAbDatasetError, LiveAbHarnessError, ValueError):
        ledger = build_failure_ledger(
            manifest,
            reason=FailureCode.ARTIFACT_INTEGRITY_FAILED,
            created_at=datetime.now(UTC),
            live_model_calls=(
                sum(
                    provider_call_was_attempted(call)
                    for item in observations
                    for call in item.provider_calls
                )
                if observations is not None
                else None
            ),
            authorization=authorization,
        )
        write_json_exclusive(args.failure_ledger, ledger)
        print(
            "paired report blocked: artifact_integrity_failed; resume_claims=0",
            file=sys.stderr,
        )
        return 2
    assert authorization is not None
    write_json_exclusive(args.report_json, report)
    write_text_exclusive(args.report_markdown, render_markdown(report))
    if not report.conclusion_eligible:
        ledger = build_report_failure_ledger(
            manifest,
            authorization,
            report,
            created_at=datetime.now(UTC),
        )
        write_json_exclusive(args.failure_ledger, ledger)
    print(
        f"paired report written; complete_pairs={report.complete_pair_count}; "
        f"conclusion_eligible={str(report.conclusion_eligible).lower()}; "
        f"resume_claims={len(report.resume_claims)}; "
        f"report_sha256={report_sha256(report)}"
    )
    return 0 if report.conclusion_eligible else 2


def _confirm_report(args: argparse.Namespace) -> int:
    report = load_json_model(args.report, LiveAbReport)
    ensure_live_artifact_path(args.candidate)
    candidate = build_calibration_candidate(
        report=report,
        confirmed_at=args.confirmed_at,
        confirmed_by_ref=args.confirmed_by_ref,
        confirmation=args.confirmation,
        expected_report_sha256=args.expected_report_sha256,
    )
    write_json_exclusive(args.candidate, candidate)
    print(
        "non-activating calibration candidate written; "
        f"report_sha256={candidate.report_sha256}; production_mode_changed=false"
    )
    return 0


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include an offset")
    return parsed


def _require_distinct_outputs(paths: tuple[Path, ...]) -> None:
    normalized = tuple(path.resolve(strict=False) for path in paths)
    if len(normalized) != len(set(normalized)):
        raise LiveAbHarnessError("evidence output paths must be distinct")


if __name__ == "__main__":
    raise SystemExit(main())
