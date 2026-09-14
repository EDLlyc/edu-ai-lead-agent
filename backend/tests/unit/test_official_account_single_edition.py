from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.application.ports.official_account_single_edition import SingleEdition
from app.application.ports.wechat_official_account import (
    WeChatDraftCreated,
    WeChatInlineImage,
    WeChatMpTransientError,
    WeChatThumbMedia,
)
from app.application.ports.wechat_official_account_manual_draft import ManualDraftError
from app.application.services.official_account_single_edition import SingleEditionProducer
from app.application.services.wechat_official_account_draft import (
    WeChatPreparedDraft,
    WeChatPreparedMedia,
)
from app.application.services.wechat_single_edition_delivery import deliver_single
from app.core.config import Settings
from app.domain.official_account_single_edition import (
    due_single_edition,
    edition_window,
    select_single_article,
    single_edition_id,
)
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from app.infrastructure.wechat_official_account.manual_journal import (
    LocalManualDraftJournal,
    fingerprint,
)
from test_official_account_strict_prepared import _write, strict_projection  # noqa: F401
from test_official_account_visual_preview import captured  # noqa: F401
from test_official_account_weekly_edition import _CUTOFF, _governed
from test_official_account_xiaosai_final_cta import final_cta  # noqa: F401

ACCOUNT = "a" * 64
DAY = date(2026, 9, 16)
NOW = datetime(2026, 9, 16, 2, tzinfo=UTC)


def edition(**changes):
    window = edition_window(DAY)
    value = SingleEdition(
        id=single_edition_id(ACCOUNT, DAY),
        account=ACCOUNT,
        business_date=DAY,
        prepare_at=window.prepare_at,
        deliver_at=window.deliver_at,
        expires_at=window.expires_at,
        identity=official_account_identity_from_settings(
            Settings(_env_file=None), provider="zhipu", model="glm-test"
        ),
        max_attempts=3,
        retry_base_seconds=60,
        status="delivering",
        attempts={},
        available_at=NOW,
        lease_token=uuid4(),
        article_fingerprint="b" * 64,
        content_fingerprint="c" * 64,
    )
    return replace(value, **changes)


def prepared():
    media = WeChatPreparedMedia("assets/body.jpg", "image/jpeg", b"body", "body.jpg")
    return WeChatPreparedDraft(
        role="application_case",
        article_fingerprint="b" * 64,
        content_fingerprint="c" * 64,
        title="科学教育",
        author="程岳",
        digest="家长与孩子共同学习",
        content_source_url="https://education.news.cn/article.html",
        body_html='<section><img src="assets/body.jpg"/></section>',
        body_media=(media,),
        cover=WeChatPreparedMedia("assets/cover.jpg", "image/jpeg", b"cover", "cover.jpg"),
        need_open_comment=False,
        only_fans_can_comment=False,
    )


class Client:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def upload_inline_image(self, *args):
        self.calls.append("inline")
        return WeChatInlineImage("https://mmbiz.qpic.cn/test.jpg")

    async def upload_thumb(self, *args):
        self.calls.append("thumb")
        if self.error:
            raise self.error
        return WeChatThumbMedia("thumb_id")

    async def add_draft(self, article):
        self.calls.append("add")
        self.article = article
        return WeChatDraftCreated("draft_id")


class Repository:
    def __init__(self, value=None, fail_save=False):
        self.value = value
        self.fail_save = fail_save
        self.saved = []

    async def heartbeat(self, *args, **kwargs):
        return True

    async def save(self, value, **kwargs):
        if self.fail_save:
            raise OSError("database unavailable")
        self.value = value
        self.saved.append(value)
        return True


@pytest.mark.parametrize("offset", range(7))
def test_only_mwf_current_shanghai_date(offset):
    day = date(2026, 9, 14) + timedelta(days=offset)
    now = datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=1)
    result = due_single_edition(now, minimum_date=date(2026, 9, 14))
    assert (result is not None) == (day.weekday() in {0, 2, 4})
    if result:
        assert result.deliver_at.hour == 2
        assert result.expires_at.hour == 8


