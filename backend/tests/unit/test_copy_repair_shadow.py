# ruff: noqa: RUF001

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from app.application.ports.copy_generation import DraftAuditRequest, DraftAuditResult
from app.application.services.copy_repair_agent import ChatTurn
from app.copy_repair_shadow_main import (
    CallCap,
    CallCapReachedError,
    shadow_case,
    summarize,
)
from app.domain.copy_generation import CopyVersionBundle
from app.infrastructure.db.copy_repair_workspace import BlockedCase, ProductionRepair
from app.schemas.copy_generation import AuditVerdict, CopyIssue
from tests.unit.test_copy_repair_tools import EVIDENCE_A, _call, _workspace

BUNDLE = CopyVersionBundle(
    pipeline_version="copy-pipeline-v1",
    generator_prompt_version="moments-generator-v28-shared-quotes",
    draft_schema_version="material-draft-v1",
    auditor_prompt_version="moments-auditor-v21-lean-context",
    audit_schema_version="audit-verdict-v1",
    rule_version="preview-v13-headline-hook",
    provider="zhipu",
    model="glm-test",
)


class _Scripted:
    def __init__(self, turns: list[ChatTurn]) -> None:
        self.turns = turns

    async def complete(self, messages, tools):  # type: ignore[no-untyped-def]
        return self.turns.pop(0)


class _Auditor:
    def __init__(self) -> None:
        self.requests: list[DraftAuditRequest] = []

    async def audit(self, request: DraftAuditRequest) -> DraftAuditResult:
        self.requests.append(request)
        return DraftAuditResult(
            verdict=AuditVerdict(accepted=True),
            provider="zhipu",
            model="glm-test",
            request_fingerprint="f" * 64,
            provider_request_id=None,
            prompt_tokens=900,
            completion_tokens=30,
            reasoning_tokens=0,
            latency_ms=10,
        )


def _case() -> BlockedCase:
    return BlockedCase(
        run_id=uuid4(),
        business_date=date(2026, 9, 30),
        content_slot="evening",
        ordinal=2,
        version_bundle=BUNDLE,
        workspace=_workspace(claim_text="该模型在五项测试中表现领先。"),
        blocking_issues=(
            CopyIssue(code="evidence_mismatch", message="数字与原文不符", claim_id="fact-1"),
        ),
        production=ProductionRepair(regenerated=True, passed=False, run_status="review_required"),
    )


def _repair_turns() -> list[ChatTurn]:
    return [
        ChatTurn(
            None,
            (
                _call(
                    "1",
                    "replace_claim",
                    {
                        "claim_id": "fact-1",
                        "text": "该模型在三项测试中表现领先。",
                        "evidence_ids": [str(EVIDENCE_A)],
                    },
                ),
                _call("2", "check_draft", {}),
            ),
            400,
            40,
        )
    ]


@pytest.mark.asyncio
async def test_shadow_case_records_agent_and_production_outcomes_side_by_side() -> None:
    case = _case()
    auditor = _Auditor()
    cap = CallCap(limit=5)

    record = await shadow_case(
        case,
        model=_Scripted(_repair_turns()),
        auditor=auditor,
        cap=cap,
        max_rounds=6,
        audit_max_output_tokens=512,
    )

    agent = record["agent"]
    assert isinstance(agent, dict)
    assert agent["passed"] is True and agent["stopped"] == "checked"
    assert agent["model_calls"] == 1 and cap.used == 2  # one agent round, one gate audit
    assert agent["edits"] == ["replace_claim:fact-1"]
    assert record["production"] == {
        "regenerated": True,
        "passed": False,
        "run_status": "review_required",
    }
    assert record["blocking_codes"] == ["evidence_mismatch"]
    assert auditor.requests[0].version_bundle.auditor_prompt_version == (
        "moments-auditor-v21-lean-context"
    )


@pytest.mark.asyncio
async def test_shadow_case_stops_at_the_model_call_cap() -> None:
    with pytest.raises(CallCapReachedError):
        await shadow_case(
            _case(),
            model=_Scripted(_repair_turns()),
            auditor=_Auditor(),
            cap=CallCap(limit=1),
            max_rounds=6,
            audit_max_output_tokens=512,
        )


def test_summary_counts_where_agent_and_regeneration_differ() -> None:
    def record(agent: bool, production: bool) -> dict[str, object]:
        return {
            "business_date": "2026-09-30",
            "agent": {"passed": agent, "model_calls": 3, "prompt_tokens": 6000},
            "production": {"passed": production},
        }

    text = summarize([record(True, True), record(True, False), record(False, True)])

    assert "| Agent 修好 | 2（67%） |" in text
    assert "| 只有 Agent 修好 | 1 |" in text
    assert "| 只有重写修好 | 1 |" in text
    assert "| 都没修好 | 0 |" in text
    assert "还没有记录" in summarize([])
