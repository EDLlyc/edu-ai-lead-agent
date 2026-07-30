from enum import StrEnum


class GovernanceRunTrigger(StrEnum):
    ACQUISITION = "acquisition"
    MANUAL = "manual"


class GovernanceRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GovernanceJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GovernanceAttemptResult(StrEnum):
    SUCCEEDED = "succeeded"
    RETRY_SCHEDULED = "retry_scheduled"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class FactualCategory(StrEnum):
    AI_EDUCATION_POLICY = "ai_education_policy"
    LARGE_GENERATIVE_MODELS = "large_generative_models"
    ROBOTICS_EMBODIED_INTELLIGENCE = "robotics_embodied_intelligence"
    AI_COMPUTE_CHIPS = "ai_compute_chips"
    YOUTH_SCIENCE_EDUCATION = "youth_science_education"
    AI_INDUSTRY_APPLICATION = "ai_industry_application"
    AI_GOVERNANCE_SAFETY = "ai_governance_safety"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    INVALID = "invalid"
    REVIEW_REQUIRED = "review_required"


class EmbeddingPurpose(StrEnum):
    NEAR_DUPLICATE = "near_duplicate"
    EVENT_ASSIGNMENT = "event_assignment"


class DuplicateRelationKind(StrEnum):
    SAME_CONTENT = "same_content"
    SAME_URL = "same_url"
    SAME_SOURCE_ITEM = "same_source_item"
    REVISION_OF = "revision_of"
    NEAR_DUPLICATE = "near_duplicate"


class EventAssignmentOutcome(StrEnum):
    ASSIGNED_EXISTING = "assigned_existing"
    CREATED_NEW = "created_new"
    REVIEW_REQUIRED = "review_required"


class EventTimePrecision(StrEnum):
    EXACT = "exact"
    DAY = "day"
    MONTH = "month"
    UNKNOWN = "unknown"


class FactualEntityType(StrEnum):
    ORGANIZATION = "organization"
    PERSON = "person"
    PRODUCT = "product"
    MODEL = "model"
    POLICY = "policy"
    PLACE = "place"
    TECHNOLOGY = "technology"
    OTHER = "other"


class AnalysisValidationCode(StrEnum):
    INVALID_SCHEMA = "invalid_schema"
    MALFORMED_JSON = "malformed_json"
    UNSUPPORTED_TAXONOMY = "unsupported_taxonomy"
    MISSING_EVIDENCE = "missing_evidence"
    UNKNOWN_PASSAGE_ID = "unknown_passage_id"
    PUBLICATION_TIME_MISMATCH = "publication_time_mismatch"
    EVENT_TIME_OUT_OF_RANGE = "event_time_out_of_range"
    NON_CHINESE_SUMMARY = "non_chinese_summary"
    NON_CHINESE_FACT = "non_chinese_fact"
    UNEXPECTED_FIELD = "unexpected_field"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
