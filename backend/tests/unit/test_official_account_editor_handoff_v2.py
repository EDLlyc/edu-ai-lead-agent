from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast
from unittest.mock import AsyncMock
from uuid import UUID
from zipfile import ZipFile

import pytest
from app.api.v1.routes.official_account_local import (
    _editor_handoff_service,
    read_editor_handoff,
)
from app.application.ports.official_account_local import (
    OfficialAccountGeneratedVisualPlan,
    StoredOfficialAccountGeneratedVisual,
    StoredOfficialAccountManualReview,
)
from app.application.services.official_account_editor_handoff_v2 import (
    OfficialAccountEditorHandoffV2Service,
    bind_editor_handoff_v2_mobile_validation,
    build_editor_handoff_v2_artifact,
)
from app.application.services.official_account_local import manual_review_request_fingerprint
from app.application.services.official_account_visual_generation import (
    select_generated_visual_block_anchor,
)
from app.domain.official_account_editor_handoff_v2 import (
    BodyVisualLineage,
    BodyVisualReferenceProjection,
    EditorHandoffMobileValidation,
    EditorHandoffRelease,
    fingerprint_v2,
    select_semantic_emphasis,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    ArticleImageBlock,
    ArticlePackage,
    article_package_fingerprint,
    fingerprint,
    render_wechat_html,
)
from app.infrastructure.official_account_local import FIXTURE_BODY_PUBLICATION_SHA256S
from app.infrastructure.official_account_media import OfficialAccountPersistedMedia
from app.official_account_editor_handoff_v2_demo import (
    _DEFAULT_BODY_VISUAL_DIR,
    _load_browser_report,
    build_demo_artifact,
)
from fastapi import Response
from pydantic import ValidationError
from test_official_account_export import _news_context_bundle_input
from test_official_account_local_api import _handoff_request


async def _v2_artifact(bundle: Any | None = None):
    if bundle is None:
        bundle = await _news_context_bundle_input()
    release = EditorHandoffRelease(
        policy="quality_auto",
        kind="machine",
        input_fingerprint=fingerprint_v2("quality-auto-fixture"),
        gate_codes=("deterministic_validation_passed", "model_audit_accepted"),
    )
    return build_editor_handoff_v2_artifact(
        run_id=bundle.run_id,
        run_request_fingerprint=bundle.request_fingerprint,
        article=bundle.article,
        release=release,
        review=None,
        draft_resolved_fingerprint=bundle.resolved_fingerprint,
        media=tuple(
            zip(
                (
                    *bundle.body_media_items,
                    *bundle.context_media_items,
                    bundle.cover_media,
                ),
                (
                    *bundle.body_bytes_items,
                    *bundle.context_bytes_items,
                    bundle.cover_bytes,
                ),
                strict=True,
            )
        ),
        body_visuals=_body_visual_lineages(bundle),
        eligibility_checks=(),
    )


def _body_visual_lineages(bundle: Any) -> tuple[BodyVisualLineage, ...]:
    body_items = tuple(sorted(bundle.body_media_items, key=lambda item: item.ordinal))
    article = cast(Any, SimpleNamespace(article=bundle.article))
    section_by_ordinal = _body_section_indexes(bundle.article)
    lineages: list[BodyVisualLineage] = []
    for item in body_items:
        section_index = section_by_ordinal[item.ordinal]
        anchor = select_generated_visual_block_anchor(
            article=article,
            section_index=section_index,
        )
        lineages.append(
            BodyVisualLineage(
                ordinal=item.ordinal,
                section_index=section_index,
                block_index=anchor.block_index,
                block_kind=anchor.block_kind,
                block_fingerprint=anchor.block_fingerprint,
                scene_brief=anchor.scene_text,
                scene_brief_fingerprint=fingerprint_v2(
                    "editor-handoff-body-visual-scene-brief-v1",
                    section_index,
                    anchor.block_index,
                    anchor.block_kind,
                    anchor.scene_text,
                ),
                reference=BodyVisualReferenceProjection(
                    public_ref=f"{item.ordinal + 1:016x}",
                    catalog_version="test-approved-catalog-v1",
                    role="identity_reference",
                    character_labels=("xiao-sai", "sai-xiansheng"),
                    source_checksum=f"{item.ordinal + 1:064x}",
                    publication_checksum=f"{item.ordinal + 11:064x}",
                    input_checksum=f"{item.ordinal + 21:064x}",
                ),
                selection_method="deterministic_tag",
                generation_kind="frozen_reference_conditioned_fixture",
                provider_execution="not_claimed",
                plan_fingerprint=fingerprint_v2("test-body-visual-plan", item.ordinal),
                output_sha256=item.sha256,
                output_byte_size=item.byte_size,
                visible_character_labels=("xiao-sai", "sai-xiansheng"),
                visibility_status="passed_local_visual_inspection",
            )
        )
    return tuple(lineages)


