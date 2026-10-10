"""Provider-free reproduction: pre-template journal ACK after console selection."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

from app.application.services.wechat_official_account_draft import (
    WeChatOfficialAccountDraftOnlyService,
)
from app.application.services.wechat_single_edition_delivery import (
    JournaledSingleDraftClient,
    deliver_single,
)
from test_official_account_single_edition import NOW, Client, Repository, edition, prepared


class MemoryJournal:
    def __init__(self):
        self.rows = {}

    def read(self, name):
        return self.rows.get(name)

    def write(self, name, payload):
        assert name not in self.rows
        self.rows[name] = payload


async def main():
    value = edition()
    body = replace(
        prepared(),
        body_html='<section style="color:#0D57C8"><img src="assets/body.jpg"/></section>',
    )
    journal = MemoryJournal()
    original = Client()

    async def authorize():
        return True

    # Recreate the old runtime's journal, which never wrote a layout pin.
    observed = JournaledSingleDraftClient(
        client=original,
        journal=journal,
        edition=value,
        prepared=body,
        authorize=authorize,
        clock=lambda: NOW,
    )
    await WeChatOfficialAccountDraftOnlyService(
        client=observed, clock=lambda: NOW
    ).create_prepared(body)
    assert not any(name.endswith("-layout.json") for name in journal.rows)
    # SQL save may have failed. Retry after midnight must reconcile the old ACK.
    retry = Client()
    repository = Repository()
    await deliver_single(
        repository=repository,
        edition=value,
        prepared=body,
        journal=journal,
        client=retry,
        clock=lambda: NOW + timedelta(days=1),
        layout_template_id="jade-green",
    )
    print(json.dumps({
        "original_fake_writes": original.calls,
        "retry_fake_writes": retry.calls,
        "expected_status": "delivered",
        "actual_status": repository.value.status,
        "error_code": repository.value.error_code,
        "provider_calls": 0,
    }, sort_keys=True))


asyncio.run(main())
