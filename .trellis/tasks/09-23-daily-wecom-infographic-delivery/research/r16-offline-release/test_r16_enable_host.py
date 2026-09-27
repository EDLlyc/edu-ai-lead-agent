from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import r16_enable_host as host_module
import r16_enablement as enable
import r16_forward_operator as release


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        argv: tuple[str, ...],
        *,
        code: str,
        timeout: int = 60,
        input_file: Path | None = None,
        output_file: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bytes:
        self.commands.append(argv)
        assert env == host_module.COMPOSE_ENV
        return b""


def _host(tmp_path: Path) -> tuple[host_module.RealEnableHost, RecordingRunner, Path]:
    app = tmp_path / "app"
    app.mkdir()
    backups = tmp_path / "backups"
    backups.mkdir()
    env_file = app / ".env"
    env_file.write_text("WECOM_ENABLED=true\nKEEP_SECRET=unchanged\n")
    os.chmod(env_file, 0o600)
    runner = RecordingRunner()
    host = host_module.RealEnableHost(
        runner,
        host_module.EnablePaths(app, backups),
        {"revision": "1" * 40, "image": "sha256:" + "2" * 64},
        require_production_paths=False,
    )
    return host, runner, env_file


def test_managed_enable_and_compensation_touch_only_supplement(tmp_path: Path) -> None:
    host, runner, env_file = _host(tmp_path)
    host._armed = True
    host._env_identity = host._env_file_identity()
    host.install_flags(
        dict(enable.ACTIVE_FLAGS), enable.MAX_ORDINAL, enable.REVIEW_MODE
    )
    enabled = env_file.read_text()
    assert "KEEP_SECRET=unchanged" in enabled
    assert "WECOM_INFOGRAPHIC_PRODUCER_ENABLED=true" in enabled
    assert "WECOM_INFOGRAPHIC_DELIVERY_ENABLED=true" in enabled
    assert "WECOM_INFOGRAPHIC_MAX_ORDINAL=3" in enabled
    assert "WECOM_INFOGRAPHIC_REVIEW_MODE=advisory" in enabled
    host.restart_dispatcher(enable.DISPATCHER_START)
    host.start_producer(enable.PRODUCER_START)
    host.disable_supplement_preserve_base()
    disabled = env_file.read_text()
    assert "KEEP_SECRET=unchanged" in disabled
    assert "WECOM_ENABLED=true" in disabled
    assert "WECOM_INFOGRAPHIC_PRODUCER_ENABLED=false" in disabled
    assert "WECOM_INFOGRAPHIC_DELIVERY_ENABLED=false" in disabled
    assert "WECOM_INFOGRAPHIC_MAX_ORDINAL=1" in disabled
    assert "WECOM_INFOGRAPHIC_REVIEW_MODE=strict" in disabled
    assert all(
        "--no-deps" in command
        for command in (runner.commands[0], runner.commands[1], runner.commands[3])
    )
    assert all(
        "--pull" in command and "never" in command
        for command in (runner.commands[0], runner.commands[1], runner.commands[3])
    )
    assert runner.commands[2][-2:] == ("stop", "wecom-infographic-producer")
    assert not any("backend-migrate" in command for command in runner.commands)


def test_env_drift_and_duplicate_managed_key_refuse_before_write(
    tmp_path: Path,
) -> None:
    host, runner, env_file = _host(tmp_path)
    host._armed = True
    host._env_identity = host._env_file_identity()
    env_file.write_text(env_file.read_text() + "NEW_KEY=changed\n")
    with pytest.raises(release.ReleaseBlocked, match="enable_env_drift"):
        host.install_flags(dict(enable.ACTIVE_FLAGS), 3, "advisory")
    assert runner.commands == []
    host._env_identity = host._env_file_identity()
    env_file.write_text(
        "WECOM_INFOGRAPHIC_DELIVERY_ENABLED=false\n"
        "WECOM_INFOGRAPHIC_DELIVERY_ENABLED=false\n"
    )
    host._env_identity = host._env_file_identity()
    with pytest.raises(release.ReleaseBlocked, match="enable_env_duplicate"):
        host.install_flags(dict(enable.ACTIVE_FLAGS), 3, "advisory")


