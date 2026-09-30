"""Offline replay of production visual briefs through the semantic asset selector.

Inputs are two read-only production exports (briefs with the references the rule
selector actually used, and the run headlines). The replay computes, on the local
visual index, what the semantic selector would have picked under three query
variants, writes aggregate statistics, and renders a blinded side-by-side page so a
human can judge which reference set fits better. Private brand images are embedded
only in the local HTML; asset names never appear in the report.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import random
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from io import BytesIO
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
from app.application.ports.visual_retrieval import VisualEmbeddingModel
from app.application.services.visual_retrieval import VisualRetrievalService
from app.core.config import Settings
from app.domain.visual_assets import (
    AssetSelectionRequest,
    VisualAssetRole,
    VisualAssetSelection,
)
from app.domain.visual_brief import DEFAULT_CHARACTERS
from app.domain.visual_diversity import VISUAL_SELECTOR_V2_VERSION, ControlledVisualPlan
from app.domain.visual_retrieval import VISUAL_SELECTOR_VERSION as VISUAL_SEMANTIC_SELECTOR_VERSION
from app.domain.visual_retrieval import (
    VisualEmbeddingRequest,
    VisualEmbeddingResult,
    VisualSemanticRanking,
    canonical_visual_query,
)
from app.infrastructure.ai.visual_embedding import AlibabaVisualEmbeddingAdapter
from app.infrastructure.brand.visual_catalog import (
    LoadedVisualCatalog,
    load_visual_catalog,
    read_visual_asset_bytes,
    select_visual_assets,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.visual_retrieval import PostgresVisualIndexRepository
from PIL import Image

ARMS = ("production_rule", "rule_replay", "semantic_brief", "semantic_plan", "semantic_headline")
REPLAY_ARMS = ARMS[1:]
SEMANTIC_ARMS = ARMS[2:]
CATEGORY_LABELS = {
    "ai": "人工智能",
    "science": "科学探索",
    "robotics": "具身智能",
    "astronomy": "探索宇宙",
    "experiment": "科学实验",
    "reading": "科学阅读",
}
ACTION = VisualAssetRole.ACTION_REFERENCE.value
IDENTITY = VisualAssetRole.IDENTITY_REFERENCE.value


class BudgetExhaustedError(RuntimeError):
    pass


class BudgetedEmbeddings(VisualEmbeddingModel):
    """Count provider calls, enforce a hard cap and sum the safe usage numbers."""

    def __init__(self, inner: VisualEmbeddingModel, *, max_calls: int) -> None:
        self._inner = inner
        self._max_calls = max_calls
        self.calls = 0
        self.input_tokens = 0
        self.image_tokens = 0

    async def embed_visual(self, request: VisualEmbeddingRequest) -> VisualEmbeddingResult:
        if self.calls >= self._max_calls:
            raise BudgetExhaustedError(f"embedding call cap {self._max_calls} reached")
        self.calls += 1
        result = await self._inner.embed_visual(request)
        self.input_tokens += result.input_tokens
        self.image_tokens += result.image_tokens
        return result


@dataclass(frozen=True, slots=True)
class Brief:
    artifact_id: str
    run_id: str
    created_at: str
    business_date: date
    status: str
    category: str
    title: str
    asset_tags: tuple[str, ...]
    learning_goal: str
    scene: str
    main_action: str
    reference_roles: tuple[str, ...]
    plan: ControlledVisualPlan
    headline: str
    production_refs: tuple[dict[str, Any], ...]


@dataclass(slots=True)
class ArmPick:
    refs: tuple[dict[str, Any], ...]
    query: str | None = None
    fallback: bool = False
    similarity: float | None = None
    error: str | None = None


@dataclass(slots=True)
class ReplayRow:
    brief: Brief
    picks: dict[str, ArmPick] = field(default_factory=dict)


def load_briefs(briefs_path: Path, headlines_path: Path) -> list[Brief]:
    raw_briefs = json.loads(briefs_path.read_text(encoding="utf-8"))
    raw_runs = json.loads(headlines_path.read_text(encoding="utf-8"))
    runs = {row["run_id"]: row for row in raw_runs}
    briefs: list[Brief] = []
    for row in raw_briefs:
        snapshot = row["visual_brief_snapshot"]
        run = runs.get(row["run_id"])
        if run is None:
            raise ValueError(f"headline export lacks run {row['run_id']}")
        final_ordinal = row.get("final_plan_ordinal") or 1
        refs = tuple(
            ref
            for ref in row["refs"]
            if ref["attempt_ordinal"] == final_ordinal and ref["role"] != "style_reference"
        )
        if not refs:
            refs = tuple(ref for ref in row["refs"] if ref["attempt_ordinal"] == 1)
        briefs.append(
            Brief(
                artifact_id=row["id"],
                run_id=row["run_id"],
                created_at=row["created_at"],
                business_date=date.fromisoformat(run["business_date"]),
                status=row["status"],
                category=snapshot["category"],
                title=snapshot["text_layer"]["title"],
                asset_tags=tuple(snapshot["asset_tags"]),
                learning_goal=snapshot["learning_goal"],
                scene=snapshot["scene"],
                main_action=snapshot["main_action"],
                reference_roles=tuple(snapshot["reference_roles"]),
                plan=ControlledVisualPlan.from_metadata(snapshot["controlled_plan"]),
                headline=run["headline"],
                production_refs=refs,
            )
        )
    briefs.sort(key=lambda item: item.created_at)
    return briefs


def brief_query(brief: Brief) -> str:
    """Exactly what production sends today (material_package._visual_query_for_brief)."""
    return canonical_visual_query(
        {
            "category": brief.category,
            "title": brief.title,
            "learning_goal": brief.learning_goal,
            "scene": brief.scene,
            "main_action": brief.main_action,
            "characters": list(DEFAULT_CHARACTERS),
            "asset_tags": list(brief.asset_tags),
        }
    )


def plan_query(brief: Brief) -> str:
    """Brief plus the per-post controlled plan (fields the canonicaliser already allows)."""
    plan = brief.plan
    return canonical_visual_query(
        {
            "category": brief.category,
            "title": brief.title,
            "learning_goal": brief.learning_goal,
            "scene": plan.scene.value,
            "main_action": brief.main_action,
            "characters": list(plan.characters),
            "subject": plan.subject.value,
            "cast": plan.cast.value,
            "composition": plan.composition.value,
            "camera": plan.camera.value,
            "asset_tags": list(brief.asset_tags),
        }
    )


def headline_query(brief: Brief) -> str:
    """Plan query with the selected news headline in place of the fixed category title."""
    plan = brief.plan
    return canonical_visual_query(
        {
            "category": brief.category,
            "title": brief.headline,
            "learning_goal": brief.learning_goal,
            "scene": plan.scene.value,
            "main_action": brief.main_action,
            "characters": list(plan.characters),
            "subject": plan.subject.value,
            "cast": plan.cast.value,
            "composition": plan.composition.value,
            "camera": plan.camera.value,
            "asset_tags": list(brief.asset_tags),
        }
    )


QUERY_BUILDERS = {
    "semantic_brief": brief_query,
    "semantic_plan": plan_query,
    "semantic_headline": headline_query,
}


def selection_request(
    brief: Brief,
    *,
    max_references: int,
    max_reference_bytes: int,
    recent_action: tuple[str, ...],
    recent_variant_groups: tuple[str, ...],
) -> AssetSelectionRequest:
    plan = brief.plan
    return AssetSelectionRequest(
        category=brief.category,
        topic=brief.title,
        asset_tags=brief.asset_tags,
        characters=plan.characters,
        main_action=plan.subject.value,
        poses=(plan.composition.value, plan.camera.value),
        scene=plan.scene.value,
        subject=plan.subject.value,
        cast=plan.cast.value,
        reference_roles=tuple(VisualAssetRole(role) for role in brief.reference_roles),
        max_references=max_references,
        max_reference_bytes=max_reference_bytes,
        selection_seed=f"{brief.run_id}:primary:{plan.fingerprint}",
        recent_action_asset_ids=recent_action,
        recent_style_asset_ids=(),
        recent_variant_groups=recent_variant_groups,
    )


def selection_refs(selection: VisualAssetSelection) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "asset_id": selected.asset_id,
            "role": selected.role.value,
            "ordinal": ordinal,
            "selection_reason": selected.reason,
            "fallback_used": selected.fallback,
            "semantic_similarity": selected.semantic_similarity,
            "rule_score": selected.rule_score,
        }
        for ordinal, selected in enumerate(selection.selected_assets, start=1)
    )


def action_asset(refs: Sequence[dict[str, Any]]) -> str | None:
    for ref in refs:
        if ref["role"] == ACTION:
            return str(ref["asset_id"])
    return None


class History:
    """Emulate the 7-day novelty window with the arm's own earlier picks."""

    def __init__(self, loaded: LoadedVisualCatalog, *, history_days: int, limit: int) -> None:
        self._catalog = loaded.catalog
        self._days = history_days
        self._limit = limit
        self._rows: list[tuple[date, str]] = []

    def recent(self, business_date: date) -> tuple[tuple[str, ...], tuple[str, ...]]:
        cutoff = business_date - timedelta(days=self._days - 1)
        rows = [
            asset_id
            for row_date, asset_id in reversed(self._rows)
            if cutoff <= row_date <= business_date
        ][: self._limit]
        groups = tuple(
            asset.variant_group
            for asset_id in rows
            if (asset := self._catalog.asset_by_id.get(asset_id)) is not None
            and asset.variant_group is not None
        )
        return tuple(rows), groups

    def record(self, business_date: date, refs: Sequence[dict[str, Any]]) -> None:
        for ref in refs:
            if ref["role"] == ACTION:
                self._rows.append((business_date, str(ref["asset_id"])))

    def seed(self, rows: Sequence[dict[str, Any]]) -> None:
        """Pre-load production's own references from the days before the window."""
        for ref in rows:
            if ref["role"] == ACTION:
                self._rows.append((date.fromisoformat(ref["business_date"]), str(ref["asset_id"])))
        self._rows.sort(key=lambda item: item[0])


