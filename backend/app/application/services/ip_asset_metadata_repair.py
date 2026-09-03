from __future__ import annotations

import asyncio
import hashlib
import math
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

from app.application.ports.ip_assets import (
    IpAssetMetadataMutationOutcome,
    IpAssetObjectDescriptor,
    IpAssetRecognitionModel,
    IpAssetRepairableMetadataState,
    IpAssetRepository,
    IpAssetStore,
)
from app.application.services.ip_asset_recognition import IpAssetRecognitionService
from app.core.errors import IpAssetUploadRejectedError, ProviderError
from app.domain.ip_asset_metadata_repair import (
    IP_ASSET_METADATA_REPAIR_DEFAULT_PACING_SECONDS,
    IP_ASSET_METADATA_REPAIR_MAX_ASSETS,
    IP_ASSET_METADATA_REPAIR_MAX_PACING_SECONDS,
    IP_ASSET_METADATA_REPAIR_MIN_PACING_SECONDS,
    IP_ASSET_METADATA_REPAIR_MODEL,
    IpAssetMetadataMutationStatus,
    IpAssetMetadataRepairCallStatus,
    IpAssetMetadataRepairCanary,
    IpAssetMetadataRepairErrorCode,
    IpAssetMetadataRepairItemStatus,
    IpAssetMetadataRepairPlan,
    IpAssetMetadataRepairPlanItem,
    IpAssetMetadataRepairResult,
    IpAssetMetadataRepairResultItem,
    IpAssetRepairMetadata,
    asset_identity_fingerprint,
    asset_set_fingerprint,
    canary_fingerprint,
    changed_fields,
    content_commitment,
    metadata_fingerprint,
    plan_fingerprint,
    repair_metadata,
    result_fingerprint,
)
from app.domain.ip_asset_recognition import (
    IpAssetRecognitionRequest,
    IpAssetRecognitionSuggestion,
)
from app.domain.ip_assets import (
    IP_ASSET_MAX_FREE_TAGS,
    IpAssetCharacter,
    IpAssetMetadata,
    IpAssetStatus,
    IpAssetType,
)


@dataclass(frozen=True, slots=True)
class _ApprovedRepairAsset:
    state: IpAssetRepairableMetadataState


@dataclass(frozen=True, slots=True)
class IpAssetMetadataRepairPreflight:
    selected_count: int
    verified_count: int
    character_distribution: tuple[tuple[str, int], ...]
    asset_type_distribution: tuple[tuple[str, int], ...]


_Sleep = Callable[[float], Awaitable[None]]
_SHARED_TRANSIENT_ERROR_CODES: Final[frozenset[IpAssetMetadataRepairErrorCode]] = frozenset(
    {
        IpAssetMetadataRepairErrorCode.PROVIDER_RATE_LIMITED,
        IpAssetMetadataRepairErrorCode.PROVIDER_TIMEOUT,
        IpAssetMetadataRepairErrorCode.PROVIDER_UNAVAILABLE,
    }
)


class CountingIpAssetRecognitionModel(IpAssetRecognitionModel):
    """Count actual provider-bound suggest calls without inspecting their payloads."""

    def __init__(self, delegate: IpAssetRecognitionModel) -> None:
        self._delegate = delegate
        self.call_count = 0

    async def suggest(self, request: IpAssetRecognitionRequest) -> IpAssetRecognitionSuggestion:
        self.call_count += 1
        return await self._delegate.suggest(request)


class PacedIpAssetRecognitionModel(IpAssetRecognitionModel):
    """Delay only provider-bound recognition calls, never local reads or validation."""

    def __init__(
        self,
        delegate: IpAssetRecognitionModel,
        *,
        pacing_seconds: float,
        sleep: _Sleep,
    ) -> None:
        self._delegate = delegate
        self._pacing_seconds = _validate_pacing_seconds(pacing_seconds)
        self._sleep = sleep

    async def suggest(self, request: IpAssetRecognitionRequest) -> IpAssetRecognitionSuggestion:
        await self._sleep(self._pacing_seconds)
        return await self._delegate.suggest(request)


