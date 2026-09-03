from __future__ import annotations

import argparse
import hashlib
import io
import json
import stat
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from app.application.ports.ip_assets import (
    IpAssetMetadataMutationOutcome,
    IpAssetObjectDescriptor,
    IpAssetRecord,
    IpAssetRepairableMetadataState,
)
from app.application.services.ip_asset_metadata_repair import (
    apply_metadata_repair_plan,
    create_metadata_repair_canary,
    create_metadata_repair_plan,
    prepare_approved_repair_assets,
    restore_metadata_repair_result,
    validate_metadata_repair_plan,
    validate_metadata_repair_result,
    verify_approved_repair_assets,
)
from app.core.config import Settings
from app.core.errors import (
    InvalidProviderOutputError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.domain.ip_asset_metadata_repair import (
    IP_ASSET_METADATA_REPAIR_ACKNOWLEDGEMENT,
    IP_ASSET_METADATA_REPAIR_CANARY_SCHEMA_VERSION,
    IP_ASSET_METADATA_REPAIR_MAX_ASSETS,
    IP_ASSET_METADATA_REPAIR_MODEL,
    IP_ASSET_METADATA_REPAIR_PLAN_SCHEMA_VERSION,
    IP_ASSET_METADATA_REPAIR_RESULT_SCHEMA_VERSION,
    IpAssetMetadataMutationStatus,
    IpAssetMetadataRepairCallStatus,
    IpAssetMetadataRepairCanary,
    IpAssetMetadataRepairErrorCode,
    IpAssetMetadataRepairItemStatus,
    IpAssetMetadataRepairPlan,
    IpAssetMetadataRepairPlanItem,
    IpAssetMetadataRepairResult,
    IpAssetRepairMetadata,
    canonical_json,
    content_commitment,
    metadata_fingerprint,
)
from app.domain.ip_asset_recognition import (
    IpAssetRecognitionRequest,
    IpAssetRecognitionSuggestion,
)
from app.domain.ip_assets import (
    IpAssetCharacter,
    IpAssetMetadata,
    IpAssetOrientation,
    IpAssetSemanticStatus,
    IpAssetSource,
    IpAssetStatus,
    IpAssetType,
)
from app.infrastructure.ip_asset_metadata_repair_artifacts import (
    read_private_artifact,
    reserve_private_artifact,
    write_private_artifact,
)
from PIL import Image


def _png(index: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (32, 32), (index, 255 - index, index * 3 % 255, 255)).save(
        output, format="PNG"
    )
    return output.getvalue()


def _record(index: int, body: bytes) -> IpAssetRecord:
    digest = hashlib.sha256(body).hexdigest()
    created_at = datetime(2026, 9, 2, 9, index, tzinfo=UTC)
    return IpAssetRecord(
        id=UUID(int=index + 1),
        asset_ref=f"ipa_{index + 1:020x}",
        blob_sha256=digest,
        perceptual_hash=f"{index + 1:016x}",
        safe_original_filename=f"private-seed-{index}.png",
        media_type="image/png",
        byte_size=len(body),
        width=32,
        height=32,
        has_alpha=True,
        orientation=IpAssetOrientation.SQUARE,
        bucket="private-bucket",
        object_key=f"ip-assets/originals/sha256/{digest[:2]}/{digest}.png",
        canonical_name=f"小赛-全身动作-方图-v{index + 1:03d}",
        canonical_slug=f"xiao-sai-action-square-v{index + 1:03d}",
        name_version=index + 1,
        character=IpAssetCharacter.XIAO_SAI,
        asset_type=IpAssetType.FULL_BODY_ACTION,
        source_kind=IpAssetSource.SEED_IMPORT,
        department="品牌部",
        contributor="素材管理员",
        emotion="",
        action="站立",
        scene="",
        intended_use="",
        style="3D",
        tags=("站立", "3D", "seed"),
        status=IpAssetStatus.READY,
        semantic_status=IpAssetSemanticStatus.READY,
        failure_code=None,
        parent_asset_id=None,
        created_at=created_at,
        updated_at=created_at,
        shared_at=created_at,
    )


class _MemoryRepository:
    def __init__(self) -> None:
        self.bodies = tuple(_png(index) for index in range(IP_ASSET_METADATA_REPAIR_MAX_ASSETS))
        self.by_sha = {
            record.blob_sha256: record
            for index, body in enumerate(self.bodies)
            if (record := _record(index, body))
        }
        self.metadata = {
            record.asset_ref: IpAssetMetadata(
                character=record.character,
                asset_type=record.asset_type,
                department=record.department,
                contributor=record.contributor,
                emotion=record.emotion,
                action=record.action,
                scene=record.scene,
                intended_use=record.intended_use,
                style=record.style,
                tags=("seed",),
            )
            for record in self.by_sha.values()
        }
        self.mutation_calls = 0

    async def get_by_sha256(self, sha256: str) -> IpAssetRecord | None:
        return self.by_sha.get(sha256)

    async def get_repairable_metadata(
        self, asset_ref: str
    ) -> IpAssetRepairableMetadataState | None:
        record = next(
            (record for record in self.by_sha.values() if record.asset_ref == asset_ref), None
        )
        if record is None:
            return None
        return IpAssetRepairableMetadataState(asset=record, metadata=self.metadata[asset_ref])

    async def compare_and_swap_metadata(
        self,
        *,
        asset_ref: str,
        expected_content_commitment: str,
        expected_metadata_fingerprint: str,
        target_metadata: IpAssetMetadata,
        target_metadata_fingerprint: str,
    ) -> IpAssetMetadataMutationOutcome:
        self.mutation_calls += 1
        state = await self.get_repairable_metadata(asset_ref)
        if state is None:
            return IpAssetMetadataMutationOutcome(IpAssetMetadataMutationStatus.NOT_FOUND, None)
        if content_commitment(state.asset.blob_sha256) != expected_content_commitment:
            return IpAssetMetadataMutationOutcome(
                IpAssetMetadataMutationStatus.CONTENT_DRIFT, state
            )
        current_fingerprint = metadata_fingerprint(state.metadata)
        if current_fingerprint == target_metadata_fingerprint:
            return IpAssetMetadataMutationOutcome(
                IpAssetMetadataMutationStatus.ALREADY_APPLIED, state
            )
        if current_fingerprint != expected_metadata_fingerprint:
            return IpAssetMetadataMutationOutcome(
                IpAssetMetadataMutationStatus.METADATA_DRIFT, state
            )
        current = self.metadata[asset_ref]
        self.metadata[asset_ref] = IpAssetMetadata(
            character=target_metadata.character,
            asset_type=target_metadata.asset_type,
            department=current.department,
            contributor=current.contributor,
            emotion=target_metadata.emotion,
            action=target_metadata.action,
            scene=target_metadata.scene,
            intended_use=target_metadata.intended_use,
            style=target_metadata.style,
            tags=target_metadata.tags,
        )
        updated = await self.get_repairable_metadata(asset_ref)
        assert updated is not None
        return IpAssetMetadataMutationOutcome(IpAssetMetadataMutationStatus.APPLIED, updated)


class _MemoryStore:
    def __init__(self, repository: _MemoryRepository) -> None:
        self._bodies = {hashlib.sha256(body).hexdigest(): body for body in repository.bodies}

    async def get_verified(self, descriptor: IpAssetObjectDescriptor) -> bytes:
        return self._bodies[descriptor.sha256]


class _SuggestionModel:
    def __init__(
        self,
        *,
        error: ProviderError | None = None,
        error_on_call: int | None = None,
    ) -> None:
        self.error = error
        self.error_on_call = error_on_call
        self.calls: list[IpAssetRecognitionRequest] = []

    async def suggest(self, request: IpAssetRecognitionRequest) -> IpAssetRecognitionSuggestion:
        self.calls.append(request)
        if self.error is not None and (
            self.error_on_call is None or len(self.calls) == self.error_on_call
        ):
            raise self.error
        return IpAssetRecognitionSuggestion(
            character=IpAssetCharacter.SAI_XIANSHENG,
            asset_type=IpAssetType.PORTRAIT_AVATAR,
            emotion="开心",
            action="挥手",
            scene="空间站",
            intended_use="公众号配图",
            style="3D",
            tags=("seed", "空间站"),
            provider="zhipu",
            model=IP_ASSET_METADATA_REPAIR_MODEL,
        )


async def _no_sleep(_delay: float) -> None:
    return None


async def _plan(
    repository: _MemoryRepository, model: _SuggestionModel
) -> IpAssetMetadataRepairPlan:
    approved = tuple(repository.by_sha)
    selected = await prepare_approved_repair_assets(
        repository=repository,  # type: ignore[arg-type]
        approved_checksums=approved,
    )
    store = _MemoryStore(repository)
    canary = await create_metadata_repair_canary(
        selected=selected,
        store=store,  # type: ignore[arg-type]
        recognition_model=model,
        now=datetime(2026, 9, 2, 9, 59, tzinfo=UTC),
    )
    return await create_metadata_repair_plan(
        selected=selected,
        store=store,  # type: ignore[arg-type]
        recognition_model=model,
        canary=canary,
        sleep=_no_sleep,
        now=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_plan_uses_exact_41_calls_conservative_merge_and_private_artifact(
    tmp_path: Path,
) -> None:
    repository = _MemoryRepository()
    model = _SuggestionModel()

    selected = await prepare_approved_repair_assets(
        repository=repository,  # type: ignore[arg-type]
        approved_checksums=tuple(repository.by_sha),
    )
    preflight = await verify_approved_repair_assets(
        selected=selected,
        store=_MemoryStore(repository),  # type: ignore[arg-type]
    )

    plan = await _plan(repository, model)

    assert preflight.selected_count == preflight.verified_count == 41
    assert preflight.asset_type_distribution == (("full_body_action", 41),)
    validate_metadata_repair_plan(plan, require_exact_set=True)
    assert len(model.calls) == 41
    assert plan.provider_call_count == 41
    assert plan.schema_version == IP_ASSET_METADATA_REPAIR_PLAN_SCHEMA_VERSION
    assert plan.model == IP_ASSET_METADATA_REPAIR_MODEL == "glm-5v-turbo"
    assert plan.changed_count == 41
    assert plan.failed_count == 0
    assert all(item.status is IpAssetMetadataRepairItemStatus.CHANGED for item in plan.items)
    assert all(item.proposed_metadata is not None for item in plan.items)
    assert all(
        item.proposed_metadata.character is IpAssetCharacter.XIAO_SAI
        and item.proposed_metadata.asset_type is IpAssetType.PORTRAIT_AVATAR
        and item.proposed_metadata.tags == ("seed", "空间站")
        for item in plan.items
        if item.proposed_metadata is not None
    )
    serialized = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)
    assert "private-seed" not in serialized
    assert "private-bucket" not in serialized
    assert "ip-assets/originals" not in serialized
    assert all(raw_digest not in serialized for raw_digest in repository.by_sha)

    path = tmp_path / "private" / "plan.json"
    write_private_artifact(path, plan)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    loaded = read_private_artifact(path, IpAssetMetadataRepairPlan)
    assert loaded == plan
    with pytest.raises(FileExistsError):
        write_private_artifact(path, plan)
    path.parent.chmod(0o755)
    with pytest.raises(ValueError, match="directory is not private"):
        read_private_artifact(path, IpAssetMetadataRepairPlan)


def test_repair_metadata_rejects_private_storage_and_identity_tokens() -> None:
    base = {
        "character": IpAssetCharacter.XIAO_SAI,
        "asset_type": IpAssetType.FULL_BODY_ACTION,
    }

    for private_value in (
        "/private/ip-assets/original.png",
        "550e8400-e29b-41d4-a716-446655440000",
        "Bearer private-token-value",
        "data:image/png;base64,private",
    ):
        with pytest.raises(ValueError, match="private artifact data"):
            IpAssetRepairMetadata(**base, scene=private_value)


@pytest.mark.asyncio
async def test_approved_set_rejects_private_before_metadata_during_preflight() -> None:
    repository = _MemoryRepository()
    first_ref = next(iter(repository.metadata))
    repository.metadata[first_ref] = replace(
        repository.metadata[first_ref], scene="/private/original.png"
    )

    with pytest.raises(ValueError, match="private artifact data"):
        await prepare_approved_repair_assets(
            repository=repository,  # type: ignore[arg-type]
            approved_checksums=tuple(repository.by_sha),
        )


@pytest.mark.asyncio
async def test_plan_schema_rejects_noncanonical_diff_and_status() -> None:
    plan = await _plan(_MemoryRepository(), _SuggestionModel())
    payload = plan.model_dump(mode="json")
    payload["items"][0]["changed_fields"] = ["style"]

    with pytest.raises(ValueError, match="changed fields are not canonical"):
        IpAssetMetadataRepairPlan.model_validate_json(json.dumps(payload))

    payload = plan.model_dump(mode="json")
    payload["items"][0]["status"] = "unchanged"
    with pytest.raises(ValueError, match="non-changed repair item"):
        IpAssetMetadataRepairPlan.model_validate_json(json.dumps(payload))


@pytest.mark.asyncio
async def test_glm5_v2_contract_rejects_legacy_canary_plan_and_result_before_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import ip_asset_metadata_repair_main as cli

    repository = _MemoryRepository()
    selected = await prepare_approved_repair_assets(
        repository=repository,  # type: ignore[arg-type]
        approved_checksums=tuple(repository.by_sha),
    )
    canary = await create_metadata_repair_canary(
        selected=selected,
        store=_MemoryStore(repository),  # type: ignore[arg-type]
        recognition_model=_SuggestionModel(),
        now=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
    )
    plan = await create_metadata_repair_plan(
        selected=selected,
        store=_MemoryStore(repository),  # type: ignore[arg-type]
        recognition_model=_SuggestionModel(),
        canary=canary,
        sleep=_no_sleep,
        now=datetime(2026, 9, 3, 9, 1, tzinfo=UTC),
    )
    result = await apply_metadata_repair_plan(
        repository=repository,  # type: ignore[arg-type]
        store=_MemoryStore(repository),  # type: ignore[arg-type]
        plan=plan,
        now=datetime(2026, 9, 3, 9, 2, tzinfo=UTC),
    )

    assert canary.schema_version == IP_ASSET_METADATA_REPAIR_CANARY_SCHEMA_VERSION
    assert canary.model == IP_ASSET_METADATA_REPAIR_MODEL == "glm-5v-turbo"
    assert plan.schema_version == IP_ASSET_METADATA_REPAIR_PLAN_SCHEMA_VERSION
    assert plan.model == IP_ASSET_METADATA_REPAIR_MODEL
    assert result.schema_version == IP_ASSET_METADATA_REPAIR_RESULT_SCHEMA_VERSION
    assert result.provider == "zhipu"
    assert result.model == IP_ASSET_METADATA_REPAIR_MODEL

    def legacy_domain_fingerprint(
        value: IpAssetMetadataRepairCanary
        | IpAssetMetadataRepairPlan
        | IpAssetMetadataRepairResult,
        *,
        field: str,
        domain: str,
    ) -> str:
        payload = value.model_dump(mode="json", exclude={field})
        return hashlib.sha256(domain.encode() + b"\0" + canonical_json(payload)).hexdigest()

    assert canary.canary_fingerprint != legacy_domain_fingerprint(
        canary,
        field="canary_fingerprint",
        domain="ip-asset-metadata-repair-canary-fingerprint-v1",
    )
    assert plan.plan_fingerprint != legacy_domain_fingerprint(
        plan,
        field="plan_fingerprint",
        domain="ip-asset-metadata-repair-plan-fingerprint-v1",
    )
    assert result.result_fingerprint != legacy_domain_fingerprint(
        result,
        field="result_fingerprint",
        domain="ip-asset-metadata-repair-result-fingerprint-v1",
    )

    legacy_canary = canary.model_dump(mode="json")
    legacy_canary["schema_version"] = "ip-asset-metadata-repair-canary-v1"
    legacy_canary["model"] = "glm-4.6v-flash"
    with pytest.raises(ValueError):
        type(canary).model_validate_json(json.dumps(legacy_canary))

    legacy_plan = plan.model_dump(mode="json")
    legacy_plan["schema_version"] = "ip-asset-metadata-repair-plan-v1"
    legacy_plan["model"] = "glm-4.6v-flash"
    with pytest.raises(ValueError):
        type(plan).model_validate_json(json.dumps(legacy_plan))

    legacy_result = result.model_dump(mode="json")
    legacy_result["schema_version"] = "ip-asset-metadata-repair-result-v1"
    legacy_result.pop("provider")
    legacy_result.pop("model")
    with pytest.raises(ValueError):
        type(result).model_validate_json(json.dumps(legacy_result))

    monkeypatch.setattr(cli, "_OUTPUT_ROOT", tmp_path)
    inputs = (
        ("plan", "canary", legacy_canary),
        ("apply", "plan", legacy_plan),
        ("restore", "result", legacy_result),
    )

    async def must_not_reach_provider_or_database_setup(
        _args: argparse.Namespace, *, input_artifact: object | None = None
    ) -> int:
        raise AssertionError(f"unexpected side-effect setup: {input_artifact!r}")

    monkeypatch.setattr(
        cli, "_run_side_effecting_command", must_not_reach_provider_or_database_setup
    )
    for command, input_name, payload in inputs:
        input_path = tmp_path / f"legacy-{input_name}.json"
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        input_path.chmod(0o600)
        output_path = tmp_path / f"new-{command}.json"
        args = SimpleNamespace(
            command=command,
            acknowledgement=IP_ASSET_METADATA_REPAIR_ACKNOWLEDGEMENT,
            output=output_path,
            **{input_name: input_path},
        )
        with pytest.raises(ValueError):
            await cli._run(args)
        assert not output_path.exists()
        assert not (tmp_path / f".{output_path.name}.lock").exists()


@pytest.mark.parametrize(
    ("error", "expected_code"),
    (
        (
            ProviderAuthenticationError(),
            IpAssetMetadataRepairErrorCode.PROVIDER_AUTHENTICATION_FAILED,
        ),
        (ProviderRateLimitError(), IpAssetMetadataRepairErrorCode.PROVIDER_RATE_LIMITED),
        (ProviderRejectedError(), IpAssetMetadataRepairErrorCode.PROVIDER_REQUEST_REJECTED),
        (ProviderTimeoutError(), IpAssetMetadataRepairErrorCode.PROVIDER_TIMEOUT),
        (
            InvalidProviderOutputError(("private-raw-issue",)),
            IpAssetMetadataRepairErrorCode.INVALID_PROVIDER_OUTPUT,
        ),
        (ProviderUnavailableError(), IpAssetMetadataRepairErrorCode.PROVIDER_UNAVAILABLE),
    ),
)
@pytest.mark.asyncio
async def test_canary_failure_stops_after_one_call_and_records_safe_category(
    error: ProviderError,
    expected_code: IpAssetMetadataRepairErrorCode,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app import ip_asset_metadata_repair_main as cli

    repository = _MemoryRepository()
    model = _SuggestionModel(error=error)
    selected = await prepare_approved_repair_assets(
        repository=repository,  # type: ignore[arg-type]
        approved_checksums=tuple(repository.by_sha),
    )

    canary = await create_metadata_repair_canary(
        selected=selected,
        store=_MemoryStore(repository),  # type: ignore[arg-type]
        recognition_model=model,
        now=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
    )

    assert len(model.calls) == 1
    assert canary.provider_call_count == 1
    assert canary.item.status is IpAssetMetadataRepairItemStatus.PROVIDER_FAILED
    assert canary.item.error_code is expected_code
    serialized = json.dumps(canary.model_dump(mode="json"), ensure_ascii=False)
    assert "private-raw-issue" not in serialized
    cli._print_canary_summary(canary, operation="canary")
    summary = json.loads(capsys.readouterr().out)
    assert summary["error_code"] == expected_code.value
    assert summary["local_schema_valid"] is False
    assert summary["provider_json_mode_requested"] is False
    assert "schema_valid" not in summary
    assert "json_mode_valid" not in summary
    assert "private-raw-issue" not in json.dumps(summary)

    remaining_model = _SuggestionModel()
    with pytest.raises(ValueError, match="canary did not pass"):
        await create_metadata_repair_plan(
            selected=selected,
            store=_MemoryStore(repository),  # type: ignore[arg-type]
            recognition_model=remaining_model,
            canary=canary,
            now=datetime(2026, 9, 2, 10, 1, tzinfo=UTC),
        )
    assert remaining_model.calls == []


@pytest.mark.asyncio
async def test_successful_canary_summary_names_local_validation_without_json_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app import ip_asset_metadata_repair_main as cli

    repository = _MemoryRepository()
    selected = await prepare_approved_repair_assets(
        repository=repository,  # type: ignore[arg-type]
        approved_checksums=tuple(repository.by_sha),
    )
    canary = await create_metadata_repair_canary(
        selected=selected,
        store=_MemoryStore(repository),  # type: ignore[arg-type]
        recognition_model=_SuggestionModel(),
        now=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
    )

    cli._print_canary_summary(canary, operation="canary")
    summary = json.loads(capsys.readouterr().out)

    assert summary["passed"] is True
    assert summary["schema_version"] == IP_ASSET_METADATA_REPAIR_CANARY_SCHEMA_VERSION
    assert summary["model"] == IP_ASSET_METADATA_REPAIR_MODEL
    assert summary["local_schema_valid"] is True
    assert summary["provider_json_mode_requested"] is False
    assert summary["error_code"] is None
    assert "schema_valid" not in summary
    assert "json_mode_valid" not in summary


@pytest.mark.parametrize(
    "transient_error",
    (ProviderRateLimitError(), ProviderTimeoutError(), ProviderUnavailableError()),
)
@pytest.mark.asyncio
async def test_batch_stops_on_first_shared_transient_and_partial_plan_cannot_apply(
    transient_error: ProviderError,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app import ip_asset_metadata_repair_main as cli

    repository = _MemoryRepository()
    selected = await prepare_approved_repair_assets(
        repository=repository,  # type: ignore[arg-type]
        approved_checksums=tuple(repository.by_sha),
    )
    canary = await create_metadata_repair_canary(
        selected=selected,
        store=_MemoryStore(repository),  # type: ignore[arg-type]
        recognition_model=_SuggestionModel(),
        now=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
    )
    model = _SuggestionModel(error=transient_error, error_on_call=3)
    pacing: list[float] = []

    async def record_pacing(delay: float) -> None:
        pacing.append(delay)

    plan = await create_metadata_repair_plan(
        selected=selected,
        store=_MemoryStore(repository),  # type: ignore[arg-type]
        recognition_model=model,
        canary=canary,
        inter_request_pacing_seconds=2.0,
        sleep=record_pacing,
        now=datetime(2026, 9, 2, 10, 1, tzinfo=UTC),
    )

    assert len(model.calls) == 3
    assert pacing == [2.0, 2.0, 2.0]
    assert plan.provider_call_count == 4
    assert plan.scanned_count == 4
    assert plan.suggested_count == 3
    assert plan.failed_count == 38
    assert plan.items[3].error_code in {
        IpAssetMetadataRepairErrorCode.PROVIDER_RATE_LIMITED,
        IpAssetMetadataRepairErrorCode.PROVIDER_TIMEOUT,
        IpAssetMetadataRepairErrorCode.PROVIDER_UNAVAILABLE,
    }
    assert all(
        item.status is IpAssetMetadataRepairItemStatus.NOT_PROCESSED
        and item.error_code is IpAssetMetadataRepairErrorCode.NOT_CALLED_AFTER_TRANSIENT_FAILURE
        and item.provider_call_status is IpAssetMetadataRepairCallStatus.NOT_CALLED
        and item.suggestion_metadata is None
        and item.proposed_metadata is None
        for item in plan.items[4:]
    )
    validate_metadata_repair_plan(plan, require_exact_set=True)

    monkeypatch.setattr(cli, "_OUTPUT_ROOT", tmp_path)
    path = tmp_path / "partial-plan.json"
    write_private_artifact(path, plan)
    loaded = read_private_artifact(path, IpAssetMetadataRepairPlan)
    assert loaded == plan
    assert await cli._run(SimpleNamespace(command="validate-plan", plan=path)) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["failed_count"] == 38
    assert summary["provider_call_count"] == 4
    assert summary["schema_version"] == IP_ASSET_METADATA_REPAIR_PLAN_SCHEMA_VERSION
    assert summary["model"] == IP_ASSET_METADATA_REPAIR_MODEL

    malformed_remainder = plan.items[4].model_dump(mode="json")
    malformed_remainder["error_code"] = IpAssetMetadataRepairErrorCode.READ_FAILED.value
    with pytest.raises(ValueError, match="interrupted-item shape"):
        IpAssetMetadataRepairPlanItem.model_validate_json(json.dumps(malformed_remainder))

    malformed_remainder = plan.items[4].model_dump(mode="json")
    malformed_remainder["provider_call_status"] = IpAssetMetadataRepairCallStatus.FAILED.value
    with pytest.raises(ValueError, match="call status is inconsistent"):
        IpAssetMetadataRepairPlanItem.model_validate_json(json.dumps(malformed_remainder))

    malformed_plan = plan.model_dump(mode="json")
    malformed_plan["items"][5]["status"] = IpAssetMetadataRepairItemStatus.READ_FAILED.value
    malformed_plan["items"][5]["error_code"] = IpAssetMetadataRepairErrorCode.READ_FAILED.value
    malformed_plan["scanned_count"] += 1
    with pytest.raises(ValueError, match="interrupted suffix is inconsistent"):
        IpAssetMetadataRepairPlan.model_validate_json(json.dumps(malformed_plan))

    before_metadata = dict(repository.metadata)
    with pytest.raises(ValueError, match="complete recognition plan"):
        await apply_metadata_repair_plan(
            repository=repository,  # type: ignore[arg-type]
            store=_MemoryStore(repository),  # type: ignore[arg-type]
            plan=loaded,
            now=datetime(2026, 9, 2, 10, 2, tzinfo=UTC),
        )
    assert repository.mutation_calls == 0
    assert repository.metadata == before_metadata


def test_cli_plan_pacing_default_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import ip_asset_metadata_repair_main as cli

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ip-asset-metadata-repair",
            "plan",
            "--output",
            "plan.json",
            "--canary",
            "canary.json",
            "--acknowledgement",
            "ack",
        ],
    )
    assert cli._arguments().pacing_seconds == 2.0
    assert cli._pacing_seconds("0.5") == 0.5
    assert cli._pacing_seconds("60") == 60.0
    for invalid in ("0", "0.49", "61", "nan", "not-a-number"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli._pacing_seconds(invalid)


def test_cli_binds_generic_factory_to_exact_glm5_contract() -> None:
    from app import ip_asset_metadata_repair_main as cli

    base = Settings(_env_file=None)
    repair = cli._repair_provider_settings(base)

    assert base.ip_asset_recognition_model == "glm-4.1v-thinking-flash"
    assert repair.ip_asset_recognition_model == IP_ASSET_METADATA_REPAIR_MODEL
    assert repair.ip_asset_recognition_concurrency == 1


def test_cli_artifact_path_keeps_symlink_for_artifact_layer_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import ip_asset_metadata_repair_main as cli

    output_root = tmp_path / "output"
    real_directory = output_root / "real"
    real_directory.mkdir(parents=True)
    alias = output_root / "alias"
    alias.symlink_to(real_directory, target_is_directory=True)
    monkeypatch.setattr(cli, "_OUTPUT_ROOT", output_root)

    path = cli._local_artifact_path(alias / "plan.json")

    assert path == alias / "plan.json"
    with pytest.raises(ValueError, match="cannot contain a symlink"):
        with reserve_private_artifact(path):
            pass
    with pytest.raises(ValueError, match="private output root"):
        cli._local_artifact_path(output_root / ".." / "outside.json")


@pytest.mark.asyncio
async def test_apply_is_idempotent_and_result_can_restore_without_provider() -> None:
    repository = _MemoryRepository()
    model = _SuggestionModel()
    plan = await _plan(repository, model)
    store = _MemoryStore(repository)

    applied = await apply_metadata_repair_plan(
        repository=repository,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        plan=plan,
        now=datetime(2026, 9, 2, 10, 5, tzinfo=UTC),
    )
    replayed = await apply_metadata_repair_plan(
        repository=repository,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        plan=plan,
        now=datetime(2026, 9, 2, 10, 6, tzinfo=UTC),
    )
    restored = await restore_metadata_repair_result(
        repository=repository,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        applied=applied,
        now=datetime(2026, 9, 2, 10, 7, tzinfo=UTC),
    )
    restore_replay = await restore_metadata_repair_result(
        repository=repository,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        applied=applied,
        now=datetime(2026, 9, 2, 10, 8, tzinfo=UTC),
    )

    validate_metadata_repair_result(applied)
    validate_metadata_repair_result(replayed)
    validate_metadata_repair_result(restored)
    validate_metadata_repair_result(restore_replay)
    assert (applied.changed_count, applied.already_applied_count) == (41, 0)
    assert (replayed.changed_count, replayed.already_applied_count) == (0, 41)
    assert (restored.changed_count, restored.already_applied_count) == (41, 0)
    assert (restore_replay.changed_count, restore_replay.already_applied_count) == (0, 41)
    assert all(
        metadata.asset_type is IpAssetType.FULL_BODY_ACTION and metadata.tags == ("seed",)
        for metadata in repository.metadata.values()
    )

    payload = applied.model_dump(mode="json")
    payload["items"][0]["proposed_metadata"] = None
    payload["items"][0]["proposed_metadata_fingerprint"] = None
    with pytest.raises(ValueError, match="requires proposed metadata"):
        type(applied).model_validate_json(json.dumps(payload))


@pytest.mark.asyncio
async def test_apply_fails_closed_on_metadata_drift() -> None:
    repository = _MemoryRepository()
    plan = await _plan(repository, _SuggestionModel())
    store = _MemoryStore(repository)
    drifted_ref = plan.items[0].asset_ref
    repository.metadata[drifted_ref] = replace(repository.metadata[drifted_ref], emotion="人工修改")

    result = await apply_metadata_repair_plan(
        repository=repository,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        plan=plan,
        now=datetime(2026, 9, 2, 10, 5, tzinfo=UTC),
    )

    assert result.changed_count == 40
    assert result.drift_count == 1
    assert result.items[0].status is IpAssetMetadataMutationStatus.METADATA_DRIFT
    assert repository.metadata[drifted_ref].emotion == "人工修改"


@pytest.mark.asyncio
async def test_apply_verifies_object_bytes_before_each_row_cas() -> None:
    repository = _MemoryRepository()
    plan = await _plan(repository, _SuggestionModel())
    store = _MemoryStore(repository)
    drifted_ref = plan.items[0].asset_ref
    drifted_record = next(
        record for record in repository.by_sha.values() if record.asset_ref == drifted_ref
    )
    store._bodies[drifted_record.blob_sha256] = b"corrupt-object-body"

    result = await apply_metadata_repair_plan(
        repository=repository,  # type: ignore[arg-type]
        store=store,  # type: ignore[arg-type]
        plan=plan,
        now=datetime(2026, 9, 2, 10, 5, tzinfo=UTC),
    )

    assert result.changed_count == 40
    assert result.drift_count == 1
    assert result.items[0].status is IpAssetMetadataMutationStatus.CONTENT_DRIFT
    assert repository.mutation_calls == 40
    assert repository.metadata[drifted_ref].asset_type is IpAssetType.FULL_BODY_ACTION


@pytest.mark.asyncio
async def test_cli_validation_is_provider_free_and_rejects_wrong_acknowledgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app import ip_asset_metadata_repair_main as cli

    plan = await _plan(_MemoryRepository(), _SuggestionModel())
    monkeypatch.setattr(cli, "_OUTPUT_ROOT", tmp_path)
    path = tmp_path / "plan.json"
    write_private_artifact(path, plan)

    code = await cli._run(SimpleNamespace(command="validate-plan", plan=path))
    summary = json.loads(capsys.readouterr().out)

    assert code == 0
    assert summary["operation"] == "validated"
    assert summary["provider_call_count"] == 41
    assert IP_ASSET_METADATA_REPAIR_ACKNOWLEDGEMENT == ("I_ACKNOWLEDGE_LOCAL_IP_METADATA_REPAIR_V2")
    for rejected_acknowledgement in (
        "wrong",
        "I_ACKNOWLEDGE_LOCAL_IP_METADATA_REPAIR_V1",
    ):
        with pytest.raises(ValueError, match="exact local acknowledgement"):
            await cli._run(
                SimpleNamespace(
                    command="apply",
                    acknowledgement=rejected_acknowledgement,
                    plan=path,
                    output=tmp_path / "result.json",
                )
            )
    with pytest.raises(ValueError, match="private output root"):
        cli._local_artifact_path(tmp_path.parent / "outside.json")


@pytest.mark.parametrize("command", ("canary", "plan", "apply", "restore"))
@pytest.mark.asyncio
async def test_cli_rejects_existing_output_before_provider_or_database_side_effects(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import ip_asset_metadata_repair_main as cli

    monkeypatch.setattr(cli, "_OUTPUT_ROOT", tmp_path)
    output = tmp_path / f"{command}.json"
    output.write_text("existing", encoding="utf-8")
    output.chmod(0o600)

    def fail_if_settings_are_loaded() -> None:
        raise AssertionError("output reservation must happen before side effects")

    monkeypatch.setattr(cli, "get_settings", fail_if_settings_are_loaded)
    args = SimpleNamespace(
        command=command,
        acknowledgement=IP_ASSET_METADATA_REPAIR_ACKNOWLEDGEMENT,
        output=output,
        canary=tmp_path / "input-canary.json",
        plan=tmp_path / "input-plan.json",
        result=tmp_path / "input-result.json",
    )

    with pytest.raises(FileExistsError):
        await cli._run(args)

    assert output.read_text(encoding="utf-8") == "existing"
    assert not (tmp_path / f".{command}.json.lock").exists()
