"""Fail-closed manifest, authorization, attempt, and blinding orchestration."""

from __future__ import annotations

import fcntl
import hmac
import json
import os
import secrets
import stat
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .dataset import LoadedLiveAbDataset
from .models import (
    BLIND_MAP_SCHEMA_VERSION,
    FAILURE_LEDGER_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    WORKSHEET_SCHEMA_VERSION,
    AttemptObservation,
    AttemptPlan,
    AttemptStatus,
    BlindMapRow,
    CaseBinding,
    ExperimentArm,
    ExperimentVersions,
    FailureCode,
    FailureLedger,
    LiveAbCase,
    LiveAuthorization,
    PricingSnapshot,
    ProviderCallObservation,
    ProviderCallStatus,
    RunManifest,
    WorksheetRow,
    canonical_json_bytes,
    evidence_sha256,
)
from .privacy import PrivacyScanError, require_privacy_safe

MAX_JSON_BYTES = 4_194_304
MAX_JSONL_BYTES = 16_777_216
MAX_BLINDING_SECRET_BYTES = 128
EVAL_SOURCE_ROOT = Path(__file__).resolve().parent.parent


class LiveAbHarnessError(ValueError):
    """The experiment evidence is unsafe, unauthorized, or integrity-invalid."""


class AttemptExecutor(Protocol):
    """Replaceable execution boundary; this package ships no provider implementation.

    Implementations must make at most ``plan.max_provider_calls`` requests, apply the frozen
    token/cost ceilings before each request, and return one terminal observation. The harness
    invokes this method exactly once per arm/case/repetition and never retries the suite.
    """

    async def execute(self, *, plan: AttemptPlan, case: LiveAbCase) -> AttemptObservation: ...


def build_manifest(
    *,
    dataset: LoadedLiveAbDataset,
    run_ref: str,
    created_at: datetime,
    execution_window_start: datetime,
    execution_window_end: datetime,
    git_sha: str,
    provider: str,
    model: str,
    temperature: float,
    seed: int | None,
    versions: ExperimentVersions,
    pricing: PricingSnapshot,
    sample_count: int,
    repetitions: int,
    max_input_tokens_per_call: int,
    max_output_tokens_per_call: int,
    max_cost_per_provider_call_usd: float,
    minimum_evidence_pairs: int,
    minimum_double_annotated_pairs: int,
    blinding_secret: bytes,
    bootstrap_samples: int = 5_000,
    bootstrap_seed: int = 20_260_902,
) -> RunManifest:
    """Freeze the exact paired experiment and derive, rather than estimate, its ceilings."""

    if not 32 <= len(blinding_secret) <= MAX_BLINDING_SECRET_BYTES:
        raise LiveAbHarnessError("blinding secret must contain 32 to 128 bytes")
    selected = _select_stratified_cases(dataset, sample_count)
    if len(selected) != sample_count:
        raise LiveAbHarnessError("requested sample count exceeds the frozen dataset")
    selected_ids = tuple(case.case_id for case in selected)
    bindings = tuple(
        CaseBinding(
            case_id=case.case_id,
            initial_article_sha256=dataset.article_sha256_by_case[case.case_id],
            baseline_initial_sha256=dataset.article_sha256_by_case[case.case_id],
            treatment_initial_sha256=dataset.article_sha256_by_case[case.case_id],
        )
        for case in selected
    )
    maximum_calls = sample_count * repetitions * 3
    maximum_cost = round(maximum_calls * max_cost_per_provider_call_usd, 6)
    payload: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "track": "opt_in_live_ab",
        "run_ref": run_ref,
        "created_at": created_at,
        "execution_window_start": execution_window_start,
        "execution_window_end": execution_window_end,
        "git_sha": git_sha,
        "dataset_version": dataset.dataset_version,
        "dataset_sha256": dataset.dataset_sha256,
        "selected_case_ids": selected_ids,
        "sample_count": sample_count,
        "repetitions": repetitions,
        "arms": (ExperimentArm.BASELINE, ExperimentArm.TREATMENT),
        "provider": provider,
        "model": model,
        "temperature": temperature,
        "seed": seed,
        "versions": versions,
        "pricing": pricing,
        "max_input_tokens_per_call": max_input_tokens_per_call,
        "max_output_tokens_per_call": max_output_tokens_per_call,
        "max_provider_calls_per_treatment": 3,
        "max_provider_calls": maximum_calls,
        "max_cost_per_provider_call_usd": max_cost_per_provider_call_usd,
        "max_total_cost_usd": maximum_cost,
        "minimum_evidence_pairs": minimum_evidence_pairs,
        "minimum_double_annotated_pairs": minimum_double_annotated_pairs,
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_seed": bootstrap_seed,
        "blinding_secret_sha256": sha256(blinding_secret).hexdigest(),
        "case_bindings": bindings,
    }
    require_privacy_safe(payload)
    candidate = RunManifest.model_construct(**payload, manifest_sha256="0" * 64)
    hash_payload = candidate.model_dump(mode="json", exclude={"manifest_sha256"})
    return RunManifest.model_validate(
        {**hash_payload, "manifest_sha256": evidence_sha256(hash_payload)}
    )