@pytest.mark.parametrize(
    "hour,minute,due",
    [
        (0, 59, False),
        (1, 0, True),
        (1, 59, True),
        (2, 0, True),
        (7, 59, True),
        (8, 0, False),
        (16, 0, False),
    ],
)
def test_preparation_delivery_expiry_and_no_next_day_catchup(hour, minute, due):
    result = due_single_edition(NOW.replace(hour=hour, minute=minute), minimum_date=DAY)
    assert (result is not None) == due
    if result:
        assert (NOW.replace(hour=hour, minute=minute) >= result.deliver_at) == (hour >= 2)


def test_cutover_never_backfills_monday_and_naive_time_rejected():
    assert due_single_edition(datetime(2026, 9, 14, 2, tzinfo=UTC), minimum_date=DAY) is None
    with pytest.raises(ValueError):
        due_single_edition(NOW.replace(tzinfo=None), minimum_date=DAY)


def test_one_eligible_candidate_without_three_roles_and_history_veto():
    item = _governed(1, age_days=1, organization_type="enterprise")
    result = select_single_article((item,), cutoff=_CUTOFF)
    assert result.event_id == item.candidate.event_id
    assert (
        select_single_article((item,), cutoff=_CUTOFF, excluded_events=frozenset({result.event_id}))
        is None
    )
    veto = _governed(2, age_days=1, organization_type="government", veto=True)
    assert select_single_article((veto,), cutoff=_CUTOFF) is None


def test_highest_stored_score_not_three_role_quota():
    low = _governed(1, age_days=1, organization_type="enterprise", total=0.7)
    high = _governed(2, age_days=1, organization_type="enterprise", total=0.95)
    assert select_single_article((low, high), cutoff=_CUTOFF).event_id == high.candidate.event_id


@pytest.mark.asyncio
async def test_ack_before_db_failure_reconciles_after_midnight_without_writes(tmp_path):
    value = edition()
    client = Client()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        with pytest.raises(OSError):
            await deliver_single(
                repository=Repository(fail_save=True),
                edition=value,
                prepared=prepared(),
                journal=journal,
                client=client,
                clock=lambda: NOW,
            )
    finally:
        journal.close()
    assert client.calls == ["inline", "thumb", "add"]
    client = Client()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    repository = Repository()
    try:
        await deliver_single(
            repository=repository,
            edition=value,
            prepared=prepared(),
            journal=journal,
            client=client,
            clock=lambda: NOW + timedelta(days=1),
        )
    finally:
        journal.close()
    assert client.calls == []
    assert repository.value.status == "delivered"
    assert repository.value.receipt_fingerprint == sha256(b"draft_id").hexdigest()


@pytest.mark.asyncio
async def test_definite_rejection_retries_only_unacknowledged_step(tmp_path):
    value = edition()
    first = Client(WeChatMpTransientError(endpoint="material_add_thumb", provider_code=-1))
    repository = Repository()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await deliver_single(
            repository=repository,
            edition=value,
            prepared=prepared(),
            journal=journal,
            client=first,
            clock=lambda: NOW,
        )
    finally:
        journal.close()
    assert first.calls == ["inline", "thumb"]
    assert repository.value.status == "delivering"
    second = Client()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await deliver_single(
            repository=repository,
            edition=repository.value,
            prepared=prepared(),
            journal=journal,
            client=second,
            clock=lambda: NOW + timedelta(minutes=1),
        )
    finally:
        journal.close()
    assert second.calls == ["thumb", "add"]
    assert repository.value.status == "delivered"
    assert second.article.author == "程岳"
    assert second.article.content_source_url == prepared().content_source_url


@pytest.mark.parametrize("provider_code", [None, 500, 503])
@pytest.mark.asyncio
async def test_transport_and_http_5xx_remain_unknown_not_safe_retry(tmp_path, provider_code):
    client = Client(
        WeChatMpTransientError(endpoint="material_add_thumb", provider_code=provider_code)
    )
    repository = Repository()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await deliver_single(
            repository=repository,
            edition=edition(),
            prepared=prepared(),
            journal=journal,
            client=client,
            clock=lambda: NOW,
        )
        assert repository.value.status == "outcome_unknown"
        second = Client()
        await deliver_single(
            repository=repository,
            edition=edition(),
            prepared=prepared(),
            journal=journal,
            client=second,
            clock=lambda: NOW,
        )
        assert second.calls == []
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_expiry_never_creates_new_side_effect(tmp_path):
    client = Client()
    repository = Repository()
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    try:
        await deliver_single(
            repository=repository,
            edition=edition(),
            prepared=prepared(),
            journal=journal,
            client=client,
            clock=lambda: NOW + timedelta(days=1),
        )
    finally:
        journal.close()
    assert client.calls == []
    assert repository.value.error_code == "single_delivery_expired"


