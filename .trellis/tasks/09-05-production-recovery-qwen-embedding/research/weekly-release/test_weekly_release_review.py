"""Independent failure injection against the real transaction and file fingerprints."""

from __future__ import annotations

import copy
import json
import os

import pytest
from test_weekly_release import R
from test_weekly_release import activation_fixture as activation_fixture
from test_weekly_release import lib as lib


@pytest.mark.parametrize("ordinal", range(1, 13))
@pytest.mark.parametrize("after", [False, True])
def test_every_source_rename_boundary_recovers_real_metadata(
    activation_fixture, monkeypatch, ordinal, after
):
    operation, _events, app, _work = activation_fixture
    rename = os.rename
    count = 0
    fired = False

    def fail_one(source, destination):
        nonlocal count, fired
        count += 1
        if count == ordinal and not fired:
            fired = True
            if after:
                rename(source, destination)
            raise OSError("injected_rename_boundary")
        return rename(source, destination)

    monkeypatch.setattr(R.os, "rename", fail_one)
    with pytest.raises(OSError, match="injected_rename_boundary"):
        operation.execute("c" * 64)
    assert fired and operation.armed
    operation.restore()
    assert R.current_source(operation.lib) == operation.state["source"]
    assert R.protected_state(operation.lib) == operation.state["protected"]
    assert (app / ".env").stat().st_uid == 1000
    assert (app / ".env").stat().st_gid == 1001


@pytest.mark.parametrize("target", [".release-commit", "RELEASE_COMMIT", ".release.env"])
@pytest.mark.parametrize("after", [False, True])
def test_each_protected_replace_failure_restores_exact_snapshot(
    activation_fixture, monkeypatch, target, after
):
    operation, _events, app, _work = activation_fixture
    replace = os.replace
    fired = False

    def fail_one(source, destination):
        nonlocal fired
        if not fired and destination == app / target:
            fired = True
            if after:
                replace(source, destination)
            raise OSError("injected_replace_boundary")
        return replace(source, destination)

    monkeypatch.setattr(R.os, "replace", fail_one)
    with pytest.raises(OSError, match="injected_replace_boundary"):
        operation.execute("c" * 64)
    operation.restore()
    assert R.current_source(operation.lib) == operation.state["source"]
    assert R.protected_state(operation.lib) == operation.state["protected"]
    assert list(app.glob(".weekly-release-*")) == []


@pytest.mark.parametrize(
    "fault,code",
    [
        (None, None),
        ("health_service", "api_health_contract_drift"),
        ("health_environment", "api_health_contract_drift"),
        ("public_port", "api_port_binding_drift"),
        ("digest", "readiness_digest_drift"),
        ("one_app", "service_image_drift"),
    ],
)
def test_real_readiness_binds_health_ports_and_one_observed_id(monkeypatch, lib, fault, code):
    candidate_id = "sha256:" + "a" * 64
    names = sorted((*lib.APP_SERVICES, "postgres", "minio"))
    health = {
        "service": "wrong" if fault == "health_service" else "edu-ai-lead-agent-api",
        "status": "ok",
        "environment": "development" if fault == "health_environment" else "production",
        "timezone": "Asia/Shanghai",
    }

    def compose(*argv, **kwargs):
        assert kwargs == {}
        if argv == ("ps", "--services", "--status", "running"):
            return "\n".join(names).encode()
        assert len(argv) == 3 and argv[:2] == ("ps", "-q") and argv[2] in names
        return (argv[2] + "-container").encode()

    def docker(*argv, **kwargs):
        assert kwargs == {} and len(argv) == 2 and argv[0] == "inspect"
        name = argv[1].removesuffix("-container")
        assert name in names
        value = {
            "Image": (
                "sha256:" + "b" * 64
                if fault == "one_app" and name == "content-worker"
                else candidate_id
            ),
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
            "RestartCount": 0,
            "NetworkSettings": {
                "Ports": {
                    "8000/tcp": [
                        {
                            "HostIp": "0.0.0.0" if fault == "public_port" else "127.0.0.1",
                            "HostPort": "8000",
                        }
                    ]
                }
            },
        }
        return json.dumps([value]).encode()

    monkeypatch.setattr(R, "compose", compose)
    monkeypatch.setattr(R, "docker", docker)
    monkeypatch.setattr(R, "run", lambda *args, **kwargs: json.dumps(health).encode())
    monkeypatch.setattr(
        R,
        "inspect_image",
        lambda _: {
            "Id": "sha256:" + "b" * 64 if fault == "digest" else candidate_id,
        },
    )
    if code:
        with pytest.raises(R.ReleaseError, match=code):
            R.services(lib, "candidate@" + candidate_id, pinned_image_id=candidate_id)
    else:
        result = R.services(lib, "candidate@" + candidate_id, pinned_image_id=candidate_id)
        assert len(result) == 14
        assert result["postgres"]["container_id"] == "postgres-container"
        assert result["minio"]["container_id"] == "minio-container"


def test_candidate_start_cannot_recreate_database_container(activation_fixture, monkeypatch):
    operation, _events, _app, _work = activation_fixture
    previous = R.services

    def services(lib, image, **kwargs):
        result = copy.deepcopy(previous(lib, image, **kwargs))
        if image == operation.metadata["candidate_reference"]:
            result["postgres"]["container_id"] = "changed-container"
        return result

    monkeypatch.setattr(R, "services", services)
    with pytest.raises(R.ReleaseError, match="infrastructure_identity_drift"):
        operation.execute("c" * 64)
    assert not (operation.work / "success.json").exists()
