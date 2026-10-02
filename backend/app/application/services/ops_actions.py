"""Approved ops actions: the diagnosis agent proposes, an operator approves, the app executes.

The read-only diagnosis agent can only suggest. When it suggests a resend, the watchdog turns the
slot's failed deliveries into action proposals (deterministically, from the delivery rows, not from
ids the model wrote). An operator approves one on the server's command line; only then does the
application (its own database role, never the agent's) call the existing delivery retry, which
re-checks the job's state and window itself. Every step is an append-only event:

    proposed -> approved -> executed | execution_failed | expired -> verified | still_failing
    proposed -> rejected | expired
    approved (actions disabled) -> stays approved, nothing runs

Guards: a white list of actions (only `retry_delivery` for now); one proposal per target; at most
`MAX_EXECUTIONS_PER_DAY` executions per action and day; a proposal expires with the slot's
delivery window; `OPS_ACTIONS_ENABLED` (off by default) must be on for anything to execute.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import fcntl
import json
import secrets
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

ActionName = Literal["retry_delivery"]
ACTIONS: frozenset[str] = frozenset({"retry_delivery"})
RETRYABLE_DELIVERY_STATUSES = frozenset({"failed", "partial", "delivery_unknown"})
MAX_EXECUTIONS_PER_DAY = 3
SLOT_LABELS = {"morning": "早间", "noon": "午间", "evening": "晚间"}
BUSINESS_TZ = ZoneInfo("Asia/Shanghai")

Status = Literal[
    "proposed",
    "rejected",
    "approved",
    "executed",
    "execution_failed",
    "expired",
    "verified",
    "still_failing",
]
EventName = Literal[
    "proposed",
    "rejected",
    "approved",
    "executed",
    "execution_failed",
    "expired",
    "verified",
    "still_failing",
]


class ActionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    business_date: date
    content_slot: Literal["morning", "noon", "evening"]
    sequence_ordinal: int = Field(ge=1, le=12)


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action: ActionName
    target: ActionTarget
    reason: str = Field(max_length=200)
    proposed_by: str
    proposed_at: datetime
    expires_at: datetime
    status: Status = "proposed"
    history: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def key(self) -> str:
        t = self.target
        return f"{self.action}:{t.business_date.isoformat()}:{t.content_slot}:{t.sequence_ordinal}"

    def describe(self) -> str:
        t = self.target
        return (
            f"#{self.id} 重新发送 {t.business_date.isoformat()} "
            f"{SLOT_LABELS[t.content_slot]}第 {t.sequence_ordinal} 条"
        )


class ActionLog:
    """Append-only JSON-lines event log; the current state is a fold over the events."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def proposals(self) -> dict[str, ActionProposal]:
        state: dict[str, ActionProposal] = {}
        if not self.path.exists():
            return state
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            name = event["event"]
            if name == "proposed":
                created = ActionProposal.model_validate(event["proposal"])
                state[created.id] = created
                continue
            current = state.get(event["id"])
            if current is None:
                continue
            current.status = name
            current.history.append({k: v for k, v in event.items() if k not in {"id"}})
        return state


def slot_window_end(
    target: ActionTarget, *, target_times: dict[str, time], late_minutes: int, timezone: str
) -> datetime:
    local = datetime.combine(
        target.business_date, target_times[target.content_slot], tzinfo=ZoneInfo(timezone)
    )
    return (local + timedelta(minutes=late_minutes)).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class FailedDelivery:
    content_slot: str
    sequence_ordinal: int
    status: str
    last_error_code: str | None


def propose_resends(
    log: ActionLog,
    *,
    business_date: date,
    slot: str,
    deliveries: Iterable[FailedDelivery],
    reason: str,
    proposed_by: str,
    now: datetime,
    window_end: Callable[[ActionTarget], datetime],
) -> list[ActionProposal]:
    """One proposal per failed delivery of the slot that has no proposal yet and is still open."""

    existing = {proposal.key for proposal in log.proposals().values()}
    created: list[ActionProposal] = []
    for item in deliveries:
        if item.content_slot != slot or item.status not in RETRYABLE_DELIVERY_STATUSES:
            continue
        target = ActionTarget(
            business_date=business_date,
            content_slot=slot,
            sequence_ordinal=item.sequence_ordinal,
        )
        expires_at = window_end(target)
        if now >= expires_at:
            continue
        proposal = ActionProposal(
            id=secrets.token_hex(4),
            action="retry_delivery",
            target=target,
            reason=reason[:200],
            proposed_by=proposed_by,
            proposed_at=now,
            expires_at=expires_at,
        )
        if proposal.key in existing:
            continue
        existing.add(proposal.key)
        log.append({"event": "proposed", "at": now, "proposal": proposal.model_dump(mode="json")})
        created.append(proposal)
    return created


