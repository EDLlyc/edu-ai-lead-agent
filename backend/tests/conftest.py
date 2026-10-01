"""Shared pytest hooks.

`@pytest.mark.local_artifacts(*paths)` marks a test that needs files kept out of git on purpose:
private brand assets (private/brand-materials/...) or outputs of earlier generation runs
(output/...). Paths are relative to the repository root. When one is missing the test is skipped
with the missing paths in the reason, instead of failing in every clean checkout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    for item in items:
        marker = item.get_closest_marker("local_artifacts")
        if marker is None:
            continue
        missing = [path for path in marker.args if not (REPOSITORY_ROOT / path).exists()]
        if missing:
            item.add_marker(
                pytest.mark.skip(reason="needs local artifacts not in git: " + ", ".join(missing))
            )
