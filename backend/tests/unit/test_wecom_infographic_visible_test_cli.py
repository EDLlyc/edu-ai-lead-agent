"""No provider calls: explicit operator CLI and preview-file safeguards."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.wecom_infographic_test_main import _parser, _write_preview
from pydantic import ValidationError


def test_visible_test_is_default_off_and_cannot_use_an_unconfigured_target() -> None:
    assert not Settings(_env_file=None).wecom_infographic_test_enabled
    with pytest.raises(ValidationError, match="automatic group-webhook slot delivery"):
        Settings(_env_file=None, wecom_infographic_test_enabled=True)


def test_queue_requires_execute_and_exact_approval_inputs() -> None:
    parser = _parser()
    run_id = str(uuid4())
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "queue",
                "--test-run-id",
                run_id,
                "--expect-target-fingerprint",
                "a" * 64,
                "--approve-artifact-sha256",
                "b" * 64,
            ]
        )
    args = parser.parse_args(
        [
            "queue",
            "--test-run-id",
            run_id,
            "--expect-target-fingerprint",
            "a" * 64,
            "--approve-artifact-sha256",
            "b" * 64,
            "--execute",
        ]
    )
    assert args.execute and str(args.test_run_id) == run_id


def test_preview_is_fresh_private_and_never_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "review.jpg"
    _write_preview(output, b"synthetic-test-jpeg")
    assert output.read_bytes() == b"synthetic-test-jpeg"
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="fresh absolute"):
        _write_preview(output, b"replay")
    assert output.read_bytes() == b"synthetic-test-jpeg"
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        _write_preview(linked / "replay.jpg", b"replay")
