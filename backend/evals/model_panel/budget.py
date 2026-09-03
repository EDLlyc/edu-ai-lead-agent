"""Atomic in-process budgets bound to a frozen panel manifest and authorization."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from .models import (
    AttemptBinding,
    ModelBudgetUsage,
    PairwiseJudgeRequest,
    PanelAuthorization,
    PanelBudgetSnapshot,
    PanelManifest,
    PanelModelIdentity,
    ProviderBudgetUsage,
    ProviderUsage,
    require_aware,
)


class PanelBudgetError(RuntimeError):
    """A stable budget or authorization denial without provider-controlled text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    attempt_ref: str
    model_ref: str
    provider_ref: str
    native_unit: str
    maximum_native_cost: Decimal
    maximum_input_tokens: int
    maximum_output_tokens: int


@dataclass(slots=True)
class _ModelState:
    request_limit: int
    input_limit: int
    output_limit: int
    requests_used: int = 0
    requests_reserved: int = 0
    input_used: int = 0
    input_reserved: int = 0
    output_used: int = 0
    output_reserved: int = 0
    unknown_usage_count: int = 0


@dataclass(slots=True)
class _ProviderState:
    unit: str
    maximum: Decimal
    spent: Decimal = Decimal("0")
    reserved: Decimal = Decimal("0")
    unknown_cost_count: int = 0


@dataclass(slots=True)
class _ReservationState:
    reservation: BudgetReservation
    reconciled_signature: tuple[int | None, int | None, int | None, str | None] | None = None


def validate_authorization_binding(
    manifest: PanelManifest,
    authorization: PanelAuthorization,
    *,
    now: datetime,
) -> None:
    """Require authorization to be an exact, time-bounded projection of the manifest."""

    moment = require_aware(now, label="authorization check time")
    manifest_start = require_aware(
        manifest.execution_window_start,
        label="manifest execution start",
    )
    manifest_end = require_aware(manifest.execution_window_end, label="manifest execution end")
    authorization_start = require_aware(authorization.valid_from, label="authorization start")
    authorization_end = require_aware(authorization.valid_until, label="authorization end")
    if authorization.manifest_sha256 != manifest.manifest_sha256:
        raise PanelBudgetError("authorization_manifest_mismatch")
    if (
        authorization.total_request_limit != manifest.total_request_limit
        or authorization.model_request_limits != manifest.model_request_limits
        or authorization.provider_native_limits != manifest.provider_native_limits
    ):
        raise PanelBudgetError("authorization_budget_mismatch")
    if authorization_start < manifest_start or authorization_end > manifest_end:
        raise PanelBudgetError("authorization_window_mismatch")
    if not (manifest_start <= moment < manifest_end):
        raise PanelBudgetError("manifest_window_closed")
    if not (authorization_start <= moment < authorization_end):
        raise PanelBudgetError("authorization_expired")


