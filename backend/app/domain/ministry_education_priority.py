from __future__ import annotations

from dataclasses import dataclass

from app.domain.editorial_relevance import ScienceTechEditorialCohort

MINISTRY_EDUCATION_PRIORITY_RULE_VERSION = "ministry-education-priority-v3"
MOE_SCIENCE_TOP1_PRIORITY_POLICY = "moe-science-top1-v1"


@dataclass(frozen=True, slots=True)
class MinistryEducationPriorityResult:
    is_eligible: bool
    reason_code: str
    rule_version: str = MINISTRY_EDUCATION_PRIORITY_RULE_VERSION


def evaluate_ministry_education_priority(
    *,
    topic_priority_policy: str | None,
    editorial_cohort: ScienceTechEditorialCohort,
) -> MinistryEducationPriorityResult:
    """Compose authenticated Ministry policy metadata with the governed v2 cohort."""

    if topic_priority_policy is None:
        return MinistryEducationPriorityResult(False, "no_topic_priority_policy")
    if topic_priority_policy != MOE_SCIENCE_TOP1_PRIORITY_POLICY:
        return MinistryEducationPriorityResult(False, "unsupported_topic_priority_policy")
    if editorial_cohort is not ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY:
        return MinistryEducationPriorityResult(False, "ministry_education_topic_missing")
    return MinistryEducationPriorityResult(True, "ministry_education_priority")
