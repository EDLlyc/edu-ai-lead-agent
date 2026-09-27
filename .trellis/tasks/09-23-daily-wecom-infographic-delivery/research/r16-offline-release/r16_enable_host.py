"""Narrow R16 post-release enable host; no direct send or provider invocation.

Only the separately authenticated enable operator may arm mutations. A failed
enablement stops the optional producer and restores the dispatcher's supplement
flags; the existing base text/image services are not stopped or replaced.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from r16_enablement import (
    ACTIVE_FLAGS,
    DISPATCHER_FLAGS,
    DISPATCHER_START,
    MAX_ORDINAL,
    PRODUCER_FLAGS,
    PRODUCER_START,
    REVIEW_MODE,
)
from r16_forward_operator import (
    APPROVED_RECIPIENT_FINGERPRINT,
    APPROVED_RECIPIENT_KEY_SHA256,
    OFF_FLAGS,
    SERVICES,
    TARGET_SCHEMA,
    ReleaseBlocked,
    canonical,
    require,
    sha,
)
from r16_real_host import (
    APP,
    BACKUP_ROOT,
    PROJECT,
    Runner,
    SubprocessRunner,
    _parse_env,
)

RELEASE_IMAGE_PREFIX = "offline.local/edu-ai/edu-ai-lead-agent-backend@"
MANAGED_VALUES = {
    **{key: "true" if value else "false" for key, value in ACTIVE_FLAGS.items()},
    "WECOM_INFOGRAPHIC_MAX_ORDINAL": str(MAX_ORDINAL),
    "WECOM_INFOGRAPHIC_REVIEW_MODE": REVIEW_MODE,
}
DISABLED_VALUES = {
    **dict.fromkeys(OFF_FLAGS, "false"),
    "WECOM_INFOGRAPHIC_MAX_ORDINAL": "1",
    "WECOM_INFOGRAPHIC_REVIEW_MODE": "strict",
}
COMPOSE_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "DOCKER_CONFIG": "/root/.docker",
}
READONLY_SQL = (
    "SELECT version_num FROM alembic_version",
    (
        "SELECT count(*) FROM public.wecom_delivery_jobs t WHERE "
        "to_jsonb(t)->>'status' IN "
        "('delivery_unknown','result_unknown','outcome_unknown') "
        "AND (to_jsonb(t)->>'expires_at' IS NULL OR "
        "(to_jsonb(t)->>'expires_at')::timestamptz > now())"
    ),
    (
        "SELECT count(*) FROM public.wecom_delivery_jobs t WHERE "
        "to_jsonb(t)->>'status' IN "
        "('queued','pending','running','delivering','retryable_failed',"
        "'retry_scheduled') OR to_jsonb(t)->>'lease_token' IS NOT NULL"
    ),
)


@dataclass(frozen=True)
class EnablePaths:
    app: Path = APP
    backup_root: Path = BACKUP_ROOT


class RealEnableHost:
    """Capture exact post-release identity and make one bounded flag transition."""

    def __init__(
        self,
        runner: Runner,
        paths: EnablePaths,
        manifest: dict[str, Any],
        *,
        require_production_paths: bool = True,
    ) -> None:
        if require_production_paths:
            require(
                os.geteuid() == 0
                and isinstance(runner, SubprocessRunner)
                and paths == EnablePaths(),
                "enable_production_host_required",
            )
        else:
            require(
                paths.app.resolve() != APP
                and paths.backup_root.resolve() != BACKUP_ROOT
                and not isinstance(runner, SubprocessRunner),
                "enable_fake_host_only",
            )
        self.runner = runner
        self.paths = paths
        self.manifest = manifest
        self._armed = False
        self._last_capture: dict[str, Any] | None = None
        self._env_identity: tuple[int, int, int, int] | None = None

    def _run(self, argv: tuple[str, ...], code: str, timeout: int = 60) -> bytes:
        return self.runner.run(argv, code=code, timeout=timeout, env=COMPOSE_ENV)

    def _compose(self, *args: str, code: str, timeout: int = 60) -> bytes:
        app = self.paths.app
        return self._run(
            (
                "docker",
                "compose",
                "--project-name",
                PROJECT,
                "-f",
                str(app / "compose.yaml"),
                "--env-file",
                str(app / ".env"),
                "--env-file",
                str(app / ".release.env"),
                *args,
            ),
            code,
            timeout,
        )

    def _docker_json(self, *args: str) -> dict[str, Any]:
        try:
            value = json.loads(self._run(("docker", *args), "enable_docker_inspect"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleaseBlocked("enable_docker_json") from exc
        require(
            isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict),
            "enable_docker_shape",
        )
        return cast(dict[str, Any], value[0])

    def _service(self, name: str) -> dict[str, Any] | None:
        require(
            name in (*SERVICES, "wecom-infographic-producer"), "enable_service_name"
        )
        profile = (
            ("--profile", "infographic")
            if name == "wecom-infographic-producer"
            else ("--profile", "wecom")
            if name == "wecom-dispatcher"
            else ()
        )
        ids = (
            self._compose(
                *profile, "ps", "-a", "-q", name, code="enable_service_lookup"
            )
            .decode()
            .split()
        )
        require(len(ids) <= 1, "enable_service_count")
        if not ids:
            return None
        require(
            re.fullmatch(r"[0-9a-f]{64}", ids[0]) is not None, "enable_container_id"
        )
        item = self._docker_json("inspect", ids[0])
        labels = item.get("Config", {}).get("Labels", {})
        require(
            labels.get("com.docker.compose.project") == PROJECT
            and labels.get("com.docker.compose.service") == name,
            "enable_service_labels",
        )
        return item

    def _sql(self, sql: str) -> str:
        require(sql in READONLY_SQL, "enable_sql_not_allowlisted")
        return (
            self._compose(
                "exec",
                "-T",
                "postgres",
                "sh",
                "-c",
                'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"',
                "sh",
                sql,
                code="enable_sql_readonly",
                timeout=180,
            )
            .decode()
            .strip()
        )

    @staticmethod
    def _bool(env: dict[str, str], key: str, default: str = "false") -> bool:
        value = env.get(key, default).lower()
        require(value in ("true", "false"), "enable_flag_syntax")
        return value == "true"

    @staticmethod
    def _runtime(env: dict[str, str], flags: tuple[str, ...]) -> dict[str, object]:
        result: dict[str, object] = {
            key: RealEnableHost._bool(env, key) for key in flags
        }
        ordinal = env.get("WECOM_INFOGRAPHIC_MAX_ORDINAL", "1")
        require(ordinal in ("1", "2", "3"), "enable_runtime_ordinal")
        result["WECOM_INFOGRAPHIC_MAX_ORDINAL"] = int(ordinal)
        result["WECOM_INFOGRAPHIC_REVIEW_MODE"] = env.get(
            "WECOM_INFOGRAPHIC_REVIEW_MODE", "strict"
        )
        return result

    @staticmethod
    def _container_env(config: dict[str, Any]) -> dict[str, str]:
        entries = config.get("Env")
        require(isinstance(entries, list), "enable_container_env_shape")
        assert isinstance(entries, list)
        result: dict[str, str] = {}
        for entry in entries:
            require(
                isinstance(entry, str) and "=" in entry,
                "enable_container_env_shape",
            )
            key, value = entry.split("=", 1)
            require(key not in result, "enable_container_env_duplicate")
            result[key] = value
        return result

    def _env_file_identity(self) -> tuple[int, int, int, int]:
        info = (self.paths.app / ".env").lstat()
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and stat.S_IMODE(info.st_mode) == 0o600,
            "enable_env_file_type",
        )
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    def capture(self) -> dict[str, Any]:
        app = self.paths.app
        self._env_identity = self._env_file_identity()
        env = _parse_env(app / ".env")
        release_env = _parse_env(app / ".release.env")
        require(
            not any(
                key in release_env
                for key in (
                    *MANAGED_VALUES,
                    "WECOM_GROUP_WEBHOOK_KEY",
                    "AI_PROVIDER_MODE",
                    "AI_PLATFORM_API_KEY",
                    "IMAGE_PROVIDER_MODE",
                    "COMFLY_API_KEY",
                )
            ),
            "enable_release_env_override",
        )
        revision = self.manifest["revision"]
        image = self.manifest["image"]
        require(
            (app / ".release-commit").read_text().strip() == revision
            and (app / "RELEASE_COMMIT").read_text().strip() == revision
            and release_env.get("APP_IMAGE") == RELEASE_IMAGE_PREFIX + image,
            "enable_release_identity",
        )
        inspected = self._docker_json("image", "inspect", RELEASE_IMAGE_PREFIX + image)
        require(
            inspected.get("Id") == image
            and inspected.get("Config", {})
            .get("Labels", {})
            .get("org.opencontainers.image.revision")
            == revision,
            "enable_image_identity",
        )
        require(
            env.get("WECOM_DELIVERY_PROVIDER") == "group_webhook"
            and self._bool(env, "WECOM_ENABLED")
            and self._bool(env, "WECOM_AUTO_DELIVERY_ENABLED")
            and self._bool(env, "CONTENT_SLOT_MODE_ENABLED")
            and all(
                self._bool(env, f"CONTENT_{slot.upper()}_ENABLED")
                for slot in ("morning", "noon", "evening")
            )
            and env.get("AI_PROVIDER_MODE") == "zhipu"
            and bool(env.get("AI_PLATFORM_API_KEY"))
            and bool(env.get("COMFLY_API_KEY"))
            and env.get("IMAGE_PROVIDER_MODE") == "comfly",
            "enable_base_configuration",
        )
        key = env.get("WECOM_GROUP_WEBHOOK_KEY", "")
        require(
            bool(key)
            and sha(key.encode()) == APPROVED_RECIPIENT_KEY_SHA256
            and sha(("group_webhook\0" + key).encode())
            == APPROVED_RECIPIENT_FINGERPRINT,
            "enable_ordinary_group_identity",
        )
        flags = {name: self._bool(env, name) for name in OFF_FLAGS}
        ordinal_text = env.get("WECOM_INFOGRAPHIC_MAX_ORDINAL", "1")
        require(ordinal_text in ("1", "2", "3"), "enable_ordinal_syntax")
        review_mode = env.get("WECOM_INFOGRAPHIC_REVIEW_MODE", "strict")
        require(review_mode in ("strict", "advisory"), "enable_review_mode")
        services: dict[str, dict[str, object]] = {}
        for name in SERVICES:
            item = self._service(name)
            require(item is not None, "enable_service_missing")
            assert item is not None
            state = item.get("State", {})
            config = item.get("Config", {})
            require(
                state.get("Status") == "running"
                and state.get("Health", {}).get("Status", "healthy") == "healthy"
                and item.get("RestartCount") == 0
                and item.get("Image") == image,
                "enable_service_unhealthy_or_wrong_image",
            )
            projection: dict[str, object] = {
                "image": item["Image"],
                "running": True,
                "healthy": True,
            }
            if name == "wecom-dispatcher":
                actual_env = self._container_env(config)
                require(
                    actual_env.get("WECOM_GROUP_WEBHOOK_KEY") == key
                    and actual_env.get("WECOM_DELIVERY_PROVIDER") == "group_webhook"
                    and self._bool(actual_env, "WECOM_ENABLED")
                    and self._bool(actual_env, "WECOM_AUTO_DELIVERY_ENABLED"),
                    "enable_dispatcher_base_drift",
                )
                projection["runtime_infographic"] = self._runtime(
                    actual_env, DISPATCHER_FLAGS
                )
            services[name] = projection
        producer = self._service("wecom-infographic-producer")
        producer_running = (
            producer is not None
            and producer.get("State", {}).get("Status") == "running"
        )
        result: dict[str, Any] = {
            "image": image,
            "revision": revision,
            "schema": self._sql(READONLY_SQL[0]),
            "recipient_fingerprint": APPROVED_RECIPIENT_FINGERPRINT,
            "base_delivery_healthy": True,
            "unknown_work_count": self._count(READONLY_SQL[1]),
            "pending_work_count": self._count(READONLY_SQL[2]),
            "flags": flags,
            "producer_running": producer_running,
            "max_ordinal": int(ordinal_text),
            "review_mode": review_mode,
            "services": services,
        }
        if producer_running:
            assert producer is not None
            config = producer.get("Config", {})
            actual_env = self._container_env(config)
            require(
                producer.get("Image") == image
                and producer.get("State", {}).get("Health", {}).get("Status", "healthy")
                == "healthy"
                and producer.get("RestartCount") == 0
                and actual_env.get("WECOM_GROUP_WEBHOOK_KEY") == key
                and self._bool(actual_env, "WECOM_ENABLED")
                and self._bool(actual_env, "WECOM_AUTO_DELIVERY_ENABLED")
                and actual_env.get("WECOM_DELIVERY_PROVIDER") == "group_webhook",
                "enable_producer_identity",
            )
            require(
                actual_env.get("AI_PROVIDER_MODE") == "zhipu"
                and actual_env.get("AI_PLATFORM_API_KEY") == env["AI_PLATFORM_API_KEY"]
                and actual_env.get("IMAGE_PROVIDER_MODE") == "comfly"
                and actual_env.get("COMFLY_API_KEY") == env["COMFLY_API_KEY"],
                "enable_producer_provider_drift",
            )
            result.update(
                {
                    "producer_image": producer["Image"],
                    "producer_healthy": True,
                    "producer_runtime_infographic": self._runtime(
                        actual_env, PRODUCER_FLAGS
                    ),
                }
            )
        self._last_capture = json.loads(canonical(result))
        return cast(dict[str, Any], json.loads(canonical(result)))

    def _count(self, sql: str) -> int:
        value = self._sql(sql)
        require(value.isdecimal(), "enable_work_count")
        return int(value)

    def arm_production_mutation(
        self, manifest: dict[str, Any], current: dict[str, Any]
    ) -> None:
        require(
            not self._armed
            and manifest == self.manifest
            and current == self._last_capture
            and current.get("schema") == TARGET_SCHEMA
            and current.get("recipient_fingerprint") == APPROVED_RECIPIENT_FINGERPRINT
            and all(value is False for value in current.get("flags", {}).values())
            and current.get("producer_running") is False,
            "enable_mutation_arm_identity",
        )
        self._armed = True

    def _write_managed(self, values: dict[str, str]) -> None:
        require(self._armed, "enable_mutation_unarmed")
        require(self._env_identity == self._env_file_identity(), "enable_env_drift")
        path = self.paths.app / ".env"
        original = path.read_bytes()
        require(b"\x00" not in original, "enable_env_nul")
        lines = original.decode("utf-8").splitlines(keepends=True)
        seen: set[str] = set()
        rendered: list[str] = []
        for line in lines:
            key = line.partition("=")[0]
            if key in values:
                require(key not in seen, "enable_env_duplicate")
                rendered.append(f"{key}={values[key]}\n")
                seen.add(key)
            else:
                rendered.append(line)
        for key in sorted(values):
            if key not in seen:
                if rendered and not rendered[-1].endswith("\n"):
                    rendered.append("\n")
                rendered.append(f"{key}={values[key]}\n")
        body = "".join(rendered).encode("utf-8")
        temporary = path.with_name(".env.r16-enable-tmp")
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        temporary_created = True
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            require(self._env_identity == self._env_file_identity(), "enable_env_drift")
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary_created and temporary.exists():
                temporary.unlink()
        self._env_identity = self._env_file_identity()

    def install_flags(
        self, flags: dict[str, bool], max_ordinal: int, review_mode: str
    ) -> None:
        require(
            flags == ACTIVE_FLAGS
            and max_ordinal == MAX_ORDINAL
            and review_mode == REVIEW_MODE,
            "enable_requested_flags",
        )
        self._write_managed(MANAGED_VALUES)

    def restart_dispatcher(self, command: tuple[str, ...]) -> None:
        require(
            self._armed and command == DISPATCHER_START, "enable_dispatcher_command"
        )
        self._compose(*command[2:], code="enable_dispatcher_start", timeout=180)

    def start_producer(self, command: tuple[str, ...]) -> None:
        require(self._armed and command == PRODUCER_START, "enable_producer_command")
        self._compose(*command[2:], code="enable_producer_start", timeout=180)

    def disable_supplement_preserve_base(self) -> None:
        require(self._armed, "enable_mutation_unarmed")
        self._write_managed(DISABLED_VALUES)
        stop_error: ReleaseBlocked | None = None
        try:
            self._compose(
                "--profile",
                "infographic",
                "stop",
                "wecom-infographic-producer",
                code="enable_producer_stop",
                timeout=180,
            )
        except ReleaseBlocked as exc:
            stop_error = exc
        self._compose(
            *DISPATCHER_START[2:], code="enable_dispatcher_disable", timeout=180
        )
        if stop_error is not None:
            raise stop_error
