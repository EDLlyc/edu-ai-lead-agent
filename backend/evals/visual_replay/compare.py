"""Compare reference-selection strategies on the production brief replay.

Arms:

- production_rule: what production actually used (tag rules, selector v2-novelty).
- v2_semantic: today's semantic selector code with today's production query.
- v3_rules: identity by rules; action image gated by prop/subject and cast, one-day
  no-repeat, then rule score.
- v3_semantic: as v3_rules, but the in-tier order is Qwen3-VL similarity to the subject.
- v3_semantic_ungated: v3_semantic without the prop gate (does the embedding alone keep
  wrong props out?).

Label-based metrics use the drafted prop labels; similarity is a model score. None of this
says which images look better — that is the human pair judgment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
from app.application.services.visual_retrieval import VisualRetrievalService
from app.core.config import Settings
from app.domain.visual_assets import AssetSelector, VisualAsset, VisualAssetCatalog, VisualAssetRole
from app.domain.visual_diversity import VISUAL_SELECTOR_V2_VERSION, VISUAL_SELECTOR_V3_VERSION
from app.domain.visual_retrieval import VISUAL_SELECTOR_VERSION as VISUAL_SEMANTIC_SELECTOR_VERSION
from app.domain.visual_retrieval import canonical_visual_query
from app.infrastructure.ai.visual_embedding import AlibabaVisualEmbeddingAdapter
from app.infrastructure.brand.visual_catalog import (
    LoadedVisualCatalog,
    load_visual_catalog,
    select_visual_assets,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.visual_retrieval import PostgresVisualIndexRepository

from evals.visual_replay.runner import (
    ACTION,
    IDENTITY,
    Brief,
    History,
    brief_query,
    load_briefs,
    selection_request,
)
from evals.visual_replay.scores_cache import ScoreCache
from evals.visual_replay.subject_retrieval import production_style

ARMS = (
    "production_rule",
    "v2_semantic",
    "v3_rules",
    "v3_semantic",
    "v3_semantic_ungated",
    "v3_app_rules",
    "v3_app_semantic",
)
COOLDOWN_PICKS = 6  # about one business day of posts


@dataclass(frozen=True, slots=True)
class Labels:
    props: Mapping[str, str]
    compatible: Mapping[str, frozenset[str]]

    @classmethod
    def load(cls, path: Path) -> Labels:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            props={asset_id: row["prop"] for asset_id, row in raw["assets"].items()},
            compatible={
                subject: frozenset(props) for subject, props in raw["compatible_props"].items()
            },
        )

    def fit(self, asset_id: str, subject: str) -> int:
        """2 = the prop suits the subject, 1 = pose only, 0 = a prop the subject forbids."""
        prop = self.props[asset_id]
        if prop == "none":
            return 1
        return 2 if prop in self.compatible[subject] else 0


class Recency:
    """Sequence numbers of each arm's own earlier action picks (seeded from production)."""

    def __init__(self) -> None:
        self._last: dict[str, int] = {}
        self._sequence = 0

    def seed(self, asset_ids: Sequence[str]) -> None:
        for asset_id in asset_ids:
            self.record(asset_id)

    def gap(self, asset_id: str) -> int:
        last = self._last.get(asset_id)
        return 10_000 if last is None else self._sequence - last

    def record(self, asset_id: str | None) -> None:
        self._sequence += 1
        if asset_id is not None:
            self._last[asset_id] = self._sequence