async def prepare_approved_repair_assets(
    *, repository: IpAssetRepository, approved_checksums: tuple[str, ...]
) -> tuple[_ApprovedRepairAsset, ...]:
    """Resolve the exact private manifest set before any provider call."""

    if (
        len(approved_checksums) != IP_ASSET_METADATA_REPAIR_MAX_ASSETS
        or len(set(approved_checksums)) != IP_ASSET_METADATA_REPAIR_MAX_ASSETS
    ):
        raise ValueError("IP asset repair requires exactly 41 unique approved assets")
    selected: list[_ApprovedRepairAsset] = []
    seen_asset_refs: set[str] = set()
    for checksum in approved_checksums:
        record = await repository.get_by_sha256(checksum)
        if (
            record is None
            or record.blob_sha256 != checksum
            or record.status is not IpAssetStatus.READY
            or record.shared_at is None
            or record.asset_ref in seen_asset_refs
        ):
            raise ValueError("IP asset repair approved-set mapping is invalid")
        state = await repository.get_repairable_metadata(record.asset_ref)
        if state is None or state.asset.id != record.id or state.asset.blob_sha256 != checksum:
            raise ValueError("IP asset repair metadata projection is invalid")
        # Prove every before-state can enter the private artifact before the first provider call.
        # A private-looking legacy value is a corpus-level preflight failure, never a mid-batch
        # exception after earlier images have already consumed the authorized call budget.
        repair_metadata(state.metadata)
        seen_asset_refs.add(record.asset_ref)
        selected.append(_ApprovedRepairAsset(state=state))
    return tuple(sorted(selected, key=lambda item: item.state.asset.asset_ref))


async def create_metadata_repair_plan(
    *,
    selected: tuple[_ApprovedRepairAsset, ...],
    store: IpAssetStore,
    recognition_model: IpAssetRecognitionModel,
    canary: IpAssetMetadataRepairCanary,
    inter_request_pacing_seconds: float = IP_ASSET_METADATA_REPAIR_DEFAULT_PACING_SECONDS,
    sleep: _Sleep = asyncio.sleep,
    now: datetime | None = None,
) -> IpAssetMetadataRepairPlan:
    if len(selected) != IP_ASSET_METADATA_REPAIR_MAX_ASSETS:
        raise ValueError("IP asset repair plan requires exactly 41 approved assets")
    if tuple(sorted(item.state.asset.asset_ref for item in selected)) != tuple(
        item.state.asset.asset_ref for item in selected
    ):
        raise ValueError("IP asset repair assets must use canonical order")
    validate_metadata_repair_canary(canary, selected=selected, require_pass=True)
    counted_model = CountingIpAssetRecognitionModel(
        PacedIpAssetRecognitionModel(
            recognition_model,
            pacing_seconds=inter_request_pacing_seconds,
            sleep=sleep,
        )
    )
    recognition = IpAssetRecognitionService(counted_model)
    items: list[IpAssetMetadataRepairPlanItem] = [canary.item]
    for index, selected_item in enumerate(selected[1:], start=1):
        item = await _recognize_plan_item(
            state=selected_item.state,
            store=store,
            recognition=recognition,
        )
        items.append(item)
        if item.error_code in _SHARED_TRANSIENT_ERROR_CODES:
            items.extend(
                _not_called_after_transient_failure(remaining.state)
                for remaining in selected[index + 1 :]
            )
            break
    plan = _build_plan(
        items=tuple(items),
        provider_call_count=canary.provider_call_count + counted_model.call_count,
        inter_request_pacing_seconds=inter_request_pacing_seconds,
        created_at=now or datetime.now(UTC),
    )
    validate_metadata_repair_plan(plan, require_exact_set=True)
    return plan


