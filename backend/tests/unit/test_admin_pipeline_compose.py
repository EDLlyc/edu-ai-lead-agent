"""The pipeline override cannot recreate unrelated services or broaden secret grants."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TARGETS = {
    "official-account-local-worker",
    "official-account-weekly-dag-worker",
    "governance-worker",
    "wechat-official-account-draft-worker",
}
CONSUMERS = (TARGETS - {"wechat-official-account-draft-worker"}) | {
    "acquisition-api",
    "content-worker",
    "wecom-infographic-producer",
}


def _render(**environment):
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(ROOT / "compose.yaml"),
            "--profile",
            "*",
            "config",
            "--format",
            "json",
        ],
        env={"PATH": os.environ["PATH"], "COMPOSE_DISABLE_ENV_FILE": "1", **environment},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)["services"]


@pytest.mark.parametrize("app_image", [None, "example.invalid/app@sha256:" + "a" * 64])
def test_pipeline_image_only_overrides_four_services_and_preserves_other_config(app_image):
    environment = {"MODEL_SECRET_KEY": "synthetic-model-key", "ADMIN_SECRET_KEY": "must-not-spread"}
    if app_image is not None:
        environment["APP_IMAGE"] = app_image
    ordinary = _render(**environment)
    candidate_pin = "example.invalid/pipeline@sha256:" + "b" * 64
    candidate = _render(**environment, ADMIN_PIPELINE_IMAGE=candidate_pin)
    for name, original in ordinary.items():
        expected = dict(original)
        if name in TARGETS:
            assert original["image"] == (app_image or "edu-ai-lead-agent-backend:local")
            expected["image"] = candidate_pin
        assert candidate[name] == expected
    mapped = {
        name
        for name, service in candidate.items()
        if "MODEL_SECRET_KEY" in service.get("environment", {})
    }
    assert mapped == CONSUMERS
    for name in mapped:
        assert candidate[name]["environment"]["MODEL_SECRET_KEY"] == "synthetic-model-key"
    assert all("ADMIN_SECRET_KEY" not in candidate[name]["environment"] for name in TARGETS)