def validate_authorization(
    manifest: RunManifest,
    authorization: LiveAuthorization | None,
    *,
    now: datetime,
) -> FailureCode | None:
    """Validate an explicit artifact only; credentials and provider availability are not read."""

    if authorization is None:
        return FailureCode.AUTHORIZATION_MISSING
    expected = (
        manifest.manifest_sha256,
        manifest.provider,
        manifest.model,
        manifest.sample_count,
        manifest.repetitions,
        manifest.max_provider_calls,
        manifest.max_cost_per_provider_call_usd,
        manifest.max_total_cost_usd,
    )
    actual = (
        authorization.manifest_sha256,
        authorization.provider,
        authorization.model,
        authorization.sample_count,
        authorization.repetitions,
        authorization.max_provider_calls,
        authorization.max_cost_per_provider_call_usd,
        authorization.max_total_cost_usd,
    )
    if actual != expected:
        return FailureCode.AUTHORIZATION_MISMATCH
    normalized_now = _aware_utc(now)
    if not (
        authorization.valid_from <= normalized_now <= authorization.valid_until
        and authorization.valid_from <= manifest.execution_window_start
        and manifest.execution_window_end <= authorization.valid_until
    ):
        return FailureCode.AUTHORIZATION_EXPIRED
    return None


def build_failure_ledger(
    manifest: RunManifest,
    *,
    reason: FailureCode,
    created_at: datetime,
    live_model_calls: int | None,
    authorization: LiveAuthorization | None = None,
) -> FailureLedger:
    payload: dict[str, Any] = {
        "schema_version": FAILURE_LEDGER_SCHEMA_VERSION,
        "manifest_sha256": manifest.manifest_sha256,
        "dataset_sha256": manifest.dataset_sha256,
        "created_at": created_at,
        "reason": reason,
        "planned_max_provider_calls": manifest.max_provider_calls,
        "planned_max_cost_usd": manifest.max_total_cost_usd,
        "live_model_calls": live_model_calls,
        "conclusion_eligible": False,
        "uplift_claims": (),
        "authorization_sha256": (
            evidence_sha256(authorization) if authorization is not None else None
        ),
    }
    candidate = FailureLedger.model_construct(**payload, ledger_sha256="0" * 64)
    hash_payload = candidate.model_dump(mode="json", exclude={"ledger_sha256"})
    return FailureLedger.model_validate(
        {**hash_payload, "ledger_sha256": evidence_sha256(hash_payload)}
    )


def preflight_failure_ledger(
    manifest: RunManifest,
    *,
    authorization: LiveAuthorization | None,
    now: datetime,
) -> FailureLedger | None:
    """Return a reproducible zero-call blocker, or ``None`` when authorization matches."""

    reason: FailureCode | None
    try:
        require_privacy_safe(manifest)
        if authorization is not None:
            require_privacy_safe(authorization)
    except PrivacyScanError:
        reason = FailureCode.PRIVACY_SCAN_FAILED
    else:
        reason = validate_authorization(manifest, authorization, now=now)
    if reason is None:
        return None
    return build_failure_ledger(
        manifest,
        reason=reason,
        created_at=now,
        live_model_calls=0,
        authorization=authorization,
    )


