"""Explicit, private, one-preview operator. The default preflight constructs no clients."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx

from app.application.services.official_account_visual_preview import (
    AUDIT_MODEL,
    GENERATION_MODEL,
    PreviewJournal,
    PreviewPlan,
    VisualPreviewError,
    execute_visual_preview,
    finalize_visual_preview,
    load_preview_input,
    plan_visual_preview,
    rerender_visual_preview,
    validate_preview_output_path,
)


class _JournalStream(httpx.AsyncByteStream):
    def __init__(
        self, stream: httpx.AsyncByteStream, journal: PreviewJournal, name: str, status: int
    ) -> None:
        self.stream = stream
        self.journal = journal
        self.name = name
        self.status = status
        self.finished = False
        self.received_bytes = 0

    def _finish(self, state: str) -> None:
        if not self.finished:
            self.journal.write_json(
                f"transport/{self.name}.result.json",
                {
                    "status": state,
                    "http_status": self.status,
                    "received_bytes": self.received_bytes,
                    "recorded_at": datetime.now(UTC).isoformat(),
                },
            )
            self.finished = True

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.stream:
                self.received_bytes += len(chunk)
                if self.received_bytes > 32 * 1024 * 1024:
                    raise VisualPreviewError("preview_response_too_large")
                yield chunk
            self._finish("response_complete")
        except BaseException:
            self._finish("response_incomplete_or_unknown")
            raise

    async def aclose(self) -> None:
        try:
            await self.stream.aclose()
        finally:
            self._finish("response_incomplete_or_unknown")


class PreviewJournalTransport(httpx.AsyncBaseTransport):
    """Journal every physical dispatch, including polling/download, without recording URLs.

    There is exactly one POST per active application intent. Polling is bounded separately;
    neither HTTP retries, redirects, proxy environment, nor a second charged POST is allowed.
    """

    def __init__(
        self,
        *,
        journal: PreviewJournal,
        inner: httpx.AsyncBaseTransport,
        kind: Literal["generation", "audit"],
        base_url: str,
    ) -> None:
        self.journal = journal
        self.inner = inner
        self.kind = kind
        self.base_url = httpx.URL(base_url.rstrip("/"))
        self.counts: dict[tuple[str, str], int] = {}
        self.sequence = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        active = self.journal.active_call
        if active is None or not active.startswith(f"{self.kind}-"):
            raise VisualPreviewError("preview_transport_without_intent")
        same_origin = (
            request.url.scheme == self.base_url.scheme
            and request.url.host == self.base_url.host
            and request.url.port == self.base_url.port
        )
        if request.url.scheme != "https" or request.url.userinfo or request.url.fragment:
            raise VisualPreviewError("preview_transport_route_invalid")
        if self.kind == "audit":
            if (
                request.method != "POST"
                or not same_origin
                or request.url.path != self.base_url.path.rstrip("/") + "/chat/completions"
                or request.url.query
            ):
                raise VisualPreviewError("preview_transport_route_invalid")
            operation = "audit"
            maximum = 1
        elif (
            request.method == "POST"
            and same_origin
            and request.url.path == "/v1/images/generations"
            and not request.url.query
        ):
            operation = "generation"
            maximum = 1
        elif (
            request.method == "GET"
            and same_origin
            and request.url.path.startswith("/v1/images/tasks/")
            and not request.url.query
        ):
            operation = "poll"
            maximum = 30
        elif request.method == "GET" and "authorization" not in request.headers:
            operation = "download"
            maximum = 1
        else:
            raise VisualPreviewError("preview_transport_route_invalid")
        counter_key = (active, operation)
        count = self.counts.get(counter_key, 0)
        if count >= maximum:
            raise VisualPreviewError("preview_transport_budget_exceeded")
        name = f"{self.kind}-{self.sequence:03d}"
        self.journal.write_json(
            f"transport/{name}.intent.json",
            {
                "call": active,
                "operation": operation,
                "attempt": 1,
                "recorded_at": datetime.now(UTC).isoformat(),
                "route_owner": "comfly" if self.kind == "generation" else "zhipu",
            },
        )
        self.counts[counter_key] = count + 1
        self.sequence += 1
        try:
            response = await self.inner.handle_async_request(request)
        except BaseException:
            self.journal.write_json(
                f"transport/{name}.result.json",
                {
                    "status": "dispatch_outcome_unknown",
                    "recorded_at": datetime.now(UTC).isoformat(),
                },
            )
            raise
        if not isinstance(response.stream, httpx.AsyncByteStream):
            raise VisualPreviewError("preview_transport_stream_invalid")
        response.stream = _JournalStream(response.stream, self.journal, name, response.status_code)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


async def _live(plan: PreviewPlan, *, output_dir: Path) -> dict[str, object]:
    validate_preview_output_path(output_dir)
    # Lazy infrastructure imports keep default input preflight independent of settings and DB.
    from pydantic_settings import SettingsConfigDict

    from app.core.config import Settings
    from app.infrastructure.ai.factory import create_image_generator
    from app.infrastructure.ai.image_validation import OpenAICompatibleImageQualityAuditor

    class PreviewSettings(Settings):
        # Keep inherited validation, while explicitly disabling ambient dotenv loading.
        model_config = SettingsConfigDict(env_file=None)

    settings = PreviewSettings()
    if (
        settings.image_provider_mode != "comfly"
        or settings.image_model != GENERATION_MODEL
        or settings.ai_provider_mode != "zhipu"
        or settings.comfly_api_key is None
        or not settings.comfly_api_key.get_secret_value().strip()
        or settings.ai_platform_api_key is None
        or not settings.ai_platform_api_key.get_secret_value().strip()
        or not settings.ai_platform_base_url
    ):
        raise VisualPreviewError("preview_credentials_or_route_unavailable")
    audit_url = httpx.URL(settings.ai_platform_base_url)
    if (
        audit_url.scheme != "https"
        or audit_url.host != "open.bigmodel.cn"
        or audit_url.path.rstrip("/") != "/api/paas/v4"
        or audit_url.query
        or audit_url.fragment
        or audit_url.userinfo
        or audit_url.port not in {None, 443}
    ):
        raise VisualPreviewError("preview_audit_route_invalid")
    # This copy belongs only to this standalone process; running worker configuration is untouched.
    bounded = settings.model_copy(
        update={
            "image_max_attempts": 1,
            "ai_max_attempts": 1,
            "image_provider_window_seconds": min(settings.image_provider_window_seconds, 360),
            "image_provider_timeout_seconds": min(settings.image_provider_timeout_seconds, 300),
        }
    )
    journal = PreviewJournal(output_dir, plan)
    generation_transport = PreviewJournalTransport(
        journal=journal,
        inner=httpx.AsyncHTTPTransport(retries=0, trust_env=False),
        kind="generation",
        base_url=settings.comfly_base_url,
    )
    audit_transport = PreviewJournalTransport(
        journal=journal,
        inner=httpx.AsyncHTTPTransport(retries=0, trust_env=False),
        kind="audit",
        base_url=settings.ai_platform_base_url,
    )
    async with (
        httpx.AsyncClient(
            transport=generation_transport, trust_env=False, follow_redirects=False
        ) as image_client,
        httpx.AsyncClient(
            transport=audit_transport, trust_env=False, follow_redirects=False
        ) as audit_client,
    ):
        generator = create_image_generator(bounded, client=image_client)
        auditor = OpenAICompatibleImageQualityAuditor(
            client=audit_client,
            base_url=settings.ai_platform_base_url,
            api_key=settings.ai_platform_api_key,
            model=AUDIT_MODEL,
            connect_timeout_seconds=min(settings.ai_connect_timeout_seconds, 30),
            read_timeout_seconds=120,
            total_timeout_seconds=180,
            concurrency=1,
            max_attempts=1,
            max_request_bytes=settings.image_max_request_bytes,
            max_response_bytes=min(settings.image_max_provider_response_bytes, 1024 * 1024),
        )
        return await execute_visual_preview(
            plan=plan, journal=journal, generator=generator, auditor=auditor
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--source-manifest-sha256")
    parser.add_argument("--output-dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--live",
        action="store_true",
        help="Authorize this one fresh preview's bounded provider calls",
    )
    mode.add_argument(
        "--rerender",
        action="store_true",
        help="Rebuild a completed preview in a fresh directory without providers",
    )
    mode.add_argument(
        "--finalize", action="store_true", help="Append exact browser evidence without providers"
    )
    parser.add_argument("--preview-dir", type=Path)
    parser.add_argument("--preview-manifest-sha256")
    parser.add_argument("--browser-report", type=Path)
    args = parser.parse_args(argv)
    # Standalone operator output is an allowlist, never an HTTP log or exception traceback.
    logging.disable(logging.CRITICAL)
    try:
        result: dict[str, object]
        if args.rerender or args.finalize:
            if args.preview_dir is None or args.preview_manifest_sha256 is None:
                raise VisualPreviewError("preview_identity_required")
            if args.rerender:
                if args.output_dir is None:
                    raise VisualPreviewError("preview_output_required")
                manifest = rerender_visual_preview(
                    source_dir=args.preview_dir,
                    manifest_sha256=args.preview_manifest_sha256,
                    output_dir=args.output_dir,
                )
                result = {
                    "status": "rendered",
                    "provider_calls": 0,
                    "content_fingerprint": manifest["content_fingerprint"],
                    "preview_accepted": False,
                }
            else:
                if args.browser_report is None:
                    raise VisualPreviewError("preview_browser_report_required")
                acceptance = finalize_visual_preview(
                    root=args.preview_dir,
                    manifest_sha256=args.preview_manifest_sha256,
                    report_path=args.browser_report,
                )
                result = {
                    "status": "finalized",
                    "provider_calls": 0,
                    "preview_accepted": acceptance["preview_accepted"],
                    "human_approved": False,
                }
        else:
            if args.source_dir is None or args.source_manifest_sha256 is None:
                raise VisualPreviewError("preview_source_required")
            source = load_preview_input(
                args.source_dir, manifest_sha256=args.source_manifest_sha256
            )
            plan = plan_visual_preview(source)
            if args.output_dir is not None:
                validate_preview_output_path(args.output_dir)
            if not args.live:
                result = {
                    "status": "preflight_passed",
                    "provider_calls": 0,
                    "scene_count": len(plan.scenes),
                    "source_manifest_sha256": source.manifest_sha256,
                }
            elif args.output_dir is None:
                raise VisualPreviewError("preview_output_required")
            else:
                manifest = asyncio.run(_live(plan, output_dir=args.output_dir))
                result = {
                    "status": "rendered",
                    "quality_gate_passed": manifest["quality_gate_passed"],
                    "preview_accepted": False,
                    "mobile_validation": "not_run",
                    "content_fingerprint": manifest["content_fingerprint"],
                }
    except Exception:
        print(json.dumps({"status": "failed", "code": "preview_failed_closed"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
