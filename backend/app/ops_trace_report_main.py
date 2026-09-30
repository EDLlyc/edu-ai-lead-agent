"""Trace and cost dashboard for the Moments pipeline, as one self-contained HTML file.

For each business date it shows every post end to end (topic rerank, copy generation, audit,
repair, image, long image, WeCom delivery) with model, calls, tokens, latency and status, and a
per-stage, per-model usage table with p50/p95 latency. It reads through the same read-only ops
role and the same `get_day_trace` reader the ops MCP tool uses.

Cost appears only when a price file is given (yuan per million input/output tokens per model);
prices are never guessed.

  OPS_DATABASE_URL=... python -m app.ops_trace_report_main --days 3 --output trace.html
"""

# ruff: noqa: RUF001, E501
# (E501: the HTML template lines are kept whole for readability.)

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.application.services.ops_tools import DayTraceResult, PostTrace, StageSpan

TZ = ZoneInfo("Asia/Shanghai")
STAGE_LABELS = {
    "rerank": "选题重排",
    "generation": "写稿",
    "audit": "审查",
    "repair": "修复重写",
    "workflow": "流程",
    "image": "配图",
    "long_image": "长图",
    "delivery": "发送",
    "news_analysis": "新闻分析",
}
STAGE_COLORS = {
    "rerank": "#8b5cf6",
    "generation": "#2563eb",
    "audit": "#0891b2",
    "repair": "#f59e0b",
    "workflow": "#94a3b8",
    "image": "#16a34a",
    "long_image": "#65a30d",
    "delivery": "#db2777",
}
Prices = Mapping[str, Mapping[str, float]]


def _e(value: object) -> str:
    return html.escape("" if value is None else str(value))


def _local(value: datetime | None) -> str:
    return value.astimezone(TZ).strftime("%H:%M:%S") if value is not None else "—"


def _cost(model: str | None, prompt: int, completion: int, prices: Prices) -> float | None:
    price = prices.get(model or "")
    if price is None:
        return None
    return (prompt * price["input"] + completion * price["output"]) / 1_000_000


def _money(value: float | None) -> str:
    return "未配置单价" if value is None else f"¥{value:.3f}"


def _waterfall(post: PostTrace) -> str:
    points = [
        moment
        for stage in post.stages
        for moment in (stage.started_at, stage.ended_at)
        if moment is not None
    ]
    if post.prepared_at is not None:
        points.append(post.prepared_at)
    if not points:
        return '<p class="muted">没有时间数据</p>'
    start, end = min(points), max(points)
    span = max((end - start).total_seconds(), 1.0)
    rows = []
    for index, stage in enumerate(post.stages):
        if stage.started_at is None:
            continue
        finish = stage.ended_at or stage.started_at
        left = (stage.started_at - start).total_seconds() / span * 100
        width = max((finish - stage.started_at).total_seconds() / span * 100, 0.6)
        color = STAGE_COLORS.get(stage.stage, "#64748b")
        label = STAGE_LABELS.get(stage.stage, stage.stage)
        seconds = (finish - stage.started_at).total_seconds()
        rows.append(
            f'<div class="lane"><span class="lane-label">{_e(label)}</span>'
            f'<span class="track"><span class="bar" style="left:{left:.2f}%;'
            f'width:{min(width, 100 - left):.2f}%;background:{color}" '
            f'title="{_e(label)} {seconds:.1f}s"></span></span>'
            f'<span class="lane-time">{seconds:.1f}s</span></div>'
        )
        del index
    total = (end - start).total_seconds()
    return (
        '<div class="waterfall">'
        + "".join(rows)
        + f'<div class="axis">{_local(start)} → {_local(end)}，共 {total / 60:.1f} 分钟</div></div>'
    )


