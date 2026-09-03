from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast

import httpx
import pytest
from app import image_quality_panel_main as app_main
from app.image_quality_panel_main import ImagePanelLiveCliError, _execution_exit_code
from app.infrastructure.ai import image_quality_panel as live_adapter
from app.infrastructure.ai.image_quality_panel import (
    IMAGE_PANEL_TRANSPORT_ADAPTER_VERSION,
    ZHIPU_CHAT_COMPLETIONS_URL,
    ImagePanelLiveAdapterError,
    ImagePanelModelPrice,
    ImagePanelPricingSnapshot,
    build_panel_identities,
    create_image_panel_executions,
    maximum_native_cost_by_model,
    price_token_usage,
    provider_native_limits,
    token_pricing_cost_extractor,
    validate_manifest_pricing_binding,
)
from evals.image_quality_panel import runner as provider_free_runner
from evals.image_quality_panel.dataset import (
    LoadedImagePanelDataset,
    build_image_panel_dataset,
)
from evals.image_quality_panel.execution import (
    ImagePlanExecutionResult,
    material_for_request,
)
from evals.image_quality_panel.models import ALL_MODEL_SPECS
from evals.image_quality_panel.planning import (
    ImageExperimentPlan,
    bind_authorization,
    build_experiment_plan,
    issue_authorization,
)
from evals.model_panel import (
    MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    AtomicPanelBudget,
    AttemptJournal,
    AttemptStatus,
    PanelBudgetError,
    PanelFailureCode,
    PanelIssueCode,
    PanelTransportError,
    SecureEvidenceStore,
    canonical_json_bytes,
    evidence_sha256,
    panel_manifest_fingerprint,
    validate_authorization_binding,
)
from pydantic import ValidationError

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)
PRICING_EFFECTIVE_AT = NOW - timedelta(days=1)
PRICING_EXPIRES_AT = NOW + timedelta(days=1)
INPUT_RATE = Decimal("1.00000000")
OUTPUT_RATE = Decimal("2.00000000")
REASONING_RATE = Decimal("3.00000000")
MAXIMUM_CALL_COST = Decimal("0.03532800")


@pytest.fixture(scope="module")
def pricing_snapshot() -> ImagePanelPricingSnapshot:
    spec = ALL_MODEL_SPECS[0]
    price = ImagePanelModelPrice(
        model_ref=spec.model_ref,
        provider="zhipu",
        requested_model=spec.requested_model,
        native_unit="cny",
        input_per_million_tokens=INPUT_RATE,
        output_per_million_tokens=OUTPUT_RATE,
        reasoning_per_million_tokens=REASONING_RATE,
        maximum_native_cost_per_call=MAXIMUM_CALL_COST,
    )
    prices = (price,)
    payload: dict[str, object] = {
        "schema_version": "image-panel-zhipu-pricing-snapshot-v1",
        "pricing_version": "operator-fixture-v1",
        "effective_at": PRICING_EFFECTIVE_AT,
        "expires_at": PRICING_EXPIRES_AT,
        "pricing_source_sha256": sha256(b"operator-pricing-fixture").hexdigest(),
        "zhipu_cny_cap": Decimal("100"),
        "models": prices,
    }
    return ImagePanelPricingSnapshot(
        schema_version="image-panel-zhipu-pricing-snapshot-v1",
        pricing_version="operator-fixture-v1",
        effective_at=PRICING_EFFECTIVE_AT,
        expires_at=PRICING_EXPIRES_AT,
        pricing_source_sha256=sha256(b"operator-pricing-fixture").hexdigest(),
        zhipu_cny_cap=Decimal("100"),
        models=prices,
        snapshot_sha256=evidence_sha256(payload),
    )


@pytest.fixture(scope="module")
def app_image_dataset(
    tmp_path_factory: pytest.TempPathFactory,
) -> LoadedImagePanelDataset:
    directory = tmp_path_factory.mktemp("image-panel-live-app")
    directory.chmod(0o700)
    return build_image_panel_dataset(artifact_directory=directory)