async def create_metadata_repair_canary(
    *,
    selected: tuple[_ApprovedRepairAsset, ...],
    store: IpAssetStore,
    recognition_model: IpAssetRecognitionModel,
    now: datetime | None = None,
) -> IpAssetMetadataRepairCanary:
    if len(selected) != IP_ASSET_METADATA_REPAIR_MAX_ASSETS:
        raise ValueError("IP asset repair canary requires exactly 41 approved assets")
    counted_model = CountingIpAssetRecognitionModel(recognition_model)
    item = await _recognize_plan_item(
        state=selected[0].state,
        store=store,
        recognition=IpAssetRecognitionService(counted_model),
    )
    canary = IpAssetMetadataRepairCanary(
        created_at=now or datetime.now(UTC),
        asset_set_fingerprint=_selected_asset_set_fingerprint(selected),
        provider_call_count=counted_model.call_count,
        item=item,
        canary_fingerprint="0" * 64,
    )
    completed = canary.model_copy(update={"canary_fingerprint": canary_fingerprint(canary)})
    validate_metadata_repair_canary(completed, selected=selected, require_pass=False)
    return completed


async def verify_approved_repair_assets(
    *, selected: tuple[_ApprovedRepairAsset, ...], store: IpAssetStore
) -> IpAssetMetadataRepairPreflight:
    if len(selected) != IP_ASSET_METADATA_REPAIR_MAX_ASSETS:
        raise ValueError("IP asset repair preflight requires exactly 41 approved assets")
    verified_count = 0
    for item in selected:
        asset = item.state.asset
        descriptor = IpAssetObjectDescriptor(
            bucket=asset.bucket,
            object_key=asset.object_key,
            media_type=asset.media_type,
            byte_size=asset.byte_size,
            sha256=asset.blob_sha256,
        )
        body = await store.get_verified(descriptor)
        if hashlib.sha256(body).hexdigest() != asset.blob_sha256:
            raise ValueError("IP asset repair verified content identity changed")
        verified_count += 1
    return IpAssetMetadataRepairPreflight(
        selected_count=len(selected),
        verified_count=verified_count,
        character_distribution=tuple(
            sorted(Counter(item.state.metadata.character.value for item in selected).items())
        ),
        asset_type_distribution=tuple(
            sorted(Counter(item.state.metadata.asset_type.value for item in selected).items())
        ),
    )


async def apply_metadata_repair_plan(
    *,
    repository: IpAssetRepository,
    store: IpAssetStore,
    plan: IpAssetMetadataRepairPlan,
    now: datetime | None = None,
) -> IpAssetMetadataRepairResult:
    validate_metadata_repair_plan(plan, require_exact_set=True, require_complete=True)
    result_items: list[IpAssetMetadataRepairResultItem] = []
    for item in plan.items:
        if item.status is IpAssetMetadataRepairItemStatus.UNCHANGED:
            status = IpAssetMetadataMutationStatus.NO_CHANGE_PLANNED
        elif item.status is not IpAssetMetadataRepairItemStatus.CHANGED:
            status = IpAssetMetadataMutationStatus.NOT_PLANNED
        elif item.proposed_metadata is None or item.proposed_metadata_fingerprint is None:
            raise ValueError("IP asset repair changed item is incomplete")
        else:
            status = await _mutate_one(
                repository=repository,
                store=store,
                item=item,
                expected_metadata=item.before_metadata,
                expected_fingerprint=item.before_metadata_fingerprint,
                target_metadata=item.proposed_metadata,
                target_fingerprint=item.proposed_metadata_fingerprint,
            )
        result_items.append(_result_item(item, status=status))
    return _build_result(
        operation="apply",
        plan=plan,
        items=tuple(result_items),
        created_at=now or datetime.now(UTC),
    )


