from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import stat
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


operator = load("no_source_link_operator", "deploy-no-source-links.py")
validator = load("no_source_link_validator", "validate-no-source-link-overlay.py")
builder = load("no_source_link_builder", "build-no-source-link-overlay.py")


def manifest() -> dict[str, object]:
    revision = "a" * 40
    image_id = "sha256:" + "b" * 64
    return {
        "version": "no-source-links-offline-v1",
        "revision": revision,
        "previous_revision": operator.PREVIOUS_REVISION,
        "base_ref": operator.PREVIOUS_REF,
        "base_archive_sha256": operator.BASE_ARCHIVE_SHA256,
        "candidate_tag": operator.REPOSITORY + ":no-source-links-" + revision[:12],
        "candidate_ref": operator.REPOSITORY + "@" + image_id,
        "candidate_image_id": image_id,
        "archive": "backend-image.oci.tar.gz",
        "archive_sha256": "c" * 64,
        "app_files": operator.FILES,
        "validator": "validate-no-source-link-overlay.py",
        "validator_sha256": "d" * 64,
    }


def write_manifest(tmp_path: Path, value: dict[str, object]) -> tuple[Path, str]:
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    path = tmp_path / "candidate.json"
    path.write_bytes(body)
    return path, hashlib.sha256(body).hexdigest()


def test_manifest_is_exact_and_revision_bound(tmp_path: Path) -> None:
    assert builder.FILES == operator.FILES == validator.OVERLAY_FILES
    value = manifest()
    path, digest = write_manifest(tmp_path, value)
    assert operator.load_manifest(path, digest) == value
    for field, bad in (
        ("revision", operator.PREVIOUS_REVISION),
        ("candidate_tag", operator.REPOSITORY + ":other"),
        ("candidate_ref", operator.PREVIOUS_REF),
        ("candidate_image_id", operator.PREVIOUS_ID),
        ("archive", "../escape.tar.gz"),
        ("app_files", {}),
        ("base_archive_sha256", "0" * 64),
    ):
        changed = {**value, field: bad}
        candidate, candidate_hash = write_manifest(tmp_path, changed)
        with pytest.raises(RuntimeError):
            operator.load_manifest(candidate, candidate_hash)


def test_release_env_replacement_is_one_exact_line() -> None:
    original = b"KEEP=yes\r\nAPP_IMAGE=" + operator.PREVIOUS_REF.encode() + b"\r\n"
    assert operator.replace_image(
        original, str(manifest()["candidate_ref"])
    ) == original.replace(
        operator.PREVIOUS_REF.encode(), str(manifest()["candidate_ref"]).encode()
    )
    for bad in (b"APP_IMAGE=tag\n", original + original, b"KEEP=yes\n"):
        with pytest.raises(RuntimeError, match="base_release_env"):
            operator.replace_image(bad, str(manifest()["candidate_ref"]))


def owner_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "account_fingerprint": operator.SINGLE_ACCOUNT,
            "key_kind": "history",
            "key_value": "import-v1",
            "owner": "history-import-v1",
            "status": "ready",
            "provenance_fingerprint": "1" * 64,
            "created_at": "2026-09-14T00:00:00+00:00",
            "updated_at": "2026-09-14T00:00:00+00:00",
        }
    ]
    for index in range(13):
        rows.append(
            {
                "account_fingerprint": operator.SINGLE_ACCOUNT,
                "key_kind": "article" if index % 2 else "event",
                "key_value": f"key-{index}",
                "owner": f"owner-{index}",
                "status": "acknowledged",
                "provenance_fingerprint": f"{index + 2:064x}",
                "created_at": "2026-09-14T00:00:00+00:00",
                "updated_at": "2026-09-14T00:00:00+00:00",
            }
        )
    return rows


def test_owner_state_requires_exact_barrier_count_and_safe_terminal_rows() -> None:
    rows = owner_rows()
    assert len(operator.validate_owner_rows(rows)) == 64
    for mutation in ("count", "account", "barrier", "unknown", "duplicate"):
        changed = copy.deepcopy(rows)
        if mutation == "count":
            changed.pop()
        elif mutation == "account":
            changed[1]["account_fingerprint"] = "0" * 64
        elif mutation == "barrier":
            changed[0]["status"] = "reserved"
        elif mutation == "unknown":
            changed[1]["status"] = "outcome_unknown"
        else:
            changed[2]["key_kind"] = changed[1]["key_kind"]
            changed[2]["key_value"] = changed[1]["key_value"]
        with pytest.raises(RuntimeError):
            operator.validate_owner_rows(changed)


