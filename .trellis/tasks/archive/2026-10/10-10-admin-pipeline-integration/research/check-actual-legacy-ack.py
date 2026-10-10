"""Independent provider-free ACK replay using the actual extracted 83a source."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import tempfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from app.application.services.wechat_single_edition_delivery import deliver_single
from app.infrastructure.wechat_official_account.manual_journal import (
    LocalManualDraftJournal,
)
from test_official_account_single_edition import (
    NOW,
    Client,
    Repository,
    edition,
    prepared,
)

LEGACY = Path(
    "/tmp/edu-admin-pipeline-integration/legacy-source/app/application/services"
)


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, LEGACY / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


async def main() -> None:
    old_delivery = load(
        "review_actual_legacy_delivery", "wechat_single_edition_delivery.py"
    )
    old_service = load(
        "review_actual_legacy_service", "wechat_official_account_draft.py"
    )
    results = []
    for with_media in (True, False):
        value = edition()
        body = replace(
            prepared(),
            body_html='<section style="color:#0D57C8"><img src="assets/body.jpg"/></section>'
            if with_media
            else '<section style="color:#0D57C8">正文</section>',
            body_media=prepared().body_media if with_media else (),
        )

        async def authorize() -> bool:
            return True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = LocalManualDraftJournal(root, value.account)
            try:
                original = Client()
                observed = old_delivery.JournaledSingleDraftClient(
                    client=original,
                    journal=journal,
                    edition=value,
                    prepared=body,
                    authorize=authorize,
                    clock=lambda: NOW,
                )
                await old_service.WeChatOfficialAccountDraftOnlyService(
                    client=observed, clock=lambda: NOW
                ).create_prepared(body)
                assert journal.read(f"single-{value.id.hex}-layout.json") is None
                before = {path: path.read_bytes() for path in root.rglob("*.json")}
                retry, repository = Client(), Repository()
                await deliver_single(
                    repository=repository,
                    edition=value,
                    prepared=body,
                    journal=journal,
                    client=retry,
                    clock=lambda: NOW + timedelta(days=1),
                    layout_template_id="jade-green",
                )
                assert repository.value.status == "delivered"
                assert retry.calls == []
                assert all(path.read_bytes() == data for path, data in before.items())
                assert (
                    journal.read(f"single-{value.id.hex}-layout.json")["template"]
                    == "xiaosai-blue"
                )
                results.append(
                    {
                        "with_media": with_media,
                        "status": "delivered",
                        "retry_writes": 0,
                        "old_files_unchanged": True,
                    }
                )
            finally:
                journal.close()
    print(
        json.dumps(
            {"actual_legacy_source": "83a41e41", "cases": results, "provider_calls": 0},
            sort_keys=True,
        )
    )


asyncio.run(main())
