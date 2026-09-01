"""Provider-neutral contracts for the opt-in WeChat Official Account draft boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

WECHAT_MP_MAX_IMAGE_BYTES = 10 * 1024 * 1024
WECHAT_MP_MIN_IMAGE_BYTES = 8
WECHAT_MP_MAX_RESPONSE_BYTES = 64 * 1024
WECHAT_MP_MAX_INLINE_IMAGE_BYTES = 1024 * 1024 - 1
WECHAT_MP_MAX_THUMB_BYTES = 64 * 1024 - 1
WECHAT_MP_MAX_DRAFT_TITLE_CHARACTERS = 32
WECHAT_MP_MAX_DRAFT_AUTHOR_CHARACTERS = 16
WECHAT_MP_MAX_DRAFT_DIGEST_CHARACTERS = 120
WECHAT_MP_MAX_DRAFT_CONTENT_CHARACTERS = 20_000 - 1
WECHAT_MP_MAX_DRAFT_CONTENT_BYTES = 1024 * 1024 - 1
WECHAT_MP_MAX_CONTENT_SOURCE_URL_BYTES = 1024
WECHAT_MP_MAX_DRAFT_MEDIA_ID_CHARACTERS = 128

WeChatDraftRole = Literal["official_anchor", "industry_trend", "application_case"]
WeChatMpEndpoint = Literal[
    "stable_token",
    "media_uploadimg",
    "material_add_thumb",
    "draft_add",
]

WECHAT_MP_CONFIG_DISABLED = "wechat_mp_config_disabled"
WECHAT_MP_INVALID_INPUT = "wechat_mp_invalid_input"
WECHAT_MP_INVALID_RESPONSE = "wechat_mp_invalid_response"
WECHAT_MP_TOKEN_INVALID = "wechat_mp_token_invalid"
WECHAT_MP_RATE_LIMITED = "wechat_mp_rate_limited"
WECHAT_MP_TRANSIENT = "wechat_mp_transient"
WECHAT_MP_PROVIDER_REJECTED = "wechat_mp_provider_rejected"
WECHAT_MP_OUTCOME_UNKNOWN = "wechat_mp_outcome_unknown"
WECHAT_MP_DRAFT_PREPARATION_INVALID = "wechat_mp_draft_preparation_invalid"


class WeChatOfficialAccountError(Exception):
    """A stable, body-free failure safe to project into application diagnostics."""

    __slots__ = (
        "code",
        "endpoint",
        "provider_code",
        "retryable",
        "unknown",
    )

    def __init__(
        self,
        code: str,
        *,
        endpoint: WeChatMpEndpoint | None = None,
        provider_code: int | None = None,
        retryable: bool = False,
        unknown: bool = False,
        message: str | None = None,
    ) -> None:
        if not code or len(code) > 80 or any(character.isspace() for character in code):
            raise ValueError("WeChat Official Account error code must be a bounded identifier")
        if provider_code is not None and (
            isinstance(provider_code, bool) or not isinstance(provider_code, int)
        ):
            raise ValueError("WeChat Official Account provider code must be an integer")
        self.code = code
        self.endpoint = endpoint
        self.provider_code = provider_code
        self.retryable = retryable
        self.unknown = unknown
        super().__init__(message or code)


class WeChatMpConfigurationError(WeChatOfficialAccountError):
    def __init__(self) -> None:
        super().__init__(
            WECHAT_MP_CONFIG_DISABLED,
            message="WeChat Official Account draft adapter is not safely enabled",
        )


class WeChatMpInvalidInputError(WeChatOfficialAccountError):
    def __init__(self, *, endpoint: WeChatMpEndpoint | None = None) -> None:
        super().__init__(
            WECHAT_MP_INVALID_INPUT,
            endpoint=endpoint,
            message="WeChat Official Account request input is invalid",
        )


class WeChatMpDraftPreparationError(WeChatOfficialAccountError):
    def __init__(self) -> None:
        super().__init__(
            WECHAT_MP_DRAFT_PREPARATION_INVALID,
            message="WeChat Official Account draft preparation failed local validation",
        )


class WeChatMpInvalidResponseError(WeChatOfficialAccountError):
    def __init__(self, *, endpoint: WeChatMpEndpoint) -> None:
        super().__init__(
            WECHAT_MP_INVALID_RESPONSE,
            endpoint=endpoint,
            message=f"WeChat Official Account returned an invalid response at {endpoint}",
        )


class WeChatMpTokenInvalidError(WeChatOfficialAccountError):
    def __init__(self, *, endpoint: WeChatMpEndpoint, provider_code: int | None) -> None:
        super().__init__(
            WECHAT_MP_TOKEN_INVALID,
            endpoint=endpoint,
            provider_code=provider_code,
            message=f"WeChat Official Account access token is invalid at {endpoint}",
        )


class WeChatMpRateLimitError(WeChatOfficialAccountError):
    def __init__(self, *, endpoint: WeChatMpEndpoint, provider_code: int | None) -> None:
        super().__init__(
            WECHAT_MP_RATE_LIMITED,
            endpoint=endpoint,
            provider_code=provider_code,
            retryable=True,
            message=f"WeChat Official Account rate limit was reached at {endpoint}",
        )


class WeChatMpTransientError(WeChatOfficialAccountError):
    def __init__(self, *, endpoint: WeChatMpEndpoint, provider_code: int | None = None) -> None:
        super().__init__(
            WECHAT_MP_TRANSIENT,
            endpoint=endpoint,
            provider_code=provider_code,
            retryable=True,
            message=f"WeChat Official Account is temporarily unavailable at {endpoint}",
        )


class WeChatMpProviderRejectedError(WeChatOfficialAccountError):
    def __init__(self, *, endpoint: WeChatMpEndpoint, provider_code: int | None) -> None:
        super().__init__(
            WECHAT_MP_PROVIDER_REJECTED,
            endpoint=endpoint,
            provider_code=provider_code,
            message=f"WeChat Official Account rejected the request at {endpoint}",
        )


class WeChatMpOutcomeUnknownError(WeChatOfficialAccountError):
    def __init__(self, *, endpoint: WeChatMpEndpoint) -> None:
        super().__init__(
            WECHAT_MP_OUTCOME_UNKNOWN,
            endpoint=endpoint,
            unknown=True,
            message=f"WeChat Official Account request outcome is unknown at {endpoint}",
        )


@dataclass(frozen=True, slots=True)
class WeChatInlineImage:
    """HTTPS URL returned for one uploaded article-body image."""

    url: str


@dataclass(frozen=True, slots=True)
class WeChatThumbMedia:
    """Permanent thumb material used immediately by one draft request."""

    media_id: str


@dataclass(frozen=True, slots=True)
class WeChatDraftArticleRequest:
    """Exactly one article accepted by the application-facing draft port."""

    title: str
    author: str
    digest: str
    content: str
    content_source_url: str | None
    thumb_media_id: str
    need_open_comment: bool
    only_fans_can_comment: bool


@dataclass(frozen=True, slots=True)
class WeChatDraftCreated:
    """Provider result retained only long enough to form the safe application receipt."""

    media_id: str


@dataclass(frozen=True, slots=True)
class WeChatDraftReceipt:
    """Safe draft-only result; it never represents publication or homepage pinning."""

    role: WeChatDraftRole
    article_fingerprint: str
    content_fingerprint: str
    draft_media_id: str
    uploaded_image_count: int
    created_at: datetime
    mode: Literal["draft_only"] = "draft_only"
    not_published: Literal[True] = True


class WeChatOfficialAccountDraftClient(Protocol):
    """Only the three write operations required to create one independent draft."""

    async def upload_inline_image(
        self,
        image_bytes: bytes,
        media_type: str,
        filename: str,
    ) -> WeChatInlineImage: ...

    async def upload_thumb(
        self,
        image_bytes: bytes,
        media_type: str,
        filename: str,
    ) -> WeChatThumbMedia: ...

    async def add_draft(self, article: WeChatDraftArticleRequest) -> WeChatDraftCreated: ...


__all__ = [
    "WECHAT_MP_CONFIG_DISABLED",
    "WECHAT_MP_DRAFT_PREPARATION_INVALID",
    "WECHAT_MP_INVALID_INPUT",
    "WECHAT_MP_INVALID_RESPONSE",
    "WECHAT_MP_MAX_CONTENT_SOURCE_URL_BYTES",
    "WECHAT_MP_MAX_DRAFT_AUTHOR_CHARACTERS",
    "WECHAT_MP_MAX_DRAFT_CONTENT_BYTES",
    "WECHAT_MP_MAX_DRAFT_CONTENT_CHARACTERS",
    "WECHAT_MP_MAX_DRAFT_DIGEST_CHARACTERS",
    "WECHAT_MP_MAX_DRAFT_MEDIA_ID_CHARACTERS",
    "WECHAT_MP_MAX_DRAFT_TITLE_CHARACTERS",
    "WECHAT_MP_MAX_IMAGE_BYTES",
    "WECHAT_MP_MAX_INLINE_IMAGE_BYTES",
    "WECHAT_MP_MAX_RESPONSE_BYTES",
    "WECHAT_MP_MAX_THUMB_BYTES",
    "WECHAT_MP_MIN_IMAGE_BYTES",
    "WECHAT_MP_OUTCOME_UNKNOWN",
    "WECHAT_MP_PROVIDER_REJECTED",
    "WECHAT_MP_RATE_LIMITED",
    "WECHAT_MP_TOKEN_INVALID",
    "WECHAT_MP_TRANSIENT",
    "WeChatDraftArticleRequest",
    "WeChatDraftCreated",
    "WeChatDraftReceipt",
    "WeChatDraftRole",
    "WeChatInlineImage",
    "WeChatMpConfigurationError",
    "WeChatMpDraftPreparationError",
    "WeChatMpEndpoint",
    "WeChatMpInvalidInputError",
    "WeChatMpInvalidResponseError",
    "WeChatMpOutcomeUnknownError",
    "WeChatMpProviderRejectedError",
    "WeChatMpRateLimitError",
    "WeChatMpTokenInvalidError",
    "WeChatMpTransientError",
    "WeChatOfficialAccountDraftClient",
    "WeChatOfficialAccountError",
    "WeChatThumbMedia",
]