def cohort_rows() -> list[dict[str, object]]:
    return [
        {
            "job": {
                "id": f"00000000-0000-0000-0000-{index:012d}",
                "run_id": f"run-{index}",
                "status": "queued",
                "attempt_count": 0,
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
            },
            "run": {
                "id": f"run-{index}",
                "business_date": day,
                "scoring_profile": "preview",
                "timezone": "Asia/Shanghai",
            },
        }
        for index, day in enumerate(operator.HISTORICAL_DATES)
    ]


def pin_cohort(monkeypatch: pytest.MonkeyPatch, rows: object) -> None:
    body = json.dumps(
        rows, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    monkeypatch.setattr(
        operator, "HISTORICAL_COHORT_SHA256", hashlib.sha256(body).hexdigest()
    )


def future_wecom_rows(count: int = 2) -> list[dict[str, object]]:
    return [
        {
            "id": f"10000000-0000-4000-8000-{index:012d}",
            "delivery_window_id": f"20000000-0000-4000-8000-{index:012d}",
            "content_slot_selection_id": f"30000000-0000-4000-8000-{index:012d}",
            "sequence_ordinal": index + 1,
            "mode": "formal",
            "status": "queued",
            "text_status": "pending",
            "image_status": "pending",
            "include_copy": True,
            "include_image": True,
            "attempt_count": 0,
            "next_attempt_at_epoch": "1000001200.000000",
            "not_before_epoch": "1000001200.000000",
            "expires_at_epoch": "1000004800.000000",
            "lease_owner": None,
            "lease_token": None,
            "lease_expires_at_epoch": None,
            "heartbeat_at_epoch": None,
            "last_error_code": None,
            "created_at_epoch": "0999999000.000000",
            "started_at_epoch": None,
            "completed_at_epoch": None,
            "attempt_rows": 0,
        }
        for index in range(count)
    ]


def wecom_snapshot(rows: object, observed: str = "1000000000.000000") -> str:
    return json.dumps({"observed_at_epoch": observed, "jobs": rows})


def test_future_wecom_snapshot_accepts_zero_or_bounded_unclaimable_jobs() -> None:
    empty = operator.validate_future_wecom_jobs(
        json.loads(wecom_snapshot([])), minimum_lead_seconds=600
    )
    rows = future_wecom_rows()
    bounded = operator.validate_future_wecom_jobs(
        json.loads(wecom_snapshot(rows)), minimum_lead_seconds=600
    )
    assert empty == (0, hashlib.sha256(b"[]").hexdigest())
    assert bounded[0] == 2 and len(bounded[1]) == 64
    with pytest.raises(RuntimeError, match="wecom_future_count"):
        operator.validate_future_wecom_jobs(
            json.loads(wecom_snapshot(future_wecom_rows(4))),
            minimum_lead_seconds=600,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "running"),
        ("status", "partial"),
        ("status", "delivery_unknown"),
        ("text_status", "unknown"),
        ("image_status", "unknown"),
        ("image_status", "delivered"),
        ("mode", "test"),
        ("include_copy", False),
        ("attempt_count", 1),
        ("attempt_rows", 1),
        ("lease_owner", "worker"),
        ("lease_token", "40000000-0000-4000-8000-000000000000"),
        ("lease_expires_at_epoch", "1000000600.000000"),
        ("heartbeat_at_epoch", "1000000000.000000"),
        ("last_error_code", "provider_failed"),
        ("started_at_epoch", "1000000000.000000"),
        ("completed_at_epoch", "1000000000.000000"),
        ("next_attempt_at_epoch", "1000001199.000000"),
        ("created_at_epoch", "1000000001.000000"),
        ("not_before_epoch", "1000000000.000000"),
        ("expires_at_epoch", "0999999999.000000"),
    ],
)
def test_future_wecom_snapshot_rejects_due_or_unsafe_state(
    field: str, value: object
) -> None:
    rows = future_wecom_rows()
    rows[0][field] = value
    with pytest.raises(RuntimeError):
        operator.validate_future_wecom_jobs(
            json.loads(wecom_snapshot(rows)), minimum_lead_seconds=600
        )