class AtomicPanelBudget:
    """Reserve worst-case vectors before each one-shot call and reconcile exactly once."""

    def __init__(
        self,
        *,
        manifest: PanelManifest,
        authorization: PanelAuthorization,
        clock: Callable[[], datetime],
    ) -> None:
        validate_authorization_binding(manifest, authorization, now=clock())
        self._manifest = manifest
        self._authorization = authorization
        self._clock = clock
        self._lock = asyncio.Lock()
        self._total_limit = authorization.total_request_limit
        self._total_used = 0
        self._total_reserved = 0
        self._models = {
            limit.model_ref: _ModelState(
                request_limit=limit.request_limit,
                input_limit=limit.input_token_limit,
                output_limit=limit.output_token_limit,
            )
            for limit in authorization.model_request_limits
        }
        self._providers = {
            limit.provider_ref: _ProviderState(unit=limit.unit, maximum=limit.maximum)
            for limit in authorization.provider_native_limits
        }
        self._identities = {item.identity_ref: item for item in manifest.identities}
        self._bindings = {item.attempt_ref: item for item in manifest.attempt_bindings}
        self._reservations: dict[str, _ReservationState] = {}

    async def reserve(
        self,
        *,
        request: PairwiseJudgeRequest,
        identity: PanelModelIdentity,
    ) -> BudgetReservation:
        async with self._lock:
            self._require_open_window()
            self._validate_request_binding(request, identity)
            if request.attempt_ref in self._reservations:
                raise PanelBudgetError("attempt_already_reserved")
            model = self._models[identity.identity_ref]
            provider = self._providers[identity.provider]
            if self._total_used + self._total_reserved + 1 > self._total_limit:
                raise PanelBudgetError("total_request_budget_exhausted")
            if model.requests_used + model.requests_reserved + 1 > model.request_limit:
                raise PanelBudgetError("model_request_budget_exhausted")
            if (
                model.input_used + model.input_reserved + request.max_input_tokens
                > model.input_limit
            ):
                raise PanelBudgetError("input_token_budget_exhausted")
            if (
                model.output_used + model.output_reserved + request.max_output_tokens
                > model.output_limit
            ):
                raise PanelBudgetError("output_token_budget_exhausted")
            if request.native_cost_unit != provider.unit:
                raise PanelBudgetError("native_cost_unit_mismatch")
            if provider.spent + provider.reserved + request.maximum_native_cost > provider.maximum:
                raise PanelBudgetError("native_cost_budget_exhausted")
            reservation = BudgetReservation(
                attempt_ref=request.attempt_ref,
                model_ref=identity.identity_ref,
                provider_ref=identity.provider,
                native_unit=provider.unit,
                maximum_native_cost=request.maximum_native_cost,
                maximum_input_tokens=request.max_input_tokens,
                maximum_output_tokens=request.max_output_tokens,
            )
            self._total_reserved += 1
            model.requests_reserved += 1
            model.input_reserved += request.max_input_tokens
            model.output_reserved += request.max_output_tokens
            provider.reserved += request.maximum_native_cost
            self._reservations[request.attempt_ref] = _ReservationState(reservation)
            return reservation

    async def release_before_start(self, reservation: BudgetReservation) -> None:
        """Release a reservation only when no started event/provider call was made."""

        async with self._lock:
            state = self._require_reservation(reservation)
            if state.reconciled_signature is not None:
                raise PanelBudgetError("reservation_already_reconciled")
            self._release_reserved_vector(reservation)
            del self._reservations[reservation.attempt_ref]

    async def reconcile(
        self,
        reservation: BudgetReservation,
        *,
        usage: ProviderUsage,
    ) -> PanelBudgetSnapshot:
        signature = (
            usage.input_tokens,
            usage.output_tokens,
            usage.reasoning_tokens,
            None
            if usage.native_cost is None
            else f"{usage.native_cost.unit}:{usage.native_cost.amount}",
        )
        async with self._lock:
            state = self._require_reservation(reservation)
            if state.reconciled_signature is not None:
                if state.reconciled_signature != signature:
                    raise PanelBudgetError("reservation_reconciliation_conflict")
                return self._snapshot_unlocked()
            model = self._models[reservation.model_ref]
            provider = self._providers[reservation.provider_ref]
            input_used = (
                reservation.maximum_input_tokens
                if usage.input_tokens is None
                else usage.input_tokens
            )
            output_used = (
                reservation.maximum_output_tokens
                if usage.output_tokens is None
                else usage.output_tokens
            )
            native_used = (
                reservation.maximum_native_cost
                if usage.native_cost is None
                else usage.native_cost.amount
            )
            unit_mismatch = (
                usage.native_cost is not None and usage.native_cost.unit != reservation.native_unit
            )
            if unit_mismatch:
                native_used = reservation.maximum_native_cost
            exceeded = (
                input_used > reservation.maximum_input_tokens
                or output_used > reservation.maximum_output_tokens
                or native_used > reservation.maximum_native_cost
                or unit_mismatch
            )
            self._release_reserved_vector(reservation)
            self._total_used += 1
            model.requests_used += 1
            if exceeded:
                model.input_used += reservation.maximum_input_tokens
                model.output_used += reservation.maximum_output_tokens
                model.unknown_usage_count += 1
                provider.spent += reservation.maximum_native_cost
                provider.unknown_cost_count += 1
                state.reconciled_signature = signature
                code = (
                    "native_cost_unit_mismatch"
                    if unit_mismatch
                    else "provider_usage_exceeded_reservation"
                )
                raise PanelBudgetError(code)
            model.input_used += input_used
            model.output_used += output_used
            provider.spent += native_used
            if usage.input_tokens is None or usage.output_tokens is None:
                model.unknown_usage_count += 1
            if usage.native_cost is None:
                provider.unknown_cost_count += 1
            state.reconciled_signature = signature
            return self._snapshot_unlocked()

    async def snapshot(self) -> PanelBudgetSnapshot:
        async with self._lock:
            return self._snapshot_unlocked()

    def _validate_request_binding(
        self,
        request: PairwiseJudgeRequest,
        identity: PanelModelIdentity,
    ) -> None:
        if (
            request.manifest_sha256 != self._manifest.manifest_sha256
            or request.authorization_sha256 != self._authorization.authorization_sha256
        ):
            raise PanelBudgetError("request_authorization_mismatch")
        if self._identities.get(identity.identity_ref) != identity:
            raise PanelBudgetError("model_identity_not_declared")
        expected = self._bindings.get(request.attempt_ref)
        actual = AttemptBinding(
            attempt_ref=request.attempt_ref,
            pair_ref=request.pair_ref,
            case_ref=request.case_ref,
            evaluator_model_ref=request.evaluator_model_ref,
            target_model_ref=request.target_model_ref,
            presentation_order=request.presentation_order,
            repeat_index=request.repeat_index,
            max_input_tokens=request.max_input_tokens,
            max_output_tokens=request.max_output_tokens,
            native_cost_unit=request.native_cost_unit,
            maximum_native_cost=request.maximum_native_cost,
            request_fingerprint=request.request_fingerprint,
        )
        if expected != actual or identity.identity_ref != request.evaluator_model_ref:
            raise PanelBudgetError("request_manifest_binding_mismatch")

    def _require_open_window(self) -> None:
        validate_authorization_binding(
            self._manifest,
            self._authorization,
            now=self._clock(),
        )

    def _require_reservation(self, reservation: BudgetReservation) -> _ReservationState:
        state = self._reservations.get(reservation.attempt_ref)
        if state is None or state.reservation != reservation:
            raise PanelBudgetError("reservation_unknown")
        return state

    def _release_reserved_vector(self, reservation: BudgetReservation) -> None:
        model = self._models[reservation.model_ref]
        provider = self._providers[reservation.provider_ref]
        self._total_reserved -= 1
        model.requests_reserved -= 1
        model.input_reserved -= reservation.maximum_input_tokens
        model.output_reserved -= reservation.maximum_output_tokens
        provider.reserved -= reservation.maximum_native_cost

    def _snapshot_unlocked(self) -> PanelBudgetSnapshot:
        return PanelBudgetSnapshot(
            total_request_limit=self._total_limit,
            total_requests_used=self._total_used,
            total_requests_reserved=self._total_reserved,
            model_usage=tuple(
                ModelBudgetUsage(
                    model_ref=model_ref,
                    request_limit=state.request_limit,
                    requests_used=state.requests_used,
                    requests_reserved=state.requests_reserved,
                    input_token_limit=state.input_limit,
                    input_tokens_used=state.input_used,
                    input_tokens_reserved=state.input_reserved,
                    output_token_limit=state.output_limit,
                    output_tokens_used=state.output_used,
                    output_tokens_reserved=state.output_reserved,
                    unknown_usage_count=state.unknown_usage_count,
                )
                for model_ref, state in sorted(self._models.items())
            ),
            provider_usage=tuple(
                ProviderBudgetUsage(
                    provider_ref=provider_ref,
                    unit=state.unit,
                    maximum=state.maximum,
                    spent=state.spent,
                    reserved=state.reserved,
                    unknown_cost_count=state.unknown_cost_count,
                )
                for provider_ref, state in sorted(self._providers.items())
            ),
            observed_at=require_aware(
                self._clock(),
                label="budget snapshot time",
            ).astimezone(UTC),
        )
