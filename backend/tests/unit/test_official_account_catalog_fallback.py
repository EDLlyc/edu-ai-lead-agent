from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from app.application.ports.official_account_strict_visual import (
    resilient_visual_failure_retries,
    resilient_visual_provider_request_fingerprint,
)
from app.application.services.official_account_catalog_fallback import (
    build_catalog_fallback_projection,
    fallback_failure_allowed,
    validate_catalog_fallback_projection,
)
from app.application.services.official_account_single_edition import SingleEditionProducer
from app.application.services.wechat_single_edition_delivery import deliver_single
from app.core.errors import ImageGenerationFailure
from app.domain.official_account_local import ArticlePackage
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION,
    TOLERANT_VISUAL_PIPELINE_VERSION,
)
from app.domain.official_account_weekly_dag import WeeklyDagArtifact
from app.domain.official_account_weekly_edition import WeeklyArticleRole
from app.infrastructure.official_account_marketing_footer import (
    load_official_account_marketing_framing,
)
from app.infrastructure.wechat_official_account.manual_journal import LocalManualDraftJournal
from app.infrastructure.wechat_official_account.prepared_artifacts import (
    _directory_size,
    _write_directory,
    load_prepared_draft_child,
)
from test_official_account_single_edition import ACCOUNT, NOW, Client, Repository, edition, prepared
from test_official_account_strict_prepared import strict_projection  # noqa: F401
from test_official_account_visual_preview import captured  # noqa: F401


def test_503_is_fallback_eligible_but_explicit_4xx_is_not():
    assert fallback_failure_allowed(
        ImageGenerationFailure(
            error_code="image_provider_rejected",
            disposition="unknown",
            reason="post_outcome_unknown",
            http_status=503,
        ).safe_metadata()["image_failure"]
    )
    assert not fallback_failure_allowed(
        ImageGenerationFailure(
            error_code="image_provider_rejected",
            disposition="terminal",
            reason="provider_failure",
            http_status=403,
        ).safe_metadata()["image_failure"]
    )


@pytest.mark.parametrize("field", ["http_status", "response_kind", "reason", "unexpected"])
def test_fallback_diagnostic_uses_closed_persisted_contract(field):
    diagnostic = ImageGenerationFailure(
        error_code="image_provider_timeout",
        disposition="unknown",
        reason="post_outcome_unknown",
    ).safe_metadata()["image_failure"]
    if field == "unexpected":
        diagnostic[field] = "not part of the persisted contract"
    else:
        diagnostic.pop(field)
    assert not fallback_failure_allowed(diagnostic)


@pytest.fixture
def fallback_projection(strict_projection, captured):  # noqa: F811
    root, _ = captured
    article = ArticlePackage.model_validate(strict_projection.manifest["article"])
    header, header_bytes, footer, footer_bytes = load_official_account_marketing_framing()
    return build_catalog_fallback_projection(
        run_id=uuid4(),
        article_version_id=uuid4(),
        render_version_id=uuid4(),
        article=article,
        role="official_anchor",
        failure_evidence={
            "version": "single-catalog-fallback-evidence-v1",
            "physical_attempt_count": 3,
            "failed_slot": 0,
            "logical_request_fingerprint": "a" * 64,
            "attempts": [
                {
                    "request_fingerprint": resilient_visual_provider_request_fingerprint(
                        "a" * 64,
                        number,
                        policy=TOLERANT_VISUAL_PIPELINE_VERSION,
                    ),
                    "diagnostic": ImageGenerationFailure(
                        error_code="image_provider_timeout",
                        disposition="unknown",
                        reason="post_outcome_unknown",
                    ).safe_metadata()["image_failure"],
                }
                for number in range(1, 4)
            ],
        },
        bodies=tuple((root / f"catalog/{i}.jpg").read_bytes() for i in range(5)),
        contexts={0: (root / "context/0.png").read_bytes()},
        header=header,
        header_bytes=header_bytes,
        footer=footer,
        footer_bytes=footer_bytes,
    )


def test_canonical_fallback_preserves_all_five_catalog_sources_and_news_image(
    fallback_projection, tmp_path
):
    value = fallback_projection
    validate_catalog_fallback_projection(value.manifest, value.files)
    target = tmp_path / "children" / f"wechat-draft-prepared-child-{value.child_fingerprint}"
    _write_directory(
        target, files={**value.files, "prepared-manifest.json": json.dumps(value.manifest).encode()}
    )
    artifact = WeeklyDagArtifact(
        opaque_ref=f"wechat-prepared-child-v1:{value.child_fingerprint}",
        fingerprint=value.child_fingerprint,
        media_type="application/vnd.wechat.approved-catalog-fallback-child+directory",
        byte_size=_directory_size(target),
    )
    draft = load_prepared_draft_child(
        artifact,
        work_root=tmp_path,
        role=WeeklyArticleRole.OFFICIAL_ANCHOR,
        max_image_bytes=10 * 1024 * 1024,
    )
    assert draft.visual_origin == "approved_catalog_fallback"
    assert len(draft.body_media) == 8  # Five catalog, one original news, two framing.
    assert draft.content_source_url is None
    assert "visual_evidence" not in value.manifest
    with pytest.raises(ValueError, match="origin"):
        load_prepared_draft_child(
            replace(artifact, media_type="application/vnd.wechat.prepared-draft-child+directory"),
            work_root=tmp_path,
            role=WeeklyArticleRole.OFFICIAL_ANCHOR,
            max_image_bytes=10 * 1024 * 1024,
        )


