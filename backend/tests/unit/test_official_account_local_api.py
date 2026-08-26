from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in the boundary assertion.
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from app.api.v1.routes.official_account_local import (
    _media_selection,
    capabilities,
    preview_local_draft,
    read_local_media,
    record_manual_review,
)
from app.api_main import app
from app.application.ports.official_account_local import StoredOfficialAccountManualReview
from app.domain.official_account_local import OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION
from app.infrastructure.official_account_local import (
    FIXTURE_BODY_IMAGE_BYTE_SIZES,
    FIXTURE_BODY_IMAGE_SHA256S,
    FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
    FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
    FIXTURE_BODY_PUBLICATION_SHA256S,
    FIXTURE_COVER_BYTE_SIZE,
    FIXTURE_COVER_MEDIA_TYPE,
    FIXTURE_COVER_PUBLICATION_BYTE_SIZE,
    FIXTURE_COVER_PUBLICATION_MEDIA_TYPE,
    FIXTURE_COVER_PUBLICATION_SHA256,
    FIXTURE_COVER_SHA256,
    FIXTURE_IMAGE_BYTE_SIZE,
    FIXTURE_IMAGE_MEDIA_TYPE,
    FIXTURE_IMAGE_SHA256,
)
from app.schemas.official_account_local import (
    OfficialAccountManualReviewRequest,
    OfficialAccountMediaResponse,
)
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


class _NoQuerySession:
    async def execute(self, _statement: object) -> object:
        raise AssertionError("disabled capabilities must not query the database")


class _ScalarSession:
    def __init__(self, value: object) -> None:
        self._value = value

    async def scalar(self, _statement: object) -> object:
        return self._value

    async def get(self, _model: object, _identifier: object) -> object:
        raise AssertionError("fixture media must not load a stored image")


def _request(*, enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    official_account_local_enabled=enabled,
                    ai_provider_mode="disabled",
                    ai_platform_base_url=None,
                    ai_platform_api_key=None,
                )
            )
        )
    )


@pytest.mark.asyncio
async def test_capabilities_fail_closed_without_querying_when_disabled() -> None:
    result = await capabilities(
        cast(Request, _request(enabled=False)),
        cast(AsyncSession, _NoQuerySession()),
    )

    assert result.enabled is False
    assert result.fixture_available is False
    assert result.live_available is False
    assert result.simulation is True
    assert result.boundary_label == "本地模拟，未同步公众号"


@pytest.mark.asyncio
async def test_preview_uses_fixed_document_and_strict_security_headers() -> None:
    draft = SimpleNamespace(
        resolved_html='<section><p style="color:#123">escaped article</p></section>'
    )
    response = await preview_local_draft(
        "local-draft-safe",
        cast(Request, _request(enabled=True)),
        cast(AsyncSession, _ScalarSession(draft)),
    )

    assert response.media_type == "text/html"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "img-src 'self'" in csp
    assert "form-action 'none'" in csp
    assert b"escaped article" in response.body


