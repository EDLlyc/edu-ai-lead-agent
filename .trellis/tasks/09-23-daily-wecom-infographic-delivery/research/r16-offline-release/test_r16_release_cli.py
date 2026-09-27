from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import r16_release_cli as cli


def _bundle(tmp_path: Path) -> tuple[Path, dict[str, str], str]:
    source = Path(cli.__file__).parent
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    bundle.chmod(0o700)
    manifest: dict[str, str] = {}
    for name, field in (
        ("r16_forward_operator.py", "operator_sha256"),
        ("r16_real_host.py", "real_host_sha256"),
        ("r16_release_cli.py", "release_cli_sha256"),
        ("r16_enablement.py", "enable_operator_sha256"),
        ("r16_enable_host.py", "enable_host_sha256"),
    ):
        shutil.copyfile(source / name, bundle / name)
        manifest[field] = cli.file_sha256(bundle / name)
    (bundle / "backend-image.oci.tar.gz").write_bytes(b"fake-archive")
    host_files = bundle / "host-files"
    host_files.mkdir(mode=0o700)
    for name in cli.HOST_FILE_FILES:
        path = host_files / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    body = json.dumps(manifest, sort_keys=True).encode()
    (bundle / "candidate.json").write_bytes(body)
    (bundle / "candidate.json").chmod(0o600)
    return bundle, manifest, cli.file_sha256(bundle / "candidate.json")


def test_bootstrap_hashes_all_executable_sources_before_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest, manifest_sha = _bundle(tmp_path)
    monkeypatch.setattr(cli, "trusted_path", lambda *_args, **_kwargs: None)
    observed = cli.authenticate_bundle(
        bundle / "r16_release_cli.py",
        bundle,
        bundle / "candidate.json",
        manifest_sha,
        manifest["release_cli_sha256"],
    )
    assert observed == manifest
    (bundle / "r16_real_host.py").write_bytes(b"tampered")
    with pytest.raises(cli.LaunchBlocked, match="source_hash_mismatch"):
        cli.authenticate_bundle(
            bundle / "r16_release_cli.py",
            bundle,
            bundle / "candidate.json",
            manifest_sha,
            manifest["release_cli_sha256"],
        )


def test_enable_sources_are_part_of_same_sealed_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest, manifest_sha = _bundle(tmp_path)
    monkeypatch.setattr(cli, "trusted_path", lambda *_args, **_kwargs: None)
    (bundle / "r16_enable_host.py").write_bytes(b"tampered")
    with pytest.raises(cli.LaunchBlocked, match="source_hash_mismatch"):
        cli.authenticate_bundle(
            bundle / "r16_release_cli.py",
            bundle,
            bundle / "candidate.json",
            manifest_sha,
            manifest["release_cli_sha256"],
        )


def test_independent_manifest_and_launcher_hashes_are_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest, manifest_sha = _bundle(tmp_path)
    monkeypatch.setattr(cli, "trusted_path", lambda *_args, **_kwargs: None)
    with pytest.raises(cli.LaunchBlocked, match="manifest_hash_mismatch"):
        cli.authenticate_bundle(
            bundle / "r16_release_cli.py",
            bundle,
            bundle / "candidate.json",
            "f" * 64,
            manifest["release_cli_sha256"],
        )
    with pytest.raises(cli.LaunchBlocked, match="launcher_hash_mismatch"):
        cli.authenticate_bundle(
            bundle / "r16_release_cli.py",
            bundle,
            bundle / "candidate.json",
            manifest_sha,
            "f" * 64,
        )


def test_private_bundle_and_manifest_modes_are_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest, manifest_sha = _bundle(tmp_path)
    monkeypatch.setattr(cli, "trusted_path", lambda *_args, **_kwargs: None)
    bundle.chmod(0o755)
    with pytest.raises(cli.LaunchBlocked, match="bundle_not_private"):
        cli.authenticate_bundle(
            bundle / "r16_release_cli.py",
            bundle,
            bundle / "candidate.json",
            manifest_sha,
            manifest["release_cli_sha256"],
        )
    bundle.chmod(0o700)
    (bundle / "candidate.json").chmod(0o644)
    with pytest.raises(cli.LaunchBlocked, match="manifest_not_private"):
        cli.authenticate_bundle(
            bundle / "r16_release_cli.py",
            bundle,
            bundle / "candidate.json",
            manifest_sha,
            manifest["release_cli_sha256"],
        )


def test_writable_bundle_ancestor_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(cli.LaunchBlocked, match="path_writable|path_owner_or_link"):
        cli.trusted_path(tmp_path, directory=True)


