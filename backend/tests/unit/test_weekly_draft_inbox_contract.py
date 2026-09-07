from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

import pytest


def _volume_location(service: dict[str, Any]) -> tuple[str, PurePosixPath, bool]:
    inbox = PurePosixPath(service["environment"]["WECHAT_MP_DRAFT_WEEKLY_INBOX_ROOT"])
    matches = [
        volume
        for volume in service["volumes"]
        if volume["type"] == "volume" and inbox.is_relative_to(volume["target"])
    ]
    assert len(matches) == 1, "weekly inbox must resolve inside exactly one named volume"
    volume = matches[0]
    return (
        volume["source"],
        inbox.relative_to(volume["target"]),
        volume.get("read_only", False),
    )


def test_weekly_producer_and_draft_consumer_share_same_volume_relative_inbox() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "--project-directory",
            str(root),
            "-f",
            str(root / "compose.yaml"),
            "--profile",
            "official-account-weekly-dag",
            "--profile",
            "wechat-official-account-draft",
            "config",
            "--format",
            "json",
        ],
        env={"PATH": os.environ["PATH"], "COMPOSE_DISABLE_ENV_FILE": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=30,
    )
    services = json.loads(result.stdout)["services"]
    producer = services["official-account-weekly-dag-worker"]
    consumer = services["wechat-official-account-draft-worker"]
    source, relative, read_only = _volume_location(producer)
    target, consumer_relative, consumer_read_only = _volume_location(consumer)

    assert source == target == "official_account_weekly_dag_output"
    assert relative == consumer_relative == PurePosixPath("weekly-inbox")
    assert read_only is False
    assert consumer_read_only is True
    assert consumer["environment"]["WECHAT_MP_DRAFT_WORKER_ENABLED"] == "false"
    assert consumer["environment"]["WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED"] == "false"
    assert consumer["environment"]["WECHAT_MP_MODE"] == "draft_only"
    assert consumer["command"] == [
        "python",
        "-m",
        "app.wechat_official_account_draft_main",
        "worker",
    ]

    # The old path is outside the consumer mount, even though it resembles the producer path.
    old_consumer = {
        **consumer,
        "environment": {
            **consumer["environment"],
            "WECHAT_MP_DRAFT_WEEKLY_INBOX_ROOT": "/app/input/weekly-inbox",
        },
    }
    with pytest.raises(AssertionError, match="exactly one named volume"):
        _volume_location(old_consumer)
