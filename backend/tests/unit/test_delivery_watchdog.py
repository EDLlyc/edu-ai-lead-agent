# ruff: noqa: RUF001

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from app.application.services.ops_tools import (
    CopyRunItem,
    CopyRunsResult,
    DeliveriesResult,
    DeliveryItem,
    SlotRunItem,
    SlotRunsResult,
)
from app.delivery_watchdog_main import check_slot

DAY = date(2026, 10, 1)
AT = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)


def _slot(unfilled: int = 0) -> SlotRunsResult:
    return SlotRunsResult(
        runs=(
            SlotRunItem(
                content_slot="noon",
                status="succeeded",
                target_at=AT,
                total_scores=500,
                eligible_scores=40,
                selected_count=3 - unfilled,
                unfilled_count=unfilled,
                unfilled_reason_codes=("no_eligible_topic",) if unfilled else (),
                error_code=None,
            ),
        )
    )


def _copy(ordinal: int, status: str = "accepted") -> CopyRunItem:
    return CopyRunItem(
        run_id=uuid4(),
        content_slot="noon",
        ordinal=ordinal,
        title=f"新闻{ordinal}",
        status=status,
        decision_kind="selected",
        repair_count=0,
        error_code="repair_validation_failed" if status != "accepted" else None,
        generator_prompt_version=None,
        auditor_prompt_version=None,
        created_at=AT,
        completed_at=AT,
    )


def _job(ordinal: int, status: str = "delivered") -> DeliveryItem:
    return DeliveryItem(
        content_slot="noon",
        sequence_ordinal=ordinal,
        status=status,
        text_status=status,
        image_status=status,
        attempt_count=1,
        last_error_code="provider_timeout" if status != "delivered" else None,
        not_before=AT,
        completed_at=AT if status == "delivered" else None,
    )


def test_a_fully_delivered_slot_raises_nothing() -> None:
    check = check_slot(
        DAY,
        "noon",
        _slot(),
        CopyRunsResult(runs=tuple(_copy(i) for i in (1, 2, 3))),
        DeliveriesResult(deliveries=tuple(_job(i) for i in (1, 2, 3))),
    )

    assert check.ok


def test_review_required_copy_and_a_stuck_delivery_are_both_reported() -> None:
    check = check_slot(
        DAY,
        "noon",
        _slot(),
        CopyRunsResult(runs=(_copy(1), _copy(2), _copy(3, "review_required"))),
        DeliveriesResult(deliveries=(_job(1), _job(2))),
    )

    assert not check.ok
    assert any("第 3 条文案 review_required" in p for p in check.problems)
    assert any(p.startswith("已送达 2/3") for p in check.problems)
    assert check.message().startswith("【推送告警】2026-10-01 午间推送异常")


def test_an_unfilled_slot_is_reported_even_when_the_rest_went_out() -> None:
    check = check_slot(
        DAY,
        "noon",
        _slot(unfilled=1),
        CopyRunsResult(runs=(_copy(1), _copy(2))),
        DeliveriesResult(deliveries=(_job(1), _job(2))),
    )

    assert check.problems == ["选题少了 1 条（no_eligible_topic）"]
