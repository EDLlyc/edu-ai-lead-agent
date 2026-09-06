"""Synthetic policy regressions, not measured human precision/recall or a safety classifier."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from itertools import product
from pathlib import Path
from uuid import UUID

import pytest
from app.application.services.topic_selection import build_topic_scoring_config
from app.core.config import Settings
from app.domain.editorial_relevance import (
    SCIENCE_TECH_EDITORIAL_RULE_VERSION,
    SCIENCE_TECH_EDITORIAL_V2_RULE_VERSION,
    SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION,
    SUPPORTED_SCIENCE_TECH_EDITORIAL_RULE_VERSIONS,
    ScienceTechEditorialCohort,
    evaluate_science_tech_editorial_relevance,
)
from app.domain.topic_selection import (
    GOV_CN_YAOWEN_PRIORITY_POLICY,
    MOE_SCIENCE_TOP1_PRIORITY_POLICY,
    QUALIFIED_AUTHORITATIVE_TOPIC_SCORING_VERSION,
    SUBSTANTIVE_TOPIC_SCORING_VERSION,
    TopicCandidate,
    TopicScoringConfig,
    score_topic_candidate,
)
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS

NOW = datetime(2026, 9, 5, 8, tzinfo=UTC)
HISTORICAL_VERSIONS = (
    "scoring-v1-preview.6-tiered-science-tech-priority",
    "scoring-v1-preview.7-delivered-repeat-history",
    "scoring-v1-preview.8-threshold-059",
    "scoring-v1-preview.9-broad-hard-tech-pool",
    "scoring-v1-preview.10-substantive-science-education-priority",
    "scoring-v1-preview.11-qualified-authoritative-priority",
)
HISTORICAL_POSITIVE_CASES = (
    ("人工智能治理办法公布", "有关部门发布人工智能治理办法。办法明确模型风险评估和测试标准。"),
    ("学校推进科学教育", "学校开设科学课程并培训科学教师。学生通过实验开展科学探究。"),
    ("科研团队发布新模型", "团队发布新一代人工智能模型。该模型支持多模态输入并降低推理延迟。"),
    ("量子计算取得进展", "研究团队研制量子计算芯片。实验测量精度达到新水平。其能耗降低30%。"),
    ("研究取得新结果", "团队研制新型量子计算芯片。实验测量误差降至0.1%。其功耗降低30%。"),
    ("有关部门发布新规范", "有关部门制定人工智能评测标准。标准明确风险评估与测试要求。"),
    ("新成果发布", "研究团队开发人工智能算法并开源测试代码。"),
    ("机器人产品上市", "企业发布新一代人形机器人并完成性能测试。"),
)
POSITIVE_CASES = (
    *HISTORICAL_POSITIVE_CASES,
    ("研究结果公布", "研究表明新材料能够降低电池能耗。实验测量效率提升20%。"),
    ("科研团队公布发现", "团队证实新发现的蛋白质参与细胞修复机制。"),
    ("芯片进入量产", "工厂量产新型半导体芯片。该芯片功耗降低30%。"),
)
HISTORICAL_NEGATIVE_CASES = (
    ("经贸论坛举行", "与会代表讨论贸易投资和区域合作。会议还提及人工智能合作。"),
    ("经济合作取得成果", "会议就基础设施投资和双边贸易达成共识\uff0c并提及人工智能治理。"),
    ("经济合作取得成果", "会议研究区域发展贸易投资旅游文化和教育并要求推进人工智能合作。"),
    ("双边会谈举行", "双方研究贸易金融港口公路等领域合作并要求推动人工智能交流。"),
    ("人工智能发展新进展", "两地代表讨论货物运输便利化。港口贸易额增长。会议安排文艺演出。"),
    ("会议通报", "人工智能、机器人、量子计算、人工智能、机器人、量子计算。"),
    ("会议通报", "人工智能 机器人 量子计算。人工智能 机器人 量子计算。"),
    ("会议通报", "会上提及人工智能。两地港口货物运输保持稳定。后续还将开展教育交流。"),
    ("人工智能模型发布", None),
    ("人工智能模型发布", "AI"),
    ("会议通报", "人工智能科技教育"),
)
NEGATIVE_CASES = (
    *HISTORICAL_NEGATIVE_CASES,
    ("合作论坛举行", "代表讨论贸易投资。会议明确人工智能合作方向。"),
    ("经贸会议举行", "双方就港口贸易达成共识。代表支持人工智能交流。"),
    ("联合声明发布", "双方发布人工智能合作倡议。"),
)


@pytest.mark.parametrize(("title", "body"), POSITIVE_CASES)
def test_substantive_subject_is_qualified(title: str, body: str) -> None:
    result = evaluate_science_tech_editorial_relevance(
        title, body, rule_version=SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION
    )
    assert result.is_candidate
    assert result.rule_version == SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION
    assert result.reason_codes[0] == "substantive_topic_primary"


@pytest.mark.parametrize(("title", "body"), NEGATIVE_CASES)
def test_incidental_or_unsupported_subject_is_not_qualified(title: str, body: str | None) -> None:
    result = evaluate_science_tech_editorial_relevance(
        title, body, rule_version=SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION
    )
    assert not result.is_candidate
    assert result.cohort is ScienceTechEditorialCohort.OUT_OF_SCOPE
    assert result.editorial_priority_score == 0
    assert result.reason_codes[0].startswith("substantive_topic_")


def test_repetition_does_not_manufacture_primary_subject() -> None:
    background = "大会讨论双边经贸关系和港口基础设施建设。双方就货物运输便利化达成共识。"
    incidental = "团队发布人工智能模型。"
    for count in (1, 4, 100):
        result = evaluate_science_tech_editorial_relevance(
            "双边经贸会谈",
            background + incidental * count,
            rule_version=SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION,
        )
        assert not result.is_candidate


@pytest.mark.parametrize(
    ("title", "body"),
    (
        (
            "测试数据公布",
            "新型人工智能模型的准确率为92%。该系统的推理延迟为15毫秒,功耗比此前方案低三成。",
        ),
        (
            "量子测试结果",
            "新型量子芯片的误差率为0.1%。其工作温度为二十毫开尔文,持续运行时间为十小时。",
        ),
        ("新产品发布", "企业研制新型半导体芯片。该芯片功耗降低30%。"),
        (
            "政策发布",
            "各国代表发布人工智能风险评估标准,规范模型能力测试和训练数据审查。该标准提出统一评测方法并明确技术报告要求。",
        ),
    ),
)
def test_explicit_measurement_or_technical_object_can_authenticate_subject(
    title: str, body: str
) -> None:
    assert evaluate_science_tech_editorial_relevance(
        title, body, rule_version=SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION
    ).is_candidate


@pytest.mark.parametrize(
    "body",
    (
        "人工智能 92% 机器人 30% 量子计算 0.1%。",
        "量子计算 量子计算 量子计算 量子计算。",
        "可回收火箭 可回收火箭 可回收火箭 可回收火箭。",
        "半导体 芯片 半导体 芯片 集成电路 集成电路。",
    ),
)
def test_bare_numbers_and_compound_nouns_are_not_predicates(body: str) -> None:
    assert not evaluate_science_tech_editorial_relevance(
        "关键词通报", body, rule_version=SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION
    ).is_candidate


def test_continuity_is_bounded_and_resets_on_new_subject_or_paragraph() -> None:
    anchor = "团队研制新型量子计算芯片。"
    details = "实验测量误差降至0.1%。其功耗降低30%。"
    assert evaluate_science_tech_editorial_relevance(
        "最新研究", anchor + details, rule_version=SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION
    ).is_candidate
    for separator in ("\n", "双方讨论港口投资和区域贸易。"):
        result = evaluate_science_tech_editorial_relevance(
            "最新研究",
            anchor + separator + details * 2,
            rule_version=SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION,
        )
        assert not result.is_candidate


def test_body_bound_prevents_late_topic_rescue() -> None:
    result = evaluate_science_tech_editorial_relevance(
        "最新研究",
        "双方讨论经贸合作。" * 100 + POSITIVE_CASES[2][1],
        body_limit=120,
        rule_version=SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION,
    )
    assert not result.is_candidate
    assert result.body_truncated
    with pytest.raises(ValueError):
        evaluate_science_tech_editorial_relevance(
            "", "", body_limit=0, rule_version=SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION
        )


def _candidate(**changes: object) -> TopicCandidate:
    candidate = TopicCandidate(
        event_id=UUID(int=1),
        event_version_id=UUID(int=2),
        event_time=NOW,
        source_trust=1,
        source_diversity=4,
        ai_relevance=1,
        parent_relevance=1,
        communication_potential=1,
        product_matrix_fit_v2=1,
        editorial_priority=1,
        priority_title="教育部印发科学教育课程实施办法",
        priority_summary="学校实施科学教育课程并培训教师。",
    )
    return replace(candidate, **changes)


@pytest.mark.parametrize(
    "policy", (None, GOV_CN_YAOWEN_PRIORITY_POLICY, MOE_SCIENCE_TOP1_PRIORITY_POLICY)
)
@pytest.mark.parametrize("trust", (0.1, 1.0))
def test_scope_precedes_numeric_pool_and_source_priority(policy: str | None, trust: float) -> None:
    config = build_topic_scoring_config(Settings(_env_file=None))
    score = score_topic_candidate(
        _candidate(topic_priority_policy=policy, source_trust=trust), as_of=NOW, config=config
    )
    assert not score.eligible
    assert not score.priority_applied
    assert not score.threshold_bypass_applied


@pytest.mark.parametrize(
    "changes",
    (
        {"unverified": True},
        {"tier_c_only": True},
        {"unsuitable_negative_incident": True},
        {"privacy_legal_safety_uncertain": True},
        {"prohibited_marketing_risk": True},
        {"governance_resolved": False},
        {"has_eligible_evidence": False},
        {"days_since_last_selection": 3},
        {"event_time": NOW - timedelta(days=11)},
    ),
)
@pytest.mark.parametrize(
    ("cohort", "policy"),
    (
        (ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY, GOV_CN_YAOWEN_PRIORITY_POLICY),
        (
            ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY,
            MOE_SCIENCE_TOP1_PRIORITY_POLICY,
        ),
    ),
)
def test_genuine_vetoes_remain_authoritative(
    changes: dict[str, object], cohort: ScienceTechEditorialCohort, policy: str
) -> None:
    config = build_topic_scoring_config(Settings(_env_file=None))
    candidate = _candidate(
        science_tech_editorial_cohort=cohort,
        topic_priority_policy=policy,
        **changes,
    )
    score = score_topic_candidate(candidate, as_of=NOW, config=config)
    assert not score.eligible and not score.priority_applied and not score.threshold_bypass_applied


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _historical_score_digest() -> str:
    rows = []
    for version, cohort, policy, veto, feature, evidence in product(
        HISTORICAL_VERSIONS,
        tuple(ScienceTechEditorialCohort),
        (None, GOV_CN_YAOWEN_PRIORITY_POLICY, MOE_SCIENCE_TOP1_PRIORITY_POLICY),
        (False, True),
        (0.0, 0.2, 0.5, 0.8, 1.0),
        (False, True),
    ):
        config = build_topic_scoring_config(
            Settings(
                _env_file=None,
                content_scoring_version=version,
                content_selection_priority_rule_version=(
                    "qualified-authoritative-priority-v1"
                    if version == HISTORICAL_VERSIONS[5]
                    else "ministry-education-priority-v4-substantive-science-education"
                    if version == HISTORICAL_VERSIONS[4]
                    else "ministry-education-priority-v3"
                ),
            )
        )
        candidate = _candidate(
            science_tech_editorial_cohort=cohort,
            topic_priority_policy=policy,
            unverified=veto,
            has_eligible_evidence=evidence,
            editorial_priority=feature,
            product_matrix_fit_v2=feature,
            source_trust=feature,
        )
        rows.append(score_topic_candidate(candidate, as_of=NOW, config=config).as_metadata())
    assert len(rows) == 1080
    return _hash(rows)


def test_historical_1080_scoring_explanations_are_byte_equivalent() -> None:
    assert (
        _historical_score_digest()
        == "d23d658665caf062b45cc3fde01bf4fec758e860e691bab754f21804770eda3a"
    )


def _historical_editorial_digest() -> str:
    return _hash(
        [
            asdict(evaluate_science_tech_editorial_relevance(title, body, rule_version=version))
            for version in (
                SCIENCE_TECH_EDITORIAL_V2_RULE_VERSION,
                SCIENCE_TECH_EDITORIAL_RULE_VERSION,
            )
            for title, body in (*HISTORICAL_POSITIVE_CASES, *HISTORICAL_NEGATIVE_CASES)
        ]
    )


def test_literal_v2_v3_editorial_results_remain_unchanged() -> None:
    assert SCIENCE_TECH_EDITORIAL_RULE_VERSION == "science-tech-editorial-v3-broad"
    assert (
        _historical_editorial_digest()
        == "ace540bbbd8b4ace842c14209aa79450702105d3d90ac872eaf24cff4f631575"
    )
    assert evaluate_science_tech_editorial_relevance("人工智能模型发布").is_candidate


def test_all_eleven_acquisition_fingerprints_are_frozen() -> None:
    assert len(SOURCE_SEEDS) == 11
    assert SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION not in (
        SUPPORTED_SCIENCE_TECH_EDITORIAL_RULE_VERSIONS
    )
    assert {seed.relevance_rule_version for seed in SOURCE_SEEDS} == {
        SCIENCE_TECH_EDITORIAL_RULE_VERSION
    }
    assert (
        _hash([(seed.slug, seed.config_fingerprint) for seed in SOURCE_SEEDS])
        == "75a72ee79df27a0108cf122acf99a869a7cae9db60b7f788f89fe4ee984fd71c"
    )


def test_config_defaults_and_new_snapshot_are_coherent() -> None:
    new = build_topic_scoring_config(Settings(_env_file=None))
    old = build_topic_scoring_config(
        Settings(
            _env_file=None, content_scoring_version=QUALIFIED_AUTHORITATIVE_TOPIC_SCORING_VERSION
        )
    )
    assert new.version == SUBSTANTIVE_TOPIC_SCORING_VERSION
    assert (
        new.effective_science_tech_editorial_rule_version == SCIENCE_TECH_EDITORIAL_V4_RULE_VERSION
    )
    assert TopicScoringConfig.from_metadata(new.as_metadata()).as_metadata() == new.as_metadata()
    before, after = old.as_metadata(), new.as_metadata()
    for key in ("version", "science_tech_editorial_rule_version"):
        before.pop(key)
        after.pop(key)
    assert before == after
    assert new.has_authenticated_ministry_priority
    assert new.has_broad_hard_tech_pool and new.has_qualified_authoritative_priority
    root = Path(__file__).resolve().parents[3]
    for path in (".env.example", "compose.yaml", "scripts/doctor.sh"):
        assert SUBSTANTIVE_TOPIC_SCORING_VERSION in (root / path).read_text()


def test_mismatched_new_editorial_identity_cannot_enable_bypasses() -> None:
    new = build_topic_scoring_config(Settings(_env_file=None))
    mismatched = replace(
        new,
        science_tech_editorial_rule_version=SCIENCE_TECH_EDITORIAL_RULE_VERSION,
        product_matrix_fit_rule_version=new.effective_product_matrix_fit_rule_version,
    )
    assert not mismatched.has_broad_hard_tech_pool
    assert not mismatched.has_qualified_authoritative_priority
    assert not mismatched.has_authenticated_ministry_priority
