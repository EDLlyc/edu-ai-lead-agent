"""Pure, versioned selection policy for fused brand-retrieval candidates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.domain.brand_knowledge import (
    LEGACY_BRAND_RETRIEVAL_VERSION,
    STRUCTURED_BRAND_RETRIEVAL_VERSION,
    BrandRetrievalHit,
)


@dataclass(frozen=True, slots=True)
class RankedBrandHit:
    hit: BrandRetrievalHit
    ordinal: int


def select_diverse_brand_hits(
    candidates: Sequence[RankedBrandHit],
    *,
    limit: int,
    retrieval_version: str = STRUCTURED_BRAND_RETRIEVAL_VERSION,
) -> tuple[BrandRetrievalHit, ...]:
    """Keep fused order while preferring candidates from different brand sections."""

    if retrieval_version == LEGACY_BRAND_RETRIEVAL_VERSION:
        return _select_legacy_diverse_brand_hits(candidates, limit=limit)
    if retrieval_version != STRUCTURED_BRAND_RETRIEVAL_VERSION:
        raise ValueError("unsupported brand retrieval version")
    if limit < 1:
        return ()
    ordered = _ordered_candidates(candidates)
    document_cap = max(1, min(2, (limit + 1) // 2))
    selected: list[RankedBrandHit] = []
    selected_ids: set[UUID] = set()

    def parent_key(candidate: RankedBrandHit) -> tuple[object, ...]:
        if candidate.hit.section_id is not None:
            return ("section", candidate.hit.section_id)
        # Historical rows intentionally have no synthetic parent. Treat each as independent.
        return ("historical", candidate.hit.version_id, candidate.ordinal)

    def add_candidates(
        *,
        max_per_document: int | None,
        max_per_parent: int | None,
        avoid_duplicate_text: bool,
    ) -> None:
        document_counts: dict[UUID, int] = {}
        parent_counts: dict[tuple[object, ...], int] = {}
        for candidate in selected:
            document_counts[candidate.hit.document_id] = (
                document_counts.get(candidate.hit.document_id, 0) + 1
            )
            key = parent_key(candidate)
            parent_counts[key] = parent_counts.get(key, 0) + 1
        for candidate in ordered:
            if len(selected) >= limit:
                return
            hit = candidate.hit
            if hit.chunk_id in selected_ids:
                continue
            if (
                max_per_document is not None
                and document_counts.get(hit.document_id, 0) >= max_per_document
            ):
                continue
            if avoid_duplicate_text and any(existing.hit.text == hit.text for existing in selected):
                continue
            key = parent_key(candidate)
            if max_per_parent is not None and parent_counts.get(key, 0) >= max_per_parent:
                continue
            selected.append(candidate)
            selected_ids.add(hit.chunk_id)
            document_counts[hit.document_id] = document_counts.get(hit.document_id, 0) + 1
            parent_counts[key] = parent_counts.get(key, 0) + 1

    # The first pass is intentionally conservative. Later passes are deterministic fallbacks
    # for a corpus with one document, one section, or repeated OCR output.
    add_candidates(
        max_per_document=document_cap,
        max_per_parent=1,
        avoid_duplicate_text=True,
    )
    add_candidates(max_per_document=None, max_per_parent=1, avoid_duplicate_text=True)
    add_candidates(
        max_per_document=document_cap,
        max_per_parent=2,
        avoid_duplicate_text=True,
    )
    add_candidates(max_per_document=None, max_per_parent=2, avoid_duplicate_text=True)
    add_candidates(max_per_document=None, max_per_parent=None, avoid_duplicate_text=False)

    rank_by_chunk_id = {candidate.hit.chunk_id: rank for rank, candidate in enumerate(ordered)}
    selected.sort(key=lambda candidate: rank_by_chunk_id[candidate.hit.chunk_id])
    return tuple(candidate.hit for candidate in selected)


def _select_legacy_diverse_brand_hits(
    candidates: Sequence[RankedBrandHit], *, limit: int
) -> tuple[BrandRetrievalHit, ...]:
    """Frozen v2 selector: document cap, adjacent-ordinal avoidance, then fallback."""

    if limit < 1:
        return ()
    ordered = _ordered_candidates(candidates)
    document_cap = max(1, min(2, (limit + 1) // 2))
    selected: list[RankedBrandHit] = []
    selected_ids: set[UUID] = set()

    def add_candidates(
        *,
        max_per_document: int | None,
        avoid_adjacent: bool,
        avoid_duplicate_text: bool,
    ) -> None:
        document_counts: dict[UUID, int] = {}
        for candidate in selected:
            document_counts[candidate.hit.document_id] = (
                document_counts.get(candidate.hit.document_id, 0) + 1
            )
        for candidate in ordered:
            if len(selected) >= limit:
                return
            hit = candidate.hit
            if hit.chunk_id in selected_ids:
                continue
            if (
                max_per_document is not None
                and document_counts.get(hit.document_id, 0) >= max_per_document
            ):
                continue
            if avoid_duplicate_text and any(existing.hit.text == hit.text for existing in selected):
                continue
            if avoid_adjacent and any(
                existing.hit.document_id == hit.document_id
                and existing.hit.version_id == hit.version_id
                and abs(existing.ordinal - candidate.ordinal) <= 1
                for existing in selected
            ):
                continue
            selected.append(candidate)
            selected_ids.add(hit.chunk_id)
            document_counts[hit.document_id] = document_counts.get(hit.document_id, 0) + 1

    add_candidates(
        max_per_document=document_cap,
        avoid_adjacent=True,
        avoid_duplicate_text=True,
    )
    add_candidates(
        max_per_document=document_cap,
        avoid_adjacent=False,
        avoid_duplicate_text=True,
    )
    add_candidates(max_per_document=None, avoid_adjacent=False, avoid_duplicate_text=False)

    rank_by_chunk_id = {candidate.hit.chunk_id: rank for rank, candidate in enumerate(ordered)}
    selected.sort(key=lambda candidate: rank_by_chunk_id[candidate.hit.chunk_id])
    return tuple(candidate.hit for candidate in selected)


def _ordered_candidates(candidates: Sequence[RankedBrandHit]) -> list[RankedBrandHit]:
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.hit.fused_score,
            -candidate.hit.vector_score,
            -candidate.hit.full_text_score,
            str(candidate.hit.chunk_id),
        ),
    )
