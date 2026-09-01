"""Application boundary for durable WeChat Official Account draft jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.wechat_official_account_draft_jobs import (
    WeChatDraftJobClaim,
    WeChatDraftJobEnqueue,
    WeChatDraftStatusProjection,
)


class WeChatOfficialAccountDraftJobRepository(Protocol):
    async def enqueue(
        self,
        command: WeChatDraftJobEnqueue,
        *,
        now: datetime,
    ) -> tuple[WeChatDraftStatusProjection, bool]: ...

    async def get_status(self, job_id: UUID) -> WeChatDraftStatusProjection: ...

    async def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> WeChatDraftJobClaim | None: ...

    async def heartbeat(
        self,
        claim: WeChatDraftJobClaim,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> bool: ...

    async def mark_side_effect_started(
        self,
        claim: WeChatDraftJobClaim,
        *,
        endpoint: str,
        now: datetime,
    ) -> bool: ...

    async def succeed(
        self,
        claim: WeChatDraftJobClaim,
        *,
        endpoint: str,
        uploaded_image_count: int,
        draft_media_fingerprint: str,
        now: datetime,
    ) -> WeChatDraftStatusProjection: ...

    async def fail_known(
        self,
        claim: WeChatDraftJobClaim,
        *,
        error_code: str,
        endpoint: str | None,
        retryable: bool,
        uploaded_image_count: int,
        available_at: datetime,
        now: datetime,
    ) -> WeChatDraftStatusProjection: ...

    async def mark_outcome_unknown(
        self,
        claim: WeChatDraftJobClaim,
        *,
        error_code: str,
        endpoint: str | None,
        uploaded_image_count: int,
        now: datetime,
    ) -> WeChatDraftStatusProjection: ...