def _stage_table(stages: Sequence[StageSpan], prices: Prices) -> str:
    body = "".join(
        "<tr>"
        f"<td>{_e(STAGE_LABELS.get(s.stage, s.stage))}</td><td>{_e(s.model or '—')}</td>"
        f"<td>{s.calls}</td><td class='{'bad' if s.failures else ''}'>{s.failures}</td>"
        f"<td>{s.prompt_tokens:,}</td><td>{s.completion_tokens:,}</td>"
        f"<td>{s.latency_ms / 1000:.1f}s</td><td>{_e(s.status or '—')}</td>"
        f"<td>{_money(_cost(s.model, s.prompt_tokens, s.completion_tokens, prices)) if s.prompt_tokens else '—'}</td>"
        "</tr>"
        for s in stages
    )
    return (
        "<table><thead><tr><th>环节</th><th>模型</th><th>调用</th><th>失败</th>"
        "<th>输入 token</th><th>输出 token</th><th>模型耗时</th><th>状态</th><th>成本</th>"
        f"</tr></thead><tbody>{body}</tbody></table>"
    )


def _day(day: DayTraceResult, prices: Prices) -> str:
    calls = sum(row.calls for row in day.usage)
    failures = sum(row.failures for row in day.usage)
    prompt = sum(row.prompt_tokens for row in day.usage)
    completion = sum(row.completion_tokens for row in day.usage)
    costs = [
        _cost(row.model, row.prompt_tokens, row.completion_tokens, prices) for row in day.usage
    ]
    known = [cost for cost in costs if cost is not None]
    delivered = [post for post in day.posts if post.delivered_at is not None]
    lead_times = sorted(
        (post.delivered_at - post.prepared_at).total_seconds() / 60
        for post in delivered
        if post.delivered_at is not None and post.prepared_at is not None
    )
    usage_rows = "".join(
        "<tr>"
        f"<td>{_e(STAGE_LABELS.get(row.stage, row.stage))}</td><td>{_e(row.model)}</td>"
        f"<td>{row.calls}</td><td class='{'bad' if row.failures else ''}'>{row.failures}</td>"
        f"<td>{row.prompt_tokens:,}</td><td>{row.completion_tokens:,}</td>"
        f"<td>{row.p50_latency_ms / 1000:.1f}s</td><td>{row.p95_latency_ms / 1000:.1f}s</td>"
        f"<td>{_money(_cost(row.model, row.prompt_tokens, row.completion_tokens, prices))}</td>"
        "</tr>"
        for row in day.usage
    )
    posts = "".join(
        f'<details class="post"><summary><b>{_e(post.content_slot)} #{post.ordinal}</b> '
        f"{_e(post.title or '（无标题）')}"
        f'<span class="muted"> · 计划 {_local(post.target_at)} · 送达 {_local(post.delivered_at)}</span>'
        f"</summary>{_waterfall(post)}{_stage_table(post.stages, prices)}</details>"
        for post in day.posts
    )
    cost_text = (
        f"¥{sum(known):.2f}" + ("（部分模型未配置单价）" if len(known) < len(costs) else "")
        if known
        else "未配置单价"
    )
    median_lead = f"{lead_times[len(lead_times) // 2]:.0f} 分钟" if lead_times else "—"
    return f"""
<section class="day">
  <h2>{day.business_date.isoformat()}</h2>
  <div class="cards">
    <div class="card"><div class="k">推送</div><div class="v">{len(delivered)}/{len(day.posts)}</div><div class="s">已送达/已选题</div></div>
    <div class="card"><div class="k">模型调用</div><div class="v">{calls}</div><div class="s">失败 {failures}</div></div>
    <div class="card"><div class="k">token</div><div class="v">{(prompt + completion) / 1000:,.0f}k</div><div class="s">输入 {prompt:,} · 输出 {completion:,}</div></div>
    <div class="card"><div class="k">成本</div><div class="v">{_e(cost_text)}</div><div class="s">按单价文件计算</div></div>
    <div class="card"><div class="k">准备到送达</div><div class="v">{median_lead}</div><div class="s">中位数</div></div>
  </div>
  <h3>按环节和模型汇总</h3>
  <table><thead><tr><th>环节</th><th>模型</th><th>调用</th><th>失败</th><th>输入 token</th>
  <th>输出 token</th><th>p50</th><th>p95</th><th>成本</th></tr></thead><tbody>{usage_rows}</tbody></table>
  <h3>每条推送的全链路</h3>
  {posts or '<p class="muted">当天没有定时推送。</p>'}
</section>"""


