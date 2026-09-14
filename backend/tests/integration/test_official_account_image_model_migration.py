from __future__ import annotations

import asyncio
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.application.ports.official_account_local import OfficialAccountGeneratedVisualResult
from app.domain.official_account_visual_pipeline import (
    LEGACY_STRICT_VISUAL_GENERATION_MODEL,
    STRICT_VISUAL_POLICY,
)
from app.infrastructure.db.models import OfficialAccountGeneratedVisualModel
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from .conftest import integration_context as context_fixture
from .test_official_account_strict_visual import _generated, _plan, _prime

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def migration_context(monkeypatch):
    original_upgrade = command.upgrade

    def upgrade_previous(config, revision):
        assert revision == "head"
        original_upgrade(config, "20260909_0045")

    with monkeypatch.context() as patcher:
        patcher.setattr(command, "upgrade", upgrade_previous)
        iterator = context_fixture.__wrapped__()
        context = await anext(iterator)
    try:
        yield context
    finally:
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)


async def test_model_constraint_upgrade_preserves_legacy_and_downgrade_is_data_safe(
    migration_context,
):
    context = migration_context
    repository, claimed, article, rendered = await _prime(context)
    legacy = await _generated(repository, claimed, article, rendered)
    assert legacy.plan.model == LEGACY_STRICT_VISUAL_GENERATION_MODEL

    config = Config("backend/alembic.ini")
    await asyncio.to_thread(command.upgrade, config, "head")
    async with context.session_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260914_0046"
        )
        definition = await session.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'official_account_generated_visuals'::regclass "
                "AND pg_get_constraintdef(oid) LIKE '%gpt-image-2.5-sunburst%'"
            )
        )
        assert definition is not None
        assert LEGACY_STRICT_VISUAL_GENERATION_MODEL in definition
        assert STRICT_VISUAL_POLICY.generation_model in definition
        preserved = await session.get(OfficialAccountGeneratedVisualModel, legacy.id)
        assert preserved is not None
        assert preserved.model == LEGACY_STRICT_VISUAL_GENERATION_MODEL
        assert preserved.sha256 == legacy.sha256

    plan = replace(
        _plan(claimed, article, rendered, ordinal=1),
        model=STRICT_VISUAL_POLICY.generation_model,
        request_fingerprint=sha256(uuid4().bytes).hexdigest(),
    )
    claim = await repository.claim_strict_generated_visual(claimed=claimed, plan=plan)
    assert claim.outcome == "newly_claimed"
    current = await repository.persist_generated_visual(
        claimed=claimed,
        plan=plan,
        result=OfficialAccountGeneratedVisualResult("image/jpeg", 100, "c" * 64, 1536, 1024),
    )
    assert current is not None and current.plan.model == STRICT_VISUAL_POLICY.generation_model

    async with context.session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                update(OfficialAccountGeneratedVisualModel)
                .where(OfficialAccountGeneratedVisualModel.id == current.id)
                .values(model="unsupported-model")
            )
        await session.rollback()

    with pytest.raises(
        DBAPIError, match="cannot downgrade populated current strict visual image model"
    ):
        await asyncio.to_thread(command.downgrade, config, "20260909_0045")
    async with context.session_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260914_0046"
        )
        await session.execute(
            delete(OfficialAccountGeneratedVisualModel).where(
                OfficialAccountGeneratedVisualModel.id == current.id
            )
        )
        await session.commit()

    await asyncio.to_thread(command.downgrade, config, "20260909_0045")
    async with context.session_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260909_0045"
        )
        preserved = await session.get(OfficialAccountGeneratedVisualModel, legacy.id)
        assert preserved is not None and preserved.model == LEGACY_STRICT_VISUAL_GENERATION_MODEL
    await asyncio.to_thread(command.upgrade, config, "head")
