# ruff: noqa: RUF001, E501
"""Qwen3-VL as a judge of generated images: right characters, nothing broken, usable.

    # judge (paid; outside slot hours)
    python -m evals.image_qa.judge run --sample-dir tmp/image-qa/2026-10-08 \\
        --catalog-root private/brand-materials \\
        --references "05-visual-assets/<xiaosai full body>.png,05-visual-assets/<sai full body>.png" \\
        --models qwen3-vl-plus,qwen3-vl-flash
    # score against the person's labels (free)
    python -m evals.image_qa.judge score --sample-dir tmp/image-qa/2026-10-08 \\
        --labels <export.json> --report evals/image_qa/reports/2026-10-08-image-qa.md

The judge sees the two characters' reference looks, the plan (who should appear, the subject)
and the generated image, and answers in a closed JSON schema. Raw verdicts stay in the sample
directory (tmp/, never committed); the report has aggregates only.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from evals.asset_labels.client import ChatModel, DashScopeVL, image_data_url

Character = Literal["xiaosai", "sai_xiansheng", "other_character"]
BrokenReason = Literal["identity_drift", "garbled_text", "anatomy", "prop_wrong", "other"]
CAST_CHARACTERS = {
    "xiaosai_solo": {"xiaosai"},
    "sai_xiansheng_solo": {"sai_xiansheng"},
    "duo": {"xiaosai", "sai_xiansheng"},
}
CAST_ZH = {"xiaosai_solo": "只有小赛", "sai_xiansheng_solo": "只有赛先生", "duo": "小赛和赛先生"}
PROMPT_VERSION = "image-qa-judge-v1"


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    characters_seen: list[Character] = Field(max_length=4)
    cast_ok: bool
    broken: bool
    broken_reasons: list[BrokenReason] = Field(default_factory=list, max_length=5)
    usable: bool
    note: str = Field(default="", max_length=120)


class InvalidVerdict(ValueError):
    pass


def prompt(cast: str, subject: str) -> str:
    return (
        "你是科普品牌配图的质检员。前两张是品牌角色的参考形象：第一张是“小赛”"
        "（白蓝配色的机器人猫头鹰，大圆眼睛，不戴护目镜），第二张是“赛先生”"
        "（棕色头发的猫头鹰，戴橙色护目镜，穿白色实验服）。最后一张是要检查的生成配图。\n"
        f"这张配图计划出现的角色：{CAST_ZH.get(cast, cast)}；主题：{subject}。\n"
        "逐项检查：\n"
        "1. characters_seen：图里出现了哪些角色（xiaosai、sai_xiansheng；"
        "其他人物或拟人角色记为 other_character；背景里的机器、设备不算角色）。\n"
        "2. cast_ok：出现的角色是否和计划完全一致（不多、不少、没把一个角色画成另一个）。\n"
        "3. broken：有没有明显画坏。broken_reasons 从下面选：identity_drift（角色外形和参考明显不符，"
        "例如小赛戴了护目镜或长了头发、赛先生没有护目镜）、garbled_text（画面中文字乱码、错字）、"
        "anatomy（肢体、五官明显畸形）、prop_wrong（道具和主题明显不符）、other。\n"
        "4. usable：整体能不能直接发布。\n"
        "只输出一个 JSON 对象，不要其他文字："
        '{"characters_seen":[...],"cast_ok":true,"broken":false,"broken_reasons":[],'
        '"usable":true,"note":"一句话说明"}'
    )


def parse_verdict(text: str) -> Verdict:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match is None:
        raise InvalidVerdict("no JSON object")
    try:
        return Verdict.model_validate_json(match.group(0))
    except ValidationError as error:
        raise InvalidVerdict(str(error.errors()[:2])) from None


@dataclass(slots=True)
class Judged:
    verdict: Verdict | None
    calls: int
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    error: str | None = None


def judge_image(
    model: ChatModel,
    *,
    image: Path,
    references: Sequence[Path],
    cast: str,
    subject: str,
) -> Judged:
    content: list[dict[str, Any]] = [
        {"type": "image_url", "image_url": {"url": image_data_url(path, edge=512)}}
        for path in references
    ]
    content.append({"type": "image_url", "image_url": {"url": image_data_url(image, edge=768)}})
    content.append({"type": "text", "text": prompt(cast, subject)})
    judged = Judged(verdict=None, calls=0, prompt_tokens=0, completion_tokens=0, seconds=0.0)
    for _attempt in range(2):
        result = model.complete(content)
        judged.calls += 1
        judged.prompt_tokens += result.prompt_tokens
        judged.completion_tokens += result.completion_tokens
        judged.seconds += result.seconds
        try:
            judged.verdict = parse_verdict(result.text)
            judged.error = None
            return judged
        except InvalidVerdict as error:
            judged.error = str(error)[:200]
            content = [
                *content[:-1],
                {
                    "type": "text",
                    "text": prompt(cast, subject) + "\n上次输出不合格式，只输出 JSON。",
                },
            ]
    return judged


# ---------------------------------------------------------------- scoring


def _problem(label: Mapping[str, Any]) -> dict[str, bool | None]:
    """The person's answers as 'problem' flags (None when unanswered)."""

    def flag(key: str, problem_value: str) -> bool | None:
        value = label.get(key)
        return None if value is None else value == problem_value

    return {
        "cast": flag("cast", "wrong"),
        "broken": flag("broken", "yes"),
        "unusable": flag("usable", "no"),
    }


def _judge_problem(verdict: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "cast": not verdict["cast_ok"],
        "broken": bool(verdict["broken"]),
        "unusable": not verdict["usable"],
    }


