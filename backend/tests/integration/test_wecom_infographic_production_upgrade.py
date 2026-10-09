"""Exercise the additive infographic revision from the deployed migration head."""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_existing_production_head_upgrades_without_losing_draft_ownership(
    integration_context: IntegrationContext,
) -> None:
    config = Config("backend/alembic.ini")
    await asyncio.to_thread(command.downgrade, config, "20260916_0048")

    async with integration_context.engine.begin() as connection:
        assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260916_0048"
        )
        tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        assert "official_account_draft_owners" in tables
        assert "news_infographic_jobs" not in tables
        await connection.execute(
            text(
                "INSERT INTO official_account_draft_owners "
                "(account_fingerprint, key_kind, key_value, owner, status, "
                "provenance_fingerprint, created_at, updated_at) "
                "VALUES (:account, 'event', :value, 'production-owned', 'reserved', "
                ":provenance, now(), now())"
            ),
            {"account": "a" * 64, "value": "production-upgrade-probe", "provenance": "b" * 64},
        )

    await asyncio.to_thread(command.upgrade, config, "head")

    async with integration_context.engine.connect() as connection:
        assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20261009_0057"
        )
        tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        assert {
            "official_account_strict_visual_audits",
            "official_account_single_editions",
            "official_account_draft_owners",
            "news_infographic_jobs",
            "wecom_infographic_supplements",
            "wecom_infographic_attempts",
            "wecom_infographic_test_runs",
            "wecom_infographic_test_attempts",
        } <= tables
        columns = await connection.run_sync(
            lambda sync: {
                column["name"]: column
                for column in inspect(sync).get_columns("news_infographic_jobs")
            }
        )
        assert {
            "raw_sha256",
            "raw_byte_size",
            "composite_sha256",
            "composite_byte_size",
            "footer_sha256",
            "footer_byte_size",
            "delivery_sha256",
            "delivery_byte_size",
            "quality_mode",
            "warning_codes",
            "warning_notice_version",
            "copy_candidate_snapshot",
            "copy_audit_snapshot",
        } <= columns.keys()
        assert columns["composite_sha256"]["nullable"] is True
        assert columns["composite_byte_size"]["nullable"] is True
        assert columns["quality_mode"]["nullable"] is False
        assert columns["warning_codes"]["nullable"] is False
        assert columns["warning_notice_version"]["nullable"] is True
        constraints = await connection.run_sync(
            lambda sync: {
                item["name"]
                for item in inspect(sync).get_check_constraints("news_infographic_jobs")
            }
        )
        assert {
            "ck_news_infographic_jobs_quality_mode",
            "ck_news_infographic_jobs_warning_codes",
            "ck_news_infographic_jobs_advisory_shape",
        } <= constraints
        assert (
            await connection.scalar(
                text(
                    "SELECT owner FROM official_account_draft_owners "
                    "WHERE account_fingerprint = :account AND key_kind = 'event'"
                ),
                {"account": "a" * 64},
            )
            == "production-owned"
        )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_empty_advisory_revision_can_downgrade_and_upgrade(
    integration_context: IntegrationContext,
) -> None:
    config = Config("backend/alembic.ini")
    await asyncio.to_thread(command.downgrade, config, "20260923_0049")
    async with integration_context.engine.connect() as connection:
        assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260923_0049"
        )
        columns = await connection.run_sync(
            lambda sync: {
                column["name"] for column in inspect(sync).get_columns("news_infographic_jobs")
            }
        )
        assert "warning_codes" not in columns
    await asyncio.to_thread(command.upgrade, config, "head")
    async with integration_context.engine.connect() as connection:
        assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20261009_0057"
        )