async def rank_query(
    service: VisualRetrievalService,
    loaded: LoadedVisualCatalog,
    cache: dict[str, VisualSemanticRanking],
    query: str,
) -> VisualSemanticRanking:
    ranking = cache.get(query)
    if ranking is None:
        ranking = await service.search_text(text=query, catalog=loaded.catalog)
        if not ranking.complete or ranking.catalog_version != loaded.catalog.catalog_version:
            raise RuntimeError("local visual index is incomplete for the current catalog")
        cache[query] = ranking
    return ranking


async def replay(
    briefs: Sequence[Brief],
    *,
    loaded: LoadedVisualCatalog,
    service: VisualRetrievalService,
    settings: Settings,
    arms: Sequence[str],
    history_seed: Sequence[dict[str, Any]] = (),
) -> tuple[list[ReplayRow], dict[str, VisualSemanticRanking]]:
    cache: dict[str, VisualSemanticRanking] = {}
    histories = {
        arm: History(
            loaded,
            history_days=settings.image_diversity_history_days,
            limit=settings.image_diversity_history_limit,
        )
        for arm in arms
    }
    for history in histories.values():
        history.seed(history_seed)
    rows: list[ReplayRow] = []
    for index, brief in enumerate(briefs, start=1):
        row = ReplayRow(brief=brief)
        row.picks["production_rule"] = ArmPick(refs=brief.production_refs)
        for arm in arms:
            recent_action, recent_groups = histories[arm].recent(brief.business_date)
            request = selection_request(
                brief,
                max_references=settings.image_max_reference_images,
                max_reference_bytes=settings.image_reference_budget_bytes,
                recent_action=recent_action,
                recent_variant_groups=recent_groups,
            )
            try:
                if arm == "rule_replay":
                    selection = select_visual_assets(
                        loaded,
                        request,
                        selector_version=VISUAL_SELECTOR_V2_VERSION,
                        max_references=request.max_references,
                        max_reference_bytes=request.max_reference_bytes,
                    )
                    pick = ArmPick(refs=selection_refs(selection), fallback=selection.fallback_used)
                else:
                    query = QUERY_BUILDERS[arm](brief)
                    ranking = await rank_query(service, loaded, cache, query)
                    selection = select_visual_assets(
                        loaded,
                        request,
                        selector_version=VISUAL_SEMANTIC_SELECTOR_VERSION,
                        max_references=request.max_references,
                        max_reference_bytes=request.max_reference_bytes,
                        semantic_scores=ranking.score_map,
                    )
                    refs = selection_refs(selection)
                    chosen = action_asset(refs)
                    pick = ArmPick(
                        refs=refs,
                        query=query,
                        fallback=selection.fallback_used,
                        similarity=ranking.score_map.get(chosen) if chosen else None,
                    )
            except BudgetExhaustedError:
                raise
            except Exception as error:  # recorded per row, replay continues
                pick = ArmPick(refs=(), error=type(error).__name__)
            histories[arm].record(brief.business_date, pick.refs)
            row.picks[arm] = pick
        rows.append(row)
        if index % 20 == 0:
            print(f"replayed {index}/{len(briefs)}", file=sys.stderr)
    return rows, cache


