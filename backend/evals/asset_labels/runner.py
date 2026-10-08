"""Can Qwen3-VL label a brand image the way the catalog does? Offline eval on the 41 assets.

Ground truth is the private manifest (characters for every asset; props, poses and scene tags for
action images, as the builder and the reviewed metadata set them). Each asset is labelled from the
image alone (no filename), with one reference image per character. Per-asset outputs stay in
`tmp/` (private); the report holds aggregates only.

    python -m evals.asset_labels.runner \\
        --manifest /root/projects/edu-ai-lead-agent/private/brand-materials/visual-assets.manifest.json \\
        --references <xiao-sai full body>,<sai-xiansheng full body> \\
        --models qwen3-vl-plus,qwen3-vl-flash \\
        --raw-dir /root/projects/edu-ai-lead-agent/tmp/asset-labels \\
        --report evals/asset_labels/reports/2026-10-08-asset-labels.md
"""

# ruff: noqa: RUF001, E501

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.asset_labels.client import ChatModel, DashScopeVL, label_image
from evals.asset_labels.labels import CHARACTERS, PROPS, AssetLabels, Scorecard, Truth, score


@dataclass(slots=True)
class ModelRun:
    model: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    capped: bool = False


def run_model(
    model: ChatModel,
    assets: Sequence[dict[str, Any]],
    root: Path,
    *,
    references: Sequence[str],
    calls_left: Callable[[], int],
    spend: Callable[[int], None],
) -> ModelRun:
    run = ModelRun(model=model.name)
    reference_paths = [root / path for path in references]
    for asset in assets:
        if calls_left() < 2:
            # Keep what was labelled; the report says the run stopped at the cap.
            run.capped = True
            break
        outcome = label_image(model, root / asset["relative_path"], references=reference_paths)
        spend(outcome.calls)
        run.calls += outcome.calls
        run.prompt_tokens += outcome.prompt_tokens
        run.completion_tokens += outcome.completion_tokens
        run.seconds += outcome.seconds
        run.rows.append(
            {
                "relative_path": asset["relative_path"],
                "is_reference": asset["relative_path"] in references,
                "truth": {
                    k: sorted(asset.get(k) or [])
                    for k in ("characters", "props", "poses", "scene_tags")
                }
                | {"asset_kind": asset.get("asset_kind")},
                "labels": outcome.labels.model_dump() if outcome.labels else None,
                "calls": outcome.calls,
                "error": outcome.error,
            }
        )
    return run


def card_of(run: ModelRun) -> Scorecard:
    pairs = []
    for row in run.rows:
        labels = AssetLabels.model_validate(row["labels"]) if row["labels"] else None
        truth = Truth(
            asset_kind=row["truth"]["asset_kind"],
            characters=frozenset(row["truth"]["characters"]),
            props=frozenset(row["truth"]["props"]),
            poses=frozenset(row["truth"]["poses"]),
            scene_tags=frozenset(row["truth"]["scene_tags"]),
        )
        pairs.append((labels, truth))
    return score(pairs)


def _confusions(run: ModelRun, field_name: str, *, action_only: bool) -> Counter[str]:
    """Counts of 'truth → predicted' for mismatched sets (ids only, no brand text)."""

    pairs: Counter[str] = Counter()
    for row in run.rows:
        if row["labels"] is None:
            continue
        if action_only and row["truth"]["asset_kind"] != "action":
            continue
        truth = sorted(row["truth"][field_name])
        predicted = sorted(row["labels"][field_name])
        if truth != predicted:
            pairs[f"{','.join(truth) or '∅'} → {','.join(predicted) or '∅'}"] += 1
    return pairs


