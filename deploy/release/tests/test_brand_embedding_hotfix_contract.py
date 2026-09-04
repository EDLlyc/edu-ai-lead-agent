from __future__ import annotations

import runpy
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
validate_services: Callable[[dict[str, object]], str] = runpy.run_path(
    str(_PROJECT_ROOT / "scripts/validate_brand_delivery_config.py")
)["validate_services"]


def _services() -> dict[str, object]:
    shared = {
        "BRAND_EMBEDDING_PROVIDER_MODE": "auto",
        "AI_PROVIDER_MODE": "disabled",
        "AI_PLATFORM_BASE_URL": "",
        "AI_EMBEDDING_MODEL": "embedding-3",
        "AI_EMBEDDING_DIMENSIONS": "2048",
        "VISUAL_EMBEDDING_PROVIDER_MODE": "disabled",
        "VISUAL_EMBEDDING_MODEL": "qwen3-vl-embedding",
        "VISUAL_EMBEDDING_DIMENSIONS": "2048",
        "VISUAL_EMBEDDING_ENDPOINT": "",
        "VISUAL_EMBEDDING_API_KEY": "",
        "CONTENT_ENABLED": "false",
    }
    return {
        "acquisition-api": {
            "environment": {
                **shared,
                "AI_PLATFORM_API_KEY": "",
                "WECOM_AUTO_DELIVERY_ENABLED": "false",
            }
        },
        "content-worker": {
            "environment": {
                **shared,
                "AI_PLATFORM_API_KEY": "",
                "CONTENT_WORKER_ENABLED": "false",
                "CONTENT_COPY_PROVIDER_REQUIRED": "false",
            }
        },
        "wecom-dispatcher": {
            "environment": {
                "WECOM_ENABLED": "false",
                "WECOM_AUTO_DELIVERY_ENABLED": "false",
            }
        },
    }


def _environment(services: dict[str, object], name: str) -> dict[str, str]:
    return services[name]["environment"]  # type: ignore[index,return-value]


def test_provider_free_compose_defaults_remain_valid() -> None:
    assert validate_services(_services()) == "disabled"


def test_zhipu_auto_resolution_requires_shared_compatible_identity() -> None:
    services = _services()
    for name in ("acquisition-api", "content-worker"):
        environment = _environment(services, name)
        environment["AI_PROVIDER_MODE"] = "zhipu"
        environment["AI_PLATFORM_BASE_URL"] = "https://open.bigmodel.cn/api/paas/v4"
        environment["AI_PLATFORM_API_KEY"] = "test-only-key"

    assert validate_services(services) == "zhipu"

    missing_key = deepcopy(services)
    _environment(missing_key, "content-worker")["AI_PLATFORM_API_KEY"] = ""
    with pytest.raises(ValueError, match="requires a shared API key"):
        validate_services(missing_key)

    drifted_base_url = deepcopy(services)
    _environment(drifted_base_url, "content-worker")["AI_PLATFORM_BASE_URL"] = (
        "https://open.bigmodel.cn/api/paas/v4/alternate"
    )
    with pytest.raises(ValueError, match="base URL must be identical across services"):
        validate_services(drifted_base_url)

    drifted_key = deepcopy(services)
    _environment(drifted_key, "content-worker")["AI_PLATFORM_API_KEY"] = (
        "other-test-key"
    )
    with pytest.raises(ValueError, match="API key must be identical across services"):
        validate_services(drifted_key)

    wrong_model = deepcopy(services)
    for name in ("acquisition-api", "content-worker"):
        _environment(wrong_model, name)["AI_EMBEDDING_MODEL"] = "other-model"
    with pytest.raises(ValueError, match="must pin embedding-3"):
        validate_services(wrong_model)


def test_automatic_delivery_requires_the_complete_copy_upstream() -> None:
    services = _services()
    _environment(services, "acquisition-api")["WECOM_AUTO_DELIVERY_ENABLED"] = "true"
    dispatcher = _environment(services, "wecom-dispatcher")
    dispatcher["WECOM_AUTO_DELIVERY_ENABLED"] = "true"
    dispatcher["WECOM_ENABLED"] = "true"
    worker = _environment(services, "content-worker")
    worker["CONTENT_ENABLED"] = "true"
    worker["CONTENT_WORKER_ENABLED"] = "true"
    worker["CONTENT_COPY_PROVIDER_REQUIRED"] = "true"

    with pytest.raises(ValueError, match="copy-capable AI provider"):
        validate_services(services)

    for name in ("acquisition-api", "content-worker"):
        environment = _environment(services, name)
        environment["AI_PROVIDER_MODE"] = "zhipu"
        environment["AI_PLATFORM_BASE_URL"] = "https://open.bigmodel.cn/api/paas/v4"
        environment["AI_PLATFORM_API_KEY"] = "test-only-key"

    assert validate_services(services) == "zhipu"


def test_copy_provider_projection_must_match_automatic_delivery() -> None:
    services = _services()
    _environment(services, "content-worker")["CONTENT_COPY_PROVIDER_REQUIRED"] = "true"

    with pytest.raises(ValueError, match="must match automatic WeCom delivery"):
        validate_services(services)


def test_doctor_executes_the_tested_cross_process_validator() -> None:
    doctor = (_PROJECT_ROOT / "scripts/doctor.sh").read_text(encoding="utf-8")
    compose = (_PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "scripts/validate_brand_delivery_config.py" in doctor
    assert (
        "BRAND_EMBEDDING_PROVIDER_MODE: ${BRAND_EMBEDDING_PROVIDER_MODE:-auto}"
        in compose
    )
    assert (
        "CONTENT_COPY_PROVIDER_REQUIRED: ${WECOM_AUTO_DELIVERY_ENABLED:-false}"
        in compose
    )
