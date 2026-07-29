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
