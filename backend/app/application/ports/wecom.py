"""Provider-neutral contracts for Enterprise WeChat delivery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

WECOM_MAX_IMAGE_BYTES = 10 * 1024 * 1024
WECOM_MIN_IMAGE_BYTES = 6
WECOM_MAX_RESPONSE_BYTES = 64 * 1024
WECOM_MAX_TEXT_BYTES = 2048
WECOM_DUPLICATE_CHECK_INTERVAL_SECONDS = 1_800

WECOM_TOKEN_INVALID = "wecom_token_invalid"
WECOM_RATE_LIMITED = "wecom_rate_limited"
WECOM_TRANSIENT = "wecom_transient"
WECOM_PROVIDER_REJECTED = "wecom_provider_rejected"
WECOM_DELIVERY_UNKNOWN = "wecom_delivery_unknown"
WECOM_INVALID_RESPONSE = "wecom_invalid_response"
WECOM_INVALID_INPUT = "wecom_invalid_input"


class WeComProviderError(Exception):
    """A body-free, stable failure projected from an Enterprise WeChat call."""

    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        unknown: bool = False,
        response_code: int | None = None,
        provider_request_id: str | None = None,
        message: str | None = None,
    ) -> None:
        if not code or len(code) > 80 or any(character.isspace() for character in code):
            raise ValueError("WeCom provider error code must be a bounded identifier")
        if response_code is not None and (
            isinstance(response_code, bool) or not isinstance(response_code, int)
        ):
            raise ValueError("WeCom provider response code must be an integer")
        self.code = code
        self.retryable = retryable
        self.unknown = unknown
        self.response_code = response_code
        self.provider_request_id = provider_request_id
        self.message = message or code
        super().__init__(self.message)

    @property
    def safe_response_code(self) -> int | None:
        """Compatibility name for persistence code that uses an explicit safe prefix."""

        return self.response_code


class WeComTokenInvalidError(WeComProviderError):
    """The access token or the credentials used to obtain it were rejected."""

    def __init__(
        self,
        *,
        response_code: int | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(
            WECOM_TOKEN_INVALID,
            response_code=response_code,
            provider_request_id=provider_request_id,
            message="Enterprise WeChat access token is invalid",
        )


class WeComRateLimitError(WeComProviderError):
    """Enterprise WeChat explicitly asked the caller to slow down."""

    def __init__(
        self,
        *,
        response_code: int | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(
            WECOM_RATE_LIMITED,
            retryable=True,
            response_code=response_code,
            provider_request_id=provider_request_id,
            message="Enterprise WeChat rate limit was reached",
        )


class WeComTransientError(WeComProviderError):
    """A bounded retryable provider or transport failure."""

    def __init__(
        self,
        *,
        response_code: int | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(
            WECOM_TRANSIENT,
            retryable=True,
            response_code=response_code,
            provider_request_id=provider_request_id,
            message="Enterprise WeChat is temporarily unavailable",
        )


class WeComProviderRejectedError(WeComProviderError):
    """A non-retryable provider rejection such as an invalid recipient."""

    def __init__(
        self,
        *,
        response_code: int | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(
            WECOM_PROVIDER_REJECTED,
            response_code=response_code,
            provider_request_id=provider_request_id,
            message="Enterprise WeChat rejected the request",
        )


class WeComUnknownTimeoutError(WeComProviderError):
    """A send did not finish, so the provider may already have accepted it."""

    def __init__(self, *, provider_request_id: str | None = None) -> None:
        super().__init__(
            WECOM_DELIVERY_UNKNOWN,
            unknown=True,
            provider_request_id=provider_request_id,
            message="Enterprise WeChat delivery outcome is unknown",
        )


class WeComInvalidResponseError(WeComProviderError):
    """The provider response was missing required bounded fields."""

    def __init__(self) -> None:
        super().__init__(
            WECOM_INVALID_RESPONSE,
            message="Enterprise WeChat returned an invalid response",
        )


class WeComInvalidInputError(WeComProviderError):
    """The application supplied an input outside the official API boundary."""

    def __init__(self) -> None:
        super().__init__(WECOM_INVALID_INPUT, message="Enterprise WeChat request input is invalid")


# Short aliases keep application imports readable while retaining explicit provider names.
WeComTimeoutError = WeComUnknownTimeoutError
WeComRejectedError = WeComProviderRejectedError


@dataclass(frozen=True, slots=True)
class UploadedMedia:
    """A temporary media reference kept in memory for one immediate send."""

    media_id: str = field(repr=False)
    provider_request_id: str | None = None
    response_code: int = 0

    @property
    def safe_response_code(self) -> str:
        return str(self.response_code)


@dataclass(frozen=True, slots=True)
class SendResult:
    """Safe projection of a successful text or image send."""

    provider_request_id: str | None = None
    response_code: int = 0

    @property
    def safe_response_code(self) -> str:
        return str(self.response_code)


class WeComApiClient(Protocol):
    """The application-facing Enterprise WeChat side-effect boundary."""

    async def upload_image(
        self, image_bytes: bytes, media_type: str, filename: str
    ) -> UploadedMedia: ...

    async def send_text(
        self,
        recipient_id: str,
        agent_id: int,
        content: str,
        request_fingerprint: str,
    ) -> SendResult: ...

    async def send_image(
        self,
        recipient_id: str,
        agent_id: int,
        media_id: str,
        request_fingerprint: str,
    ) -> SendResult: ...


__all__ = [
    "WECOM_DELIVERY_UNKNOWN",
    "WECOM_DUPLICATE_CHECK_INTERVAL_SECONDS",
    "WECOM_INVALID_INPUT",
    "WECOM_INVALID_RESPONSE",
    "WECOM_MAX_IMAGE_BYTES",
    "WECOM_MAX_RESPONSE_BYTES",
    "WECOM_MAX_TEXT_BYTES",
    "WECOM_MIN_IMAGE_BYTES",
    "WECOM_PROVIDER_REJECTED",
    "WECOM_RATE_LIMITED",
    "WECOM_TOKEN_INVALID",
    "WECOM_TRANSIENT",
    "SendResult",
    "UploadedMedia",
    "WeComApiClient",
    "WeComInvalidInputError",
    "WeComInvalidResponseError",
    "WeComProviderError",
    "WeComProviderRejectedError",
    "WeComRateLimitError",
    "WeComRejectedError",
    "WeComTimeoutError",
    "WeComTokenInvalidError",
    "WeComTransientError",
    "WeComUnknownTimeoutError",
]