class ActionRefused(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# Executes the white-listed action for a target and returns a short, safe result.
Executor = Callable[[ActionProposal], Awaitable[dict[str, Any]]]


def _local_day(value: object) -> date | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(BUSINESS_TZ).date()


def _executions_today(proposals: Sequence[ActionProposal], action: str, day: date) -> int:
    return sum(
        1
        for proposal in proposals
        if proposal.action == action
        and any(
            step.get("event") in {"executed", "execution_failed"}
            and step.get("error") != "daily_cap"
            and _local_day(step.get("at")) == day
            for step in proposal.history
        )
    )


def reject(log: ActionLog, proposal_id: str, *, by: str, now: datetime, note: str = "") -> None:
    proposal = log.proposals().get(proposal_id)
    if proposal is None:
        raise ActionRefused("not_found", f"没有编号为 {proposal_id} 的提案")
    if proposal.status != "proposed":
        raise ActionRefused("not_open", f"提案状态是 {proposal.status}，不能拒绝")
    log.append({"event": "rejected", "id": proposal_id, "by": by, "at": now, "note": note[:200]})


async def approve(
    log: ActionLog,
    proposal_id: str,
    *,
    by: str,
    now: datetime,
    enabled: bool,
    execute: Executor,
) -> str:
    """Record the approval, then execute when actions are enabled. Returns the final status."""

    if not by.strip():
        raise ActionRefused("approver_required", "需要写明批准人")
    proposals = log.proposals()
    proposal = proposals.get(proposal_id)
    if proposal is None:
        raise ActionRefused("not_found", f"没有编号为 {proposal_id} 的提案")
    if proposal.action not in ACTIONS:
        raise ActionRefused("action_not_allowed", f"不支持的动作 {proposal.action}")
    if proposal.status != "proposed":
        raise ActionRefused("not_open", f"提案状态是 {proposal.status}，不能再批准")
    if now >= proposal.expires_at:
        log.append({"event": "expired", "id": proposal_id, "at": now})
        raise ActionRefused("expired", "发送窗口已过，提案作废")
    log.append({"event": "approved", "id": proposal_id, "by": by, "at": now})
    if not enabled:
        return "approved"  # propose-only: the approval is recorded, nothing runs
    local_day = now.astimezone(BUSINESS_TZ).date()
    if _executions_today(list(proposals.values()), proposal.action, local_day) >= (
        MAX_EXECUTIONS_PER_DAY
    ):
        log.append(
            {"event": "execution_failed", "id": proposal_id, "at": now, "error": "daily_cap"}
        )
        return "execution_failed"
    try:
        result = await execute(proposal)
    except ActionRefused as refused:
        log.append(
            {"event": "execution_failed", "id": proposal_id, "at": now, "error": refused.code}
        )
        return "execution_failed"
    except Exception as error:  # the executor's own guards (state, window) refuse here
        log.append(
            {
                "event": "execution_failed",
                "id": proposal_id,
                "at": now,
                "error": type(error).__name__,
            }
        )
        return "execution_failed"
    log.append({"event": "executed", "id": proposal_id, "at": now, "result": result})
    return "executed"


# Returns the target's current delivery status, or None when the target cannot be found.
StatusReader = Callable[[ActionTarget], Awaitable[str | None]]


async def verify(
    log: ActionLog, *, now: datetime, read_status: StatusReader, min_age: timedelta
) -> list[tuple[str, str]]:
    """Check executed proposals at least `min_age` old: verified when delivered."""

    outcomes: list[tuple[str, str]] = []
    for proposal in log.proposals().values():
        if proposal.status != "executed":
            continue
        executed_at = next(
            (
                datetime.fromisoformat(str(step["at"]))
                for step in reversed(proposal.history)
                if step.get("event") == "executed"
            ),
            None,
        )
        if executed_at is None or now - executed_at < min_age:
            continue
        status = await read_status(proposal.target)
        event = "verified" if status == "delivered" else "still_failing"
        log.append({"event": event, "id": proposal.id, "at": now, "delivery_status": status})
        outcomes.append((proposal.id, event))
    return outcomes


def proposal_lines(proposals: Sequence[ActionProposal]) -> list[str]:
    return [
        f"{proposal.describe()}（原因：{proposal.reason}；"
        f"截止 {proposal.expires_at.astimezone(BUSINESS_TZ):%H:%M}）"
        for proposal in proposals
    ]