def build_attempt_plans(
    manifest: RunManifest,
    authorization: LiveAuthorization,
) -> tuple[AttemptPlan, ...]:
    authorization_failure = validate_authorization(
        manifest,
        authorization,
        now=manifest.execution_window_start,
    )
    if authorization_failure is not None:
        raise LiveAbHarnessError(f"attempt planning blocked: {authorization_failure.value}")
    authorization_digest = evidence_sha256(authorization)
    bindings = {binding.case_id: binding for binding in manifest.case_bindings}
    return tuple(
        AttemptPlan(
            attempt_ref=_attempt_ref(case_id, repetition, arm),
            manifest_sha256=manifest.manifest_sha256,
            authorization_sha256=authorization_digest,
            case_id=case_id,
            repetition=repetition,
            arm=arm,
            initial_article_sha256=bindings[case_id].initial_article_sha256,
            max_provider_calls=0 if arm is ExperimentArm.BASELINE else 3,
            max_cost_per_provider_call_usd=manifest.max_cost_per_provider_call_usd,
            max_input_tokens_per_call=manifest.max_input_tokens_per_call,
            max_output_tokens_per_call=manifest.max_output_tokens_per_call,
        )
        for case_id in manifest.selected_case_ids
        for repetition in range(1, manifest.repetitions + 1)
        for arm in manifest.arms
    )


async def execute_authorized_experiment(
    *,
    manifest: RunManifest,
    authorization: LiveAuthorization,
    dataset: LoadedLiveAbDataset,
    executor: AttemptExecutor,
    output_dir: Path,
    now: datetime,
) -> tuple[AttemptObservation, ...]:
    """Execute each plan once and persist each terminal attempt before moving on.

    This orchestration is provider-agnostic. No concrete network/provider adapter is included or
    wired by the CLI in this package.
    """

    failure = validate_authorization(manifest, authorization, now=now)
    if failure is not None:
        raise LiveAbHarnessError(f"live A/B execution blocked: {failure.value}")
    _validate_dataset_binding(manifest, dataset)
    require_privacy_safe(manifest)
    ensure_live_artifact_path(output_dir)
    create_live_artifact_dir(output_dir)
    write_json_exclusive(output_dir / "manifest.json", manifest)
    write_json_exclusive(output_dir / "authorization.json", authorization)
    attempts_path = output_dir / "attempts.jsonl"
    cases = {case.case_id: case for case in dataset.cases}
    observations: list[AttemptObservation] = []
    for plan in build_attempt_plans(manifest, authorization):
        try:
            observation = await executor.execute(plan=plan, case=cases[plan.case_id])
            validate_attempt_binding(manifest, plan, observation)
            require_privacy_safe(observation)
        except Exception as exc:
            # An exception after the provider boundary has ambiguous billing/call count. Preserve
            # no raw exception and stop: continuing could exceed the frozen total ceiling.
            ledger = build_failure_ledger(
                manifest,
                reason=FailureCode.PROVIDER_RESULT_UNKNOWN,
                created_at=now,
                live_model_calls=None,
                authorization=authorization,
            )
            write_json_exclusive(output_dir / "failure-ledger.json", ledger)
            raise LiveAbHarnessError(
                "attempt result became unknown; suite stopped without retry"
            ) from exc
        append_jsonl_durable(attempts_path, observation)
        observations.append(observation)
        if observation.status is not AttemptStatus.COMPLETED:
            known_calls = sum(
                provider_call_was_attempted(call)
                for item in observations
                for call in item.provider_calls
            )
            reason = (
                FailureCode.PROVIDER_RESULT_UNKNOWN
                if observation.status is AttemptStatus.RESULT_UNKNOWN
                else FailureCode.PROVIDER_FAILED
            )
            ledger = build_failure_ledger(
                manifest,
                reason=reason,
                created_at=now,
                live_model_calls=known_calls,
                authorization=authorization,
            )
            write_json_exclusive(output_dir / "failure-ledger.json", ledger)
            break
    return tuple(observations)


