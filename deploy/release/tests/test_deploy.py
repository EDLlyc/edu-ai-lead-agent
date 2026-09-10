from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from contract import ReleaseManifest

from deploy import (
    APPLICATION_ENTRYPOINT_MODULES,
    APPLICATION_SERVICES,
    LONG_RUNNING_SERVICES,
    PRODUCTION_COMPOSE_PROFILES,
    QUIESCE_PHASES,
    START_PHASES,
    CommandResult,
    DeploymentEngine,
    DeploymentPaths,
    Phase,
    PhaseFailure,
    ProductionActions,
    RollbackFailure,
    exclusive_lock,
    redact_text,
    rollback_eligible,
)


class FakeActions:
    def __init__(
        self,
        *,
        fail_at: str | None = None,
        previous_head: str = "20260814_0020",
        rollback_fails: bool = False,
    ) -> None:
        self.fail_at = fail_at
        self.previous_head = previous_head
        self.rollback_fails = rollback_fails
        self.calls: list[str] = []

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError(f"injected_{name}_failure")

    def preflight(self) -> str:
        self._call("preflight")
        return self.previous_head

    def pull_and_verify_image(self) -> None:
        self._call("image")

    def quiesce(self) -> None:
        self._call("quiesce")

    def backup(self) -> str:
        self._call("backup")
        return "20260814T060000Z"

    def snapshot_previous(self) -> None:
        self._call("snapshot")

    def activate(self) -> None:
        self._call("activate")

    def migrate(self) -> str:
        self._call("migrate")
        return "20260814_0020"

    def start_phase(self, name: str, services: Sequence[str]) -> None:
        del services
        self._call(f"start:{name}")

    def collect_evidence(self) -> None:
        self._call("evidence")

    def mark_success(self) -> None:
        self._call("success")

    def restart_previous(self) -> None:
        self._call("restart_previous")

    def rollback(self) -> None:
        self._call("rollback")
        if self.rollback_fails:
            raise RuntimeError("injected_rollback_failure")

    def stop_writers(self) -> None:
        self.calls.append("stop_writers")


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        del cwd, timeout
        self.calls.append(tuple(arguments))
        return CommandResult(stdout="0\n")


def production_actions(
    tmp_path: Path,
    release_manifest: ReleaseManifest,
    runner: RecordingRunner,
) -> ProductionActions:
    active = tmp_path / "active"
    staging = tmp_path / "staging"
    active.mkdir()
    staging.mkdir()
    return ProductionActions(
        release_manifest,
        tmp_path / "release-manifest.json",
        tmp_path / "release-bundle.tar.gz",
        staging,
        DeploymentPaths(
            active=active,
            releases=tmp_path / "releases",
            state=tmp_path / "state",
            backups=tmp_path / "backups",
            lock=tmp_path / "deploy.lock",
        ),
        "test-runner",
        runner,
    )


def test_phase_order_is_explicit(release_manifest: ReleaseManifest) -> None:
    actions = FakeActions()
    engine = DeploymentEngine(release_manifest, actions)
    engine.run()
    assert actions.calls == [
        "preflight",
        "image",
        "quiesce",
        "backup",
        "snapshot",
        "activate",
        "migrate",
        "start:api-acquisition",
        "start:governance",
        "start:content",
        "start:official-account",
        "start:wecom",
        "evidence",
        "success",
    ]


def test_preflight_failure_has_no_mutating_calls(
    release_manifest: ReleaseManifest,
) -> None:
    actions = FakeActions(fail_at="preflight")
    with pytest.raises(PhaseFailure) as failure:
        DeploymentEngine(release_manifest, actions).run()
    assert failure.value.phase == Phase.PREFLIGHT
    assert actions.calls == ["preflight"]


def test_backup_failure_restarts_unchanged_previous_release(
    release_manifest: ReleaseManifest,
) -> None:
    actions = FakeActions(fail_at="backup")
    with pytest.raises(PhaseFailure):
        DeploymentEngine(release_manifest, actions).run()
    assert actions.calls[-1] == "restart_previous"
    assert "activate" not in actions.calls


def test_partial_quiesce_failure_restarts_complete_previous_release(
    release_manifest: ReleaseManifest,
) -> None:
    actions = FakeActions(fail_at="quiesce")
    with pytest.raises(PhaseFailure):
        DeploymentEngine(release_manifest, actions).run()
    assert actions.calls == [
        "preflight",
        "image",
        "quiesce",
        "restart_previous",
    ]


