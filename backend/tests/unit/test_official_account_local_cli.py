from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.official_account_local_cli import (
    _export_fixture_review_bundle,
    _parser,
    _resolve_local_manifest_path,
)


def test_live_local_export_flag_is_explicit_and_cli_only() -> None:
    run_id = uuid4()
    default = _parser().parse_args(["export", "--run-id", str(run_id)])
    explicit = _parser().parse_args(
        ["export", "--run-id", str(run_id), "--allow-live-local-export"]
    )

    assert default.allow_live_local_export is False
    assert explicit.allow_live_local_export is True


def test_cli_resolves_existing_repository_relative_catalog_manifest() -> None:
    resolved = _resolve_local_manifest_path("private/brand-materials/visual-assets.manifest.json")

    assert resolved is not None
    assert resolved.endswith("private/brand-materials/visual-assets.manifest.json")


@pytest.mark.asyncio
async def test_cli_default_rejects_live_before_any_media_or_provider_access() -> None:
    class Repository:
        async def get_run(self, _run_id: object) -> object:
            return SimpleNamespace(fixture_id=None)

    with pytest.raises(ValueError, match="sanitized fixture"):
        await _export_fixture_review_bundle(
            Repository(),  # type: ignore[arg-type]
            run_id=uuid4(),
            output_directory=SimpleNamespace(),  # type: ignore[arg-type]
            mode="review",
            session_factory=SimpleNamespace(),  # type: ignore[arg-type]
            settings=SimpleNamespace(),  # type: ignore[arg-type]
        )