@dataclass(slots=True)
class Confusion:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, truth: bool, predicted: bool) -> None:
        if truth and predicted:
            self.tp += 1
        elif predicted:
            self.fp += 1
        elif truth:
            self.fn += 1
        else:
            self.tn += 1

    def line(self) -> str:
        precision = self.tp / (self.tp + self.fp) if self.tp + self.fp else None
        recall = self.tp / (self.tp + self.fn) if self.tp + self.fn else None
        false_alarm = self.fp / (self.fp + self.tn) if self.fp + self.tn else None

        def pct(value: float | None) -> str:
            return "-" if value is None else f"{value:.0%}"

        return (
            f"{self.tp + self.fn} | {self.tp} | {self.fp} | {pct(precision)} | {pct(recall)} | "
            f"{pct(false_alarm)} | {self.tp + self.tn}/{self.tp + self.fp + self.fn + self.tn}"
        )


def score(
    labels: Sequence[Mapping[str, Any]], verdicts: Mapping[str, Mapping[str, Any]]
) -> dict[str, Confusion]:
    table = {key: Confusion() for key in ("cast", "broken", "unusable")}
    for label in labels:
        verdict = verdicts.get(str(label["image"]))
        if verdict is None:
            continue
        truth = _problem(label)
        predicted = _judge_problem(verdict)
        for key, value in truth.items():
            if value is not None:
                table[key].add(value, predicted[key])
    return table


QUESTION_ZH = {"cast": "人物不对", "broken": "画坏了", "unusable": "不能发"}


def render(
    labels: Sequence[Mapping[str, Any]],
    runs: Mapping[str, Mapping[str, Any]],
) -> str:
    positives = {key: sum(1 for label in labels if _problem(label)[key]) for key in QUESTION_ZH}
    lines = [
        "# 配图质检：Qwen3-VL 判图 vs 人工标注",
        "",
        f"- 线上生成的配图 {len(labels)} 张（三种人物组合各 16 张，选图 v2 与 v3 时期都有），"
        f"负责人逐张标注。人工认为有问题：人物不对 {positives['cast']}、画坏了 {positives['broken']}、"
        f"不能发 {positives['unusable']}。",
        f"- 判图提示词 {PROMPT_VERSION}：参考形象两张 + 计划人物和主题 + 生成图，输出固定格式 JSON。",
        "",
    ]
    for model, run in runs.items():
        verdicts = run["verdicts"]
        table = score(labels, verdicts)
        cost = run["usage"]
        lines += [
            f"## {model}",
            "",
            f"- 调用 {cost['calls']} 次（含格式重试），平均每张 {cost['seconds'] / max(len(verdicts), 1):.1f} 秒，"
            f"输入 {cost['prompt_tokens']:,} / 输出 {cost['completion_tokens']:,} token；"
            f"判不出 {cost['invalid']} 张。",
            "",
            "| 问题 | 人工判有 | 抓到 | 误报 | 准确率 | 召回率 | 误报率（无问题图） | 一致 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        lines += [f"| {QUESTION_ZH[key]} | {table[key].line()} |" for key in QUESTION_ZH]
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- CLI


def _run(args: argparse.Namespace) -> int:
    sample = json.loads((args.sample_dir / "sample.json").read_text(encoding="utf-8"))
    references = [args.catalog_root / item.strip() for item in args.references.split(",")]
    for model_name in [m.strip() for m in args.models.split(",") if m.strip()]:
        out = args.sample_dir / f"verdicts-{model_name}.json"
        existing: dict[str, Any] = (
            json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        )
        verdicts: dict[str, Any] = existing.get("verdicts", {})
        usage = existing.get(
            "usage",
            {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0, "invalid": 0},
        )
        model = DashScopeVL(model_name)
        try:
            for item in sample:
                if item["image"] in verdicts or usage["calls"] >= args.max_calls:
                    continue
                judged = judge_image(
                    model,
                    image=args.sample_dir / "images" / f"{item['image']}.png",
                    references=references,
                    cast=item["cast"],
                    subject=item["subject"],
                )
                usage["calls"] += judged.calls
                usage["prompt_tokens"] += judged.prompt_tokens
                usage["completion_tokens"] += judged.completion_tokens
                usage["seconds"] += judged.seconds
                if judged.verdict is None:
                    usage["invalid"] += 1
                    continue
                verdicts[item["image"]] = judged.verdict.model_dump()
                out.write_text(
                    json.dumps(
                        {
                            "model": model_name,
                            "prompt": PROMPT_VERSION,
                            "usage": usage,
                            "verdicts": verdicts,
                        },
                        ensure_ascii=False,
                        indent=1,
                    ),
                    encoding="utf-8",
                )
        finally:
            model.close()
        print(f"{model_name}: {len(verdicts)} verdicts, {usage['calls']} calls")
    return 0


def _score(args: argparse.Namespace) -> int:
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))["labels"]
    runs = {
        json.loads(path.read_text(encoding="utf-8"))["model"]: json.loads(
            path.read_text(encoding="utf-8")
        )
        for path in sorted(args.sample_dir.glob("verdicts-*.json"))
    }
    report = render(labels, runs)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(report, encoding="utf-8")
    print(report)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--sample-dir", type=Path, required=True)
    run.add_argument("--catalog-root", type=Path, required=True)
    run.add_argument("--references", required=True, help="two paths: Xiaosai, Sai")
    run.add_argument("--models", default="qwen3-vl-plus,qwen3-vl-flash")
    run.add_argument("--max-calls", type=int, default=110)
    scoring = sub.add_parser("score")
    scoring.add_argument("--sample-dir", type=Path, required=True)
    scoring.add_argument("--labels", required=True)
    scoring.add_argument("--report", default=None)
    args = parser.parse_args(argv)
    return _run(args) if args.command == "run" else _score(args)


if __name__ == "__main__":
    raise SystemExit(main())