def _body_section_indexes(article: ArticlePackage) -> dict[int, int]:
    return {
        int(block.slot_key.removeprefix("body-")): section_index
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if isinstance(block, ArticleImageBlock)
    }


@pytest.mark.asyncio
async def test_v2_machine_release_interleaves_news_and_ip_assets_deterministically() -> None:
    bundle = await _news_context_bundle_input()
    artifact = await _v2_artifact(bundle)
    repeated = await _v2_artifact(bundle)

    assert artifact.release.kind == "machine"
    assert artifact.release.manual_review_fingerprint is None
    assert artifact.recipe.kind == "news_analysis"
    assert len(artifact.placements) == 1
    assert artifact.placements[0].media_path == "assets/context-00.png"
    assert [item.role for item in artifact.media].count("body") == 3
    assert [item.role for item in artifact.media].count("context") == 1
    assert artifact.content_fingerprint == repeated.content_fingerprint
    assert artifact.artifact_fingerprint == repeated.artifact_fingerprint
    assert artifact.body_html == repeated.body_html
    assert artifact.zip_bytes == repeated.zip_bytes
    assert artifact.mobile_validation.status == "not_run"
    assert artifact.preflight.passed is True
    assert "mobile_browser_validation_not_run" in artifact.preflight.warning_codes
    assert b"assets/context-00.png" in artifact.body_html
    assert b"publish_permission_unverified" not in artifact.body_html

    release = json.loads(artifact.files["release.json"])
    review = json.loads(artifact.files["review.json"])
    manifest = json.loads(artifact.files["manifest.json"])
    assert release["kind"] == "machine"
    assert review == {"immutable": True, "review": None, "status": "not_present"}
    assert manifest["content_fingerprint"] == artifact.content_fingerprint
    assert manifest["artifact_fingerprint"] == artifact.artifact_fingerprint
    assert manifest["published"] is False
    assert manifest["local_only"] is True
    with ZipFile(BytesIO(artifact.zip_bytes)) as archive:
        assert archive.testzip() is None
        assert all(".." not in name.split("/") for name in archive.namelist())


def test_semantic_emphasis_is_exact_bounded_and_escapes_at_render_boundary() -> None:
    text = "AI时代，科创教育要帮助孩子建立问题意识，完成2026年三项真实任务。"  # noqa: RUF001
    first = select_semantic_emphasis(text, context_terms=("科创教育", "问题意识", "真实任务"))
    repeated = select_semantic_emphasis(text, context_terms=("科创教育", "问题意识", "真实任务"))

    assert first == repeated
    assert 1 <= len(first) <= 3
    assert all(text[item.start : item.end] == item.text for item in first)
    assert all(4 <= len(item.text) <= 15 for item in first)
    assert all(left.end <= right.start for left, right in pairwise(first))


