"""Can Qwen3-VL text-to-image similarity tell which action image carries the right prop?

Uses the prop labels of the 26 action images as ground truth. For each plan subject, the
relevant set is every image whose prop the subject allows; the wrong set is every image
whose prop the subject forbids (pose-only images are neither). Metrics per query style:

- MRR of the first relevant image among the 26 action images,
- wrong@3: share of the top three that carry a forbidden prop,
- AUC: probability that a random relevant image outranks a random wrong-prop image.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
from app.application.services.visual_retrieval import VisualRetrievalService
from app.core.config import Settings
from app.domain.visual_retrieval import canonical_visual_query
from app.infrastructure.ai.visual_embedding import AlibabaVisualEmbeddingAdapter
from app.infrastructure.brand.visual_catalog import load_visual_catalog
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.visual_retrieval import PostgresVisualIndexRepository

from evals.visual_replay.scores_cache import ScoreCache

SUBJECT_TEXT: dict[str, tuple[str, str]] = {
    "robot_arm": ("小赛和赛先生在操作一台机械臂", "cartoon owls operating a robotic arm"),
    "ai_sensor_console": (
        "小赛和赛先生在人工智能传感器控制台前操作",
        "cartoon owls working at an AI sensor console",
    ),
    "competition_prototype": (
        "小赛和赛先生展示科技竞赛的原型作品",
        "cartoon owls presenting a science competition prototype",
    ),
    "telescope_star_map": (
        "小赛和赛先生用望远镜观察星空和星图",
        "cartoon owls looking through a telescope at the stars",
    ),
    "rocket_satellite_model": (
        "小赛和赛先生和火箭卫星模型，太空探索",
        "cartoon owls with a rocket and satellite model, space exploration",
    ),
    "microscope_sample": (
        "小赛和赛先生用显微镜观察样本",
        "cartoon owls examining a sample under a microscope",
    ),
    "experiment_apparatus": (
        "小赛和赛先生在做科学实验，使用实验器材",
        "cartoon owls doing a science experiment with lab apparatus",
    ),
    "science_book_model": (
        "小赛和赛先生在读科普书籍",
        "cartoon owls reading popular science books",
    ),
}
SUBJECT_CATEGORY = {
    "robot_arm": "robotics",
    "ai_sensor_console": "ai",
    "competition_prototype": "ai",
    "telescope_star_map": "astronomy",
    "rocket_satellite_model": "astronomy",
    "microscope_sample": "experiment",
    "experiment_apparatus": "science",
    "science_book_model": "science",
}


def production_style(subject: str) -> str:
    """The JSON shape production sends, reduced to the subject-bearing fields."""
    return canonical_visual_query({"category": SUBJECT_CATEGORY[subject], "subject": subject})


STYLES: dict[str, Callable[[str], str]] = {
    "production_json": production_style,
    "sentence_zh": lambda subject: SUBJECT_TEXT[subject][0],
    "sentence_en": lambda subject: SUBJECT_TEXT[subject][1],
}


def evaluate_subject(
    subject: str,
    scores: dict[str, float],
    labels: dict[str, Any],
) -> dict[str, Any]:
    allowed = set(labels["compatible_props"][subject])
    assets = labels["assets"]
    ranked = sorted(assets, key=lambda asset_id: (-scores[asset_id], asset_id))
    relevant = [a for a in ranked if assets[a]["prop"] in allowed]
    wrong = [a for a in ranked if assets[a]["prop"] not in allowed | {"none"}]
    first = next((index for index, a in enumerate(ranked, start=1) if a in relevant), None)
    pairs = [(r, w) for r in relevant for w in wrong]
    auc = (
        sum(
            1.0 if scores[r] > scores[w] else 0.5 if scores[r] == scores[w] else 0.0
            for r, w in pairs
        )
        / len(pairs)
        if pairs
        else None
    )
    top3 = ranked[:3]
    return {
        "subject": subject,
        "relevant": len(relevant),
        "reciprocal_rank": 1 / first if first else 0.0,
        "first_relevant_rank": first,
        "wrong_at_3": sum(1 for a in top3 if a in wrong) / 3,
        "auc": auc,
        "top3_props": [assets[a]["prop"] for a in top3],
        "score_range": [min(scores[a] for a in ranked), max(scores[a] for a in ranked)],
    }


def render(results: dict[str, list[dict[str, Any]]], *, calls: int) -> str:
    lines = [
        "# Subject retrieval — can text-to-image similarity find the right prop?",
        "",
        "- Ground truth: prop labels of the 26 action images (drafted by Claude from visual "
        "inspection, pending owner confirmation) and the subject → allowed-prop table.",
        f"- Provider calls: {calls}. One query per subject and style; single trial.",
        "",
        "| style | mean RR | mean wrong@3 | mean AUC (right vs wrong prop) |",
        "|---|---|---|---|",
    ]
    for style, rows in results.items():
        aucs = [row["auc"] for row in rows if row["auc"] is not None]
        lines.append(
            f"| {style} | {sum(r['reciprocal_rank'] for r in rows) / len(rows):.2f} | "
            f"{sum(r['wrong_at_3'] for r in rows) / len(rows):.2f} | "
            f"{sum(aucs) / len(aucs):.2f} |"
        )
    lines += ["", "## Per subject", ""]
    for style, rows in results.items():
        lines += [
            f"### {style}",
            "",
            "| subject | relevant | first relevant rank | wrong@3 | AUC | top-3 props "
            "| score range |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            auc = f"{row['auc']:.2f}" if row["auc"] is not None else "–"
            low, high = row["score_range"]
            lines.append(
                f"| {row['subject']} | {row['relevant']} | {row['first_relevant_rank']} | "
                f"{row['wrong_at_3']:.2f} | {auc} | {', '.join(row['top3_props'])} | "
                f"{low:.3f}–{high:.3f} |"
            )
        lines.append("")
    return "\n".join(lines)


async def collect(
    settings: Settings, cache: ScoreCache, queries: Sequence[str]
) -> dict[str, dict[str, float]]:
    endpoint = settings.visual_embedding_endpoint
    api_key = settings.visual_embedding_api_key
    if endpoint is None or api_key is None:
        raise SystemExit("visual embedding secrets are unavailable")
    loaded = load_visual_catalog(settings.image_asset_manifest)
    engine = create_engine(settings)
    client = httpx.AsyncClient(follow_redirects=False)
    try:
        service = VisualRetrievalService(
            embeddings=AlibabaVisualEmbeddingAdapter(
                client=client,
                endpoint=endpoint,
                api_key=api_key,
                timeout_seconds=settings.visual_embedding_timeout_seconds,
                concurrency=1,
            ),
            repository=PostgresVisualIndexRepository(create_session_factory(engine)),
            identity=settings.visual_embedding_identity,
        )
        return {query: await cache.scores(service, loaded.catalog, query) for query in queries}
    finally:
        await client.aclose()
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--env-file", default="/root/projects/edu-ai-lead-agent/.env")
    args = parser.parse_args(argv)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    settings = Settings(_env_file=args.env_file, visual_semantic_enabled=False)
    cache = ScoreCache(Path(args.cache_dir), identity_key="qwen3-vl-embedding-2048-v2")
    queries = {
        (style, subject): build(subject)
        for style, build in STYLES.items()
        for subject in SUBJECT_TEXT
    }
    maps = asyncio.run(collect(settings, cache, list(queries.values())))
    cache.save()
    results: dict[str, list[dict[str, Any]]] = {}
    for (style, subject), query in queries.items():
        results.setdefault(style, []).append(evaluate_subject(subject, maps[query], labels))
    Path(args.output).write_text(render(results, calls=cache.misses), encoding="utf-8")
    print(json.dumps({"calls": cache.misses, "cached": cache.hits, "output": args.output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
