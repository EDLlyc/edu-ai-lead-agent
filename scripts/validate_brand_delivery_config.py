#!/usr/bin/env python3
"""Validate cross-process brand embedding and automatic delivery configuration."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import NoReturn


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


def _compose_bool(value: object, *, label: str) -> bool:
    normalized = str(value).strip().casefold()
    if normalized in {"1", "on", "t", "true", "y", "yes"}:
        return True
    if normalized in {"0", "off", "f", "false", "n", "no"}:
        return False
    _fail(f"{label} must be a valid boolean")


def _resolved_brand_provider(environment: Mapping[str, object]) -> str:
    configured = str(environment.get("BRAND_EMBEDDING_PROVIDER_MODE", ""))
    if configured not in {"auto", "disabled", "fake", "zhipu", "alibaba"}:
        _fail("brand embedding provider mode is unsupported")
    if configured != "auto":
        return configured
    if environment.get("AI_PROVIDER_MODE") == "fake":
        return "fake"
    if environment.get("VISUAL_EMBEDDING_PROVIDER_MODE") == "alibaba":
        return "alibaba"
    if environment.get("AI_PROVIDER_MODE") == "zhipu":
        return "zhipu"
    return "disabled"


def validate_services(services: Mapping[str, object]) -> str:
    try:
        api_environment = services["acquisition-api"]["environment"]  # type: ignore[index]
        worker_environment = services["content-worker"]["environment"]  # type: ignore[index]
        delivery_environment = services["wecom-dispatcher"]["environment"]  # type: ignore[index]
    except (KeyError, TypeError):
        _fail(
            "brand delivery validation requires API, content worker, and WeCom services"
        )
    if not all(
        isinstance(environment, Mapping)
        for environment in (api_environment, worker_environment, delivery_environment)
    ):
        _fail("brand delivery service environments must be mappings")

    shared_keys = (
        "BRAND_EMBEDDING_PROVIDER_MODE",
        "AI_PROVIDER_MODE",
        "AI_EMBEDDING_MODEL",
        "AI_EMBEDDING_DIMENSIONS",
        "VISUAL_EMBEDDING_PROVIDER_MODE",
        "VISUAL_EMBEDDING_MODEL",
        "VISUAL_EMBEDDING_DIMENSIONS",
    )
    for key in shared_keys:
        values = [api_environment.get(key), worker_environment.get(key)]
        if any(value in (None, "") for value in values) or len(set(values)) != 1:
            _fail(f"brand embedding setting {key} must be present and identical")

    resolved_provider = _resolved_brand_provider(worker_environment)
    if resolved_provider == "fake" and worker_environment["AI_PROVIDER_MODE"] != "fake":
        _fail("fake brand embedding requires fake AI provider mode")
    if resolved_provider == "zhipu":
        if worker_environment["AI_PROVIDER_MODE"] != "zhipu":
            _fail("Zhipu brand embedding requires Zhipu AI provider mode")
        if worker_environment["AI_EMBEDDING_MODEL"] != "embedding-3":
            _fail("Zhipu brand embedding must pin embedding-3")
        if worker_environment["AI_EMBEDDING_DIMENSIONS"] != "2048":
            _fail("Zhipu brand embedding must pin 2048 dimensions")
        for key, label in (
            ("AI_PLATFORM_BASE_URL", "base URL"),
            ("AI_PLATFORM_API_KEY", "API key"),
        ):
            values = [api_environment.get(key), worker_environment.get(key)]
            if any(not str(value or "").strip() for value in values):
                _fail(f"Zhipu brand embedding requires a shared {label}")
            if len(set(values)) != 1:
                _fail(
                    f"Zhipu brand embedding {label} must be identical across services"
                )
    elif resolved_provider == "alibaba":
        if worker_environment["VISUAL_EMBEDDING_MODEL"] != "qwen3-vl-embedding":
            _fail("Alibaba brand embedding model identity drifted")
        if worker_environment["VISUAL_EMBEDDING_DIMENSIONS"] != "2048":
            _fail("Alibaba brand embedding dimensions drifted")
        for key in ("VISUAL_EMBEDDING_ENDPOINT", "VISUAL_EMBEDDING_API_KEY"):
            values = [api_environment.get(key), worker_environment.get(key)]
            if any(value in (None, "") for value in values) or len(set(values)) != 1:
                _fail(f"Alibaba brand embedding requires shared {key}")

    auto_delivery_values = [
        api_environment.get("WECOM_AUTO_DELIVERY_ENABLED"),
        delivery_environment.get("WECOM_AUTO_DELIVERY_ENABLED"),
    ]
    if (
        any(value in (None, "") for value in auto_delivery_values)
        or len(set(auto_delivery_values)) != 1
    ):
        _fail("automatic WeCom delivery flag must be shared by API and dispatcher")
    auto_delivery_enabled = _compose_bool(
        auto_delivery_values[0], label="automatic WeCom delivery flag"
    )
    copy_provider_required = _compose_bool(
        worker_environment.get("CONTENT_COPY_PROVIDER_REQUIRED", ""),
        label="content copy-provider requirement",
    )
    if copy_provider_required != auto_delivery_enabled:
        _fail("content copy-provider requirement must match automatic WeCom delivery")
    if auto_delivery_enabled:
        if not _compose_bool(
            delivery_environment.get("WECOM_ENABLED", ""), label="WeCom enabled flag"
        ):
            _fail("automatic WeCom delivery requires WeCom to be enabled")
        if not _compose_bool(
            worker_environment.get("CONTENT_ENABLED", ""), label="content enabled flag"
        ):
            _fail("automatic WeCom delivery requires content to be enabled")
        if not _compose_bool(
            worker_environment.get("CONTENT_WORKER_ENABLED", ""),
            label="content worker enabled flag",
        ):
            _fail("automatic WeCom delivery requires the content worker")
        if worker_environment["AI_PROVIDER_MODE"] not in {"fake", "zhipu"}:
            _fail("automatic WeCom delivery requires a copy-capable AI provider")
        if resolved_provider not in {"fake", "zhipu", "alibaba"}:
            _fail("automatic WeCom delivery requires a brand embedding provider")
    return resolved_provider


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        services = payload["services"]
        if not isinstance(services, Mapping):
            _fail("Compose services must be a mapping")
        validate_services(services)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