def choose_v3(
    brief: Brief,
    *,
    loaded: LoadedVisualCatalog,
    labels: Labels,
    recency: Recency,
    scores: Mapping[str, float] | None,
    max_references: int,
    max_reference_bytes: int,
    prop_gate: bool = True,
) -> tuple[dict[str, Any], ...]:
    request = selection_request(
        brief,
        max_references=max_references,
        max_reference_bytes=max_reference_bytes,
        recent_action=(),
        recent_variant_groups=(),
    )
    identity_only = select_visual_assets(
        loaded,
        replace(request, reference_roles=(VisualAssetRole.IDENTITY_REFERENCE,)),
        selector_version=VISUAL_SELECTOR_V2_VERSION,
        max_references=max_references,
        max_reference_bytes=max_reference_bytes,
    )
    refs: list[dict[str, Any]] = [
        {"asset_id": selected.asset_id, "role": IDENTITY}
        for selected in identity_only.selected_assets
    ]
    if len(refs) >= max_references:
        return tuple(refs)
    remaining = max_reference_bytes - identity_only.total_byte_size
    cast = set(brief.plan.characters)
    subject = brief.plan.subject.value

    def eligible(asset: VisualAsset, *, cast_gate: bool) -> bool:
        return (
            asset.approved
            and VisualAssetRole.ACTION_REFERENCE in asset.roles
            and asset.byte_size <= remaining
            and (not cast_gate or set(asset.characters) <= cast)
            and (not prop_gate or labels.fit(asset.asset_id, subject) > 0)
        )

    pool = [a for a in loaded.catalog.assets if eligible(a, cast_gate=True)]
    if not pool:
        pool = [a for a in loaded.catalog.assets if eligible(a, cast_gate=False)]
    if not pool:
        return tuple(refs)

    def preference(asset: VisualAsset) -> float:
        if scores is not None:
            return scores[asset.asset_id]
        return AssetSelector._action_match_score(asset, request) * 100 + asset.priority

    def key(asset: VisualAsset) -> tuple[int, int, float, str]:
        gap = recency.gap(asset.asset_id)
        if gap > COOLDOWN_PICKS:
            tier = 0 if labels.fit(asset.asset_id, subject) == 2 else 1
            return (tier, 0, -preference(asset), asset.asset_id)
        return (2, -gap, -preference(asset), asset.asset_id)

    chosen = min(pool, key=key)
    refs.append({"asset_id": chosen.asset_id, "role": ACTION})
    return tuple(refs)


def labelled_catalog(loaded: LoadedVisualCatalog, labels: Labels) -> LoadedVisualCatalog:
    """The local catalog with the drafted prop labels, as selector v3 reads them."""
    assets = tuple(
        replace(
            asset,
            props=(
                ()
                if labels.props.get(asset.asset_id, "none") == "none"
                else (labels.props[asset.asset_id],)
            )
            if VisualAssetRole.ACTION_REFERENCE in asset.roles
            else (),
        )
        for asset in loaded.catalog.assets
    )
    catalog = VisualAssetCatalog(
        schema_version=loaded.catalog.schema_version,
        catalog_version=loaded.catalog.catalog_version,
        assets=assets,
    )
    return LoadedVisualCatalog(catalog=catalog, materials_root=loaded.materials_root)


def app_subject_query(brief: Brief) -> str:
    """Exactly `material_package._subject_visual_query`."""
    return canonical_visual_query({"category": brief.category, "subject": brief.plan.subject.value})


def action_of(refs: Sequence[dict[str, Any]]) -> str | None:
    return next((str(ref["asset_id"]) for ref in refs if ref["role"] == ACTION), None)


def metrics(
    rows: Sequence[dict[str, Any]], arm: str, *, labels: Labels, loaded: LoadedVisualCatalog
) -> dict[str, Any]:
    catalog = loaded.catalog.asset_by_id
    actions = [action_of(row["picks"][arm]["refs"]) for row in rows]
    errors = sum(1 for row in rows if row["picks"][arm].get("error"))
    present = [(row, a) for row, a in zip(rows, actions, strict=True) if a is not None]
    wrong = sum(1 for row, a in present if labels.fit(a, row["subject"]) == 0)
    strong = sum(1 for row, a in present if labels.fit(a, row["subject"]) == 2)
    extra = sum(1 for row, a in present if set(catalog[a].characters) - set(row["cast_characters"]))
    counter = Counter(a for _, a in present)
    return {
        "rows": len(rows),
        "errors": errors,
        "no_action": len(rows) - len(present) - errors,
        "wrong_prop": wrong,
        "strong_fit": strong,
        "extra_character": extra,
        "distinct": len(counter),
        "top1_share": counter.most_common(1)[0][1] / len(present) if present else 0.0,
        "same_as_previous": sum(1 for x, y in pairwise(actions) if x is not None and x == y)
        / max(len(actions) - 1, 1),
    }