async def restore_metadata_repair_result(
    *,
    repository: IpAssetRepository,
    store: IpAssetStore,
    applied: IpAssetMetadataRepairResult,
    now: datetime | None = None,
) -> IpAssetMetadataRepairResult:
    validate_metadata_repair_result(applied)
    if applied.operation != "apply":
        raise ValueError("IP asset repair restore requires an apply result")
    result_items: list[IpAssetMetadataRepairResultItem] = []
    for item in applied.items:
        if item.status not in {
            IpAssetMetadataMutationStatus.APPLIED,
            IpAssetMetadataMutationStatus.ALREADY_APPLIED,
        }:
            status = IpAssetMetadataMutationStatus.NOT_PLANNED
        elif item.proposed_metadata is None or item.proposed_metadata_fingerprint is None:
            raise ValueError("IP asset repair applied item is incomplete")
        else:
            status = await _mutate_one(
                repository=repository,
                store=store,
                item=item,
                expected_metadata=item.proposed_metadata,
                expected_fingerprint=item.proposed_metadata_fingerprint,
                target_metadata=item.before_metadata,
                target_fingerprint=item.before_metadata_fingerprint,
            )
            if status is IpAssetMetadataMutationStatus.APPLIED:
                status = IpAssetMetadataMutationStatus.RESTORED
        result_items.append(_result_item(item, status=status))
    return _build_result_from_apply(
        operation="restore",
        applied=applied,
        items=tuple(result_items),
        created_at=now or datetime.now(UTC),
    )


def validate_metadata_repair_plan(
    plan: IpAssetMetadataRepairPlan,
    *,
    require_exact_set: bool,
    require_complete: bool = False,
) -> None:
    if plan.plan_fingerprint != plan_fingerprint(plan):
        raise ValueError("IP asset repair plan fingerprint is invalid")
    if require_exact_set and len(plan.items) != IP_ASSET_METADATA_REPAIR_MAX_ASSETS:
        raise ValueError("IP asset repair plan does not contain the approved set")
    if plan.provider != "zhipu" or plan.model != IP_ASSET_METADATA_REPAIR_MODEL:
        raise ValueError("IP asset repair provider identity is invalid")
    if require_complete and (
        plan.failed_count != 0
        or any(
            item.provider_call_status is not IpAssetMetadataRepairCallStatus.COMPLETED
            for item in plan.items
        )
    ):
        raise ValueError("IP asset repair apply requires a complete recognition plan")


def validate_metadata_repair_canary(
    canary: IpAssetMetadataRepairCanary,
    *,
    selected: tuple[_ApprovedRepairAsset, ...] | None = None,
    require_pass: bool,
) -> None:
    if canary.canary_fingerprint != canary_fingerprint(canary):
        raise ValueError("IP asset repair canary fingerprint is invalid")
    if canary.provider != "zhipu" or canary.model != IP_ASSET_METADATA_REPAIR_MODEL:
        raise ValueError("IP asset repair canary provider identity is invalid")
    if require_pass and (
        canary.provider_call_count != 1
        or canary.item.status
        not in {
            IpAssetMetadataRepairItemStatus.CHANGED,
            IpAssetMetadataRepairItemStatus.UNCHANGED,
        }
    ):
        raise ValueError("IP asset repair canary did not pass")
    if selected is not None:
        first = selected[0].state
        before = repair_metadata(first.metadata)
        if (
            canary.asset_set_fingerprint != _selected_asset_set_fingerprint(selected)
            or canary.item.asset_ref != first.asset.asset_ref
            or canary.item.content_commitment != content_commitment(first.asset.blob_sha256)
            or canary.item.before_metadata_fingerprint != metadata_fingerprint(before)
        ):
            raise ValueError("IP asset repair canary does not match the approved set")


