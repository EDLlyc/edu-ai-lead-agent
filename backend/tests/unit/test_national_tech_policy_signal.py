# ruff: noqa: RUF001
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from app.application.services.topic_selection import build_topic_scoring_config
from app.core.config import Settings
from app.domain.editorial_relevance import ScienceTechEditorialCohort
from app.domain.national_tech_policy_signal import evaluate_national_tech_policy
from app.domain.topic_selection import (
    GOV_CN_YAOWEN_PRIORITY_POLICY,
    GOV_YAOWEN_TOPIC_SCORING_VERSION,
    NATIONAL_TECH_POLICY_TOPIC_SCORING_VERSION,
    TopicCandidate,
    TopicScoringConfig,
    score_topic_candidate,
    topic_priority_group,
)

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
# The real headline that production scored 0.56 (below 0.59) on 2026-10-12.
REAL_TITLE = "中共中央 国务院关于发展新质生产力的意见"


@pytest.mark.parametrize(
    "title",
    (
        REAL_TITLE,
        "国务院关于深入实施“人工智能+”行动的意见",
        "中共中央办公厅 国务院办公厅印发《关于加强科学技术普及工作的意见》",
        "国务院印发《数字中国建设整体布局规划》",
        "中共中央 国务院印发《教育强国建设规划纲要（2024—2035年）》",
    ),
)
def test_central_policy_documents_about_science_technology_or_education_qualify(
    title: str,
) -> None:
    signal = evaluate_national_tech_policy(title)
    assert signal.matched and signal.reason_code == "national_tech_policy"


@pytest.mark.parametrize(
    ("title", "reason"),
    (
        ("国务院常务会议研究推进新质生产力发展，听取意见", "national_tech_policy_excluded_item"),
        ("李强考察科技企业并座谈", "national_tech_policy_excluded_item"),
        ("李强会见吉尔吉斯斯坦总理，就科技创新合作交换意见", "national_tech_policy_excluded_item"),
        ("中美经贸磋商就人工智能问题举行对话", "national_tech_policy_excluded_item"),
        ("国务院任免国家工作人员", "national_tech_policy_excluded_item"),
        ("国务院关于水利建设投资的意见", "national_tech_policy_subject_missing"),
        ("某省关于发展新质生产力的实施意见", "national_tech_policy_issuer_missing"),
        ("国务院发展新质生产力成效显著", "national_tech_policy_document_missing"),
        ("全国办学条件持续改善 教育科技并进", "national_tech_policy_issuer_missing"),
        ("", "national_tech_policy_empty_title"),
    ),
)
def test_meetings_visits_trade_other_subjects_and_local_documents_do_not(
    title: str, reason: str
) -> None:
    signal = evaluate_national_tech_policy(title)
    assert not signal.matched and signal.reason_code == reason


def _config(version: str) -> TopicScoringConfig:
    return build_topic_scoring_config(Settings(_env_file=None, content_scoring_version=version))


def _article(title: str = REAL_TITLE, **changes: Any) -> TopicCandidate:
    """Feature vector observed in production for the real article (score 0.56)."""

    candidate = TopicCandidate(
        event_id=UUID(int=1),
        event_version_id=UUID(int=2),
        event_time=NOW - timedelta(days=3.71),
        source_trust=1.0,
        source_diversity=2,
        ai_relevance=0.0,
        parent_relevance=0.0,
        communication_potential=0.98,
        science_tech_editorial_cohort=ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY,
        science_tech_education_relevance=1.0,
        editorial_priority=1.0,
        product_matrix_fit_v2=0.0,
        theme_repetition=2 / 3,
        topic_priority_policy=GOV_CN_YAOWEN_PRIORITY_POLICY,
        priority_title=title,
        priority_summary="意见从总体要求、科技创新、产业体系、教育科技人才等方面作出部署。",
    )
    return replace(candidate, **changes)


def test_v15_leaves_the_real_article_below_threshold_and_unprioritised() -> None:
    score = score_topic_candidate(
        _article(), as_of=NOW, config=_config(GOV_YAOWEN_TOPIC_SCORING_VERSION)
    )

    assert score.total < 0.59 and not score.passes_threshold
    assert not score.eligible and not score.priority_applied
    assert score.priority_reason == "government_yaowen_not_eligible"
    assert not score.threshold_bypass_applied


def test_v17_makes_the_real_article_a_priority_item_through_the_threshold() -> None:
    v15 = score_topic_candidate(
        _article(), as_of=NOW, config=_config(GOV_YAOWEN_TOPIC_SCORING_VERSION)
    )
    v17 = score_topic_candidate(
        _article(), as_of=NOW, config=_config(NATIONAL_TECH_POLICY_TOPIC_SCORING_VERSION)
    )

    assert v17.total == v15.total  # the numeric score is untouched; only eligibility changes
    assert v17.eligible and v17.priority_applied and not v17.passes_threshold
    assert v17.priority_reason == "national_tech_policy"
    assert v17.threshold_bypass_applied
    assert v17.threshold_bypass_reason == "national_tech_policy"
    assert topic_priority_group(v17) == 0
    assert topic_priority_group(v15) == 3


@pytest.mark.parametrize(
    "veto_change",
    (
        {"unsuitable_negative_incident": True},
        {"governance_resolved": False},
        {"has_eligible_evidence": False},
        {"days_since_last_selection": 3},
    ),
)
def test_v17_never_overrides_a_hard_veto(veto_change: dict[str, Any]) -> None:
    score = score_topic_candidate(
        _article(**veto_change),
        as_of=NOW,
        config=_config(NATIONAL_TECH_POLICY_TOPIC_SCORING_VERSION),
    )

    assert score.veto_codes
    assert not score.eligible and not score.priority_applied
    assert not score.threshold_bypass_applied


def test_v17_needs_the_authenticated_government_source_and_a_qualifying_headline() -> None:
    config = _config(NATIONAL_TECH_POLICY_TOPIC_SCORING_VERSION)
    other_source = score_topic_candidate(
        _article(topic_priority_policy=None), as_of=NOW, config=config
    )
    meeting = score_topic_candidate(
        _article("国务院常务会议研究推进新质生产力发展，听取意见"), as_of=NOW, config=config
    )

    assert not other_source.eligible and not other_source.threshold_bypass_applied
    assert not meeting.eligible and not meeting.threshold_bypass_applied


def test_default_is_v17_and_metadata_round_trips() -> None:
    config = build_topic_scoring_config(Settings(_env_file=None))

    assert config.version == NATIONAL_TECH_POLICY_TOPIC_SCORING_VERSION
    assert config.has_national_tech_policy and config.has_government_yaowen_topic_gate
    assert config.recent_selection_window_days == 14
    metadata = config.as_metadata()
    assert metadata["national_tech_policy_rule_version"] == "national-tech-policy-signal-v1"
    assert metadata["government_yaowen_topic_rule_version"] == "gov-yaowen-topic-v1"
    assert TopicScoringConfig.from_metadata(metadata).as_metadata() == metadata
    v15 = _config(GOV_YAOWEN_TOPIC_SCORING_VERSION)
    assert not v15.has_national_tech_policy and v15.has_government_yaowen_topic_gate
    assert "national_tech_policy_rule_version" not in v15.as_metadata()
