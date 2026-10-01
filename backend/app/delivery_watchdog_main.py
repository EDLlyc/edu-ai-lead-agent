"""Delivery watchdog: alert when a slot did not go out as planned.

Runs a few minutes after each slot's target time (cron). For today's slot it checks, through the
read-only ops role:
- the slot's topic run succeeded and selected its full count;
- every copy run of the slot was accepted;
- every WeCom delivery job of the slot is delivered.
Any miss produces one short alert. The alert goes to a dedicated ops webhook
(OPS_ALERT_WEBHOOK_KEY, a separate internal group, never the formal delivery group); without a
key it is only logged. Every check writes one JSON line, and an alert is sent once per slot and day.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.application.services.ops_tools import CopyRunsResult, DeliveriesResult, SlotRunsResult

TZ = ZoneInfo("Asia/Shanghai")
SLOT_LABELS = {"morning": "早间", "noon": "午间", "evening": "晚间"}
WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


@dataclass(slots=True)
class SlotCheck:
    business_date: date
    slot: str
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def message(self) -> str:
        label = SLOT_LABELS.get(self.slot, self.slot)
        lines = [f"【推送告警】{self.business_date.isoformat()} {label}推送异常："]
        lines += [f"- {problem}" for problem in self.problems]
        lines.append("可在运维助手里问“今天" + label + "为什么没发”查看详情。")
        return "\n".join(lines)


def check_slot(
    business_date: date,
    slot: str,
    slots: SlotRunsResult,
    copies: CopyRunsResult,
    deliveries: DeliveriesResult,
) -> SlotCheck:
    result = SlotCheck(business_date, slot)
    slot_runs = [run for run in slots.runs if run.content_slot == slot]
    if not slot_runs:
        result.problems.append("没有找到这个时段的选题运行")
        return result
    run = slot_runs[-1]
    if run.status != "succeeded":
        result.problems.append(f"选题运行状态 {run.status}（{run.error_code or '无错误码'}）")
    if run.unfilled_count:
        reasons = "、".join(run.unfilled_reason_codes) or "未说明"
        result.problems.append(f"选题少了 {run.unfilled_count} 条（{reasons}）")
    for copy in (item for item in copies.runs if item.content_slot == slot):
        if copy.status != "accepted":
            title = (copy.title or "")[:24]
            result.problems.append(
                f"第 {copy.ordinal} 条文案 {copy.status}"
                f"（{copy.error_code or '无错误码'}）：{title}"
            )
    jobs = [job for job in deliveries.deliveries if job.content_slot == slot]
    expected = run.selected_count
    delivered = sum(1 for job in jobs if job.status == "delivered")
    if delivered < expected:
        stuck = [
            f"第 {job.sequence_ordinal} 条 {job.status}"
            + (f"（{job.last_error_code}）" if job.last_error_code else "")
            for job in jobs
            if job.status != "delivered"
        ]
        detail = "；".join(stuck) if stuck else "没有发送任务"
        result.problems.append(f"已送达 {delivered}/{expected}：{detail}")
    return result


async def load(business_date: date) -> tuple[SlotRunsResult, CopyRunsResult, DeliveriesResult]:
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
        return (
            await reader.list_slot_runs(business_date),
            await reader.list_copy_runs(business_date, 30),
            await reader.list_deliveries(business_date),
        )
    finally:
        await engine.dispose()


async def send_alert(text: str, key: str) -> bool:
    import httpx

    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.post(
            WEBHOOK_URL, params={"key": key}, json={"msgtype": "text", "text": {"content": text}}
        )
    try:
        return response.status_code == 200 and response.json().get("errcode") == 0
    except ValueError:
        return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", choices=sorted(SLOT_LABELS), required=True)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="never send, only log")
    args = parser.parse_args(argv)
    business_date = args.date or datetime.now(UTC).astimezone(TZ).date()
    slots, copies, deliveries = asyncio.run(load(business_date))
    check = check_slot(business_date, args.slot, slots, copies, deliveries)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    marker = args.output_dir / f"alerted-{business_date.isoformat()}-{args.slot}"
    key = os.environ.get("OPS_ALERT_WEBHOOK_KEY", "").strip()
    sent: bool | None = None
    if not check.ok and not marker.exists() and key and not args.dry_run:
        sent = asyncio.run(send_alert(check.message(), key))
        if sent:
            marker.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    record = {
        "checked_at": datetime.now(UTC).isoformat(),
        "business_date": business_date.isoformat(),
        "slot": args.slot,
        "ok": check.ok,
        "problems": check.problems,
        "alert_channel": "webhook" if key else "log_only",
        "sent": sent,
    }
    with (args.output_dir / f"watchdog-{business_date.isoformat()}.jsonl").open(
        "a", encoding="utf-8"
    ) as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False), file=sys.stderr)
    if not check.ok:
        print(check.message())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