@pytest.mark.asyncio
async def test_semantic_emphasis_never_keeps_mid_clause_truncation_fragments() -> None:
    artifact = await _v2_artifact()
    forbidden = {
        "就会发现这个问题也许正连接着一",
        "次真实的观察、一段尚未成形的推",
        "而是在承担一个真实、可理解的探",
    }
    selected = {span.text for block in artifact.emphasis for span in block.spans}

    assert selected.isdisjoint(forbidden)
    assert all(
        len(block.spans) <= (3 if len(block.source_text) >= 120 else 2)
        for block in artifact.emphasis
    )
    assert all(
        not span.text.endswith(("的", "了", "而", "也", "与", "和", "一"))
        for block in artifact.emphasis
        for span in block.spans
    )
    assert all(
        span.text.count("“") == span.text.count("”")
        for block in artifact.emphasis
        for span in block.spans
    )


def test_semantic_emphasis_skips_generic_transition_units() -> None:
    text = "这份实践清单提醒我们，答案只是过程中的一个节点。"  # noqa: RUF001

    selected = select_semantic_emphasis(text)

    assert "提醒我们" not in {item.text for item in selected}
    assert "答案只是过程中的一个节点" in {item.text for item in selected}


def test_mobile_report_requires_the_exact_ordered_viewport_pair() -> None:
    with pytest.raises(ValidationError):
        EditorHandoffMobileValidation.model_validate({"status": "not_run", "viewports": [430, 320]})


def test_browser_sidecar_requires_real_320_and_430_observations(tmp_path: Path) -> None:
    report_path = tmp_path / "mobile.json"
    payload = {
        "status": "passed",
        "content_fingerprint": "a" * 64,
        "body_sha256": "b" * 64,
        "media_sha256s": ["c" * 64],
        "viewports": [
            {
                "viewport": 320,
                "imageCount": 5,
                "documentScrollWidth": 320,
                "documentClientWidth": 320,
            },
            {
                "viewport": 430,
                "imageCount": 5,
                "documentScrollWidth": 430,
                "documentClientWidth": 430,
            },
        ],
        "external_requests": 0,
        "copy_root_matches_body": True,
    }
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    assert _load_browser_report(report_path).viewports == (320, 430)

    payload["viewports"] = [payload["viewports"][1], payload["viewports"][0]]
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="exact mobile checks"):
        _load_browser_report(report_path)


def _stored_generated_visuals(
    *,
    bundle: Any,
    article: Any,
    article_id: UUID,
) -> tuple[StoredOfficialAccountGeneratedVisual, ...]:
    render_id = UUID("44444444-4444-4444-8444-444444444444")
    stored_article = cast(Any, SimpleNamespace(id=article_id, article=article))
    section_by_ordinal = _body_section_indexes(article)
    visuals: list[StoredOfficialAccountGeneratedVisual] = []
    for media in sorted(bundle.body_media_items, key=lambda item: item.ordinal):
        section_index = section_by_ordinal[media.ordinal]
        anchor = select_generated_visual_block_anchor(
            article=stored_article,
            section_index=section_index,
        )
        plan = OfficialAccountGeneratedVisualPlan(
            run_id=bundle.run_id,
            article_version_id=article_id,
            render_version_id=render_id,
            ordinal=media.ordinal,
            section_index=section_index,
            reference_asset_ref=f"{media.ordinal + 1:016x}",
            reference_catalog_version="test-approved-catalog-v1",
            reference_source_checksum=f"{media.ordinal + 1:064x}",
            reference_publication_checksum=f"{media.ordinal + 11:064x}",
            selection_method="deterministic_tag",
            similarity_band=None,
            request_fingerprint=fingerprint_v2("stored-generated-plan", media.ordinal),
            plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
            prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
            provider="fake",
            model="test-reference-conditioned-image-generator",
            block_index=anchor.block_index,
            block_kind=anchor.block_kind,
            block_fingerprint=anchor.block_fingerprint,
            reference_input_version=("image-reference-input-v2-png-preserve-jpeg-normalize"),
            reference_input_checksum=f"{media.ordinal + 21:064x}",
            output_profile_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION,
        )
        visuals.append(
            StoredOfficialAccountGeneratedVisual(
                id=UUID(int=media.ordinal + 1),
                plan=plan,
                status="ready",
                media_type=media.media_type,
                byte_size=media.byte_size,
                sha256=media.sha256,
                width=1_536,
                height=1_024,
                error_code=None,
                created_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
                completed_at=datetime(2026, 8, 27, 9, 1, tzinfo=UTC),
            )
        )
    return tuple(visuals)