@pytest.mark.parametrize(
    "version", ["manual-draft-binding-v1", "manual-local-editorial-preview-binding-v1"]
)
def test_manual_claim_and_ack_bridge_accepts_null_content_and_unknown_run(tmp_path, version):
    journal = LocalManualDraftJournal(tmp_path, ACCOUNT)
    fp = "d" * 64
    binding = {
        "version": version,
        "raw_article": fp,
        "raw_content": None,
        "provenance": {"run_id": str(uuid4()), "production_run_status": "result_unknown"},
    }
    intent = {"binding": fingerprint(binding), "step": "add", "request": {}}
    try:
        journal.write(fp + "-claim.json", {"account": ACCOUNT, "binding": binding})
        assert journal.manual_history(ACCOUNT)[0][2] is False
        journal.write(fp + "-add-intent.json", intent)
        journal.write(
            fp + "-add-ack.json", {"intent_sha256": fingerprint(intent), "value": "private_draft"}
        )
        rows = journal.manual_history(ACCOUNT)
        assert rows[0][0] == fp and rows[0][2] is True
        assert "private_draft" not in repr(rows)
        with pytest.raises(ManualDraftError):
            LocalManualDraftJournal(tmp_path, ACCOUNT)
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_producer_poll_preserves_article_and_does_not_reenqueue_ready_text():
    run_id = uuid4()
    value = edition(status="generating", article_run_id=run_id)
    repository = Repository(value)
    repository.claim = AsyncMock(return_value=value)
    articles = SimpleNamespace(
        get_run=AsyncMock(return_value=SimpleNamespace(id=run_id, status="running")),
        enqueue_material_package=AsyncMock(),
    )
    producer = SingleEditionProducer(
        repository=repository,
        planner=object(),
        article_repository=articles,
        artifacts=object(),
        checkpoints=object(),
        account=ACCOUNT,
        clock=lambda: NOW,
    )
    await producer.process_once()
    articles.enqueue_material_package.assert_not_called()
    assert repository.value.article_run_id == run_id
    assert repository.value.attempts == {}
    articles.get_run.return_value = SimpleNamespace(id=run_id, status="ready")
    await producer.process_once()
    assert repository.value.status == "preparing"


@pytest.mark.parametrize(
    "flag",
    [
        "official_account_weekly_scheduler_enabled",
        "official_account_weekly_worker_enabled",
        "wechat_mp_draft_auto_enqueue_enabled",
    ],
)
def test_settings_reject_overlap(flag):
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            official_account_single_enabled=True,
            official_account_single_min_date=DAY,
            official_account_single_account_fingerprint=ACCOUNT,
            **{flag: True},
        )