def arm_stats(rows: Sequence[ReplayRow], arm: str) -> dict[str, Any]:
    actions = [action_asset(row.picks[arm].refs) for row in rows if arm in row.picks]
    present = [item for item in actions if item is not None]
    counter = Counter(present)
    repeats = sum(1 for previous, current in pairwise(actions) if previous == current)
    identities = Counter(
        ref["asset_id"]
        for row in rows
        if arm in row.picks
        for ref in row.picks[arm].refs
        if ref["role"] == IDENTITY
    )
    similarities = [
        similarity
        for row in rows
        if arm in row.picks and (similarity := row.picks[arm].similarity) is not None
    ]
    return {
        "rows": len(actions),
        "errors": sum(1 for row in rows if arm in row.picks and row.picks[arm].error),
        "no_action_reference": sum(
            1
            for row in rows
            if arm in row.picks
            and not row.picks[arm].error
            and action_asset(row.picks[arm].refs) is None
        ),
        "fallbacks": sum(1 for row in rows if arm in row.picks and row.picks[arm].fallback),
        "distinct_action_assets": len(counter),
        "top_action_share": (counter.most_common(1)[0][1] / len(present)) if present else 0.0,
        "same_action_as_previous": repeats / max(len(actions) - 1, 1),
        "distinct_identity_assets": len(identities),
        "mean_action_similarity": (sum(similarities) / len(similarities)) if similarities else None,
        "distinct_queries": len({row.picks[arm].query for row in rows if row.picks[arm].query}),
    }


