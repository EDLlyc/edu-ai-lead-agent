from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from app.application.ports.wechat_official_account import (
    WeChatDraftArticleRequest,
    WeChatDraftCreated,
    WeChatDraftRole,
    WeChatInlineImage,
    WeChatMpOutcomeUnknownError,
    WeChatMpTransientError,
    WeChatThumbMedia,
)
from app.application.ports.wechat_official_account_draft_artifacts import (
    ResolvedWeChatDraftArtifactSource,
    WeChatDraftArtifactBatch,
    WeChatDraftArtifactDiscovery,
    WeChatDraftArtifactSource,
)
from app.application.services.wechat_official_account_draft import (
    WeChatDraftLocalSource,
    WeChatPreparedDraft,
    WeChatPreparedMedia,
)
from app.application.services.wechat_official_account_draft_jobs import (
    WeChatOfficialAccountDraftJobExecutor,
    WeChatOfficialAccountDraftJobService,
)
from app.domain.official_account_weekly_edition import WeeklyArticleRole
from app.domain.wechat_official_account_draft_jobs import (
    WECHAT_DRAFT_JOB_POLICY_VERSION,
    WeChatDraftItemSnapshot,
    WeChatDraftItemStatus,
    WeChatDraftJobClaim,
    WeChatDraftJobEnqueue,
    WeChatDraftJobFailure,
    WeChatDraftJobSnapshot,
    WeChatDraftJobStatus,
    WeChatDraftStatusProjection,
    wechat_draft_account_fingerprint,
    wechat_draft_policy_fingerprint,
)

_NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
_AGGREGATE = "a" * 64
_BATCH = "b" * 64
_ACCOUNT = "c" * 64
_ROLES = (
    WeeklyArticleRole.OFFICIAL_ANCHOR,
    WeeklyArticleRole.INDUSTRY_TREND,
    WeeklyArticleRole.APPLICATION_CASE,
)


def _artifact_batch() -> WeChatDraftArtifactBatch:
    article_hashes = ("d" * 64, "e" * 64, "f" * 64)
    content_hashes = ("1" * 64, "2" * 64, "3" * 64)
    zip_hashes = ("4" * 64, "5" * 64, "6" * 64)
    sources = tuple(
        WeChatDraftArtifactSource(
            role=cast(WeChatDraftRole, role.value),
            ordinal=ordinal,
            source_ref=f"wechat-draft-v1:{_AGGREGATE}:{role.value}",
            source_fingerprint=str(ordinal) * 64,
            article_fingerprint=article_hashes[ordinal - 1],
            content_fingerprint=content_hashes[ordinal - 1],
            child_zip_sha256=zip_hashes[ordinal - 1],
        )
        for ordinal, role in enumerate(_ROLES, start=1)
    )
    return WeChatDraftArtifactBatch(
        week_start="2026-08-31",
        batch_fingerprint=_BATCH,
        aggregate_fingerprint=_AGGREGATE,
        sources=cast(
            tuple[
                WeChatDraftArtifactSource,
                WeChatDraftArtifactSource,
                WeChatDraftArtifactSource,
            ],
            sources,
        ),
    )


class _ArtifactStore:
    def __init__(self, batch: WeChatDraftArtifactBatch) -> None:
        self.batch = batch
        self.resolved: list[str] = []

    def stage_weekly(self, _source_directory: Path) -> WeChatDraftArtifactBatch:
        return self.batch

    def resolve(self, source_ref: str) -> ResolvedWeChatDraftArtifactSource:
        self.resolved.append(source_ref)
        source = next(item for item in self.batch.sources if item.source_ref == source_ref)
        return ResolvedWeChatDraftArtifactSource(
            directory=Path(f"/private/{source.ordinal}"),
            source=source,
            batch_fingerprint=self.batch.batch_fingerprint,
            aggregate_fingerprint=self.batch.aggregate_fingerprint,
        )

    def discover_weekly(self, *, maximum: int = 100) -> WeChatDraftArtifactDiscovery:
        assert maximum >= 1
        return WeChatDraftArtifactDiscovery(
            batches=(self.batch,),
            skipped_by_code={"weekly_edition_live_provenance_required": 2},
        )


