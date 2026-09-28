# ruff: noqa: RUF001
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.application.services.topic_selection import build_topic_scoring_config
from app.core.config import Settings
from app.domain.editorial_relevance import ScienceTechEditorialCohort
from app.domain.topic_safety_signals import (
    evaluate_industrial_technology,
    evaluate_negative_incident,
    is_industrial_technology_title,
)
from app.domain.topic_selection import (
    EDUCATION_POLICY_TOPIC_SCORING_VERSION,
    GOV_CN_YAOWEN_PRIORITY_POLICY,
    SAFETY_INDUSTRY_TOPIC_SCORING_VERSION,
    TopicCandidate,
    TopicScoringConfig,
    TopicVetoCode,
    score_topic_candidate,
)

NOW = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)
RUMOUR = (
    "男子编造“某院士窃取他人科研成果”谣言，已被刑拘",
    "上海市公安局黄浦分局通报，刘某某编造谣言并在社交媒体传播，张某某利用AI软件生成相关虚假视频"
    "发布上网，二人均已被依法刑事拘留。",
)
INDUSTRY = (
    "【“十五五”开好局起好步】融合升级 新型工业化提速",
    "国务院新闻办公室今天举行新闻发布会。工业和信息化部有关负责人表示，我国将实施一系列专项行动，"
    "加快构建以先进制造业为骨干的现代化产业体系。",
)


@pytest.mark.parametrize(
    ("title", "summary", "reason"),
    (
        (*RUMOUR, "negative_incident_legal_or_rumour"),
        ("某地发生车祸致3人死亡", "事故原因正在调查。", "negative_incident_casualty_headline"),
        ("某公司员工涉嫌诈骗被批捕", "检察机关依法批准逮捕。", "negative_incident_legal_or_rumour"),
    ),
)
def test_negative_incidents_are_detected(title: str, summary: str, reason: str) -> None:
    result = evaluate_negative_incident(title, summary)
    assert result.matched and result.reason_code == reason


@pytest.mark.parametrize(
    ("title", "summary"),
    (
        ("科学辟谣：吃糖会让孩子多动吗？", "网上谣言称吃糖导致多动，研究并不支持。"),
        ("反诈宣传进校园", "民警为学生讲解防诈骗知识。"),
        ("研究揭示细胞程序性死亡新机制", "团队发现细胞死亡调控通路。"),
        ("朱雀三号遥二运载火箭发射成功 一子级成功着陆预定位置", "发射成功。"),
    ),
)
def test_constructive_or_scientific_text_is_not_negative(title: str, summary: str) -> None:
    assert not evaluate_negative_incident(title, summary).matched


def test_industrial_technology_needs_headline_term_and_national_issuer() -> None:
    assert evaluate_industrial_technology(*INDUSTRY).matched
    assert is_industrial_technology_title(INDUSTRY[0])
    local = evaluate_industrial_technology("某区推进数字化转型", "区里召开工作会议。")
    assert local.reason_code == "industrial_technology_issuer_missing"
    assert not evaluate_industrial_technology("融合升级 提速", INDUSTRY[1]).matched


def _candidate(title_summary: tuple[str, str], **changes: object) -> TopicCandidate:
    candidate = TopicCandidate(
        event_id=UUID(int=1),
        event_version_id=UUID(int=2),
        event_time=NOW - timedelta(days=1),
        source_trust=1.0,
        source_diversity=1,
        ai_relevance=0.0,
        parent_relevance=0.0,
        communication_potential=0.5,
        science_tech_editorial_cohort=ScienceTechEditorialCohort.OUT_OF_SCOPE,
        priority_title=title_summary[0],
        priority_summary=title_summary[1],
    )
    return replace(candidate, **changes)


def _config(version: str = SAFETY_INDUSTRY_TOPIC_SCORING_VERSION) -> TopicScoringConfig:
    return build_topic_scoring_config(Settings(_env_file=None, content_scoring_version=version))


def test_default_is_v14_and_metadata_round_trips() -> None:
    config = _config()
    assert build_topic_scoring_config(Settings(_env_file=None)).version == (
        SAFETY_INDUSTRY_TOPIC_SCORING_VERSION
    )
    assert config.has_safety_industry_rules and config.has_education_policy_signal
    metadata = config.as_metadata()
    assert metadata["negative_incident_rule_version"] == "negative-incident-v1"
    assert metadata["industrial_technology_rule_version"] == "industrial-technology-v1"
    assert TopicScoringConfig.from_metadata(metadata).as_metadata() == metadata
    assert (
        "negative_incident_rule_version"
        not in _config(EDUCATION_POLICY_TOPIC_SCORING_VERSION).as_metadata()
    )


def test_v14_vetoes_rumour_that_v13_selected() -> None:
    rumour = _candidate(
        RUMOUR,
        science_tech_editorial_cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
        editorial_priority=0.7,
        product_matrix_fit_v2=0.5,
    )

    v13 = score_topic_candidate(
        rumour, as_of=NOW, config=_config(EDUCATION_POLICY_TOPIC_SCORING_VERSION)
    )
    v14 = score_topic_candidate(rumour, as_of=NOW, config=_config())

    assert v13.eligible
    assert not v14.eligible
    assert TopicVetoCode.UNSUITABLE_NEGATIVE_INCIDENT in v14.veto_codes


def test_v14_admits_national_industry_news_with_yaowen_priority() -> None:
    news = _candidate(INDUSTRY, topic_priority_policy=GOV_CN_YAOWEN_PRIORITY_POLICY)

    v13 = score_topic_candidate(
        news, as_of=NOW, config=_config(EDUCATION_POLICY_TOPIC_SCORING_VERSION)
    )
    v14 = score_topic_candidate(news, as_of=NOW, config=_config())

    assert not v13.eligible
    assert v14.eligible and v14.priority_applied
    assert v14.priority_reason == "qualified_government_yaowen_priority"
    assert (
        v14.science_tech_editorial_cohort is ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY
    )
    assert "industrial_technology_national" in v14.science_tech_editorial_reason_codes


def test_negative_education_policy_news_is_still_vetoed() -> None:
    news = _candidate(
        ("教育部通报：某高校招生诈骗案嫌疑人被逮捕", "教育部通报高校招生改革中的诈骗案件。")
    )

    score = score_topic_candidate(news, as_of=NOW, config=_config())

    assert not score.eligible and not score.priority_applied