def _persisted_body_rows(
    *,
    bundle: Any,
    visuals: tuple[StoredOfficialAccountGeneratedVisual, ...],
) -> tuple[tuple[OfficialAccountPersistedMedia, Any], ...]:
    by_ordinal = {item.plan.ordinal: item for item in visuals}
    return tuple(
        (
            OfficialAccountPersistedMedia(
                local_media_id=media.local_media_id,
                source_image_artifact_id=None,
                fixture_id=None,
                role="body",
                ordinal=media.ordinal,
                media_type=media.media_type,
                byte_size=media.byte_size,
                sha256=media.sha256,
                descriptor={"source_kind": "generated_visual"},
                generated_visual_id=by_ordinal[media.ordinal].id,
            ),
            replace(
                media,
                assigned_section_index=by_ordinal[media.ordinal].plan.section_index,
            ),
        )
        for media in sorted(bundle.body_media_items, key=lambda item: item.ordinal)
    )


@pytest.mark.asyncio
async def test_mobile_report_is_exactly_bound_and_changes_only_artifact_identity() -> None:
    artifact = await _v2_artifact()
    report = EditorHandoffMobileValidation(
        status="passed",
        content_fingerprint=artifact.content_fingerprint,
        body_sha256=artifact.preflight.checks
        and __import__("hashlib").sha256(artifact.body_html).hexdigest(),
        media_sha256s=tuple(item.sha256 for item in artifact.media),
        external_requests=0,
        copy_root_matches_body=True,
    )
    finalized = bind_editor_handoff_v2_mobile_validation(artifact, report)

    assert finalized.content_fingerprint == artifact.content_fingerprint
    assert finalized.artifact_fingerprint != artifact.artifact_fingerprint
    assert finalized.mobile_validation.status == "passed"
    assert "mobile_browser_validation_not_run" not in finalized.preflight.warning_codes
    assert json.loads(finalized.files["mobile-validation.json"])["status"] == "passed"
    assert json.loads(finalized.files["manifest.json"])["artifact_fingerprint"] == (
        finalized.artifact_fingerprint
    )

    tampered = report.model_copy(update={"body_sha256": "0" * 64})
    with pytest.raises(ValueError, match="does not match"):
        bind_editor_handoff_v2_mobile_validation(artifact, tampered)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "policy",
        "review_decision",
        "image_validation",
        "generated_visual_status",
        "expected_state",
        "expected_code",
        "expected_kind",
    ),
    [
        ("quality_auto", None, True, None, "ready", None, "machine"),
        ("quality_auto", "approved", True, None, "ready", None, "manual"),
        (
            "quality_auto",
            "rejected",
            True,
            None,
            "blocked",
            "manual_review_not_rejected",
            None,
        ),
        (
            "quality_auto",
            None,
            True,
            "failed",
            "blocked",
            "generated_visuals_ready",
            None,
        ),
        ("quality_auto", None, False, None, "blocked", "image_validation_passed", None),
        ("manual_only", None, True, None, "blocked", "immutable_review_approved", None),
    ],
)
async def test_v2_release_policy_gate_matrix(
    policy: Literal["manual_only", "quality_auto"],
    review_decision: Literal["approved", "rejected"] | None,
    image_validation: bool,
    generated_visual_status: Literal["failed"] | None,
    expected_state: Literal["ready", "blocked"],
    expected_code: str | None,
    expected_kind: Literal["manual", "machine"] | None,
) -> None:
    bundle = await _news_context_bundle_input()
    article_id = UUID("33333333-3333-4333-8333-333333333333")
    draft_request_fingerprint = "c" * 64
    resolved_html = "<section>immutable draft</section>"
    article = bundle.article.model_copy(
        update={
            "quality": bundle.article.quality.model_copy(
                update={"inherited_image_validation_passed": image_validation}
            )
        }
    )
    article = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    rendered = render_wechat_html(article)
    ready_visuals = _stored_generated_visuals(
        bundle=bundle,
        article=article,
        article_id=article_id,
    )
    review = None
    if review_decision is not None:
        review = StoredOfficialAccountManualReview(
            id=UUID("22222222-2222-4222-8222-222222222222"),
            run_id=bundle.run_id,
            decision=review_decision,
            reviewer_label="内容审核",
            note="不可变决定",
            request_fingerprint=manual_review_request_fingerprint(
                run_id=bundle.run_id,
                decision=review_decision,
                reviewer_label="内容审核",
                note="不可变决定",
            ),
            reviewed_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
        )
    repository = SimpleNamespace(
        get_run=AsyncMock(
            return_value=SimpleNamespace(status="ready", request_fingerprint="a" * 64)
        ),
        get_article=AsyncMock(
            return_value=SimpleNamespace(
                id=article_id,
                article=article,
                validation_passed=True,
                audit=SimpleNamespace(accepted=True),
            )
        ),
        get_render=AsyncMock(
            return_value=SimpleNamespace(
                article_version_id=article_id,
                canonical_html=rendered.canonical_html,
                render_fingerprint=rendered.render_fingerprint,
            )
        ),
        get_draft=AsyncMock(
            return_value=SimpleNamespace(
                state="ready",
                simulation=True,
                request_fingerprint=draft_request_fingerprint,
                resolved_html=resolved_html,
                resolved_fingerprint=fingerprint(
                    rendered.render_fingerprint,
                    draft_request_fingerprint,
                    resolved_html,
                ),
            )
        ),
        get_manual_review=AsyncMock(return_value=review),
        list_generated_visuals=AsyncMock(
            return_value=(
                ready_visuals
                if generated_visual_status is None
                else (SimpleNamespace(status=generated_visual_status),)
            )
        ),
    )
    media = tuple(
        zip(
            (*bundle.body_media_items, *bundle.context_media_items, bundle.cover_media),
            (*bundle.body_bytes_items, *bundle.context_bytes_items, bundle.cover_bytes),
            strict=True,
        )
    )
    service = OfficialAccountEditorHandoffV2Service(
        session_factory=cast(Any, object()),
        resolver=cast(Any, object()),
        release_policy=policy,
    )
    service._repository = cast(Any, repository)
    service._load_media_rows = AsyncMock(
        return_value=_persisted_body_rows(bundle=bundle, visuals=ready_visuals)
    )
    service._resolve_media = AsyncMock(return_value=media)

    inspection = await service.inspect(bundle.run_id)

    assert inspection.state == expected_state, inspection.blocking_codes
    if expected_code is not None:
        assert expected_code in inspection.blocking_codes
        service._resolve_media.assert_not_awaited()
    else:
        assert inspection.artifact is not None
        assert inspection.artifact.release.kind == expected_kind
        assert inspection.artifact.release.policy == "quality_auto"