def test_live_capture_binds_image_schema_recipient_and_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host, _, env_file = _host(tmp_path)
    image = host.manifest["image"]
    revision = host.manifest["revision"]
    key = "fake-current-group-key"
    monkeypatch.setattr(
        host_module, "APPROVED_RECIPIENT_KEY_SHA256", release.sha(key.encode())
    )
    monkeypatch.setattr(
        host_module,
        "APPROVED_RECIPIENT_FINGERPRINT",
        release.sha(("group_webhook\0" + key).encode()),
    )
    env_file.write_text(
        "WECOM_ENABLED=true\nWECOM_AUTO_DELIVERY_ENABLED=true\n"
        "WECOM_DELIVERY_PROVIDER=group_webhook\n"
        f"WECOM_GROUP_WEBHOOK_KEY={key}\n"
        "CONTENT_SLOT_MODE_ENABLED=true\nCONTENT_MORNING_ENABLED=true\n"
        "CONTENT_NOON_ENABLED=true\nCONTENT_EVENING_ENABLED=true\n"
        "AI_PROVIDER_MODE=zhipu\nAI_PLATFORM_API_KEY=fake-chat-key\n"
        "COMFLY_API_KEY=fake-key\nIMAGE_PROVIDER_MODE=comfly\n"
    )
    os.chmod(env_file, 0o600)
    release_env = host.paths.app / ".release.env"
    release_env.write_text(f"APP_IMAGE={host_module.RELEASE_IMAGE_PREFIX}{image}\n")
    os.chmod(release_env, 0o600)
    (host.paths.app / ".release-commit").write_text(revision)
    (host.paths.app / "RELEASE_COMMIT").write_text(revision)

    def fake_docker_json(*args: str) -> dict[str, Any]:
        assert args[:2] == ("image", "inspect")
        return {
            "Id": image,
            "Config": {"Labels": {"org.opencontainers.image.revision": revision}},
        }

    def fake_service(name: str) -> dict[str, Any] | None:
        if name == "wecom-infographic-producer":
            return None
        runtime = [
            "WECOM_ENABLED=true",
            "WECOM_AUTO_DELIVERY_ENABLED=true",
            "WECOM_DELIVERY_PROVIDER=group_webhook",
            f"WECOM_GROUP_WEBHOOK_KEY={key}",
        ]
        return {
            "Image": image,
            "RestartCount": 0,
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "Config": {"Env": runtime},
        }

    def fake_sql(sql: str) -> str:
        return release.TARGET_SCHEMA if sql == host_module.READONLY_SQL[0] else "0"

    monkeypatch.setattr(host, "_docker_json", fake_docker_json)
    monkeypatch.setattr(host, "_service", fake_service)
    monkeypatch.setattr(host, "_sql", fake_sql)
    captured = host.capture()
    assert captured["schema"] == release.TARGET_SCHEMA
    assert captured["recipient_fingerprint"] == release.sha(
        ("group_webhook\0" + key).encode()
    )
    assert captured["producer_running"] is False
    assert captured["services"]["wecom-dispatcher"]["runtime_infographic"] == {
        **dict.fromkeys(enable.DISPATCHER_FLAGS, False),
        "WECOM_INFOGRAPHIC_MAX_ORDINAL": 1,
        "WECOM_INFOGRAPHIC_REVIEW_MODE": "strict",
    }
    host.arm_production_mutation(host.manifest, captured)
    assert host._armed is True
    env_file.write_text(env_file.read_text().replace(key, "different-key"))
    with pytest.raises(release.ReleaseBlocked, match="enable_ordinary_group_identity"):
        host.capture()
    env_file.write_text(env_file.read_text().replace("different-key", key))

    def wrong_provider_service(name: str) -> dict[str, Any] | None:
        if name != "wecom-infographic-producer":
            return fake_service(name)
        return {
            "Image": image,
            "RestartCount": 0,
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "Config": {
                "Env": [
                    "WECOM_ENABLED=true",
                    "WECOM_AUTO_DELIVERY_ENABLED=true",
                    "WECOM_DELIVERY_PROVIDER=group_webhook",
                    f"WECOM_GROUP_WEBHOOK_KEY={key}",
                    "AI_PROVIDER_MODE=zhipu",
                    "AI_PLATFORM_API_KEY=fake-chat-key",
                    "IMAGE_PROVIDER_MODE=comfly",
                    "COMFLY_API_KEY=wrong-key",
                ]
            },
        }

    monkeypatch.setattr(host, "_service", wrong_provider_service)
    with pytest.raises(release.ReleaseBlocked, match="enable_producer_provider_drift"):
        host.capture()

    def restarted_service(name: str) -> dict[str, Any] | None:
        item = fake_service(name)
        if name == "wecom-dispatcher" and item is not None:
            item["RestartCount"] = 1
        return item

    monkeypatch.setattr(host, "_service", restarted_service)
    with pytest.raises(
        release.ReleaseBlocked, match="enable_service_unhealthy_or_wrong_image"
    ):
        host.capture()
    release_env.write_text(
        f"APP_IMAGE={host_module.RELEASE_IMAGE_PREFIX}{image}\n"
        "IMAGE_PROVIDER_MODE=disabled\n"
    )
    with pytest.raises(release.ReleaseBlocked, match="enable_release_env_override"):
        host.capture()
    release_env.write_text(f"APP_IMAGE={host_module.RELEASE_IMAGE_PREFIX}{image}\n")

    def duplicate_key_service(name: str) -> dict[str, Any] | None:
        item = fake_service(name)
        if name == "wecom-dispatcher" and item is not None:
            item["Config"]["Env"].append(f"WECOM_GROUP_WEBHOOK_KEY={key}")
        return item

    monkeypatch.setattr(host, "_service", duplicate_key_service)
    with pytest.raises(release.ReleaseBlocked, match="enable_container_env_duplicate"):
        host.capture()
