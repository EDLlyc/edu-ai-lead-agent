"""Turn operator edits of human picks into a before/after dataset.

The human-pick review flow keeps every saved edit in material_packages.copy_snapshot
['operator_edits'] (model_copywriting = the model's accepted text, copywriting = the text after
the edit) and the pushed text in ['operator_push']. Each edited package becomes one example:
the model's hook, the operator's final hook, whether hashtags changed and whether it was pushed.

Uses: a human gold set for the hook judge and the auditor (did they flag what people changed?),
and retrieved few-shot examples for the generator. Reads through the read-only ops role. The
output holds copy text, so it stays out of git.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


def example_from_snapshot(snapshot: Mapping[str, Any], *, title: str) -> dict[str, Any] | None:
    """One example per edited package, or None when the package has no operator edit."""

    from app.schemas.copy_generation import extract_headline_hook, extract_trailing_hashtags

    edits = snapshot.get("operator_edits")
    if not isinstance(edits, list) or not edits:
        return None
    first, last = edits[0], edits[-1]
    model_text = str(first.get("model_copywriting") or "")
    final_text = str(last.get("copywriting") or "")
    raw_push = snapshot.get("operator_push")
    push: Mapping[str, Any] | None = raw_push if isinstance(raw_push, dict) else None
    model_hook = extract_headline_hook(model_text, title=title)
    final_hook = extract_headline_hook(final_text, title=title)
    return {
        "copy_run_id": first.get("copy_run_id"),
        "draft_version_id": first.get("draft_version_id"),
        "title": title,
        "edit_count": len(edits),
        "first_edited_at": first.get("edited_at"),
        "model_hook": model_hook,
        "final_hook": final_hook,
        "hook_changed": model_hook.strip() != final_hook.strip(),
        "hook_similarity": round(SequenceMatcher(None, model_hook, final_hook).ratio(), 3),
        "hashtags_changed": extract_trailing_hashtags(model_text)
        != extract_trailing_hashtags(final_text),
        "rule_warnings": list(last.get("rule_issue_codes") or []),
        "pushed": bool(push),
        "pushed_text_matches_final": push is not None
        and str(push.get("copywriting") or "") == final_text,
    }


def summarize(examples: Sequence[Mapping[str, Any]]) -> str:
    total = len(examples)
    if not total:
        return "# 运营修改数据\n\n还没有运营修改过的人工加推稿。\n"
    hooks = sum(1 for example in examples if example["hook_changed"])
    tags = sum(1 for example in examples if example["hashtags_changed"])
    pushed = sum(1 for example in examples if example["pushed"])
    similarity = sorted(
        example["hook_similarity"] for example in examples if example["hook_changed"]
    )
    median = similarity[len(similarity) // 2] if similarity else None
    return "\n".join(
        [
            "# 运营修改数据",
            "",
            f"- 被运营修改过的人工加推稿 {total} 份，其中已推送 {pushed} 份。",
            f"- 改了引导语 {hooks} 份，改了标签 {tags} 份。",
            f"- 改过的引导语与模型原句的相似度中位数：{median if median is not None else '—'}"
            "（1 = 没改，越小改得越多）。",
            "",
        ]
    )


async def load(date_from: date, date_to: date) -> list[dict[str, Any]]:
    from app.infrastructure.db.models import (
        CopyGenerationRunModel,
        EventClusterVersionModel,
        MaterialPackageModel,
    )
    from app.infrastructure.db.ops_reader import (
        create_ops_engine,
        ops_database_url,
        verify_read_only_role,
    )
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_ops_engine(ops_database_url(os.environ))
    try:
        await verify_read_only_role(engine)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        package, run, version = (
            MaterialPackageModel,
            CopyGenerationRunModel,
            EventClusterVersionModel,
        )
        async with factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            rows = (
                await session.execute(
                    select(package.copy_snapshot, version.representative_title)
                    .join(run, run.id == package.run_id)
                    .outerjoin(version, version.id == run.selected_event_version_id)
                    .where(
                        run.business_date >= date_from,
                        run.business_date <= date_to,
                        package.copy_snapshot.has_key("operator_edits"),
                    )
                    .order_by(package.created_at)
                )
            ).all()
            await session.rollback()
    finally:
        await engine.dispose()
    examples = []
    for snapshot, title in rows:
        example = example_from_snapshot(snapshot or {}, title=title or "")
        if example is not None:
            examples.append(example)
    return examples


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, default=None, help="JSON Lines file (not in git)")
    args = parser.parse_args(argv)
    examples = asyncio.run(load(args.date_from, args.date_to))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(example, ensure_ascii=False) + "\n" for example in examples),
            encoding="utf-8",
        )
    print(summarize(examples))
    print(f"generated at {datetime.now().isoformat(timespec='seconds')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
