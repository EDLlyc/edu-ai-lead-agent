from __future__ import annotations

import json
import socket
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest
from app import official_account_weekly_edition_demo as weekly_demo
from app.application.services.official_account_editor_handoff_v2 import (
    write_editor_handoff_v2_artifact,
)
from app.application.services.official_account_weekly_edition import (
    FinalizedWeeklyChild,
    bind_weekly_child,
    build_weekly_edition_artifact,
    build_weekly_homepage_operator_state_sidecar,
    finalized_v2_child_from_artifact,
    load_finalized_v2_child,
    write_weekly_edition_artifact,
    write_weekly_homepage_operator_state_sidecar,
)
from app.domain.editorial_relevance import (
    ScienceTechContentSignal,
    ScienceTechEditorialCohort,
)
from app.domain.official_account_weekly_edition import (
    WeeklyArticleRole,
    WeeklyEditionSchedule,
    WeeklyGovernedCandidate,
    WeeklyHomepageOperatorEvent,
    WeeklyHomepageOperatorEventKind,
    WeeklyHomepagePublicationStatus,
    WeeklySelectionReason,
    apply_weekly_homepage_operator_event,
    due_weekly_edition_week_start,
    initial_weekly_homepage_operator_state,
    select_weekly_articles,
    weekly_homepage_operator_state_from_projection,
    weekly_homepage_operator_state_projection,
    weekly_selection_from_projection,
    weekly_selection_projection,
)
from app.domain.topic_selection import TopicCandidate, TopicScoringConfig, score_topic_candidate
from app.official_account_weekly_edition_demo import (
    build_fixture_children,
    build_fixture_selection,
    fixture_mobile_validation,
)
from PIL import Image

_CUTOFF = datetime(2026, 8, 31, 9, tzinfo=UTC)


def _decoded_rgb_fingerprint(body: bytes) -> tuple[tuple[int, int], str]:
    with Image.open(BytesIO(body)) as opened:
        opened.load()
        return opened.size, sha256(opened.convert("RGB").tobytes()).hexdigest()


