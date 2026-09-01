from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from app.application.services.official_account_weekly_edition import (
    WEEKLY_EDITION_LIVE_PROVENANCE_REQUIRED,
    WeeklyEditionLiveProvenanceError,
    load_finalized_weekly_edition,
    write_weekly_edition_artifact,
)
from app.core.config import Settings
from app.infrastructure.ingestion.fetcher import SafeHttpFetcher
from app.infrastructure.ingestion.source_image_fetcher import SafeSourceImageFetcher
from app.infrastructure.wechat_official_account.artifacts import (
    LocalWeChatDraftArtifactStore,
)
from app.official_account_weekly_edition_demo import fixture_mobile_validation
from app.official_account_weekly_edition_live_demo import (
    build_live_weekly_edition_artifact,
    load_live_weekly_input,
)
from tests.unit.test_official_account_weekly_edition_live import (
    _INPUT,
    _image_bytes,
    _page,
    _public_resolver,
)


async def _live_weekly_directory(output_root: Path) -> Path:
    live_input = load_live_weekly_input(_INPUT)
    image_payloads = {
        live_input.articles[0].preferred_image_urls[0]: (
            "image/jpeg",
            _image_bytes("image/jpeg", (20, 86, 122)),
        ),
        live_input.articles[1].preferred_image_urls[0]: (
            "image/jpeg",
            _image_bytes("image/jpeg", (43, 92, 170)),
        ),
        live_input.articles[2].preferred_image_urls[0]: (
            "image/png",
            _image_bytes("image/png", (25, 135, 113)),
        ),
    }
    selectors = (".TRS_UEDITOR", "#detail", "#detail")
    page_payloads = {
        item.url: _page(
            item.expected_title,
            item.expected_published_date.isoformat(),
            item.preferred_image_urls[0],
            selector=selector,
            lead_sentence=(
                "南京人工智能智能终端消费中心展示多种可体验的应用场景。"
                if item.role == "application_case"
                else ""
            ),
        )
        for item, selector in zip(live_input.articles, selectors, strict=True)
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in page_payloads:
            return httpx.Response(
                200,
                headers={"Content-Type": "text/html; charset=utf-8"},
                content=page_payloads[url],
            )
        media_type, body = image_payloads[url]
        return httpx.Response(200, headers={"Content-Type": media_type}, content=body)

    transport = httpx.MockTransport(handler)
    artifact = await build_live_weekly_edition_artifact(
        live_input,
        page_fetcher=SafeHttpFetcher(
            Settings(),
            resolver=_public_resolver,
            transport=transport,
        ),
        image_fetcher=SafeSourceImageFetcher(
            Settings(),
            resolver=_public_resolver,
            transport=transport,
        ),
        mobile_validation_factory=fixture_mobile_validation,
    )
    return write_weekly_edition_artifact(artifact, output_root)


@pytest.mark.asyncio
async def test_live_loader_stages_resolves_and_discovers_only_opaque_sources(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    source = await _live_weekly_directory(inbox)
    loaded = load_finalized_weekly_edition(source)
    assert loaded.live_acquisition_audit_version.endswith(("v2", "v3"))
    assert len(loaded.children) == 3

    store = LocalWeChatDraftArtifactStore(
        inbox_root=inbox,
        staging_root=tmp_path / "staged",
    )
    batch = store.stage_weekly(source)
    assert store.stage_weekly(source) == batch
    assert batch.batch_fingerprint == loaded.batch_fingerprint
    assert batch.aggregate_fingerprint == loaded.zip_sha256
    assert [source.role for source in batch.sources] == [
        "official_anchor",
        "industry_trend",
        "application_case",
    ]
    assert all(
        source.source_ref.startswith(f"wechat-draft-v1:{loaded.zip_sha256}:")
        and str(tmp_path) not in source.source_ref
        for source in batch.sources
    )

    resolved = tuple(store.resolve(source.source_ref) for source in batch.sources)
    assert [item.source.article_fingerprint for item in resolved] == [
        source.article_fingerprint for source in batch.sources
    ]
    assert all(item.directory.is_dir() and str(tmp_path) not in repr(item) for item in resolved)
    discovery = store.discover_weekly()
    assert discovery.batches == (batch,)
    assert discovery.skipped_by_code == {}

    with pytest.raises(ValueError, match="artifact resolution failed"):
        store.resolve("wechat-draft-v1:not-a-sha:official_anchor")

    index_path = source / "weekly-index.json"
    index_path.write_bytes(index_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="size changed"):
        load_finalized_weekly_edition(source)


@pytest.mark.asyncio
async def test_loader_rejects_fixture_and_discovery_reports_same_safe_code(
    tmp_path: Path,
) -> None:
    from app.application.services.official_account_weekly_edition import (
        bind_weekly_child,
        build_weekly_edition_artifact,
        finalized_v2_child_from_artifact,
    )
    from app.domain.official_account_weekly_edition import (
        WeeklyArticleRole,
        WeeklyEditionSchedule,
    )
    from app.official_account_weekly_edition_demo import (
        build_fixture_children,
        build_fixture_selection,
    )

    staged = await build_fixture_children()
    reports = {
        role: fixture_mobile_validation(artifact)
        for role, artifact in zip(WeeklyArticleRole, staged, strict=True)
    }
    finalized = await build_fixture_children(browser_validations=reports)
    selection = build_fixture_selection()
    children = tuple(
        finalized_v2_child_from_artifact(artifact, role=role)
        for role, artifact in zip(WeeklyArticleRole, finalized, strict=True)
    )
    bindings = tuple(
        bind_weekly_child(selected=selected, child=child)
        for selected, child in zip(selection.selected, children, strict=True)
    )
    artifact = build_weekly_edition_artifact(
        selection=selection,
        schedule=WeeklyEditionSchedule(),
        children=children,
        bindings=bindings,
    )
    inbox = tmp_path / "inbox"
    source = write_weekly_edition_artifact(artifact, inbox)
    with pytest.raises(WeeklyEditionLiveProvenanceError) as captured:
        load_finalized_weekly_edition(source)
    assert captured.value.code == WEEKLY_EDITION_LIVE_PROVENANCE_REQUIRED

    store = LocalWeChatDraftArtifactStore(
        inbox_root=inbox,
        staging_root=tmp_path / "staged",
    )
    discovery = store.discover_weekly()
    assert discovery.batches == ()
    assert discovery.skipped_by_code == {WEEKLY_EDITION_LIVE_PROVENANCE_REQUIRED: 1}
    with pytest.raises(WeeklyEditionLiveProvenanceError):
        store.stage_weekly(source)