@pytest.mark.asyncio
async def test_v2_api_projection_exposes_release_placement_and_honest_mobile_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = await _v2_artifact()
    inspection = SimpleNamespace(
        state="ready",
        artifact=artifact,
        checks=artifact.preflight.checks,
        blocking_codes=artifact.preflight.blocking_codes,
        warning_codes=artifact.preflight.warning_codes,
    )
    monkeypatch.setattr(
        "app.api.v1.routes.official_account_local._editor_handoff_service",
        lambda _request: SimpleNamespace(inspect=AsyncMock(return_value=inspection)),
    )

    response = await read_editor_handoff(artifact.run_id, _handoff_request(), Response())

    assert response.release is not None
    assert response.release.kind == "machine"
    assert response.release.policy == "quality_auto"
    assert response.recipe == "news_analysis"
    assert response.content_fingerprint == artifact.content_fingerprint
    assert response.artifact_fingerprint == artifact.artifact_fingerprint
    assert response.mobile_validation.status == "not_run"
    context = next(item for item in response.media if item.role == "context")
    assert context.placement is not None
    assert context.placement.target_block_index == artifact.placements[0].target_block_index
    assert context.rights_status == "publish_permission_unverified"


@pytest.mark.asyncio
async def test_news_demo_uses_source_bound_semantic_context_placements() -> None:
    artifact = await build_demo_artifact()
    article = json.loads(artifact.files["article.json"])
    markdown = artifact.files["article.md"].decode("utf-8")

    assert len(artifact.placements) == 2
    assert all(item.reason_code == "semantic_text_overlap" for item in artifact.placements)
    assert all(item.matched_terms for item in artifact.placements)
    assert {item["source_url"] for item in article["sources"]} == {
        "https://www.moe.gov.cn/jyb_xwfb/s6052/moe_838/202607/t20260722_1444692.html",
        "https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/t20260410_1433382.html",
    }
    assert b"example.invalid" not in artifact.body_html
    for placement in artifact.placements:
        block = article["sections"][placement.section_index]["blocks"][placement.target_block_index]
        media = next(item for item in artifact.media if item.path == placement.media_path)
        assert block["claim_refs"] in (
            ["news-foundation-education"],
            ["news-ai-education"],
        )
        assert all(term in block["text"] for term in placement.matched_terms)
        assert (
            f"定位：第 {placement.section_index + 1} 节 · "  # noqa: RUF001
            f"正文块 {placement.target_block_index + 1} 后"
        ) in markdown
        assert f"来源：{media.source_page_url}" in markdown  # noqa: RUF001
        assert f"署名：{media.credit}" in markdown  # noqa: RUF001
        assert "权利说明：发布权未验证" in markdown  # noqa: RUF001
        assert media.rights_status not in markdown
    assert [item.role for item in artifact.media].count("body") == 3
    assert [item.role for item in artifact.media].count("context") == 2