def _rebind_child_media_bytes(
    child: FinalizedWeeklyChild,
    replacements: dict[str, bytes],
) -> FinalizedWeeklyChild:
    files = dict(child.files)
    manifest = json.loads(files["manifest.json"])
    for media in manifest["media"]:
        path = media["path"]
        body = replacements.get(path)
        if body is None:
            continue
        size, _pixel_hash = _decoded_rgb_fingerprint(body)
        files[path] = body
        media["sha256"] = sha256(body).hexdigest()
        media["byte_size"] = len(body)
        media["width"], media["height"] = size
        for projection in manifest["files"]:
            if projection["path"] == path:
                projection["sha256"] = media["sha256"]
                projection["byte_size"] = len(body)
                break
    files["manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    return replace(child, files=files)


def _governed(
    suffix: int,
    *,
    age_days: int,
    organization_type: str,
    cohort: ScienceTechEditorialCohort = (
        ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY
    ),
    signals: tuple[ScienceTechContentSignal, ...] = (),
    directions: tuple[str, ...] = (),
    veto: bool = False,
    total: float = 0.9,
) -> WeeklyGovernedCandidate:
    candidate = TopicCandidate(
        event_id=UUID(f"00000000-0000-4000-8000-{suffix:012d}"),
        event_version_id=UUID(f"10000000-0000-4000-8000-{suffix:012d}"),
        event_time=_CUTOFF - timedelta(days=age_days),
        source_trust=total,
        source_diversity=4,
        ai_relevance=total,
        parent_relevance=total,
        communication_potential=total,
        editorial_priority=total,
        science_tech_editorial_cohort=cohort,
        science_tech_education_relevance=total,
        frontier_significance=total,
        science_tech_editorial_reason_codes=("explicit_science_technology_education",),
        science_tech_content_signals=signals,
        product_matrix_fit_v2=total,
        product_matrix_v2_direction_ids=directions,
        priority_title="标题包含教育部也不能证明官方",
        priority_summary="持久化治理摘要",
        prohibited_marketing_risk=veto,
    )
    score = score_topic_candidate(candidate, as_of=_CUTOFF, config=TopicScoringConfig())
    return WeeklyGovernedCandidate(
        candidate=candidate,
        score=score,
        organization_type=organization_type,
        source_metadata_fingerprint=f"{suffix:064x}",
    )


def test_weekly_schedule_has_one_shanghai_due_window_and_durable_once_only() -> None:
    schedule = WeeklyEditionSchedule()

    assert (
        due_weekly_edition_week_start(
            datetime(2026, 8, 31, 0, 59, tzinfo=UTC),
            schedule=schedule,
        )
        is None
    )
    assert due_weekly_edition_week_start(
        datetime(2026, 8, 31, 1, 0, tzinfo=UTC),
        schedule=schedule,
    ) == date(2026, 8, 31)
    assert (
        due_weekly_edition_week_start(
            datetime(2026, 9, 1, 1, 0, tzinfo=UTC),
            schedule=schedule,
            completed_week_starts=frozenset({date(2026, 8, 31)}),
        )
        is None
    )
    assert (
        due_weekly_edition_week_start(
            datetime(2026, 9, 1, 1, 0, 1, tzinfo=UTC),
            schedule=schedule,
        )
        is None
    )


def test_weekly_selection_uses_official_metadata_then_role_affinity() -> None:
    official = _governed(1, age_days=1, organization_type="government", total=0.7)
    industry = _governed(
        2,
        age_days=2,
        organization_type="ai_company",
        cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
        signals=(ScienceTechContentSignal.PRODUCT_OR_SERVICE_RELEASE,),
        directions=("ai_theme_robotics_agent_safety_math_3d_hackathon",),
        total=0.75,
    )
    application = _governed(
        3,
        age_days=3,
        organization_type="education_institution",
        directions=("science_exploration_courses_and_camps",),
        total=0.74,
    )
    higher_generic = _governed(4, age_days=1, organization_type="ai_company", total=0.95)

    selection = select_weekly_articles(
        (official, industry, application, higher_generic),
        week_start=date(2026, 8, 31),
        cutoff=_CUTOFF,
        schedule=WeeklyEditionSchedule(),
    )

    assert [item.role.value for item in selection.selected] == [
        "official_anchor",
        "industry_trend",
        "application_case",
    ]
    assert selection.selected[0].event_id == official.candidate.event_id
    assert selection.selected[0].official_authority == "stored_government_organization_type"
    assert selection.selected[1].event_id == industry.candidate.event_id
    assert selection.selected[2].event_id == application.candidate.event_id
    assert selection.selected[1].affinity_reasons
    assert selection.selected[2].affinity_reasons


def test_weekly_selection_allows_bounded_official_lookback_with_two_current_items() -> None:
    official = _governed(1, age_days=10, organization_type="government")
    industry = _governed(
        2,
        age_days=2,
        organization_type="ai_company",
        cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
        signals=(ScienceTechContentSignal.COMPLETED_PROGRESS,),
    )
    application = _governed(
        3,
        age_days=3,
        organization_type="education_institution",
        directions=("science_exploration_courses_and_camps",),
    )

    selection = select_weekly_articles(
        (official, industry, application),
        week_start=date(2026, 8, 31),
        cutoff=_CUTOFF,
        schedule=WeeklyEditionSchedule(),
    )

    assert selection.selected[0].event_id == official.candidate.event_id
    assert selection.selected[0].selection_reason is WeeklySelectionReason.OFFICIAL_LOOKBACK


@pytest.mark.parametrize(
    ("official_age_days", "expected_reason"),
    [
        (7, WeeklySelectionReason.OFFICIAL_CURRENT_WINDOW),
        (14, WeeklySelectionReason.OFFICIAL_LOOKBACK),
        (15, WeeklySelectionReason.OFFICIAL_UNAVAILABLE_FALLBACK),
    ],
)
def test_weekly_official_windows_have_exact_7_and_14_day_boundaries(
    official_age_days: int,
    expected_reason: WeeklySelectionReason,
) -> None:
    official = _governed(
        1,
        age_days=official_age_days,
        organization_type="government",
        total=0.7,
    )
    # Weekly selection consumes the stored governed result; it does not re-score at the
    # edition cutoff. Keep that persisted result eligible to isolate the exact role window.
    official = replace(
        official,
        score=replace(
            official.score,
            eligible=True,
            passes_threshold=True,
            veto_codes=(),
        ),
    )
    current = (
        _governed(2, age_days=1, organization_type="ai_company", total=0.95),
        _governed(
            3,
            age_days=2,
            organization_type="ai_company",
            cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
        ),
        _governed(
            4,
            age_days=3,
            organization_type="education_institution",
            directions=("science_exploration_courses_and_camps",),
        ),
    )

    selection = select_weekly_articles(
        (official, *current),
        week_start=date(2026, 8, 31),
        cutoff=_CUTOFF,
        schedule=WeeklyEditionSchedule(),
    )

    assert selection.selected[0].selection_reason is expected_reason
    if official_age_days <= 14:
        assert selection.selected[0].event_id == official.candidate.event_id
    else:
        assert selection.selected[0].event_id != official.candidate.event_id


def test_weekly_selection_has_stable_empty_and_insufficient_errors() -> None:
    expired = tuple(
        _governed(
            suffix,
            age_days=15 + suffix,
            organization_type="government" if suffix == 1 else "ai_company",
        )
        for suffix in (1, 2, 3)
    )
    with pytest.raises(ValueError, match="no eligible candidates in the bounded windows"):
        select_weekly_articles(
            expired,
            week_start=date(2026, 8, 31),
            cutoff=_CUTOFF,
            schedule=WeeklyEditionSchedule(),
        )

    official_lookback = _governed(4, age_days=10, organization_type="government")
    only_current = _governed(5, age_days=1, organization_type="ai_company")
    with pytest.raises(ValueError, match="requires two distinct current-window"):
        select_weekly_articles(
            (official_lookback, only_current),
            week_start=date(2026, 8, 31),
            cutoff=_CUTOFF,
            schedule=WeeklyEditionSchedule(),
        )


def test_weekly_selection_does_not_infer_official_from_title_or_rescue_veto() -> None:
    title_only = _governed(1, age_days=1, organization_type="ai_company", total=0.95)
    vetoed_official = _governed(
        2,
        age_days=1,
        organization_type="government",
        veto=True,
        total=1.0,
    )
    second = _governed(
        3,
        age_days=2,
        organization_type="ai_company",
        cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
    )
    third = _governed(
        4,
        age_days=3,
        organization_type="education_institution",
        directions=("science_exploration_courses_and_camps",),
    )

    selection = select_weekly_articles(
        (title_only, vetoed_official, second, third),
        week_start=date(2026, 8, 31),
        cutoff=_CUTOFF,
        schedule=WeeklyEditionSchedule(),
    )

    assert (
        selection.selected[0].selection_reason
        is WeeklySelectionReason.OFFICIAL_UNAVAILABLE_FALLBACK
    )
    assert selection.selected[0].official_authority is None
    assert vetoed_official.candidate.event_id not in {item.event_id for item in selection.selected}


def test_weekly_selection_projection_is_strict_and_fingerprint_bound() -> None:
    selection = build_fixture_selection()
    projection = weekly_selection_projection(selection)

    assert weekly_selection_from_projection(projection) == selection
    projection["week_start"] = "2026-08-24"
    with pytest.raises(ValueError, match="fingerprint"):
        weekly_selection_from_projection(projection)


def test_weekly_selection_rejects_inconsistent_projection_truth() -> None:
    selection = build_fixture_selection()

    with pytest.raises(ValueError, match="official selection reason"):
        replace(
            selection.selected[0],
            selection_reason=WeeklySelectionReason.ROLE_AFFINITY,
        )
    with pytest.raises(ValueError, match="governed total must be finite"):
        replace(selection.selected[1], governed_total=float("nan"))
    with pytest.raises(ValueError, match="cutoff and week_start disagree"):
        select_weekly_articles(
            tuple(),
            week_start=date(2026, 8, 24),
            cutoff=_CUTOFF,
            schedule=WeeklyEditionSchedule(),
        )


@pytest.mark.asyncio
async def test_weekly_fixture_articles_have_role_specific_full_copy() -> None:
    artifacts = await build_fixture_children()
    articles = [json.loads(artifact.files["article.json"]) for artifact in artifacts]
    headings = [
        tuple(section["heading"] for section in article["sections"]) for article in articles
    ]
    serialized = [json.dumps(article, ensure_ascii=False) for article in articles]

    assert len(set(headings)) == 3
    assert "原文边界" in serialized[0]
    assert "需求是否真实存在" in serialized[1]
    assert "真正提出的问题" in serialized[2]
    assert "需求是否真实存在" not in serialized[0]
    assert "真正提出的问题" not in serialized[1]


@pytest.mark.asyncio
async def test_weekly_fixture_has_distinct_decoded_role_visuals_and_truthful_lineage() -> None:
    artifacts = await build_fixture_children()
    cover_hashes: list[str] = []
    cover_pixels: list[str] = []
    body_hash_sets: list[tuple[str, ...]] = []
    body_pixel_sets: list[tuple[str, ...]] = []

    for _role, artifact in zip(WeeklyArticleRole, artifacts, strict=True):
        article = json.loads(artifact.files["article.json"])
        body_assets = tuple(item for item in artifact.media if item.role == "body")
        cover = next(item for item in artifact.media if item.role == "cover")
        assert len(body_assets) == 3
        assert all(
            item.provider_execution == "not_claimed"
            and item.selection_method == "deterministic_fixture_semantic"
            and set(item.visible_character_labels) == {"xiao-sai", "sai-xiansheng"}
            for item in artifact.body_visuals
        )
        context_assets = tuple(item for item in artifact.media if item.role == "context")
        assert all(
            item.context_only_not_evidence is True
            and "不是新闻现场原图" in item.alt_text
            and item.caption is not None
            and "不构成事实证据" in item.caption
            and item.credit == "项目本地 fixture\N{FULLWIDTH VERTICAL LINE}非新闻原图"
            for item in context_assets
        )

        cover_body = artifact.files[cover.path]
        cover_size, cover_pixel_hash = _decoded_rgb_fingerprint(cover_body)
        assert cover_size == (1923, 818)
        assert cover.sha256 == sha256(cover_body).hexdigest()
        cover_hashes.append(cover.sha256)
        cover_pixels.append(cover_pixel_hash)

        role_hashes: list[str] = []
        role_pixels: list[str] = []
        for media, lineage in zip(body_assets, artifact.body_visuals, strict=True):
            body = artifact.files[media.path]
            size, pixel_hash = _decoded_rgb_fingerprint(body)
            assert size == (1536, 1024)
            assert media.sha256 == sha256(body).hexdigest() == lineage.output_sha256
            assert media.alt_text == lineage.scene_brief
            assert article["sections"][lineage.section_index]["blocks"][-1]["kind"] == "image"
            role_hashes.append(media.sha256)
            role_pixels.append(pixel_hash)
        assert len(set(role_hashes)) == 3
        assert len(set(role_pixels)) == 3
        body_hash_sets.append(tuple(role_hashes))
        body_pixel_sets.append(tuple(role_pixels))

    assert len(set(cover_hashes)) == 3
    assert len(set(cover_pixels)) == 3
    assert len(set(body_hash_sets)) == 3
    assert len(set(body_pixel_sets)) == 3
    assert len({item for hashes in body_hash_sets for item in hashes}) == 9
    assert len({item for pixels in body_pixel_sets for item in pixels}) == 9


@pytest.mark.asyncio
async def test_weekly_aggregate_is_deterministic_byte_preserving_and_zero_network(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def blocked_socket(*_args: object, **_kwargs: object) -> socket.socket:
        raise AssertionError("weekly fixture attempted a network request")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    monkeypatch.setattr(weekly_demo, "_PORTABLE_BASE_ARTIFACT", None)
    weekly_demo._fixture_role_visuals.cache_clear()
    weekly_demo._compose_role_cover.cache_clear()
    staged = await build_fixture_children()
    reports = {
        role: fixture_mobile_validation(artifact)
        for role, artifact in zip(WeeklyArticleRole, staged, strict=True)
    }
    finalized = await build_fixture_children(browser_validations=reports)
    articles = tuple(json.loads(artifact.files["article.json"]) for artifact in finalized)
    assert len({json.dumps(item["sections"], ensure_ascii=False) for item in articles}) == 3
    assert len({item["conclusion"] for item in articles}) == 3
    assert all(len(item["sections"]) >= 3 for item in articles)
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
        children=(children[0], children[1], children[2]),
        bindings=(bindings[0], bindings[1], bindings[2]),
    )
    repeated = build_weekly_edition_artifact(
        selection=selection,
        schedule=WeeklyEditionSchedule(),
        children=(children[0], children[1], children[2]),
        bindings=(bindings[0], bindings[1], bindings[2]),
    )
    first = write_weekly_edition_artifact(artifact, tmp_path / "first")
    second = write_weekly_edition_artifact(repeated, tmp_path / "second")

    assert artifact.zip_bytes == repeated.zip_bytes
    assert artifact.batch_fingerprint == repeated.batch_fingerprint
    assert (first / artifact.bundle_filename).read_bytes() == (
        second / repeated.bundle_filename
    ).read_bytes()
    index = json.loads(artifact.files["weekly-index.json"])
    manifest = json.loads(artifact.files["manifest.json"])
    assert index["article_count"] == 3
    assert [item["homepage_display"]["display_intent"] for item in index["articles"]] == [
        "pinned_primary",
        "standard",
        "standard",
    ]
    assert [item["homepage_display"]["cover"]["purpose"] for item in index["articles"]] == [
        "homepage_pinned_large_card_candidate",
        "homepage_standard_thumbnail_candidate",
        "homepage_standard_thumbnail_candidate",
    ]
    assert all(
        item["homepage_display"]["cover"]["source_aspect_ratio_intent"] == "2.35:1"
        and item["homepage_display"]["cover"]["wechat_system_crop_controlled"] is True
        for item in index["articles"]
    )
    assert index["homepage_operator_state"]["status"] == "not_published"
    assert index["wechat_homepage_ui_owner"] == "wechat_homepage_system"
    assert manifest["children"] == index["articles"]
    assert manifest["version"] == "official-account-weekly-edition-manifest-v3"
    assert manifest["homepage_operator_initial_state"] == index["homepage_operator_state"]
    assert manifest["homepage_display_policy_version"] == index["homepage_display_policy_version"]
    assert manifest["homepage_presentation_version"] == index["homepage_presentation_version"]
    checklist = json.loads(artifact.files["operator-publication-checklist.json"])
    assert checklist["article_count"] == 3
    assert checklist["initial_status"] == "not_published"
    assert (
        "群发功能 → 已发送 → 找到官方主推文章 → 更多 → 置顶到公众号主页"
        in checklist["steps"][3]["instruction"]
    )
    assert checklist["wechat_calls"] == 0
    assert checklist["official_article"]["cover_purpose"] == (
        "homepage_pinned_large_card_candidate"
    )
    assert [item["cover_purpose"] for item in checklist["standard_articles"]] == [
        "homepage_standard_thumbnail_candidate",
        "homepage_standard_thumbnail_candidate",
    ]
    assert checklist["article_order"] == [
        "official_anchor",
        "industry_trend",
        "application_case",
    ]
    index_html = artifact.files["index.html"]
    assert b"pinned_primary" not in index_html
    assert b"homepage_pinned_large_card_candidate" not in index_html
    assert b"homepage_standard_thumbnail_candidate" not in index_html
    assert "主页置顶候选".encode() in index_html
    assert "主页缩略图候选".encode() in index_html
    for projected_file in (
        artifact.files["README.md"],
        artifact.files["operator-publication-checklist.md"],
    ):
        assert b"pinned_primary" in projected_file
        assert b"standard" in projected_file
        assert b"homepage_pinned_large_card_candidate" in projected_file
        assert b"homepage_standard_thumbnail_candidate" in projected_file
    assert index["external_calls"] == {
        "news": 0,
        "model": 0,
        "embedding": 0,
        "image_generation": 0,
        "wechat": 0,
        "wecom": 0,
    }
    assert manifest["external_calls"] == index["external_calls"]
    assert manifest["fixture_truth"] == index["fixture_truth"]
    final_text_files = b"\n".join(
        body
        for path, body in artifact.files.items()
        if Path(path).suffix in {".html", ".json", ".md"}
    )
    assert b"authorized_local_generation_completed" not in final_text_files
    assert b'"image_generation_calls":3' not in final_text_files
    assert b"built_in_imagegen_reference_conditioned" not in final_text_files
    for child in children:
        prefix = f"articles/{child.role.ordinal:02d}-{child.role.value}/"
        for relative, body in child.files.items():
            assert artifact.files[f"{prefix}{relative}"] == body
        cover = next(
            item["homepage_display"]["cover"]
            for item in index["articles"]
            if item["role"] == child.role.value
        )
        child_manifest = json.loads(child.files["manifest.json"])
        child_cover = next(item for item in child_manifest["media"] if item["role"] == "cover")
        assert cover["sha256"] == child_cover["sha256"]
        assert cover["width"] == child_cover["width"]
        assert cover["height"] == child_cover["height"]
        with Image.open(BytesIO(child.files[child_cover["path"]])) as opened:
            opened.load()
            assert (cover["width"], cover["height"]) == opened.size

    tampered_manifest = json.loads(children[0].files["manifest.json"])
    tampered_cover = next(item for item in tampered_manifest["media"] if item["role"] == "cover")
    tampered_cover["width"] += 1
    tampered_files = dict(children[0].files)
    tampered_files["manifest.json"] = (
        json.dumps(
            tampered_manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    with pytest.raises(ValueError, match="media dimensions changed"):
        build_weekly_edition_artifact(
            selection=selection,
            schedule=WeeklyEditionSchedule(),
            children=(replace(children[0], files=tampered_files), children[1], children[2]),
            bindings=(bindings[0], bindings[1], bindings[2]),
        )


@pytest.mark.asyncio
async def test_weekly_aggregate_rejects_duplicate_role_cover_pixels_and_body_sets() -> None:
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

    source_cover = next(item for item in finalized[0].media if item.role == "cover")
    target_cover = next(item for item in finalized[1].media if item.role == "cover")
    source_cover_body = finalized[0].files[source_cover.path]
    comment = b"weekly-pixel-duplicate"
    jpeg_with_comment = (
        source_cover_body[:2]
        + b"\xff\xfe"
        + (len(comment) + 2).to_bytes(2, "big")
        + comment
        + source_cover_body[2:]
    )
    assert sha256(jpeg_with_comment).hexdigest() != source_cover.sha256
    assert _decoded_rgb_fingerprint(jpeg_with_comment) == _decoded_rgb_fingerprint(
        source_cover_body
    )
    pixel_duplicate = _rebind_child_media_bytes(
        children[1],
        {target_cover.path: jpeg_with_comment},
    )
    with pytest.raises(ValueError, match="role cover pixels must differ"):
        build_weekly_edition_artifact(
            selection=selection,
            schedule=WeeklyEditionSchedule(),
            children=(children[0], pixel_duplicate, children[2]),
            bindings=(bindings[0], bindings[1], bindings[2]),
        )

    source_bodies = tuple(item for item in finalized[0].media if item.role == "body")
    target_bodies = tuple(item for item in finalized[1].media if item.role == "body")
    repeated_body_set = _rebind_child_media_bytes(
        children[1],
        {
            target.path: finalized[0].files[source.path]
            for source, target in zip(source_bodies, target_bodies, strict=True)
        },
    )
    with pytest.raises(ValueError, match="role body media sets must differ"):
        build_weekly_edition_artifact(
            selection=selection,
            schedule=WeeklyEditionSchedule(),
            children=(children[0], repeated_body_set, children[2]),
            bindings=(bindings[0], bindings[1], bindings[2]),
        )

    one_repeated_body = _rebind_child_media_bytes(
        children[1],
        {target_bodies[0].path: finalized[0].files[source_bodies[0].path]},
    )
    with pytest.raises(ValueError, match="body image hashes must all differ"):
        build_weekly_edition_artifact(
            selection=selection,
            schedule=WeeklyEditionSchedule(),
            children=(children[0], one_repeated_body, children[2]),
            bindings=(bindings[0], bindings[1], bindings[2]),
        )

    metadata_only_bodies = {
        target.path: (
            finalized[0].files[source.path][:2]
            + b"\xff\xfe"
            + (len(comment) + 3).to_bytes(2, "big")
            + comment
            + bytes((source.ordinal,))
            + finalized[0].files[source.path][2:]
        )
        for source, target in zip(source_bodies, target_bodies, strict=True)
    }
    for source, target in zip(source_bodies, target_bodies, strict=True):
        mutated = metadata_only_bodies[target.path]
        assert sha256(mutated).hexdigest() != source.sha256
        assert _decoded_rgb_fingerprint(mutated) == _decoded_rgb_fingerprint(
            finalized[0].files[source.path]
        )
    pixel_duplicate_body_set = _rebind_child_media_bytes(children[1], metadata_only_bodies)
    with pytest.raises(ValueError, match="role body pixel sets must differ"):
        build_weekly_edition_artifact(
            selection=selection,
            schedule=WeeklyEditionSchedule(),
            children=(children[0], pixel_duplicate_body_set, children[2]),
            bindings=(bindings[0], bindings[1], bindings[2]),
        )

    one_metadata_only_body = _rebind_child_media_bytes(
        children[1],
        {target_bodies[0].path: metadata_only_bodies[target_bodies[0].path]},
    )
    with pytest.raises(ValueError, match="body image pixels must all differ"):
        build_weekly_edition_artifact(
            selection=selection,
            schedule=WeeklyEditionSchedule(),
            children=(children[0], one_metadata_only_body, children[2]),
            bindings=(bindings[0], bindings[1], bindings[2]),
        )


def test_weekly_homepage_operator_state_requires_explicit_linear_confirmations(
    tmp_path: Path,
) -> None:
    initial = initial_weekly_homepage_operator_state(
        batch_fingerprint="a" * 64,
        official_article_fingerprint="b" * 64,
    )
    assert initial.status is WeeklyHomepagePublicationStatus.NOT_PUBLISHED
    assert (
        weekly_homepage_operator_state_from_projection(
            weekly_homepage_operator_state_projection(initial)
        )
        == initial
    )

    publication = WeeklyHomepageOperatorEvent(
        event_id=UUID("20000000-0000-4000-8000-000000000001"),
        kind=WeeklyHomepageOperatorEventKind.PUBLICATION_CONFIRMED,
        occurred_at=datetime(2026, 9, 7, 2, tzinfo=UTC),
        actor_reference="ops-local-001",
        batch_fingerprint=initial.batch_fingerprint,
        official_article_fingerprint=initial.official_article_fingerprint,
        published_url="https://mp.weixin.qq.com/s/local-confirmed-article",
    )
    awaiting = apply_weekly_homepage_operator_event(initial, publication)
    assert awaiting.status is WeeklyHomepagePublicationStatus.AWAITING_MANUAL_PIN
    assert build_weekly_homepage_operator_state_sidecar(awaiting) == (
        build_weekly_homepage_operator_state_sidecar(awaiting)
    )
    awaiting_path = write_weekly_homepage_operator_state_sidecar(awaiting, tmp_path)
    assert awaiting_path.read_bytes() == build_weekly_homepage_operator_state_sidecar(awaiting)
    with pytest.raises(FileExistsError):
        write_weekly_homepage_operator_state_sidecar(awaiting, tmp_path)

    pin = WeeklyHomepageOperatorEvent(
        event_id=UUID("20000000-0000-4000-8000-000000000002"),
        kind=WeeklyHomepageOperatorEventKind.HOMEPAGE_PIN_CONFIRMED,
        occurred_at=datetime(2026, 9, 7, 2, 5, tzinfo=UTC),
        actor_reference="ops-local-001",
        batch_fingerprint=initial.batch_fingerprint,
        official_article_fingerprint=initial.official_article_fingerprint,
    )
    confirmed = apply_weekly_homepage_operator_event(awaiting, pin)
    assert confirmed.status is WeeklyHomepagePublicationStatus.CONFIRMED
    assert len(confirmed.events) == 2
    assert (
        weekly_homepage_operator_state_from_projection(
            weekly_homepage_operator_state_projection(confirmed)
        )
        == confirmed
    )
    sidecar = json.loads(build_weekly_homepage_operator_state_sidecar(confirmed))
    assert sidecar["wechat_calls"] == 0
    assert sidecar["immutable_weekly_batch_unchanged"] is True
    assert sidecar["operator_state"]["status"] == "confirmed"

    with pytest.raises(ValueError, match="transition is not allowed"):
        apply_weekly_homepage_operator_event(initial, pin)
    with pytest.raises(ValueError, match="already applied"):
        apply_weekly_homepage_operator_event(awaiting, publication)
    with pytest.raises(ValueError, match="identity changed"):
        apply_weekly_homepage_operator_event(
            initial,
            replace(publication, batch_fingerprint="c" * 64),
        )
    with pytest.raises(ValueError, match="time moved backwards"):
        apply_weekly_homepage_operator_event(
            awaiting,
            replace(pin, occurred_at=publication.occurred_at - timedelta(seconds=1)),
        )
    tampered = weekly_homepage_operator_state_projection(confirmed)
    tampered["state_fingerprint"] = "c" * 64
    with pytest.raises(ValueError, match="fingerprint changed"):
        weekly_homepage_operator_state_from_projection(tampered)

    type_drift = weekly_homepage_operator_state_projection(confirmed)
    type_drift["events"][0]["actor_reference"] = 7
    with pytest.raises(ValueError, match="projection strings are invalid"):
        weekly_homepage_operator_state_from_projection(type_drift)

    immutable_batch = tmp_path / "immutable-weekly-batch"
    immutable_batch.mkdir()
    (immutable_batch / "manifest.json").write_text(
        '{"bundle_version":"official-account-weekly-edition-bundle-v2"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="outside the immutable batch"):
        write_weekly_homepage_operator_state_sidecar(
            confirmed,
            immutable_batch / "operator-states",
        )
    assert not (immutable_batch / "operator-states").exists()


@pytest.mark.parametrize(
    "published_url",
    [
        None,
        "http://mp.weixin.qq.com/s/not-https",
        "https://example.com/s/not-wechat",
        "https://mp.weixin.qq.com/not-a-published-article",
        "https://mp.weixin.qq.com/s/",
        "https://mp.weixin.qq.com/s",
        "https://mp.weixin.qq.com:443/s/not-default-port",
        "https://operator@mp.weixin.qq.com/s/userinfo",
        "https://mp.weixin.qq.com/s/line\nbreak",
        "https://mp.weixin.qq.com/s/非-ascii",
    ],
)
def test_weekly_publication_confirmation_requires_wechat_publication_url(
    published_url: str | None,
) -> None:
    with pytest.raises(ValueError, match="publication URL"):
        WeeklyHomepageOperatorEvent(
            event_id=UUID("20000000-0000-4000-8000-000000000003"),
            kind=WeeklyHomepageOperatorEventKind.PUBLICATION_CONFIRMED,
            occurred_at=datetime(2026, 9, 7, 2, tzinfo=UTC),
            actor_reference="ops-local-001",
            batch_fingerprint="a" * 64,
            official_article_fingerprint="b" * 64,
            published_url=published_url,
        )


@pytest.mark.parametrize(
    "actor_reference",
    ["/root/private", "ops@example.com", " leading", "line\nbreak", ""],
)
def test_weekly_operator_reference_is_safe_and_opaque(actor_reference: str) -> None:
    with pytest.raises(ValueError, match="operator reference"):
        WeeklyHomepageOperatorEvent(
            event_id=UUID("20000000-0000-4000-8000-000000000004"),
            kind=WeeklyHomepageOperatorEventKind.PUBLICATION_CONFIRMED,
            occurred_at=datetime(2026, 9, 7, 2, tzinfo=UTC),
            actor_reference=actor_reference,
            batch_fingerprint="a" * 64,
            official_article_fingerprint="b" * 64,
            published_url="https://mp.weixin.qq.com/s/valid-article",
        )


@pytest.mark.asyncio
async def test_weekly_loader_rejects_tampered_child_and_writer_never_overwrites(
    tmp_path: Path,
) -> None:
    staged = await build_fixture_children()
    reports = {
        role: fixture_mobile_validation(artifact)
        for role, artifact in zip(WeeklyArticleRole, staged, strict=True)
    }
    finalized = await build_fixture_children(browser_validations=reports)
    child_paths = tuple(
        write_editor_handoff_v2_artifact(artifact, tmp_path / role.value)
        for role, artifact in zip(WeeklyArticleRole, finalized, strict=True)
    )
    loaded = tuple(
        load_finalized_v2_child(path, role=role)
        for role, path in zip(WeeklyArticleRole, child_paths, strict=True)
    )
    selection = build_fixture_selection()
    bindings = tuple(
        bind_weekly_child(selected=selected, child=child)
        for selected, child in zip(selection.selected, loaded, strict=True)
    )
    artifact = build_weekly_edition_artifact(
        selection=selection,
        schedule=WeeklyEditionSchedule(),
        children=(loaded[0], loaded[1], loaded[2]),
        bindings=(bindings[0], bindings[1], bindings[2]),
    )
    output = tmp_path / "weekly"
    write_weekly_edition_artifact(artifact, output)
    with pytest.raises(FileExistsError):
        write_weekly_edition_artifact(artifact, output)

    (child_paths[0] / "article-body.html").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match=r"size|checksum"):
        load_finalized_v2_child(
            child_paths[0],
            role=WeeklyArticleRole.OFFICIAL_ANCHOR,
        )


@pytest.mark.asyncio
async def test_weekly_aggregate_rejects_duplicate_or_cross_wired_children() -> None:
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
    duplicate = replace(children[1], run_id=children[0].run_id)
    duplicate_bindings = (
        bind_weekly_child(selected=selection.selected[0], child=children[0]),
        bind_weekly_child(selected=selection.selected[1], child=duplicate),
        bind_weekly_child(selected=selection.selected[2], child=children[2]),
    )
    with pytest.raises(ValueError, match="identities must differ"):
        build_weekly_edition_artifact(
            selection=selection,
            schedule=WeeklyEditionSchedule(),
            children=(children[0], duplicate, children[2]),
            bindings=duplicate_bindings,
        )

    bindings = (
        bind_weekly_child(selected=selection.selected[0], child=children[0]),
        bind_weekly_child(selected=selection.selected[1], child=children[1]),
        bind_weekly_child(selected=selection.selected[2], child=children[2]),
    )
    with pytest.raises(ValueError, match="binding role order changed"):
        build_weekly_edition_artifact(
            selection=selection,
            schedule=WeeklyEditionSchedule(),
            children=(children[0], children[1], children[2]),
            bindings=(bindings[1], bindings[0], bindings[2]),
        )