def validate_attempt_binding(
    manifest: RunManifest,
    plan: AttemptPlan,
    observation: AttemptObservation,
) -> None:
    expected = (
        plan.attempt_ref,
        plan.manifest_sha256,
        plan.authorization_sha256,
        plan.case_id,
        plan.repetition,
        plan.arm,
        plan.initial_article_sha256,
    )
    actual = (
        observation.attempt_ref,
        observation.manifest_sha256,
        observation.authorization_sha256,
        observation.case_id,
        observation.repetition,
        observation.arm,
        observation.initial_article_sha256,
    )
    if actual != expected:
        raise LiveAbHarnessError("attempt observation drifted from its frozen plan")
    if len(observation.provider_calls) > plan.max_provider_calls:
        raise LiveAbHarnessError("attempt exceeded its provider-call ceiling")
    for call in observation.provider_calls:
        if call.usage is not None and (
            call.usage.input_tokens > manifest.max_input_tokens_per_call
            or call.usage.output_tokens > manifest.max_output_tokens_per_call
        ):
            raise LiveAbHarnessError("attempt exceeded its frozen token ceiling")
        cost = provider_call_cost_usd(call, manifest.pricing)
        if cost is not None and cost > manifest.max_cost_per_provider_call_usd + 1e-9:
            raise LiveAbHarnessError("attempt exceeded its per-provider-call cost ceiling")


def provider_call_cost_usd(
    call: ProviderCallObservation,
    pricing: PricingSnapshot,
) -> float | None:
    usage = call.usage
    if usage is None:
        return None
    value = (
        usage.input_tokens * pricing.input_usd_per_million_tokens
        + usage.output_tokens * pricing.output_usd_per_million_tokens
        + usage.reasoning_tokens * pricing.reasoning_usd_per_million_tokens
    ) / 1_000_000
    return value


def provider_call_was_attempted(call: ProviderCallObservation) -> bool:
    return call.status is not ProviderCallStatus.BUDGET_DENIED


def build_blinded_worksheet(
    *,
    manifest: RunManifest,
    authorization: LiveAuthorization,
    observations: Sequence[AttemptObservation],
    blinding_secret: bytes,
) -> tuple[tuple[WorksheetRow, ...], tuple[BlindMapRow, ...]]:
    if not hmac.compare_digest(
        sha256(blinding_secret).hexdigest(),
        manifest.blinding_secret_sha256,
    ):
        raise LiveAbHarnessError("blinding secret does not match the manifest")
    by_key = _complete_observation_map(manifest, authorization, observations)
    worksheets: list[WorksheetRow] = []
    mappings: list[BlindMapRow] = []
    for case_id in manifest.selected_case_ids:
        for repetition in range(1, manifest.repetitions + 1):
            pair_ref = f"pair:{case_id}:{repetition}"
            baseline_is_a = _blind_bit(blinding_secret, pair_ref) == 0
            for arm in manifest.arms:
                observation = by_key[(case_id, repetition, arm)]
                final = observation.revisions[-1]
                candidate = "A" if (arm is ExperimentArm.BASELINE) == baseline_is_a else "B"
                blind_ref = _blind_ref(blinding_secret, pair_ref, candidate)
                artifact_commitment = blind_artifact_commitment(
                    blinding_secret,
                    manifest.manifest_sha256,
                    pair_ref,
                    candidate,
                    blind_ref,
                    final.artifact_sha256,
                )
                worksheets.append(
                    WorksheetRow(
                        schema_version=WORKSHEET_SCHEMA_VERSION,
                        blind_ref=blind_ref,
                        pair_ref=pair_ref,
                        candidate=candidate,
                        artifact_ref=f"artifact:{blind_ref}",
                        artifact_commitment_sha256=artifact_commitment,
                    )
                )
                mappings.append(
                    BlindMapRow(
                        schema_version=BLIND_MAP_SCHEMA_VERSION,
                        blind_ref=blind_ref,
                        pair_ref=pair_ref,
                        candidate=candidate,
                        case_id=case_id,
                        repetition=repetition,
                        arm=arm,
                        revision_no=final.revision_no,
                        source_artifact_ref=final.artifact_ref,
                        artifact_sha256=final.artifact_sha256,
                        artifact_commitment_sha256=artifact_commitment,
                    )
                )
    worksheet_result = tuple(sorted(worksheets, key=lambda item: (item.pair_ref, item.candidate)))
    mapping_result = tuple(sorted(mappings, key=lambda item: (item.pair_ref, item.arm.value)))
    require_privacy_safe(worksheet_result)
    require_privacy_safe(mapping_result)
    return worksheet_result, mapping_result


