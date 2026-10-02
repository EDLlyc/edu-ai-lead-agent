# ruff: noqa: RUF001
"""Approved ops actions: propose, approve (or reject), execute only when enabled, verify."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest
from app.application.services.ops_actions import (
    ActionLog,
    ActionProposal,
    ActionRefused,
    ActionTarget,
    FailedDelivery,
    approve,
    propose_resends,
    reject,
    slot_window_end,
    verify,
)
from app.application.services.ops_diagnosis import DiagnosisOutcome, DiagnosisReport
from app.application.services.ops_tools import DeliveriesResult, DeliveryItem
from app.core.errors import ConflictError
from app.delivery_watchdog_main import SlotCheck, alert_text, propose_actions
from app.ops_actions_main import main as cli

DAY = date(2026, 10, 2)
# 18:42 local, 12 minutes after the evening target; the window closes at 19:30 local.
NOW = datetime(2026, 10, 2, 10, 42, tzinfo=UTC)
TIMES = {"morning": time(7, 30), "noon": time(12, 30), "evening": time(18, 30)}


def _window_end(target: ActionTarget) -> datetime:
    return slot_window_end(target, target_times=TIMES, late_minutes=60, timezone="Asia/Shanghai")


def _failed(ordinal: int, status: str = "failed", slot: str = "evening") -> FailedDelivery:
    return FailedDelivery(slot, ordinal, status, "wecom_rate_limited")


def _propose(log: ActionLog, *items: FailedDelivery, now: datetime = NOW) -> list[ActionProposal]:
    return propose_resends(
        log,
        business_date=DAY,
        slot="evening",
        deliveries=items,
        reason="限流失败",
        proposed_by="ops-diagnosis-v2-slot-scope",
        now=now,
        window_end=_window_end,
    )


class Executor:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[ActionTarget] = []
        self.error = error

    async def __call__(self, proposal: ActionProposal) -> dict[str, Any]:
        self.calls.append(proposal.target)
        if self.error is not None:
            raise self.error
        return {"delivery_status": "queued", "job": "0e0a0000"}


def test_proposals_cover_only_open_failed_deliveries_of_the_slot_once(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "actions.jsonl")

    created = _propose(
        log,
        _failed(2),
        _failed(3, status="delivered"),
        _failed(1, slot="noon"),
        _failed(1, status="delivery_unknown"),
    )
    again = _propose(log, _failed(2))
    late = _propose(log, _failed(1, status="partial"), now=NOW + timedelta(hours=1))

    assert [p.target.sequence_ordinal for p in created] == [2, 1]
    assert again == [] and late == []
    assert created[0].expires_at == datetime(2026, 10, 2, 11, 30, tzinfo=UTC)
    assert set(log.proposals()) == {p.id for p in created}


@pytest.mark.asyncio
async def test_propose_only_records_the_approval_and_runs_nothing(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "actions.jsonl")
    (proposal,) = _propose(log, _failed(2))
    executor = Executor()

    status = await approve(log, proposal.id, by="李昱辰", now=NOW, enabled=False, execute=executor)

    assert status == "approved" and executor.calls == []
    assert log.proposals()[proposal.id].status == "approved"
    with pytest.raises(ActionRefused) as again:
        await approve(log, proposal.id, by="李昱辰", now=NOW, enabled=True, execute=executor)
    assert again.value.code == "not_open"


@pytest.mark.asyncio
async def test_enabled_approval_executes_once_and_records_the_result(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "actions.jsonl")
    (proposal,) = _propose(log, _failed(2))
    executor = Executor()

    status = await approve(log, proposal.id, by="运营", now=NOW, enabled=True, execute=executor)

    assert status == "executed"
    assert executor.calls == [proposal.target]
    history = log.proposals()[proposal.id].history
    assert [step["event"] for step in history] == ["approved", "executed"]
    assert history[0]["by"] == "运营" and history[1]["result"]["delivery_status"] == "queued"


@pytest.mark.asyncio
async def test_the_executor_guard_refusing_is_recorded_as_a_failed_execution(
    tmp_path: Path,
) -> None:
    log = ActionLog(tmp_path / "actions.jsonl")
    (proposal,) = _propose(log, _failed(2))
    executor = Executor(ConflictError("only failed or unknown WeCom deliveries can be retried"))

    status = await approve(log, proposal.id, by="运营", now=NOW, enabled=True, execute=executor)

    assert status == "execution_failed"
    assert log.proposals()[proposal.id].history[-1]["error"] == "ConflictError"


@pytest.mark.asyncio
async def test_expired_rejected_and_anonymous_approvals_are_refused(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "actions.jsonl")
    first, second = _propose(log, _failed(1), _failed(2))
    executor = Executor()

    with pytest.raises(ActionRefused) as anonymous:
        await approve(log, first.id, by=" ", now=NOW, enabled=True, execute=executor)
    with pytest.raises(ActionRefused) as expired:
        await approve(
            log, first.id, by="运营", now=NOW + timedelta(hours=1), enabled=True, execute=executor
        )
    reject(log, second.id, by="运营", now=NOW, note="已手动补发")
    with pytest.raises(ActionRefused) as rejected:
        await approve(log, second.id, by="运营", now=NOW, enabled=True, execute=executor)

    assert (anonymous.value.code, expired.value.code, rejected.value.code) == (
        "approver_required",
        "expired",
        "not_open",
    )
    assert log.proposals()[first.id].status == "expired"
    assert log.proposals()[second.id].status == "rejected"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_at_most_three_executions_per_day(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "actions.jsonl")
    proposals = _propose(log, *(_failed(n) for n in range(1, 5)))
    executor = Executor()

    statuses = [
        await approve(log, p.id, by="运营", now=NOW, enabled=True, execute=executor)
        for p in proposals
    ]

    assert statuses == ["executed", "executed", "executed", "execution_failed"]
    assert log.proposals()[proposals[3].id].history[-1]["error"] == "daily_cap"
    assert len(executor.calls) == 3


@pytest.mark.asyncio
async def test_verify_checks_executed_actions_after_a_while(tmp_path: Path) -> None:
    log = ActionLog(tmp_path / "actions.jsonl")
    done, failing = _propose(log, _failed(1), _failed(2))
    for proposal in (done, failing):
        await approve(log, proposal.id, by="运营", now=NOW, enabled=True, execute=Executor())

    async def status(target: ActionTarget) -> str | None:
        return "delivered" if target.sequence_ordinal == 1 else "failed"

    early = await verify(
        log, now=NOW + timedelta(minutes=5), read_status=status, min_age=timedelta(minutes=10)
    )
    later = await verify(
        log, now=NOW + timedelta(minutes=15), read_status=status, min_age=timedelta(minutes=10)
    )

    assert early == []
    assert sorted(later) == sorted([(done.id, "verified"), (failing.id, "still_failing")])


def _diagnosis(action: str) -> DiagnosisOutcome:
    report = DiagnosisReport(
        stage="delivery", cause="第 2 条企业微信限流，重试 3 次仍失败。", action=action
    )
    return DiagnosisOutcome(report=report, stopped="reported")


def test_the_watchdog_proposes_only_for_a_suggested_resend(tmp_path: Path) -> None:
    check = SlotCheck(DAY, "evening", problems=["已送达 2/3：第 2 条 failed（wecom_rate_limited）"])
    deliveries = DeliveriesResult(
        deliveries=(
            DeliveryItem(
                content_slot="evening",
                sequence_ordinal=2,
                status="failed",
                text_status="failed",
                image_status="failed",
                attempt_count=3,
                last_error_code="wecom_rate_limited",
                not_before=None,
                completed_at=None,
            ),
        )
    )
    log = ActionLog(tmp_path / "actions.jsonl")

    none = propose_actions(
        check, _diagnosis("manual_review"), deliveries, log, now=NOW, window_end=_window_end
    )
    proposals = propose_actions(
        check, _diagnosis("rerun_delivery"), deliveries, log, now=NOW, window_end=_window_end
    )

    assert none == [] and len(proposals) == 1
    text = alert_text(check, _diagnosis("rerun_delivery"), proposals)
    assert "【待批准动作】" in text and f"#{proposals[0].id}" in text
    assert "sudo edu-ai-ops-action approve" in text


def test_the_command_line_lists_rejects_and_approves_without_executing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPS_ACTIONS_ENABLED", raising=False)
    path = tmp_path / "actions.jsonl"
    log = ActionLog(path)
    now = datetime.now(UTC)
    first, second = propose_resends(
        log,
        business_date=DAY,
        slot="evening",
        deliveries=(_failed(1), _failed(2)),
        reason="限流失败",
        proposed_by="ops-diagnosis-v2-slot-scope",
        now=now,
        window_end=lambda _target: now + timedelta(hours=1),
    )

    assert cli(["--log", str(path), "list"]) == 0
    assert cli(["--log", str(path), "approve", first.id, "--by", "运营"]) == 0
    assert cli(["--log", str(path), "reject", second.id, "--by", "运营"]) == 0
    assert cli(["--log", str(path), "approve", second.id, "--by", "运营"]) == 2

    output = capsys.readouterr().out
    assert "执行开关：关" in output and f"#{first.id} → approved" in output
    assert log.proposals()[first.id].status == "approved"
