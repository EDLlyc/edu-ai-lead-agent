from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.visual_retrieval import VisualIndexClaim, VisualIndexRepository
from app.domain.visual_retrieval import (
    VISUAL_EMBEDDING_INPUT_POLICY_V1,
    VisualAssetDerivation,
    VisualEmbeddingIdentity,
    VisualEmbeddingResult,
    VisualSemanticRanking,
    VisualSemanticScore,
)
from app.infrastructure.db.models import (
    BrandVisualAssetEmbeddingModel,
    BrandVisualIndexJobModel,
)

_SAFE_ERROR_CODES = frozenset(
    {
        "provider_unavailable",
        "input_normalization_failed",
        "identity_mismatch",
        "invalid_provider_output",
        "catalog_changed",
        "lease_expired",
    }
)


class PostgresVisualIndexRepository(VisualIndexRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_asset(
        self,
        *,
        derivation: VisualAssetDerivation,
        worker_id: str,
        lease_seconds: int,
    ) -> VisualIndexClaim | None:
        if not worker_id.strip() or len(worker_id) > 200 or not 30 <= lease_seconds <= 3_600:
            raise ValueError("visual index claim bounds are invalid")
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            await session.execute(
                pg_insert(BrandVisualIndexJobModel)
                .values(
                    id=uuid4(),
                    derivation_key=derivation.key,
                    asset_id=derivation.asset_id,
                    asset_checksum=derivation.asset_checksum,
                    embedding_input_sha256=derivation.embedding_input_sha256,
                    catalog_version=derivation.catalog_version,
                    provider=derivation.identity.provider,
                    model=derivation.identity.model,
                    dimensions=derivation.identity.dimensions,
                    input_policy_version=derivation.identity.input_policy_version,
                    status="queued",
                    attempt_count=0,
                    input_tokens=0,
                    image_tokens=0,
                    latency_ms=0,
                )
                .on_conflict_do_nothing(index_elements=["derivation_key"])
            )
            job = await session.scalar(
                select(BrandVisualIndexJobModel)
                .where(BrandVisualIndexJobModel.derivation_key == derivation.key)
                .with_for_update()
            )
            if job is None:
                raise RuntimeError("visual index job could not be created")
            if (
                job.derivation_key != derivation.key
                or job.asset_id != derivation.asset_id
                or job.asset_checksum != derivation.asset_checksum
                or job.embedding_input_sha256 != derivation.embedding_input_sha256
                or job.catalog_version != derivation.catalog_version
                or job.provider != derivation.identity.provider
                or job.model != derivation.identity.model
                or job.dimensions != derivation.identity.dimensions
                or job.input_policy_version != derivation.identity.input_policy_version
            ):
                raise RuntimeError("visual index job derivation is inconsistent")
            ready = await session.scalar(
                select(BrandVisualAssetEmbeddingModel.id).where(
                    BrandVisualAssetEmbeddingModel.derivation_key == derivation.key
                )
            )
            if ready is not None:
                await session.rollback()
                return None
            if job.status == "running" and job.lease_expires_at is not None:
                if job.lease_expires_at >= now:
                    await session.rollback()
                    return None
                job.status = "failed"
                job.error_code = "lease_expired"
                job.lease_owner = None
                job.lease_token = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.completed_at = now
            token = uuid4()
            job.status = "running"
            job.attempt_count += 1
            job.lease_owner = worker_id.strip()
            job.lease_token = token
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.heartbeat_at = now
            job.started_at = now
            job.completed_at = None
            job.error_code = None
            claim = VisualIndexClaim(
                job_id=job.id,
                lease_token=token,
                derivation=derivation,
                attempt_number=job.attempt_count,
            )
            await session.commit()
            return claim

    async def persist_embedding(
        self, *, claim: VisualIndexClaim, embedding: VisualEmbeddingResult
    ) -> bool:
        if (
            embedding.identity != claim.derivation.identity
            or embedding.input_sha256 != claim.derivation.embedding_input_sha256
        ):
            return False
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(BrandVisualIndexJobModel)
                .where(
                    BrandVisualIndexJobModel.id == claim.job_id,
                    BrandVisualIndexJobModel.lease_token == claim.lease_token,
                    BrandVisualIndexJobModel.status == "running",
                    BrandVisualIndexJobModel.lease_expires_at >= now,
                    BrandVisualIndexJobModel.derivation_key == claim.derivation.key,
                    BrandVisualIndexJobModel.asset_id == claim.derivation.asset_id,
                    BrandVisualIndexJobModel.asset_checksum == claim.derivation.asset_checksum,
                    BrandVisualIndexJobModel.embedding_input_sha256
                    == claim.derivation.embedding_input_sha256,
                    BrandVisualIndexJobModel.catalog_version == claim.derivation.catalog_version,
                    BrandVisualIndexJobModel.provider == claim.derivation.identity.provider,
                    BrandVisualIndexJobModel.model == claim.derivation.identity.model,
                    BrandVisualIndexJobModel.dimensions == claim.derivation.identity.dimensions,
                    BrandVisualIndexJobModel.input_policy_version
                    == claim.derivation.identity.input_policy_version,
                )
                .with_for_update()
            )
            if job is None:
                await session.rollback()
                return False
            existing = await session.scalar(
                select(BrandVisualAssetEmbeddingModel.id).where(
                    BrandVisualAssetEmbeddingModel.derivation_key == claim.derivation.key
                )
            )
            if existing is None:
                session.add(
                    BrandVisualAssetEmbeddingModel(
                        id=uuid4(),
                        job_id=job.id,
                        derivation_key=claim.derivation.key,
                        asset_id=claim.derivation.asset_id,
                        asset_checksum=claim.derivation.asset_checksum,
                        embedding_input_sha256=claim.derivation.embedding_input_sha256,
                        catalog_version=claim.derivation.catalog_version,
                        provider=claim.derivation.identity.provider,
                        model=claim.derivation.identity.model,
                        dimensions=claim.derivation.identity.dimensions,
                        input_policy_version=claim.derivation.identity.input_policy_version,
                        request_fingerprint=embedding.request_fingerprint,
                        vector=list(embedding.vector),
                    )
                )
                await session.flush()
            job.status = "succeeded"
            job.error_code = None
            job.input_tokens = embedding.input_tokens
            job.image_tokens = embedding.image_tokens
            job.latency_ms = embedding.latency_ms
            job.completed_at = now
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            await session.commit()
            return True

    async def fail_asset(self, *, claim: VisualIndexClaim, error_code: str) -> bool:
        safe_code = error_code if error_code in _SAFE_ERROR_CODES else "provider_unavailable"
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(BrandVisualIndexJobModel)
                .where(
                    BrandVisualIndexJobModel.id == claim.job_id,
                    BrandVisualIndexJobModel.lease_token == claim.lease_token,
                    BrandVisualIndexJobModel.status == "running",
                    BrandVisualIndexJobModel.derivation_key == claim.derivation.key,
                    BrandVisualIndexJobModel.asset_id == claim.derivation.asset_id,
                    BrandVisualIndexJobModel.asset_checksum == claim.derivation.asset_checksum,
                    BrandVisualIndexJobModel.embedding_input_sha256
                    == claim.derivation.embedding_input_sha256,
                    BrandVisualIndexJobModel.catalog_version == claim.derivation.catalog_version,
                    BrandVisualIndexJobModel.provider == claim.derivation.identity.provider,
                    BrandVisualIndexJobModel.model == claim.derivation.identity.model,
                    BrandVisualIndexJobModel.dimensions == claim.derivation.identity.dimensions,
                    BrandVisualIndexJobModel.input_policy_version
                    == claim.derivation.identity.input_policy_version,
                )
                .with_for_update()
            )
            if job is None:
                await session.rollback()
                return False
            job.status = "failed"
            job.error_code = safe_code
            job.completed_at = now
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            await session.commit()
            return True

    async def search_complete_catalog(
        self,
        *,
        catalog_version: str,
        catalog_assets: tuple[tuple[str, str], ...],
        identity: VisualEmbeddingIdentity,
        query: VisualEmbeddingResult,
    ) -> VisualSemanticRanking:
        expected = dict(catalog_assets)
        if len(expected) != len(catalog_assets) or query.identity != identity:
            raise ValueError("visual catalog retrieval identity is invalid")
        if not expected:
            return VisualSemanticRanking(
                catalog_version=catalog_version,
                identity=identity,
                query_fingerprint=query.request_fingerprint,
                scores=(),
                indexed_asset_count=0,
                catalog_asset_count=0,
                complete=True,
            )
        distance = BrandVisualAssetEmbeddingModel.vector.cosine_distance(list(query.vector)).label(
            "distance"
        )
        async with self._session_factory() as session:
            rows = tuple(
                (
                    await session.execute(
                        select(BrandVisualAssetEmbeddingModel, distance)
                        .where(
                            BrandVisualAssetEmbeddingModel.catalog_version == catalog_version,
                            BrandVisualAssetEmbeddingModel.provider == identity.provider,
                            BrandVisualAssetEmbeddingModel.model == identity.model,
                            BrandVisualAssetEmbeddingModel.dimensions == identity.dimensions,
                            BrandVisualAssetEmbeddingModel.input_policy_version
                            == identity.input_policy_version,
                            BrandVisualAssetEmbeddingModel.asset_id.in_(tuple(expected)),
                        )
                        .order_by(distance, BrandVisualAssetEmbeddingModel.asset_id)
                    )
                ).tuples()
            )
        compatible_rows = tuple(
            (row, raw_distance)
            for row, raw_distance in rows
            if expected.get(row.asset_id) == row.asset_checksum
            and len(row.embedding_input_sha256) == 64
            and all(character in "0123456789abcdef" for character in row.embedding_input_sha256)
            and (
                identity.input_policy_version != VISUAL_EMBEDDING_INPUT_POLICY_V1
                or row.embedding_input_sha256 == row.asset_checksum
            )
        )
        row_counts = Counter(row.asset_id for row, _raw_distance in compatible_rows)
        compatible = {
            row.asset_id: max(-1.0, min(1.0, 1.0 - float(raw_distance)))
            for row, raw_distance in compatible_rows
            if row_counts[row.asset_id] == 1
        }
        complete = (
            len(compatible_rows) == len(expected)
            and set(compatible) == set(expected)
            and len(compatible) == len(expected)
        )
        scores = tuple(
            VisualSemanticScore(asset_id=asset_id, similarity=similarity)
            for asset_id, similarity in sorted(
                compatible.items(), key=lambda item: (-item[1], item[0])
            )
        )
        return VisualSemanticRanking(
            catalog_version=catalog_version,
            identity=identity,
            query_fingerprint=query.request_fingerprint,
            scores=scores,
            indexed_asset_count=len(compatible),
            catalog_asset_count=len(expected),
            complete=complete,
        )

    async def prove_complete_catalog(
        self,
        *,
        catalog_version: str,
        catalog_assets: tuple[tuple[str, str], ...],
        identity: VisualEmbeddingIdentity,
    ) -> bool:
        """Prove exact current coverage before a caller incurs a paid text query."""
        expected = dict(catalog_assets)
        if len(expected) != len(catalog_assets) or not expected:
            return not catalog_assets
        async with self._session_factory() as session:
            rows = tuple(
                (
                    await session.execute(
                        select(
                            BrandVisualAssetEmbeddingModel.asset_id,
                            BrandVisualAssetEmbeddingModel.asset_checksum,
                            BrandVisualAssetEmbeddingModel.embedding_input_sha256,
                        ).where(
                            BrandVisualAssetEmbeddingModel.catalog_version == catalog_version,
                            BrandVisualAssetEmbeddingModel.provider == identity.provider,
                            BrandVisualAssetEmbeddingModel.model == identity.model,
                            BrandVisualAssetEmbeddingModel.dimensions == identity.dimensions,
                            BrandVisualAssetEmbeddingModel.input_policy_version
                            == identity.input_policy_version,
                            BrandVisualAssetEmbeddingModel.asset_id.in_(tuple(expected)),
                        )
                    )
                ).tuples()
            )
        compatible = tuple(
            asset_id
            for asset_id, checksum, input_sha256 in rows
            if expected.get(asset_id) == checksum
            and len(input_sha256) == 64
            and all(character in "0123456789abcdef" for character in input_sha256)
            and (
                identity.input_policy_version != VISUAL_EMBEDDING_INPUT_POLICY_V1
                or input_sha256 == checksum
            )
        )
        counts = Counter(compatible)
        return (
            len(rows) == len(expected)
            and set(counts) == set(expected)
            and all(count == 1 for count in counts.values())
        )
