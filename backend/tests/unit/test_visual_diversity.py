from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.domain.content_slots import ContentSlot
from app.domain.visual_brief import (
    AcceptedVisualContext,
    VisualCategory,
    VisualReferenceDescriptor,
    VisualReferenceRole,
    build_visual_brief,
)
from app.domain.visual_diversity import (
    ControlledVisualPlan,
    RecentVisualPlan,
    VisualCamera,
    VisualCast,
    VisualComposition,
    VisualScene,
    VisualSlotTone,
    VisualSubject,
    build_controlled_visual_prompt_bundle,
    build_visual_plan_bundle,
    controlled_image_request_fingerprint,
    controlled_plan_prompt_lines,
)


def _recent(plan: ControlledVisualPlan, *, day: date, slot: ContentSlot) -> RecentVisualPlan:
    return RecentVisualPlan(
        business_date=day,
        content_slot=slot,
        plan_fingerprint=plan.fingerprint,
        scene=plan.scene,
        composition=plan.composition,
        camera=plan.camera,
        cast=plan.cast,
        subject=plan.subject,
    )


def test_controlled_vocabularies_have_the_approved_breadth() -> None:
    assert len(VisualScene) == 10
    assert len(VisualComposition) == 8
    assert len(VisualCamera) == 5
    assert len(VisualCast) == 3
    assert len(VisualSlotTone) == 3
    assert len(VisualSubject) == 8


@pytest.mark.parametrize(
    ("slot", "tone"),
    (
        (ContentSlot.MORNING, VisualSlotTone.FRESH_START),
        (ContentSlot.NOON, VisualSlotTone.ANALYTICAL_FOCUS),
        (ContentSlot.EVENING, VisualSlotTone.REFLECTIVE_DISCOVERY),
    ),
)
def test_slot_controls_tone_and_plan_is_deterministic(
    slot: ContentSlot, tone: VisualSlotTone
) -> None:
    arguments = {
        "category": VisualCategory.ROBOTICS,
        "business_date": date(2026, 8, 15),
        "content_slot": slot,
        "stable_seed": "event-version-1",
    }

    first = build_visual_plan_bundle(**arguments)
    second = build_visual_plan_bundle(**arguments)

    assert first == second
    assert first.primary.slot_tone is tone
    assert first.alternate.slot_tone is tone
    assert first.primary.major_signature != first.alternate.major_signature
    assert first.primary.fingerprint != first.alternate.fingerprint


@pytest.mark.parametrize(
    ("category", "allowed_subjects"),
    (
        (
            VisualCategory.ROBOTICS,
            {
                VisualSubject.ROBOT_ARM,
                VisualSubject.COMPETITION_PROTOTYPE,
                VisualSubject.AI_SENSOR_CONSOLE,
            },
        ),
        (
            VisualCategory.ASTRONOMY,
            {
                VisualSubject.TELESCOPE_STAR_MAP,
                VisualSubject.ROCKET_SATELLITE_MODEL,
                VisualSubject.SCIENCE_BOOK_MODEL,
            },
        ),
        (
            VisualCategory.READING,
            {
                VisualSubject.SCIENCE_BOOK_MODEL,
                VisualSubject.TELESCOPE_STAR_MAP,
                VisualSubject.EXPERIMENT_APPARATUS,
            },
        ),
        (
            VisualCategory.SCIENCE,
            {
                VisualSubject.SCIENCE_BOOK_MODEL,
                VisualSubject.EXPERIMENT_APPARATUS,
            },
        ),
    ),
)
def test_subject_is_constrained_by_stored_topic_category(
    category: VisualCategory, allowed_subjects: set[VisualSubject]
) -> None:
    bundle = build_visual_plan_bundle(
        category=category,
        business_date=date(2026, 8, 15),
        content_slot=ContentSlot.NOON,
        stable_seed=f"{category.value}-event",
    )

    assert bundle.primary.subject in allowed_subjects
    assert bundle.alternate.subject in allowed_subjects


