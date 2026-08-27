from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.application.ports.ip_assets import (
    IpAssetDerivativeRecord,
    IpAssetEmbeddingClaim,
    IpAssetGenerationClaim,
    IpAssetGenerationRecord,
    IpAssetGenerationReferenceRecord,
    IpAssetLeaderboardItemRecord,
    IpAssetLeaderboardRecord,
    IpAssetObjectDescriptor,
    IpAssetPage,
    IpAssetPersonalItemRecord,
    IpAssetPersonalPage,
    IpAssetProfileRecord,
    IpAssetQuery,
    IpAssetRecord,
    IpAssetVectorHit,
)
from app.core.errors import ConflictError
from app.domain.image_similarity import perceptual_hash_distance
from app.domain.ip_assets import (
    IpAssetCharacter,
    IpAssetLeaderboardPeriod,
    IpAssetMembershipSource,
    IpAssetMetadata,
    IpAssetOrientation,
    IpAssetSemanticStatus,
    IpAssetSource,
    IpAssetStatus,
    IpAssetType,
    ValidatedIpAssetUpload,
    canonical_name_base,
    versioned_canonical_name,
)
from app.domain.visual_retrieval import VisualEmbeddingIdentity, VisualEmbeddingResult
from app.infrastructure.db.models import (
    IpAssetDerivativeModel,
    IpAssetDownloadDailyModel,
    IpAssetEmbeddingJobModel,
    IpAssetEmbeddingModel,
    IpAssetFavoriteModel,
    IpAssetGenerationJobModel,
    IpAssetGenerationReferenceModel,
    IpAssetModel,
    IpAssetProfileMembershipModel,
    IpAssetProfileModel,
    IpAssetTagModel,
)

_NEAR_DUPLICATE_SCAN_LIMIT = 2_000
_NEAR_DUPLICATE_DISTANCE = 6


class PostgresIpAssetRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_by_sha256(self, sha256: str) -> IpAssetRecord | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(IpAssetModel).where(IpAssetModel.blob_sha256 == sha256)
            )
            return await _record_or_none(session, model)

    async def get_by_ref(self, asset_ref: str) -> IpAssetRecord | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(IpAssetModel).where(IpAssetModel.asset_ref == asset_ref)
            )
            return await _record_or_none(session, model)

    async def get_shared_by_ref(self, asset_ref: str) -> IpAssetRecord | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(IpAssetModel).where(
                    IpAssetModel.asset_ref == asset_ref,
                    IpAssetModel.shared_at.is_not(None),
                )
            )
            return await _record_or_none(session, model)

    async def get_accessible_by_ref(
        self, asset_ref: str, *, profile_id: UUID | None
    ) -> IpAssetRecord | None:
        async with self._session_factory() as session:
            statement = select(IpAssetModel).where(IpAssetModel.asset_ref == asset_ref)
            if profile_id is None:
                statement = statement.where(IpAssetModel.shared_at.is_not(None))
            else:
                membership = select(IpAssetProfileMembershipModel.id).where(
                    IpAssetProfileMembershipModel.profile_id == profile_id,
                    IpAssetProfileMembershipModel.asset_id == IpAssetModel.id,
                )
                statement = statement.where(
                    or_(IpAssetModel.shared_at.is_not(None), membership.exists())
                )
            return await _record_or_none(session, await session.scalar(statement))

    async def get_by_id(self, asset_id: UUID) -> IpAssetRecord | None:
        async with self._session_factory() as session:
            model = await session.get(IpAssetModel, asset_id)
            return await _record_or_none(session, model)

    async def get_derivative(
        self, *, asset_id: UUID, policy_version: str, kind: str
    ) -> IpAssetDerivativeRecord | None:
        async with self._session_factory() as session:
            model = await session.scalar(
                select(IpAssetDerivativeModel).where(
                    IpAssetDerivativeModel.asset_id == asset_id,
                    IpAssetDerivativeModel.policy_version == policy_version,
                    IpAssetDerivativeModel.kind == kind,
                )
            )
            return _derivative_record(model) if model is not None else None

    async def create_derivative(
        self,
        *,
        asset_id: UUID,
        policy_version: str,
        kind: str,
        source_sha256: str,
        descriptor: IpAssetObjectDescriptor,
        width: int,
        height: int,
    ) -> IpAssetDerivativeRecord:
        if kind != "thumbnail":
            raise ValueError("IP asset derivative kind is unsupported")
        async with self._session_factory() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"ip-asset-derivative:{asset_id}:{policy_version}:{kind}"},
            )
            existing = await session.scalar(
                select(IpAssetDerivativeModel).where(
                    IpAssetDerivativeModel.asset_id == asset_id,
                    IpAssetDerivativeModel.policy_version == policy_version,
                    IpAssetDerivativeModel.kind == kind,
                )
            )
            if existing is not None:
                _assert_derivative_matches(
                    existing,
                    source_sha256=source_sha256,
                    descriptor=descriptor,
                    width=width,
                    height=height,
                )
                await session.commit()
                return _derivative_record(existing)
            model = IpAssetDerivativeModel(
                id=uuid4(),
                asset_id=asset_id,
                policy_version=policy_version,
                kind=kind,
                source_sha256=source_sha256,
                media_type=descriptor.media_type,
                byte_size=descriptor.byte_size,
                width=width,
                height=height,
                bucket=descriptor.bucket,
                object_key=descriptor.object_key,
                sha256=descriptor.sha256,
            )
            session.add(model)
            await session.commit()
            return _derivative_record(model)

    async def create_asset(
        self,
        *,
        upload: ValidatedIpAssetUpload,
        metadata: IpAssetMetadata,
        descriptor: IpAssetObjectDescriptor,
        source_kind: IpAssetSource,
        parent_asset_id: UUID | None = None,
        semantic_enabled: bool,
        shared: bool = True,
        membership_profile_id: UUID | None = None,
        membership_source: IpAssetMembershipSource | None = None,
    ) -> tuple[IpAssetRecord, bool]:
        existing = await self.get_by_sha256(upload.sha256)
        if existing is not None:
            return (
                await self._link_existing_asset(
                    asset_id=existing.id,
                    shared=shared,
                    profile_id=membership_profile_id,
                    source=membership_source,
                ),
                False,
            )
        display_base, naming = canonical_name_base(metadata, upload.orientation)
        naming_key, slug_base = naming.split(":", 1)
        async with self._session_factory() as session:
            try:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"ip-asset-blob:{upload.sha256}"},
                )
                duplicate = await session.scalar(
                    select(IpAssetModel).where(IpAssetModel.blob_sha256 == upload.sha256)
                )
                if duplicate is not None:
                    await _apply_asset_relationships(
                        session,
                        asset=duplicate,
                        shared=shared,
                        profile_id=membership_profile_id,
                        source=membership_source,
                    )
                    tags = await _tags_for(session, (duplicate.id,))
                    record = _record(duplicate, tags.get(duplicate.id, ()))
                    await session.commit()
                    return record, False
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": naming_key},
                )
                maximum = await session.scalar(
                    select(func.max(IpAssetModel.name_version)).where(
                        IpAssetModel.naming_key == naming_key
                    )
                )
                version = int(maximum or 0) + 1
                canonical_name, canonical_slug = versioned_canonical_name(
                    display_base, slug_base, version
                )
                asset_id = uuid4()
                model = IpAssetModel(
                    id=asset_id,
                    asset_ref=f"ipa_{uuid4().hex[:20]}",
                    blob_sha256=upload.sha256,
                    perceptual_hash=upload.perceptual_hash,
                    safe_original_filename=upload.safe_original_filename,
                    media_type=upload.media_type,
                    byte_size=upload.byte_size,
                    width=upload.width,
                    height=upload.height,
                    has_alpha=upload.has_alpha,
                    orientation=upload.orientation.value,
                    bucket=descriptor.bucket,
                    object_key=descriptor.object_key,
                    naming_key=naming_key,
                    canonical_name=canonical_name,
                    canonical_slug=canonical_slug,
                    name_version=version,
                    character=metadata.character.value,
                    asset_type=metadata.asset_type.value,
                    source_kind=source_kind.value,
                    department=metadata.department,
                    contributor=metadata.contributor,
                    emotion=metadata.emotion,
                    action=metadata.action,
                    scene=metadata.scene,
                    intended_use=metadata.intended_use,
                    style=metadata.style,
                    status=IpAssetStatus.READY.value,
                    semantic_status=(
                        IpAssetSemanticStatus.QUEUED.value
                        if semantic_enabled
                        else IpAssetSemanticStatus.UNAVAILABLE.value
                    ),
                    failure_code=None,
                    parent_asset_id=parent_asset_id,
                    shared_at=datetime.now(UTC) if shared else None,
                )
                session.add(model)
                # Flush the parent first because these deliberately relationship-free ORM
                # models keep repository ownership explicit while database FKs remain strict.
                await session.flush()
                for dimension, value in _tag_rows(metadata):
                    session.add(
                        IpAssetTagModel(
                            id=uuid4(), asset_id=asset_id, dimension=dimension, value=value
                        )
                    )
                if semantic_enabled:
                    session.add(
                        IpAssetEmbeddingJobModel(
                            id=uuid4(), asset_id=asset_id, status="queued", attempt_count=0
                        )
                    )
                await _apply_asset_relationships(
                    session,
                    asset=model,
                    shared=shared,
                    profile_id=membership_profile_id,
                    source=membership_source,
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self.get_by_sha256(upload.sha256)
                if existing is not None:
                    return (
                        await self._link_existing_asset(
                            asset_id=existing.id,
                            shared=shared,
                            profile_id=membership_profile_id,
                            source=membership_source,
                        ),
                        False,
                    )
                raise
        created = await self.get_by_ref(model.asset_ref)
        if created is None:
            raise RuntimeError("created IP asset could not be projected")
        return created, True

    async def _link_existing_asset(
        self,
        *,
        asset_id: UUID,
        shared: bool,
        profile_id: UUID | None,
        source: IpAssetMembershipSource | None,
    ) -> IpAssetRecord:
        async with self._session_factory() as session:
            asset = await session.scalar(
                select(IpAssetModel).where(IpAssetModel.id == asset_id).with_for_update()
            )
            if asset is None:
                raise RuntimeError("existing IP asset disappeared")
            await _apply_asset_relationships(
                session,
                asset=asset,
                shared=shared,
                profile_id=profile_id,
                source=source,
            )
            await session.commit()
        linked = await self.get_by_id(asset_id)
        if linked is None:
            raise RuntimeError("linked IP asset disappeared")
        return linked

    async def list_assets(self, query: IpAssetQuery) -> IpAssetPage:
        async with self._session_factory() as session:
            statement = select(IpAssetModel).where(IpAssetModel.shared_at.is_not(None))
            statement = _apply_filters(statement, query, include_keyword=True)
            if query.cursor_created_at is not None and query.cursor_id is not None:
                statement = statement.where(
                    or_(
                        IpAssetModel.created_at < query.cursor_created_at,
                        and_(
                            IpAssetModel.created_at == query.cursor_created_at,
                            IpAssetModel.id < query.cursor_id,
                        ),
                    )
                )
            models = tuple(
                (
                    await session.scalars(
                        statement.order_by(
                            IpAssetModel.created_at.desc(), IpAssetModel.id.desc()
                        ).limit(query.limit + 1)
                    )
                ).unique()
            )
            has_more = len(models) > query.limit
            selected = models[: query.limit]
            tags = await _tags_for(session, tuple(model.id for model in selected))
            records = tuple(_record(model, tags.get(model.id, ())) for model in selected)
            last = selected[-1] if has_more and selected else None
            return IpAssetPage(
                items=records,
                next_cursor_created_at=last.created_at if last is not None else None,
                next_cursor_id=last.id if last is not None else None,
            )

    async def bootstrap_profile(
        self, *, token_digest: str, display_name: str, department: str
    ) -> tuple[IpAssetProfileRecord, bool]:
        async with self._session_factory() as session:
            profile_id = uuid4()
            inserted = await session.scalar(
                pg_insert(IpAssetProfileModel)
                .values(
                    id=profile_id,
                    profile_ref=f"ipp_{uuid4().hex[:20]}",
                    token_digest=token_digest,
                    display_name=display_name,
                    department=department,
                )
                .on_conflict_do_nothing(index_elements=["token_digest"])
                .returning(IpAssetProfileModel.id)
            )
            await session.commit()
        async with self._session_factory() as session:
            profile = await session.scalar(
                select(IpAssetProfileModel).where(IpAssetProfileModel.token_digest == token_digest)
            )
        if profile is None:
            raise RuntimeError("IP asset profile bootstrap disappeared")
        if profile.display_name != display_name or profile.department != department:
            raise ConflictError("local profile token was reused with different profile labels")
        return _profile_record(profile), inserted is not None

    async def get_profile_by_token_digest(self, token_digest: str) -> IpAssetProfileRecord | None:
        async with self._session_factory() as session:
            profile = await session.scalar(
                select(IpAssetProfileModel).where(IpAssetProfileModel.token_digest == token_digest)
            )
            return _profile_record(profile) if profile is not None else None

    async def list_personal_assets(
        self,
        *,
        profile_id: UUID,
        source: str,
        cursor_created_at: datetime | None,
        cursor_id: UUID | None,
        limit: int,
    ) -> IpAssetPersonalPage:
        membership = select(IpAssetProfileMembershipModel.id).where(
            IpAssetProfileMembershipModel.profile_id == profile_id,
            IpAssetProfileMembershipModel.asset_id == IpAssetModel.id,
        )
        favorite = select(IpAssetFavoriteModel.id).where(
            IpAssetFavoriteModel.profile_id == profile_id,
            IpAssetFavoriteModel.asset_id == IpAssetModel.id,
        )
        access_filter: ColumnElement[bool]
        if source in {"generated", "uploaded"}:
            membership = membership.where(IpAssetProfileMembershipModel.source == source)
            access_filter = membership.exists()
        elif source == "favorite":
            access_filter = and_(
                favorite.exists(),
                or_(IpAssetModel.shared_at.is_not(None), membership.exists()),
            )
        else:
            access_filter = or_(
                membership.exists(),
                and_(favorite.exists(), IpAssetModel.shared_at.is_not(None)),
            )
        async with self._session_factory() as session:
            statement = select(IpAssetModel).where(access_filter)
            if cursor_created_at is not None and cursor_id is not None:
                statement = statement.where(
                    or_(
                        IpAssetModel.created_at < cursor_created_at,
                        and_(
                            IpAssetModel.created_at == cursor_created_at,
                            IpAssetModel.id < cursor_id,
                        ),
                    )
                )
            models = tuple(
                await session.scalars(
                    statement.order_by(
                        IpAssetModel.created_at.desc(), IpAssetModel.id.desc()
                    ).limit(limit + 1)
                )
            )
            has_more = len(models) > limit
            selected = models[:limit]
            asset_ids = tuple(model.id for model in selected)
            tags = await _tags_for(session, asset_ids)
            memberships = await _membership_sources_for(session, profile_id, asset_ids)
            favorites = await _favorite_ids_for(session, profile_id, asset_ids)
            items = tuple(
                IpAssetPersonalItemRecord(
                    asset=_record(model, tags.get(model.id, ())),
                    membership_sources=memberships.get(model.id, ()),
                    favorite=model.id in favorites,
                )
                for model in selected
            )
            last = selected[-1] if has_more and selected else None
            return IpAssetPersonalPage(
                items=items,
                next_cursor_created_at=last.created_at if last is not None else None,
                next_cursor_id=last.id if last is not None else None,
            )

    async def favorite_asset(self, *, profile_id: UUID, asset_ref: str, favorite: bool) -> bool:
        async with self._session_factory() as session:
            membership = select(IpAssetProfileMembershipModel.id).where(
                IpAssetProfileMembershipModel.profile_id == profile_id,
                IpAssetProfileMembershipModel.asset_id == IpAssetModel.id,
            )
            asset_id = await session.scalar(
                select(IpAssetModel.id).where(
                    IpAssetModel.asset_ref == asset_ref,
                    IpAssetModel.status == IpAssetStatus.READY.value,
                    or_(IpAssetModel.shared_at.is_not(None), membership.exists()),
                )
            )
            if asset_id is None:
                return False
            if favorite:
                await session.execute(
                    pg_insert(IpAssetFavoriteModel)
                    .values(id=uuid4(), profile_id=profile_id, asset_id=asset_id)
                    .on_conflict_do_nothing(index_elements=["profile_id", "asset_id"])
                )
            else:
                await session.execute(
                    delete(IpAssetFavoriteModel).where(
                        IpAssetFavoriteModel.profile_id == profile_id,
                        IpAssetFavoriteModel.asset_id == asset_id,
                    )
                )
            await session.commit()
            return True

    async def favorite_asset_ids(
        self, *, profile_id: UUID, asset_ids: tuple[UUID, ...]
    ) -> frozenset[UUID]:
        if not asset_ids:
            return frozenset()
        async with self._session_factory() as session:
            return frozenset(
                await session.scalars(
                    select(IpAssetFavoriteModel.asset_id).where(
                        IpAssetFavoriteModel.profile_id == profile_id,
                        IpAssetFavoriteModel.asset_id.in_(asset_ids),
                    )
                )
            )

    async def share_generated_asset(self, *, profile_id: UUID, asset_ref: str) -> IpAssetRecord:
        async with self._session_factory() as session:
            asset = await session.scalar(
                select(IpAssetModel)
                .join(
                    IpAssetProfileMembershipModel,
                    IpAssetProfileMembershipModel.asset_id == IpAssetModel.id,
                )
                .where(
                    IpAssetModel.asset_ref == asset_ref,
                    IpAssetProfileMembershipModel.profile_id == profile_id,
                    IpAssetProfileMembershipModel.source == IpAssetMembershipSource.GENERATED.value,
                )
                .with_for_update()
            )
            if asset is None:
                raise ConflictError("only a generated personal asset can be shared")
            if asset.shared_at is None:
                asset.shared_at = datetime.now(UTC)
                asset.updated_at = asset.shared_at
            await session.commit()
        shared = await self.get_by_ref(asset_ref)
        if shared is None:
            raise RuntimeError("shared IP asset disappeared")
        return shared

    async def increment_downloads(
        self, *, asset_ids: tuple[UUID, ...], business_date: date
    ) -> None:
        unique_ids = tuple(dict.fromkeys(asset_ids))
        if not unique_ids:
            return
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            shared_ids = tuple(
                await session.scalars(
                    select(IpAssetModel.id).where(
                        IpAssetModel.id.in_(unique_ids),
                        IpAssetModel.status == IpAssetStatus.READY.value,
                        IpAssetModel.shared_at.is_not(None),
                    )
                )
            )
            for asset_id in shared_ids:
                await session.execute(
                    pg_insert(IpAssetDownloadDailyModel)
                    .values(
                        id=uuid4(),
                        asset_id=asset_id,
                        business_date=business_date,
                        download_count=1,
                        updated_at=now,
                    )
                    .on_conflict_do_update(
                        index_elements=["asset_id", "business_date"],
                        set_={
                            "download_count": IpAssetDownloadDailyModel.download_count + 1,
                            "updated_at": now,
                        },
                    )
                )
            await session.commit()

    async def leaderboard(
        self,
        *,
        period: IpAssetLeaderboardPeriod,
        start_date: date | None,
        limit: int,
    ) -> IpAssetLeaderboardRecord:
        async with self._session_factory() as session:
            statement = (
                select(IpAssetModel, func.sum(IpAssetDownloadDailyModel.download_count))
                .join(
                    IpAssetDownloadDailyModel,
                    IpAssetDownloadDailyModel.asset_id == IpAssetModel.id,
                )
                .where(
                    IpAssetModel.shared_at.is_not(None),
                    IpAssetModel.status == IpAssetStatus.READY.value,
                )
            )
            if start_date is not None:
                statement = statement.where(
                    IpAssetDownloadDailyModel.business_date >= start_date,
                    IpAssetDownloadDailyModel.business_date <= start_date + timedelta(days=29),
                )
            rows = tuple(
                (
                    await session.execute(
                        statement.group_by(IpAssetModel.id)
                        .order_by(
                            func.sum(IpAssetDownloadDailyModel.download_count).desc(),
                            IpAssetModel.created_at.desc(),
                            IpAssetModel.id.desc(),
                        )
                        .limit(limit)
                    )
                ).tuples()
            )
            tags = await _tags_for(session, tuple(model.id for model, _count in rows))
            return IpAssetLeaderboardRecord(
                period=period,
                generated_at=datetime.now(UTC),
                items=tuple(
                    IpAssetLeaderboardItemRecord(
                        asset=_record(model, tags.get(model.id, ())),
                        download_count=int(count),
                    )
                    for model, count in rows
                ),
            )

    async def find_near_duplicate(
        self, *, perceptual_hash: str, exclude_id: UUID | None = None
    ) -> tuple[str, int] | None:
        async with self._session_factory() as session:
            statement = (
                select(IpAssetModel.asset_ref, IpAssetModel.perceptual_hash)
                .order_by(IpAssetModel.created_at.desc(), IpAssetModel.id.desc())
                .where(IpAssetModel.shared_at.is_not(None))
            )
            if exclude_id is not None:
                statement = statement.where(IpAssetModel.id != exclude_id)
            rows = tuple(
                (await session.execute(statement.limit(_NEAR_DUPLICATE_SCAN_LIMIT))).tuples()
            )
        nearest: tuple[str, int] | None = None
        for asset_ref, candidate_hash in rows:
            distance = perceptual_hash_distance(perceptual_hash, candidate_hash)
            if distance <= _NEAR_DUPLICATE_DISTANCE and (
                nearest is None or (distance, asset_ref) < (nearest[1], nearest[0])
            ):
                nearest = (asset_ref, distance)
        return nearest

    async def enqueue_unavailable_embeddings(self, *, limit: int = 500) -> int:
        if limit < 1 or limit > 500:
            raise ValueError("IP asset embedding backfill limit must be between 1 and 500")
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            existing_job = select(IpAssetEmbeddingJobModel.id).where(
                IpAssetEmbeddingJobModel.asset_id == IpAssetModel.id
            )
            assets = tuple(
                await session.scalars(
                    select(IpAssetModel)
                    .where(
                        IpAssetModel.status == IpAssetStatus.READY.value,
                        IpAssetModel.semantic_status == IpAssetSemanticStatus.UNAVAILABLE.value,
                        ~existing_job.exists(),
                    )
                    .order_by(IpAssetModel.created_at, IpAssetModel.id)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            )
            for asset in assets:
                session.add(
                    IpAssetEmbeddingJobModel(
                        id=uuid4(), asset_id=asset.id, status="queued", attempt_count=0
                    )
                )
                asset.semantic_status = IpAssetSemanticStatus.QUEUED.value
                asset.updated_at = now
            await session.commit()
            return len(assets)

    async def claim_embedding_job(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int = 3
    ) -> IpAssetEmbeddingClaim | None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(IpAssetEmbeddingJobModel)
                .where(
                    or_(
                        and_(
                            IpAssetEmbeddingJobModel.status == "queued",
                            IpAssetEmbeddingJobModel.available_at <= now,
                            IpAssetEmbeddingJobModel.attempt_count < max_attempts,
                        ),
                        and_(
                            IpAssetEmbeddingJobModel.status == "running",
                            IpAssetEmbeddingJobModel.lease_expires_at < now,
                        ),
                    )
                )
                .order_by(IpAssetEmbeddingJobModel.created_at, IpAssetEmbeddingJobModel.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                await session.rollback()
                return None
            if job.attempt_count >= max_attempts:
                job.status = "failed"
                job.error_code = "provider_unavailable"
                job.completed_at = now
                job.lease_owner = None
                job.lease_token = None
                job.lease_expires_at = None
                asset = await session.get(IpAssetModel, job.asset_id)
                if asset is not None:
                    asset.semantic_status = IpAssetSemanticStatus.FAILED.value
                    asset.updated_at = now
                await session.commit()
                return None
            asset = await session.get(IpAssetModel, job.asset_id)
            if asset is None:
                job.status = "failed"
                job.error_code = "asset_missing"
                job.completed_at = now
                await session.commit()
                return None
            token = uuid4()
            job.status = "running"
            job.attempt_count += 1
            job.lease_owner = worker_id[:200]
            job.lease_token = token
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.error_code = None
            asset.semantic_status = IpAssetSemanticStatus.RUNNING.value
            tags = await _tags_for(session, (asset.id,))
            claim = IpAssetEmbeddingClaim(
                job_id=job.id,
                asset=_record(asset, tags.get(asset.id, ())),
                lease_token=token,
                attempt_number=job.attempt_count,
            )
            await session.commit()
            return claim

    async def renew_embedding_lease(
        self, *, claim: IpAssetEmbeddingClaim, lease_seconds: int
    ) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(IpAssetEmbeddingJobModel)
                .where(
                    IpAssetEmbeddingJobModel.id == claim.job_id,
                    IpAssetEmbeddingJobModel.status == "running",
                    IpAssetEmbeddingJobModel.lease_token == claim.lease_token,
                    IpAssetEmbeddingJobModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            if job is None:
                await session.rollback()
                return False
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            await session.commit()
            return True

    async def complete_embedding(
        self,
        *,
        claim: IpAssetEmbeddingClaim,
        embedding: VisualEmbeddingResult,
        identity: VisualEmbeddingIdentity,
    ) -> bool:
        if embedding.identity != identity:
            return False
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(IpAssetEmbeddingJobModel)
                .where(
                    IpAssetEmbeddingJobModel.id == claim.job_id,
                    IpAssetEmbeddingJobModel.status == "running",
                    IpAssetEmbeddingJobModel.lease_token == claim.lease_token,
                    IpAssetEmbeddingJobModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            if job is None:
                await session.rollback()
                return False
            await session.execute(
                pg_insert(IpAssetEmbeddingModel)
                .values(
                    id=uuid4(),
                    asset_id=claim.asset.id,
                    job_id=job.id,
                    source_sha256=claim.asset.blob_sha256,
                    embedding_input_sha256=embedding.input_sha256,
                    provider=identity.provider,
                    model=identity.model,
                    dimensions=identity.dimensions,
                    input_policy_version=identity.input_policy_version,
                    request_fingerprint=embedding.request_fingerprint,
                    vector=list(embedding.vector),
                )
                .on_conflict_do_nothing(index_elements=["job_id"])
            )
            asset = await session.get(IpAssetModel, claim.asset.id)
            if asset is None:
                await session.rollback()
                return False
            job.status = "succeeded"
            job.completed_at = now
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None
            asset.semantic_status = IpAssetSemanticStatus.READY.value
            asset.updated_at = now
            await session.commit()
            return True

    async def fail_embedding(self, *, claim: IpAssetEmbeddingClaim, error_code: str) -> bool:
        now = datetime.now(UTC)
        safe_code = (
            error_code
            if error_code
            in {"provider_unavailable", "input_normalization_failed", "invalid_provider_output"}
            else "provider_unavailable"
        )
        async with self._session_factory() as session:
            job = await session.scalar(
                select(IpAssetEmbeddingJobModel)
                .where(
                    IpAssetEmbeddingJobModel.id == claim.job_id,
                    IpAssetEmbeddingJobModel.status == "running",
                    IpAssetEmbeddingJobModel.lease_token == claim.lease_token,
                    IpAssetEmbeddingJobModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            if job is None:
                await session.rollback()
                return False
            asset = await session.get(IpAssetModel, claim.asset.id)
            job.status = "failed"
            job.error_code = safe_code
            job.completed_at = now
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None
            if asset is not None:
                asset.semantic_status = IpAssetSemanticStatus.FAILED.value
                asset.updated_at = now
            await session.commit()
            return True

    async def search_vectors(
        self,
        *,
        query: IpAssetQuery,
        embedding: VisualEmbeddingResult,
        identity: VisualEmbeddingIdentity,
    ) -> tuple[IpAssetVectorHit, ...]:
        if embedding.identity != identity:
            raise ValueError("IP asset query embedding identity mismatch")
        distance = IpAssetEmbeddingModel.vector.cosine_distance(list(embedding.vector)).label(
            "distance"
        )
        async with self._session_factory() as session:
            statement = (
                select(IpAssetModel, distance)
                .join(IpAssetEmbeddingModel, IpAssetEmbeddingModel.asset_id == IpAssetModel.id)
                .where(
                    IpAssetModel.status == IpAssetStatus.READY.value,
                    IpAssetModel.shared_at.is_not(None),
                    IpAssetEmbeddingModel.source_sha256 == IpAssetModel.blob_sha256,
                    IpAssetEmbeddingModel.provider == identity.provider,
                    IpAssetEmbeddingModel.model == identity.model,
                    IpAssetEmbeddingModel.dimensions == identity.dimensions,
                    IpAssetEmbeddingModel.input_policy_version == identity.input_policy_version,
                )
            )
            statement = _apply_filters(statement, query, include_keyword=False)
            rows = tuple(
                (
                    await session.execute(
                        statement.order_by(
                            distance, IpAssetModel.created_at.desc(), IpAssetModel.id.desc()
                        ).limit(query.limit)
                    )
                ).tuples()
            )
            tags = await _tags_for(session, tuple(model.id for model, _distance in rows))
            return tuple(
                IpAssetVectorHit(
                    record=_record(model, tags.get(model.id, ())),
                    similarity=max(-1.0, min(1.0, 1.0 - float(raw_distance))),
                )
                for model, raw_distance in rows
            )

    async def enqueue_generation(
        self,
        *,
        idempotency_key: str,
        request_fingerprint: str,
        prompt: str,
        metadata: IpAssetMetadata,
        ratio: str,
        profile_id: UUID | None,
        references: tuple[tuple[UUID, str], ...],
        provider: str,
        model: str,
    ) -> tuple[IpAssetGenerationRecord, bool]:
        async with self._session_factory() as session:
            job_id = uuid4()
            inserted_id = await session.scalar(
                pg_insert(IpAssetGenerationJobModel)
                .values(
                    id=job_id,
                    job_ref=f"ipg_{uuid4().hex[:20]}",
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    prompt=prompt,
                    character=metadata.character.value,
                    asset_type=metadata.asset_type.value,
                    department=metadata.department,
                    contributor=metadata.contributor,
                    ratio=ratio,
                    profile_id=profile_id,
                    reference_asset_id=references[0][0] if references else None,
                    provider=provider,
                    model=model,
                    status="queued",
                    attempt_count=0,
                )
                .on_conflict_do_nothing()
                .returning(IpAssetGenerationJobModel.id)
            )
            if inserted_id is not None:
                for ordinal, (asset_id, source_sha256) in enumerate(references):
                    session.add(
                        IpAssetGenerationReferenceModel(
                            id=uuid4(),
                            job_id=inserted_id,
                            ordinal=ordinal,
                            asset_id=asset_id,
                            source_sha256=source_sha256,
                        )
                    )
            await session.commit()
        if inserted_id is not None:
            async with self._session_factory() as session:
                created = await session.get(IpAssetGenerationJobModel, inserted_id)
                if created is None:
                    raise RuntimeError("created IP asset generation job disappeared")
                return _generation_record(
                    created, await _generation_references_for(session, created.id)
                ), True
        async with self._session_factory() as session:
            matches = tuple(
                await session.scalars(
                    select(IpAssetGenerationJobModel).where(
                        or_(
                            and_(
                                IpAssetGenerationJobModel.profile_id == profile_id,
                                IpAssetGenerationJobModel.idempotency_key == idempotency_key,
                            ),
                            IpAssetGenerationJobModel.request_fingerprint == request_fingerprint,
                        )
                    )
                )
            )
            if len(matches) != 1 or matches[0].request_fingerprint != request_fingerprint:
                raise ConflictError("generation idempotency key was reused for another request")
            references_found = await _generation_references_for(session, matches[0].id)
        return _generation_record(matches[0], references_found), False

    async def get_generation(
        self, job_ref: str, *, profile_id: UUID | None = None
    ) -> IpAssetGenerationRecord | None:
        async with self._session_factory() as session:
            statement = select(IpAssetGenerationJobModel).where(
                IpAssetGenerationJobModel.job_ref == job_ref
            )
            if profile_id is not None:
                statement = statement.where(
                    or_(
                        IpAssetGenerationJobModel.profile_id == profile_id,
                        IpAssetGenerationJobModel.profile_id.is_(None),
                    )
                )
            else:
                statement = statement.where(IpAssetGenerationJobModel.profile_id.is_(None))
            model = await session.scalar(statement)
            if model is None:
                return None
            return _generation_record(model, await _generation_references_for(session, model.id))

    async def claim_generation_job(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> IpAssetGenerationClaim | None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(IpAssetGenerationJobModel)
                .where(
                    or_(
                        and_(
                            IpAssetGenerationJobModel.status == "queued",
                            IpAssetGenerationJobModel.available_at <= now,
                            IpAssetGenerationJobModel.attempt_count < max_attempts,
                        ),
                        and_(
                            IpAssetGenerationJobModel.status == "running",
                            IpAssetGenerationJobModel.lease_expires_at < now,
                        ),
                    ),
                )
                .order_by(IpAssetGenerationJobModel.created_at, IpAssetGenerationJobModel.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                await session.rollback()
                return None
            if job.attempt_count >= max_attempts:
                job.status = "failed"
                job.error_code = "provider_unavailable"
                job.completed_at = now
                job.lease_owner = None
                job.lease_token = None
                job.lease_expires_at = None
                await session.commit()
                return None
            token = uuid4()
            job.status = "running"
            job.attempt_count += 1
            job.lease_owner = worker_id[:200]
            job.lease_token = token
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.started_at = job.started_at or now
            job.error_code = None
            references = await _generation_references_for(session, job.id)
            await session.commit()
            return IpAssetGenerationClaim(
                job=_generation_record(job, references), lease_token=token
            )

    async def renew_generation_lease(
        self, *, claim: IpAssetGenerationClaim, lease_seconds: int
    ) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(IpAssetGenerationJobModel)
                .where(
                    IpAssetGenerationJobModel.id == claim.job.id,
                    IpAssetGenerationJobModel.status == "running",
                    IpAssetGenerationJobModel.lease_token == claim.lease_token,
                    IpAssetGenerationJobModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            if job is None:
                await session.rollback()
                return False
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            await session.commit()
            return True

    async def complete_generation(
        self, *, claim: IpAssetGenerationClaim, output_asset_id: UUID
    ) -> bool:
        return await self._finish_generation(
            claim, output_asset_id=output_asset_id, error_code=None
        )

    async def complete_generation_asset(
        self,
        *,
        claim: IpAssetGenerationClaim,
        upload: ValidatedIpAssetUpload,
        metadata: IpAssetMetadata,
        descriptor: IpAssetObjectDescriptor,
        semantic_enabled: bool,
    ) -> IpAssetRecord | None:
        """Fence generated-asset visibility and job completion in one short transaction."""

        now = datetime.now(UTC)
        display_base, naming = canonical_name_base(metadata, upload.orientation)
        naming_key, slug_base = naming.split(":", 1)
        output_id: UUID
        async with self._session_factory() as session:
            job = await session.scalar(
                select(IpAssetGenerationJobModel)
                .where(
                    IpAssetGenerationJobModel.id == claim.job.id,
                    IpAssetGenerationJobModel.status == "running",
                    IpAssetGenerationJobModel.lease_token == claim.lease_token,
                    IpAssetGenerationJobModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            if job is None:
                await session.rollback()
                return None
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"ip-asset-blob:{upload.sha256}"},
            )
            duplicate = await session.scalar(
                select(IpAssetModel).where(IpAssetModel.blob_sha256 == upload.sha256)
            )
            if duplicate is not None:
                output_id = duplicate.id
            else:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": naming_key},
                )
                maximum = await session.scalar(
                    select(func.max(IpAssetModel.name_version)).where(
                        IpAssetModel.naming_key == naming_key
                    )
                )
                version = int(maximum or 0) + 1
                canonical_name, canonical_slug = versioned_canonical_name(
                    display_base, slug_base, version
                )
                output_id = uuid4()
                session.add(
                    IpAssetModel(
                        id=output_id,
                        asset_ref=f"ipa_{uuid4().hex[:20]}",
                        blob_sha256=upload.sha256,
                        perceptual_hash=upload.perceptual_hash,
                        safe_original_filename=upload.safe_original_filename,
                        media_type=upload.media_type,
                        byte_size=upload.byte_size,
                        width=upload.width,
                        height=upload.height,
                        has_alpha=upload.has_alpha,
                        orientation=upload.orientation.value,
                        bucket=descriptor.bucket,
                        object_key=descriptor.object_key,
                        naming_key=naming_key,
                        canonical_name=canonical_name,
                        canonical_slug=canonical_slug,
                        name_version=version,
                        character=metadata.character.value,
                        asset_type=metadata.asset_type.value,
                        source_kind=IpAssetSource.GENERATED.value,
                        department=metadata.department,
                        contributor=metadata.contributor,
                        emotion=metadata.emotion,
                        action=metadata.action,
                        scene=metadata.scene,
                        intended_use=metadata.intended_use,
                        style=metadata.style,
                        status=IpAssetStatus.READY.value,
                        semantic_status=(
                            IpAssetSemanticStatus.QUEUED.value
                            if semantic_enabled
                            else IpAssetSemanticStatus.UNAVAILABLE.value
                        ),
                        failure_code=None,
                        parent_asset_id=job.reference_asset_id,
                        shared_at=now if job.profile_id is None else None,
                    )
                )
                await session.flush()
                for dimension, value in _tag_rows(metadata):
                    session.add(
                        IpAssetTagModel(
                            id=uuid4(), asset_id=output_id, dimension=dimension, value=value
                        )
                    )
                if semantic_enabled:
                    session.add(
                        IpAssetEmbeddingJobModel(
                            id=uuid4(), asset_id=output_id, status="queued", attempt_count=0
                        )
                    )
            if job.profile_id is not None:
                await session.execute(
                    pg_insert(IpAssetProfileMembershipModel)
                    .values(
                        id=uuid4(),
                        profile_id=job.profile_id,
                        asset_id=output_id,
                        source=IpAssetMembershipSource.GENERATED.value,
                        generation_job_id=job.id,
                    )
                    .on_conflict_do_nothing(index_elements=["profile_id", "asset_id", "source"])
                )
            job.status = "succeeded"
            job.output_asset_id = output_id
            job.error_code = None
            job.completed_at = now
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None
            await session.commit()
        return await self.get_by_id(output_id)

    async def fail_generation(self, *, claim: IpAssetGenerationClaim, error_code: str) -> bool:
        safe_code = (
            error_code
            if error_code
            in {"provider_unavailable", "provider_rejected", "invalid_output", "lease_expired"}
            else "provider_unavailable"
        )
        return await self._finish_generation(claim, output_asset_id=None, error_code=safe_code)

    async def retry_generation(
        self, *, claim: IpAssetGenerationClaim, error_code: str, delay_seconds: int
    ) -> bool:
        now = datetime.now(UTC)
        safe_code = (
            error_code
            if error_code in {"provider_unavailable", "provider_rejected", "invalid_output"}
            else "provider_unavailable"
        )
        async with self._session_factory() as session:
            job = await session.scalar(
                select(IpAssetGenerationJobModel)
                .where(
                    IpAssetGenerationJobModel.id == claim.job.id,
                    IpAssetGenerationJobModel.status == "running",
                    IpAssetGenerationJobModel.lease_token == claim.lease_token,
                    IpAssetGenerationJobModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            if job is None:
                await session.rollback()
                return False
            job.status = "queued"
            job.available_at = now + timedelta(seconds=max(1, min(delay_seconds, 300)))
            job.error_code = safe_code
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None
            await session.commit()
            return True

    async def _finish_generation(
        self,
        claim: IpAssetGenerationClaim,
        *,
        output_asset_id: UUID | None,
        error_code: str | None,
    ) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(IpAssetGenerationJobModel)
                .where(
                    IpAssetGenerationJobModel.id == claim.job.id,
                    IpAssetGenerationJobModel.status == "running",
                    IpAssetGenerationJobModel.lease_token == claim.lease_token,
                    IpAssetGenerationJobModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            if job is None:
                await session.rollback()
                return False
            job.status = "succeeded" if output_asset_id is not None else "failed"
            job.output_asset_id = output_asset_id
            job.error_code = error_code
            job.completed_at = now
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None
            await session.commit()
            return True


def _apply_filters(
    statement: Select[Any], query: IpAssetQuery, *, include_keyword: bool
) -> Select[Any]:
    # SQLAlchemy Select is intentionally left generic so this helper supports asset-only and
    # asset-plus-distance selections without weakening their result typing at callers.
    filters: list[ColumnElement[bool]] = []
    if query.character is not None:
        filters.append(IpAssetModel.character == query.character.value)
    if query.asset_type is not None:
        filters.append(IpAssetModel.asset_type == query.asset_type.value)
    if query.department:
        filters.append(func.lower(IpAssetModel.department) == query.department.casefold())
    if query.source_kind is not None:
        filters.append(IpAssetModel.source_kind == query.source_kind.value)
    if query.orientation is not None:
        filters.append(IpAssetModel.orientation == query.orientation.value)
    if query.tag:
        filters.append(
            IpAssetModel.id.in_(
                select(IpAssetTagModel.asset_id).where(
                    func.lower(IpAssetTagModel.value) == query.tag.casefold()
                )
            )
        )
    if include_keyword and query.query:
        pattern = f"%{_escape_like(query.query)}%"
        tag_match = select(IpAssetTagModel.asset_id).where(
            IpAssetTagModel.value.ilike(pattern, escape="\\")
        )
        filters.append(
            or_(
                IpAssetModel.canonical_name.ilike(pattern, escape="\\"),
                IpAssetModel.safe_original_filename.ilike(pattern, escape="\\"),
                IpAssetModel.department.ilike(pattern, escape="\\"),
                IpAssetModel.contributor.ilike(pattern, escape="\\"),
                IpAssetModel.emotion.ilike(pattern, escape="\\"),
                IpAssetModel.action.ilike(pattern, escape="\\"),
                IpAssetModel.scene.ilike(pattern, escape="\\"),
                IpAssetModel.intended_use.ilike(pattern, escape="\\"),
                IpAssetModel.style.ilike(pattern, escape="\\"),
                IpAssetModel.id.in_(tag_match),
            )
        )
    for criterion in filters:
        statement = statement.where(criterion)
    return statement


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")[:200]


def _tag_rows(metadata: IpAssetMetadata) -> tuple[tuple[str, str], ...]:
    rows = [
        ("emotion", metadata.emotion),
        ("action", metadata.action),
        ("scene", metadata.scene),
        ("intended_use", metadata.intended_use),
        ("style", metadata.style),
    ]
    return tuple((dimension, value) for dimension, value in rows if value) + tuple(
        ("free", value) for value in metadata.tags
    )


async def _apply_asset_relationships(
    session: AsyncSession,
    *,
    asset: IpAssetModel,
    shared: bool,
    profile_id: UUID | None,
    source: IpAssetMembershipSource | None,
) -> None:
    if shared and asset.shared_at is None:
        asset.shared_at = datetime.now(UTC)
        asset.updated_at = asset.shared_at
    if profile_id is None or source is None:
        return
    await session.execute(
        pg_insert(IpAssetProfileMembershipModel)
        .values(
            id=uuid4(),
            profile_id=profile_id,
            asset_id=asset.id,
            source=source.value,
            generation_job_id=None,
        )
        .on_conflict_do_nothing(index_elements=["profile_id", "asset_id", "source"])
    )


async def _membership_sources_for(
    session: AsyncSession, profile_id: UUID, asset_ids: tuple[UUID, ...]
) -> dict[UUID, tuple[IpAssetMembershipSource, ...]]:
    if not asset_ids:
        return {}
    rows = tuple(
        (
            await session.execute(
                select(
                    IpAssetProfileMembershipModel.asset_id,
                    IpAssetProfileMembershipModel.source,
                )
                .where(
                    IpAssetProfileMembershipModel.profile_id == profile_id,
                    IpAssetProfileMembershipModel.asset_id.in_(asset_ids),
                )
                .order_by(
                    IpAssetProfileMembershipModel.asset_id,
                    IpAssetProfileMembershipModel.source,
                )
            )
        ).tuples()
    )
    grouped: dict[UUID, list[IpAssetMembershipSource]] = {}
    for asset_id, source in rows:
        grouped.setdefault(asset_id, []).append(IpAssetMembershipSource(source))
    return {asset_id: tuple(values) for asset_id, values in grouped.items()}


async def _favorite_ids_for(
    session: AsyncSession, profile_id: UUID, asset_ids: tuple[UUID, ...]
) -> frozenset[UUID]:
    if not asset_ids:
        return frozenset()
    return frozenset(
        await session.scalars(
            select(IpAssetFavoriteModel.asset_id).where(
                IpAssetFavoriteModel.profile_id == profile_id,
                IpAssetFavoriteModel.asset_id.in_(asset_ids),
            )
        )
    )


async def _generation_references_for(
    session: AsyncSession, job_id: UUID
) -> tuple[IpAssetGenerationReferenceRecord, ...]:
    rows = tuple(
        (
            await session.execute(
                select(IpAssetGenerationReferenceModel, IpAssetModel.asset_ref)
                .join(IpAssetModel, IpAssetModel.id == IpAssetGenerationReferenceModel.asset_id)
                .where(IpAssetGenerationReferenceModel.job_id == job_id)
                .order_by(IpAssetGenerationReferenceModel.ordinal)
            )
        ).tuples()
    )
    return tuple(
        IpAssetGenerationReferenceRecord(
            asset_id=reference.asset_id,
            asset_ref=asset_ref,
            ordinal=reference.ordinal,
            source_sha256=reference.source_sha256,
        )
        for reference, asset_ref in rows
    )


def _profile_record(model: IpAssetProfileModel) -> IpAssetProfileRecord:
    return IpAssetProfileRecord(
        id=model.id,
        profile_ref=model.profile_ref,
        display_name=model.display_name,
        department=model.department,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _derivative_record(model: IpAssetDerivativeModel) -> IpAssetDerivativeRecord:
    return IpAssetDerivativeRecord(
        asset_id=model.asset_id,
        policy_version=model.policy_version,
        kind=model.kind,
        source_sha256=model.source_sha256,
        media_type=model.media_type,
        byte_size=model.byte_size,
        width=model.width,
        height=model.height,
        bucket=model.bucket,
        object_key=model.object_key,
        sha256=model.sha256,
    )


def _assert_derivative_matches(
    model: IpAssetDerivativeModel,
    *,
    source_sha256: str,
    descriptor: IpAssetObjectDescriptor,
    width: int,
    height: int,
) -> None:
    if (
        model.source_sha256 != source_sha256
        or model.media_type != descriptor.media_type
        or model.byte_size != descriptor.byte_size
        or model.width != width
        or model.height != height
        or model.bucket != descriptor.bucket
        or model.object_key != descriptor.object_key
        or model.sha256 != descriptor.sha256
    ):
        raise ConflictError("IP asset derivative does not match immutable content")


async def _tags_for(
    session: AsyncSession, asset_ids: tuple[UUID, ...]
) -> dict[UUID, tuple[str, ...]]:
    if not asset_ids:
        return {}
    rows = tuple(
        (
            await session.execute(
                select(IpAssetTagModel.asset_id, IpAssetTagModel.value)
                .where(IpAssetTagModel.asset_id.in_(asset_ids))
                .order_by(
                    IpAssetTagModel.asset_id, IpAssetTagModel.dimension, IpAssetTagModel.value
                )
            )
        ).tuples()
    )
    values: dict[UUID, list[str]] = {}
    for asset_id, value in rows:
        if value not in values.setdefault(asset_id, []):
            values[asset_id].append(value)
    return {asset_id: tuple(tags) for asset_id, tags in values.items()}


async def _record_or_none(
    session: AsyncSession, model: IpAssetModel | None
) -> IpAssetRecord | None:
    if model is None:
        return None
    tags = await _tags_for(session, (model.id,))
    return _record(model, tags.get(model.id, ()))


def _record(model: IpAssetModel, tags: tuple[str, ...]) -> IpAssetRecord:
    return IpAssetRecord(
        id=model.id,
        asset_ref=model.asset_ref,
        blob_sha256=model.blob_sha256,
        perceptual_hash=model.perceptual_hash,
        safe_original_filename=model.safe_original_filename,
        media_type=model.media_type,
        byte_size=model.byte_size,
        width=model.width,
        height=model.height,
        has_alpha=model.has_alpha,
        orientation=IpAssetOrientation(model.orientation),
        bucket=model.bucket,
        object_key=model.object_key,
        canonical_name=model.canonical_name,
        canonical_slug=model.canonical_slug,
        name_version=model.name_version,
        character=IpAssetCharacter(model.character),
        asset_type=IpAssetType(model.asset_type),
        source_kind=IpAssetSource(model.source_kind),
        department=model.department,
        contributor=model.contributor,
        emotion=model.emotion,
        action=model.action,
        scene=model.scene,
        intended_use=model.intended_use,
        style=model.style,
        tags=tags,
        status=IpAssetStatus(model.status),
        semantic_status=IpAssetSemanticStatus(model.semantic_status),
        failure_code=model.failure_code,
        parent_asset_id=model.parent_asset_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        shared_at=model.shared_at,
    )


def _generation_record(
    model: IpAssetGenerationJobModel,
    references: tuple[IpAssetGenerationReferenceRecord, ...],
) -> IpAssetGenerationRecord:
    return IpAssetGenerationRecord(
        id=model.id,
        job_ref=model.job_ref,
        idempotency_key=model.idempotency_key,
        request_fingerprint=model.request_fingerprint,
        prompt=model.prompt,
        character=IpAssetCharacter(model.character),
        asset_type=IpAssetType(model.asset_type),
        department=model.department,
        contributor=model.contributor,
        ratio=model.ratio,
        profile_id=model.profile_id,
        reference_asset_id=model.reference_asset_id,
        references=references,
        provider=model.provider,
        model=model.model,
        status=model.status,
        attempt_count=model.attempt_count,
        lease_token=model.lease_token,
        output_asset_id=model.output_asset_id,
        error_code=model.error_code,
        created_at=model.created_at,
        completed_at=model.completed_at,
    )
