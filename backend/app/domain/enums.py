from enum import StrEnum


class SourceTier(StrEnum):
    A = "A"
    B = "B"


class RunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ObservationOutcome(StrEnum):
    NEW = "new"
    UNCHANGED = "unchanged"
    NOT_MODIFIED = "not_modified"
    EXACT_DUPLICATE = "exact_duplicate"
    TRANSIENT_FETCH_FAILURE = "transient_fetch_failure"
    PERMANENT_FETCH_FAILURE = "permanent_fetch_failure"
    POLICY_REJECTION = "policy_rejection"
    RESPONSE_LIMIT_REJECTION = "response_limit_rejection"
    UNSUPPORTED_CONTENT = "unsupported_content"
    PARSE_FAILURE = "parse_failure"
    FILTERED = "filtered"
    NO_RELEVANT_ITEMS = "no_relevant_items"
    STALE = "stale"
    FRESHNESS_UNKNOWN = "freshness_unknown"
