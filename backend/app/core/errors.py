from __future__ import annotations

from dataclasses import dataclass


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


class InvalidProviderOutputError(ProviderError):
    __slots__ = ("issue_codes",)

    def __init__(self, issue_codes: tuple[str, ...]) -> None:
        super().__init__(
            "invalid_provider_output",
            "factual-analysis provider returned invalid structured output",
            422,
        )
        self.issue_codes = issue_codes or ("invalid_schema",)


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
