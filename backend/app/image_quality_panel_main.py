"""Application composition root for the 120-call GLM-5V-Turbo image evaluation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import TypeVar

import httpx
from evals.image_quality_panel.dataset import (
    LoadedImagePanelDataset,
    build_image_panel_dataset,
)
from evals.image_quality_panel.execution import (
    ImagePlanExecutionResult,
    execute_image_plan,
    material_for_request,
)
from evals.image_quality_panel.metrics import build_candidate_artifact, build_report
from evals.image_quality_panel.models import IMAGE_EVALUATOR_MODEL_SPEC
from evals.image_quality_panel.planning import (
    RUBRIC_BY_DIMENSION,
    TOTAL_CALL_CEILING,
    ZERO_HASH,
    ImageExperimentPlan,
    bind_authorization,
    build_experiment_plan,
    issue_authorization,
    validate_experiment_plan,
)
from evals.image_quality_panel.reporting import write_safe_reports
from evals.image_quality_panel.sources import (
    REPOSITORY_ROOT,
    load_source_catalog,
    preflight_sources,
)
from evals.model_panel import (
    AtomicPanelBudget,
    AttemptJournal,
    AttemptStatus,
    PairwiseJudgeRequest,
    PanelAuthorization,
    PanelManifest,
    PrivacyProfile,
    SecureEvidenceStore,
    canonical_json_bytes,
    require_privacy_safe,
    strict_json_object,
    validate_authorization_binding,
)
from pydantic import BaseModel, ValidationError

from app.infrastructure.ai.image_quality_panel import (
    ImagePanelLiveAdapterError,
    ImagePanelPricingSnapshot,
    build_panel_identities,
    create_image_panel_executions,
    maximum_native_cost_by_model,
    provider_native_limits,
    validate_manifest_pricing_binding,
)

ZHIPU_CREDENTIAL_ENV = "AI_PLATFORM_API_KEY"
ModelT = TypeVar("ModelT", bound=BaseModel)


class ImagePanelLiveCliError(ValueError):
    """A redacted application-level preflight or live-composition failure."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    _add_prepare(commands)
    _add_authorize(commands)
    _add_preflight(commands)
    _add_live(commands)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            return _prepare(args)
        if args.command == "authorize":
            return _authorize(args)
        if args.command == "preflight":
            return _preflight(args)
        if args.command == "live":
            return asyncio.run(_live(args))
    except (
        ImagePanelLiveAdapterError,
        ImagePanelLiveCliError,
        ValidationError,
        RuntimeError,
        OSError,
        ValueError,
    ):
        print("image panel live evidence failed: evidence_rejected", file=sys.stderr)
        return 1
    raise AssertionError("unreachable command")


def _add_prepare(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = commands.add_parser("prepare", help="freeze the zero-call 120-request plan")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--run-ref", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--window-start", type=_parse_datetime, required=True)
    parser.add_argument("--window-end", type=_parse_datetime, required=True)
    _pricing_args(parser)


