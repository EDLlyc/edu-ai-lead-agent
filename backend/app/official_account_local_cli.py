from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.official_account_local import (
    OfficialAccountMediaResult,
    OfficialAccountVersionIdentity,
)
from app.application.services.official_account_export import (
    ReviewBundleInput,
    export_fixture_review_bundle,
    export_live_local_review_bundle,
)
from app.core.config import Settings, get_settings
from app.domain.official_account_local import OFFICIAL_ACCOUNT_FIXTURE_ID
from app.infrastructure.db.models import (
    OfficialAccountArticleRunModel,
    OfficialAccountLocalMediaModel,
)
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.official_account_media import (
    OfficialAccountLocalMediaResolver,
    OfficialAccountMediaIntegrityError,
    persisted_media_snapshot,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore

_TERMINAL_STATUSES = frozenset({"review_required", "ready", "failed", "result_unknown"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Operate the local official-account simulation without social-platform I/O."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    fixture = subparsers.add_parser("fixture", help="enqueue the offline fixture idempotently")
    fixture.add_argument("--wait-seconds", type=int, default=180)
    live = subparsers.add_parser("live", help="enqueue one explicit live model run")
    live.add_argument("--material-package-id", required=True, type=UUID)
    live.add_argument("--wait-seconds", type=int, default=600)
    export = subparsers.add_parser(
        "export",
        help="export one ready fixture run as a local manual-review bundle",
    )
    export.add_argument("--run-id", required=True, type=UUID)
    export.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/official-account-local"),
    )
    export.add_argument(
        "--mode",
        choices=("review", "copy-ready"),
        default="review",
        help="copy-ready requires an immutable approved manual review",
    )
    export.add_argument(
        "--allow-live-local-export",
        action="store_true",
        help=(
            "explicitly export one ready simulated live run for LOCAL ONLY review; "
            "it never contacts WeChat, WeCom, a worker, or a model provider"
        ),
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.official_account_local_enabled:
        raise RuntimeError("OFFICIAL_ACCOUNT_LOCAL_ENABLED=true is required")
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    repository = PostgresOfficialAccountRepository(session_factory)
    try:
        if args.command == "export":
            return await _export_fixture_review_bundle(
                repository,
                run_id=args.run_id,
                output_directory=args.output_dir,
                mode=args.mode,
                allow_live_local_export=bool(args.allow_live_local_export),
                session_factory=session_factory,
                settings=settings,
            )
        if args.command == "fixture":
            run, created = await repository.enqueue_fixture(
                identity=_identity(settings, provider="fake", model="official-account-fixture-v1")
            )
        elif args.command == "live":
            if settings.ai_provider_mode != "zhipu":
                raise RuntimeError("live smoke requires AI_PROVIDER_MODE=zhipu")
            run, created = await repository.enqueue_material_package(
                material_package_id=args.material_package_id,
                identity=_identity(
                    settings,
                    provider="zhipu",
                    model=settings.ai_chat_model,
                ),
            )
        else:
            raise RuntimeError("unsupported official-account local command")
        completed = await _wait_for_terminal(
            repository,
            run_id=run.id,
            wait_seconds=max(1, min(int(args.wait_seconds), 1_800)),
        )
        article = await repository.get_article(run.id)
        summary = {
            "run_id": str(completed.id),
            "created": created,
            "generation_mode": completed.generation_mode,
            "provider": completed.provider,
            "model": completed.model,
            "status": completed.status,
            "current_stage": completed.current_stage,
            "attempt_count": completed.attempt_count,
            "error_code": completed.error_code,
            "usage": {
                "prompt_tokens": article.prompt_tokens if article is not None else 0,
                "completion_tokens": article.completion_tokens if article is not None else 0,
                "reasoning_tokens": article.reasoning_tokens if article is not None else 0,
                "latency_ms": article.latency_ms if article is not None else 0,
            },
            "simulation": True,
            "browser_url": os.environ.get(
                "OFFICIAL_ACCOUNT_LOCAL_BROWSER_URL", "http://127.0.0.1:5173"
            ),
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if completed.status in {"ready", "review_required"} else 2
    finally:
        await engine.dispose()


async def _export_fixture_review_bundle(
    repository: PostgresOfficialAccountRepository,
    *,
    run_id: UUID,
    output_directory: Path,
    mode: Literal["review", "copy-ready"],
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    allow_live_local_export: bool = False,
) -> int:
    run = await repository.get_run(run_id)
    is_fixture = run.fixture_id == OFFICIAL_ACCOUNT_FIXTURE_ID
    if not is_fixture and not allow_live_local_export:
        raise ValueError("local export accepts sanitized fixture runs only")
    if not is_fixture and mode != "review":
        raise ValueError("live-local export only supports review mode")
    article = await repository.get_article(run_id)
    render = await repository.get_render(run_id)
    draft = await repository.get_draft(run_id)
    body_items = await repository.list_media(run_id, "body")
    context_items = await repository.list_media(run_id, "context")
    cover = await repository.get_media(run_id, "cover")
    manual_review = await repository.get_manual_review(run_id)
    if article is None or render is None or draft is None or not body_items or cover is None:
        raise ValueError("ready fixture run is missing a required immutable artifact")
    body_results = tuple(result for _media_id, result in body_items)
    context_results = tuple(result for _media_id, result in context_items)
    body_result = body_results[0]
    _, cover_result = cover
    body_bytes_items, context_bytes_items, cover_bytes = await _read_verified_export_media(
        session_factory=session_factory,
        settings=settings,
        run_id=run_id,
        body_results=body_results,
        context_results=context_results,
        cover_result=cover_result,
    )
    bundle = ReviewBundleInput(
        run_id=run.id,
        run_status=run.status,
        request_fingerprint=run.request_fingerprint,
        generation_mode=run.generation_mode,
        simulation=bool(draft.simulation),
        article=article.article,
        validation_issues=article.validation_issues,
        audit=article.audit,
        resolved_html=draft.resolved_html,
        draft_request_fingerprint=draft.request_fingerprint,
        resolved_fingerprint=draft.resolved_fingerprint,
        render_fingerprint=render.render_fingerprint,
        body_media=body_result,
        cover_media=cover_result,
        body_bytes=body_bytes_items[0],
        cover_bytes=cover_bytes,
        body_media_items=body_results,
        body_bytes_items=body_bytes_items,
        context_media_items=context_results,
        context_bytes_items=context_bytes_items,
        manual_review=manual_review,
    )
    result = await asyncio.to_thread(
        export_fixture_review_bundle if is_fixture else export_live_local_review_bundle,
        bundle,
        output_directory=output_directory,
        **({"mode": mode} if is_fixture else {}),
    )
    print(
        json.dumps(
            {
                "run_id": str(run.id),
                "bundle_directory": str(result.bundle_directory),
                "zip_path": str(result.zip_path),
                "zip_sha256": result.zip_sha256,
                "manifest_path": str(result.manifest_path),
                "reused": result.reused,
                "preflight_passed": result.preflight.passed,
                "manual_review_status": (
                    manual_review.decision if manual_review is not None else "pending"
                ),
                "editorially_approved": mode == "copy-ready" if is_fixture else False,
                "copy_ready": mode == "copy-ready" if is_fixture else False,
                "simulation": True,
                "boundary_label": (
                    "COPY-READY · 本地模拟 · 未同步公众号"
                    if mode == "copy-ready"
                    else "LOCAL ONLY · 未同步公众号"
                    if not is_fixture
                    else "NOT READY FOR PUBLICATION · 未同步公众号"
                ),
                "export_scope": "fixture" if is_fixture else "live_local",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.preflight.passed else 2


async def _read_verified_export_media(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    run_id: UUID,
    body_results: tuple[OfficialAccountMediaResult, ...],
    context_results: tuple[OfficialAccountMediaResult, ...],
    cover_result: OfficialAccountMediaResult,
) -> tuple[tuple[bytes, ...], tuple[bytes, ...], bytes]:
    """Read persisted media through the API's shared integrity boundary only."""

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(OfficialAccountLocalMediaModel)
                .where(
                    OfficialAccountLocalMediaModel.run_id == run_id,
                    OfficialAccountLocalMediaModel.status == "ready",
                )
                .order_by(
                    OfficialAccountLocalMediaModel.role,
                    OfficialAccountLocalMediaModel.ordinal,
                )
            )
        ).all()
        by_id = {row.local_media_id: persisted_media_snapshot(row) for row in rows}
        expected = (*body_results, *context_results, cover_result)
        if any(result.local_media_id not in by_id for result in expected):
            raise ValueError("ready run media rows are incomplete")
        resolver = OfficialAccountLocalMediaResolver(
            image_asset_manifest=_resolve_local_manifest_path(settings.image_asset_manifest),
            image_store=(
                MinioImageStore(settings)
                if any(
                    row.source_image_artifact_id is not None or row.generated_visual_id is not None
                    for row in by_id.values()
                )
                else None
            ),
            snapshot_store=(
                MinioSnapshotStore(settings)
                if any(row.source_article_image_id is not None for row in by_id.values())
                else None
            ),
        )
        payloads: list[bytes] = []
        for result in expected:
            media = by_id[result.local_media_id]
            if (
                media.role != result.role
                or media.ordinal != result.ordinal
                or media.media_type != result.media_type
                or media.byte_size != result.byte_size
                or media.sha256 != result.sha256
            ):
                raise ValueError("ready run media metadata changed during export")
            try:
                payloads.append(await resolver.read_verified_bytes(session=session, media=media))
            except OfficialAccountMediaIntegrityError as error:
                raise ValueError("ready run media integrity check failed") from error
    body_count = len(body_results)
    context_count = len(context_results)
    return (
        tuple(payloads[:body_count]),
        tuple(payloads[body_count : body_count + context_count]),
        payloads[-1],
    )


def _resolve_local_manifest_path(configured_path: str | None) -> str | None:
    """Keep the documented ``cd backend`` CLI invocation compatible with root-relative config."""

    if not configured_path:
        return None
    configured = Path(configured_path)
    if configured.is_absolute() or configured.exists():
        return str(configured)
    repository_relative = Path(__file__).resolve().parents[2] / configured
    return str(repository_relative) if repository_relative.exists() else configured_path


async def _wait_for_terminal(
    repository: PostgresOfficialAccountRepository,
    *,
    run_id: UUID,
    wait_seconds: int,
) -> OfficialAccountArticleRunModel:
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        run = await repository.get_run(run_id)
        if run.status in _TERMINAL_STATUSES:
            return run
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("official-account local run did not reach a terminal state")
        await asyncio.sleep(1)


def _identity(
    settings: Settings,
    *,
    provider: Literal["fake", "zhipu"],
    model: str,
) -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider=provider,
        model=model,
        generator_prompt_version=settings.official_account_local_generator_prompt_version,
        article_schema_version=settings.official_account_local_article_schema_version,
        media_plan_version=settings.official_account_local_media_plan_version,
        auditor_prompt_version=settings.official_account_local_auditor_prompt_version,
        audit_schema_version=settings.official_account_local_audit_schema_version,
        rule_version=settings.official_account_local_rule_version,
        renderer_version=settings.official_account_local_renderer_version,
        style_version=settings.official_account_local_style_version,
        template_version=settings.official_account_local_template_version,
        local_adapter_version=settings.official_account_local_adapter_version,
        default_author=settings.official_account_local_default_author,
        min_characters=settings.official_account_local_min_characters,
        target_min_characters=settings.official_account_local_target_min_characters,
        target_max_characters=settings.official_account_local_target_max_characters,
        max_characters=settings.official_account_local_max_characters,
        visual_query_version=settings.official_account_local_visual_query_version,
        visual_selector_version=settings.official_account_local_visual_selector_version,
        context_media_plan_version=settings.official_account_local_context_media_plan_version,
        generated_visual_plan_version=(
            settings.official_account_local_generated_visual_plan_version
            if provider == "zhipu" and settings.official_account_local_generated_visuals_enabled
            else None
        ),
        generated_visual_prompt_version=(
            settings.official_account_local_generated_visual_prompt_version
            if provider == "zhipu" and settings.official_account_local_generated_visuals_enabled
            else None
        ),
    )


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))


if __name__ == "__main__":
    main()
