from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from contract import ReleaseManifest

from deploy import (
    DeploymentEngine,
    Phase,
    PhaseFailure,
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