class _Preparer:
    def __init__(self, batch: WeChatDraftArtifactBatch, *, fail: bool = False) -> None:
        self.batch = batch
        self.fail = fail
        self.calls = 0

    def prepare_weekly(
        self,
        sources: tuple[
            WeChatDraftLocalSource,
            WeChatDraftLocalSource,
            WeChatDraftLocalSource,
        ],
    ) -> tuple[WeChatPreparedDraft, WeChatPreparedDraft, WeChatPreparedDraft]:
        self.calls += 1
        if self.fail:
            raise ValueError("private preparation detail")
        assert tuple(source.role for source in sources) == tuple(
            item.role for item in self.batch.sources
        )
        prepared = tuple(
            WeChatPreparedDraft(
                role=item.role,
                article_fingerprint=item.article_fingerprint,
                content_fingerprint=item.content_fingerprint,
                title=f"title {item.ordinal}",
                author="赛先生",
                digest="digest",
                content_source_url=None,
                body_html='<p><img src="assets/body.png" alt="body"></p>',
                body_media=(
                    WeChatPreparedMedia(
                        path="assets/body.png",
                        media_type="image/png",
                        body=b"body-image",
                        upload_filename="body.png",
                    ),
                ),
                cover=WeChatPreparedMedia(
                    path="assets/cover.jpg",
                    media_type="image/jpeg",
                    body=b"cover-image",
                    upload_filename="cover.jpg",
                ),
                need_open_comment=False,
                only_fans_can_comment=False,
            )
            for item in self.batch.sources
        )
        return cast(
            tuple[WeChatPreparedDraft, WeChatPreparedDraft, WeChatPreparedDraft],
            prepared,
        )


def _projection(
    command: WeChatDraftJobEnqueue,
    *,
    job_status: WeChatDraftJobStatus,
    current_item: WeChatDraftItemStatus,
) -> WeChatDraftStatusProjection:
    job = WeChatDraftJobSnapshot(
        job_id=command.job_id,
        request_fingerprint=command.request_fingerprint,
        account_fingerprint=command.account_fingerprint,
        aggregate_fingerprint=command.aggregate_fingerprint,
        batch_fingerprint=command.batch_fingerprint,
        policy_version=WECHAT_DRAFT_JOB_POLICY_VERSION,
        status=job_status,
        attempt_count=1 if job_status is not WeChatDraftJobStatus.QUEUED else 0,
        max_attempts=command.max_attempts,
        fencing_token=1 if job_status is WeChatDraftJobStatus.RUNNING else 0,
        available_at=_NOW,
        error_code=None,
        created_at=_NOW,
        updated_at=_NOW,
        completed_at=None,
    )
    items = tuple(
        WeChatDraftItemSnapshot(
            job_id=command.job_id,
            role=item.role,
            ordinal=item.ordinal,
            source_ref=item.source_ref,
            source_fingerprint=item.source_fingerprint,
            article_fingerprint=item.article_fingerprint,
            content_fingerprint=item.content_fingerprint,
            policy_fingerprint=item.policy_fingerprint,
            status=current_item if item.ordinal == 1 else WeChatDraftItemStatus.PENDING,
            attempt_count=(
                1 if item.ordinal == 1 and current_item is not WeChatDraftItemStatus.PENDING else 0
            ),
            side_effect_started_at=None,
            endpoint=None,
            uploaded_image_count=0,
            draft_media_fingerprint=None,
            error_code=None,
            started_at=(
                _NOW
                if item.ordinal == 1 and current_item is not WeChatDraftItemStatus.PENDING
                else None
            ),
            completed_at=None,
        )
        for item in command.items
    )
    return WeChatDraftStatusProjection(
        job=job,
        items=cast(
            tuple[
                WeChatDraftItemSnapshot,
                WeChatDraftItemSnapshot,
                WeChatDraftItemSnapshot,
            ],
            items,
        ),
    )