def validate_metadata_repair_result(result: IpAssetMetadataRepairResult) -> None:
    if result.result_fingerprint != result_fingerprint(result):
        raise ValueError("IP asset repair result fingerprint is invalid")
    if len(result.items) != IP_ASSET_METADATA_REPAIR_MAX_ASSETS:
        raise ValueError("IP asset repair result does not contain the approved set")
    if result.provider != "zhipu" or result.model != IP_ASSET_METADATA_REPAIR_MODEL:
        raise ValueError("IP asset repair result provider identity is invalid")


async def _recognize_plan_item(
    *,
    state: IpAssetRepairableMetadataState,
    store: IpAssetStore,
    recognition: IpAssetRecognitionService,
) -> IpAssetMetadataRepairPlanItem:
    before = repair_metadata(state.metadata)
    commitment = content_commitment(state.asset.blob_sha256)
    before_fingerprint = metadata_fingerprint(before)
    descriptor = IpAssetObjectDescriptor(
        bucket=state.asset.bucket,
        object_key=state.asset.object_key,
        media_type=state.asset.media_type,
        byte_size=state.asset.byte_size,
        sha256=state.asset.blob_sha256,
    )
    try:
        body = await store.get_verified(descriptor)
        if hashlib.sha256(body).hexdigest() != state.asset.blob_sha256:
            raise ValueError("verified body identity changed")
    except Exception:
        return IpAssetMetadataRepairPlanItem(
            asset_ref=state.asset.asset_ref,
            content_commitment=commitment,
            before_metadata=before,
            before_metadata_fingerprint=before_fingerprint,
            status=IpAssetMetadataRepairItemStatus.READ_FAILED,
            error_code=IpAssetMetadataRepairErrorCode.READ_FAILED,
            provider_call_status=IpAssetMetadataRepairCallStatus.NOT_CALLED,
        )
    try:
        suggestion = await recognition.recognize(
            filename=state.asset.safe_original_filename,
            media_type=state.asset.media_type,
            body=body,
        )
    except IpAssetUploadRejectedError:
        return IpAssetMetadataRepairPlanItem(
            asset_ref=state.asset.asset_ref,
            content_commitment=commitment,
            before_metadata=before,
            before_metadata_fingerprint=before_fingerprint,
            status=IpAssetMetadataRepairItemStatus.INVALID_RASTER,
            error_code=IpAssetMetadataRepairErrorCode.INVALID_RASTER,
            provider_call_status=IpAssetMetadataRepairCallStatus.NOT_CALLED,
        )
    except ProviderError as error:
        error_code = _safe_provider_error_code(error)
        return IpAssetMetadataRepairPlanItem(
            asset_ref=state.asset.asset_ref,
            content_commitment=commitment,
            before_metadata=before,
            before_metadata_fingerprint=before_fingerprint,
            status=IpAssetMetadataRepairItemStatus.PROVIDER_FAILED,
            error_code=error_code,
            provider_call_status=IpAssetMetadataRepairCallStatus.FAILED,
        )
    if suggestion.provider != "zhipu" or suggestion.model != IP_ASSET_METADATA_REPAIR_MODEL:
        return IpAssetMetadataRepairPlanItem(
            asset_ref=state.asset.asset_ref,
            content_commitment=commitment,
            before_metadata=before,
            before_metadata_fingerprint=before_fingerprint,
            status=IpAssetMetadataRepairItemStatus.PROVIDER_FAILED,
            error_code=IpAssetMetadataRepairErrorCode.PROVIDER_IDENTITY_MISMATCH,
            provider_call_status=IpAssetMetadataRepairCallStatus.FAILED,
        )
    try:
        suggested = IpAssetRepairMetadata(
            character=suggestion.character,
            asset_type=suggestion.asset_type,
            emotion=suggestion.emotion,
            action=suggestion.action,
            scene=suggestion.scene,
            intended_use=suggestion.intended_use,
            style=suggestion.style,
            tags=suggestion.tags,
        )
        proposed = _proposed_metadata(before=before, suggested=suggested)
    except ValueError:
        return IpAssetMetadataRepairPlanItem(
            asset_ref=state.asset.asset_ref,
            content_commitment=commitment,
            before_metadata=before,
            before_metadata_fingerprint=before_fingerprint,
            status=IpAssetMetadataRepairItemStatus.INVALID_SUGGESTION,
            error_code=IpAssetMetadataRepairErrorCode.INVALID_SUGGESTION,
            provider_call_status=IpAssetMetadataRepairCallStatus.FAILED,
        )
    changes = changed_fields(before, proposed)
    return IpAssetMetadataRepairPlanItem(
        asset_ref=state.asset.asset_ref,
        content_commitment=commitment,
        before_metadata=before,
        before_metadata_fingerprint=before_fingerprint,
        suggestion_metadata=suggested,
        proposed_metadata=proposed,
        proposed_metadata_fingerprint=metadata_fingerprint(proposed),
        changed_fields=changes,
        status=(
            IpAssetMetadataRepairItemStatus.CHANGED
            if changes
            else IpAssetMetadataRepairItemStatus.UNCHANGED
        ),
        error_code=None,
        provider_call_status=IpAssetMetadataRepairCallStatus.COMPLETED,
    )