def test_post_activation_failure_rolls_back_when_head_is_unchanged(
    release_manifest: ReleaseManifest,
) -> None:
    actions = FakeActions(fail_at="start:content")
    with pytest.raises(PhaseFailure):
        DeploymentEngine(release_manifest, actions).run()
    assert actions.calls[-1] == "rollback"
    assert "stop_writers" not in actions.calls


def test_official_account_start_failure_uses_compatible_rollback(
    release_manifest: ReleaseManifest,
) -> None:
    actions = FakeActions(fail_at="start:official-account")
    with pytest.raises(PhaseFailure) as failure:
        DeploymentEngine(release_manifest, actions).run()
    assert failure.value.phase == Phase.START_OFFICIAL_ACCOUNT
    assert actions.calls[-1] == "rollback"
    assert "start:wecom" not in actions.calls


def test_partial_activation_failure_restores_previous_snapshot(
    release_manifest: ReleaseManifest,
) -> None:
    actions = FakeActions(fail_at="activate")
    with pytest.raises(PhaseFailure):
        DeploymentEngine(release_manifest, actions).run()
    assert actions.calls[-1] == "rollback"
    assert "restart_previous" not in actions.calls


def test_migration_failure_never_attempts_automatic_rollback(
    release_manifest: ReleaseManifest,
) -> None:
    actions = FakeActions(fail_at="migrate")
    with pytest.raises(PhaseFailure):
        DeploymentEngine(release_manifest, actions).run()
    assert "rollback" not in actions.calls
    assert actions.calls[-1] == "stop_writers"


def test_rollback_failure_closes_writers(release_manifest: ReleaseManifest) -> None:
    actions = FakeActions(fail_at="evidence", rollback_fails=True)
    with pytest.raises(RollbackFailure):
        DeploymentEngine(release_manifest, actions).run()
    assert actions.calls[-1] == "stop_writers"


def test_rollback_eligibility_requires_completed_or_unattempted_migration() -> None:
    assert rollback_eligible(
        migration_attempted=False,
        migration_completed=False,
        previous_head="old",
        target_head="new",
        compatibility_reviewed=False,
        previous_application_compatible=False,
    )
    assert not rollback_eligible(
        migration_attempted=True,
        migration_completed=False,
        previous_head="same",
        target_head="same",
        compatibility_reviewed=True,
        previous_application_compatible=True,
    )


def test_deployment_lock_rejects_concurrent_holder(tmp_path: Path) -> None:
    lock = tmp_path / "deploy.lock"
    with (
        exclusive_lock(lock),
        pytest.raises(PhaseFailure, match="deployment_lock_busy"),
        exclusive_lock(lock),
    ):
        pass


def test_error_redaction_removes_credentials() -> None:
    value = "password=hunter2 url=https://user:pass@example.test/path token=abcd"
    redacted = redact_text(value)
    assert "hunter2" not in redacted
    assert "user:pass" not in redacted
    assert "abcd" not in redacted


def test_release_topology_is_exact_unique_and_fully_quiesced() -> None:
    start_services = tuple(
        service for start_phase in START_PHASES for service in start_phase.services
    )
    quiesce_services = tuple(
        service for services in QUIESCE_PHASES for service in services
    )
    assert tuple(start_phase.phase for start_phase in START_PHASES) == (
        Phase.START_API,
        Phase.START_GOVERNANCE,
        Phase.START_CONTENT,
        Phase.START_OFFICIAL_ACCOUNT,
        Phase.START_WECOM,
    )
    assert len(start_services) == len(set(start_services)) == 12
    assert set(quiesce_services) == set(start_services)
    assert len(quiesce_services) == len(set(quiesce_services)) == 12
    assert APPLICATION_SERVICES == ("backend-migrate", *start_services)
    assert len(APPLICATION_SERVICES) == len(set(APPLICATION_SERVICES)) == 13
    assert set(APPLICATION_ENTRYPOINT_MODULES) == {
        "app.seed_sources",
        "app.api_main",
        "app.scheduler_main",
        "app.worker_main",
        "app.governance_scheduler_main",
        "app.governance_worker_main",
        "app.content_scheduler_main",
        "app.content_worker_main",
        "app.official_account_weekly_dag_main",
        "app.official_account_weekly_scheduler_main",
        "app.official_account_worker_main",
        "app.wechat_official_account_draft_main",
        "app.wecom_dispatcher_main",
    }