@pytest.mark.asyncio
async def test_fixture_media_is_read_locally_and_checksum_revalidated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_inline(function: Callable[..., object], *args: object) -> object:
        return function(*args)

    monkeypatch.setattr(
        "app.infrastructure.official_account_media.asyncio.to_thread",
        run_inline,
    )
    media = SimpleNamespace(
        local_media_id="local-media-body-safe",
        fixture_id="official-account-article-v1",
        source_image_artifact_id=None,
        role="body",
        ordinal=0,
        media_type=FIXTURE_IMAGE_MEDIA_TYPE,
        byte_size=FIXTURE_IMAGE_BYTE_SIZE,
        sha256=FIXTURE_IMAGE_SHA256,
    )
    response = await read_local_media(
        "local-media-body-safe",
        cast(Request, _request(enabled=True)),
        cast(AsyncSession, _ScalarSession(media)),
    )

    assert response.media_type == "image/png"
    assert len(response.body) == FIXTURE_IMAGE_BYTE_SIZE
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"

    cover_media = SimpleNamespace(
        local_media_id="local-media-cover-safe",
        fixture_id="official-account-article-v1",
        source_image_artifact_id=None,
        role="cover",
        ordinal=0,
        media_type=FIXTURE_COVER_MEDIA_TYPE,
        byte_size=FIXTURE_COVER_BYTE_SIZE,
        sha256=FIXTURE_COVER_SHA256,
    )
    cover_response = await read_local_media(
        "local-media-cover-safe",
        cast(Request, _request(enabled=True)),
        cast(AsyncSession, _ScalarSession(cover_media)),
    )

    assert cover_response.media_type == "image/png"
    assert len(cover_response.body) == FIXTURE_COVER_BYTE_SIZE
    assert cover_response.body != response.body

    historical_cover = SimpleNamespace(
        local_media_id="local-media-cover-historical",
        fixture_id="official-account-article-v1",
        source_image_artifact_id=None,
        role="cover",
        ordinal=0,
        media_type=FIXTURE_IMAGE_MEDIA_TYPE,
        byte_size=FIXTURE_IMAGE_BYTE_SIZE,
        sha256=FIXTURE_IMAGE_SHA256,
    )
    historical_response = await read_local_media(
        "local-media-cover-historical",
        cast(Request, _request(enabled=True)),
        cast(AsyncSession, _ScalarSession(historical_cover)),
    )

    assert historical_response.body == response.body

    fixture_bodies: list[bytes] = []
    for ordinal, (checksum, byte_size) in enumerate(
        zip(FIXTURE_BODY_IMAGE_SHA256S, FIXTURE_BODY_IMAGE_BYTE_SIZES, strict=True)
    ):
        body_media = SimpleNamespace(
            local_media_id=f"local-media-body-{ordinal}",
            fixture_id="official-account-article-v1",
            source_image_artifact_id=None,
            role="body",
            ordinal=ordinal,
            media_type=FIXTURE_IMAGE_MEDIA_TYPE,
            byte_size=byte_size,
            sha256=checksum,
        )
        body_response = await read_local_media(
            f"local-media-body-{ordinal}",
            cast(Request, _request(enabled=True)),
            cast(AsyncSession, _ScalarSession(body_media)),
        )
        assert len(body_response.body) == byte_size
        fixture_bodies.append(body_response.body)
    assert len(set(fixture_bodies)) == 3

    publication_bodies: list[bytes] = []
    for ordinal, (checksum, byte_size) in enumerate(
        zip(
            FIXTURE_BODY_PUBLICATION_SHA256S,
            FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
            strict=True,
        )
    ):
        publication_media = SimpleNamespace(
            local_media_id=f"local-media-publication-body-{ordinal}",
            fixture_id="official-account-article-v1",
            source_image_artifact_id=None,
            role="body",
            ordinal=ordinal,
            media_type=FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
            byte_size=byte_size,
            sha256=checksum,
        )
        publication_response = await read_local_media(
            f"local-media-publication-body-{ordinal}",
            cast(Request, _request(enabled=True)),
            cast(AsyncSession, _ScalarSession(publication_media)),
        )
        assert publication_response.media_type == "image/jpeg"
        assert len(publication_response.body) == byte_size
        publication_bodies.append(publication_response.body)
    assert len(set(publication_bodies)) == 3

    publication_cover = SimpleNamespace(
        local_media_id="local-media-publication-cover",
        fixture_id="official-account-article-v1",
        source_image_artifact_id=None,
        role="cover",
        ordinal=0,
        media_type=FIXTURE_COVER_PUBLICATION_MEDIA_TYPE,
        byte_size=FIXTURE_COVER_PUBLICATION_BYTE_SIZE,
        sha256=FIXTURE_COVER_PUBLICATION_SHA256,
    )
    publication_cover_response = await read_local_media(
        "local-media-publication-cover",
        cast(Request, _request(enabled=True)),
        cast(AsyncSession, _ScalarSession(publication_cover)),
    )
    assert publication_cover_response.media_type == "image/jpeg"
    assert len(publication_cover_response.body) == FIXTURE_COVER_PUBLICATION_BYTE_SIZE


