from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.application.ports.ip_assets import IpAssetQuery
from app.application.services.ip_asset_metadata_repair import apply_metadata_repair_plan
from app.domain.ip_asset_metadata_repair import (
    IpAssetMetadataMutationStatus,
    IpAssetMetadataRepairCallStatus,
    IpAssetMetadataRepairErrorCode,
    IpAssetMetadataRepairItemStatus,
    IpAssetMetadataRepairPlan,
    IpAssetMetadataRepairPlanItem,
    asset_set_fingerprint,
    changed_fields,
    content_commitment,
    metadata_fingerprint,
    plan_fingerprint,
    repair_metadata,
)
from app.domain.ip_assets import (
    IpAssetCharacter,
    IpAssetMembershipSource,
    IpAssetMetadata,
    IpAssetSource,
    IpAssetStatus,
    IpAssetType,
    validate_ip_asset_upload,
)
from app.infrastructure.db.ip_assets import PostgresIpAssetRepository
from app.infrastructure.db.models import (
    IpAssetDownloadDailyModel,
    IpAssetFavoriteModel,
    IpAssetModel,
    IpAssetProfileMembershipModel,
    IpAssetProfileModel,
)
from app.infrastructure.storage.minio_ip_asset_store import MinioIpAssetStore
from PIL import Image
from sqlalchemy import delete, func, select

from .conftest import IntegrationContext


def _png() -> bytes:
    seed = uuid4().int
    output = io.BytesIO()
    Image.new(
        "RGB",
        (96, 64),
        (seed & 255, (seed >> 8) & 255, (seed >> 16) & 255),
    ).save(output, format="PNG")
    return output.getvalue()