ModelT = TypeVar("ModelT", bound=BaseModel)


def load_json_model(path: Path, model: type[ModelT]) -> ModelT:
    payload = _read_bounded(path, MAX_JSON_BYTES)
    try:
        raw = _strict_json_loads(payload.decode("utf-8"))
        return model.model_validate(raw)
    except (UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise LiveAbHarnessError("evidence JSON is invalid") from exc


def load_jsonl_models(path: Path, model: type[ModelT]) -> tuple[ModelT, ...]:
    payload = _read_bounded(path, MAX_JSONL_BYTES)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LiveAbHarnessError("evidence JSONL must be UTF-8") from exc
    records: list[ModelT] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise LiveAbHarnessError(f"blank evidence JSONL row at line {line_number}")
        try:
            records.append(model.model_validate(_strict_json_loads(line)))
        except (ValueError, ValidationError) as exc:
            raise LiveAbHarnessError(f"invalid evidence row at line {line_number}") from exc
    return tuple(records)


def write_json_exclusive(path: Path, value: object) -> None:
    require_privacy_safe(value)
    payload = (
        json.dumps(
            _json_ready(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    _write_atomic_exclusive(path, payload, "evidence artifact")


def write_text_exclusive(path: Path, value: str) -> None:
    require_privacy_safe(value)
    _write_atomic_exclusive(path, value.encode(), "text evidence artifact")


def write_blinding_secret_exclusive(path: Path, value: bytes) -> None:
    if not 32 <= len(value) <= MAX_BLINDING_SECRET_BYTES:
        raise LiveAbHarnessError("blinding secret must contain 32 to 128 bytes")
    _write_atomic_exclusive(path, value, "blinding secret")


def read_blinding_secret(path: Path) -> bytes:
    value = _read_bounded(path, MAX_BLINDING_SECRET_BYTES)
    if len(value) < 32:
        raise LiveAbHarnessError("blinding secret must contain 32 to 128 bytes")
    return value


def ensure_live_artifact_path(path: Path) -> None:
    """Keep mutable/live evidence outside the checked-in deterministic eval source tree."""

    resolved = path.resolve()
    try:
        resolved.relative_to(EVAL_SOURCE_ROOT)
    except ValueError:
        return
    raise LiveAbHarnessError("live artifacts cannot be written into backend/evals")


def append_jsonl_durable(path: Path, value: object) -> None:
    require_privacy_safe(value)
    payload = canonical_json_bytes(value) + b"\n"
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    parent_descriptor: int | None = None
    try:
        parent_descriptor = _open_parent_directory(path)
        descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_descriptor)
        with os.fdopen(descriptor, "ab") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                raise LiveAbHarnessError("attempt ledger must be a private regular file")
            if info.st_size + len(payload) > MAX_JSONL_BYTES:
                raise LiveAbHarnessError("attempt ledger exceeds its byte limit")
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise LiveAbHarnessError("attempt ledger could not be durably appended") from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _complete_observation_map(
    manifest: RunManifest,
    authorization: LiveAuthorization,
    observations: Sequence[AttemptObservation],
) -> dict[tuple[str, int, ExperimentArm], AttemptObservation]:
    plans = build_attempt_plans(manifest, authorization)
    plan_by_ref = {plan.attempt_ref: plan for plan in plans}
    result: dict[tuple[str, int, ExperimentArm], AttemptObservation] = {}
    for observation in observations:
        plan = plan_by_ref.get(observation.attempt_ref)
        if plan is None:
            raise LiveAbHarnessError("observation is not declared by the manifest")
        validate_attempt_binding(manifest, plan, observation)
        if observation.status is not AttemptStatus.COMPLETED:
            raise LiveAbHarnessError("worksheet requires complete paired attempts")
        key = (observation.case_id, observation.repetition, observation.arm)
        if key in result:
            raise LiveAbHarnessError("duplicate paired attempt observation")
        result[key] = observation
    expected = {(plan.case_id, plan.repetition, plan.arm) for plan in plans}
    if set(result) != expected:
        raise LiveAbHarnessError("paired attempt observations are incomplete")
    return result


def _validate_dataset_binding(manifest: RunManifest, dataset: LoadedLiveAbDataset) -> None:
    if (
        manifest.dataset_version != dataset.dataset_version
        or manifest.dataset_sha256 != dataset.dataset_sha256
    ):
        raise LiveAbHarnessError("dataset identity drifted from the manifest")
    expected = {
        binding.case_id: binding.initial_article_sha256 for binding in manifest.case_bindings
    }
    actual = {
        case_id: dataset.article_sha256_by_case.get(case_id)
        for case_id in manifest.selected_case_ids
    }
    if actual != expected:
        raise LiveAbHarnessError("initial Article hashes drifted from the manifest")


def _select_stratified_cases(
    dataset: LoadedLiveAbDataset,
    sample_count: int,
) -> tuple[LiveAbCase, ...]:
    if sample_count < 2:
        raise LiveAbHarnessError("paired evidence requires calibration and holdout samples")
    calibration = tuple(case for case in dataset.cases if case.split == "calibration")
    holdout = tuple(case for case in dataset.cases if case.split == "holdout")
    holdout_count = max(1, sample_count // 3)
    holdout_count = min(holdout_count, len(holdout), sample_count - 1)
    calibration_count = sample_count - holdout_count
    selected = calibration[:calibration_count] + holdout[:holdout_count]
    if len(selected) != sample_count:
        raise LiveAbHarnessError("requested sample count exceeds the stratified frozen dataset")
    return selected


def _attempt_ref(case_id: str, repetition: int, arm: ExperimentArm) -> str:
    suffix = "b" if arm is ExperimentArm.BASELINE else "t"
    return f"attempt:{case_id}:{repetition}:{suffix}"


def _blind_bit(secret: bytes, pair_ref: str) -> int:
    return hmac.new(secret, pair_ref.encode("utf-8"), sha256).digest()[0] & 1


def _blind_ref(secret: bytes, pair_ref: str, candidate: str) -> str:
    digest = hmac.new(
        secret,
        f"{pair_ref}:{candidate}".encode(),
        sha256,
    ).hexdigest()[:24]
    return f"blind:{digest}"


def blind_artifact_commitment(
    secret: bytes,
    manifest_sha256: str,
    pair_ref: str,
    candidate: str,
    blind_ref: str,
    artifact_sha256: str,
) -> str:
    return hmac.new(
        secret,
        (
            "official-account-review-live-ab-artifact-commitment-v1\x00"
            f"{manifest_sha256}\x00{pair_ref}\x00{candidate}\x00{blind_ref}\x00{artifact_sha256}"
        ).encode(),
        sha256,
    ).hexdigest()


def _strict_json_loads(text: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicates)


def _read_bounded(path: Path, limit: int) -> bytes:
    parent_descriptor: int | None = None
    try:
        parent_descriptor = _open_parent_directory(path)
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                raise LiveAbHarnessError("evidence artifact must be a private regular file")
            payload = stream.read(limit + 1)
    except OSError as exc:
        raise LiveAbHarnessError("evidence artifact could not be read") from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)
    if not payload or len(payload) > limit:
        raise LiveAbHarnessError("evidence artifact has an invalid byte length")
    return payload


def _json_ready(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return json.loads(canonical_json_bytes(value).decode("utf-8"))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise LiveAbHarnessError("authorization check time must be timezone-aware")
    return value.astimezone(UTC)


def create_live_artifact_dir(path: Path) -> None:
    _reject_symlink_ancestors(path.parent)
    try:
        path.mkdir(parents=True, exist_ok=False)
        path.chmod(0o700)
    except OSError as exc:
        raise LiveAbHarnessError("live artifact directory must be new and writable") from exc


def _write_atomic_exclusive(path: Path, payload: bytes, label: str) -> None:
    """Publish a new 0600 artifact atomically without replacing existing evidence."""

    temporary_name = f".{path.name}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    parent_descriptor: int | None = None
    try:
        parent_descriptor = _open_parent_directory(path)
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_descriptor)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary_name,
                path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        finally:
            os.unlink(temporary_name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
    except OSError as exc:
        if parent_descriptor is not None:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except OSError:
                pass
        raise LiveAbHarnessError(f"{label} could not be written atomically") from exc
    finally:
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _open_parent_directory(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path.parent, flags)


def _reject_symlink_ancestors(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise LiveAbHarnessError("live artifact path cannot traverse a symbolic link")
