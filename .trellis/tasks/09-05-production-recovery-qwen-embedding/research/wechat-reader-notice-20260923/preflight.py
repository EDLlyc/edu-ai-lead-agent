"""Read-only safety snapshot before a narrow WeChat draft-worker update."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

from app.core.config import get_settings
from app.infrastructure.db.models import (
    OfficialAccountSingleEditionModel,
    WeChatOfficialAccountDraftItemModel,
    WeChatOfficialAccountDraftJobModel,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from sqlalchemy import select


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        sessions = create_session_factory(engine)
        async with sessions() as session:
            edition_rows = await session.execute(
                select(
                    OfficialAccountSingleEditionModel.status,
                    OfficialAccountSingleEditionModel.lease_token,
                )
            )
            job_rows = await session.execute(
                select(WeChatOfficialAccountDraftJobModel.status)
            )
            item_rows = await session.execute(
                select(
                    WeChatOfficialAccountDraftItemModel.status,
                    WeChatOfficialAccountDraftItemModel.side_effect_started_at,
                )
            )
        editions = list(edition_rows)
        jobs = [row[0] for row in job_rows]
        items = list(item_rows)
    finally:
        await engine.dispose()

    journal_root = Path(settings.wechat_mp_draft_artifact_root) / "manual-v1"
    pending_add_intents = 0
    if journal_root.is_dir():
        for intent in journal_root.glob("*/single-*-add-*-intent.json"):
            if intent.is_symlink() or not intent.is_file():
                raise ValueError("preflight_journal_invalid")
            if not intent.with_name(
                intent.name.removesuffix("-intent.json") + "-ack.json"
            ).is_file():
                pending_add_intents += 1
    print(
        json.dumps(
            {
                "edition_statuses": dict(Counter(row[0] for row in editions)),
                "edition_active_leases": sum(row[1] is not None for row in editions),
                "draft_job_statuses": dict(Counter(jobs)),
                "draft_item_statuses": dict(Counter(row[0] for row in items)),
                "draft_item_open_effects": sum(
                    row[1] is not None
                    and row[0] not in {"succeeded", "terminal_failed"}
                    for row in items
                ),
                "single_add_intents_without_ack": pending_add_intents,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