def test_bootstrap_rejects_duplicate_keys_and_python_decoys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest, _ = _bundle(tmp_path)
    monkeypatch.setattr(cli, "trusted_path", lambda *_args, **_kwargs: None)
    (bundle / "candidate.json").write_bytes(b'{"revision":"a","revision":"b"}')
    with pytest.raises(cli.LaunchBlocked, match="duplicate_manifest_key"):
        cli.authenticate_bundle(
            bundle / "r16_release_cli.py",
            bundle,
            bundle / "candidate.json",
            cli.file_sha256(bundle / "candidate.json"),
            manifest["release_cli_sha256"],
        )
    (bundle / "candidate.json").write_bytes(json.dumps(manifest).encode())
    (bundle / "json.py").write_bytes(b"raise RuntimeError('decoy')")
    with pytest.raises(cli.LaunchBlocked, match="unreviewed_bundle_entry"):
        cli.authenticate_bundle(
            bundle / "r16_release_cli.py",
            bundle,
            bundle / "candidate.json",
            cli.file_sha256(bundle / "candidate.json"),
            manifest["release_cli_sha256"],
        )


def test_nested_host_file_decoy_and_missing_image_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, manifest, manifest_sha = _bundle(tmp_path)
    monkeypatch.setattr(cli, "trusted_path", lambda *_args, **_kwargs: None)
    (bundle / "host-files/extra.py").write_bytes(b"decoy")
    with pytest.raises(cli.LaunchBlocked, match="unreviewed_host_file_entry"):
        cli.authenticate_bundle(
            bundle / "r16_release_cli.py",
            bundle,
            bundle / "candidate.json",
            manifest_sha,
            manifest["release_cli_sha256"],
        )
    (bundle / "host-files/extra.py").unlink()
    (bundle / "backend-image.oci.tar.gz").unlink()
    with pytest.raises(cli.LaunchBlocked):
        cli.authenticate_bundle(
            bundle / "r16_release_cli.py",
            bundle,
            bundle / "candidate.json",
            manifest_sha,
            manifest["release_cli_sha256"],
        )


def test_script_refuses_non_isolated_python_before_imports(tmp_path: Path) -> None:
    bundle, _, _ = _bundle(tmp_path)
    # Use the ordinary interpreter deliberately; the launcher must refuse
    # before importing a sibling package or trying to read any host path.
    result = subprocess.run(
        [sys.executable, str(bundle / "r16_release_cli.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "phase": "blocked",
        "code": "isolated_python_required",
    }


def test_isolated_python_does_not_import_bundle_decoy(tmp_path: Path) -> None:
    bundle, _, _ = _bundle(tmp_path)
    marker = tmp_path / "decoy-ran"
    (bundle / "json.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", str(bundle / "r16_release_cli.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert not marker.exists()


def test_apply_requires_execute_and_full_typed_identity() -> None:
    manifest = {
        "revision": "1" * 40,
        "image": "sha256:" + "2" * 64,
        "trusted_recipient_fingerprint": "3" * 64,
        "base_revision": "4" * 40,
        "schema": "20260926_0050",
    }
    args = argparse.Namespace(
        execute=False,
        confirm_revision=manifest["revision"],
        confirm_image=manifest["image"],
        confirm_recipient_fingerprint=manifest["trusted_recipient_fingerprint"],
        confirm_base_revision=manifest["base_revision"],
        confirm_schema=manifest["schema"],
        confirm_default_off="DEFAULT_OFF_12_SERVICES",
    )
    with pytest.raises(cli.LaunchBlocked, match="explicit_execute_required"):
        cli.confirmations(args, manifest)
    args.execute = True
    cli.confirmations(args, manifest)
    args.confirm_image = "sha256:" + "f" * 64
    with pytest.raises(cli.LaunchBlocked, match="typed_confirmation_mismatch"):
        cli.confirmations(args, manifest)


def test_cli_crash_attempt_refuses_before_bundle_or_host_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    attempt = tmp_path / "r16-forward-crash1"
    attempt.mkdir()
    (attempt / "migration-intent.json").write_bytes(b"{}")
    monkeypatch.setattr(cli, "require_isolated", lambda: None)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "r16_release_cli.py",
            "apply",
            "--bundle",
            "/missing-bundle",
            "--manifest",
            "/missing-bundle/candidate.json",
            "--manifest-sha256",
            "f" * 64,
            "--launcher-sha256",
            "f" * 64,
            "--attempt-dir",
            str(attempt),
            "--execute",
        ],
    )
    assert cli.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "phase": "blocked",
        "code": "attempt_exists_reconcile_only",
    }