@pytest.fixture(scope="module")
def app_image_plan(
    app_image_dataset: LoadedImagePanelDataset,
    pricing_snapshot: ImagePanelPricingSnapshot,
) -> ImageExperimentPlan:
    return build_experiment_plan(
        dataset=app_image_dataset,
        run_ref="image-panel-live-app-test",
        blind_key=b"image-panel-live-app-test-key-32-bytes",
        identities=build_panel_identities(pricing_snapshot),
        provider_limits=provider_native_limits(pricing_snapshot),
        maximum_native_cost_by_model=maximum_native_cost_by_model(pricing_snapshot),
        git_sha="a" * 40,
        created_at=NOW - timedelta(minutes=2),
        execution_window_start=NOW - timedelta(minutes=1),
        execution_window_end=NOW + timedelta(hours=1),
    )


def test_pricing_snapshot_binds_exact_routes_units_and_native_caps(
    pricing_snapshot: ImagePanelPricingSnapshot,
    app_image_plan: ImageExperimentPlan,
) -> None:
    identities = build_panel_identities(pricing_snapshot)
    assert tuple(identity.requested_model for identity in identities) == tuple(
        spec.requested_model for spec in sorted(ALL_MODEL_SPECS, key=lambda item: item.model_ref)
    )
    assert [
        (limit.provider_ref, limit.unit, limit.maximum)
        for limit in provider_native_limits(pricing_snapshot)
    ] == [
        ("zhipu", "cny", Decimal("100")),
    ]
    assert {binding.native_cost_unit for binding in app_image_plan.manifest.attempt_bindings} == {
        "cny",
    }
    assert {
        binding.maximum_native_cost for binding in app_image_plan.manifest.attempt_bindings
    } == {MAXIMUM_CALL_COST}
    validate_manifest_pricing_binding(app_image_plan.manifest, pricing_snapshot)

    drifted = pricing_snapshot.model_copy(update={"zhipu_cny_cap": Decimal("99")})
    with pytest.raises(ImagePanelLiveAdapterError, match="hard caps"):
        validate_manifest_pricing_binding(app_image_plan.manifest, drifted)

    expired = pricing_snapshot.model_copy(
        update={"expires_at": app_image_plan.manifest.execution_window_end - timedelta(seconds=1)}
    )
    with pytest.raises(ImagePanelLiveAdapterError, match="validity window"):
        validate_manifest_pricing_binding(app_image_plan.manifest, expired)


def test_pricing_snapshot_rejects_route_and_self_hash_drift(
    pricing_snapshot: ImagePanelPricingSnapshot,
) -> None:
    raw = pricing_snapshot.model_dump(mode="json")
    raw["pricing_version"] = "tampered"
    with pytest.raises(ValidationError, match="snapshot SHA-256"):
        ImagePanelPricingSnapshot.model_validate_json(canonical_json_bytes(raw))

    raw = pricing_snapshot.model_dump(mode="json")
    models = cast(list[dict[str, object]], raw["models"])
    models[0]["requested_model"] = "substitute-model"
    raw["snapshot_sha256"] = evidence_sha256(
        {key: value for key, value in raw.items() if key != "snapshot_sha256"}
    )
    with pytest.raises(ValidationError, match="only GLM-5V-Turbo"):
        ImagePanelPricingSnapshot.model_validate_json(canonical_json_bytes(raw))

    raw = pricing_snapshot.model_dump(mode="json")
    raw["expires_at"] = raw["effective_at"]
    raw["snapshot_sha256"] = evidence_sha256(
        {key: value for key, value in raw.items() if key != "snapshot_sha256"}
    )
    with pytest.raises(ValidationError, match="validity window must be increasing"):
        ImagePanelPricingSnapshot.model_validate_json(canonical_json_bytes(raw))

    legacy = pricing_snapshot.model_dump(mode="json")
    legacy["schema_version"] = "image-panel-pricing-snapshot-v1"
    legacy["toapis_credit_cap"] = "10000"
    with pytest.raises(ValidationError):
        ImagePanelPricingSnapshot.model_validate_json(canonical_json_bytes(legacy))


