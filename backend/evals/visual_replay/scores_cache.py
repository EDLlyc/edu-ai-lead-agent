"""Disk cache of complete semantic score maps, keyed by the exact query text.

Replays re-run many times while a selector is tuned; the provider is called once per distinct
query and identity. The cache stores cosine scores per asset id only (no vectors, no text).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.application.services.visual_retrieval import VisualRetrievalService
from app.domain.visual_assets import VisualAssetCatalog


class ScoreCache:
    def __init__(self, directory: Path, *, identity_key: str) -> None:
        self._path = directory / f"scores-{identity_key}.json"
        self._scores: dict[str, dict[str, float]] = (
            json.loads(self._path.read_text(encoding="utf-8")) if self._path.exists() else {}
        )
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(query: str) -> str:
        return hashlib.sha256(query.encode("utf-8")).hexdigest()

    async def scores(
        self, service: VisualRetrievalService, catalog: VisualAssetCatalog, query: str
    ) -> dict[str, float]:
        key = self._key(query)
        cached = self._scores.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        ranking = await service.search_text(text=query, catalog=catalog)
        if not ranking.complete or ranking.catalog_version != catalog.catalog_version:
            raise RuntimeError("local visual index is incomplete for the current catalog")
        self.misses += 1
        self._scores[key] = ranking.score_map
        return ranking.score_map

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._scores), encoding="utf-8")
