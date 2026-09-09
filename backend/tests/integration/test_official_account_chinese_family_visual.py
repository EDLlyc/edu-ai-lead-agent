from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.application.ports.official_account_local import OfficialAccountGeneratedVisualResult
from app.domain.image_provider_input import normalize_image_provider_reference
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION as V4,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION as V5,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleRunModel,
    OfficialAccountGeneratedVisualModel,
)
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from .conftest import integration_context as context_fixture
from .test_official_account_strict_visual import (
    _generated,
    _plan,
    _prime,
    native_path_context,
)
from .test_official_account_strict_visual import (
    test_normal_material_enqueue_executor_durable_ready_and_prepared_consumer as _normal_flow,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="session")]

# Reuse the existing isolated PostgreSQL/MinIO fixture; never an application database.
__all__ = ["native_path_context"]


@pytest_asyncio.fixture(loop_scope="session")
async def migration_context(monkeypatch):
    original_upgrade = command.upgrade

    def upgrade_old(config, revision):
        assert revision == "head"
        original_upgrade(config, "20260907_0043")

    with monkeypatch.context() as patcher:
        patcher.setattr(command, "upgrade", upgrade_old)
        iterator = context_fixture.__wrapped__()
        context = await anext(iterator)
    try:
        yield context
    finally:
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)


async def test_additive_migration_preserves_v4_and_native_guards(migration_context):
    context = migration_context
    repository, claimed, article, rendered = await _prime(context)
    old = await _generated(repository, claimed, article, rendered)
    async with context.session_factory() as session:
        constraint_before = await session.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_official_generated_visuals_native_intent'"
            )
        )
        with pytest.raises(IntegrityError):
            await session.execute(
                update(OfficialAccountGeneratedVisualModel)
                .where(OfficialAccountGeneratedVisualModel.id == old.id)
                .values(prompt_version=V5)
            )
        await session.rollback()

    config = Config("backend/alembic.ini")
    await asyncio.to_thread(command.upgrade, config, "head")
    async with context.session_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260909_0045"
        )
        assert constraint_before == await session.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_official_generated_visuals_native_intent'"
            )
        )
        original = await session.get(OfficialAccountGeneratedVisualModel, old.id)
        assert original.prompt_version == V4 and original.sha256 == old.sha256
        values = {
            column.name: getattr(original, column.name)
            for column in OfficialAccountGeneratedVisualModel.__table__.columns
        }
        new_id = uuid4()
        values.update(
            id=new_id,
            ordinal=1,
            prompt_version=V5,
            request_fingerprint=sha256(new_id.bytes).hexdigest(),
        )
        session.add(OfficialAccountGeneratedVisualModel(**values))
        await session.commit()

    # Check real SQL, not only the Python version predicate. Every failure rolls back locally.
    invalid = (
        {"prompt_version": None},
        {"prompt_version": "unsupported-prompt"},
        {"plan_version": "official-account-generated-visual-plan-v3-visible-ip"},
        {"block_index": None},
        {"block_index": 13},
        {"block_kind": "image"},
        {"reference_input_checksum": None},
        {"output_size": None},
        {"output_size": "1024x1024"},
        {"intent_lease_token": None},
        {"intent_attempt_number": None},
        {"intent_attempt_number": 0},
        {"provider": "other-provider"},
        {"model": "other-model"},
        {"width": 1024},
        {"height": None},
        {"media_type": "image/png"},
    )
    for mutation in invalid:
        async with context.session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(OfficialAccountGeneratedVisualModel)
                    .where(OfficialAccountGeneratedVisualModel.id == new_id)
                    .values(**mutation)
                )
            await session.rollback()

    with pytest.raises(RuntimeError, match="cannot downgrade Chinese-family visual prompt"):
        await asyncio.to_thread(command.downgrade, config, "20260907_0043")
    async with context.session_factory() as session:
        assert await session.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260909_0045"
        )
        assert (await session.get(OfficialAccountGeneratedVisualModel, old.id)).prompt_version == V4
        assert (await session.get(OfficialAccountGeneratedVisualModel, new_id)).prompt_version == V5


