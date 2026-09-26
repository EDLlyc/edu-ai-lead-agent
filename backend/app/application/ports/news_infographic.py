"""Read-only source and frozen-input ports for a local infographic run."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.domain.news_infographic import ValidatedInfographicInput


class NewsInfographicPackageSource(Protocol):
    async def load(
        self, package_ids: tuple[UUID, ...], *, api_base_url: str
    ) -> tuple[ValidatedInfographicInput, ...]: ...


class NewsInfographicInputStore(Protocol):
    def read(self, path: Path) -> tuple[ValidatedInfographicInput, ...]: ...

    def write(self, path: Path, cases: tuple[ValidatedInfographicInput, ...]) -> None: ...
