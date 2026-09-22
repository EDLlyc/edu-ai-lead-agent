from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest
from app.infrastructure.wechat_official_account.manual_journal import LocalManualDraftJournal


class Repository:
    def __init__(self) -> None:
        self.reconciled = []

    async def reconcile(self, **kwargs):
        self.reconciled.append(kwargs)
        return True


class Readback:
    def __init__(self, verified: bool) -> None:
        self.verified = verified
        self.calls = 0

    async def verify(self, media_id, expected):
        self.calls += 1
        assert media_id == "draft_id"
        assert expected.title == "科学教育"
        return self.verified


@pytest.mark.asyncio
async def test_interrupted_image_phase_seals_fallback_for_credential_isolated_delivery(
    tmp_path,
):
    from test_official_account_single_backfill import (
        CountingGenerator,
        MemoryStore,
        allowed,
        auth,
        operator,
        slots,
    )

    store = MemoryStore()
    authorization = auth()
    visual_slots = slots()
    journal = LocalManualDraftJournal(tmp_path, operator.ACCOUNT)
    try:
        with pytest.raises(asyncio.CancelledError):
            await operator.select_visuals(
                journal=journal,
                auth=authorization,
                slots=visual_slots,
                generator=CountingGenerator(cancel_at=0),
                store=store,
                authorize_side_effect=allowed,
            )
    finally:
        journal.close()

    journal = LocalManualDraftJournal(tmp_path, operator.ACCOUNT)
    try:
        resumed_generator = CountingGenerator()
        selected = await operator.select_visuals(
            journal=journal,
            auth=authorization,
            slots=visual_slots,
            generator=resumed_generator,
            store=store,
            authorize_side_effect=allowed,
        )
        assert resumed_generator.calls == []
        operator.seal_visual_selection(journal, auth=authorization, selection=selected)
    finally:
        journal.close()

    # A separate process/container uses only the shared journal and immutable store.
    journal = LocalManualDraftJournal(tmp_path, operator.ACCOUNT)
    try:
        handed_off = await operator.load_visual_selection(
            journal,
            auth=authorization,
            slots=visual_slots,
            store=store,
        )
        assert handed_off is not None
        assert handed_off.origin == "approved_catalog_fallback"
        assert handed_off.bodies is None
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_acknowledged_add_retries_only_readback_and_database_reconciliation(tmp_path):
    from test_official_account_single_backfill import allowed, auth, operator
    from test_official_account_single_edition import Client, edition, prepared

    value = prepared()
    target = SimpleNamespace(
        edition=replace(
            edition(),
            id=operator.EDITION,
            account=operator.ACCOUNT,
            article_fingerprint=value.article_fingerprint,
            content_fingerprint=value.content_fingerprint,
        )
    )
    authorization = auth()
    repository = Repository()
    first_client = Client()
    first_readback = Readback(False)
    journal = LocalManualDraftJournal(tmp_path, operator.ACCOUNT)
    try:
        first = await operator.deliver_and_reconcile(
            repository=repository,
            target=target,
            prepared=value,
            journal=journal,
            client=first_client,
            readback=first_readback,
            auth=authorization,
            authorize_side_effect=allowed,
        )
    finally:
        journal.close()
    assert first["status"] == "created_unverified"
    assert first_client.calls == ["inline", "thumb", "add"]
    assert repository.reconciled == []

    second_client = Client()
    second_readback = Readback(True)
    journal = LocalManualDraftJournal(tmp_path, operator.ACCOUNT)
    try:
        second = await operator.deliver_and_reconcile(
            repository=repository,
            target=target,
            prepared=value,
            journal=journal,
            client=second_client,
            readback=second_readback,
            auth=authorization,
            authorize_side_effect=allowed,
        )
    finally:
        journal.close()
    assert second["status"] == "delivered"
    assert second_client.calls == []
    assert second_readback.calls == 1
    assert len(repository.reconciled) == 1
