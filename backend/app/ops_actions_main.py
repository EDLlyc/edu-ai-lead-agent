"""Operator command line for approved ops actions (see app/application/services/ops_actions.py).

    python -m app.ops_actions_main --log /out/action-proposals.jsonl list
    python -m app.ops_actions_main --log ... approve <id> --by <operator>
    python -m app.ops_actions_main --log ... reject <id> --by <operator> [--note ...]
    python -m app.ops_actions_main --log ... verify [--min-age-minutes 10]

Execution uses the application's database role and only runs with OPS_ACTIONS_ENABLED=true;
otherwise an approval is recorded and nothing changes (propose-only).
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.application.services.ops_actions import (
    ActionLog,
    ActionRefused,
    approve,
    proposal_lines,
    reject,
    verify,
)


def actions_enabled(environ: dict[str, str] | os._Environ[str]) -> bool:
    return environ.get("OPS_ACTIONS_ENABLED", "").strip().lower() == "true"


async def _approve(log: ActionLog, proposal_id: str, by: str) -> str:
    from app.core.config import get_settings
    from app.infrastructure.db.ops_actions import retry_delivery_executor
    from app.infrastructure.db.session import create_engine, create_session_factory

    enabled = actions_enabled(os.environ)
    if not enabled:
        return await approve(
            log, proposal_id, by=by, now=datetime.now(UTC), enabled=False, execute=_never
        )
    settings = get_settings()
    engine = create_engine(settings)
    try:
        executor = retry_delivery_executor(create_session_factory(engine), settings)
        return await approve(
            log, proposal_id, by=by, now=datetime.now(UTC), enabled=True, execute=executor
        )
    finally:
        await engine.dispose()


async def _never(_proposal: object) -> dict[str, object]:
    raise AssertionError("actions are disabled")


async def _verify(log: ActionLog, min_age: timedelta) -> list[tuple[str, str]]:
    from app.core.config import get_settings
    from app.infrastructure.db.ops_actions import delivery_status_reader
    from app.infrastructure.db.session import create_engine, create_session_factory

    engine = create_engine(get_settings())
    try:
        reader = delivery_status_reader(create_session_factory(engine))
        return await verify(log, now=datetime.now(UTC), read_status=reader, min_age=min_age)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--all", action="store_true")
    for name in ("approve", "reject"):
        command = commands.add_parser(name)
        command.add_argument("id")
        command.add_argument("--by", required=True)
        if name == "reject":
            command.add_argument("--note", default="")
    check = commands.add_parser("verify")
    check.add_argument("--min-age-minutes", type=int, default=10)
    args = parser.parse_args(argv)
    log = ActionLog(args.log)

    if args.command == "list":
        proposals = [
            proposal
            for proposal in log.proposals().values()
            if args.all or proposal.status in {"proposed", "approved"}
        ]
        for proposal, line in zip(proposals, proposal_lines(proposals), strict=True):
            print(f"[{proposal.status}] {line}")
        if not proposals:
            print("没有待处理的提案")
        print(f"执行开关：{'开' if actions_enabled(os.environ) else '关（只记录批准，不执行）'}")
        return 0
    try:
        if args.command == "approve":
            status = asyncio.run(_approve(log, args.id, args.by))
            print(f"#{args.id} → {status}")
            return 0 if status in {"approved", "executed"} else 1
        if args.command == "reject":
            reject(log, args.id, by=args.by, now=datetime.now(UTC), note=args.note)
            print(f"#{args.id} → rejected")
            return 0
        outcomes = asyncio.run(_verify(log, timedelta(minutes=args.min_age_minutes)))
        for proposal_id, outcome in outcomes:
            print(f"#{proposal_id} → {outcome}")
        if not outcomes:
            print("没有需要核对的已执行提案")
        return 0
    except ActionRefused as refused:
        print(f"拒绝：{refused}（{refused.code}）", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