def _command(batch: WeChatDraftArtifactBatch) -> WeChatDraftJobEnqueue:
    from app.domain.wechat_official_account_draft_jobs import WeChatDraftJobItemInput

    items = tuple(
        WeChatDraftJobItemInput(
            role=WeeklyArticleRole(source.role),
            ordinal=source.ordinal,
            source_ref=source.source_ref,
            source_fingerprint=source.source_fingerprint,
            article_fingerprint=source.article_fingerprint,
            content_fingerprint=source.content_fingerprint,
            policy_fingerprint=wechat_draft_policy_fingerprint(
                content_source_url=None,
                need_open_comment=False,
                only_fans_can_comment=False,
            ),
        )
        for source in batch.sources
    )
    return WeChatDraftJobEnqueue(
        account_fingerprint=_ACCOUNT,
        aggregate_fingerprint=batch.aggregate_fingerprint,
        batch_fingerprint=batch.batch_fingerprint,
        items=cast(
            "tuple[WeChatDraftJobItemInput, WeChatDraftJobItemInput, WeChatDraftJobItemInput]",
            items,
        ),
    )


class _Repository:
    def __init__(self, command: WeChatDraftJobEnqueue) -> None:
        self.command = command
        self.status = _projection(
            command,
            job_status=WeChatDraftJobStatus.QUEUED,
            current_item=WeChatDraftItemStatus.PENDING,
        )
        self.enqueues = 0
        self.side_effect_started = False
        self.succeeded_fingerprint: str | None = None
        self.known_failure: dict[str, object] | None = None
        self.unknown_failure: dict[str, object] | None = None

    async def enqueue(
        self, command: WeChatDraftJobEnqueue, *, now: datetime
    ) -> tuple[WeChatDraftStatusProjection, bool]:
        assert now == _NOW
        assert command.request_fingerprint == self.command.request_fingerprint
        self.enqueues += 1
        return self.status, self.enqueues == 1

    async def get_status(self, _job_id: object) -> WeChatDraftStatusProjection:
        return self.status

    async def claim_next(
        self, *, worker_id: str, now: datetime, lease_seconds: int
    ) -> WeChatDraftJobClaim | None:
        assert worker_id == "wechat.worker.test"
        assert now == _NOW and lease_seconds == 300
        self.status = _projection(
            self.command,
            job_status=WeChatDraftJobStatus.RUNNING,
            current_item=WeChatDraftItemStatus.RUNNING,
        )
        return WeChatDraftJobClaim(
            job=self.status.job,
            item=self.status.items[0],
            worker_id=worker_id,
            lease_expires_at=_NOW.replace(minute=5),
        )

    async def heartbeat(self, *_args: object, **_kwargs: object) -> bool:
        return True

    async def mark_side_effect_started(
        self, _claim: object, *, endpoint: str, now: datetime
    ) -> bool:
        assert endpoint == "media_uploadimg" and now == _NOW
        self.side_effect_started = True
        return True

    async def succeed(
        self,
        _claim: object,
        *,
        endpoint: str,
        uploaded_image_count: int,
        draft_media_fingerprint: str,
        now: datetime,
    ) -> WeChatDraftStatusProjection:
        assert self.side_effect_started
        assert endpoint == "draft_add" and uploaded_image_count == 1 and now == _NOW
        self.succeeded_fingerprint = draft_media_fingerprint
        self.status = replace(
            self.status,
            job=replace(self.status.job, status=WeChatDraftJobStatus.QUEUED),
        )
        return self.status

    async def fail_known(self, _claim: object, **kwargs: object) -> WeChatDraftStatusProjection:
        self.known_failure = kwargs
        target = (
            WeChatDraftJobStatus.RETRYABLE_FAILED
            if kwargs["retryable"]
            else WeChatDraftJobStatus.TERMINAL_FAILED
        )
        self.status = replace(self.status, job=replace(self.status.job, status=target))
        return self.status

    async def mark_outcome_unknown(
        self, _claim: object, **kwargs: object
    ) -> WeChatDraftStatusProjection:
        self.unknown_failure = kwargs
        self.status = replace(
            self.status,
            job=replace(self.status.job, status=WeChatDraftJobStatus.OUTCOME_UNKNOWN),
        )
        return self.status