@pytest.mark.asyncio
async def test_news_demo_uses_exact_block_reference_conditioned_body_visuals() -> None:
    artifact = await build_demo_artifact()
    article = json.loads(artifact.files["article.json"])
    payload = json.loads(artifact.files["body-visuals.json"])
    manifest = json.loads(artifact.files["manifest.json"])
    visuals = payload["items"]
    body_media = sorted(
        (item for item in artifact.media if item.role == "body"),
        key=lambda item: item.ordinal,
    )

    assert payload["version"] == "editor-handoff-body-visual-lineage-v1"
    assert len(visuals) == 3
    assert manifest["body_visuals"] == visuals
    assert {item["selection_method"] for item in visuals} == {"deterministic_fixture_semantic"}
    assert {item["provider_execution"] for item in visuals} == {"authorized_local_imagegen_result"}
    assert len({item["reference"]["public_ref"] for item in visuals}) == 3
    assert len({item["output_sha256"] for item in visuals}) == 3
    assert {item["output_sha256"] for item in visuals}.isdisjoint(FIXTURE_BODY_PUBLICATION_SHA256S)
    assert {label for item in visuals for label in item["visible_character_labels"]} == {
        "xiao-sai",
        "sai-xiansheng",
    }
    assert [item["output_sha256"] for item in visuals] == [item.sha256 for item in body_media]
    assert [item["reference"]["public_ref"] for item in visuals] == [
        item["candidate_ref"] for item in article["media_selection"]["assignments"]
    ]
    stored_article = cast(
        Any,
        SimpleNamespace(article=ArticlePackage.model_validate(article)),
    )
    for item in visuals:
        anchor = select_generated_visual_block_anchor(
            article=stored_article,
            section_index=item["section_index"],
        )
        assert (
            item["block_index"],
            item["block_kind"],
            item["block_fingerprint"],
        ) == (anchor.block_index, anchor.block_kind, anchor.block_fingerprint)
    assert b"private/" not in artifact.files["body-visuals.json"]
    assert b'"prompt":' not in artifact.files["body-visuals.json"]
    assert b'"provider_body":' not in artifact.files["body-visuals.json"]