def render(runs: Sequence[ModelRun], *, assets: int, actions: int) -> str:
    in_set = max((sum(bool(row["is_reference"]) for row in run.rows) for run in runs), default=0)
    lines = [
        "# Qwen3-VL 品牌素材自动打标签（离线评测，2026-10-08）",
        "",
        f"- 素材 {assets} 张（动作图 {actions} 张、形象图 {assets - actions} 张），标准答案是现有私有素材清单"
        "（人物、道具经人工确认；动作和场景标签来自清单生成规则，偏粗）。",
        f"- 每张图只给图片本身（不给文件名），另附每个角色一张全身参考图（其中 {in_set} 张本身也在被测素材里）。",
        "- 道具、动作、场景只在动作图上评；形象图按清单惯例固定为无道具、无动作、场景 brand。",
        "",
        "| 指标 | " + " | ".join(run.model for run in runs) + " |",
        "|---|" + "---|" * len(runs),
    ]

    def row(label: str, fn: Callable[[ModelRun, Scorecard], str]) -> None:
        lines.append(f"| {label} | " + " | ".join(fn(r, card_of(r)) for r in runs) + " |")

    def pct(a: int, b: int) -> str:
        return f"{a}/{b}（{a / b:.0%}）" if b else "-"

    row("已标注 / 触达调用上限", lambda r, c: f"{len(r.rows)} / {'是' if r.capped else '否'}")
    row("非法输出（重试后仍不合法）", lambda r, c: str(c.invalid))
    row("调用次数 / 平均耗时", lambda r, c: f"{r.calls} / {r.seconds / max(r.calls, 1):.1f}s")
    row(
        "平均输入 / 输出 token",
        lambda r, c: (
            f"{r.prompt_tokens // max(r.calls, 1):,} / {r.completion_tokens // max(r.calls, 1)}"
        ),
    )
    row("形象图 / 动作图分类正确", lambda r, c: pct(c.kind_correct, c.kind_total))
    row("人物完全正确", lambda r, c: pct(c.characters.exact, c.characters.total))
    row("人物 精确率 / 召回率", lambda r, c: "{:.0%} / {:.0%}".format(*c.characters.micro()))
    row("道具完全正确（动作图）", lambda r, c: pct(c.props.exact, c.props.total))
    row("道具 精确率 / 召回率", lambda r, c: "{:.0%} / {:.0%}".format(*c.props.micro()))
    row("动作 精确率 / 召回率（粗标）", lambda r, c: "{:.0%} / {:.0%}".format(*c.poses.micro()))
    row(
        "场景 精确率 / 召回率（粗标）", lambda r, c: "{:.0%} / {:.0%}".format(*c.scene_tags.micro())
    )
    for run in runs:
        card = card_of(run)
        lines += ["", f"## {run.model}：错在哪里", ""]
        per_character = card.characters.per_value(CHARACTERS)
        lines.append(
            "- 人物（对/多标/漏标）："
            + "；".join(f"{k} {tp}/{fp}/{fn}" for k, (tp, fp, fn) in per_character.items())
        )
        per_prop = card.props.per_value(PROPS)
        lines.append(
            "- 道具（对/多标/漏标）："
            + "；".join(f"{k} {tp}/{fp}/{fn}" for k, (tp, fp, fn) in sorted(per_prop.items()))
        )
        for field_name, action_only, label in (
            ("characters", False, "人物错配"),
            ("props", True, "道具错配"),
        ):
            confusions = _confusions(run, field_name, action_only=action_only)
            if confusions:
                lines.append(
                    f"- {label}（标准 → 模型）："
                    + "；".join(f"{k} ×{v}" for k, v in confusions.most_common())
                )
    return "\n".join(lines) + "\n"


REFERENCES_HELP = (
    "comma-separated full-body images, one per character (xiao-sai first), relative to the "
    "materials folder; kept out of the repo because file names are private"
)


def split_references(raw: str, root: Path, parser: argparse.ArgumentParser) -> list[str]:
    references = [part.strip() for part in raw.split(",") if part.strip()]
    if len(references) != len(CHARACTERS):
        parser.error(f"--references needs {len(CHARACTERS)} images, one per character")
    missing = [path for path in references if not (root / path).is_file()]
    if missing:
        parser.error(f"{len(missing)} reference image(s) not found under the materials folder")
    return references


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--references", default="", help=REFERENCES_HELP)
    parser.add_argument("--models", default="qwen3-vl-plus,qwen3-vl-flash")
    parser.add_argument("--max-calls", type=int, default=120)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--from-raw", action="store_true", help="re-render saved runs")
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = [a for a in manifest["assets"] if a.get("approved")]
    root = args.manifest.parent
    args.raw_dir.mkdir(parents=True, exist_ok=True)
    runs: list[ModelRun] = []
    names = [name.strip() for name in args.models.split(",") if name.strip()]
    if args.from_raw:
        for name in names:
            data = json.loads((args.raw_dir / f"{name}.json").read_text(encoding="utf-8"))
            runs.append(ModelRun(**data))
    else:
        references = split_references(args.references, root, parser)
        budget = {"left": args.max_calls}

        def spend(n: int) -> None:
            budget["left"] -= n

        for name in names:
            model = DashScopeVL(name)
            try:
                run = run_model(
                    model,
                    assets,
                    root,
                    references=references,
                    calls_left=lambda: budget["left"],
                    spend=spend,
                )
            finally:
                model.close()
            (args.raw_dir / f"{name}.json").write_text(
                json.dumps(_as_dict(run), ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            runs.append(run)
    actions = sum(1 for a in assets if a.get("asset_kind") == "action")
    report = render(runs, assets=len(assets), actions=actions)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    print(report)
    return 0


def _as_dict(run: ModelRun) -> dict[str, Any]:
    return {
        "model": run.model,
        "rows": run.rows,
        "calls": run.calls,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "seconds": run.seconds,
        "capped": run.capped,
    }


if __name__ == "__main__":
    raise SystemExit(main())
