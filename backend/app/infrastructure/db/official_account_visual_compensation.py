"""Explicit one-edition compensation, never an ordinary unknown-result retry.

The old ambiguous attempts remain immutable. A closed workflow authorization and
consumption retain the new physical operation identity without changing the logical
article/visual identities. The CLI has one fixed target and no publishing authority.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    OfficialAccountGeneratedVisualPlan,
)
from app.application.ports.official_account_strict_visual import StrictGeneratedVisualClaim
from app.application.ports.wechat_official_account_manual_draft import ManualDraftJournal
from app.domain.official_account_local import fingerprint
from app.infrastructure.db.models import (
    OfficialAccountArticleAttemptModel as Attempt,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleRunModel as Run,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleVersionModel as Article,
)
from app.infrastructure.db.models import (
    OfficialAccountDraftOwnerModel as Owner,
)
from app.infrastructure.db.models import (
    OfficialAccountGeneratedVisualModel as Visual,
)
from app.infrastructure.db.models import (
    OfficialAccountRenderVersionModel as Render,
)
from app.infrastructure.db.models import (
    OfficialAccountSingleEditionModel as Edition,
)
from app.infrastructure.db.models import (
    WeChatOfficialAccountDraftItemModel as DraftItem,
)

AUTH_STAGE = "visual_compensation_authorized"
CONSUMED_STAGE = "visual_compensation_consumed"
SHANGHAI = ZoneInfo("Asia/Shanghai")
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CompensationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    edition_id: UUID
    run_id: UUID
    article_version_id: UUID
    visual_id: UUID
    business_date: date


SEPTEMBER_16_TARGET = CompensationTarget(
    edition_id=UUID("41b26b7f-e792-56ff-bdfa-643171114056"),
    run_id=UUID("5e2bbc6e-6bec-4234-b516-7b2c58e198c6"),
    article_version_id=UUID("5107bfe9-ae30-4a2d-9fd0-c57a369fa6a8"),
    visual_id=UUID("31c58fc2-2722-4a28-957d-0b7b9b16d510"),
    business_date=date(2026, 9, 16),
)


class VisualCompensationAuthorization(CompensationTarget):
    version: Literal["single-visual-compensation-v1"] = "single-visual-compensation-v1"
    account_fingerprint: Sha256
    render_version_id: UUID
    original_attempt_id: UUID
    original_intent_lease_token: UUID
    original_attempt_number: Annotated[int, Field(strict=True, ge=1, le=5)]
    successor_attempt_number: Annotated[int, Field(strict=True, ge=2, le=6)]
    max_attempts: Annotated[int, Field(strict=True, ge=2, le=6)]
    logical_request_fingerprint: Sha256
    original_run_bundle_fingerprint: Sha256
    preserved_content_fingerprint: Sha256
    snapshot_fingerprint: Sha256
    authorized_at: datetime
    original_expires_at: datetime
    recovery_expires_at: datetime

    @model_validator(mode="after")
    def _closed_authority(self) -> VisualCompensationAuthorization:
        if (
            any(
                value.utcoffset() is None
                for value in (
                    self.authorized_at,
                    self.original_expires_at,
                    self.recovery_expires_at,
                )
            )
            or self.successor_attempt_number != self.original_attempt_number + 1
            or self.successor_attempt_number > self.max_attempts
            or not self.original_expires_at <= self.authorized_at < self.recovery_expires_at
            or self.recovery_expires_at - self.authorized_at > timedelta(hours=2)
            or any(
                value.astimezone(SHANGHAI).date() != self.business_date
                for value in (
                    self.authorized_at,
                    self.original_expires_at,
                    self.recovery_expires_at,
                )
            )
        ):
            raise ValueError("visual_compensation_authority_invalid")
        return self

    @property
    def authorization_fingerprint(self) -> str:
        return fingerprint("single-visual-compensation-v1", self.model_dump(mode="json"))

    @property
    def provider_request_fingerprint(self) -> str:
        return fingerprint(
            "single-visual-compensation-provider-request-v1",
            self.authorization_fingerprint,
            self.logical_request_fingerprint,
        )


class VisualCompensationConsumption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["single-visual-compensation-consumed-v1"] = (
        "single-visual-compensation-consumed-v1"
    )
    authorization_fingerprint: Sha256
    provider_request_fingerprint: Sha256
    visual_id: UUID
    attempt_number: Annotated[int, Field(strict=True, ge=2, le=6)]
    lease_token: UUID


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("visual_compensation_precondition_failed")


async def _workflow_record(session: AsyncSession, run_id: UUID, stage: str) -> Attempt | None:
    return cast(
        Attempt | None,
        await session.scalar(
            select(Attempt).where(
                Attempt.run_id == run_id, Attempt.stage == stage, Attempt.ordinal == 1
            )
        ),
    )


def _authorization(row: Attempt) -> VisualCompensationAuthorization:
    value = VisualCompensationAuthorization.model_validate(row.safe_metadata)
    _require(
        row.capability == "workflow"
        and row.status == "succeeded"
        and row.run_id == value.run_id
        and row.article_version_id == value.article_version_id
        and row.request_fingerprint == value.authorization_fingerprint
    )
    return value


async def resolve_visual_provider_request_fingerprint(
    session: AsyncSession, *, run_id: UUID, visual_id: UUID
) -> str | None:
    """Subsequent proved non-applied retries retain the compensating physical key."""
    consumed_row = await _workflow_record(session, run_id, CONSUMED_STAGE)
    if consumed_row is None:
        return None
    auth_row = await _workflow_record(session, run_id, AUTH_STAGE)
    _require(auth_row is not None)
    assert auth_row is not None
    auth = _authorization(auth_row)
    consumed = VisualCompensationConsumption.model_validate(consumed_row.safe_metadata)
    _require(
        consumed_row.capability == "workflow"
        and consumed_row.status == "succeeded"
        and consumed_row.article_version_id == auth.article_version_id
        and consumed_row.request_fingerprint == auth.provider_request_fingerprint
        and consumed.authorization_fingerprint == auth.authorization_fingerprint
        and consumed.provider_request_fingerprint == auth.provider_request_fingerprint
        and consumed.visual_id == auth.visual_id
        and consumed.attempt_number == auth.successor_attempt_number
    )
    return auth.provider_request_fingerprint if visual_id == auth.visual_id else None


def _new_record(
    auth: VisualCompensationAuthorization,
    *,
    stage: str,
    request_fingerprint: str,
    metadata: dict[str, Any],
    now: datetime,
) -> Attempt:
    return Attempt(
        id=uuid4(),
        run_id=auth.run_id,
        article_version_id=auth.article_version_id,
        stage=stage,
        capability="workflow",
        ordinal=1,
        status="succeeded",
        request_fingerprint=request_fingerprint,
        safe_metadata=metadata,
        created_at=now,
        completed_at=now,
    )


async def claim_authorized_visual_compensation(
    session: AsyncSession,
    run: Run,
    claimed: ClaimedOfficialAccountRun,
    row: Visual,
    plan: OfficialAccountGeneratedVisualPlan,
) -> StrictGeneratedVisualClaim | None:
    """Caller already holds run/visual locks and commits the consumed intent atomically.

    None does not mutate state. An abandoned successor claim consumes the run
    attempt budget, not another compensation; a later lease may never replay it.
    """
    from app.infrastructure.db.official_account_local import (
        _assert_generated_visual_plan,
        _frozen_retry_policy,
        _stored_generated_visual,
    )

    auth_row = await _workflow_record(session, run.id, AUTH_STAGE)
    if auth_row is None or await _workflow_record(session, run.id, CONSUMED_STAGE) is not None:
        return None
    auth = _authorization(auth_row)
    now = datetime.now(UTC)
    maximum, _delay, expiry = _frozen_retry_policy(run.version_bundle.get("execution_retry_policy"))
    if (
        row.id != auth.visual_id
        or row.status != "result_unknown"
        or run.id != claimed.run_id
        or run.status != "running"
        or run.lease_token != claimed.lease_token
        or run.lease_expires_at is None
        or run.lease_expires_at <= now
        or run.attempt_count != claimed.attempt_number
        or claimed.attempt_number != auth.successor_attempt_number
        or row.intent_attempt_number != auth.original_attempt_number
        or row.intent_lease_token != auth.original_intent_lease_token
        or (run.active_article_version_id, run.active_render_version_id)
        != (auth.article_version_id, auth.render_version_id)
        or (row.run_id, row.article_version_id, row.render_version_id, row.request_fingerprint)
        != (
            auth.run_id,
            auth.article_version_id,
            auth.render_version_id,
            auth.logical_request_fingerprint,
        )
        or maximum != auth.max_attempts
        or expiry != auth.recovery_expires_at
        or not auth.authorized_at <= now < auth.recovery_expires_at
    ):
        return None
    _assert_generated_visual_plan(row, plan)
    old = await session.get(Attempt, auth.original_attempt_id)
    article = await session.get(Article, auth.article_version_id)
    render = await session.get(Render, auth.render_version_id)
    _require(
        old is not None
        and old.status == "failed"
        and old.run_id == run.id
        and old.capability == "visual_generation"
        and old.stage == "generating_body_visuals"
        and old.article_version_id == auth.article_version_id
        and old.request_fingerprint == auth.logical_request_fingerprint
        and old.ordinal == auth.original_attempt_number * 10 + row.ordinal
        and old.error_code == "official_account_generated_visual_result_unknown"
        and (old.provider, old.model) == (row.provider, row.model)
        and old.provider_request_id is None
        and article is not None
        and render is not None
        and _preserved_content(article, render) == auth.preserved_content_fingerprint
    )
    original_bundle = {
        **run.version_bundle,
        "execution_retry_policy": {
            **run.version_bundle["execution_retry_policy"],
            "expires_at": auth.original_expires_at.isoformat(),
        },
    }
    _require(_bundle_fingerprint(original_bundle) == auth.original_run_bundle_fingerprint)
    consumed = VisualCompensationConsumption(
        authorization_fingerprint=auth.authorization_fingerprint,
        provider_request_fingerprint=auth.provider_request_fingerprint,
        visual_id=row.id,
        attempt_number=claimed.attempt_number,
        lease_token=claimed.lease_token,
    )
    session.add(
        _new_record(
            auth,
            stage=CONSUMED_STAGE,
            request_fingerprint=auth.provider_request_fingerprint,
            metadata=consumed.model_dump(mode="json"),
            now=now,
        )
    )
    row.status = "generating"
    row.error_code = None
    row.completed_at = None
    row.intent_lease_token = claimed.lease_token
    row.intent_attempt_number = claimed.attempt_number
    run.current_stage = "generating_body_visuals"
    return StrictGeneratedVisualClaim(
        "newly_claimed", _stored_generated_visual(row), auth.provider_request_fingerprint
    )


def _snapshot(row: Any) -> dict[str, Any]:
    # Only stored in a protected operator receipt, never in console/repo/safe_metadata.
    return cast(
        dict[str, Any],
        json.loads(
            json.dumps(
                {column.key: getattr(row, column.key) for column in row.__table__.columns},
                default=str,
            )
        ),
    )


def _bundle_fingerprint(bundle: dict[str, Any]) -> str:
    """Normalize the sole timestamp representation; preserve every other frozen byte."""
    policy = bundle["execution_retry_policy"]
    return fingerprint(
        {
            **bundle,
            "execution_retry_policy": {
                **policy,
                "expires_at": datetime.fromisoformat(policy["expires_at"])
                .astimezone(UTC)
                .isoformat(),
            },
        }
    )


def _preserved_content(article: Article, render: Render) -> str:
    return fingerprint(
        "visual-compensation-preserved-content-v1", _snapshot(article), _snapshot(render)
    )


def check_journal_absence(
    journal: ManualDraftJournal, *, names: list[str], target: CompensationTarget
) -> None:
    """Call with the existing account journal locked; no new/empty substitute root."""
    _require(len(names) <= 10000)
    prefix = f"single-{target.edition_id.hex}-"
    for name in names:
        _require(not name.startswith(prefix))
        if name.endswith("-claim.json"):
            claim = journal.read(name)
            _require(claim is not None)
            assert claim is not None
            binding = claim.get("binding")
            _require(
                not isinstance(binding, dict) or binding.get("edition_id") != str(target.edition_id)
            )


async def authorize_visual_compensation(
    session: AsyncSession,
    *,
    target: CompensationTarget,
    journal: ManualDraftJournal,
    journal_names: list[str],
    now: datetime,
    apply: bool = False,
) -> VisualCompensationAuthorization:
    """Exact-target preflight/apply; caller owns journal lock and DB transaction.

    Repeated apply returns the original authorization without touching any row or
    extending its deadline, including after success, crash, or a second unknown.
    """
    from app.infrastructure.db.official_account_local import _frozen_retry_policy

    edition = await session.scalar(
        select(Edition).where(Edition.id == target.edition_id).with_for_update()
    )
    run = await session.scalar(select(Run).where(Run.id == target.run_id).with_for_update())
    row = await session.scalar(
        select(Visual).where(Visual.id == target.visual_id).with_for_update()
    )
    _require(edition is not None and run is not None and row is not None)
    assert edition is not None and run is not None and row is not None
    prior_auth = await _workflow_record(session, target.run_id, AUTH_STAGE)
    if prior_auth is not None:
        old_auth = _authorization(prior_auth)
        _require(all(getattr(old_auth, key) == value for key, value in target))
        return old_auth
    _require(
        now.utcoffset() is not None
        and now.astimezone(SHANGHAI).date() == target.business_date
        and edition.business_date == target.business_date
        and edition.article_run_id == run.id == row.run_id
        and edition.material_package_id == run.material_package_id
        and run.active_article_version_id == target.article_version_id == row.article_version_id
        and run.active_render_version_id == row.render_version_id
        and edition.status in {"outcome_unknown", "expired"}
        and run.status == "result_unknown"
        and row.status == "result_unknown"
        and row.error_code == "official_account_generated_visual_result_unknown"
        and edition.expires_at <= now
        and edition.lease_token is None
        and edition.lease_expires_at is None
        and run.lease_token is None
        and run.lease_expires_at is None
        and run.lease_owner is None
        and row.intent_attempt_number == run.attempt_count
        and run.attempt_count == 1
        and row.intent_lease_token is not None
        and edition.prepared_artifact is None
        and edition.receipt_fingerprint is None
        and edition.article_fingerprint is None
        and edition.content_fingerprint is None
        and run.active_draft_id is None
        and run.active_body_media_id is None
        and run.active_cover_media_id is None
        and edition.event_id is not None
    )
    check_journal_absence(journal, names=journal_names, target=target)
    article = await session.get(Article, target.article_version_id)
    render = await session.get(Render, row.render_version_id)
    _require(
        article is not None
        and render is not None
        and article.run_id == run.id
        and render.run_id == run.id
        and render.article_version_id == article.id
        and article.audit_snapshot.get("accepted") is True
        and article.validation_snapshot.get("passed") is True
    )
    assert article is not None and render is not None
    owner = await session.scalar(
        select(Owner)
        .where(
            Owner.account_fingerprint == edition.account_fingerprint,
            Owner.key_kind == "event",
            Owner.key_value == str(edition.event_id),
        )
        .with_for_update()
    )
    _require(
        owner is not None and owner.owner == str(edition.id) and owner.status == "outcome_unknown"
    )
    assert owner is not None
    owners = (
        await session.scalars(
            select(Owner).where(
                Owner.account_fingerprint == edition.account_fingerprint,
                Owner.owner == str(edition.id),
            )
        )
    ).all()
    _require(len(owners) == 1)
    drafts = await session.scalar(
        select(DraftItem.job_id)
        .where(
            or_(
                DraftItem.source_ref == str(run.id),
                DraftItem.source_ref == str(edition.id),
                DraftItem.source_fingerprint == run.source_fingerprint,
                DraftItem.article_fingerprint == article.content_fingerprint,
            )
        )
        .limit(1)
    )
    _require(drafts is None)
    original = await session.scalar(
        select(Attempt).where(
            Attempt.run_id == run.id,
            Attempt.article_version_id == article.id,
            Attempt.capability == "visual_generation",
            Attempt.stage == "generating_body_visuals",
            Attempt.ordinal == run.attempt_count * 10 + row.ordinal,
            Attempt.status == "failed",
            Attempt.request_fingerprint == row.request_fingerprint,
            Attempt.error_code == row.error_code,
        )
    )
    _require(
        original is not None
        and original.provider_request_id is None
        and row.intent_lease_token is not None
    )
    assert original is not None
    assert row.intent_lease_token is not None
    maximum, _delay, expiry = _frozen_retry_policy(run.version_bundle.get("execution_retry_policy"))
    _require(
        expiry == edition.expires_at
        and maximum == edition.retry_policy.get("max_attempts")
        and maximum == 3
        and run.attempt_count < maximum
    )
    end_of_day = datetime.combine(target.business_date, time.max, SHANGHAI)
    recovery_expiry = min(now + timedelta(hours=2), end_of_day)
    snapshot = {
        "edition": _snapshot(edition),
        "run": _snapshot(run),
        "visual": _snapshot(row),
        "original_attempt": _snapshot(original),
        "event_owner": _snapshot(owner),
        "article": _snapshot(article),
        "render": _snapshot(render),
    }
    auth = VisualCompensationAuthorization(
        **target.model_dump(),
        account_fingerprint=edition.account_fingerprint,
        render_version_id=render.id,
        original_attempt_id=original.id,
        original_intent_lease_token=row.intent_lease_token,
        original_attempt_number=run.attempt_count,
        successor_attempt_number=run.attempt_count + 1,
        max_attempts=maximum,
        logical_request_fingerprint=row.request_fingerprint,
        original_run_bundle_fingerprint=_bundle_fingerprint(run.version_bundle),
        preserved_content_fingerprint=_preserved_content(article, render),
        snapshot_fingerprint=fingerprint(snapshot),
        authorized_at=now,
        original_expires_at=edition.expires_at,
        recovery_expires_at=recovery_expiry,
    )
    if not apply:
        return auth
    # Snapshot first: losing DB commit can leave only a harmless create-only receipt.
    name = f"compensation-{target.visual_id.hex}-{auth.snapshot_fingerprint[:16]}.json"
    old_snapshot = journal.read(name)
    if old_snapshot is None:
        journal.write(name, snapshot)
    else:
        _require(old_snapshot == snapshot)
    session.add(
        _new_record(
            auth,
            stage=AUTH_STAGE,
            request_fingerprint=auth.authorization_fingerprint,
            metadata=auth.model_dump(mode="json"),
            now=now,
        )
    )
    run.version_bundle = {
        **run.version_bundle,
        "execution_retry_policy": {
            **run.version_bundle["execution_retry_policy"],
            "expires_at": recovery_expiry.isoformat(),
        },
    }
    run.status = "queued"
    run.current_stage = "generating_body_visuals"
    run.available_at = now
    run.completed_at = None
    run.error_code = None
    run.error_retryable = False
    run.updated_at = now
    edition.status = "generating"
    edition.error_code = None
    edition.expires_at = recovery_expiry
    edition.available_at = now
    edition.updated_at = now
    owner.status = "reserved"
    owner.updated_at = now
    return auth


async def _main(apply: bool) -> None:
    from app.core.config import get_settings
    from app.domain.wechat_official_account_draft_jobs import wechat_draft_account_fingerprint
    from app.infrastructure.db.session import create_engine, create_session_factory
    from app.infrastructure.wechat_official_account.manual_journal import LocalManualDraftJournal

    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    journal = None
    try:
        async with sessions() as session:
            edition = await session.get(Edition, SEPTEMBER_16_TARGET.edition_id)
            _require(edition is not None)
            assert edition is not None
            account = edition.account_fingerprint
        _require(
            settings.wechat_mp_app_id is not None
            and wechat_draft_account_fingerprint(settings.wechat_mp_app_id.get_secret_value())
            == account
        )
        root = Path(settings.wechat_mp_draft_artifact_root)
        directory = root / "manual-v1" / account
        _require(directory.is_dir() and not directory.is_symlink())
        journal = LocalManualDraftJournal(root, account)
        async with sessions() as session, session.begin():
            auth = await authorize_visual_compensation(
                session,
                target=SEPTEMBER_16_TARGET,
                journal=journal,
                journal_names=os.listdir(directory),
                now=datetime.now(UTC),
                apply=apply,
            )
        print(
            json.dumps(
                {
                    "mode": "apply" if apply else "plan",
                    "authorization": auth.model_dump(mode="json"),
                },
                ensure_ascii=False,
            )
        )
    finally:
        if journal is not None:
            journal.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="One authorized September 16 draft-only visual compensation"
    )
    parser.add_argument(
        "--apply", action="store_true", help="persist exact-target one-time compensation"
    )
    arguments = parser.parse_args()
    try:
        asyncio.run(_main(arguments.apply))
    except Exception:
        # No raw ORM/transport/config error bodies or credentials in operator output.
        raise SystemExit("visual_compensation_operator_failed") from None
