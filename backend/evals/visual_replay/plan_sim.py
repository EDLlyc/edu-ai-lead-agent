"""Sequential replay of planning plus selector v3 over production visual briefs.

Unlike runner.py (which keeps the plans production stored), this re-plans every brief in time
order with the controlled planner, then selects references with selector v3, carrying each arm's
own plan and action history forward. Arms:

- baseline: today's planner (no knowledge of the action pool);
- pool_aware: the planner penalizes a subject+cast whose fresh action pool is empty or low;
- pool_aware_compressed: pool_aware, and every action image over 3.5 MB counted at 3.5 MB, as if
  the oversized PNGs were re-encoded.

Reported per arm: how often selector v3 had to reuse a cooled image (least recently used), how many
distinct action images were used and the most-used image's share, overall and per cast. No model
calls; the catalog is the private manifest.
"""

# ruff: noqa: RUF001, E501

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.content_slots import ContentSlot
from app.domain.image_generation import IMAGE_REFERENCE_BUDGET_BYTES
from app.domain.visual_assets import (
    AssetSelectionRequest,
    VisualAssetRole,
    action_pool_capacity,
)
from app.domain.visual_brief import VisualCategory
from app.domain.visual_diversity import (
    VISUAL_SELECTOR_V3_VERSION,
    ControlledVisualPlan,
    RecentVisualPlan,
    build_visual_plan_bundle,
)
from app.infrastructure.brand.visual_catalog import (
    LoadedVisualCatalog,
    load_visual_catalog,
    select_visual_assets,
)

from evals.visual_replay.runner import Brief, load_briefs

TZ = ZoneInfo("Asia/Shanghai")
ARMS = ("baseline", "pool_aware", "pool_aware_compressed")
COMPRESSED_BYTES = 3_500_000
HISTORY_DAYS = 7


def slot_of(created_at: str) -> ContentSlot:
    hour = datetime.fromisoformat(created_at).astimezone(TZ).hour
    if hour < 10:
        return ContentSlot.MORNING
    if hour < 15:
        return ContentSlot.NOON
    return ContentSlot.EVENING


@dataclass(slots=True)
class ArmResult:
    picks: list[dict[str, Any]] = field(default_factory=list)
    errors: int = 0


def compressed(loaded: LoadedVisualCatalog) -> LoadedVisualCatalog:
    assets = tuple(
        replace(asset, byte_size=min(asset.byte_size, COMPRESSED_BYTES))
        if VisualAssetRole.ACTION_REFERENCE in asset.roles
        else asset
        for asset in loaded.catalog.assets
    )
    return replace(loaded, catalog=replace(loaded.catalog, assets=assets))


SemanticScores = Callable[[Brief, ControlledVisualPlan], Mapping[str, float] | None]


def simulate(
    briefs: Sequence[Brief],
    loaded: LoadedVisualCatalog,
    arm: str,
    *,
    semantic: SemanticScores | None = None,
) -> ArmResult:
    """`semantic` (optional) gives the selector's in-tier semantic scores for a brief and plan."""

    catalog = compressed(loaded) if arm == "pool_aware_compressed" else loaded
    result = ArmResult()
    history: list[tuple[RecentVisualPlan, str]] = []
    for brief in briefs:
        slot = slot_of(brief.created_at)
        window = [
            item
            for item in history
            if brief.business_date - timedelta(days=HISTORY_DAYS - 1)
            <= item[0].business_date
            <= brief.business_date
        ]
        sequence = tuple(action for _, action in window)
        capacity = (
            action_pool_capacity(
                catalog.catalog,
                recent_action_sequence=sequence,
                max_reference_bytes=IMAGE_REFERENCE_BUDGET_BYTES,
            )
            if arm != "baseline"
            else None
        )
        try:
            bundle = build_visual_plan_bundle(
                category=VisualCategory(brief.category),
                business_date=brief.business_date,
                content_slot=slot,
                stable_seed=brief.run_id,
                recent=tuple(plan for plan, _ in window),
                history_days=HISTORY_DAYS,
                action_capacity=capacity,
            )
            plan = bundle.primary
            selection = select_visual_assets(
                catalog,
                AssetSelectionRequest(
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
                    max_references=3,
                    max_reference_bytes=IMAGE_REFERENCE_BUDGET_BYTES,
                    selection_seed=f"{brief.run_id}:primary:{plan.fingerprint}",
                    recent_action_sequence=sequence,
                ),
                selector_version=VISUAL_SELECTOR_V3_VERSION,
                max_references=3,
                max_reference_bytes=IMAGE_REFERENCE_BUDGET_BYTES,
                semantic_scores=semantic(brief, plan) if semantic is not None else None,
            )
        except Exception:  # count, keep going: the arm's history simply does not grow
            result.errors += 1
            continue
        action = next(
            (
                item
                for item in selection.selected_assets
                if item.role is VisualAssetRole.ACTION_REFERENCE
            ),
            None,
        )
        if action is None:
            result.errors += 1
            continue
        result.picks.append(
            {
                "cast": plan.cast.value,
                "subject": plan.subject.value,
                "action": action.filename,
                "action_id": action.asset_id,
                "brief": brief.artifact_id,
                "lru": "cooldown exhausted" in action.reason,
            }
        )
        history.append(
            (
                RecentVisualPlan(
                    business_date=brief.business_date,
                    content_slot=slot,
                    plan_fingerprint=plan.fingerprint,
                    scene=plan.scene,
                    composition=plan.composition,
                    camera=plan.camera,
                    cast=plan.cast,
                    subject=plan.subject,
                ),
                action.asset_id,
            )
        )
    return result