@pytest.mark.asyncio
async def test_single_candidate_to_real_canonical_child_and_draft_framing(final_cta, tmp_path):  # noqa: F811
    from app.application.ports.official_account_weekly_production import WeeklyProductionInputItem
    from app.application.services.official_account_strict_prepared import (
        build_strict_prepared_projection,
    )
    from app.domain.official_account_source_presentation import READABLE_SOURCE_PRESENTATION_VERSION
    from app.domain.official_account_weekly_dag import WeeklyDagArtifact
    from app.domain.official_account_weekly_edition import WeeklyArticleRole
    from app.domain.official_account_xiaosai_footer import (
        CHENGYUE_HEADER_PUBLICATION_SHA256,
        XIAOSAI_FOOTER_PUBLICATION_SHA256,
    )
    from app.infrastructure.official_account_weekly_production import (
        LocalWeeklyProductionArtifactOwner,
    )
    from app.infrastructure.wechat_official_account.prepared_artifacts import (
        _directory_size,
        load_prepared_draft_child,
    )

    inputs, _ = final_cta
    projection = build_strict_prepared_projection(
        **inputs, source_presentation=READABLE_SOURCE_PRESENTATION_VERSION
    )
    root = tmp_path / "prepared"
    target = root / "children" / f"wechat-draft-prepared-child-{projection.child_fingerprint}"
    _write(projection, target)
    artifact = WeeklyDagArtifact(
        opaque_ref="wechat-prepared-child-v1:" + projection.child_fingerprint,
        fingerprint=projection.child_fingerprint,
        media_type="application/vnd.wechat.prepared-draft-child+directory",
        byte_size=_directory_size(target),
    )
    # Bind the actual persisted child ref discriminator, not a new weekly aggregate.
    from app.infrastructure.wechat_official_account.prepared_artifacts import (
        PREPARED_DRAFT_CHILD_REF_VERSION,
    )

    artifact = replace(
        artifact, opaque_ref=PREPARED_DRAFT_CHILD_REF_VERSION + ":" + projection.child_fingerprint
    )
    expected = load_prepared_draft_child(
        artifact,
        work_root=root,
        role=WeeklyArticleRole(inputs["role"]),
        max_image_bytes=10 * 1024 * 1024,
    )
    run_id = inputs["run_id"]
    item = WeeklyProductionInputItem(
        role=WeeklyArticleRole(inputs["role"]),
        material_package_id=uuid4(),
        event_id=uuid4(),
        event_version_id=uuid4(),
        title="真实单篇",
        material_request_fingerprint="1" * 64,
        score_fingerprint="2" * 64,
        source_metadata_fingerprint="3" * 64,
        organization_type="news_media",
        official_authority=None,
        selection_reason="stored_score",
        affinity_reasons=(),
        governed_total=0.9,
        governed_score_version="frozen-test",
    )
    repository = Repository(
        edition(status="admitted", article_fingerprint=None, content_fingerprint=None)
    )

    async def claim(**kwargs):
        return repository.value

    async def select(value, selected, selected_artifact, **kwargs):
        repository.value = replace(
            value,
            status="generating",
            material_package_id=selected.material_package_id,
            event_id=selected.event_id,
            role=selected.role.value,
            selection_artifact=selected_artifact,
        )
        return True

    repository.claim = claim
    repository.select = select
    repository.excluded_events = AsyncMock(return_value=frozenset())
    repository.reserve_article = AsyncMock(return_value=True)
    articles = SimpleNamespace(
        enqueue_material_package=AsyncMock(return_value=(SimpleNamespace(id=run_id), True)),
        get_run=AsyncMock(return_value=SimpleNamespace(id=run_id, status="ready")),
    )
    artifacts = SimpleNamespace(
        build_child=AsyncMock(return_value=artifact), validate_child=lambda *a, **kw: expected
    )
    producer = SingleEditionProducer(
        repository=repository,
        planner=SimpleNamespace(plan_single=AsyncMock(return_value=item)),
        article_repository=articles,
        artifacts=artifacts,
        checkpoints=LocalWeeklyProductionArtifactOwner(tmp_path / "checkpoints"),
        account=ACCOUNT,
        clock=lambda: NOW,
    )
    for _ in range(3):
        assert await producer.process_once()
    assert repository.value.status == "ready"
    articles.enqueue_material_package.assert_awaited_once()
    artifacts.build_child.assert_awaited_once()
    bodies = []

    class Outbound(Client):
        async def upload_inline_image(self, body, *args):
            bodies.append(sha256(body).hexdigest())
            self.calls.append("inline")
            return WeChatInlineImage(f"https://mmbiz.qpic.cn/{len(bodies)}.jpg")

    client = Outbound()
    journal = LocalManualDraftJournal(tmp_path / "journal", ACCOUNT)
    try:
        await deliver_single(
            repository=repository,
            edition=repository.value,
            prepared=expected,
            journal=journal,
            client=client,
            clock=lambda: NOW,
        )
    finally:
        journal.close()
    assert repository.value.status == "delivered"
    assert client.calls.count("add") == 1
    assert client.article.author == "程岳"
    assert client.article.content_source_url == inputs["article"].sources[0].source_url
    assert bodies[0] == CHENGYUE_HEADER_PUBLICATION_SHA256
    assert bodies[-1] == XIAOSAI_FOOTER_PUBLICATION_SHA256
    assert "查看权威原文" not in client.article.content
    assert "赛先生" not in client.article.content