class _Client:
    def __init__(self, repository: _Repository, *, failure: str | None = None) -> None:
        self.repository = repository
        self.failure = failure
        self.calls: list[str] = []

    async def upload_inline_image(
        self, _image_bytes: bytes, _media_type: str, _filename: str
    ) -> WeChatInlineImage:
        assert self.repository.side_effect_started
        self.calls.append("media_uploadimg")
        return WeChatInlineImage(url="https://mmbiz.qpic.cn/safe")

    async def upload_thumb(
        self, _image_bytes: bytes, _media_type: str, _filename: str
    ) -> WeChatThumbMedia:
        self.calls.append("material_add_thumb")
        return WeChatThumbMedia(media_id="temporary-thumb")

    async def add_draft(self, _article: WeChatDraftArticleRequest) -> WeChatDraftCreated:
        self.calls.append("draft_add")
        if self.failure == "unknown":
            raise WeChatMpOutcomeUnknownError(endpoint="draft_add")
        if self.failure == "retryable":
            raise WeChatMpTransientError(endpoint="draft_add")
        return WeChatDraftCreated(media_id="raw-provider-media-id")


class _RecoveredDuringResultRepository(_Repository):
    """Simulate another claimant terminalizing an ambiguous started write first."""

    def __init__(self, command: WeChatDraftJobEnqueue, *, reject: str) -> None:
        super().__init__(command)
        self.reject = reject
        self.unknown_transition_attempts = 0

    def _terminalize_elsewhere(self) -> None:
        current = self.status.items[0]
        unknown = replace(
            current,
            status=WeChatDraftItemStatus.OUTCOME_UNKNOWN,
            side_effect_started_at=_NOW,
            error_code="lease_lost_after_side_effect",
            completed_at=_NOW,
        )
        self.status = WeChatDraftStatusProjection(
            job=replace(
                self.status.job,
                status=WeChatDraftJobStatus.OUTCOME_UNKNOWN,
                error_code="lease_lost_after_side_effect",
                completed_at=_NOW,
            ),
            items=cast(
                tuple[
                    WeChatDraftItemSnapshot,
                    WeChatDraftItemSnapshot,
                    WeChatDraftItemSnapshot,
                ],
                (unknown, *self.status.items[1:]),
            ),
        )

    async def succeed(self, *_args: object, **_kwargs: object) -> WeChatDraftStatusProjection:
        if self.reject == "succeed":
            self._terminalize_elsewhere()
            raise WeChatDraftJobFailure("lease_lost", retryable=False)
        return await super().succeed(*_args, **_kwargs)  # type: ignore[arg-type]

    async def fail_known(self, *_args: object, **_kwargs: object) -> WeChatDraftStatusProjection:
        if self.reject == "known":
            self._terminalize_elsewhere()
            raise WeChatDraftJobFailure("lease_lost", retryable=False)
        return await super().fail_known(*_args, **_kwargs)

    async def mark_outcome_unknown(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> WeChatDraftStatusProjection:
        self.unknown_transition_attempts += 1
        raise WeChatDraftJobFailure("lease_lost", retryable=False)


class _ThreeChildRepository:
    def __init__(self) -> None:
        self.command: WeChatDraftJobEnqueue | None = None
        self.status: WeChatDraftStatusProjection | None = None
        self.current_claim: WeChatDraftJobClaim | None = None
        self.side_effect_ordinal: int | None = None

    async def enqueue(
        self, command: WeChatDraftJobEnqueue, *, now: datetime
    ) -> tuple[WeChatDraftStatusProjection, bool]:
        assert now == _NOW
        if self.command is not None:
            assert command.request_fingerprint == self.command.request_fingerprint
            assert self.status is not None
            return self.status, False
        self.command = command
        self.status = _projection(
            command,
            job_status=WeChatDraftJobStatus.QUEUED,
            current_item=WeChatDraftItemStatus.PENDING,
        )
        return self.status, True

    async def get_status(self, _job_id: object) -> WeChatDraftStatusProjection:
        assert self.status is not None
        return self.status

    async def claim_next(
        self, *, worker_id: str, now: datetime, lease_seconds: int
    ) -> WeChatDraftJobClaim | None:
        assert now == _NOW and lease_seconds == 300
        assert self.status is not None
        if self.status.job.status is WeChatDraftJobStatus.READY:
            return None
        pending = next(
            (item for item in self.status.items if item.status is WeChatDraftItemStatus.PENDING),
            None,
        )
        if pending is None:
            return None
        running = replace(
            pending,
            status=WeChatDraftItemStatus.RUNNING,
            attempt_count=pending.attempt_count + 1,
            started_at=pending.started_at or now,
        )
        items = tuple(
            running if item.ordinal == running.ordinal else item for item in self.status.items
        )
        job = replace(
            self.status.job,
            status=WeChatDraftJobStatus.RUNNING,
            attempt_count=self.status.job.attempt_count + 1,
            fencing_token=self.status.job.fencing_token + 1,
            updated_at=now,
        )
        self.status = WeChatDraftStatusProjection(
            job=job,
            items=cast(
                tuple[
                    WeChatDraftItemSnapshot,
                    WeChatDraftItemSnapshot,
                    WeChatDraftItemSnapshot,
                ],
                items,
            ),
        )
        self.current_claim = WeChatDraftJobClaim(
            job=job,
            item=running,
            worker_id=worker_id,
            lease_expires_at=_NOW.replace(minute=5),
        )
        return self.current_claim

    async def heartbeat(self, *_args: object, **_kwargs: object) -> bool:
        return True

    async def mark_side_effect_started(
        self, claim: WeChatDraftJobClaim, *, endpoint: str, now: datetime
    ) -> bool:
        assert self.status is not None
        assert self.current_claim == claim
        running = replace(
            self.status.items[claim.item.ordinal - 1],
            side_effect_started_at=now,
            endpoint=endpoint,
        )
        self.status = replace(
            self.status,
            items=cast(
                tuple[
                    WeChatDraftItemSnapshot,
                    WeChatDraftItemSnapshot,
                    WeChatDraftItemSnapshot,
                ],
                tuple(
                    running if item.ordinal == running.ordinal else item
                    for item in self.status.items
                ),
            ),
        )
        self.side_effect_ordinal = claim.item.ordinal
        return True

    async def succeed(
        self,
        claim: WeChatDraftJobClaim,
        *,
        endpoint: str,
        uploaded_image_count: int,
        draft_media_fingerprint: str,
        now: datetime,
    ) -> WeChatDraftStatusProjection:
        assert self.status is not None
        assert self.side_effect_ordinal == claim.item.ordinal
        succeeded = replace(
            self.status.items[claim.item.ordinal - 1],
            status=WeChatDraftItemStatus.SUCCEEDED,
            endpoint=endpoint,
            uploaded_image_count=uploaded_image_count,
            draft_media_fingerprint=draft_media_fingerprint,
            completed_at=now,
        )
        items = tuple(
            succeeded if item.ordinal == succeeded.ordinal else item for item in self.status.items
        )
        ready = all(item.status is WeChatDraftItemStatus.SUCCEEDED for item in items)
        self.status = WeChatDraftStatusProjection(
            job=replace(
                self.status.job,
                status=(WeChatDraftJobStatus.READY if ready else WeChatDraftJobStatus.QUEUED),
                updated_at=now,
                completed_at=now if ready else None,
            ),
            items=cast(
                tuple[
                    WeChatDraftItemSnapshot,
                    WeChatDraftItemSnapshot,
                    WeChatDraftItemSnapshot,
                ],
                items,
            ),
        )
        self.current_claim = None
        self.side_effect_ordinal = None
        return self.status

    async def fail_known(self, *_args: object, **_kwargs: object) -> WeChatDraftStatusProjection:
        raise AssertionError("three-child happy path must not fail")

    async def mark_outcome_unknown(
        self, *_args: object, **_kwargs: object
    ) -> WeChatDraftStatusProjection:
        raise AssertionError("three-child happy path must not become unknown")


class _OrderingClient:
    def __init__(self, repository: _ThreeChildRepository) -> None:
        self._repository = repository
        self.draft_ordinals: list[int] = []

    async def upload_inline_image(
        self, _image_bytes: bytes, _media_type: str, _filename: str
    ) -> WeChatInlineImage:
        assert self._repository.side_effect_ordinal is not None
        return WeChatInlineImage(url="https://mmbiz.qpic.cn/safe")

    async def upload_thumb(
        self, _image_bytes: bytes, _media_type: str, _filename: str
    ) -> WeChatThumbMedia:
        return WeChatThumbMedia(media_id="temporary-thumb")

    async def add_draft(self, article: WeChatDraftArticleRequest) -> WeChatDraftCreated:
        ordinal = int(article.title.removeprefix("title "))
        assert ordinal == self._repository.side_effect_ordinal
        self.draft_ordinals.append(ordinal)
        return WeChatDraftCreated(media_id=f"raw-provider-media-id-{ordinal}")


def _executor(
    repository: _Repository | _ThreeChildRepository,
    store: _ArtifactStore,
    preparer: _Preparer,
    client: _Client | _OrderingClient,
) -> WeChatOfficialAccountDraftJobExecutor:
    return WeChatOfficialAccountDraftJobExecutor(
        repository=repository,
        artifact_store=store,
        client=client,
        lease_seconds=300,
        heartbeat_seconds=60,
        retry_base_seconds=30,
        max_image_bytes=1024,
        clock=lambda: _NOW,
        preparer=preparer,
    )


@pytest.mark.asyncio
async def test_worker_preflights_all_three_then_persists_only_media_fingerprint() -> None:
    batch = _artifact_batch()
    repository = _Repository(_command(batch))
    store = _ArtifactStore(batch)
    preparer = _Preparer(batch)
    client = _Client(repository)

    status = await _executor(repository, store, preparer, client).execute_next("wechat.worker.test")

    assert status is not None
    assert preparer.calls == 1
    assert len(store.resolved) == 3
    assert client.calls == ["media_uploadimg", "material_add_thumb", "draft_add"]
    assert repository.succeeded_fingerprint is not None
    assert repository.succeeded_fingerprint != "raw-provider-media-id"


@pytest.mark.asyncio
async def test_worker_maps_authenticated_timeout_to_terminal_unknown() -> None:
    batch = _artifact_batch()
    repository = _Repository(_command(batch))
    client = _Client(repository, failure="unknown")

    status = await _executor(
        repository, _ArtifactStore(batch), _Preparer(batch), client
    ).execute_next("wechat.worker.test")

    assert status is not None
    assert status.job.status is WeChatDraftJobStatus.OUTCOME_UNKNOWN
    assert repository.unknown_failure is not None
    assert repository.known_failure is None
    assert repository.unknown_failure["error_code"] == "wechat_mp_outcome_unknown"


@pytest.mark.asyncio
async def test_worker_retries_only_known_retryable_provider_rejection() -> None:
    batch = _artifact_batch()
    repository = _Repository(_command(batch))
    client = _Client(repository, failure="retryable")

    status = await _executor(
        repository, _ArtifactStore(batch), _Preparer(batch), client
    ).execute_next("wechat.worker.test")

    assert status is not None
    assert status.job.status is WeChatDraftJobStatus.RETRYABLE_FAILED
    assert repository.known_failure is not None
    assert repository.known_failure["retryable"] is True
    assert repository.unknown_failure is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rejected_transition", "provider_failure"),
    [("succeed", None), ("known", "retryable")],
)
async def test_stale_started_result_returns_authoritative_status_without_crashing(
    rejected_transition: str,
    provider_failure: str | None,
) -> None:
    batch = _artifact_batch()
    repository = _RecoveredDuringResultRepository(
        _command(batch),
        reject=rejected_transition,
    )
    client = _Client(repository, failure=provider_failure)

    status = await _executor(
        repository,
        _ArtifactStore(batch),
        _Preparer(batch),
        client,
    ).execute_next("wechat.worker.test")

    assert status is not None
    assert status.job.status is WeChatDraftJobStatus.OUTCOME_UNKNOWN
    assert status.items[0].status is WeChatDraftItemStatus.OUTCOME_UNKNOWN
    assert repository.unknown_transition_attempts == 1