def test_adapter_v3_rejects_a_self_hashed_manifest_from_the_previous_adapter(
    pricing_snapshot: ImagePanelPricingSnapshot,
    app_image_plan: ImageExperimentPlan,
) -> None:
    assert IMAGE_PANEL_TRANSPORT_ADAPTER_VERSION.endswith("-v3")
    previous_identity = app_image_plan.manifest.identities[0].model_copy(
        update={"adapter_version": "image-panel-zhipu-glm-5v-turbo-one-shot-v2"}
    )
    legacy_payload = app_image_plan.manifest.model_dump(
        mode="json",
        exclude={"manifest_sha256"},
    )
    legacy_payload["identities"] = (previous_identity,)
    legacy_payload["manifest_sha256"] = panel_manifest_fingerprint(legacy_payload)
    legacy_manifest = type(app_image_plan.manifest).model_validate_json(
        canonical_json_bytes(legacy_payload)
    )

    with pytest.raises(ImagePanelLiveAdapterError, match="identities"):
        validate_manifest_pricing_binding(legacy_manifest, pricing_snapshot)


def test_token_pricing_preserves_unknown_usage_and_rounds_up(
    pricing_snapshot: ImagePanelPricingSnapshot,
) -> None:
    price = pricing_snapshot.models[0]
    extractor = token_pricing_cost_extractor(price)
    assert extractor({}) is None
    assert extractor({"usage": {"prompt_tokens": 1, "completion_tokens": 1}}) is None
    cost = extractor(
        {
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "reasoning_tokens": 1,
            }
        }
    )
    assert cost is not None
    assert cost.unit == "cny"
    assert cost.amount == Decimal("0.00000600")
    assert (
        price_token_usage(
            price,
            input_tokens=32_768,
            output_tokens=512,
            reasoning_tokens=512,
        )
        == MAXIMUM_CALL_COST
    )


