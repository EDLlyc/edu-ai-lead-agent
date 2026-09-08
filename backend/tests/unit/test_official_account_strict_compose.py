"""Real rendered Compose/Settings contracts; synthetic configuration, never daemon/provider I/O."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from argparse import Namespace
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from app import official_account_worker_main as worker
from app.api.v1.routes.official_account_local import _identity as api_identity
from app.core.config import Settings
from app.domain.official_account_local import OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION
from app.domain.official_account_visual_pipeline import (
    OBSERVE_VISUAL_PIPELINE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
    STRICT_VISUAL_PIPELINE_VERSION,
    STRICT_VISUAL_POLICY,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from app.official_account_weekly_dag_main import _handler_registry
from app.official_account_weekly_scheduler_main import _require_scheduler_dependencies
from pydantic import ValidationError

_ROOT = Path(__file__).resolve().parents[3]
_POLICY_ONLY = {
    "acquisition-api",
    "official-account-weekly-scheduler",
    "official-account-weekly-dag-worker",
}
_ARTICLE_WORKER = "official-account-local-worker"
_IDENTITY_OWNERS = _POLICY_ONLY | {_ARTICLE_WORKER}
_COMMON_SECRETS = {
    "DATABASE_URL",
    "GOVERNANCE_CHECKPOINT_DATABASE_URL",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
}
_IMAGE_SECRETS = {
    "AI_PLATFORM_API_KEY",
    "COMFLY_API_KEY",
    "TOAPIS_API_KEY",
    "VISUAL_EMBEDDING_API_KEY",
}
_WECOM_SECRETS = {"WECOM_CORP_SECRET", "WECOM_GROUP_WEBHOOK_KEY"}
# Exact existing credential projection, independently captured before the policy fix.
_ROLE_SECRETS = {
    "backend-migrate": set(),
    "acquisition-api": _IMAGE_SECRETS | _WECOM_SECRETS,
    "acquisition-scheduler": set(),
    "acquisition-worker": set(),
    "governance-scheduler": set(),
    "governance-worker": {"AI_PLATFORM_API_KEY"},
    "content-scheduler": set(),
    "content-worker": _IMAGE_SECRETS,
    "wecom-dispatcher": _WECOM_SECRETS,
    "official-account-weekly-scheduler": set(),
    "official-account-weekly-dag-worker": {"AI_PLATFORM_API_KEY"},
    _ARTICLE_WORKER: _IMAGE_SECRETS,
    "wechat-official-account-draft-worker": {"WECHAT_MP_APP_SECRET"},
    "ip-asset-worker": _IMAGE_SECRETS,
    "official-account-local-fixture": set(),
}


@pytest.fixture(scope="module", params=("disabled", "strict", "observe", "legacy"))
def rendered(request: pytest.FixtureRequest) -> tuple[str, dict[str, dict[str, str]]]:
    return _rendered(request.param)


@pytest.fixture(scope="module")
def strict_rendered() -> dict[str, dict[str, str]]:
    return _rendered("strict")[1]


@lru_cache(maxsize=4)
def _rendered(mode: str) -> tuple[str, dict[str, dict[str, str]]]:
    env = {
        "PATH": "/usr/bin:/bin",
        "COMPOSE_DISABLE_ENV_FILE": "1",
        "APP_ENV": "production",
        "POSTGRES_USER": "synthetic",
        "POSTGRES_PASSWORD": "synthetic-database-only",
        "MINIO_ROOT_USER": "synthetic-storage",
        "MINIO_ROOT_PASSWORD": "synthetic-storage-only",
        "AI_PROVIDER_MODE": "zhipu",
        "AI_PLATFORM_BASE_URL": STRICT_VISUAL_POLICY.audit_base_url,
        "OFFICIAL_ACCOUNT_LOCAL_ENABLED": "true",
        "OFFICIAL_ACCOUNT_LOCAL_WORKER_ENABLED": "true",
        "OFFICIAL_ACCOUNT_LOCAL_GENERATED_VISUALS_ENABLED": (
            "false" if mode == "disabled" else "true"
        ),
        "OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION": (
            STRICT_VISUAL_PIPELINE_VERSION
            if mode == "strict"
            else OBSERVE_VISUAL_PIPELINE_VERSION
            if mode == "observe"
            else ""
        ),
        "OFFICIAL_ACCOUNT_WEEKLY_PRODUCTION_ENABLED": "true",
        "OFFICIAL_ACCOUNT_WEEKLY_SCHEDULER_ENABLED": "true",
        "OFFICIAL_ACCOUNT_WEEKLY_WORKER_ENABLED": "true",
        "OFFICIAL_ACCOUNT_WEEKLY_MIN_WEEK_START": "2026-09-14",
        "IMAGE_ENABLED": "true",
        "IMAGE_PROVIDER_MODE": "comfly",
        "IMAGE_MODEL": "gpt-image-2",
        "IMAGE_MAX_ATTEMPTS": "1" if mode == "legacy" else "3",
        # Match the observed live bound; the unrelated Compose 900 fallback is not this task.
        "IMAGE_PROVIDER_WINDOW_SECONDS": "300",
        "IMAGE_PROVIDER_TIMEOUT_SECONDS": "300",
        "IMAGE_QUALITY_AUDIT_MODEL": "glm-5v-turbo",
        "IMAGE_QUALITY_EVAL_MODE": "observe" if mode == "legacy" else "off",
    }
    env.update({key: "synthetic-test-only" for key in _IMAGE_SECRETS | _WECOM_SECRETS})
    env["WECHAT_MP_APP_SECRET"] = "synthetic-test-only"
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(_ROOT / "compose.yaml"),
            "--profile",
            "*",
            "config",
            "--format",
            "json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    services = json.loads(result.stdout)["services"]
    python_services = {
        name: service["environment"]
        for name, service in services.items()
        if service.get("build", {}).get("dockerfile") == "Dockerfile"
    }
    assert python_services.keys() == _ROLE_SECRETS.keys()
    return mode, python_services


def _settings(environment: dict[str, str]) -> Settings:
    # Exercise env_ignore_empty and exact real service parsing, without host/.env leakage.
    with patch.dict(os.environ, environment, clear=True):
        return Settings(_env_file=None)


def test_default_off_full_profile_starts_without_model_credentials() -> None:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(_ROOT / "compose.yaml"),
            "--profile",
            "*",
            "config",
            "--format",
            "json",
        ],
        env={
            "PATH": "/usr/bin:/bin",
            "COMPOSE_DISABLE_ENV_FILE": "1",
            "IMAGE_PROVIDER_WINDOW_SECONDS": "300",
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    services = json.loads(result.stdout)["services"]
    for name in _ROLE_SECRETS:
        settings = _settings(services[name]["environment"])
        assert settings.ai_platform_api_key is None
        assert settings.comfly_api_key is None
        assert settings.official_account_local_visual_pipeline_version is None
        assert not settings.official_account_local_generated_visuals_enabled
        assert not settings.official_account_local_legacy_generated_visual_policy_enabled


def test_all_python_roles_start_and_keep_exact_secret_and_policy_projection(rendered) -> None:
    mode, roles = rendered
    identities = []
    for name, environment in roles.items():
        settings = _settings(environment)
        secret_fields = {
            key
            for key in environment
            if key.endswith(("_KEY", "_SECRET", "_PASSWORD", "_TOKEN", "DATABASE_URL"))
        }
        assert secret_fields == _COMMON_SECRETS | _ROLE_SECRETS[name]
        assert all(environment[key] for key in secret_fields)
        assert ("IMAGE_QUALITY_AUDIT_MODEL" in environment) == (name == _ARTICLE_WORKER)
        if name == _ARTICLE_WORKER:
            assert environment["IMAGE_QUALITY_AUDIT_MODEL"] == "glm-5v-turbo"
        assert settings.official_account_local_generated_visuals_enabled == (
            name == _ARTICLE_WORKER and mode != "disabled"
        )
        assert settings.official_account_local_legacy_generated_visual_policy_enabled == (
            name in _POLICY_ONLY and mode != "disabled"
        )
        assert settings.official_account_local_visual_pipeline_version == (
            (
                STRICT_VISUAL_PIPELINE_VERSION
                if mode == "strict"
                else OBSERVE_VISUAL_PIPELINE_VERSION
            )
            if name in _IDENTITY_OWNERS and mode in {"strict", "observe"}
            else None
        )
        assert settings.image_quality_eval_mode == (
            "observe" if name == _ARTICLE_WORKER and mode == "legacy" else "off"
        )
        if name in _IDENTITY_OWNERS:
            identity = official_account_identity_from_settings(
                settings, provider="zhipu", model=settings.ai_chat_model
            )
            assert (
                api_identity(settings, provider="zhipu", model=settings.ai_chat_model) == identity
            )
            identities.append(identity)
    assert len(identities) == 4 and all(item == identities[0] for item in identities)
    assert (
        identities[0].generated_visual_plan_version
        == {
            "disabled": None,
            "strict": OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
            "observe": OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
            "legacy": OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
        }[mode]
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AI_PLATFORM_API_KEY", ""),
        ("AI_PLATFORM_API_KEY", " "),
        ("COMFLY_API_KEY", ""),
        ("IMAGE_QUALITY_AUDIT_MODEL", "glm-5.2"),
        ("IMAGE_MODEL", "another"),
        ("AI_PLATFORM_BASE_URL", "https://gateway.example/v1"),
        ("AI_PLATFORM_BASE_URL", STRICT_VISUAL_POLICY.audit_base_url + "/"),
        ("COMFLY_BASE_URL", "http://gateway.example"),
        ("IMAGE_ENABLED", "false"),
    ],
)
def test_strict_executor_rejects_bad_rendered_configuration(strict_rendered, key, value) -> None:
    with pytest.raises(ValidationError):
        _settings(strict_rendered[_ARTICLE_WORKER] | {key: value})


@pytest.mark.asyncio
async def test_policy_only_scheduler_and_dag_construct_without_model_clients(
    rendered, monkeypatch, tmp_path
) -> None:
    _, roles = rendered

    def reject_client(*args, **kwargs):
        raise AssertionError("policy-only startup constructed a model HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", reject_client)
    scheduler_settings = _settings(roles["official-account-weekly-scheduler"])
    assert scheduler_settings.ai_platform_api_key is None
    assert scheduler_settings.comfly_api_key is None
    _require_scheduler_dependencies(scheduler_settings)
    dag_settings = _settings(roles["official-account-weekly-dag-worker"])
    assert dag_settings.comfly_api_key is None
    dag_settings = dag_settings.model_copy(
        update={
            "official_account_weekly_artifact_root": str(tmp_path / "production"),
            "wechat_mp_draft_weekly_inbox_root": str(tmp_path / "inbox"),
        }
    )
    engine = create_engine(dag_settings)
    try:
        registry = _handler_registry(
            args=Namespace(handler_mode="production"),
            settings=dag_settings,
            session_factory=create_session_factory(engine),
        )
        assert registry is not None
    finally:
        await engine.dispose()


@pytest.fixture
def no_network(monkeypatch) -> Iterator[list[httpx.Request]]:
    requests = []
    client_type = httpx.AsyncClient

    def reject(request):
        requests.append(request)
        raise AssertionError("startup must not call a model or external endpoint")

    def client(*args, **kwargs):
        return client_type(*args, **kwargs, transport=httpx.MockTransport(reject))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    yield requests
    assert not requests


@pytest.mark.asyncio
async def test_real_article_worker_composes_and_exits_after_one_idle_claim(
    rendered, monkeypatch, no_network
) -> None:
    mode, roles = rendered
    settings = _settings(roles[_ARTICLE_WORKER])
    claims = []

    class EmptyRepository:
        async def claim(self, **kwargs):
            claims.append(kwargs)
            return None

    async def once(*, executor, stop, worker_id, **kwargs):
        assert executor._generated_visuals_enabled == (mode != "disabled")
        assert (executor._generated_visual_store is not None) == (mode != "disabled")
        assert executor._strict_image_generator is not None
        assert executor._strict_image_quality_auditor is not None
        assert not await executor.execute_next(worker_id)
        stop.set()

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "PostgresOfficialAccountRepository", lambda _: EmptyRepository())
    monkeypatch.setattr(worker, "_worker_loop", once)
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *args: None)
    await worker.run_worker()
    assert len(claims) == 1


@pytest.mark.asyncio
async def test_policy_only_configuration_cannot_start_the_strict_executor(
    strict_rendered, monkeypatch, no_network
) -> None:
    settings = _settings(strict_rendered["official-account-weekly-scheduler"])
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *args: None)

    def reject_engine(*args):
        raise AssertionError("executor guard must precede DB construction/claim")

    monkeypatch.setattr(worker, "create_engine", reject_engine)
    with pytest.raises(RuntimeError, match="requires generated visual execution"):
        await worker.run_worker()


@pytest.mark.asyncio
async def test_frozen_strict_run_does_not_fall_back_after_execution_is_disabled(
    monkeypatch, no_network
) -> None:
    from test_official_account_strict_visual_worker import _Repository

    repository = _Repository()
    frozen_identity = repository.identity
    settings = _settings(_rendered("disabled")[1][_ARTICLE_WORKER])
    assert settings.official_account_local_visual_pipeline_version is None

    async def once(*, executor, stop, worker_id, **kwargs):
        assert await executor.execute_next(worker_id)
        stop.set()

    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "PostgresOfficialAccountRepository", lambda _: repository)
    monkeypatch.setattr(worker, "_worker_loop", once)
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *args: None)
    await worker.run_worker()
    assert repository.identity == frozen_identity
    assert repository.failure == ("strict_visual_configuration_changed", False)
    assert not repository.failure_retryable
    assert repository.article is None and repository.draft is None
    assert not repository.generated and not repository.audits
