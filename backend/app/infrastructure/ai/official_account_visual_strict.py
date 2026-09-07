"""Lazy one-shot clients for durable strict visual intents, never the legacy observer.

The application calls these adapters only after its fenced intent transaction has committed.
One fresh transport belongs to one logical call, so configured general retries cannot multiply
POSTs. Process recovery and cross-process no-replay remain the durable repository's authority.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import httpx

from app.application.ports.image_generation import ImageGenerationRequest, ImageGenerationResult
from app.application.ports.image_validation import ImageQualityAuditRequest, ImageQualityAuditResult
from app.core.config import Settings
from app.core.errors import ProviderIdentityMismatchError
from app.domain.official_account_visual_pipeline import STRICT_VISUAL_POLICY
from app.infrastructure.ai.factory import create_image_generator
from app.infrastructure.ai.image_validation import OpenAICompatibleImageQualityAuditor


def _new_transport() -> httpx.AsyncBaseTransport:
    return httpx.AsyncHTTPTransport(retries=0, trust_env=False)


class StrictVisualOneShotTransport(httpx.AsyncBaseTransport):
    """A physical dispatch fence; counts are consumed before forwarding, even on timeout."""

    def __init__(
        self,
        *,
        inner: httpx.AsyncBaseTransport,
        kind: Literal["generation", "audit"],
        base_url: str,
    ) -> None:
        self._inner = inner
        self._kind = kind
        self._base = httpx.URL(base_url)
        self._counts: dict[str, int] = {}
        if kind == "audit" and base_url != STRICT_VISUAL_POLICY.audit_base_url:
            raise ValueError("strict visual audit route is invalid")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        same_origin = (
            request.url.scheme == self._base.scheme
            and request.url.host == self._base.host
            and request.url.port == self._base.port
        )
        if request.url.scheme != "https" or request.url.userinfo or request.url.fragment:
            raise ValueError("strict visual transport route is invalid")
        if self._kind == "audit":
            if request.method != "POST" or str(request.url) != STRICT_VISUAL_POLICY.audit_endpoint:
                raise ValueError("strict visual audit route is invalid")
            operation, maximum = "post", 1
        elif (
            request.method == "POST"
            and same_origin
            and request.url.path == "/v1/images/generations"
            and not request.url.query
        ):
            operation, maximum = "post", 1
        elif (
            request.method == "GET"
            and same_origin
            and request.url.path.startswith("/v1/images/tasks/")
            and not request.url.query
            and self._counts.get("post") == 1
        ):
            operation, maximum = "poll", 30
        elif (
            request.method == "GET"
            and "authorization" not in request.headers
            and self._counts.get("post") == 1
        ):
            # The image adapter additionally verifies public DNS, size/signature and native pixels.
            operation, maximum = "download", 1
        else:
            raise ValueError("strict visual transport route is invalid")
        count = self._counts.get(operation, 0)
        if count >= maximum:
            raise ValueError("strict visual physical dispatch budget exceeded")
        self._counts[operation] = count + 1
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


class LazyStrictOfficialAccountImageGenerator:
    def __init__(
        self,
        settings: Settings,
        *,
        transport_factory: Callable[[], httpx.AsyncBaseTransport] = _new_transport,
    ) -> None:
        self._settings = settings
        self._transport_factory = transport_factory

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        settings = self._settings
        if (
            settings.image_provider_mode != STRICT_VISUAL_POLICY.generation_provider
            or settings.image_model != STRICT_VISUAL_POLICY.generation_model
            or request.output_size != STRICT_VISUAL_POLICY.output_size
            or not request.references
            or settings.comfly_api_key is None
            or not settings.comfly_api_key.get_secret_value().strip()
        ):
            raise ValueError("strict visual generation policy is unavailable")
        transport = StrictVisualOneShotTransport(
            inner=self._transport_factory(), kind="generation", base_url=settings.comfly_base_url
        )
        async with httpx.AsyncClient(
            transport=transport, follow_redirects=False, trust_env=False
        ) as client:
            bounded = settings.model_copy(
                update={
                    "image_max_attempts": 1,
                    "image_provider_window_seconds": min(
                        settings.image_provider_window_seconds, 360
                    ),
                    "image_provider_timeout_seconds": min(
                        settings.image_provider_timeout_seconds, 300
                    ),
                }
            )
            result = await create_image_generator(bounded, client=client).generate(request)
        if (
            result.provider != STRICT_VISUAL_POLICY.generation_provider
            or result.model != STRICT_VISUAL_POLICY.generation_model
            or result.request_fingerprint != request.request_fingerprint
            or result.attempts != 1
        ):
            raise ProviderIdentityMismatchError()
        return result


class LazyStrictOfficialAccountImageQualityAuditor:
    def __init__(
        self,
        settings: Settings,
        *,
        transport_factory: Callable[[], httpx.AsyncBaseTransport] = _new_transport,
    ) -> None:
        self._settings = settings
        self._transport_factory = transport_factory

    async def audit(self, request: ImageQualityAuditRequest) -> ImageQualityAuditResult:
        settings = self._settings
        if (
            settings.ai_provider_mode != "zhipu"
            or settings.ai_platform_base_url != STRICT_VISUAL_POLICY.audit_base_url
            or settings.image_quality_audit_model != STRICT_VISUAL_POLICY.audit_model
            or settings.ai_platform_api_key is None
            or not settings.ai_platform_api_key.get_secret_value().strip()
            or request.media_type != "image/jpeg"
            or not request.references
            or request.rubric_version != STRICT_VISUAL_POLICY.audit_rubric_version
        ):
            raise ValueError("strict visual audit policy is unavailable")
        transport = StrictVisualOneShotTransport(
            inner=self._transport_factory(),
            kind="audit",
            base_url=STRICT_VISUAL_POLICY.audit_base_url,
        )
        async with httpx.AsyncClient(
            transport=transport, follow_redirects=False, trust_env=False
        ) as client:
            adapter = OpenAICompatibleImageQualityAuditor(
                client=client,
                base_url=STRICT_VISUAL_POLICY.audit_base_url,
                api_key=settings.ai_platform_api_key,
                model=STRICT_VISUAL_POLICY.audit_model,
                connect_timeout_seconds=min(settings.ai_connect_timeout_seconds, 30),
                read_timeout_seconds=120,
                total_timeout_seconds=180,
                concurrency=1,
                max_attempts=1,
                max_request_bytes=settings.image_max_request_bytes,
                max_response_bytes=min(settings.image_max_provider_response_bytes, 1024 * 1024),
            )
            return await adapter.audit(request)
