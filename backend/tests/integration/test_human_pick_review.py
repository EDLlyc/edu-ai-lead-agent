# ruff: noqa: RUF001
"""Held human picks: nothing sends them but the operator's push; edits stay consistent."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.application.services.human_pick_review import push_human_pick
from app.application.services.material_package import review_material_package
from app.application.services.wecom_delivery import (
    _slot_auto_delivery_candidate_statement,
    enqueue_wecom_delivery,
)
from app.core.errors import ConflictError
from app.domain.human_pick_review import CopyRevision
from app.domain.image_generation import image_content_key
from app.infrastructure.db.content_slot_human_picks import (
    HumanPickRejectedError,
    create_human_pick,
    human_pick_push_deadline,
)
from app.infrastructure.db.human_pick_review import (
    load_held_human_pick,
    require_editable,
    save_copy_revision,
)
from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotScoreModel,
    ContentSlotSelectionModel,
    CopyDraftClaimModel,
    CopyDraftVersionModel,
    CopyGenerationRunModel,
    CopyIssueModel,
    CopyValidationResultModel,
    ImageArtifactModel,
    MaterialPackageModel,
    MaterialReviewModel,
    WeComDeliveryAttemptModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
)
from app.schemas.copy_generation import CopyIssue
from pydantic import SecretStr
from sqlalchemy import delete, select, update

from .conftest import IntegrationContext
from .test_content_slot_human_picks import _add_rejected_candidate, _scheduled_run_id
from .test_wecom_slot_delivery_concurrency import _seed_slot_delivery_lane

ORIGINAL = (
    "🔎【小赛洞察】\n夹具新闻\nAI 写的引导语✨\n新闻来源：夹具\n原文链接：https://example.org/a"
)
EDITED = (
    "🔎【小赛洞察】\n夹具新闻\n运营改过的引导语🔧\n新闻来源：夹具\n原文链接：https://example.org/a"
)


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _purge_held_picks(integration_context: IntegrationContext) -> AsyncIterator[None]:
    """Remove everything a held pick created, so migration tests can downgrade later."""
    yield
    async with integration_context.session_factory() as session:
        human_runs = select(ContentSlotRunModel.id).where(ContentSlotRunModel.trigger == "human")
        selections = select(ContentSlotSelectionModel.id).where(
            ContentSlotSelectionModel.run_id.in_(human_runs)
        )
        copy_runs = select(CopyGenerationRunModel.id).where(
            CopyGenerationRunModel.content_slot_selection_id.in_(selections)
        )
        packages = select(MaterialPackageModel.id).where(MaterialPackageModel.run_id.in_(copy_runs))
        drafts = select(CopyDraftVersionModel.id).where(CopyDraftVersionModel.run_id.in_(copy_runs))
        jobs = select(WeComDeliveryJobModel.id).where(
            WeComDeliveryJobModel.material_package_id.in_(packages)
        )
        await session.execute(
            delete(WeComDeliveryAttemptModel).where(WeComDeliveryAttemptModel.job_id.in_(jobs))
        )
        await session.execute(
            delete(WeComDeliveryJobModel).where(WeComDeliveryJobModel.id.in_(jobs))
        )
        await session.execute(
            delete(MaterialReviewModel).where(MaterialReviewModel.package_id.in_(packages))
        )
        await session.execute(
            delete(MaterialPackageModel).where(MaterialPackageModel.id.in_(packages))
        )
        await session.execute(
            delete(ImageArtifactModel).where(ImageArtifactModel.run_id.in_(copy_runs))
        )
        await session.execute(
            delete(CopyValidationResultModel).where(
                CopyValidationResultModel.draft_version_id.in_(drafts)
            )
        )
        await session.execute(
            delete(CopyIssueModel).where(CopyIssueModel.draft_version_id.in_(drafts))
        )
        await session.execute(
            delete(CopyDraftClaimModel).where(CopyDraftClaimModel.draft_version_id.in_(drafts))
        )
        await session.execute(
            update(CopyGenerationRunModel)
            .where(CopyGenerationRunModel.id.in_(copy_runs))
            .values(active_draft_version_id=None)
        )
        await session.execute(
            delete(CopyDraftVersionModel).where(CopyDraftVersionModel.id.in_(drafts))
        )
        await session.execute(
            delete(CopyGenerationRunModel).where(CopyGenerationRunModel.id.in_(copy_runs))
        )
        await session.execute(
            delete(WeComDeliveryWindowModel).where(WeComDeliveryWindowModel.lane_key != "slot")
        )
        await session.execute(
            delete(ContentSlotSelectionModel).where(ContentSlotSelectionModel.id.in_(selections))
        )
        await session.execute(
            delete(ContentSlotScoreModel).where(ContentSlotScoreModel.run_id.in_(human_runs))
        )
        await session.execute(
            delete(ContentSlotRunModel).where(ContentSlotRunModel.trigger == "human")
        )
        await session.commit()


async def _held_pick(
    context: IntegrationContext, *, target_at: datetime
) -> tuple[UUID, UUID, UUID, datetime]:
    """A human pick whose copy, image and package are ready (as the reconcilers leave it)."""

    _, _, business_date, profile = await _seed_slot_delivery_lane(context, target_at=target_at)
    base_run_id = await _scheduled_run_id(context, business_date)
    event_id = await _add_rejected_candidate(context, run_id=base_run_id, rank=4, veto=False)
    picked_at = target_at + timedelta(hours=1)
    async with context.session_factory() as session:
        pick = await create_human_pick(
            session,
            source_run_id=base_run_id,
            event_id=event_id,
            note=None,
            now=picked_at,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
        )
    run_id, selection = pick.run.id, pick.selection
    copy_run_id, draft_id, image_id, package_id = uuid4(), uuid4(), uuid4(), uuid4()
    image_sha = uuid4().hex + uuid4().hex
    async with context.session_factory() as session:
        copy_run = CopyGenerationRunModel(
            id=copy_run_id,
            daily_topic_selection_id=None,
            content_slot_selection_id=selection.id,
            topic_selection_run_id=None,
            business_date=business_date,
            timezone="Asia/Shanghai",
            scoring_profile=profile,
            decision_kind="selected",
            selected_event_id=selection.selected_event_id,
            selected_event_version_id=selection.selected_event_version_id,
            no_topic_code=None,
            status="accepted",
            pipeline_version="held-pick-fixture-v1",
            version_fingerprint=uuid4().hex + uuid4().hex,
            version_bundle={},
            active_draft_version_id=None,
            repair_count=0,
            completed_at=picked_at,
        )
        session.add(copy_run)
        await session.flush()
        session.add(
            CopyDraftVersionModel(
                id=draft_id,
                run_id=copy_run_id,
                version=1,
                repair_of_version_id=None,
                copywriting=ORIGINAL,
                parent_takeaway="fixture takeaway",
                interaction="fixture interaction",
                source_note="fixture source",
                image_prompt="fixture image",
                provider="fake",
                model="fake",
                request_fingerprint=uuid4().hex + uuid4().hex,
                provider_request_id=None,
                prompt_version="fixture-v1",
                schema_version="fixture-v1",
                rule_version="moments-rules-v13-headline-hook",
                validation_passed=True,
                audit_accepted=True,
            )
        )
        await session.flush()
        copy_run.active_draft_version_id = draft_id
        session.add(
            CopyValidationResultModel(
                id=uuid4(),
                draft_version_id=draft_id,
                passed=True,
                rule_version="moments-rules-v13-headline-hook",
                result_fingerprint=uuid4().hex + uuid4().hex,
            )
        )
        session.add(
            CopyDraftClaimModel(
                id=uuid4(),
                draft_version_id=draft_id,
                claim_key="opinion-1",
                ordinal=0,
                kind="opinion",
                text="和孩子一起动手试试。",
            )
        )
        session.add(
            CopyIssueModel(
                id=uuid4(),
                draft_version_id=draft_id,
                stage="deterministic",
                audit_id=None,
                ordinal=0,
                code="copy_emoji_count",
                severity="warning",
                field_name="copywriting",
                claim_key=None,
                safe_message="AI 版本的提醒",
            )
        )
        session.add(
            ImageArtifactModel(
                id=image_id,
                run_id=copy_run_id,
                draft_version_id=draft_id,
                request_fingerprint=uuid4().hex + uuid4().hex,
                provider="fake",
                model="fake",
                prompt_version="fixture-v1",
                pipeline_version="fixture-v1",
                status="succeeded",
                validation_snapshot={"configured": True, "passed": True},
                audit_snapshot={"configured": False, "passed": None},
                media_type="image/png",
                width=1024,
                height=1024,
                byte_size=1024,
                sha256=image_sha,
                bucket=context.settings.minio_bucket,
                object_key=image_content_key(image_sha, "image/png"),
                storage_metadata={
                    "access": "private",
                    "immutable": True,
                    "content_addressed": True,
                },
                completed_at=picked_at,
            )
        )
        await session.flush()
        session.add(
            MaterialPackageModel(
                id=package_id,
                run_id=copy_run_id,
                draft_version_id=draft_id,
                image_artifact_id=image_id,
                package_version=1,
                request_fingerprint=uuid4().hex + uuid4().hex,
                status="awaiting_manual_use",
                topic_snapshot={},
                copy_snapshot={"copywriting": ORIGINAL, "draft_version_id": str(draft_id)},
                source_snapshot=[],
                brand_snapshot=[],
                validation_snapshot={"passed": True, "issues": []},
                audit_snapshot={"accepted": True},
                version_snapshot={},
                review_status="pending",
            )
        )
        await session.commit()
    return run_id, package_id, draft_id, picked_at


def _wecom_settings(context: IntegrationContext):  # type: ignore[no-untyped-def]
    return context.settings.model_copy(
        update={
            "content_enabled": True,
            "content_slot_mode_enabled": True,
            "content_morning_enabled": True,
            "content_noon_enabled": True,
            "content_evening_enabled": True,
            "wecom_enabled": True,
            "wecom_delivery_provider": "group_webhook",
            "wecom_group_webhook_key": SecretStr("held-pick-fixture-key"),
            "wecom_require_review_before_send": False,
        }
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_held_pick_is_sent_only_by_the_operator_push(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2097, 3, 2, 23, 30, tzinfo=UTC)
    run_id, package_id, _, picked_at = await _held_pick(integration_context, target_at=target_at)
    settings = _wecom_settings(integration_context)
    now = picked_at + timedelta(minutes=10)

    async with integration_context.session_factory() as session:
        run = await session.get(ContentSlotRunModel, run_id)
        assert run is not None
        # Held until 22:30 business time on the pick's day.
        assert run.expires_at == human_pick_push_deadline(run.business_date, "Asia/Shanghai")
        assert run.expires_at == datetime(2097, 3, 3, 14, 30, tzinfo=UTC)

        # The automatic sender never sees the held package.
        candidates = (
            await session.scalars(
                _slot_auto_delivery_candidate_statement(
                    settings=settings, business_date=run.business_date, now=now, limit=50
                )
            )
        ).all()
        assert package_id not in {package.id for package in candidates}
        # Nor can anything else send it formally.
        with pytest.raises(ConflictError, match="held"):
            await enqueue_wecom_delivery(
                session=session,
                package_id=package_id,
                recipient_id="default",
                mode="formal",
                include_copy=True,
                include_image=True,
                settings=settings,
                now=now,
            )
        await session.rollback()

    async with integration_context.session_factory() as session:
        job = await push_human_pick(
            session,
            run_id=run_id,
            reviewer="展示台审核",
            note=None,
            settings=settings,
            now=now,
        )
        job_id, window_id = job.id, job.delivery_window_id
    async with integration_context.session_factory() as session:
        job_row = await session.get(WeComDeliveryJobModel, job_id)
        package = await session.get(MaterialPackageModel, package_id)
        assert job_row is not None and package is not None
        assert (job_row.mode, job_row.include_copy, job_row.include_image) == ("formal", True, True)
        window = await session.get(WeComDeliveryWindowModel, window_id)
        assert window is not None
        assert window.lane_key == f"human-{run_id.hex}"
        assert (package.review_status, package.status) == ("approved", "completed")
        push = package.copy_snapshot["operator_push"]
        assert (push["edited"], push["reviewer"]) == (False, "展示台审核")
        assert push["copywriting"] == ORIGINAL
        review = await session.scalar(
            select(MaterialReviewModel).where(MaterialReviewModel.package_id == package_id)
        )
        assert review is not None
        assert (review.decision, review.reviewer) == ("approved", "展示台审核")

    # A second press does not send twice.
    async with integration_context.session_factory() as session:
        with pytest.raises(HumanPickRejectedError) as again:
            await push_human_pick(
                session, run_id=run_id, reviewer="展示台审核", note=None, settings=settings, now=now
            )
    assert again.value.code == "human_pick_already_pushed"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_push_is_refused_after_the_deadline_or_with_a_rule_error(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2097, 3, 9, 23, 30, tzinfo=UTC)
    run_id, package_id, draft_id, picked_at = await _held_pick(
        integration_context, target_at=target_at
    )
    settings = _wecom_settings(integration_context)

    async with integration_context.session_factory() as session:
        late = datetime(2097, 3, 10, 14, 31, tzinfo=UTC)  # 22:31 business time
        with pytest.raises(HumanPickRejectedError) as expired:
            await push_human_pick(
                session,
                run_id=run_id,
                reviewer="展示台审核",
                note=None,
                settings=settings,
                now=late,
            )
    assert expired.value.code == "human_pick_expired"

    async with integration_context.session_factory() as session:
        await session.execute(
            update(CopyDraftVersionModel)
            .where(CopyDraftVersionModel.id == draft_id)
            .values(validation_passed=False)
        )
        await session.commit()
    async with integration_context.session_factory() as session:
        with pytest.raises(HumanPickRejectedError) as invalid:
            await push_human_pick(
                session,
                run_id=run_id,
                reviewer="展示台审核",
                note=None,
                settings=settings,
                now=picked_at + timedelta(minutes=5),
            )
    assert invalid.value.code == "human_pick_copy_invalid"
    async with integration_context.session_factory() as session:
        package = await session.get(MaterialPackageModel, package_id)
        assert package is not None
        assert package.review_status == "pending"
        jobs = (
            await session.scalars(
                select(WeComDeliveryJobModel.id).where(
                    WeComDeliveryJobModel.material_package_id == package_id
                )
            )
        ).all()
        assert jobs == []


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_an_edit_updates_draft_validation_and_package_together(
    integration_context: IntegrationContext,
) -> None:
    target_at = datetime(2097, 3, 16, 23, 30, tzinfo=UTC)
    run_id, package_id, draft_id, picked_at = await _held_pick(
        integration_context, target_at=target_at
    )
    now = picked_at + timedelta(minutes=3)
    revision = CopyRevision(
        copywriting=EDITED,
        hook="运营改过的引导语🔧",
        hashtags=(),
        issues=(
            CopyIssue(
                code="copy_length",
                message="引导句应为一句8到50个汉字的话",
                severity="warning",
                field="copywriting",
            ),
        ),
    )
    async with integration_context.session_factory() as session:
        pick = await load_held_human_pick(session, run_id, lock=True)
        require_editable(pick, now=now)
        await save_copy_revision(session, pick, revision, reviewer="展示台审核", now=now)
        await session.commit()

    async with integration_context.session_factory() as session:
        draft = await session.get(CopyDraftVersionModel, draft_id)
        package = await session.get(MaterialPackageModel, package_id)
        assert draft is not None and package is not None
        # The long image requires the accepted draft and the package to agree.
        assert draft.copywriting == package.copy_snapshot["copywriting"] == EDITED
        assert draft.validation_passed is True
        assert draft.audit_accepted is True
        issues = (
            await session.scalars(
                select(CopyIssueModel.code).where(
                    CopyIssueModel.draft_version_id == draft_id,
                    CopyIssueModel.stage == "deterministic",
                )
            )
        ).all()
        assert issues == ["copy_length"]
        validation = await session.scalar(
            select(CopyValidationResultModel).where(
                CopyValidationResultModel.draft_version_id == draft_id
            )
        )
        assert validation is not None
        assert validation.result_fingerprint == package.validation_snapshot["result_fingerprint"]
        assert package.validation_snapshot["operator_edited"] is True
        assert [issue["code"] for issue in package.validation_snapshot["issues"]] == ["copy_length"]
        (edit,) = package.copy_snapshot["operator_edits"]
        # A before/after pair for evaluation and few-shot use.
        assert edit["model_copywriting"] == edit["previous_copywriting"] == ORIGINAL
        assert edit["copywriting"] == EDITED
        assert edit["draft_version_id"] == str(draft_id)
        assert edit["copy_run_id"] == str(package.run_id)
        assert edit["rule_issue_codes"] == ["copy_length"]
        assert edit["reviewer"] == "展示台审核"
        assert edit["llm_audit_repeated"] is False
        # Still held: an edit is not a push.
        assert package.review_status == "pending"

    # A second edit keeps the whole history.
    second = CopyRevision(
        copywriting=EDITED.replace("运营改过", "运营又改"),
        hook="运营又改的引导语🔧",
        hashtags=(),
        issues=(),
    )
    async with integration_context.session_factory() as session:
        pick = await load_held_human_pick(session, run_id, lock=True)
        await save_copy_revision(session, pick, second, reviewer="展示台审核", now=now)
        await session.commit()
    async with integration_context.session_factory() as session:
        package = await session.get(MaterialPackageModel, package_id)
        assert package is not None
        edits = package.copy_snapshot["operator_edits"]
        assert [edit["previous_copywriting"] for edit in edits] == [ORIGINAL, EDITED]
        # The model's text stays the first one, however many edits follow.
        assert [edit["model_copywriting"] for edit in edits] == [ORIGINAL, ORIGINAL]

    # Once pushed, the copy can no longer change.
    async with integration_context.session_factory() as session:
        await review_material_package(
            session=session,
            package_id=package_id,
            decision="approved",
            reviewer="展示台审核",
            note=None,
        )
    async with integration_context.session_factory() as session:
        pick = await load_held_human_pick(session, run_id)
        with pytest.raises(HumanPickRejectedError) as pushed:
            require_editable(pick, now=now)
    assert pushed.value.code == "human_pick_already_pushed"