def _add_authorize(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = commands.add_parser("authorize", help="bind explicit approval to one manifest")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-file-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--valid-from", type=_parse_datetime, required=True)
    parser.add_argument("--valid-until", type=_parse_datetime, required=True)
    parser.add_argument("--approved-by-ref", required=True)
    parser.add_argument("--acknowledgement", required=True)
    _pricing_args(parser)


def _add_preflight(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = commands.add_parser("preflight", help="validate all evidence before secrets")
    _live_evidence_args(parser)
    parser.add_argument("--at", type=_parse_datetime)


def _add_live(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = commands.add_parser("live", help="run the direct GLM-5V-Turbo one-shot route")
    _live_evidence_args(parser)
    parser.add_argument("--run-dir", type=Path, required=True)


def _pricing_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pricing", type=Path, required=True)
    parser.add_argument("--pricing-file-sha256", required=True)


def _live_evidence_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-file-sha256", required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--authorization-file-sha256", required=True)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--requests-file-sha256", required=True)
    _pricing_args(parser)


def _prepare(args: argparse.Namespace) -> int:
    _source_preflight()
    store = _store()
    pricing = _load_model_bound(
        store,
        args.pricing,
        ImagePanelPricingSnapshot,
        args.pricing_file_sha256,
    )
    with _derived_dataset() as dataset:
        plan = build_experiment_plan(
            dataset=dataset,
            run_ref=args.run_ref,
            blind_key=os.urandom(32),
            identities=build_panel_identities(pricing),
            provider_limits=provider_native_limits(pricing),
            maximum_native_cost_by_model=maximum_native_cost_by_model(pricing),
            git_sha=args.git_sha,
            created_at=datetime.now(UTC),
            execution_window_start=args.window_start,
            execution_window_end=args.window_end,
        )
    validate_manifest_pricing_binding(plan.manifest, pricing)
    run_dir = store.create_run_directory(args.run_dir)
    manifest_path = run_dir / "manifest.json"
    requests_path = run_dir / "requests.private.jsonl"
    store.write_json_exclusive(
        manifest_path,
        plan.manifest,
        privacy_profile=PrivacyProfile.PRIVATE_EVIDENCE,
    )
    _write_jsonl(store, requests_path, plan.requests)
    print(
        json.dumps(
            {
                "call_ceiling": TOTAL_CALL_CEILING,
                "live_calls": 0,
                "manifest_file_sha256": store.file_sha256(manifest_path)[0],
                "requests_file_sha256": store.file_sha256(requests_path)[0],
            },
            sort_keys=True,
        )
    )
    return 0


def _authorize(args: argparse.Namespace) -> int:
    _source_preflight()
    store = _store()
    pricing = _load_model_bound(
        store,
        args.pricing,
        ImagePanelPricingSnapshot,
        args.pricing_file_sha256,
    )
    manifest = _load_model_bound(
        store,
        args.manifest,
        PanelManifest,
        args.manifest_file_sha256,
    )
    validate_manifest_pricing_binding(manifest, pricing)
    authorization = issue_authorization(
        manifest=manifest,
        valid_from=args.valid_from,
        valid_until=args.valid_until,
        approved_by_ref=args.approved_by_ref,
        acknowledgement=args.acknowledgement,
    )
    store.write_json_exclusive(
        args.output,
        authorization,
        privacy_profile=PrivacyProfile.PRIVATE_EVIDENCE,
    )
    print(
        json.dumps(
            {
                "authorization_file_sha256": store.file_sha256(args.output)[0],
                "live_calls": 0,
            },
            sort_keys=True,
        )
    )
    return 0


def _preflight(args: argparse.Namespace) -> int:
    now = args.at or datetime.now(UTC)
    with _derived_dataset() as dataset:
        plan, authorization, pricing = _load_live_bundle(args, dataset=dataset, now=now)
    print(
        json.dumps(
            {
                "authorization_sha256": authorization.authorization_sha256,
                "call_ceiling": plan.manifest.total_request_limit,
                "live_calls": 0,
                "pricing_snapshot_sha256": pricing.snapshot_sha256,
                "source_clusters": dataset.effective_source_cluster_n,
                "transports": len(plan.manifest.identities),
            },
            sort_keys=True,
        )
    )
    return 0


async def _live(args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    with _derived_dataset() as dataset:
        plan, authorization, pricing = _load_live_bundle(args, dataset=dataset, now=now)
        run_dir = _create_live_run_directory(args.run_dir)
        # Credentials are intentionally read only after every source/evidence/pricing check above.
        zhipu_token = _read_live_credential()
        store = _store()
        journal = AttemptJournal(store=store, path=run_dir / "attempt-journal.private.jsonl")
        budget = AtomicPanelBudget(
            manifest=plan.manifest,
            authorization=authorization,
            clock=lambda: datetime.now(UTC),
        )
        async with _new_live_http_client() as client:
            executions = create_image_panel_executions(
                client=client,
                manifest=plan.manifest,
                snapshot=pricing,
                zhipu_bearer_token=zhipu_token,
                budget=budget,
                journal=journal,
                clock=lambda: datetime.now(UTC),
                monotonic=monotonic,
            )
            result = await execute_image_plan(
                plan=plan,
                authorization=authorization,
                dataset=dataset,
                execution_by_model=executions,
                now=now,
            )
        records = journal.load()
        terminal = tuple(
            record.attempt
            for record in records
            if record.attempt.status is not AttemptStatus.STARTED
        )
        if len(records) != 2 * len(terminal) or terminal != result.attempts:
            raise ImagePanelLiveCliError("attempts do not match the append-only journal")
        attempts_path = run_dir / "attempts.private.jsonl"
        _write_jsonl(store, attempts_path, result.attempts)
        report = build_report(
            dataset=dataset,
            manifest=plan.manifest,
            authorization=authorization,
            evaluator_model_ref=IMAGE_EVALUATOR_MODEL_SPEC.model_ref,
            attempts=result.attempts,
        )
        write_safe_reports(
            store=store,
            run_directory=run_dir,
            report=report,
            candidate_artifact=build_candidate_artifact(report),
        )
    exit_code = _execution_exit_code(result)
    complete = exit_code == 0
    print(
        json.dumps(
            {
                "attempts": len(result.attempts),
                "complete": complete,
                "live_calls": len(result.attempts),
                "report_sha256": report.report_sha256,
                "stopped_models": len(result.stopped_model_refs),
            },
            sort_keys=True,
        )
    )
    return exit_code


def _execution_exit_code(result: ImagePlanExecutionResult) -> int:
    complete = (
        len(result.attempts) == TOTAL_CALL_CEILING
        and not result.stopped_model_refs
        and result.skipped_attempt_count == 0
        and all(attempt.status is AttemptStatus.COMPLETED for attempt in result.attempts)
    )
    return 0 if complete else 2


def _load_live_bundle(
    args: argparse.Namespace,
    *,
    dataset: LoadedImagePanelDataset,
    now: datetime,
) -> tuple[ImageExperimentPlan, PanelAuthorization, ImagePanelPricingSnapshot]:
    _source_preflight()
    store = _store()
    pricing = _load_model_bound(
        store,
        args.pricing,
        ImagePanelPricingSnapshot,
        args.pricing_file_sha256,
    )
    manifest = _load_model_bound(
        store,
        args.manifest,
        PanelManifest,
        args.manifest_file_sha256,
    )
    authorization = _load_model_bound(
        store,
        args.authorization,
        PanelAuthorization,
        args.authorization_file_sha256,
    )
    requests = _load_jsonl_bound(
        store,
        args.requests,
        PairwiseJudgeRequest,
        args.requests_file_sha256,
    )
    validate_manifest_pricing_binding(manifest, pricing)
    validate_authorization_binding(manifest, authorization, now=now)
    _require_uniform_request_authorization(requests, authorization)
    unbound = ImageExperimentPlan(
        manifest=manifest,
        requests=requests,
        rubric_by_dimension=dict(RUBRIC_BY_DIMENSION),
    )
    validate_experiment_plan(unbound)
    plan = bind_authorization(unbound, authorization, now=now)
    if (
        manifest.dataset_version != dataset.dataset_version
        or manifest.dataset_sha256 != dataset.dataset_sha256
    ):
        raise ImagePanelLiveCliError("manifest dataset binding drifted")
    # Resolve and hash-check every frozen artifact while the derived dataset is available.
    # This is deliberately part of the zero-secret preflight, not deferred to paid execution.
    for request in plan.requests:
        material_for_request(dataset, plan, request)
    return plan, authorization, pricing


def _require_uniform_request_authorization(
    requests: Sequence[PairwiseJudgeRequest],
    authorization: PanelAuthorization,
) -> None:
    request_authorizations = {request.authorization_sha256 for request in requests}
    if len(request_authorizations) != 1 or not request_authorizations.issubset(
        {ZERO_HASH, authorization.authorization_sha256}
    ):
        raise ImagePanelLiveCliError("request templates bind a different authorization")


def _read_live_credential() -> str:
    zhipu = os.environ.get(ZHIPU_CREDENTIAL_ENV, "").strip()
    if not zhipu:
        raise ImagePanelLiveCliError("the Zhipu live credential is required")
    return zhipu


def _new_live_http_client() -> httpx.AsyncClient:
    """Build the only live client without ambient proxy, CA, or credential inheritance."""

    return httpx.AsyncClient(trust_env=False)


def _source_preflight() -> None:
    catalog = load_source_catalog()
    preflight_sources(catalog)


@contextmanager
def _derived_dataset() -> Iterator[LoadedImagePanelDataset]:
    _source_preflight()
    with tempfile.TemporaryDirectory(prefix="image-panel-live-") as raw:
        directory = Path(raw)
        directory.chmod(0o700)
        yield build_image_panel_dataset(artifact_directory=directory)


def _load_model_bound(
    store: SecureEvidenceStore,
    path: Path,
    model: type[ModelT],
    expected_file_sha256: str,
) -> ModelT:
    _require_file_hash(store, path, expected_file_sha256)
    return store.load_json_model(path, model)


def _load_jsonl_bound(
    store: SecureEvidenceStore,
    path: Path,
    model: type[ModelT],
    expected_file_sha256: str,
) -> tuple[ModelT, ...]:
    _require_file_hash(store, path, expected_file_sha256)
    payload = store.read_bytes(path)
    if not payload.endswith(b"\n") or any(not line for line in payload.splitlines()):
        raise ImagePanelLiveCliError("private JSONL is empty or incomplete")
    values: list[ModelT] = []
    for line in payload.splitlines():
        raw = strict_json_object(line)
        values.append(model.model_validate_json(canonical_json_bytes(raw)))
    return tuple(values)


def _write_jsonl(
    store: SecureEvidenceStore,
    path: Path,
    values: Sequence[BaseModel],
) -> None:
    if not values:
        raise ImagePanelLiveCliError("private JSONL cannot be empty")
    require_privacy_safe(values, profile=PrivacyProfile.PRIVATE_EVIDENCE)
    payload = b"".join(canonical_json_bytes(value) + b"\n" for value in values)
    store.write_bytes_exclusive(path, payload)


def _require_file_hash(
    store: SecureEvidenceStore,
    path: Path,
    expected_file_sha256: str,
) -> None:
    actual, _ = store.file_sha256(path)
    if actual != expected_file_sha256:
        raise ImagePanelLiveCliError("private evidence file hash mismatch")


def _create_live_run_directory(path: Path) -> Path:
    """Atomically create a new gitignored, untracked, owner-only output directory."""

    return _store().create_run_directory(path)


def _store() -> SecureEvidenceStore:
    return SecureEvidenceStore(repository_root=REPOSITORY_ROOT)


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


if __name__ == "__main__":
    raise SystemExit(main())