def _safe_provider_error_code(error: ProviderError) -> IpAssetMetadataRepairErrorCode:
    """Project a provider failure into a closed, content-free diagnostic category."""

    mapping = {
        "provider_authentication_failed": (
            IpAssetMetadataRepairErrorCode.PROVIDER_AUTHENTICATION_FAILED
        ),
        "provider_rate_limited": IpAssetMetadataRepairErrorCode.PROVIDER_RATE_LIMITED,
        "provider_request_rejected": (IpAssetMetadataRepairErrorCode.PROVIDER_REQUEST_REJECTED),
        # A locally rejected oversized provider payload is still a request-shape failure;
        # the artifact must not retain payload sizes or image identity.
        "provider_input_limit": IpAssetMetadataRepairErrorCode.PROVIDER_REQUEST_REJECTED,
        "provider_timeout": IpAssetMetadataRepairErrorCode.PROVIDER_TIMEOUT,
        "invalid_provider_output": IpAssetMetadataRepairErrorCode.INVALID_PROVIDER_OUTPUT,
        "provider_unavailable": IpAssetMetadataRepairErrorCode.PROVIDER_UNAVAILABLE,
    }
    return mapping.get(error.code, IpAssetMetadataRepairErrorCode.PROVIDER_UNAVAILABLE)


def _not_called_after_transient_failure(
    state: IpAssetRepairableMetadataState,
) -> IpAssetMetadataRepairPlanItem:
    before = repair_metadata(state.metadata)
    return IpAssetMetadataRepairPlanItem(
        asset_ref=state.asset.asset_ref,
        content_commitment=content_commitment(state.asset.blob_sha256),
        before_metadata=before,
        before_metadata_fingerprint=metadata_fingerprint(before),
        status=IpAssetMetadataRepairItemStatus.NOT_PROCESSED,
        error_code=IpAssetMetadataRepairErrorCode.NOT_CALLED_AFTER_TRANSIENT_FAILURE,
        provider_call_status=IpAssetMetadataRepairCallStatus.NOT_CALLED,
    )


def _validate_pacing_seconds(value: float) -> float:
    if (
        isinstance(value, bool)
        or not math.isfinite(value)
        or not IP_ASSET_METADATA_REPAIR_MIN_PACING_SECONDS
        <= value
        <= IP_ASSET_METADATA_REPAIR_MAX_PACING_SECONDS
    ):
        raise ValueError("IP asset metadata repair pacing is outside the safe bound")
    return value