@pytest.mark.asyncio
async def test_worker_preflight_failure_makes_zero_provider_calls() -> None:
    batch = _artifact_batch()
    repository = _Repository(_command(batch))
    client = _Client(repository)

    status = await _executor(
        repository,
        _ArtifactStore(batch),
        _Preparer(batch, fail=True),
        client,
    ).execute_next("wechat.worker.test")

    assert status is not None
    assert status.job.status is WeChatDraftJobStatus.TERMINAL_FAILED
    assert repository.side_effect_started is False
    assert client.calls == []


@pytest.mark.asyncio
async def test_reconcile_preserves_discovery_skips_and_is_idempotent() -> None:
    batch = _artifact_batch()
    repository = _Repository(_command(batch))
    service = WeChatOfficialAccountDraftJobService(
        repository=repository,
        artifact_store=_ArtifactStore(batch),
        account_fingerprint=_ACCOUNT,
        max_attempts=3,
        max_image_bytes=1024,
        clock=lambda: _NOW,
        preparer=_Preparer(batch),
    )

    first = await service.reconcile()
    second = await service.reconcile()

    assert first.enqueued == 1 and first.existing == 0
    assert second.enqueued == 0 and second.existing == 1
    assert first.skipped_by_code == {"weekly_edition_live_provenance_required": 2}