def test_future_wecom_snapshot_rejects_malformed_or_short_lead() -> None:
    rows = future_wecom_rows()
    del rows[0]["completed_at_epoch"]
    with pytest.raises(RuntimeError, match="wecom_future_shape"):
        operator.validate_future_wecom_jobs(
            json.loads(wecom_snapshot(rows)), minimum_lead_seconds=600
        )
    with pytest.raises(RuntimeError, match="wecom_future_window"):
        operator.validate_future_wecom_jobs(
            json.loads(wecom_snapshot(future_wecom_rows())),
            minimum_lead_seconds=1201,
        )


def test_idle_binds_sealed_copy_cohort_zero_editions_and_owner_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cohort = cohort_rows()
    owners = owner_rows()
    wecom = future_wecom_rows()
    pin_cohort(monkeypatch, cohort)
    operation = operator.Deployment(Path("/tmp/candidate.json"), manifest())
    replies = {
        operator.BUSINESS_DATE_QUERY: "2026-09-15",
        operator.HISTORICAL_COHORT_QUERY: json.dumps(cohort),
        operator.WECOM_ACTIVE_QUERY: wecom_snapshot(wecom),
        operator.IDLE_QUERY: "9",
        operator.SINGLE_EDITION_QUERY: "0",
        operator.OWNER_QUERY: json.dumps(owners),
    }
    monkeypatch.setattr(operation, "scalar", lambda query: replies[query])
    operation.idle()
    sealed = operation.owner_sha256
    wecom_sealed = operation.future_wecom_sha256
    operation.idle()
    assert sealed == operation.owner_sha256
    assert operation.future_wecom_count == 2
    assert wecom_sealed == operation.future_wecom_sha256
    changed = copy.deepcopy(wecom)
    changed[0]["created_at_epoch"] = "0999999001.000000"
    replies[operator.WECOM_ACTIVE_QUERY] = wecom_snapshot(changed)
    with pytest.raises(RuntimeError, match="queue_or_owner_not_idle"):
        operation.idle()
    replies[operator.WECOM_ACTIVE_QUERY] = wecom_snapshot(wecom)
    replies[operator.SINGLE_EDITION_QUERY] = "1"
    with pytest.raises(RuntimeError, match="queue_or_owner_not_idle"):
        operation.idle()
    assert operator.SINGLE_EDITION_QUERY == (
        "SELECT count(*) FROM official_account_single_editions"
    )


def test_idle_accepts_zero_future_wecom_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    cohort = cohort_rows()
    pin_cohort(monkeypatch, cohort)
    operation = operator.Deployment(Path("/tmp/candidate.json"), manifest())
    replies = {
        operator.BUSINESS_DATE_QUERY: "2026-09-15",
        operator.HISTORICAL_COHORT_QUERY: json.dumps(cohort),
        operator.WECOM_ACTIVE_QUERY: wecom_snapshot([]),
        operator.IDLE_QUERY: "7",
        operator.SINGLE_EDITION_QUERY: "0",
        operator.OWNER_QUERY: json.dumps(owner_rows()),
    }
    monkeypatch.setattr(operation, "scalar", lambda query: replies[query])
    operation.idle()
    assert operation.future_wecom_count == 0
    assert operation.future_wecom_sha256 == hashlib.sha256(b"[]").hexdigest()


def test_receipt_references_frozen_wecom_digest_without_private_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = operator.Deployment(Path("/tmp/candidate.json"), manifest())
    operation.backup_dir = tmp_path
    operation.owner_sha256 = "4" * 64
    operation.future_wecom_count = 2
    operation.future_wecom_sha256 = "5" * 64
    checked: list[int] = []
    monkeypatch.setattr(
        operation,
        "idle",
        lambda *, minimum_wecom_lead_seconds: checked.append(
            minimum_wecom_lead_seconds
        ),
    )
    operation.success_receipt()
    raw = (tmp_path / "result.json").read_text()
    receipt = json.loads(raw)
    assert checked == [operator.MIN_WECOM_READY_LEAD_SECONDS]
    assert receipt["future_nonclaimable_wecom_jobs"] == 2
    assert receipt["future_nonclaimable_wecom_sha256"] == "5" * 64
    assert "10000000-0000-4000-8000" not in raw


