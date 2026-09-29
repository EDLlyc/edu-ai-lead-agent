# ruff: noqa: RUF001
from __future__ import annotations

import json
from collections import Counter
from datetime import date
from uuid import uuid4

import pytest
from app.application.services.quality_report import (
    Severity,
    assess,
    most_repeated_brand_phrase,
    overall_status,
    render_json,
    render_markdown,
)
from app.domain.content_slots import TopicFingerprint
from app.domain.quality_report import (
    BrandStatementRow,
    BrandUsageRow,
    DailyTrendRow,
    ModelUsage,
    QualitySnapshot,
    RepeatedStoryRow,
    SameTopicPair,
    SelectedTopicRow,
    SlotRunRow,
    topic_match_kind,
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

    assert payload["report_version"] == "production-quality-daily-v3"
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


def _statement(
    run: str, text: str, *, day: int = 28, label: str | None = None
) -> BrandStatementRow:
    return BrandStatementRow(run_id=run, business_date=date(2026, 9, day), label=label, text=text)


def test_repeated_brand_phrase_ignores_brand_names_and_expands_to_the_shared_wording() -> None:
    statements = [
        _statement(
            "a", "在赛先生，我们用思维链教学法引导孩子——AI不直接给答案，而是展示完整的思考过程"
        ),
        _statement("b", "赛先生科学用思维链教学法引导孩子自己拆解问题，AI不直接给答案"),
        _statement("c", "在赛先生科学，AI不直接给答案，而是一步步引导孩子"),
        _statement("d", "在赛先生科学，我们让孩子亲自接触材料、尝试操作并观察现象"),
    ]

    phrase = most_repeated_brand_phrase(statements)

    assert phrase is not None
    assert phrase.phrase == "ai不直接给答案"
    assert phrase.runs == 3
    # Brand names alone never count as repeated wording.
    assert (
        most_repeated_brand_phrase(
            [_statement("x", "在赛先生科学"), _statement("y", "在赛先生科学")]
        )
        is None
    )


def test_selection_audit_flags_negative_incident_and_same_day_same_topic() -> None:
    snapshot = _healthy()
    snapshot.selected_topics.append(
        SelectedTopicRow(
            "morning",
            3,
            "男子编造“某院士窃取他人科研成果”谣言，已被刑拘",
            None,
            None,
            "frontier_science_technology",
            summary="警方通报",
        )
    )
    snapshot.same_topic_pairs = [
        SameTopicPair("evening#1", "evening#3", kind="similar_article"),
        SameTopicPair("noon#1", "noon#2", kind="title_phrase"),
    ]

    findings = assess(snapshot)
    codes = {finding.code: finding for finding in findings}
    markdown = render_markdown(snapshot, findings)

    assert codes["selected_negative_incident"].severity is Severity.CRITICAL
    assert "早间#3" in codes["selected_negative_incident"].message
    assert codes["selected_same_topic"].message == "同一天选中了同一件事：晚间#1 与 晚间#3。"
    assert "已被刑拘 ⚠负面事件" in markdown
    assert "- 同题：晚间#1 与 晚间#3\n" in markdown
    # Headline-only matches are shown but never raised as a finding (low precision).
    assert "- 同题：午间#1 与 午间#2（仅标题相似，可能误判）" in markdown


def test_brand_phrase_repetition_and_todays_angles_are_reported() -> None:
    snapshot = _healthy()
    snapshot.brand_window_accepted_runs = 13
    snapshot.brand_statements = [
        _statement(str(index), "在赛先生，AI不直接给答案，而是展示完整的思考过程", day=27)
        for index in range(4)
    ] + [
        _statement("t1", "我们让孩子亲自接触材料、尝试操作并观察现象", label="morning#1"),
        _statement("t2", "我们鼓励孩子说清观察、做法与发现", label="human"),
    ]
    snapshot.copy_prompt_versions = Counter({"moments-generator-v25-brand-rotation": 2})
    snapshot.acquisition_failed_sources = Counter({"cas-research:conflict": 3})

    findings = assess(snapshot)
    markdown = render_markdown(snapshot, findings)

    assert [finding.code for finding in findings] == ["brand_phrase_repetition"]
    assert (
        "4/13 篇文案重复使用品牌话术「ai不直接给答案而是展示完整的思考过程」" in findings[0].message
    )
    assert "  - 早间#1：我们让孩子亲自接触材料、尝试操作并观察现象" in markdown
    assert "  - 人工加推：我们鼓励孩子说清观察、做法与发现" in markdown
    assert "文案版本：moments-generator-v25-brand-rotation×2" in markdown
    assert "失败信源：cas-research:conflict×3" in markdown


def test_human_pick_topics_are_labelled_separately() -> None:
    snapshot = _healthy()
    snapshot.selected_topics.append(
        SelectedTopicRow("noon", 1, "青少年科技创新大赛开幕", None, None, None, human_pick=True)
    )

    markdown = render_markdown(snapshot, assess(snapshot))

    assert "  - 人工加推 [其他] 青少年科技创新大赛开幕" in markdown


def test_topic_match_kind_orders_clauses() -> None:
    event = uuid4()
    same = TopicFingerprint(event_id=event, title="甲")
    assert topic_match_kind(same, TopicFingerprint(event_id=event, title="乙")) == "same_event"
    left = TopicFingerprint(event_id=uuid4(), title="火箭发射", embedding=(1.0, 0.0))
    right = TopicFingerprint(event_id=uuid4(), title="大熊猫", embedding=(0.95, 0.05))
    assert topic_match_kind(left, right) == "similar_article"
    title_only = TopicFingerprint(event_id=uuid4(), title="世界技能大赛闭幕")
    assert topic_match_kind(TopicFingerprint(uuid4(), "世界技能大赛开幕"), title_only) == (
        "title_phrase"
    )


def test_repeat_of_a_delivered_story_and_off_topic_gov_priority_are_flagged() -> None:
    snapshot = _healthy()
    snapshot.selected_topics.append(
        SelectedTopicRow(
            "morning",
            1,
            "中美经贸磋商在美国纽约举行",
            "qualified_government_yaowen_priority",
            None,
            "frontier_science_technology",
        )
    )
    snapshot.repeated_stories = [
        RepeatedStoryRow(
            "morning#2",
            "望宇登月服研制已攻克数十项关键技术",
            date(2026, 9, 21),
            "望宇登月服研制已攻克数十项关键技术",
            "same_event",
        ),
        RepeatedStoryRow(
            "noon#1",
            "世界技能大赛标准引领职教课堂",
            date(2026, 9, 24),
            "李强出席2026年世界技能大会开幕式并致辞",
            "title_phrase",
        ),
    ]

    findings = assess(snapshot)
    codes = {finding.code: finding for finding in findings}
    markdown = render_markdown(snapshot, findings)

    assert "早间#2「望宇登月服" in codes["repeated_delivered_story"].message
    assert "世界技能大赛标准" not in codes["repeated_delivered_story"].message
    assert "早间#1「中美经贸磋商" in codes["gov_priority_off_topic"].message
    assert (
        "与已推重复：午间#1 ≈ 09-24「李强出席2026年世界技能大会开幕式并致辞」（仅标题相似"
        in markdown
    )


def test_daily_trend_is_rendered_as_a_table() -> None:
    snapshot = _healthy()
    snapshot.daily_trend = [
        DailyTrendRow(date(2026, 9, 27), 9, 7, 2, 6, 0),
        DailyTrendRow(date(2026, 9, 28), 9, 6, 3, 4, 1),
    ]

    markdown = render_markdown(snapshot, assess(snapshot))

    assert "**近 2 天趋势**" in markdown
    assert "| 09-28 | 9 | 6 | 3 | 4 | 1 |" in markdown