def _proposed_metadata(
    *, before: IpAssetRepairMetadata, suggested: IpAssetRepairMetadata
) -> IpAssetRepairMetadata:
    new_tags = tuple(tag for tag in suggested.tags if tag not in before.tags)
    merged_tags = (*before.tags, *new_tags[: IP_ASSET_MAX_FREE_TAGS - len(before.tags)])
    return repair_metadata(
        IpAssetMetadata(
            character=(
                before.character
                if before.character is not IpAssetCharacter.OTHER
                else suggested.character
            ),
            asset_type=(
                suggested.asset_type
                if suggested.asset_type is not IpAssetType.OTHER
                else before.asset_type
            ),
            emotion=suggested.emotion or before.emotion,
            action=suggested.action or before.action,
            scene=suggested.scene or before.scene,
            intended_use=suggested.intended_use or before.intended_use,
            style=suggested.style or before.style,
            tags=merged_tags,
        )
    )


def _selected_asset_set_fingerprint(selected: tuple[_ApprovedRepairAsset, ...]) -> str:
    return asset_identity_fingerprint(
        tuple(
            (item.state.asset.asset_ref, content_commitment(item.state.asset.blob_sha256))
            for item in selected
        )
    )


async def _mutate_one(
    *,
    repository: IpAssetRepository,
    store: IpAssetStore,
    item: IpAssetMetadataRepairPlanItem | IpAssetMetadataRepairResultItem,
    expected_metadata: IpAssetRepairMetadata,
    expected_fingerprint: str,
    target_metadata: IpAssetRepairMetadata,
    target_fingerprint: str,
) -> IpAssetMetadataMutationStatus:
    if metadata_fingerprint(expected_metadata) != expected_fingerprint:
        raise ValueError("IP asset repair expected fingerprint is invalid")
    try:
        state = await repository.get_repairable_metadata(item.asset_ref)
    except Exception:
        return IpAssetMetadataMutationStatus.MUTATION_FAILED
    if state is None:
        return IpAssetMetadataMutationStatus.NOT_FOUND
    if state.asset.status is not IpAssetStatus.READY or state.asset.shared_at is None:
        return IpAssetMetadataMutationStatus.NOT_ELIGIBLE
    descriptor = IpAssetObjectDescriptor(
        bucket=state.asset.bucket,
        object_key=state.asset.object_key,
        media_type=state.asset.media_type,
        byte_size=state.asset.byte_size,
        sha256=state.asset.blob_sha256,
    )
    try:
        body = await store.get_verified(descriptor)
        if (
            hashlib.sha256(body).hexdigest() != state.asset.blob_sha256
            or content_commitment(state.asset.blob_sha256) != item.content_commitment
        ):
            return IpAssetMetadataMutationStatus.CONTENT_DRIFT
    except Exception:
        # The mutation cannot prove that the immutable object still matches the plan. Treat
        # unavailable, moved, or corrupt content as drift and leave the row untouched.
        return IpAssetMetadataMutationStatus.CONTENT_DRIFT
    try:
        outcome: IpAssetMetadataMutationOutcome = await repository.compare_and_swap_metadata(
            asset_ref=item.asset_ref,
            expected_content_commitment=item.content_commitment,
            expected_metadata_fingerprint=expected_fingerprint,
            target_metadata=target_metadata.to_domain(),
            target_metadata_fingerprint=target_fingerprint,
        )
    except Exception:
        return IpAssetMetadataMutationStatus.MUTATION_FAILED
    return outcome.status


def _result_item(
    item: IpAssetMetadataRepairPlanItem | IpAssetMetadataRepairResultItem,
    *,
    status: IpAssetMetadataMutationStatus,
) -> IpAssetMetadataRepairResultItem:
    return IpAssetMetadataRepairResultItem(
        asset_ref=item.asset_ref,
        content_commitment=item.content_commitment,
        before_metadata=item.before_metadata,
        proposed_metadata=item.proposed_metadata,
        before_metadata_fingerprint=item.before_metadata_fingerprint,
        proposed_metadata_fingerprint=item.proposed_metadata_fingerprint,
        status=status,
    )