@pytest.mark.asyncio
async def test_unique_transport_uses_direct_zhipu_endpoint_once_without_retry(
    pricing_snapshot: ImagePanelPricingSnapshot,
    app_image_plan: ImageExperimentPlan,
    app_image_dataset: LoadedImagePanelDataset,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def reject(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        calls.append((str(request.url), payload))
        assert request.headers["authorization"] == "Bearer zhipu-unit-test-token"
        return httpx.Response(503, json={"error": "not retained"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
        executions = create_image_panel_executions(
            client=client,
            manifest=app_image_plan.manifest,
            snapshot=pricing_snapshot,
            zhipu_bearer_token="zhipu-unit-test-token",
            budget=cast(AtomicPanelBudget, object()),
            journal=cast(AttemptJournal, object()),
            clock=lambda: NOW,
            monotonic=lambda: 0.0,
        )
        assert set(executions) == {spec.model_ref for spec in ALL_MODEL_SPECS}
        for identity in app_image_plan.manifest.identities:
            request = next(
                item
                for item in app_image_plan.requests
                if item.evaluator_model_ref == identity.identity_ref
            )
            with pytest.raises(PanelTransportError, match="provider_rejected"):
                await executions[identity.identity_ref].transport.complete(
                    identity=identity,
                    request=request,
                    material=material_for_request(app_image_dataset, app_image_plan, request),
                )

    assert len(calls) == 1
    url, payload = calls[0]
    assert url == ZHIPU_CHAT_COMPLETIONS_URL
    assert set(payload) == {"model", "max_tokens", "thinking", "do_sample", "messages"}
    assert payload["model"] == "glm-5v-turbo"
    assert payload["max_tokens"] == 512
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["do_sample"] is False
    assert "response_format" not in payload
    assert "temperature" not in payload
    messages = cast(list[dict[str, object]], payload["messages"])
    assert [message["role"] for message in messages] == ["system", "user"]
    user_content = cast(list[dict[str, object]], messages[1]["content"])
    assert sum(item["type"] == "image_url" for item in user_content) == 4
    assert sum(item["type"] == "text" for item in user_content) == 9


@pytest.mark.asyncio
async def test_exact_returned_identity_mismatch_is_terminal_without_retry(
    tmp_path: Path,
    pricing_snapshot: ImagePanelPricingSnapshot,
    app_image_plan: ImageExperimentPlan,
    app_image_dataset: LoadedImagePanelDataset,
) -> None:
    authorization = issue_authorization(
        manifest=app_image_plan.manifest,
        valid_from=NOW - timedelta(seconds=30),
        valid_until=NOW + timedelta(minutes=30),
        approved_by_ref="operator-fixture",
        acknowledgement=MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    )
    bound = bind_authorization(app_image_plan, authorization, now=NOW)
    repository = tmp_path / "repository"
    repository.mkdir()
    store = SecureEvidenceStore(
        repository_root=repository,
        tracked_path_predicate=lambda _: False,
        ignored_path_predicate=lambda _: True,
    )
    run_dir = store.create_run_directory(repository / "output" / "evals" / "run")
    budget = AtomicPanelBudget(
        manifest=bound.manifest,
        authorization=authorization,
        clock=lambda: NOW,
    )
    journal = AttemptJournal(store=store, path=run_dir / "attempts.jsonl")
    call_count = 0

    def wrong_identity(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "model": "substitute-model",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": "{}"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "reasoning_tokens": 1,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(wrong_identity)) as client:
        executions = create_image_panel_executions(
            client=client,
            manifest=bound.manifest,
            snapshot=pricing_snapshot,
            zhipu_bearer_token="unit-test-token",
            budget=budget,
            journal=journal,
            clock=lambda: NOW,
            monotonic=lambda: 0.0,
        )
        request = bound.requests[0]
        identity = bound.manifest.identities[0]
        attempt = await executions[identity.identity_ref].execute(
            identity=identity,
            request=request,
            material=material_for_request(app_image_dataset, bound, request),
        )

    assert call_count == 1
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.failure_code is PanelFailureCode.PROVIDER_IDENTITY_MISMATCH


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_kind", "expected_failure"),
    [
        ("framing", PanelFailureCode.JUDGE_CONTENT_FRAMING_INVALID),
        ("schema", PanelFailureCode.JUDGE_CONTENT_SCHEMA_INVALID),
        ("policy", PanelFailureCode.JUDGE_CONTENT_POLICY_INVALID),
    ],
)
async def test_zhipu_vision_records_discriminating_safe_content_failures(
    tmp_path: Path,
    pricing_snapshot: ImagePanelPricingSnapshot,
    app_image_plan: ImageExperimentPlan,
    app_image_dataset: LoadedImagePanelDataset,
    failure_kind: str,
    expected_failure: PanelFailureCode,
) -> None:
    authorization = issue_authorization(
        manifest=app_image_plan.manifest,
        valid_from=NOW - timedelta(seconds=30),
        valid_until=NOW + timedelta(minutes=30),
        approved_by_ref="operator-fixture",
        acknowledgement=MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    )
    bound = bind_authorization(app_image_plan, authorization, now=NOW)
    repository = tmp_path / "repository"
    repository.mkdir()
    store = SecureEvidenceStore(
        repository_root=repository,
        tracked_path_predicate=lambda _: False,
        ignored_path_predicate=lambda _: True,
    )
    run_dir = store.create_run_directory(repository / "output" / "evals" / "run")
    budget = AtomicPanelBudget(
        manifest=bound.manifest,
        authorization=authorization,
        clock=lambda: NOW,
    )
    journal = AttemptJournal(store=store, path=run_dir / "attempts.jsonl")
    request = bound.requests[0]
    allowed_code = request.allowed_issue_codes[0].value
    output: dict[str, object] = {
        "profile": "image_pair_arm_verdict",
        "choice": "A",
        "a_decision": "accept",
        "b_decision": "reject",
        "a_critical": False,
        "b_critical": True,
        "a_issue_codes": [],
        "b_issue_codes": [allowed_code],
        "confidence": 0.9,
    }
    if failure_kind == "framing":
        raw_content = "safe-non-json-sentinel"
    elif failure_kind == "schema":
        output["unknown_field"] = "safe-schema-sentinel"
        raw_content = json.dumps(output, separators=(",", ":"))
    else:
        disallowed = next(
            code.value for code in PanelIssueCode if code not in request.allowed_issue_codes
        )
        output["b_issue_codes"] = [disallowed]
        raw_content = json.dumps(output, separators=(",", ":"))
    call_count = 0

    def invalid_judge_content(_: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "model": "glm-5v-turbo",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": raw_content},
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "reasoning_tokens": 1,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(invalid_judge_content)) as client:
        executions = create_image_panel_executions(
            client=client,
            manifest=bound.manifest,
            snapshot=pricing_snapshot,
            zhipu_bearer_token="unit-test-token",
            budget=budget,
            journal=journal,
            clock=lambda: NOW,
            monotonic=lambda: 0.0,
        )
        identity = bound.manifest.identities[0]
        attempt = await executions[identity.identity_ref].execute(
            identity=identity,
            request=request,
            material=material_for_request(app_image_dataset, bound, request),
        )

    assert call_count == 1
    assert attempt.status is AttemptStatus.FAILED
    assert attempt.failure_code is expected_failure
    journal_evidence = canonical_json_bytes(journal.load())
    assert raw_content.encode() not in journal_evidence


def test_authorization_mismatch_fails_closed(
    app_image_plan: ImageExperimentPlan,
) -> None:
    authorization = issue_authorization(
        manifest=app_image_plan.manifest,
        valid_from=NOW - timedelta(seconds=30),
        valid_until=NOW + timedelta(minutes=30),
        approved_by_ref="operator-fixture",
        acknowledgement=MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    )
    drifted = authorization.model_copy(update={"manifest_sha256": "f" * 64})
    with pytest.raises(PanelBudgetError, match="authorization_manifest_mismatch"):
        validate_authorization_binding(app_image_plan.manifest, drifted, now=NOW)


def test_mixed_request_authorizations_are_rejected(
    app_image_plan: ImageExperimentPlan,
) -> None:
    authorization = issue_authorization(
        manifest=app_image_plan.manifest,
        valid_from=NOW - timedelta(seconds=30),
        valid_until=NOW + timedelta(minutes=30),
        approved_by_ref="operator-fixture",
        acknowledgement=MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    )
    bound = bind_authorization(app_image_plan, authorization, now=NOW)

    app_main._require_uniform_request_authorization(app_image_plan.requests, authorization)
    app_main._require_uniform_request_authorization(bound.requests, authorization)
    with pytest.raises(ImagePanelLiveCliError, match="different authorization"):
        app_main._require_uniform_request_authorization(
            (app_image_plan.requests[0], bound.requests[1]),
            authorization,
        )


def test_live_cli_does_not_read_keys_before_bundle_preflight(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []

    @contextmanager
    def fake_dataset() -> Iterator[LoadedImagePanelDataset]:
        yield cast(LoadedImagePanelDataset, object())

    def reject_bundle(*args: object, **kwargs: object) -> object:
        events.append("bundle-preflight")
        raise ImagePanelLiveCliError("sentinel evidence mismatch")

    def read_credential() -> str:
        events.append("credentials")
        return "should-not-be-read"

    monkeypatch.setattr(app_main, "_derived_dataset", fake_dataset)
    monkeypatch.setattr(app_main, "_load_live_bundle", reject_bundle)
    monkeypatch.setattr(app_main, "_read_live_credential", read_credential)
    exit_code = app_main.main(
        [
            "live",
            "--manifest",
            "manifest.json",
            "--manifest-file-sha256",
            "0" * 64,
            "--authorization",
            "authorization.json",
            "--authorization-file-sha256",
            "0" * 64,
            "--requests",
            "requests.jsonl",
            "--requests-file-sha256",
            "0" * 64,
            "--pricing",
            "pricing.json",
            "--pricing-file-sha256",
            "0" * 64,
            "--run-dir",
            "output/evals/run",
        ]
    )

    assert exit_code == 1
    assert events == ["bundle-preflight"]
    output = capsys.readouterr()
    assert "sentinel evidence mismatch" not in output.err
    assert "should-not-be-read" not in output.err


def test_live_credential_uses_only_explicit_zhipu_platform_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOAPIS_API_KEY", "toapis-fixture")
    monkeypatch.delenv("AI_PLATFORM_API_KEY", raising=False)
    with pytest.raises(ImagePanelLiveCliError, match="Zhipu"):
        app_main._read_live_credential()
    monkeypatch.setenv("AI_PLATFORM_API_KEY", "zhipu-fixture")
    monkeypatch.setenv("ZHIPU_API_KEY", "must-not-be-read")

    assert app_main._read_live_credential() == "zhipu-fixture"


def test_live_http_client_disables_environment_inheritance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_client(**kwargs: object) -> object:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(app_main.httpx, "AsyncClient", fake_client)

    assert app_main._new_live_http_client() is sentinel
    assert captured == {"trust_env": False}


def test_existing_live_output_is_rejected_before_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []
    run_dir = tmp_path / "run"

    @contextmanager
    def fake_dataset() -> Iterator[LoadedImagePanelDataset]:
        yield cast(LoadedImagePanelDataset, object())

    def bundle(*args: object, **kwargs: object) -> tuple[object, object, object]:
        del args, kwargs
        events.append("bundle-preflight")
        return object(), object(), object()

    def read_credential() -> str:
        events.append("credentials")
        return "should-not-be-read"

    def reject_reused_run(_: Path) -> Path:
        events.append("output-preflight")
        raise ImagePanelLiveCliError("run directory is not new")

    monkeypatch.setattr(app_main, "_derived_dataset", fake_dataset)
    monkeypatch.setattr(app_main, "_load_live_bundle", bundle)
    monkeypatch.setattr(app_main, "_create_live_run_directory", reject_reused_run)
    monkeypatch.setattr(app_main, "_read_live_credential", read_credential)

    exit_code = app_main.main(
        [
            "live",
            "--manifest",
            "manifest.json",
            "--manifest-file-sha256",
            "0" * 64,
            "--authorization",
            "authorization.json",
            "--authorization-file-sha256",
            "0" * 64,
            "--requests",
            "requests.jsonl",
            "--requests-file-sha256",
            "0" * 64,
            "--pricing",
            "pricing.json",
            "--pricing-file-sha256",
            "0" * 64,
            "--run-dir",
            str(run_dir),
        ]
    )

    assert exit_code == 1
    assert events == ["bundle-preflight", "output-preflight"]
    assert "should-not-be-read" not in capsys.readouterr().err


def test_provider_free_live_boundary_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    app_image_plan: ImageExperimentPlan,
) -> None:
    authorization = issue_authorization(
        manifest=app_image_plan.manifest,
        valid_from=NOW - timedelta(seconds=30),
        valid_until=NOW + timedelta(minutes=30),
        approved_by_ref="operator-fixture",
        acknowledgement=MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    )
    manifest_path = Path("output/evals/run/manifest.json")
    authorization_path = Path("output/evals/run/authorization.json")

    class FakeStore:
        def load_json_model(self, path: Path, model: object) -> object:
            del model
            return app_image_plan.manifest if path == manifest_path else authorization

        def file_sha256(self, path: Path) -> tuple[str, int]:
            return ("a" * 64, 1) if path == manifest_path else ("b" * 64, 1)

    monkeypatch.setattr(
        provider_free_runner,
        "SecureEvidenceStore",
        lambda **_: FakeStore(),
    )
    monkeypatch.setattr(
        provider_free_runner,
        "validate_authorization_binding",
        lambda *args, **kwargs: None,
    )
    args = type(
        "Args",
        (),
        {
            "acknowledgement": MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
            "manifest": manifest_path,
            "authorization": authorization_path,
            "manifest_sha256": "a" * 64,
            "authorization_sha256": "b" * 64,
        },
    )()

    assert provider_free_runner._live_boundary(args) == 2
    assert "provider-free CLI never reads credentials" in capsys.readouterr().err


def test_incomplete_execution_exits_nonzero_through_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = ImagePlanExecutionResult(
        attempts=(),
        stopped_model_refs=("evaluator-glm-5v-turbo",),
        skipped_attempt_count=119,
    )

    async def incomplete(_: object) -> int:
        return _execution_exit_code(result)

    monkeypatch.setattr(app_main, "_live", incomplete)
    assert (
        app_main.main(
            [
                "live",
                "--manifest",
                "manifest.json",
                "--manifest-file-sha256",
                "0" * 64,
                "--authorization",
                "authorization.json",
                "--authorization-file-sha256",
                "0" * 64,
                "--requests",
                "requests.jsonl",
                "--requests-file-sha256",
                "0" * 64,
                "--pricing",
                "pricing.json",
                "--pricing-file-sha256",
                "0" * 64,
                "--run-dir",
                "output/evals/run",
            ]
        )
        == 2
    )


def test_unknown_provider_route_is_never_composed() -> None:
    with pytest.raises(ImagePanelLiveAdapterError, match="only the direct Zhipu route"):
        live_adapter._endpoint_for_provider("untrusted")
