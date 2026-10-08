"""Local rehearsal of the Qwen3-VL in-tier rollout through production's own code path.

Uses the settings of the process (run it with the production values: BRAND_EMBEDDING_PROVIDER_MODE
=zhipu, IMAGE_DIVERSITY_ENABLED=true, selector v3, VISUAL_SEMANTIC_ENABLED=true, alibaba visual
embeddings, IMAGE_ASSET_MANIFEST = a copy of the production catalog) and checks:

1. configuration: brand retrieval stays on the brand provider; the visual index is complete for
   the catalog;
2. rankings: `material_package._resolve_subject_rankings` (the function the content worker calls)
   returns `ready` for every category, with its latency and call count;
3. selection: every production brief replayed with those live rankings picks its action image
   with "semantic in-tier order", and the picks match the offline re-check (cached scores);
4. failure drill: a provider with a wrong key gives `semantic_unavailable` and the selector falls
   back to the rule order.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from app.application.services.material_package import _resolve_subject_rankings
from app.application.services.visual_retrieval import VisualRetrievalService
from app.core.config import get_settings
from app.domain.visual_brief import VisualCategory
from app.domain.visual_diversity import ControlledVisualPlan
from app.infrastructure.ai.visual_embedding import AlibabaVisualEmbeddingAdapter
from app.infrastructure.brand.visual_catalog import load_visual_catalog
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.visual_retrieval import PostgresVisualIndexRepository
from pydantic import SecretStr

from evals.visual_replay.plan_sim import simulate, stats
from evals.visual_replay.runner import Brief, load_briefs


def _service(settings: Any, client: httpx.AsyncClient, engine: Any, *, api_key: SecretStr) -> Any:
    return VisualRetrievalService(
        embeddings=AlibabaVisualEmbeddingAdapter(
            client=client,
            endpoint=settings.visual_embedding_endpoint,
            api_key=api_key,
            timeout_seconds=settings.visual_embedding_timeout_seconds,
            concurrency=settings.visual_embedding_concurrency,
        ),
        repository=PostgresVisualIndexRepository(create_session_factory(engine)),
        identity=settings.visual_embedding_identity,
    )


async def _rehearse(briefs: Sequence[Brief]) -> dict[str, Any]:
    settings = get_settings()
    loaded = load_visual_catalog(settings.image_asset_manifest)
    report: dict[str, Any] = {
        "brand_embedding_provider": settings.resolved_brand_embedding_provider_mode,
        "brand_embedding_model": settings.brand_embedding_model,
        "visual_semantic_enabled": settings.visual_semantic_enabled,
        "selector": settings.image_diversity_selector_version,
        "catalog_assets": len(loaded.catalog.assets),
    }
    engine = create_engine(settings)
    client = httpx.AsyncClient(follow_redirects=False)
    try:
        if settings.visual_embedding_api_key is None or settings.visual_embedding_endpoint is None:
            raise SystemExit("visual embedding secrets are unavailable")
        service = _service(settings, client, engine, api_key=settings.visual_embedding_api_key)
        rankings: dict[str, Mapping[Any, Any]] = {}
        categories: dict[str, Any] = {}
        for category in sorted({brief.category for brief in briefs}):
            started = time.monotonic()
            ranked, meta = await _resolve_subject_rankings(
                enabled=True,
                service=service,
                loaded_catalog=loaded,
                brief=SimpleNamespace(category=VisualCategory(category)),  # type: ignore[arg-type]
            )
            categories[category] = {
                **meta,
                "subjects": len(ranked),
                "seconds": round(time.monotonic() - started, 2),
            }
            rankings[category] = ranked
        report["categories"] = categories

        def live(brief: Brief, plan: ControlledVisualPlan) -> Mapping[str, float] | None:
            ranking = rankings.get(brief.category, {}).get(plan.subject)
            return ranking.score_map if ranking is not None else None

        result = simulate(briefs, loaded, "pool_aware", semantic=live)
        report["selection"] = {
            **stats(result.picks),
            "semantic_in_tier": sum(pick["semantic"] for pick in result.picks),
            "errors": result.errors,
        }
        report["picks"] = [{"brief": p["brief"], "action_id": p["action_id"]} for p in result.picks]

        broken = _service(settings, client, engine, api_key=SecretStr("sk-invalid-rehearsal"))
        ranked, meta = await _resolve_subject_rankings(
            enabled=True,
            service=broken,
            loaded_catalog=loaded,
            brief=SimpleNamespace(category=VisualCategory(briefs[0].category)),  # type: ignore[arg-type]
        )
        fallback = simulate(briefs[:20], loaded, "pool_aware", semantic=lambda b, p: None)
        report["failure_drill"] = {
            **meta,
            "rankings": len(ranked),
            "fallback_picks": len(fallback.picks),
            "fallback_semantic": sum(p["semantic"] for p in fallback.picks),
            "fallback_errors": fallback.errors,
        }
    finally:
        await client.aclose()
        await engine.dispose()
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--briefs", required=True)
    parser.add_argument("--headlines", required=True)
    parser.add_argument("--recheck-picks", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    briefs = load_briefs(Path(args.briefs), Path(args.headlines))
    report = asyncio.run(_rehearse(briefs))
    if args.recheck_picks:
        offline = json.loads(args.recheck_picks.read_text(encoding="utf-8"))["semantic"]
        offline_by = {p["brief"]: p["action_id"] for p in offline}
        same = sum(1 for p in report["picks"] if offline_by.get(p["brief"]) == p["action_id"])
        report["matches_offline_recheck"] = f"{same}/{len(report['picks'])}"
    picks = report.pop("picks")
    args.output.write_text(json.dumps({**report, "picks": picks}, ensure_ascii=False, indent=1))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