def agreement(rows: Sequence[ReplayRow], left: str, right: str) -> float:
    pairs = [
        (action_asset(row.picks[left].refs), action_asset(row.picks[right].refs))
        for row in rows
        if left in row.picks and right in row.picks
    ]
    return sum(1 for a, b in pairs if a == b) / len(pairs) if pairs else 0.0


def sample_pairs(
    rows: Sequence[ReplayRow], *, arm: str, count: int, seed: int
) -> list[tuple[ReplayRow, str]]:
    """Rows where both arms chose an action reference and they differ.

    Pairs are spread round-robin over distinct (production asset, replay asset)
    combinations so the judge sees every kind of disagreement, not thirty copies
    of the most frequent one. Sides are blinded at random.
    """
    rng = random.Random(seed)
    groups: dict[tuple[str, str], list[ReplayRow]] = {}
    for row in rows:
        if arm not in row.picks or row.picks[arm].error:
            continue
        replay_action = action_asset(row.picks[arm].refs)
        production_action = action_asset(row.picks["production_rule"].refs)
        if replay_action is None or production_action is None:
            continue
        if replay_action == production_action:
            continue
        groups.setdefault((production_action, replay_action), []).append(row)
    for items in groups.values():
        rng.shuffle(items)
    chosen: list[ReplayRow] = []
    while len(chosen) < count and any(groups.values()):
        for combination in sorted(groups):
            if groups[combination] and len(chosen) < count:
                chosen.append(groups[combination].pop())
    rng.shuffle(chosen)
    return [(row, rng.choice(("A", "B"))) for row in chosen]