@pytest.mark.asyncio
async def test_three_child_batch_resumes_after_restart_and_idempotent_replay_is_zero_call() -> None:
    batch = _artifact_batch()
    repository = _ThreeChildRepository()
    store = _ArtifactStore(batch)
    preparer = _Preparer(batch)
    service = WeChatOfficialAccountDraftJobService(
        repository=repository,
        artifact_store=store,
        account_fingerprint=_ACCOUNT,
        max_attempts=3,
        max_image_bytes=1024,
        clock=lambda: _NOW,
        preparer=preparer,
    )
    client = _OrderingClient(repository)

    enqueued = await service.reconcile()
    first_process = _executor(repository, store, preparer, client)
    first_status = await first_process.execute_next("wechat.worker.test")
    assert first_status is not None
    assert first_status.items[0].status is WeChatDraftItemStatus.SUCCEEDED

    restarted_process = _executor(repository, store, preparer, client)
    second_status = await restarted_process.execute_next("wechat.worker.test")
    final_status = await restarted_process.execute_next("wechat.worker.test")

    assert enqueued.enqueued == 1
    assert second_status is not None and final_status is not None
    assert final_status.job.status is WeChatDraftJobStatus.READY
    assert client.draft_ordinals == [1, 2, 3]

    replay = await service.reconcile()
    no_work = await restarted_process.execute_next("wechat.worker.test")

    assert replay.existing == 1
    assert no_work is None
    assert client.draft_ordinals == [1, 2, 3]


def test_account_fingerprint_preserves_opaque_app_id_case() -> None:
    assert wechat_draft_account_fingerprint("wxOpaqueAccount") != (
        wechat_draft_account_fingerprint("wxopaqueaccount")
    )