def test_generic_science_does_not_invent_a_specific_frontier_subject() -> None:
    unsupported = {
        VisualSubject.ROBOT_ARM,
        VisualSubject.AI_SENSOR_CONSOLE,
        VisualSubject.TELESCOPE_STAR_MAP,
        VisualSubject.ROCKET_SATELLITE_MODEL,
        VisualSubject.COMPETITION_PROTOTYPE,
    }

    for ordinal in range(20):
        bundle = build_visual_plan_bundle(
            category=VisualCategory.SCIENCE,
            business_date=date(2026, 8, 15),
            content_slot=ContentSlot.MORNING,
            stable_seed=f"generic-science-{ordinal}",
        )
        assert bundle.primary.subject not in unsupported
        assert bundle.alternate.subject not in unsupported


def test_rolling_seven_day_history_produces_at_least_eight_complete_plans() -> None:
    day = date(2026, 8, 15)
    history: list[RecentVisualPlan] = []
    selected: list[ControlledVisualPlan] = []

    for ordinal in range(10):
        bundle = build_visual_plan_bundle(
            category=VisualCategory.ARTIFICIAL_INTELLIGENCE,
            business_date=day,
            content_slot=ContentSlot.NOON,
            stable_seed=f"same-category-event-{ordinal}",
            recent=tuple(history),
        )
        selected.append(bundle.primary)
        history.append(_recent(bundle.primary, day=day, slot=ContentSlot.NOON))

    assert len({plan.fingerprint for plan in selected}) >= 8
    assert len({plan.composition for plan in selected}) >= 3
    assert len({plan.camera for plan in selected}) >= 3
    assert len({plan.cast for plan in selected}) == 3


def test_dimension_reuse_relaxes_in_fixed_order_without_changing_plan_identity() -> None:
    day = date(2026, 8, 15)
    baseline = build_visual_plan_bundle(
        category=VisualCategory.ROBOTICS,
        business_date=day,
        content_slot=ContentSlot.NOON,
        stable_seed="relaxation-baseline",
    ).primary
    history = tuple(
        _recent(
            ControlledVisualPlan(
                category=baseline.category,
                scene=baseline.scene,
                composition=baseline.composition,
                camera=camera,
                cast=baseline.cast,
                slot_tone=baseline.slot_tone,
                subject=baseline.subject,
            ),
            day=day - timedelta(days=1),
            slot=ContentSlot.NOON,
        )
        for camera in VisualCamera
    )

    selected = build_visual_plan_bundle(
        category=VisualCategory.ROBOTICS,
        business_date=day,
        content_slot=ContentSlot.NOON,
        stable_seed="relaxation-next",
        recent=history,
    ).primary
    round_trip = ControlledVisualPlan.from_metadata(selected.as_metadata())
    without_reasons = ControlledVisualPlan(
        category=selected.category,
        scene=selected.scene,
        composition=selected.composition,
        camera=selected.camera,
        cast=selected.cast,
        slot_tone=selected.slot_tone,
        subject=selected.subject,
    )

    assert selected.relaxation_codes == ("reuse_camera",)
    assert selected.fingerprint != baseline.fingerprint
    assert selected.fingerprint == without_reasons.fingerprint
    assert round_trip == selected


def test_history_older_than_configured_window_does_not_change_plan() -> None:
    day = date(2026, 8, 15)
    baseline = build_visual_plan_bundle(
        category=VisualCategory.EXPERIMENT,
        business_date=day,
        content_slot=ContentSlot.MORNING,
        stable_seed="experiment-event",
    )
    old = _recent(
        baseline.primary,
        day=day - timedelta(days=7),
        slot=ContentSlot.MORNING,
    )

    with_old_history = build_visual_plan_bundle(
        category=VisualCategory.EXPERIMENT,
        business_date=day,
        content_slot=ContentSlot.MORNING,
        stable_seed="experiment-event",
        recent=(old,),
    )

    assert with_old_history == baseline


def test_plan_snapshot_round_trip_and_prompt_use_only_controlled_values() -> None:
    plan = build_visual_plan_bundle(
        category=VisualCategory.ASTRONOMY,
        business_date=date(2026, 8, 15),
        content_slot=ContentSlot.EVENING,
        stable_seed="astronomy-event",
    ).primary

    restored = ControlledVisualPlan.from_metadata(plan.as_metadata())
    lines = controlled_plan_prompt_lines(restored)

    assert restored == plan
    assert len(lines) == 6
    assert all("https://" not in line for line in lines)
    assert all("private/" not in line for line in lines)