@pytest.mark.asyncio
async def test_manual_review_api_returns_safe_projection_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid4()
    stored = StoredOfficialAccountManualReview(
        id=uuid4(),
        run_id=run_id,
        decision="approved",
        reviewer_label="内容审核",
        note="已逐项复核。",
        request_fingerprint="a" * 64,
        reviewed_at=datetime(2026, 8, 23, 9, 30, tzinfo=UTC),
    )

    class Repository:
        def __init__(self, _session_factory: object) -> None:
            pass

        async def record_manual_review(self, **kwargs: object):
            assert kwargs == {
                "run_id": run_id,
                "decision": "approved",
                "reviewer_label": "内容审核",
                "note": "已逐项复核。",
            }
            return stored, False

    monkeypatch.setattr(
        "app.api.v1.routes.official_account_local.PostgresOfficialAccountRepository",
        Repository,
    )
    request = cast(Request, _request(enabled=True))
    request.app.state.session_factory = object()

    response = await record_manual_review(
        run_id,
        OfficialAccountManualReviewRequest(
            decision="approved",
            reviewer_label="  内容审核  ",
            note="  已逐项复核。  ",
        ),
        request,
    )

    assert response.status == "approved"
    assert response.editorially_approved is True
    assert response.idempotent_replay is True
    assert response.review_id == stored.id
    assert response.request_fingerprint == "a" * 64


def test_openapi_exposes_only_local_simulation_operations() -> None:
    document = app.openapi()
    paths = {
        path: value
        for path, value in document["paths"].items()
        if path.startswith("/api/v1/official-account-local")
    }
    schemas = {
        name: value
        for name, value in document["components"]["schemas"].items()
        if name.startswith("OfficialAccount")
    }
    serialized = str({"paths": paths, "schemas": schemas}).lower()

    assert len(paths) == 7
    assert "/api/v1/official-account-local/article-runs/{run_id}/manual-review" in paths
    assert "/publish" not in serialized
    assert "/send" not in serialized
    assert "appid" not in serialized
    assert "appsecret" not in serialized
    assert "access_token" not in serialized
    assert "simulation" in serialized
    assert "body_images" in serialized
    assert "media_selection" in serialized
    assert "body_image" in serialized
    assert "context_images" in serialized
    assert "rights_status" in serialized
    assert "source_page_url" in serialized
    assert "source_article_image_id" not in str(document).lower()
    assert "approved" in serialized
    assert "rejected" in serialized
    assert "reviewer_label" in serialized
    generated_visual = schemas["OfficialAccountGeneratedVisualResponse"]["properties"]
    assert "generated_visuals" in serialized
    assert "reference_asset_ref" in generated_visual
    assert "prompt" not in generated_visual
    assert "vector" not in generated_visual
    assert "object_key" not in generated_visual
    assert not any("generated-visual" in path for path in paths)


def test_context_media_api_accepts_the_full_bounded_alt_text() -> None:
    response = OfficialAccountMediaResponse(
        local_media_id="local-media-context-safe",
        role="context",
        ordinal=0,
        media_url="/api/v1/official-account-local/media/local-media-context-safe",
        media_type="image/jpeg",
        byte_size=1,
        sha256="a" * 64,
        alt_text="图" * 200,
        provenance_kind="source_news",
        source_page_url="https://source.example/news/article",
        rights_status="publish_permission_unverified",
        context_only_not_evidence=True,
    )

    assert len(response.alt_text or "") == 200


def test_multimodal_media_reason_is_a_valid_safe_api_projection() -> None:
    response = OfficialAccountMediaResponse(
        local_media_id="local-media-body-safe",
        role="body",
        ordinal=0,
        media_url="/api/v1/official-account-local/media/local-media-body-safe",
        media_type="image/jpeg",
        byte_size=1024,
        sha256="a" * 64,
        selection_reason_code="multimodal_similarity",
        selection_method="multimodal_embedding",
        similarity_band="high",
    )

    assert response.selection_reason_code == "multimodal_similarity"


def test_media_selection_exposes_planned_total_before_body_media_is_staged() -> None:
    snapshot = SimpleNamespace(
        status="semantic_ready",
        assignments=(object(), object(), object()),
        closed_reason=None,
        visual_query_version="official-account-visual-query-v1",
        visual_selector_version="official-account-visual-selector-v1",
        embedding_identity=None,
    )
    response = _media_selection(
        SimpleNamespace(version_bundle={"media_plan_version": OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION}),
        body_count=0,
        article=SimpleNamespace(media_selection=snapshot),
    )

    assert response.body_image_count == 3
    assert response.safely_degraded is False
