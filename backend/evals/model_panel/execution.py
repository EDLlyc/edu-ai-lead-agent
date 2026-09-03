"""One-shot model-panel execution with pre-send journal and conservative accounting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .budget import AtomicPanelBudget, BudgetReservation, PanelBudgetError
from .journal import AttemptJournal
from .models import (
    AttemptStatus,
    JudgeVote,
    PairwiseJudgeRequest,
    PanelAttempt,
    PanelFailureCode,
    PanelModelIdentity,
    ProviderUsage,
    canonicalize_arm_verdicts,
    canonicalize_choice,
)
from .parsing import (
    JudgeContentParseStage,
    JudgeContentProfile,
    ModelPanelParseError,
    parse_judge_output,
)
from .transport import JudgeMaterial, JudgeTransport, PanelTransportError, TransportCompletion


@dataclass(frozen=True, slots=True)
class OneShotExecution:
    transport: JudgeTransport
    budget: AtomicPanelBudget
    journal: AttemptJournal
    clock: Callable[[], datetime]
    monotonic: Callable[[], float]

    async def execute(
        self,
        *,
        identity: PanelModelIdentity,
        request: PairwiseJudgeRequest,
        material: JudgeMaterial,
    ) -> PanelAttempt:
        """Execute exactly one provider boundary; every post-start path is terminal or visible."""

        material.validate_against(request)
        started_at = self.clock()
        started = _attempt(
            identity_request=request,
            status=AttemptStatus.STARTED,
            started_at=started_at,
        )
        self.journal.append(started, recorded_at=started_at)
        reservation: BudgetReservation | None = None
        timer = self.monotonic()
        try:
            reservation = await self.budget.reserve(
                request=request,
                identity=identity,
            )
        except PanelBudgetError as exc:
            terminal = _attempt(
                identity_request=request,
                status=AttemptStatus.BUDGET_DENIED,
                started_at=started_at,
                finished_at=self.clock(),
                latency_ms=_elapsed_ms(timer, self.monotonic()),
                failure_code=_budget_failure(exc.code),
            )
            self.journal.append(terminal, recorded_at=terminal.finished_at or started_at)
            return terminal

        try:
            completion = await self.transport.complete(
                identity=identity,
                request=request,
                material=material,
            )
        except PanelTransportError as exc:
            await self._reconcile_unknown(reservation)
            status = AttemptStatus.RESULT_UNKNOWN if exc.outcome_unknown else AttemptStatus.FAILED
            failure = _transport_failure(exc.code)
            terminal = _attempt(
                identity_request=request,
                status=status,
                started_at=started_at,
                finished_at=self.clock(),
                latency_ms=_elapsed_ms(timer, self.monotonic()),
                usage=ProviderUsage(),
                failure_code=failure,
            )
            self.journal.append(terminal, recorded_at=terminal.finished_at or started_at)
            return terminal
        except Exception:
            await self._reconcile_unknown(reservation)
            terminal = _attempt(
                identity_request=request,
                status=AttemptStatus.RESULT_UNKNOWN,
                started_at=started_at,
                finished_at=self.clock(),
                latency_ms=_elapsed_ms(timer, self.monotonic()),
                usage=ProviderUsage(),
                failure_code=PanelFailureCode.ADAPTER_CRASH,
            )
            self.journal.append(terminal, recorded_at=terminal.finished_at or started_at)
            return terminal
        return await self._complete(
            identity=identity,
            request=request,
            completion=completion,
            reservation=reservation,
            started_at=started_at,
            timer=timer,
        )

    async def _complete(
        self,
        *,
        identity: PanelModelIdentity,
        request: PairwiseJudgeRequest,
        completion: TransportCompletion,
        reservation: BudgetReservation,
        started_at: datetime,
        timer: float,
    ) -> PanelAttempt:
        usage = ProviderUsage(
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            reasoning_tokens=completion.reasoning_tokens,
            native_cost=completion.native_cost,
        )
        if completion.returned_model != identity.requested_model:
            reconciliation_failure = await self._reconcile_failure(reservation, usage)
            if reconciliation_failure is not None:
                return self._record_terminal(
                    request=request,
                    status=AttemptStatus.RESULT_UNKNOWN,
                    started_at=started_at,
                    timer=timer,
                    usage=usage,
                    failure_code=reconciliation_failure,
                )
            return self._record_terminal(
                request=request,
                status=AttemptStatus.FAILED,
                started_at=started_at,
                timer=timer,
                usage=usage,
                failure_code=PanelFailureCode.PROVIDER_IDENTITY_MISMATCH,
            )
        returned_identity = identity
        if not usage.fully_known:
            reconciliation_failure = await self._reconcile_failure(reservation, usage)
            if reconciliation_failure is not None:
                return self._record_terminal(
                    request=request,
                    status=AttemptStatus.RESULT_UNKNOWN,
                    started_at=started_at,
                    timer=timer,
                    identity=returned_identity,
                    usage=usage,
                    failure_code=reconciliation_failure,
                )
            return self._record_terminal(
                request=request,
                status=AttemptStatus.RESULT_UNKNOWN,
                started_at=started_at,
                timer=timer,
                identity=returned_identity,
                usage=usage,
                failure_code=PanelFailureCode.USAGE_UNKNOWN,
            )
        try:
            parsed = parse_judge_output(
                completion.content,
                request=request,
                content_profile=completion.judge_content_profile,
            )
        except ModelPanelParseError as exc:
            reconciliation_failure = await self._reconcile_failure(reservation, usage)
            if reconciliation_failure is not None:
                return self._record_terminal(
                    request=request,
                    status=AttemptStatus.RESULT_UNKNOWN,
                    started_at=started_at,
                    timer=timer,
                    identity=returned_identity,
                    usage=usage,
                    failure_code=reconciliation_failure,
                )
            return self._record_terminal(
                request=request,
                status=AttemptStatus.FAILED,
                started_at=started_at,
                timer=timer,
                identity=returned_identity,
                usage=usage,
                failure_code=_judge_content_failure(
                    exc,
                    content_profile=completion.judge_content_profile,
                ),
            )
        reconciliation_failure = await self._reconcile_failure(reservation, usage)
        if reconciliation_failure is not None:
            return self._record_terminal(
                request=request,
                status=AttemptStatus.RESULT_UNKNOWN,
                started_at=started_at,
                timer=timer,
                identity=returned_identity,
                usage=usage,
                failure_code=reconciliation_failure,
            )
        canonical_first, canonical_second = canonicalize_arm_verdicts(
            parsed.presented_a_verdict,
            parsed.presented_b_verdict,
            request.presentation_order,
        )
        vote = JudgeVote(
            schema_version="model-panel-vote-v1",
            attempt_ref=request.attempt_ref,
            pair_ref=request.pair_ref,
            case_ref=request.case_ref,
            evaluator_model_ref=request.evaluator_model_ref,
            request_fingerprint=request.request_fingerprint,
            presentation_order=request.presentation_order,
            repeat_index=request.repeat_index,
            vote_profile=parsed.vote_profile,
            presented_choice=parsed.choice,
            canonical_choice=canonicalize_choice(parsed.choice, request.presentation_order),
            issue_codes=parsed.issue_codes,
            presented_a_verdict=parsed.presented_a_verdict,
            presented_b_verdict=parsed.presented_b_verdict,
            canonical_first_verdict=canonical_first,
            canonical_second_verdict=canonical_second,
            confidence=parsed.confidence,
        )
        return self._record_terminal(
            request=request,
            status=AttemptStatus.COMPLETED,
            started_at=started_at,
            timer=timer,
            identity=returned_identity,
            usage=usage,
            vote=vote,
        )

    async def _reconcile_unknown(self, reservation: BudgetReservation) -> None:
        try:
            await self.budget.reconcile(reservation, usage=ProviderUsage())
        except PanelBudgetError:
            return

    async def _reconcile_failure(
        self,
        reservation: BudgetReservation,
        usage: ProviderUsage,
    ) -> PanelFailureCode | None:
        try:
            await self.budget.reconcile(reservation, usage=usage)
        except PanelBudgetError as exc:
            if exc.code in {
                "native_cost_unit_mismatch",
                "provider_usage_exceeded_reservation",
            }:
                return PanelFailureCode.PROVIDER_USAGE_INVALID
            return PanelFailureCode.BUDGET_EXHAUSTED
        return None

    def _record_terminal(
        self,
        *,
        request: PairwiseJudgeRequest,
        status: AttemptStatus,
        started_at: datetime,
        timer: float,
        identity: PanelModelIdentity | None = None,
        usage: ProviderUsage | None = None,
        vote: JudgeVote | None = None,
        failure_code: PanelFailureCode | None = None,
    ) -> PanelAttempt:
        finished_at = self.clock()
        terminal = _attempt(
            identity_request=request,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            identity=identity,
            usage=usage,
            latency_ms=_elapsed_ms(timer, self.monotonic()),
            vote=vote,
            failure_code=failure_code,
        )
        self.journal.append(terminal, recorded_at=finished_at)
        return terminal


def _attempt(
    *,
    identity_request: PairwiseJudgeRequest,
    status: AttemptStatus,
    started_at: datetime,
    finished_at: datetime | None = None,
    identity: PanelModelIdentity | None = None,
    usage: ProviderUsage | None = None,
    latency_ms: int | None = None,
    vote: JudgeVote | None = None,
    failure_code: PanelFailureCode | None = None,
) -> PanelAttempt:
    return PanelAttempt(
        schema_version="model-panel-attempt-v1",
        run_ref=identity_request.run_ref,
        manifest_sha256=identity_request.manifest_sha256,
        authorization_sha256=identity_request.authorization_sha256,
        attempt_ref=identity_request.attempt_ref,
        pair_ref=identity_request.pair_ref,
        case_ref=identity_request.case_ref,
        evaluator_model_ref=identity_request.evaluator_model_ref,
        presentation_order=identity_request.presentation_order,
        repeat_index=identity_request.repeat_index,
        request_fingerprint=identity_request.request_fingerprint,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        identity=identity,
        usage=usage,
        latency_ms=latency_ms,
        vote=vote,
        failure_code=failure_code,
    )


def _transport_failure(code: str) -> PanelFailureCode:
    return {
        "provider_timeout": PanelFailureCode.PROVIDER_TIMEOUT,
        "provider_connection_failed": PanelFailureCode.PROVIDER_CONNECTION_FAILED,
        "provider_rejected": PanelFailureCode.PROVIDER_REJECTED,
        "provider_envelope_invalid": PanelFailureCode.PROVIDER_ENVELOPE_INVALID,
        "invalid_provider_output": PanelFailureCode.INVALID_PROVIDER_OUTPUT,
        "provider_request_too_large": PanelFailureCode.INVALID_PROVIDER_OUTPUT,
        "provider_identity_mismatch": PanelFailureCode.PROVIDER_IDENTITY_MISMATCH,
    }.get(code, PanelFailureCode.PROVIDER_RESULT_UNKNOWN)


def _judge_content_failure(
    error: ModelPanelParseError,
    *,
    content_profile: JudgeContentProfile,
) -> PanelFailureCode:
    # Keep the shared Reviewer/default JSON path's historical evidence behavior unchanged.
    if content_profile is not JudgeContentProfile.ZHIPU_VISION or error.stage is None:
        return PanelFailureCode.JUDGE_CONTENT_INVALID
    return {
        JudgeContentParseStage.FRAMING: PanelFailureCode.JUDGE_CONTENT_FRAMING_INVALID,
        JudgeContentParseStage.SCHEMA: PanelFailureCode.JUDGE_CONTENT_SCHEMA_INVALID,
        JudgeContentParseStage.POLICY: PanelFailureCode.JUDGE_CONTENT_POLICY_INVALID,
    }.get(error.stage, PanelFailureCode.JUDGE_CONTENT_INVALID)


def _budget_failure(code: str) -> PanelFailureCode:
    if code == "authorization_expired":
        return PanelFailureCode.AUTHORIZATION_EXPIRED
    if code.startswith("authorization_") or code in {
        "manifest_window_closed",
        "request_authorization_mismatch",
        "request_manifest_binding_mismatch",
        "model_identity_not_declared",
    }:
        return PanelFailureCode.AUTHORIZATION_INVALID
    return PanelFailureCode.BUDGET_EXHAUSTED


def _elapsed_ms(started: float, finished: float) -> int:
    return max(0, min(1_800_000, round((finished - started) * 1_000)))