def test_backup_records_only_safe_preflight_wecom_state(tmp_path: Path) -> None:
    operation = operator.Deployment(Path("/tmp/candidate.json"), manifest())
    operation.backup_dir = tmp_path / "backup"
    env = tmp_path / ".env"
    compose = tmp_path / "compose.yaml"
    env.write_bytes(b"fixture-env")
    compose.write_bytes(b"fixture-compose")
    operation.primary_env = (env.read_bytes(), env.stat())
    operation.compose_snapshot = (compose.read_bytes(), compose.stat())
    operation.future_wecom_count = 2
    operation.future_wecom_sha256 = "5" * 64
    operation.backup()
    raw = (operation.backup_dir / "preflight-state.json").read_text()
    state = json.loads(raw)
    assert state == {
        "future_nonclaimable_wecom_jobs": 2,
        "future_nonclaimable_wecom_sha256": "5" * 64,
        "future_wecom_minimum_lead_seconds": 600,
    }
    assert "10000000-0000-4000-8000" not in raw
    assert (
        stat.S_IMODE((operation.backup_dir / "preflight-state.json").stat().st_mode)
        == 0o600
    )


class Fake(operator.Deployment):
    def __init__(self, tmp_path: Path, failure: str | None = None) -> None:
        self.manifest = manifest()
        self.events: list[str] = []
        self.failure = failure
        self.failed = False
        self.before = {}
        self.backup_dir = tmp_path / "backup"
        for name, body in {
            ".release.env": b"APP_IMAGE=" + operator.PREVIOUS_REF.encode() + b"\n",
            ".release-commit": (operator.PREVIOUS_REVISION + "\n").encode(),
            "RELEASE_COMMIT": (operator.PREVIOUS_REVISION + "\n").encode(),
        }.items():
            path = tmp_path / name
            path.write_bytes(body)
            path.chmod(0o600)
            self.before[name] = (body, path.stat())

    def step(self, name: str) -> None:
        self.events.append(name)
        if self.failure == name and not self.failed:
            self.failed = True
            raise RuntimeError("injected_failure")

    def log(self, phase: str) -> None:
        self.events.append("log:" + phase)

    def preflight(self) -> None:
        self.step("preflight")

    def load_candidate(self) -> None:
        self.step("load")

    def backup(self) -> None:
        self.step("backup")

    def fence(self) -> None:
        self.step("fence")

    def stop(self) -> None:
        self.step("stop")

    def idle(self, *, minimum_wecom_lead_seconds: int = 0) -> None:
        self.step("idle")

    def post_quiescence_fence(self) -> None:
        self.step("post_fence")

    def activate(self) -> None:
        body, details = self.before[".release.env"]
        operator.atomic_restore(
            operator.APP / ".release.env",
            operator.replace_image(body, str(self.manifest["candidate_ref"])),
            details,
        )
        self.step("activate_partial")
        super().activate()

    def start(self, reference: str) -> None:
        self.step("start_old" if reference == operator.PREVIOUS_REF else "start_new")

    def wait_ready(
        self,
        reference: str,
        image_id: str,
        *,
        minimum_wecom_lead_seconds: int = operator.MIN_WECOM_READY_LEAD_SECONDS,
    ) -> None:
        self.step("ready_old" if reference == operator.PREVIOUS_REF else "ready_new")

    def success_receipt(self) -> None:
        self.step("receipt")


@pytest.mark.parametrize("failure", ["preflight", "load", "backup", "fence"])
def test_pre_quiescence_failure_never_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr(operator, "APP", tmp_path)
    operation = Fake(tmp_path, failure)
    with pytest.raises(RuntimeError):
        operator.execute(operation)
    assert "stop" not in operation.events and "start_old" not in operation.events


@pytest.mark.parametrize(
    "failure",
    ["stop", "post_fence", "activate_partial", "start_new", "ready_new", "receipt"],
)
def test_every_post_quiescence_failure_restores_previous_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr(operator, "APP", tmp_path)
    operation = Fake(tmp_path, failure)
    with pytest.raises(RuntimeError, match="injected_failure"):
        operator.execute(operation)
    assert operation.events.count("start_old") == 1
    assert "log:rollback_completed" in operation.events
    for name, (body, details) in operation.before.items():
        assert (tmp_path / name).read_bytes() == body
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == stat.S_IMODE(
            details.st_mode
        )


def test_post_quiescence_fence_runs_before_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(operator, "APP", tmp_path)
    operation = Fake(tmp_path)
    operator.execute(operation)
    assert operation.events.index("post_fence") < operation.events.index(
        "activate_partial"
    )


