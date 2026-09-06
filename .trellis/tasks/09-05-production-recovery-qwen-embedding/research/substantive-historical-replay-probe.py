import dataclasses
import hashlib
import itertools
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.domain.editorial_relevance import (
    ScienceTechEditorialCohort,
    evaluate_science_tech_editorial_relevance,
)
from app.domain.topic_selection import (
    TopicCandidate,
    TopicScoringConfig,
    score_topic_candidate,
)
from app.infrastructure.db.topic_selection import topic_scoring_config_fingerprint
from app.infrastructure.ingestion.source_profiles import SOURCE_SEEDS

versions = (
    "scoring-v1-preview.6-tiered-science-tech-priority",
    "scoring-v1-preview.7-delivered-repeat-history",
    "scoring-v1-preview.8-threshold-059",
    "scoring-v1-preview.9-broad-hard-tech-pool",
    "scoring-v1-preview.10-substantive-science-education-priority",
    "scoring-v1-preview.11-qualified-authoritative-priority",
)
now = datetime(2026, 9, 5, 12, tzinfo=UTC)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


report = {"configs": [], "scores": [], "editorial": [], "seeds": []}
for index, version in enumerate(versions):
    priority = (
        "ministry-education-priority-v3"
        if index < 4
        else "ministry-education-priority-v4-substantive-science-education"
        if index == 4
        else "qualified-authoritative-priority-v1"
    )
    config = TopicScoringConfig(
        version=version,
        threshold=0.62 if index < 2 else 0.59,
        selection_priority_rule_version=priority,
    )
    snapshot = config.as_metadata()
    assert TopicScoringConfig.from_metadata(snapshot).as_metadata() == snapshot
    report["configs"].append(
        [version, topic_scoring_config_fingerprint(config), digest(snapshot)]
    )
    for cohort, policy, strength, defect in itertools.product(
        tuple(ScienceTechEditorialCohort),
        (None, "moe-science-top1-v1", "gov-cn-qualified-science-tech-v1"),
        (0.0, 0.3, 0.59, 0.8, 1.0),
        ("none", "unverified", "evidence", "repeat"),
    ):
        candidate = TopicCandidate(
            event_id=UUID(int=1),
            event_version_id=UUID(int=2),
            event_time=now - timedelta(hours=6),
            source_trust=strength,
            source_diversity=2,
            ai_relevance=strength,
            parent_relevance=strength,
            communication_potential=strength,
            editorial_priority=strength,
            science_tech_editorial_cohort=cohort,
            science_tech_education_relevance=strength,
            frontier_significance=strength,
            product_matrix_fit_v2=strength,
            topic_priority_policy=policy,
            priority_title="学校发布科学教育课程方案",
            priority_summary="学校开设科学教育实验课程并组织教师培训",
            unverified=defect == "unverified",
            has_eligible_evidence=defect != "evidence",
            days_since_last_selection=3 if defect == "repeat" else None,
        )
        score = score_topic_candidate(candidate, as_of=now, config=config)
        report["scores"].append(digest(score.as_metadata()))
for rule in ("science-tech-editorial-v2", "science-tech-editorial-v3-broad"):
    for title, body in (
        ("", ""),
        ("会议召开", "双方讨论经贸合作并提及人工智能"),
        ("科学教育课程公布", "学校开设科学教育实验课程"),
        ("量子芯片研发完成", "团队研制量子芯片并完成测试"),
        ("Artificial intelligence model released", "Researchers developed a model"),
        ("旅游服务升级", "年度旅游航线安排和城市文化演出"),
    ):
        report["editorial"].append(
            digest(
                dataclasses.asdict(
                    evaluate_science_tech_editorial_relevance(
                        title, body, rule_version=rule
                    )
                )
            )
        )
for seed in SOURCE_SEEDS:
    report["seeds"].append([str(seed.source_version_id), seed.config_fingerprint])
print(
    json.dumps(
        {
            "config_count": len(report["configs"]),
            "score_count": len(report["scores"]),
            "editorial_count": len(report["editorial"]),
            "seed_count": len(report["seeds"]),
            "sha256": digest(report),
            "configs": report["configs"],
        },
        sort_keys=True,
    )
)