@pytest.mark.asyncio
async def test_news_demo_rejects_tampered_body_visual_source(tmp_path: Path) -> None:
    source = _DEFAULT_BODY_VISUAL_DIR.resolve()
    target = tmp_path / "body-visuals"
    shutil.copytree(source, target)
    map_path = target / "visual-map.json"
    payload = json.loads(map_path.read_text(encoding="utf-8"))
    payload["visuals"][0]["block_fingerprint"] = "0" * 64
    map_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="production plan no longer matches"):
        await build_demo_artifact(body_visual_directory=target)

    shutil.copytree(source, target := tmp_path / "body-visual-bytes")
    asset = target / "assets" / "body-00.jpg"
    asset.write_bytes(asset.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="integrity changed"):
        await build_demo_artifact(body_visual_directory=target)


@pytest.mark.asyncio
async def test_news_demo_rejects_symlinked_body_visual_directories(tmp_path: Path) -> None:
    source = _DEFAULT_BODY_VISUAL_DIR.resolve()
    target = tmp_path / "body-visuals"
    shutil.copytree(source, target)
    shutil.rmtree(target / "assets")
    (target / "assets").symlink_to(source / "assets", target_is_directory=True)

    with pytest.raises(ValueError, match="symlinked"):
        await build_demo_artifact(body_visual_directory=target)

    root_link = tmp_path / "body-visual-root-link"
    root_link.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="source directory is symlinked"):
        await build_demo_artifact(body_visual_directory=root_link)


@pytest.mark.asyncio
async def test_news_demo_rejects_duplicate_map_fields_and_jpeg_metadata(
    tmp_path: Path,
) -> None:
    source = _DEFAULT_BODY_VISUAL_DIR.resolve()
    duplicate_target = tmp_path / "duplicate-map"
    shutil.copytree(source, duplicate_target)
    map_path = duplicate_target / "visual-map.json"
    raw_map = map_path.read_text(encoding="utf-8")
    map_path.write_text(
        raw_map.replace(
            '{\n  "schema_version"',
            '{\n  "schema_version": '
            '"official-account-editor-handoff-body-visual-source-v1",\n'
            '  "schema_version"',
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate fields"):
        await build_demo_artifact(body_visual_directory=duplicate_target)

    metadata_target = tmp_path / "jpeg-metadata"
    shutil.copytree(source, metadata_target)
    asset = metadata_target / "assets" / "body-00.jpg"
    original = asset.read_bytes()
    comment = b"review"
    with_comment = (
        original[:2] + b"\xff\xfe" + (len(comment) + 2).to_bytes(2, "big") + comment + original[2:]
    )
    asset.write_bytes(with_comment)
    metadata_map_path = metadata_target / "visual-map.json"
    payload = json.loads(metadata_map_path.read_text(encoding="utf-8"))
    payload["visuals"][0]["byte_size"] = len(with_comment)
    payload["visuals"][0]["output_sha256"] = __import__("hashlib").sha256(with_comment).hexdigest()
    metadata_map_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="retained metadata"):
        await build_demo_artifact(body_visual_directory=metadata_target)


def test_route_selects_v2_only_for_explicit_flag_and_quality_auto_policy() -> None:
    request = _handoff_request()
    request.app.state.settings.official_account_editor_handoff_v2_enabled = True
    request.app.state.settings.official_account_editor_handoff_release_policy = "quality_auto"

    service = _editor_handoff_service(request)

    assert isinstance(service, OfficialAccountEditorHandoffV2Service)
    assert service._release_policy == "quality_auto"