@pytest.mark.asyncio
async def test_canonical_fallback_delivery_reuses_one_durable_add_ack(
    fallback_projection, tmp_path
):
    value = fallback_projection
    target = tmp_path / "children" / f"wechat-draft-prepared-child-{value.child_fingerprint}"
    _write_directory(
        target, files={**value.files, "prepared-manifest.json": json.dumps(value.manifest).encode()}
    )
    artifact = WeeklyDagArtifact(
        opaque_ref=f"wechat-prepared-child-v1:{value.child_fingerprint}",
        fingerprint=value.child_fingerprint,
        media_type="application/vnd.wechat.approved-catalog-fallback-child+directory",
        byte_size=_directory_size(target),
    )
    draft = load_prepared_draft_child(
        artifact,
        work_root=tmp_path,
        role=WeeklyArticleRole.OFFICIAL_ANCHOR,
        max_image_bytes=10 * 1024 * 1024,
    )
    current = edition(
        prepared_artifact=artifact,
        article_fingerprint=draft.article_fingerprint,
        content_fingerprint=draft.content_fingerprint,
    )
    repository, client = Repository(current), Client()
    journal = LocalManualDraftJournal(tmp_path / "journal", ACCOUNT)
    try:
        for _ in range(2):
            await deliver_single(
                repository=repository,
                edition=current,
                prepared=draft,
                journal=journal,
                client=client,
                clock=lambda: NOW,
            )
            assert repository.value.status == "delivered"
        assert client.calls == [*(["inline"] * 8), "thumb", "add"]
        assert draft.visual_origin == "approved_catalog_fallback"
    finally:
        journal.close()


@pytest.mark.parametrize("part", ["body", "source", "context", "html", "origin", "count"])
def test_fallback_tampering_fails_closed(fallback_projection, part):
    value = fallback_projection
    files, manifest = dict(value.files), dict(value.manifest)
    if part in {"body", "source", "context", "html"}:
        key = {
            "body": "assets/body-00.jpg",
            "source": "assets/catalog-source-00.jpg",
            "context": "assets/context-source-00.jpg",
            "html": "article-body.html",
        }[part]
        files[key] += b"tamper"
    elif part == "origin":
        manifest["origin"] = "generated"
    else:
        manifest["failure_evidence"] = {
            "version": "single-catalog-fallback-evidence-v1",
            "physical_attempt_count": 2,
        }
    with pytest.raises(ValueError):
        validate_catalog_fallback_projection(manifest, files)


@pytest.mark.parametrize(
    "code,reason,disposition,allowed",
    [
        ("image_provider_timeout", "post_outcome_unknown", "unknown", True),
        ("provider_unavailable", "post_outcome_unknown", "unknown", True),
        ("provider_authentication_failed", "provider_failure", "terminal", False),
        ("provider_identity_mismatch", "provider_failure", "terminal", False),
        ("image_provider_not_configured", "provider_failure", "terminal", False),
        ("image_output_invalid", "image_raster_signature_invalid", "terminal", False),
        (
            "official_account_generated_visual_result_unknown",
            "lease_authority_lost",
            "unknown",
            False,
        ),
    ],
)
def test_fallback_failure_allowlist_excludes_hard_errors(code, reason, disposition, allowed):
    failure = ImageGenerationFailure(error_code=code, reason=reason, disposition=disposition)
    assert fallback_failure_allowed(failure.safe_metadata()["image_failure"]) is allowed
    if code == "image_output_invalid":
        assert not resilient_visual_failure_retries(
            failure, policy=TOLERANT_VISUAL_PIPELINE_VERSION
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "run_status,allow", [("failed", True), ("result_unknown", True), ("review_required", False)]
)
async def test_single_producer_fallback_never_reenqueues_or_calls_model(run_status, allow):
    value = edition(status="generating", role="official_anchor", article_run_id=uuid4())
    value = replace(
        value,
        identity=replace(
            value.identity,
            visual_pipeline_version=TOLERANT_VISUAL_PIPELINE_VERSION,
            generated_visual_plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
            generated_visual_prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION,
        ),
    )
    repository = Repository(value)
    repository.claim = AsyncMock(return_value=value)
    repository.reserve_article = AsyncMock(return_value=True)
    articles = SimpleNamespace(
        get_run=AsyncMock(return_value=SimpleNamespace(status=run_status)),
        enqueue_material_package=AsyncMock(),
    )
    artifact = WeeklyDagArtifact(
        opaque_ref="test-v1:" + "a" * 64,
        fingerprint="a" * 64,
        media_type="application/json",
        byte_size=1,
    )
    fallback = AsyncMock(return_value=artifact)
    artifacts = SimpleNamespace(
        validate_child=Mock(return_value=prepared()), build_child=AsyncMock()
    )
    service = SingleEditionProducer(
        repository=repository,
        planner=object(),
        article_repository=articles,
        artifacts=artifacts,
        checkpoints=object(),
        account=ACCOUNT,
        clock=lambda: NOW,
        fallback_builder=fallback,
    )
    assert await service.process_once()
    assert fallback.await_count == int(allow)
    assert repository.value.status == ("ready" if allow else "failed")
    articles.enqueue_material_package.assert_not_awaited()
    artifacts.build_child.assert_not_awaited()