def test_compose_enables_all_six_production_profiles(
    tmp_path: Path, release_manifest: ReleaseManifest
) -> None:
    runner = RecordingRunner()
    actions = production_actions(tmp_path, release_manifest, runner)
    actions._compose("config", "--quiet")
    arguments = runner.calls[-1]
    profile_arguments = tuple(
        arguments[index + 1]
        for index, argument in enumerate(arguments[:-1])
        if argument == "--profile"
    )
    assert profile_arguments == PRODUCTION_COMPOSE_PROFILES
    assert arguments[-2:] == ("config", "--quiet")


def test_quiesce_and_incident_shutdown_cover_the_same_exact_service_set(
    tmp_path: Path, release_manifest: ReleaseManifest
) -> None:
    runner = RecordingRunner()
    actions = production_actions(tmp_path, release_manifest, runner)
    actions.quiesce()
    quiesce_stops = [
        call[call.index("stop") :] for call in runner.calls if "stop" in call
    ]
    assert quiesce_stops == [
        ("stop", "--timeout", "60", *services) for services in QUIESCE_PHASES
    ]

    runner.calls.clear()
    actions.stop_writers()
    incident_stops = [call[call.index("stop") :] for call in runner.calls]
    assert incident_stops == [
        ("stop", "--timeout", "30", *services) for services in QUIESCE_PHASES
    ]


def test_queue_gate_includes_official_account_roots_and_ambiguous_outcomes(
    tmp_path: Path, release_manifest: ReleaseManifest
) -> None:
    runner = RecordingRunner()
    actions = production_actions(tmp_path, release_manifest, runner)
    assert actions._queue_running_count() == 0
    query = base64.b64decode(runner.calls[-1][-1]).decode("utf-8")
    assert "official_account_article_runs WHERE status = 'running'" in query
    assert "official_account_weekly_dag_runs WHERE status = 'running'" in query
    assert (
        "wechat_mp_draft_jobs WHERE status IN ('running', 'outcome_unknown')" in query
    )
    assert "text_status = 'unknown'" in query
    assert "image_status = 'unknown'" in query


def test_long_running_start_disables_build_and_dependency_start(
    tmp_path: Path,
    release_manifest: ReleaseManifest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RecordingRunner()
    actions = production_actions(tmp_path, release_manifest, runner)
    verified: list[tuple[Sequence[str], str | None]] = []
    monkeypatch.setattr(
        actions,
        "_verify_services",
        lambda services, *, expected_image=None, require_zero_restarts=True: (
            verified.append((services, expected_image)) or {}
        ),
    )
    services = START_PHASES[3].services
    actions.start_phase("official-account", services)
    arguments = runner.calls[-1]
    assert arguments[arguments.index("up") :] == (
        "up",
        "-d",
        "--no-build",
        "--no-deps",
        "--force-recreate",
        *services,
    )
    assert verified == [(services, None)]


def test_previous_restart_uses_previous_image_and_disables_dependencies(
    tmp_path: Path,
    release_manifest: ReleaseManifest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RecordingRunner()
    actions = production_actions(tmp_path, release_manifest, runner)
    previous_image = release_manifest.image.reference.replace("b" * 64, "c" * 64)
    actions.previous_manifest = replace(
        release_manifest,
        source=replace(release_manifest.source, commit="d" * 40),
        image=replace(
            release_manifest.image,
            reference=previous_image,
            digest="sha256:" + "c" * 64,
        ),
    )
    verified: list[tuple[Sequence[str], str | None]] = []
    monkeypatch.setattr(
        actions,
        "_verify_services",
        lambda services, *, expected_image=None, require_zero_restarts=True: (
            verified.append((services, expected_image)) or {}
        ),
    )
    actions.restart_previous()
    arguments = runner.calls[-1]
    assert arguments[arguments.index("up") :] == (
        "up",
        "-d",
        "--no-build",
        "--no-deps",
        "--force-recreate",
        *LONG_RUNNING_SERVICES,
    )
    assert verified == [(LONG_RUNNING_SERVICES, previous_image)]
