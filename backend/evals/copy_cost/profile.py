"""Where do the copy prompts spend their tokens? (no chat-model call)

For recent accepted production topics, rebuild the exact generator and auditor prompts the copy
worker sends (same locked topic, same brand retrieval), split them into their tagged sections and
report characters per section. Token counts are estimated by scaling characters to the measured
production average prompt tokens given on the command line.

The auditor needs a draft; a deterministic offline draft stands in for it, and the DRAFT section
is reported separately (its real size is close to the generator's output).
"""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from evals.copy_quality.runner import dates_between, load_accepted_topics

TAGS = (
    "OUTPUT_SCHEMA",
    "EVIDENCE",
    "BRAND",
    "REPAIR",
    "REQUIRED_EXACT_CLAIMS",
    "RECENT_BRAND_CLAIMS",
    "PREVIOUS",
    "DRAFT",
)
# Sections start on a new line; the instructions mention tag names inline ("引用<EVIDENCE>中的").
_SECTION = re.compile(r"(?:^|\n)<(" + "|".join(TAGS) + r")>(.*?)</\1>", re.S)


def split_sections(prompt: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for match in _SECTION.finditer(prompt):
        sections[match.group(1)] = match.group(2)
    sections["instructions"] = _SECTION.sub("", prompt)
    return sections


def field_split(section: str, text_fields: set[str]) -> tuple[int, int]:
    """Characters in free-text fields vs metadata keys/values of a JSON list section."""
    try:
        items = json.loads(section)
    except json.JSONDecodeError:
        return len(section), 0
    if not isinstance(items, list):
        return len(section), 0
    text = sum(
        len(str(item.get(key) or ""))
        for item in items
        if isinstance(item, dict)
        for key in text_fields
    )
    return text, len(section) - text


def render(
    rows: dict[str, list[dict[str, Any]]],
    *,
    real_tokens: dict[str, float],
    topics: int,
    embedding_calls: int,
) -> str:
    lines = [
        "# 文案提示词成本剖析",
        "",
        f"- 选题 {topics} 条（生产上真实通过的），按线上同样的方式重新拼出生成与审查提示词；"
        f"不调用大模型，只做了 {embedding_calls} 次品牌检索向量调用。",
        "- token 为估算：各段字符数 × （线上实测平均输入 token ÷ 平均总字符数）。",
        "",
    ]
    for kind, samples in rows.items():
        total_chars = sum(sample["total"] for sample in samples) / len(samples)
        ratio = real_tokens[kind] / total_chars if real_tokens.get(kind) else None
        lines += [
            f"## {'生成' if kind == 'generator' else '审查'}提示词",
            "",
            f"- 平均 {total_chars:,.0f} 字符；"
            f"线上实测平均输入 {real_tokens.get(kind, 0):,.0f} token。",
            "",
            "| 部分 | 平均字符 | 占比 | 估算 token |",
            "|---|---|---|---|",
        ]
        averages: dict[str, float] = defaultdict(float)
        for sample in samples:
            for name, size in sample["sections"].items():
                averages[name] += size / len(samples)
        for name, size in sorted(averages.items(), key=lambda item: -item[1]):
            tokens = f"{size * ratio:,.0f}" if ratio else "–"
            lines.append(f"| {name} | {size:,.0f} | {size / total_chars:.0%} | {tokens} |")
        brand_text = sum(sample["brand_text"] for sample in samples) / len(samples)
        brand_meta = sum(sample["brand_meta"] for sample in samples) / len(samples)
        evidence_text = sum(sample["evidence_text"] for sample in samples) / len(samples)
        evidence_meta = sum(sample["evidence_meta"] for sample in samples) / len(samples)
        chunks = sum(sample["brand_chunks"] for sample in samples) / len(samples)
        lines += [
            "",
            f"- BRAND 平均 {chunks:.1f} 段：正文 {brand_text:,.0f} 字符，字段名和元数据 "
            f"{brand_meta:,.0f} 字符。",
            f"- EVIDENCE：引文与治理事实 {evidence_text:,.0f} 字符，字段名和元数据 "
            f"{evidence_meta:,.0f} 字符。",
            "",
        ]
    return "\n".join(lines)


async def collect(args: argparse.Namespace) -> tuple[dict[str, list[dict[str, Any]]], int, int]:
    import httpx
    from app.application.ports.copy_generation import (
        DraftAuditRequest,
        DraftGenerationRequest,
        RecentBrandUsage,
    )
    from app.application.services.copy_generation import (
        BRAND_ROTATION_CLAIM_LIMIT,
        BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS,
        BRAND_ROTATION_LOOKBACK_DAYS,
        BrandRagContextRetriever,
        build_auditor_prompt,
        build_copy_version_bundle,
        build_generator_prompt,
    )
    from app.core.config import get_settings
    from app.infrastructure.ai.copy_generation import DeterministicFakeMaterialDraftGenerator
    from app.infrastructure.ai.factory import (
        create_brand_embedding_model,
        select_brand_embedding_client,
    )
    from app.infrastructure.db.brand_knowledge import PostgresBrandKnowledgeRepository
    from app.infrastructure.db.copy_generation import load_recent_brand_usage_before
    from app.infrastructure.db.session import create_engine, create_session_factory
    from sqlalchemy import text

    settings = get_settings()
    bundle = build_copy_version_bundle(settings, scoring_profile=settings.content_scoring_profile)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    client = httpx.AsyncClient(follow_redirects=False)
    rows: dict[str, list[dict[str, Any]]] = {"generator": [], "auditor": []}
    embedding_calls = 0
    try:
        topics = []
        history: dict[date, RecentBrandUsage] = {}
        seen: set[UUID] = set()
        async with session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            for day in dates_between(args.date_from, args.date_to):
                for run_id, topic in await load_accepted_topics(session, day, args.limit):
                    if topic.selected_event_id is None or topic.selected_event_id in seen:
                        continue
                    seen.add(topic.selected_event_id)
                    topics.append((run_id, topic))
                history[day] = await load_recent_brand_usage_before(
                    session,
                    run_id=UUID(int=0),
                    business_date=day - timedelta(days=1),
                    timezone=settings.business_timezone,
                    lookback_days=BRAND_ROTATION_LOOKBACK_DAYS - 1,
                    claim_limit=BRAND_ROTATION_CLAIM_LIMIT,
                )
            await session.rollback()
        topics = topics[: args.limit]
        retriever = BrandRagContextRetriever(
            repository=PostgresBrandKnowledgeRepository(session_factory),
            embeddings=create_brand_embedding_model(
                settings,
                client=select_brand_embedding_client(
                    settings, zhipu_client=client, alibaba_client=client
                ),
            ),
            limit=settings.copy_brand_context_limit,
            retrieval_version=settings.brand_retrieval_version,
        )
        rotation = bundle.generator_prompt_version in BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS
        fake = DeterministicFakeMaterialDraftGenerator(model="profile-placeholder")
        for run_id, topic in topics:
            recent = history.get(topic.business_date, RecentBrandUsage())
            brand = (
                await retriever.retrieve_for_copy(topic, recent_usage=recent)
                if rotation
                else await retriever.retrieve_for_copy(topic)
            )
            embedding_calls += 1
            generation_request = DraftGenerationRequest(
                run_id=run_id,
                topic=topic,
                brand_context=brand,
                version_bundle=bundle,
                draft_version=1,
                max_output_tokens=settings.copy_max_output_tokens,
                recent_brand_claims=recent.claim_texts if rotation else (),
            )
            placeholder = (await fake.generate(generation_request)).draft
            for item in topic.evidence:
                print(
                    json.dumps(
                        {
                            "evidence_stats": True,
                            "topic": str(topic.selected_event_id)[:8],
                            "evidence": len(topic.evidence),
                            "quote_chars": len(item.exact_quote or ""),
                            "governed_chars": len(item.governed_statement or ""),
                            "ascii_share": round(
                                sum(ch.isascii() for ch in (item.exact_quote or ""))
                                / max(len(item.exact_quote or ""), 1),
                                2,
                            ),
                        }
                    ),
                    file=sys.stderr,
                )
            for kind, prompt in (
                ("generator", build_generator_prompt(generation_request)),
                (
                    "auditor",
                    build_auditor_prompt(
                        DraftAuditRequest(
                            run_id=run_id,
                            draft_version_id=UUID(int=0),
                            topic=topic,
                            brand_context=brand,
                            draft=placeholder,
                            version_bundle=bundle,
                            max_output_tokens=settings.copy_audit_max_output_tokens,
                        )
                    ),
                ),
            ):
                sections = split_sections(prompt)
                brand_text, brand_meta = field_split(sections.get("BRAND", "[]"), {"text"})
                evidence_text, evidence_meta = field_split(
                    sections.get("EVIDENCE", "[]"), {"exact_quote", "governed_statement"}
                )
                rows[kind].append(
                    {
                        "total": len(prompt),
                        "sections": {name: len(body) for name, body in sections.items()},
                        "brand_text": brand_text,
                        "brand_meta": brand_meta,
                        "brand_chunks": len(brand),
                        "evidence_text": evidence_text,
                        "evidence_meta": evidence_meta,
                    }
                )
    finally:
        await client.aclose()
        await engine.dispose()
    return rows, len(topics), embedding_calls


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--generator-tokens", type=float, required=True)
    parser.add_argument("--auditor-tokens", type=float, required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    rows, topics, embedding_calls = asyncio.run(collect(args))
    report = render(
        rows,
        real_tokens={"generator": args.generator_tokens, "auditor": args.auditor_tokens},
        topics=topics,
        embedding_calls=embedding_calls,
    )
    if args.output:
        with open(args.output, "w", encoding="utf-8") as stream:
            stream.write(report)
    print(report, file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
