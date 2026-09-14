from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.infrastructure.db.official_account_single_edition import PostgresSingleEditionRepository
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_imported_history_alone_refuses_real_downgrade_without_erasing_ownership(
    integration_context: IntegrationContext,
) -> None:
    context = integration_context
    repository = PostgresSingleEditionRepository(context.session_factory)
    account = sha256(uuid4().bytes).hexdigest()
    await repository.import_history(account, (), now=datetime.now(UTC))
    async with context.session_factory() as session:
        assert (
            await session.scalar(
                text(
                    "SELECT count(*) FROM official_account_single_editions "
                    "WHERE account_fingerprint = :account"
                ),
                {"account": account},
            )
            == 0
        )
        before = await session.scalar(text("SELECT count(*) FROM official_account_draft_owners"))
        assert before > 0
    with pytest.raises(DBAPIError, match="cannot downgrade populated single edition ownership"):
        await asyncio.to_thread(command.downgrade, Config("backend/alembic.ini"), "20260914_0046")
    async with context.session_factory() as session:
        assert (
            await session.scalar(text("SELECT version_num FROM alembic_version")) == "20260914_0047"
        )
        assert (
            await session.scalar(text("SELECT count(*) FROM official_account_draft_owners"))
            == before
        )