def test_plan_builder_rejects_unbounded_inputs() -> None:
    with pytest.raises(ValueError, match="stable seed"):
        build_visual_plan_bundle(
            category=VisualCategory.SCIENCE,
            business_date=date(2026, 8, 15),
            content_slot=None,
            stable_seed="",
        )
    with pytest.raises(ValueError, match="history days"):
        build_visual_plan_bundle(
            category=VisualCategory.SCIENCE,
            business_date=date(2026, 8, 15),
            content_slot=None,
            stable_seed="event",
            history_days=31,
        )


def test_v3_prompt_preserves_brand_rules_without_leaking_raw_inputs() -> None:
    raw_marker = "RAW_NEWS_SECRET_MARKER"
    brief = build_visual_brief(
        AcceptedVisualContext(
            topic_title=f"人工智能教育 {raw_marker}",
            topic_summary=f"summary {raw_marker}",
            copywriting=f"copy {raw_marker}",
            image_prompt=f"legacy prompt {raw_marker}",
        ),
        version="visual-brief-v2-controlled-diversity",
    )
    plan = build_visual_plan_bundle(
        category=brief.category,
        business_date=date(2026, 8, 15),
        content_slot=ContentSlot.MORNING,
        stable_seed="controlled-prompt-event",
    ).primary
    references = tuple(
        VisualReferenceDescriptor(
            asset_id=character * 64,
            role=role,
            filename=f"private-{ordinal}.png",
            checksum=character * 64,
        )
        for ordinal, (character, role) in enumerate(
            (
                ("a", VisualReferenceRole.IDENTITY_REFERENCE),
                ("b", VisualReferenceRole.ACTION_REFERENCE),
                ("c", VisualReferenceRole.STYLE_REFERENCE),
            ),
            start=1,
        )
    )

    bundle = build_controlled_visual_prompt_bundle(brief, plan, references)

    assert bundle.prompt_version == "image-prompt-v3-controlled-diversity"
    assert bundle.pipeline_version == "image-pipeline-v3-controlled-diversity"
    assert "polished 3D cartoon" in bundle.prompt
    assert "deep science blue" in bundle.prompt
    assert "real child faces" in bundle.prompt
    assert "Brand signature (exact): 赛先生科学" in bundle.prompt
    assert "Main title (exact): 人工智能" in bundle.prompt
    assert "Subtitle (exact): 理解智能如何学习与反馈" in bundle.prompt
    assert "rounded title card" in bundle.prompt
    assert "without covering any character face, scientific object, or main action" in bundle.prompt
    assert "exactly the following three Chinese text lines and no other text" in bundle.prompt
    assert "Keywords (exact" not in bundle.prompt
    assert "Brand value (exact" not in bundle.prompt
    assert "守护好奇心" not in bundle.prompt
    assert plan.scene.value not in bundle.prompt
    assert raw_marker not in bundle.prompt
    assert all(reference.asset_id not in bundle.prompt for reference in references)
    assert all(reference.filename not in bundle.prompt for reference in references)
    assert len(bundle.prompt) <= 2_000


def test_v2_artifact_fingerprint_binds_both_reserved_plans_and_history() -> None:
    common = {
        "run_id": "run-1",
        "draft_version_id": "draft-1",
        "provider": "fake",
        "model": "gpt-image-2",
        "primary_prompt_fingerprint": "a" * 64,
        "alternate_prompt_fingerprint": "b" * 64,
        "primary_reference_sha256s": ("c" * 64,),
        "alternate_reference_sha256s": ("d" * 64,),
        "history_digest": "e" * 64,
    }

    first = controlled_image_request_fingerprint(**common)
    changed = controlled_image_request_fingerprint(
        **{**common, "alternate_prompt_fingerprint": "f" * 64}
    )

    assert first == controlled_image_request_fingerprint(**common)
    assert first != changed