def test_failed_rollback_readiness_stops_writers_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailedRecovery(Fake):
        def wait_ready(
            self,
            reference: str,
            image_id: str,
            *,
            minimum_wecom_lead_seconds: int = operator.MIN_WECOM_READY_LEAD_SECONDS,
        ) -> None:
            name = "ready_old" if reference == operator.PREVIOUS_REF else "ready_new"
            self.events.append(name)
            raise RuntimeError(name + "_failed")

    monkeypatch.setattr(operator, "APP", tmp_path)
    operation = FailedRecovery(tmp_path)
    with pytest.raises(RuntimeError, match="rollback_incomplete"):
        operator.execute(operation)
    assert operation.events.count("stop") == 3
    assert operation.events[-1] == "stop"
    assert "log:rollback_completed" not in operation.events


def test_start_is_exact_twelve_services_without_dependencies_or_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = operator.Deployment(Path("/tmp/candidate.json"), manifest())
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        operation, "command", lambda args, **kwargs: calls.append((args, kwargs)) or ""
    )
    operation.start(str(manifest()["candidate_ref"]))
    args, _ = calls[0]
    assert len(operator.SERVICES) == len(set(operator.SERVICES)) == 12
    assert set(operator.SERVICES) == set(operator.STOP_ORDER)
    assert all(flag in args for flag in ("--no-build", "--no-deps", "--force-recreate"))
    assert args[args.index("--pull") + 1] == "never"
    assert tuple(args[-12:]) == operator.SERVICES
    assert all(name not in args for name in ("backend-migrate", "postgres", "minio"))


def test_no_execute_validates_archive_but_never_locks_or_deploys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, digest = write_manifest(tmp_path, manifest())
    checked: list[str] = []
    monkeypatch.setattr(
        sys, "argv", ["operator", str(path), "--manifest-sha256", digest]
    )
    monkeypatch.setattr(operator.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        operator.Deployment, "validate_archive", lambda self: checked.append("oci")
    )
    monkeypatch.setattr(operator, "execute", lambda _: pytest.fail("must not deploy"))
    assert operator.main() == 0 and checked == ["oci"]


def test_validator_rejects_duplicate_json_and_unsafe_archive_path(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        validator.strict_json(b'{"a":1,"a":2}', "duplicate")
    unsafe = tmp_path / "unsafe.tar.gz"
    with tarfile_open(unsafe) as bundle:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        bundle.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="archive_member"):
        validator.safe_members(unsafe.absolute())


def overlay_layer(
    *, extra: bool = False, wrong_mode: bool = False, corrupt: bool = False
) -> bytes:
    buffer = io.BytesIO()
    repo = ROOT.parents[3]
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as bundle:
        for index, relative in enumerate(sorted(validator.OVERLAY_FILES)):
            body = (repo / "backend/app" / relative).read_bytes()
            if corrupt and index == 0:
                body += b"\n"
            info = tarfile.TarInfo("app/app/" + relative)
            info.size = len(body)
            info.mode = 0o600 if wrong_mode and index == 0 else 0o644
            info.uid = info.gid = 999
            info.uname = info.gname = "app"
            info.mtime = 0
            bundle.addfile(info, io.BytesIO(body))
        if extra:
            info = tarfile.TarInfo("app/app/domain/unreviewed.py")
            info.size = 1
            info.mode = 0o644
            info.uid = info.gid = 999
            info.uname = info.gname = "app"
            info.mtime = 0
            bundle.addfile(info, io.BytesIO(b"x"))
    return buffer.getvalue()


def test_overlay_layer_is_exactly_the_five_reviewed_files() -> None:
    validator.validate_overlay_layer(overlay_layer())
    for changed in (
        overlay_layer(extra=True),
        overlay_layer(wrong_mode=True),
        overlay_layer(corrupt=True),
    ):
        with pytest.raises(ValueError):
            validator.validate_overlay_layer(changed)


def tarfile_open(path: Path):
    return tarfile.open(path, "w:gz")


def test_operator_has_no_publish_mass_send_upload_or_migration_surface() -> None:
    source = (ROOT / "deploy-no-source-links.py").read_text()
    for forbidden in (
        "freepublish",
        "mass/send",
        "uploadimg",
        "add_material",
        "alembic upgrade",
    ):
        assert forbidden not in source
    assert '"model_calls": 0' in source and '"social_calls": 0' in source
    assert '"--network"' in source and '"none"' in source