def thumbnail_b64(loaded: LoadedVisualCatalog, asset_id: str, *, edge: int) -> str:
    asset = loaded.catalog.asset_by_id[asset_id]
    with Image.open(BytesIO(read_visual_asset_bytes(loaded, asset))) as opened:
        opened.load()
        image = opened.convert("RGBA")
        image.thumbnail((edge, edge))
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        buffer = BytesIO()
        background.save(buffer, format="JPEG", quality=82, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def render_html(
    pairs: Sequence[tuple[ReplayRow, str]],
    *,
    arm: str,
    loaded: LoadedVisualCatalog,
    report_id: str,
) -> tuple[str, list[dict[str, Any]]]:
    asset_ids = sorted(
        {
            ref["asset_id"]
            for row, _ in pairs
            for pick_arm in ("production_rule", arm)
            for ref in row.picks[pick_arm].refs
        }
    )
    thumbs = {asset_id: thumbnail_b64(loaded, asset_id, edge=520) for asset_id in asset_ids}
    key: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for ordinal, (row, production_side) in enumerate(pairs, start=1):
        production = row.picks["production_rule"].refs
        semantic = row.picks[arm].refs
        left, right = (production, semantic) if production_side == "A" else (semantic, production)
        key.append(
            {
                "pair": ordinal,
                "artifact_id": row.brief.artifact_id,
                "left": "production_rule" if production_side == "A" else arm,
                "right": arm if production_side == "A" else "production_rule",
            }
        )
        items.append(
            {
                "pair": ordinal,
                "date": row.brief.business_date.isoformat(),
                "category": CATEGORY_LABELS.get(row.brief.category, row.brief.category),
                "headline": row.brief.headline,
                "plan": f"{row.brief.plan.subject.value} · {row.brief.plan.cast.value} · "
                f"{row.brief.plan.scene.value}",
                "left": [{"role": ref["role"], "asset": ref["asset_id"]} for ref in left],
                "right": [{"role": ref["role"], "asset": ref["asset_id"]} for ref in right],
            }
        )
    payload = json.dumps(
        {"report_id": report_id, "arm": arm, "items": items, "thumbs": thumbs},
        ensure_ascii=False,
    )
    html = _HTML_TEMPLATE.replace("__PAYLOAD__", payload.replace("</", "<\\/"))
    return html, key


_HTML_TEMPLATE = Path(__file__).with_name("compare_template.html").read_text(encoding="utf-8")


def render_report(
    rows: Sequence[ReplayRow],
    *,
    arms: Sequence[str],
    meta: dict[str, Any],
    pairs: Sequence[tuple[ReplayRow, str]],
    pair_arm: str,
) -> str:
    lines = [
        "# Visual reference replay — semantic selector vs production rules",
        "",
        f"- Briefs replayed: {len(rows)} (production `image_artifacts` of the last 30 days, "
        f"{rows[0].brief.business_date} → {rows[-1].brief.business_date})",
        f"- Catalog: `{meta['catalog_version']}`, local index complete; provider calls: "
        f"{meta['calls']} (distinct queries {meta['distinct_queries']}), "
        f"input tokens {meta['input_tokens']}",
        "- History emulation: every replay arm starts from production's own references of the "
        "8 days before the window, then sees only its own earlier primary picks within the "
        "7-day novelty window; production also counted alternate-plan reservations, so "
        "`rule_replay` is a harness check, not an exact reproduction.",
        "- `errors` are selector exceptions (production would fail that image job); "
        "`no action ref` means the byte budget left no room for an action reference; "
        "`fallbacks` counts selections whose action reference matched no rule.",
        "- Semantic similarities are model scores, not human labels. Pairs below are for a human "
        "judge; nothing here says which side is better until those labels exist.",
        "",
        "## Arms",
        "",
        "| arm | what it is |",
        "|---|---|",
        "| production_rule | references production actually used "
        "(tag rules, selector v2-novelty) |",
        "| rule_replay | same rule selector re-run locally (harness check) |",
        "| semantic_brief | semantic selector with today's production query "
        "(category profile only) |",
        "| semantic_plan | query also carries the per-post plan: "
        "subject, cast, composition, camera, scene |",
        "| semantic_headline | plan query with the selected news headline as the title |",
        "",
        "## Reference usage (action reference)",
        "",
        "| arm | rows | errors | no action ref | fallbacks | distinct action assets | "
        "top-1 share | same as previous | distinct identity assets | mean similarity | "
        "distinct queries |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in ("production_rule", *arms):
        stats = arm_stats(rows, arm)
        similarity = (
            f"{stats['mean_action_similarity']:.3f}"
            if stats["mean_action_similarity"] is not None
            else "–"
        )
        lines.append(
            f"| {arm} | {stats['rows']} | {stats['errors']} | {stats['no_action_reference']} | "
            f"{stats['fallbacks']} | "
            f"{stats['distinct_action_assets']} | {stats['top_action_share']:.0%} | "
            f"{stats['same_action_as_previous']:.0%} | {stats['distinct_identity_assets']} | "
            f"{similarity} | {stats['distinct_queries']} |"
        )
    lines += [
        "",
        "## Agreement with production on the action reference",
        "",
        "| arm | same action asset as production |",
        "|---|---|",
    ]
    for arm in arms:
        lines.append(f"| {arm} | {agreement(rows, 'production_rule', arm):.0%} |")
    per_category = Counter(row.brief.category for row, _ in pairs)
    combinations = len(
        {
            (
                action_asset(row.picks["production_rule"].refs),
                action_asset(row.picks[pair_arm].refs),
            )
            for row, _ in pairs
        }
    )
    lines += [
        "",
        "## Human judging set",
        "",
        f"- {len(pairs)} blinded pairs, production vs `{pair_arm}`, only rows where both chose "
        f"an action reference and they differ; spread over {combinations} distinct image "
        "combinations (not proportional to frequency); categories: "
        + ", ".join(
            f"{CATEGORY_LABELS.get(key, key)} {value}"
            for key, value in sorted(per_category.items())
        ),
        "- Only the action reference is shown; identity references are character sheets and "
        "would only distract the judge.",
        "- Side assignment is random per pair and recorded only in `pairs-key.json`.",
        "- Scoring after labels: win rate of each arm over judged pairs with `tie`/`neither` "
        "reported separately; 30 pairs give a rough signal only (±18 pp at 95%).",
    ]
    return "\n".join(lines) + "\n"


def build_settings(env_file: str) -> Settings:
    settings = Settings(_env_file=env_file, visual_semantic_enabled=False)
    if settings.visual_embedding_provider_mode != "alibaba":
        raise SystemExit("this replay needs the local Alibaba visual embedding settings")
    if settings.visual_embedding_endpoint is None or settings.visual_embedding_api_key is None:
        raise SystemExit("visual embedding secrets are unavailable")
    return settings


async def collect(
    args: argparse.Namespace,
    *,
    settings: Settings,
    loaded: LoadedVisualCatalog,
    briefs: Sequence[Brief],
    arms: Sequence[str],
    history_seed: Sequence[dict[str, Any]],
) -> tuple[list[ReplayRow], dict[str, VisualSemanticRanking], BudgetedEmbeddings]:
    endpoint = settings.visual_embedding_endpoint
    api_key = settings.visual_embedding_api_key
    if endpoint is None or api_key is None:
        raise SystemExit("visual embedding secrets are unavailable")
    engine = create_engine(settings)
    client = httpx.AsyncClient(follow_redirects=False)
    try:
        embeddings = BudgetedEmbeddings(
            AlibabaVisualEmbeddingAdapter(
                client=client,
                endpoint=endpoint,
                api_key=api_key,
                timeout_seconds=settings.visual_embedding_timeout_seconds,
                concurrency=1,
            ),
            max_calls=args.max_calls,
        )
        service = VisualRetrievalService(
            embeddings=embeddings,
            repository=PostgresVisualIndexRepository(create_session_factory(engine)),
            identity=settings.visual_embedding_identity,
        )
        rows, cache = await replay(
            briefs,
            loaded=loaded,
            service=service,
            settings=settings,
            arms=arms,
            history_seed=history_seed,
        )
    finally:
        await client.aclose()
        await engine.dispose()
    return rows, cache, embeddings


def run(args: argparse.Namespace) -> int:
    settings = build_settings(args.env_file)
    loaded = load_visual_catalog(settings.image_asset_manifest)
    briefs = load_briefs(Path(args.briefs), Path(args.headlines))
    if args.limit:
        briefs = briefs[: args.limit]
    arms = tuple(arm for arm in REPLAY_ARMS if arm not in set(args.skip_arm))
    print(
        json.dumps(
            {
                "briefs": len(briefs),
                "catalog_assets": len(loaded.catalog.assets),
                "arms": arms,
                "max_calls": args.max_calls,
                "distinct_queries_planned": {
                    arm: len({QUERY_BUILDERS[arm](brief) for brief in briefs})
                    for arm in arms
                    if arm in QUERY_BUILDERS
                },
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    if args.plan:
        return 0
    history_seed: list[dict[str, Any]] = (
        json.loads(Path(args.history_seed).read_text(encoding="utf-8")) or []
        if args.history_seed
        else []
    )
    rows, cache, embeddings = asyncio.run(
        collect(
            args,
            settings=settings,
            loaded=loaded,
            briefs=briefs,
            arms=arms,
            history_seed=history_seed,
        )
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "calls": embeddings.calls,
        "input_tokens": embeddings.input_tokens,
        "distinct_queries": len(cache),
        "catalog_version": loaded.catalog.catalog_version,
        "arms": list(arms),
    }
    (output_dir / "replay-meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    results = [
        {
            "artifact_id": row.brief.artifact_id,
            "business_date": row.brief.business_date.isoformat(),
            "category": row.brief.category,
            "headline": row.brief.headline,
            "plan": row.brief.plan.as_metadata(),
            "picks": {
                arm: {
                    "refs": list(pick.refs),
                    "query": pick.query,
                    "fallback": pick.fallback,
                    "similarity": pick.similarity,
                    "error": pick.error,
                }
                for arm, pick in row.picks.items()
            },
        }
        for row in rows
    ]
    (output_dir / "replay-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    write_pairs_and_report(rows, loaded=loaded, meta=meta, args=args)
    return 0


def write_pairs_and_report(
    rows: Sequence[ReplayRow],
    *,
    loaded: LoadedVisualCatalog,
    meta: dict[str, Any],
    args: argparse.Namespace,
) -> None:
    output_dir = Path(args.output_dir)
    pairs = sample_pairs(rows, arm=args.pair_arm, count=args.pairs, seed=args.seed)
    html, key = render_html(pairs, arm=args.pair_arm, loaded=loaded, report_id=args.report_id)
    (output_dir / "compare.html").write_text(html, encoding="utf-8")
    (output_dir / "pairs-key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "replay-report.md").write_text(
        render_report(rows, arms=meta["arms"], meta=meta, pairs=pairs, pair_arm=args.pair_arm),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "calls": meta["calls"],
                "input_tokens": meta["input_tokens"],
                "pairs": len(pairs),
                "output_dir": str(output_dir),
            }
        ),
        file=sys.stderr,
    )


def rebuild_pairs(args: argparse.Namespace) -> int:
    """Re-sample the judging pairs from a finished replay without provider calls."""
    settings = Settings(_env_file=args.env_file, visual_semantic_enabled=False)
    loaded = load_visual_catalog(settings.image_asset_manifest)
    briefs = {
        brief.artifact_id: brief for brief in load_briefs(Path(args.briefs), Path(args.headlines))
    }
    output_dir = Path(args.output_dir)
    results = json.loads((output_dir / "replay-results.json").read_text(encoding="utf-8"))
    meta = json.loads((output_dir / "replay-meta.json").read_text(encoding="utf-8"))
    rows = [
        ReplayRow(
            brief=briefs[result["artifact_id"]],
            picks={
                arm: ArmPick(
                    refs=tuple(pick["refs"]),
                    query=pick["query"],
                    fallback=pick["fallback"],
                    similarity=pick["similarity"],
                    error=pick["error"],
                )
                for arm, pick in result["picks"].items()
            },
        )
        for result in results
    ]
    write_pairs_and_report(rows, loaded=loaded, meta=meta, args=args)
    return 0


def score_judgments(args: argparse.Namespace) -> int:
    key = {row["pair"]: row for row in json.loads(Path(args.key).read_text(encoding="utf-8"))}
    judged = json.loads(Path(args.judgments).read_text(encoding="utf-8"))["answers"]
    wins: Counter[str] = Counter()
    for row in judged:
        choice = row["choice"]
        entry = key[row["pair"]]
        if choice == "left":
            wins[entry["left"]] += 1
        elif choice == "right":
            wins[entry["right"]] += 1
        elif choice in {"tie", "neither"}:
            wins[choice] += 1
        else:
            wins["unjudged"] += 1
    total = sum(wins.values())
    print(json.dumps({"judged_pairs": total, "outcomes": dict(wins)}, ensure_ascii=False, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--briefs", required=True)
    run_parser.add_argument("--headlines", required=True)
    run_parser.add_argument("--history-seed", default=None)
    run_parser.add_argument("--output-dir", required=True)
    run_parser.add_argument("--env-file", default="/root/projects/edu-ai-lead-agent/.env")
    run_parser.add_argument("--max-calls", type=int, default=300)
    run_parser.add_argument("--pairs", type=int, default=30)
    run_parser.add_argument("--pair-arm", default="semantic_headline", choices=SEMANTIC_ARMS)
    run_parser.add_argument("--seed", type=int, default=20260930)
    run_parser.add_argument("--report-id", default="2026-09-30")
    run_parser.add_argument("--limit", type=int, default=0)
    run_parser.add_argument("--skip-arm", action="append", default=[], choices=REPLAY_ARMS)
    run_parser.add_argument("--plan", action="store_true", help="print the call plan and exit")
    pairs_parser = sub.add_parser("pairs")
    pairs_parser.add_argument("--briefs", required=True)
    pairs_parser.add_argument("--headlines", required=True)
    pairs_parser.add_argument("--output-dir", required=True)
    pairs_parser.add_argument("--env-file", default="/root/projects/edu-ai-lead-agent/.env")
    pairs_parser.add_argument("--pairs", type=int, default=30)
    pairs_parser.add_argument("--pair-arm", default="semantic_headline", choices=SEMANTIC_ARMS)
    pairs_parser.add_argument("--seed", type=int, default=20260930)
    pairs_parser.add_argument("--report-id", default="2026-09-30")
    score_parser = sub.add_parser("score")
    score_parser.add_argument("--key", required=True)
    score_parser.add_argument("--judgments", required=True)
    args = parser.parse_args(argv)
    if args.command == "score":
        return score_judgments(args)
    if args.command == "pairs":
        return rebuild_pairs(args)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