def _partial_plan(
    *,
    real_asset_ref: str,
    real_blob_sha256: str,
    before_metadata: IpAssetMetadata,
    target_metadata: IpAssetMetadata,
) -> IpAssetMetadataRepairPlan:
    before = repair_metadata(before_metadata)
    target = repair_metadata(target_metadata)
    fake_refs: list[str] = []
    candidate = 0
    while len(fake_refs) < 40:
        asset_ref = f"ipa_{candidate:020x}"
        candidate += 1
        if asset_ref != real_asset_ref:
            fake_refs.append(asset_ref)
    ordered_refs = tuple(sorted((real_asset_ref, *fake_refs)))
    items: list[IpAssetMetadataRepairPlanItem] = []
    changed_count = 0
    for index, asset_ref in enumerate(ordered_refs):
        commitment = content_commitment(
            real_blob_sha256 if asset_ref == real_asset_ref else f"{index + 1:064x}"
        )
        if index < 39:
            proposed = target if asset_ref == real_asset_ref else before
            changes = changed_fields(before, proposed)
            changed_count += bool(changes)
            items.append(
                IpAssetMetadataRepairPlanItem(
                    asset_ref=asset_ref,
                    content_commitment=commitment,
                    before_metadata=before,
                    suggestion_metadata=proposed,
                    proposed_metadata=proposed,
                    before_metadata_fingerprint=metadata_fingerprint(before),
                    proposed_metadata_fingerprint=metadata_fingerprint(proposed),
                    changed_fields=changes,
                    status=(
                        IpAssetMetadataRepairItemStatus.CHANGED
                        if changes
                        else IpAssetMetadataRepairItemStatus.UNCHANGED
                    ),
                    provider_call_status=IpAssetMetadataRepairCallStatus.COMPLETED,
                )
            )
        elif index == 39:
            items.append(
                IpAssetMetadataRepairPlanItem(
                    asset_ref=asset_ref,
                    content_commitment=commitment,
                    before_metadata=before,
                    before_metadata_fingerprint=metadata_fingerprint(before),
                    status=IpAssetMetadataRepairItemStatus.PROVIDER_FAILED,
                    error_code=IpAssetMetadataRepairErrorCode.PROVIDER_RATE_LIMITED,
                    provider_call_status=IpAssetMetadataRepairCallStatus.FAILED,
                )
            )
        else:
            items.append(
                IpAssetMetadataRepairPlanItem(
                    asset_ref=asset_ref,
                    content_commitment=commitment,
                    before_metadata=before,
                    before_metadata_fingerprint=metadata_fingerprint(before),
                    status=IpAssetMetadataRepairItemStatus.NOT_PROCESSED,
                    error_code=(IpAssetMetadataRepairErrorCode.NOT_CALLED_AFTER_TRANSIENT_FAILURE),
                    provider_call_status=IpAssetMetadataRepairCallStatus.NOT_CALLED,
                )
            )
    ordered = tuple(items)
    partial = IpAssetMetadataRepairPlan(
        created_at=datetime(2026, 9, 2, 12, 0, tzinfo=UTC),
        asset_set_fingerprint=asset_set_fingerprint(ordered),
        selected_count=41,
        scanned_count=40,
        suggested_count=39,
        changed_count=changed_count,
        unchanged_count=39 - changed_count,
        failed_count=2,
        provider_call_count=40,
        inter_request_pacing_seconds=2.0,
        items=ordered,
        plan_fingerprint="0" * 64,
    )
    return partial.model_copy(update={"plan_fingerprint": plan_fingerprint(partial)})


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_metadata_cas_preserves_nonmetadata_and_restores_dimensioned_tags(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresIpAssetRepository(integration_context.session_factory)
    store = MinioIpAssetStore(integration_context.settings)
    profile, created = await repository.bootstrap_profile(
        token_digest=hashlib.sha256(uuid4().bytes).hexdigest(),
        display_name="repair-integration",
        department="repair-integration",
    )
    assert created is True
    upload = validate_ip_asset_upload(
        filename="repair-private-name.png",
        declared_media_type="image/png",
        body=_png(),
    )
    descriptor = await store.put_immutable(upload)
    before = IpAssetMetadata(
        character=IpAssetCharacter.XIAO_SAI,
        asset_type=IpAssetType.FULL_BODY_ACTION,
        department="repair-department",
        contributor="repair-contributor",
        emotion="平静",
        action="站立",
        scene="实验室",
        intended_use="内部素材",
        style="3D",
        tags=("original-free",),
    )
    asset, asset_created = await repository.create_asset(
        upload=upload,
        metadata=before,
        descriptor=descriptor,
        source_kind=IpAssetSource.UPLOADED,
        semantic_enabled=False,
        membership_profile_id=profile.id,
        membership_source=IpAssetMembershipSource.UPLOADED,
    )
    assert asset_created is True
    try:
        assert await repository.favorite_asset(
            profile_id=profile.id, asset_ref=asset.asset_ref, favorite=True
        )
        await repository.increment_downloads(
            asset_ids=(asset.id,), business_date=datetime.now(UTC).date()
        )
        state = await repository.get_repairable_metadata(asset.asset_ref)
        assert state is not None
        assert state.metadata.tags == ("original-free",)
        assert set(state.asset.tags) >= {
            "平静",
            "站立",
            "实验室",
            "内部素材",
            "3D",
            "original-free",
        }
        original_name = state.asset.canonical_name
        target = IpAssetMetadata(
            character=IpAssetCharacter.XIAO_SAI,
            asset_type=IpAssetType.PORTRAIT_AVATAR,
            emotion="开心",
            action="挥手",
            scene="空间站",
            intended_use="公众号配图",
            style="3D",
            tags=("original-free", "空间站"),
        )
        partial = _partial_plan(
            real_asset_ref=asset.asset_ref,
            real_blob_sha256=asset.blob_sha256,
            before_metadata=state.metadata,
            target_metadata=target,
        )
        with pytest.raises(ValueError, match="complete recognition plan"):
            await apply_metadata_repair_plan(repository=repository, store=store, plan=partial)
        unchanged_after_rejected_apply = await repository.get_repairable_metadata(asset.asset_ref)
        assert unchanged_after_rejected_apply is not None
        assert unchanged_after_rejected_apply.metadata == state.metadata

        applied = await repository.compare_and_swap_metadata(
            asset_ref=asset.asset_ref,
            expected_content_commitment=content_commitment(asset.blob_sha256),
            expected_metadata_fingerprint=metadata_fingerprint(state.metadata),
            target_metadata=target,
            target_metadata_fingerprint=metadata_fingerprint(target),
        )
        assert applied.status is IpAssetMetadataMutationStatus.APPLIED
        assert applied.state is not None
        assert applied.state.asset.canonical_name != original_name
        assert applied.state.asset.asset_ref == asset.asset_ref
        assert applied.state.asset.blob_sha256 == asset.blob_sha256
        assert applied.state.asset.department == before.department
        assert applied.state.asset.contributor == before.contributor
        assert applied.state.metadata.tags == ("original-free", "空间站")

        replayed = await repository.compare_and_swap_metadata(
            asset_ref=asset.asset_ref,
            expected_content_commitment=content_commitment(asset.blob_sha256),
            expected_metadata_fingerprint=metadata_fingerprint(state.metadata),
            target_metadata=target,
            target_metadata_fingerprint=metadata_fingerprint(target),
        )
        assert replayed.status is IpAssetMetadataMutationStatus.ALREADY_APPLIED

        restored = await repository.compare_and_swap_metadata(
            asset_ref=asset.asset_ref,
            expected_content_commitment=content_commitment(asset.blob_sha256),
            expected_metadata_fingerprint=metadata_fingerprint(target),
            target_metadata=state.metadata,
            target_metadata_fingerprint=metadata_fingerprint(state.metadata),
        )
        assert restored.status is IpAssetMetadataMutationStatus.APPLIED
        assert restored.state is not None
        assert restored.state.metadata == state.metadata

        async with integration_context.session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(IpAssetFavoriteModel)
                    .where(IpAssetFavoriteModel.asset_id == asset.id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(IpAssetProfileMembershipModel)
                    .where(IpAssetProfileMembershipModel.asset_id == asset.id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.sum(IpAssetDownloadDailyModel.download_count)).where(
                        IpAssetDownloadDailyModel.asset_id == asset.id
                    )
                )
                == 1
            )

        async with integration_context.session_factory() as session:
            model = await session.get(IpAssetModel, asset.id)
            assert model is not None
            model.status = IpAssetStatus.FAILED.value
            await session.commit()
        page = await repository.list_assets(IpAssetQuery(department=before.department, limit=20))
        assert all(item.asset_ref != asset.asset_ref for item in page.items)
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(delete(IpAssetModel).where(IpAssetModel.id == asset.id))
            await session.execute(
                delete(IpAssetProfileModel).where(IpAssetProfileModel.id == profile.id)
            )
            await session.commit()
