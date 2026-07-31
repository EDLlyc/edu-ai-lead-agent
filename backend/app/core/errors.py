from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

_PROVIDER_VALIDATION_ISSUE_LIMIT = 12
_PROVIDER_VALIDATION_LOC_DEPTH = 8
_PROVIDER_VALIDATION_LOC_SEGMENT_LIMIT = 64
_PROVIDER_VALIDATION_TYPE_LIMIT = 80
_UNSAFE_PROVIDER_VALIDATION_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int = 500
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


class NotFoundError(AppError):
    def __init__(self, resource: str) -> None:
        super().__init__("not_found", f"{resource} was not found", 404)


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("conflict", message, 409)


class PolicyRejectedError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 422)


class FetchError(AppError):
    pass


class TransientFetchError(FetchError):
    def __init__(self, code: str, message: str = "source request temporarily failed") -> None:
        super().__init__(code, message, 503, True)


class LeaseLostError(TransientFetchError):
    def __init__(self) -> None:
        super().__init__("lease_lost", "acquisition lease ownership was lost")


class GovernanceLeaseLostError(AppError):
    def __init__(self) -> None:
        super().__init__("governance_lease_lost", "governance lease ownership was lost", 503, True)


class TopicSelectionLeaseLostError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "topic_selection_lease_lost",
            "topic selection lease ownership was lost",
            503,
            True,
        )


class BrandIngestionLeaseLostError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "brand_ingestion_lease_lost",
            "brand ingestion lease ownership was lost",
            503,
            True,
        )


class CopyGenerationLeaseLostError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "copy_generation_lease_lost",
            "copy generation lease ownership was lost",
            503,
            True,
        )


class BrandUploadRejectedError(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, 422)


class ProviderError(AppError):
    """Provider boundary failure with a stable, body-free public message."""


class ProviderInputLimitError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "provider_input_limit",
            "factual-analysis input exceeded the configured limit",
            422,
        )


class ProviderAuthenticationError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "provider_authentication_failed",
            "factual-analysis provider credentials were rejected",
            503,
        )


class ProviderRejectedError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "provider_request_rejected",
            "factual-analysis provider rejected the bounded request",
            422,
        )


class ProviderRateLimitError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "provider_rate_limited",
            "factual-analysis provider rate limit was exhausted",
            429,
            True,
        )


class ProviderTimeoutError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "provider_timeout",
            "factual-analysis provider timed out",
            503,
            True,
        )


class ProviderUnavailableError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "provider_unavailable",
            "factual-analysis provider is temporarily unavailable",
            503,
            True,
        )


class ProviderDimensionMismatchError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "provider_dimension_mismatch",
            "embedding provider returned an unexpected vector dimension",
            422,
        )


class ProviderIdentityMismatchError(ProviderError):
    def __init__(self) -> None:
        super().__init__(
            "provider_identity_mismatch",
            "provider result does not match the durable run identity",
            422,
        )


@dataclass(frozen=True, slots=True)
class ProviderValidationIssue:
    """Bounded, content-free structured-output validation diagnostic."""

    loc: tuple[str | int, ...]
    type: str


def normalize_provider_validation_issues(
    issues: Iterable[tuple[Sequence[object], object]],
) -> tuple[ProviderValidationIssue, ...]:
    normalized: list[ProviderValidationIssue] = []
    for raw_loc, raw_type in issues:
        if len(normalized) >= _PROVIDER_VALIDATION_ISSUE_LIMIT:
            break
        loc = tuple(
            _normalize_provider_validation_loc_segment(segment)
            for segment in raw_loc[:_PROVIDER_VALIDATION_LOC_DEPTH]
        )
        type_name = _normalize_provider_validation_token(
            raw_type if isinstance(raw_type, str) else "invalid",
            limit=_PROVIDER_VALIDATION_TYPE_LIMIT,
            fallback="invalid",
        )
        normalized.append(
            ProviderValidationIssue(
                loc=loc or ("root",),
                type=type_name,
            )
        )
    return tuple(normalized)


def provider_validation_issues_metadata(
    issues: Iterable[ProviderValidationIssue],
) -> list[dict[str, object]]:
    normalized = normalize_provider_validation_issues((issue.loc, issue.type) for issue in issues)
    return [
        {
            "loc": list(issue.loc),
            "type": issue.type,
        }
        for issue in normalized
    ]


def _normalize_provider_validation_loc_segment(value: object) -> str | int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(-1_000_000, min(value, 1_000_000))
    return _normalize_provider_validation_token(
        value if isinstance(value, str) else "unknown",
        limit=_PROVIDER_VALIDATION_LOC_SEGMENT_LIMIT,
        fallback="unknown",
    )


def _normalize_provider_validation_token(value: str, *, limit: int, fallback: str) -> str:
    normalized = _UNSAFE_PROVIDER_VALIDATION_TOKEN.sub("_", value.strip()).strip("_.-")
    return normalized[:limit] or fallback


class InvalidProviderOutputError(ProviderError):
    __slots__ = ("issue_codes", "validation_issues")

    def __init__(
        self,
        issue_codes: tuple[str, ...],
        *,
        validation_issues: tuple[ProviderValidationIssue, ...] = (),
    ) -> None:
        super().__init__(
            "invalid_provider_output",
            "factual-analysis provider returned invalid structured output",
            422,
        )
        self.issue_codes = issue_codes or ("invalid_schema",)
        self.validation_issues = normalize_provider_validation_issues(
            (issue.loc, issue.type) for issue in validation_issues
        )


class FactualAnalysisValidationError(AppError):
    __slots__ = ("issue_codes",)

    def __init__(self, issue_codes: tuple[str, ...]) -> None:
        super().__init__(
            "factual_analysis_validation_failed",
            "factual analysis failed deterministic validation",
            422,
        )
        self.issue_codes = issue_codes


class PermanentFetchError(FetchError):
    def __init__(self, code: str, message: str = "source request failed") -> None:
        super().__init__(code, message, 422)


class ResponseLimitError(PermanentFetchError):
    def __init__(self) -> None:
        super().__init__("response_too_large", "source response exceeded the configured limit")


class UnsupportedContentError(PermanentFetchError):
    def __init__(self) -> None:
        super().__init__("unsupported_content", "source response content type is unsupported")


class ParseError(AppError):
    def __init__(self, message: str = "source document could not be parsed") -> None:
        super().__init__("parse_failure", message, 422)