def render_trace_html(
    days: Sequence[DayTraceResult], *, prices: Prices, generated_at: datetime
) -> str:
    sections = "".join(_day(day, prices) for day in days)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>推送链路追踪</title>
<style>
:root {{ --bg:#f8fafc; --fg:#0f172a; --muted:#64748b; --card:#fff; --line:#e2e8f0; --bad:#dc2626; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#0b1120; --fg:#e2e8f0; --muted:#94a3b8; --card:#111827; --line:#1f2937; --bad:#f87171; }}
}}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
  font:14px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }}
main {{ max-width:1100px; margin:0 auto; }}
h1 {{ font-size:22px; margin:0 0 4px; }} h2 {{ margin:32px 0 12px; }} h3 {{ margin:20px 0 8px; font-size:15px; }}
.muted {{ color:var(--muted); }} .bad {{ color:var(--bad); font-weight:600; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; }}
.card .k {{ color:var(--muted); font-size:12px; }} .card .v {{ font-size:22px; font-weight:700; }}
.card .s {{ color:var(--muted); font-size:12px; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); font-size:13px; margin-bottom:8px; }}
th,td {{ border-bottom:1px solid var(--line); padding:6px 8px; text-align:left; white-space:nowrap; }}
.post {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:8px 12px; margin:8px 0; overflow-x:auto; }}
.post summary {{ cursor:pointer; }}
.waterfall {{ margin:10px 0; }}
.lane {{ display:grid; grid-template-columns:72px 1fr 64px; align-items:center; gap:8px; margin:3px 0; }}
.track {{ position:relative; height:12px; background:var(--line); border-radius:6px; }}
.bar {{ position:absolute; top:0; height:12px; border-radius:6px; }}
.lane-label,.lane-time {{ font-size:12px; color:var(--muted); }}
.axis {{ font-size:12px; color:var(--muted); margin-top:4px; }}
</style></head>
<body><main>
<h1>推送链路追踪</h1>
<p class="muted">生成于 {_local(generated_at)}（北京时间）。数据来自生产库只读账号；
选题重排由同一时段的几条推送共享；成本只按单价文件计算，没有单价的模型不估算。</p>
{sections}
</main></body></html>
"""


async def _load(days: int, until: date) -> list[DayTraceResult]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.infrastructure.db.ops_reader import (
        PostgresOpsReader,
        create_ops_engine,
        ops_database_url,
        verify_read_only_role,
    )

    engine = create_ops_engine(ops_database_url(os.environ))
    try:
        await verify_read_only_role(engine)
        reader = PostgresOpsReader(async_sessionmaker(engine, expire_on_commit=False))
        return [
            await reader.get_day_trace(until - timedelta(days=offset))
            for offset in range(days - 1, -1, -1)
        ]
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--until", type=date.fromisoformat, default=None)
    parser.add_argument("--prices", type=Path, default=None, help="JSON: model -> input/output")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 14:
        parser.error("--days must be between 1 and 14")
    prices: dict[str, dict[str, float]] = (
        json.loads(args.prices.read_text(encoding="utf-8")) if args.prices else {}
    )
    now = datetime.now(UTC)
    until = args.until or now.astimezone(TZ).date()
    days = asyncio.run(_load(args.days, until))
    args.output.write_text(
        render_trace_html(days, prices=prices, generated_at=now), encoding="utf-8"
    )
    print(f"wrote {args.output} ({len(days)} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
