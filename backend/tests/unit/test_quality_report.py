# ruff: noqa: RUF001
from __future__ import annotations

import json
from collections import Counter
from datetime import date

import pytest
from app.application.services.quality_report import (
    Severity,
    assess,
    overall_status,
    render_json,
    render_markdown,
)
from app.domain.quality_report import (
    BrandUsageRow,
    ModelUsage,
    QualitySnapshot,
    SelectedTopicRow,
    SlotRunRow,
)
from app.infrastructure.db.quality_report import business_day_bounds


def _healthy() -> QualitySnapshot:
    return QualitySnapshot(
        business_date=date(2026, 9, 28),
        timezone="Asia/Shanghai",
        lookback_days=7,
        acquisition_runs=3,
        acquisition_new_items=42,
        slot_runs=[
            SlotRunRow(
                "evening",
                "succeeded",
                "scoring-v1-preview.13-education-policy-signal",
                3,
                0,
                (),
                None,
            ),
            SlotRunRow(
                "morning",
                "succeeded",
                "scoring-v1-preview.11-qualified-authoritative-priority",
                3,
                0,
                (),
                None,
            ),
        ],
        selected_topics=[
            SelectedTopicRow(
                "evening",
                1,
                "未来五年 教育将向六个方面重点发力",
                "education_policy_signal_national",
                "national",
                "out_of_scope",
            ),
            SelectedTopicRow(
                "evening",
                2,
                "朱雀三号一子级成功着陆",
                "not_eligible",
                None,
                "frontier_science_technology",
            ),
        ],
        copy_status=Counter({"accepted": 6}),
        copy_first_pass_accepted=4,
        copy_issue_codes=Counter({"length_advisory": 2}),
        brand_window_accepted_runs=20,
        brand_usage=[BrandUsageRow("品牌介绍 / 思维链教学法", 6), BrandUsageRow("7真 / 真动手", 4)],
        image_status=Counter({"succeeded": 6}),
        delivery_status=Counter({"delivered": 6}),
        infographic_status=Counter({"succeeded": 3}),
        supplement_status=Counter({"delivered": 3}),
        copy_model_usage=ModelUsage(calls=12, prompt_tokens=1000, completion_tokens=500),
    )


def test_healthy_day_has_no_findings_and_renders_every_section() -> None:
    snapshot = _healthy()

    findings = assess(snapshot)
    markdown = render_markdown(snapshot, findings)

    assert findings == []
    assert overall_status(findings) == "正常"
    assert "# 线上质量日报 2026-09-28（正常）" in markdown
    assert "晚间：succeeded，选出 3 条（规则 13-education-policy-signal）" in markdown
    assert "国家教育风向 1" in markdown and "前沿科技 1" in markdown
    assert "一次通过 4，修复后通过 2" in markdown
    assert "品牌介绍 / 思维链教学法 6" in markdown
    assert "Token 1,500" in markdown


def test_problems_are_flagged_with_severity() -> None:
    snapshot = _healthy()
    snapshot.slot_runs = [
        SlotRunRow("noon", "failed", None, 0, 3, (), "governance_not_ready"),
        SlotRunRow("evening", "succeeded", None, 0, 3, ("below_threshold",), None),
    ]
    snapshot.delivery_status = Counter({"delivered": 2, "result_unknown": 1})
    snapshot.delivery_error_codes = Counter({"provider_timeout": 1})
    snapshot.copy_status = Counter({"accepted": 2, "failed": 2, "review_required": 1})
    snapshot.copy_error_codes = Counter({"invalid_provider_output": 2})
    snapshot.infographic_status = Counter({"failed": 1})
    snapshot.acquisition_failed_jobs = 2
    snapshot.brand_usage = [BrandUsageRow("品牌介绍 / 思维链教学法", 12)]
    snapshot.official_account_draft_status = Counter({"failed": 1})

    findings = assess(snapshot)
    codes = {finding.code: finding for finding in findings}

    assert codes["slot_failed"].severity is Severity.CRITICAL
    assert codes["slot_empty"].severity is Severity.WARNING
    assert "below_threshold" in codes["slot_empty"].message
    assert codes["delivery_not_delivered"].severity is Severity.CRITICAL
    assert "provider_timeout" in codes["delivery_not_delivered"].message
    assert "invalid_provider_output" in codes["copy_failure_rate"].message
    assert {"copy_review_required", "infographic_failed", "acquisition_failed_jobs"} <= set(codes)
    assert "12/20" in codes["brand_claim_repetition"].message
    assert "official_account_draft_failed" in codes
    assert overall_status(findings) == "异常"
    assert render_markdown(snapshot, findings).startswith("# 线上质量日报 2026-09-28（异常）")


def test_no_slot_runs_is_critical_and_small_windows_do_not_flag_repetition() -> None:
    snapshot = QualitySnapshot(
        business_date=date(2026, 9, 28), timezone="Asia/Shanghai", lookback_days=7
    )
    snapshot.brand_window_accepted_runs = 2
    snapshot.brand_usage = [BrandUsageRow("品牌介绍", 2)]

    findings = assess(snapshot)

    assert [finding.code for finding in findings] == ["no_slot_runs"]


def test_json_output_is_complete_and_parseable() -> None:
    snapshot = _healthy()
    payload = json.loads(render_json(snapshot, assess(snapshot)))

    assert payload["report_version"] == "production-quality-daily-v1"
    assert payload["overall_status"] == "正常"
    assert payload["snapshot"]["copy_first_pass_accepted"] == 4


def test_business_day_bounds_use_the_business_timezone() -> None:
    start, end = business_day_bounds(date(2026, 9, 28), "Asia/Shanghai")

    assert start.isoformat() == "2026-09-28T00:00:00+08:00"
    assert (end - start).days == 1


@pytest.mark.parametrize("lookback", (0, -1))
def test_lookback_must_be_positive(lookback: int) -> None:
    import asyncio

    from app.infrastructure.db.quality_report import load_quality_snapshot

    with pytest.raises(ValueError, match="lookback"):
        asyncio.run(
            load_quality_snapshot(
                None,  # type: ignore[arg-type]
                business_date=date(2026, 9, 28),
                timezone="Asia/Shanghai",
                lookback_days=lookback,
            )
        )