def render(table: dict[str, dict[str, Any]], *, calls: int, rows: int) -> str:
    lines = [
        "# Reference selection strategies — replay of production briefs",
        "",
        f"- Briefs: {rows}; provider calls this run: {calls} (cached score maps reused).",
        "- `wrong prop` / `strong fit` use the drafted prop labels (Claude, pending owner "
        "confirmation); `extra character` means the action image shows a character the plan's "
        "cast excludes. Counts are over rows; percentages are of all rows.",
        f"- v3 tiers: suitable prop not used in the last {COOLDOWN_PICKS} picks → pose-only "
        "image not used in the last picks → least recently used; inside a tier, rule score "
        "(v3_rules) or Qwen3-VL similarity to the subject (v3_semantic).",
        "",
        "| arm | errors | no action ref | wrong prop | strong fit | extra character | "
        "distinct action images | top-1 share | same as previous |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, m in table.items():
        n = m["rows"]
        lines.append(
            f"| {arm} | {m['errors']} | {m['no_action']} | {m['wrong_prop']} "
            f"({m['wrong_prop'] / n:.0%}) | {m['strong_fit']} ({m['strong_fit'] / n:.0%}) | "
            f"{m['extra_character']} ({m['extra_character'] / n:.0%}) | {m['distinct']} | "
            f"{m['top1_share']:.0%} | {m['same_as_previous']:.0%} |"
        )
    return "\n".join(lines) + "\n"


async def score_maps(
    settings: Settings, loaded: LoadedVisualCatalog, cache: ScoreCache, queries: set[str]
) -> dict[str, dict[str, float]]:
    endpoint = settings.visual_embedding_endpoint
    api_key = settings.visual_embedding_api_key
    if endpoint is None or api_key is None:
        raise SystemExit("visual embedding secrets are unavailable")
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
        return {q: await cache.scores(service, loaded.catalog, q) for q in sorted(queries)}
    finally:
        await client.aclose()
        await engine.dispose()


def run(args: argparse.Namespace) -> int:
    settings = Settings(_env_file=args.env_file, visual_semantic_enabled=False)
    loaded = load_visual_catalog(settings.image_asset_manifest)
    labels = Labels.load(Path(args.labels))
    briefs = load_briefs(Path(args.briefs), Path(args.headlines))
    seed_rows = json.loads(Path(args.history_seed).read_text(encoding="utf-8")) or []
    seed_actions = [row["asset_id"] for row in seed_rows if row["role"] == ACTION]
    cache = ScoreCache(Path(args.cache_dir), identity_key="qwen3-vl-embedding-2048-v2")
    queries = (
        {brief_query(b) for b in briefs}
        | {production_style(b.plan.subject.value) for b in briefs}
        | {app_subject_query(b) for b in briefs}
    )
    maps = asyncio.run(score_maps(settings, loaded, cache, queries))
    cache.save()

    history = History(
        loaded,
        history_days=settings.image_diversity_history_days,
        limit=settings.image_diversity_history_limit,
    )
    history.seed(seed_rows)
    recency = {arm: Recency() for arm in ARMS[2:]}
    for arm_recency in recency.values():
        arm_recency.seed(seed_actions)
    labelled = labelled_catalog(loaded, labels)
    # App history: every reservation row, primary and alternate, oldest first.
    app_sequence = {arm: list(seed_actions) for arm in ("v3_app_rules", "v3_app_semantic")}
    budget = settings.image_reference_budget_bytes
    max_refs = settings.image_max_reference_images
    rows: list[dict[str, Any]] = []
    for brief in briefs:
        picks: dict[str, dict[str, Any]] = {
            "production_rule": {"refs": list(brief.production_refs)}
        }
        recent_action, recent_groups = history.recent(brief.business_date)
        request = selection_request(
            brief,
            max_references=max_refs,
            max_reference_bytes=budget,
            recent_action=recent_action,
            recent_variant_groups=recent_groups,
        )
        try:
            selection = select_visual_assets(
                loaded,
                request,
                selector_version=VISUAL_SEMANTIC_SELECTOR_VERSION,
                max_references=max_refs,
                max_reference_bytes=budget,
                semantic_scores=maps[brief_query(brief)],
            )
            v2_refs = [
                {"asset_id": s.asset_id, "role": s.role.value} for s in selection.selected_assets
            ]
            picks["v2_semantic"] = {"refs": v2_refs}
        except ValueError as error:
            v2_refs = []
            picks["v2_semantic"] = {"refs": [], "error": type(error).__name__}
        history.record(brief.business_date, v2_refs)
        subject_scores = maps[production_style(brief.plan.subject.value)]
        for arm, scores, gate in (
            ("v3_rules", None, True),
            ("v3_semantic", subject_scores, True),
            ("v3_semantic_ungated", subject_scores, False),
        ):
            refs = choose_v3(
                brief,
                loaded=loaded,
                labels=labels,
                recency=recency[arm],
                scores=scores,
                max_references=max_refs,
                max_reference_bytes=budget,
                prop_gate=gate,
            )
            recency[arm].record(action_of(refs))
            picks[arm] = {"refs": list(refs)}
        for arm, app_scores in (
            ("v3_app_rules", None),
            ("v3_app_semantic", maps[app_subject_query(brief)]),
        ):
            app_request = replace(
                selection_request(
                    brief,
                    max_references=max_refs,
                    max_reference_bytes=budget,
                    recent_action=(),
                    recent_variant_groups=(),
                ),
                recent_action_sequence=tuple(app_sequence[arm][-2_000:]),
            )
            app_selection = select_visual_assets(
                labelled,
                app_request,
                selector_version=VISUAL_SELECTOR_V3_VERSION,
                max_references=max_refs,
                max_reference_bytes=budget,
                semantic_scores=app_scores,
            )
            app_refs = [
                {"asset_id": s.asset_id, "role": s.role.value, "reason": s.reason}
                for s in app_selection.selected_assets
            ]
            chosen = action_of(app_refs)
            if chosen is not None:
                # One post reserves a primary and an alternate plan; the export has only the
                # primary, so the pick is recorded twice to keep the app's cooldown units.
                app_sequence[arm].extend((chosen, chosen))
            picks[arm] = {"refs": app_refs}
        rows.append(
            {
                "artifact_id": brief.artifact_id,
                "business_date": brief.business_date.isoformat(),
                "subject": brief.plan.subject.value,
                "cast_characters": list(brief.plan.characters),
                "headline": brief.headline,
                "picks": picks,
            }
        )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "strategies-results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    table = {arm: metrics(rows, arm, labels=labels, loaded=loaded) for arm in ARMS}
    (output / "strategies-report.md").write_text(
        render(table, calls=cache.misses, rows=len(rows)), encoding="utf-8"
    )
    print(json.dumps({"calls": cache.misses, "cached": cache.hits}))
    return 0


SUBJECT_ZH = {
    "robot_arm": "机械臂",
    "ai_sensor_console": "AI 传感控制台",
    "competition_prototype": "竞赛原型作品",
    "telescope_star_map": "望远镜星图",
    "rocket_satellite_model": "火箭卫星模型",
    "microscope_sample": "显微镜样本",
    "experiment_apparatus": "实验器材",
    "science_book_model": "科普书籍模型",
}
CAST_ZH = {"xiaosai_solo": "只有小赛", "sai_xiansheng_solo": "只有赛先生", "duo": "小赛和赛先生"}
COMPARISONS = (("production_rule", "v3_rules"), ("v3_rules", "v3_semantic"))


def judging_set(
    rows: Sequence[dict[str, Any]], briefs: Mapping[str, Brief], *, per_comparison: int, seed: int
) -> list[tuple[dict[str, Any], str, str, str]]:
    """Blinded pairs for each comparison, round-robin over (subject, cast), no row reused."""
    rng = random.Random(seed)
    used: set[str] = set()
    chosen: list[tuple[dict[str, Any], str, str, str]] = []
    for left_arm, right_arm in COMPARISONS:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            a = action_of(row["picks"][left_arm]["refs"])
            b = action_of(row["picks"][right_arm]["refs"])
            if a is None or b is None or a == b or row["artifact_id"] in used:
                continue
            plan = briefs[row["artifact_id"]].plan
            groups.setdefault((plan.subject.value, plan.cast.value), []).append(row)
        for items in groups.values():
            rng.shuffle(items)
        picked: list[dict[str, Any]] = []
        while len(picked) < per_comparison and any(groups.values()):
            for group in sorted(groups):
                if groups[group] and len(picked) < per_comparison:
                    picked.append(groups[group].pop())
        for row in picked:
            used.add(row["artifact_id"])
            sides = (left_arm, right_arm) if rng.random() < 0.5 else (right_arm, left_arm)
            chosen.append((row, f"{left_arm} vs {right_arm}", sides[0], sides[1]))
    rng.shuffle(chosen)
    return chosen


def write_judging_page(args: argparse.Namespace) -> int:
    from evals.visual_replay.runner import _HTML_TEMPLATE, thumbnail_b64

    settings = Settings(_env_file=args.env_file, visual_semantic_enabled=False)
    loaded = load_visual_catalog(settings.image_asset_manifest)
    briefs = {b.artifact_id: b for b in load_briefs(Path(args.briefs), Path(args.headlines))}
    output = Path(args.output_dir)
    rows = json.loads((output / "strategies-results.json").read_text(encoding="utf-8"))
    pairs = judging_set(rows, briefs, per_comparison=args.per_comparison, seed=args.seed)
    items: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    assets: set[str] = set()
    for ordinal, (row, comparison, left_arm, right_arm) in enumerate(pairs, start=1):
        brief = briefs[row["artifact_id"]]
        left = [r for r in row["picks"][left_arm]["refs"] if r["role"] == ACTION]
        right = [r for r in row["picks"][right_arm]["refs"] if r["role"] == ACTION]
        assets.update(r["asset_id"] for r in left + right)
        items.append(
            {
                "pair": ordinal,
                "date": brief.business_date.isoformat(),
                "category": SUBJECT_ZH[brief.plan.subject.value],
                "headline": brief.headline,
                "plan": (
                    f"{CAST_ZH[brief.plan.cast.value]} · {SUBJECT_ZH[brief.plan.subject.value]}"
                ),
                "left": [{"role": ACTION, "asset": r["asset_id"]} for r in left],
                "right": [{"role": ACTION, "asset": r["asset_id"]} for r in right],
            }
        )
        key.append(
            {
                "pair": ordinal,
                "artifact_id": row["artifact_id"],
                "comparison": comparison,
                "left": left_arm,
                "right": right_arm,
            }
        )
    thumbs = {asset_id: thumbnail_b64(loaded, asset_id, edge=520) for asset_id in sorted(assets)}
    payload = json.dumps(
        {"report_id": args.report_id, "arm": "v3", "items": items, "thumbs": thumbs},
        ensure_ascii=False,
    )
    html = _HTML_TEMPLATE.replace("__PAYLOAD__", payload.replace("</", "<\\/"))
    (output / "compare-v3.html").write_text(html, encoding="utf-8")
    (output / "pairs-key-v3.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"pairs": len(items), "page": str(output / "compare-v3.html")}))
    return 0


def score_judgments(args: argparse.Namespace) -> int:
    key = {row["pair"]: row for row in json.loads(Path(args.key).read_text(encoding="utf-8"))}
    answers = json.loads(Path(args.judgments).read_text(encoding="utf-8"))["answers"]
    table: dict[str, Counter[str]] = {}
    for answer in answers:
        entry = key[answer["pair"]]
        choice = answer["choice"]
        outcome = entry[choice] if choice in {"left", "right"} else choice or "unjudged"
        table.setdefault(entry["comparison"], Counter())[outcome] += 1
    print(json.dumps({k: dict(v) for k, v in table.items()}, ensure_ascii=False, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    page_parser = sub.add_parser("page")
    for sub_parser in (run_parser, page_parser):
        sub_parser.add_argument("--briefs", required=True)
        sub_parser.add_argument("--headlines", required=True)
        sub_parser.add_argument("--output-dir", required=True)
        sub_parser.add_argument("--env-file", default="/root/projects/edu-ai-lead-agent/.env")
    run_parser.add_argument("--history-seed", required=True)
    run_parser.add_argument("--labels", required=True)
    run_parser.add_argument("--cache-dir", required=True)
    page_parser.add_argument("--per-comparison", type=int, default=15)
    page_parser.add_argument("--seed", type=int, default=20260930)
    page_parser.add_argument("--report-id", default="2026-09-30-v3")
    score_parser = sub.add_parser("score")
    score_parser.add_argument("--key", required=True)
    score_parser.add_argument("--judgments", required=True)
    args = parser.parse_args(argv)
    if args.command == "page":
        return write_judging_page(args)
    if args.command == "score":
        return score_judgments(args)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