def _build_plan(
    *,
    items: tuple[IpAssetMetadataRepairPlanItem, ...],
    provider_call_count: int,
    inter_request_pacing_seconds: float,
    created_at: datetime,
) -> IpAssetMetadataRepairPlan:
    suggested_count = sum(
        item.status
        in {
            IpAssetMetadataRepairItemStatus.CHANGED,
            IpAssetMetadataRepairItemStatus.UNCHANGED,
        }
        for item in items
    )
    changed_count = sum(item.status is IpAssetMetadataRepairItemStatus.CHANGED for item in items)
    plan = IpAssetMetadataRepairPlan(
        created_at=created_at,
        asset_set_fingerprint=asset_set_fingerprint(items),
        selected_count=len(items),
        scanned_count=sum(
            item.status is not IpAssetMetadataRepairItemStatus.NOT_PROCESSED for item in items
        ),
        suggested_count=suggested_count,
        changed_count=changed_count,
        unchanged_count=suggested_count - changed_count,
        failed_count=len(items) - suggested_count,
        provider_call_count=provider_call_count,
        inter_request_pacing_seconds=inter_request_pacing_seconds,
        items=items,
        plan_fingerprint="0" * 64,
    )
    return plan.model_copy(update={"plan_fingerprint": plan_fingerprint(plan)})


def _build_result(
    *,
    operation: Literal["apply", "restore"],
    plan: IpAssetMetadataRepairPlan,
    items: tuple[IpAssetMetadataRepairResultItem, ...],
    created_at: datetime,
) -> IpAssetMetadataRepairResult:
    return _finalize_result(
        operation=operation,
        plan_fingerprint_value=plan.plan_fingerprint,
        asset_set_fingerprint_value=plan.asset_set_fingerprint,
        items=items,
        created_at=created_at,
    )


def _build_result_from_apply(
    *,
    operation: Literal["restore"],
    applied: IpAssetMetadataRepairResult,
    items: tuple[IpAssetMetadataRepairResultItem, ...],
    created_at: datetime,
) -> IpAssetMetadataRepairResult:
    return _finalize_result(
        operation=operation,
        plan_fingerprint_value=applied.plan_fingerprint,
        asset_set_fingerprint_value=applied.asset_set_fingerprint,
        items=items,
        created_at=created_at,
    )


def _finalize_result(
    *,
    operation: Literal["apply", "restore"],
    plan_fingerprint_value: str,
    asset_set_fingerprint_value: str,
    items: tuple[IpAssetMetadataRepairResultItem, ...],
    created_at: datetime,
) -> IpAssetMetadataRepairResult:
    changed_status = (
        IpAssetMetadataMutationStatus.APPLIED
        if operation == "apply"
        else IpAssetMetadataMutationStatus.RESTORED
    )
    changed = sum(item.status is changed_status for item in items)
    already = sum(item.status is IpAssetMetadataMutationStatus.ALREADY_APPLIED for item in items)
    drift = sum(
        item.status
        in {
            IpAssetMetadataMutationStatus.CONTENT_DRIFT,
            IpAssetMetadataMutationStatus.METADATA_DRIFT,
            IpAssetMetadataMutationStatus.NOT_ELIGIBLE,
            IpAssetMetadataMutationStatus.NOT_FOUND,
        }
        for item in items
    )
    failed = sum(item.status is IpAssetMetadataMutationStatus.MUTATION_FAILED for item in items)
    result = IpAssetMetadataRepairResult(
        operation=operation,
        created_at=created_at,
        plan_fingerprint=plan_fingerprint_value,
        asset_set_fingerprint=asset_set_fingerprint_value,
        changed_count=changed,
        already_applied_count=already,
        drift_count=drift,
        failed_count=failed,
        skipped_count=len(items) - changed - already - drift - failed,
        items=items,
        result_fingerprint="0" * 64,
    )
    return result.model_copy(update={"result_fingerprint": result_fingerprint(result)})