def stats(picks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not picks:
        return {"n": 0}
    counts = Counter(pick["action"] for pick in picks)
    return {
        "n": len(picks),
        "lru": sum(pick["lru"] for pick in picks),
        "distinct": len(counts),
        "top_share": counts.most_common(1)[0][1] / len(picks),
    }


def render(results: dict[str, ArmResult], briefs: int) -> str:
    lines = [
        "# 选图回放：人物计划是否考虑素材余量",
        "",
        f"- 生产视觉简报 {briefs} 条，按时间顺序重新规划和选图；每个方案各自累积历史。",
        "- 退回最久没用 = 选图时该主题加人物的可用图全在冷却期，只能重复用最久没用的那张。",
        "",
        "| 方案 | 成功 | 退回最久没用 | 用到的动作图 | 最常用一张占比 | 两人 / 赛先生 / 小赛 | 出错 |",
        "|---|---|---|---|---|---|---|",
    ]
    labels = {
        "baseline": "现在的规则",
        "pool_aware": "按余量选人物",
        "pool_aware_compressed": "按余量 + 压缩大图",
    }
    for arm, result in results.items():
        overall = stats(result.picks)
        casts = Counter(pick["cast"] for pick in result.picks)
        lines.append(
            f"| {labels[arm]} | {overall['n']} | {overall['lru']}（{overall['lru'] / max(overall['n'], 1):.0%}） | "
            f"{overall['distinct']} | {overall['top_share']:.0%} | "
            f"{casts.get('duo', 0)} / {casts.get('sai_xiansheng_solo', 0)} / {casts.get('xiaosai_solo', 0)} | {result.errors} |"
        )
    lines += [
        "",
        "## 按人物",
        "",
        "| 方案 | 人物 | 次数 | 退回最久没用 | 用到的动作图 | 最常用一张占比 |",
        "|---|---|---|---|---|---|",
    ]
    for arm, result in results.items():
        by_cast: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for pick in result.picks:
            by_cast[pick["cast"]].append(pick)
        for cast in ("duo", "sai_xiansheng_solo", "xiaosai_solo"):
            item = stats(by_cast.get(cast, []))
            if item["n"]:
                lines.append(
                    f"| {labels[arm]} | {cast} | {item['n']} | {item['lru']} | {item['distinct']} | {item['top_share']:.0%} |"
                )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--briefs", required=True)
    parser.add_argument("--headlines", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    briefs = load_briefs(Path(args.briefs), Path(args.headlines))
    loaded = load_visual_catalog(args.manifest)
    results = {arm: simulate(briefs, loaded, arm) for arm in ARMS}
    report = render(results, len(briefs))
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        args.output.with_suffix(".json").write_text(
            json.dumps(
                {arm: result.picks for arm, result in results.items()}, ensure_ascii=False, indent=1
            ),
            encoding="utf-8",
        )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