@pytest.mark.parametrize("frozen_prompt", [V4, V5])
async def test_repository_binds_native_plan_to_frozen_run(native_path_context, frozen_prompt):
    context = native_path_context
    repository, claimed, article, rendered = await _prime(context)
    identity = replace(claimed.identity, generated_visual_prompt_version=frozen_prompt)
    claimed = replace(claimed, identity=identity)
    async with context.session_factory() as session:
        await session.execute(
            update(OfficialAccountArticleRunModel)
            .where(OfficialAccountArticleRunModel.id == claimed.run_id)
            .values(version_bundle=asdict(identity))
        )
        await session.commit()
    valid = replace(_plan(claimed, article, rendered), prompt_version=frozen_prompt)
    mixed = replace(valid, prompt_version=V5 if frozen_prompt == V4 else V4)
    with pytest.raises(ValueError):
        await repository.claim_strict_generated_visual(claimed=claimed, plan=mixed)
    assert await repository.get_generated_visual(run_id=claimed.run_id, ordinal=0) is None
    claim = await repository.claim_strict_generated_visual(claimed=claimed, plan=valid)
    assert claim.outcome == "newly_claimed"
    stored = await repository.persist_generated_visual(
        claimed=claimed,
        plan=valid,
        result=OfficialAccountGeneratedVisualResult("image/jpeg", 100, "b" * 64, 1536, 1024),
    )
    assert stored is not None and stored.plan.prompt_version == frozen_prompt
    replay = await repository.claim_strict_generated_visual(claimed=claimed, plan=valid)
    assert replay.outcome == "completed"


@pytest.mark.parametrize("visual_case", ["strict", "observe_mixed"])
async def test_real_native_worker_and_prepared_keep_frozen_prompt(
    native_path_context, tmp_path, monkeypatch, visual_case
):
    from app.infrastructure import official_account_runtime as runtime

    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "unit"))
    from test_official_account_strict_visual_worker import _Generator

    captured = []
    original_generate = _Generator.generate

    async def capture_generated_request(self, request):
        captured.append(request)
        assert not request.unrestricted_prompt_length and len(request.prompt) <= 2000
        assert len(request.references) == 1 and request.output_size == "1536x1024"
        reference = request.references[0]
        assert sha256(reference.image_bytes).hexdigest() == reference.sha256
        normalized = normalize_image_provider_reference(
            reference.image_bytes, version=reference.input_normalization_version
        )
        assert normalized.sha256 == reference.provider_input_sha256
        return await original_generate(self, request)

    monkeypatch.setattr(_Generator, "generate", capture_generated_request)
    expected = V5
    if visual_case == "strict":
        original_factory = runtime.official_account_identity_from_settings

        def frozen_v4(*args, **kwargs):
            return replace(original_factory(*args, **kwargs), generated_visual_prompt_version=V4)

        monkeypatch.setattr(runtime, "official_account_identity_from_settings", frozen_v4)
        expected = V4
    await _normal_flow(native_path_context, tmp_path, monkeypatch, visual_case)
    assert len(captured) == 5
    assert all(
        ("Contemporary Chinese family" in item.prompt) == (expected == V5) for item in captured
    )
    async with native_path_context.session_factory() as session:
        visuals = (await session.scalars(select(OfficialAccountGeneratedVisualModel))).all()
        assert len(visuals) == 5 and {row.prompt_version for row in visuals} == {expected}
        run_id = visuals[0].run_id
        run = await session.get(OfficialAccountArticleRunModel, run_id)
        assert run.status == "ready"
        assert run.version_bundle["generated_visual_prompt_version"] == expected
        tampered_id = visuals[-1].id
        await session.execute(
            update(OfficialAccountGeneratedVisualModel)
            .where(OfficialAccountGeneratedVisualModel.id == tampered_id)
            .values(prompt_version=V4 if expected == V5 else V5)
        )
        await session.commit()
    repository = PostgresOfficialAccountRepository(native_path_context.session_factory)
    with pytest.raises(ValueError):
        await repository.load_strict_visual_evidence(run_id)
    async with native_path_context.session_factory() as session:
        await session.execute(
            update(OfficialAccountGeneratedVisualModel)
            .where(OfficialAccountGeneratedVisualModel.id == tampered_id)
            .values(prompt_version=expected)
        )
        await session.commit()
    evidence = await repository.load_strict_visual_evidence(run_id)
    assert len(evidence) == 6 and {item.prompt_version for item in evidence} == {expected}
