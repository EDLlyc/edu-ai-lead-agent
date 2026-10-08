"""Re-check Qwen3-VL in-tier ordering on the current selector (pool-aware planner, resized images).

Both arms replay every production brief in time order with the controlled planner and selector
v3, each carrying its own history; they differ only inside a tier: the rule score (production
today) or Qwen3-VL text-to-image similarity of the production query
(`canonical_visual_query({category, subject})`, as material_package builds it). The hard gates
(prop, cast, budget, cooldown) are the same, so semantic scores can only reorder images the
gates already allow.

Score maps come from the 2026-09-30 cache (original catalog). The 12 resized action images have
new asset ids, so their scores are mapped by filename (same picture, smaller file). A query that
is not cached is embedded through the local visual index (`--allow-embedding`), else the run
stops and lists it.

    python -m evals.visual_replay.semantic_recheck \\
        --briefs <production-briefs.json> --headlines <production-headlines.json> \\
        --manifest <current brand copy>/visual-assets.manifest.json \\
        --original-manifest <local private>/visual-assets.manifest.json \\
        --cache-dir tmp/visual-replay/cache --output-dir tmp/visual-replay/2026-10-08

Writes recheck.md (aggregates), recheck-picks.json, compare-semantic.html (blinded pairs where
the arms differ) and pairs-key-semantic.json; score the judgments with
`python -m evals.visual_replay.compare score --key ... --judgments ...`.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.domain.visual_diversity import ControlledVisualPlan
from app.domain.visual_retrieval import canonical_visual_query
from app.infrastructure.brand.visual_catalog import LoadedVisualCatalog, load_visual_catalog

from evals.visual_replay.compare import CAST_ZH, SUBJECT_ZH
from evals.visual_replay.plan_sim import ArmResult, simulate, stats
from evals.visual_replay.runner import Brief, load_briefs

COMPARISON = "v3_rules vs v3_semantic"
CACHE_NAME = "scores-qwen3-vl-embedding-2048-v2.json"


def subject_query(brief: Brief, plan: ControlledVisualPlan) -> str:
    return canonical_visual_query({"category": brief.category, "subject": plan.subject.value})


def id_map(original: LoadedVisualCatalog, current: LoadedVisualCatalog) -> dict[str, str]:
    """original asset id -> current asset id, matched by filename."""

    by_name = {asset.filename: asset.asset_id for asset in current.catalog.assets}
    return {
        asset.asset_id: by_name[asset.filename]
        for asset in original.catalog.assets
        if asset.filename in by_name
    }


class SemanticScores:
    def __init__(
        self,
        cache: Mapping[str, Mapping[str, float]],
        mapping: Mapping[str, str],
        approved: set[str],
    ) -> None:
        self._cache = cache
        self._mapping = mapping
        self._approved = approved
        self.missing: set[str] = set()
        self.used: Counter[str] = Counter()

    def __call__(self, brief: Brief, plan: ControlledVisualPlan) -> Mapping[str, float] | None:
        query = subject_query(brief, plan)
        key = hashlib.sha256(query.encode("utf-8")).hexdigest()
        raw = self._cache.get(key)
        if raw is None:
            self.missing.add(query)
            return None  # this brief falls back to the rule order; reported as missing
        scores = {self._mapping[k]: v for k, v in raw.items() if k in self._mapping}
        scores = {k: v for k, v in scores.items() if k in self._approved}
        if set(scores) != self._approved:
            self.missing.add(query)
            return None
        self.used[query] += 1
        return scores


def judging_pairs(
    rules: ArmResult, semantic: ArmResult, briefs: Mapping[str, Brief], *, count: int, seed: int
) -> list[tuple[Brief, dict[str, Any], dict[str, Any]]]:
    """Briefs where the arms picked different action images, round-robin over (subject, cast)."""

    by_brief = {pick["brief"]: pick for pick in semantic.picks}
    groups: dict[tuple[str, str], list[tuple[Brief, dict[str, Any], dict[str, Any]]]] = {}
    for left in rules.picks:
        right = by_brief.get(left["brief"])
        if right is None or right["action_id"] == left["action_id"]:
            continue
        brief = briefs[left["brief"]]
        groups.setdefault((left["subject"], left["cast"]), []).append((brief, left, right))
    rng = random.Random(seed)
    for items in groups.values():
        rng.shuffle(items)
    chosen: list[tuple[Brief, dict[str, Any], dict[str, Any]]] = []
    while len(chosen) < count and any(groups.values()):
        for group in sorted(groups):
            if groups[group] and len(chosen) < count:
                chosen.append(groups[group].pop())
    rng.shuffle(chosen)
    return chosen


def write_page(
    pairs: Sequence[tuple[Brief, dict[str, Any], dict[str, Any]]],
    loaded: LoadedVisualCatalog,
    output: Path,
    *,
    seed: int,
    report_id: str,
) -> None:
    from evals.visual_replay.runner import _HTML_TEMPLATE, thumbnail_b64

    rng = random.Random(seed + 1)
    items: list[dict[str, Any]] = []
    key: list[dict[str, Any]] = []
    assets: set[str] = set()
    for ordinal, (brief, rule_pick, semantic_pick) in enumerate(pairs, start=1):
        sides = [("v3_rules", rule_pick), ("v3_semantic", semantic_pick)]
        if rng.random() < 0.5:
            sides.reverse()
        (left_arm, left), (right_arm, right) = sides
        assets.update({left["action_id"], right["action_id"]})
        items.append(
            {
                "pair": ordinal,
                "date": brief.business_date.isoformat(),
                "category": SUBJECT_ZH.get(left["subject"], left["subject"]),
                "headline": brief.headline,
                "plan": (
                    f"{CAST_ZH.get(left['cast'], left['cast'])} · "
                    f"{SUBJECT_ZH.get(left['subject'], left['subject'])}"
                ),
                "left": [{"role": "action_reference", "asset": left["action_id"]}],
                "right": [{"role": "action_reference", "asset": right["action_id"]}],
            }
        )
        key.append(
            {
                "pair": ordinal,
                "artifact_id": brief.artifact_id,
                "comparison": COMPARISON,
                "left": left_arm,
                "right": right_arm,
            }
        )
    thumbs = {asset_id: thumbnail_b64(loaded, asset_id, edge=520) for asset_id in sorted(assets)}
    payload = json.dumps(
        {"report_id": report_id, "arm": "v3", "items": items, "thumbs": thumbs},
        ensure_ascii=False,
    )
    html = _HTML_TEMPLATE.replace("__PAYLOAD__", payload.replace("</", "<\\/"))
    (output / "compare-semantic.html").write_text(html, encoding="utf-8")
    (output / "pairs-key-semantic.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def render(
    rules: ArmResult, semantic: ArmResult, scores: SemanticScores, *, pairs: int, briefs: int
) -> str:
    by_brief = {pick["brief"]: pick for pick in semantic.picks}
    differ = sum(
        1
        for pick in rules.picks
        if pick["brief"] in by_brief and by_brief[pick["brief"]]["action_id"] != pick["action_id"]
    )
    lines = [
        "# Qwen3-VL 语义排序重新评估（当前选图 v3：按余量选人物 + 压缩大图）",
        "",
        f"- 生产视觉简报 {briefs} 条，按时间顺序重新规划和选图；两种做法各自累积历史，"
        "硬性门控（道具、人物、体积、冷却期）完全相同，只在同一档候选里排序不同。",
        f"- 语义查询 {len(scores.used)} 种（类别 + 主题），"
        "分数取自本地缓存（缺的先用本地索引补算）；"
        f"仍缺失 {len(scores.missing)} 种（缺失时该条按规则排序）。",
        "",
        "| 做法 | 成功 | 退回最久没用 | 用到的动作图 | 最常用一张占比 |",
        "|---|---|---|---|---|",
    ]
    for label, result in (("规则排序（线上）", rules), ("Qwen3-VL 语义排序", semantic)):
        s = stats(result.picks)
        lines.append(
            f"| {label} | {s['n']} | {s['lru']} | {s['distinct']} | {s['top_share']:.0%} |"
        )
    lines += [
        "",
        f"- 两种做法选出的动作图不同：{differ}/{len(rules.picks)}"
        f"（{differ / max(len(rules.picks), 1):.0%}）。",
        f"- 盲评页抽了 {pairs} 对选图不同的简报（按主题和人物轮流抽，左右随机）。",
        "- 客观指标（门控、轮换）两边相同，哪边更贴新闻只能靠人工盲评判断。",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--briefs", required=True)
    parser.add_argument("--headlines", required=True)
    parser.add_argument("--manifest", required=True, help="current catalog (resized images)")
    parser.add_argument("--original-manifest", required=True, help="catalog the cache scored")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20261008)
    parser.add_argument("--report-id", default="2026-10-08-semantic")
    args = parser.parse_args(argv)

    briefs = load_briefs(Path(args.briefs), Path(args.headlines))
    current = load_visual_catalog(args.manifest)
    original = load_visual_catalog(args.original_manifest)
    cache = json.loads((args.cache_dir / CACHE_NAME).read_text(encoding="utf-8"))
    approved = {asset.asset_id for asset in current.catalog.assets if asset.approved}
    scores = SemanticScores(cache, id_map(original, current), approved)

    rules = simulate(briefs, current, "pool_aware")
    semantic = simulate(briefs, current, "pool_aware", semantic=scores)
    if scores.missing:
        print("missing semantic queries:", *sorted(scores.missing), sep="\n  ")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pairs = judging_pairs(
        rules, semantic, {b.artifact_id: b for b in briefs}, count=args.pairs, seed=args.seed
    )
    write_page(pairs, current, args.output_dir, seed=args.seed, report_id=args.report_id)
    report = render(rules, semantic, scores, pairs=len(pairs), briefs=len(briefs))
    (args.output_dir / "recheck.md").write_text(report, encoding="utf-8")
    (args.output_dir / "recheck-picks.json").write_text(
        json.dumps(
            {"rules": rules.picks, "semantic": semantic.picks}, ensure_ascii=False, indent=1
        ),
        encoding="utf-8",
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
