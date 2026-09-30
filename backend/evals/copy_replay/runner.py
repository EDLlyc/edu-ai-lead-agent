# ruff: noqa: RUF001  (Chinese operator-facing report text)
"""A/B the Moments copy generator on real accepted topics without persisting anything.

For each accepted slot copy of a business date, the locked topic and evidence are re-loaded
read-only and one first draft per generator prompt version is generated, validated and audited
(no repair, no database writes). Brand-rotation versions see the brand statements of accepted
copy before the day plus the drafts this replay already produced, like sequential production.
This spends real model calls: about two per topic per variant.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any
from uuid import UUID

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
    _compact_brand_text,
    _phrase_windows,
    build_copy_version_bundle,
)
from app.application.services.quality_report import most_repeated_brand_phrase
from app.core.config import get_settings
from app.domain.copy_generation import (
    ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION,
    HEADLINE_HOOK_COPY_RULE_VERSIONS,
    STANDALONE_HEADING_COPY_RULE_VERSIONS,
    LockedTopicContext,
    apply_copy_audit_policy,
    validate_material_draft,
)
from app.domain.quality_report import BrandStatementRow
from app.infrastructure.ai.copy_generation import create_zhipu_copy_models
from app.infrastructure.ai.factory import (
    create_brand_embedding_model,
    select_brand_embedding_client,
)
from app.infrastructure.db.brand_knowledge import PostgresBrandKnowledgeRepository
from app.infrastructure.db.copy_generation import (
    load_governed_event_evidence,
    load_locked_topic_origin,
    load_recent_brand_usage_before,
)
from app.infrastructure.db.models import CopyGenerationRunModel, EventClusterVersionModel
from app.infrastructure.db.session import create_engine, create_session_factory
from app.schemas.copy_generation import (
    append_copy_news_source_footer,
    normalize_copy_standalone_heading,
    render_headline_hook_copy,
)
from pydantic import SecretStr
from sqlalchemy import select, text

REPORT_VERSION = "copy-replay-v1"
# Each generator prompt runs with the auditor and preview rule it shipped with.
_PAIRED_VERSIONS = {
    "moments-generator-v24-standalone-heading": (
        "moments-auditor-v19-standalone-heading",
        "preview-v12-standalone-heading-advisory",
    ),
    "moments-generator-v25-brand-rotation": (
        "moments-auditor-v19-standalone-heading",
        "preview-v12-standalone-heading-advisory",
    ),
    "moments-generator-v26-headline-hook": (
        "moments-auditor-v20-headline-hook",
        "preview-v13-headline-hook",
    ),
    "moments-generator-v27-lean-context": (
        "moments-auditor-v21-lean-context",
        "preview-v13-headline-hook",
    ),
    "moments-generator-v28-shared-quotes": (
        "moments-auditor-v21-lean-context",
        "preview-v13-headline-hook",
    ),
}


@dataclass(slots=True)
class DraftOutcome:
    topic: str
    validation_errors: list[str]
    validation_warnings: list[str]
    audit_accepted: bool | None
    audit_issues: list[str]
    brand_claims: list[str]
    reuses_recent_phrase: bool
    copywriting: str


@dataclass(slots=True)
class VariantResult:
    prompt_version: str
    drafts: list[DraftOutcome] = field(default_factory=list)


def reuses_recent_brand_phrase(claims: Sequence[str], history: Sequence[str]) -> bool:
    """True when a brand claim shares an 8-character run with brand text used before the day."""

    windows = set().union(*(_phrase_windows(text) for text in history)) if history else set()
    return any(window in _compact_brand_text(claim) for claim in claims for window in windows)


def summarize_variant(result: VariantResult) -> dict[str, object]:
    drafts = result.drafts
    statements = [
        BrandStatementRow(run_id=str(index), business_date=date.min, label=None, text=claim)
        for index, draft in enumerate(drafts)
        for claim in draft.brand_claims
    ]
    phrase = most_repeated_brand_phrase(statements)
    audited = [draft for draft in drafts if draft.audit_accepted is not None]
    return {
        "prompt_version": result.prompt_version,
        "drafts": len(drafts),
        "validation_passed": sum(not draft.validation_errors for draft in drafts),
        "audit_accepted": sum(bool(draft.audit_accepted) for draft in audited),
        "validation_error_codes": dict(
            Counter(code for draft in drafts for code in draft.validation_errors)
        ),
        "warning_codes": dict(
            Counter(code for draft in drafts for code in draft.validation_warnings)
        ),
        "audit_issue_codes": dict(Counter(code for draft in drafts for code in draft.audit_issues)),
        "reuses_recent_brand_phrase": sum(draft.reuses_recent_phrase for draft in drafts),
        "most_repeated_phrase": (
            {"phrase": phrase.phrase, "drafts": phrase.runs}
            if phrase and phrase.runs >= 2
            else None
        ),
    }


async def _load_topics(session: Any, business_date: date, limit: int) -> list[tuple[Any, ...]]:
    runs = (
        await session.scalars(
            select(CopyGenerationRunModel)
            .where(
                CopyGenerationRunModel.business_date == business_date,
                CopyGenerationRunModel.status == "accepted",
                CopyGenerationRunModel.decision_kind == "selected",
                CopyGenerationRunModel.content_slot_selection_id.is_not(None),
            )
            .order_by(CopyGenerationRunModel.created_at)
            .limit(limit)
        )
    ).all()
    topics = []
    for run in runs:
        version = await session.get(EventClusterVersionModel, run.selected_event_version_id)
        evidence = await load_governed_event_evidence(
            session,
            version,
            include_governed_statement=run.pipeline_version
            == ENGLISH_EVIDENCE_COPY_PIPELINE_VERSION,
        )
        raw_summary = version.summary_projection.get("summary")
        topic = LockedTopicContext(
            origin=await load_locked_topic_origin(session, run),
            business_date=run.business_date,
            timezone=run.timezone,
            scoring_profile=run.scoring_profile,
            decision_kind=run.decision_kind,
            selected_event_id=run.selected_event_id,
            selected_event_version_id=run.selected_event_version_id,
            no_topic_code=None,
            title=version.representative_title,
            summary=raw_summary if isinstance(raw_summary, str) else None,
            evidence=evidence,
        )
        topics.append((run.id, topic))
    return topics


async def run_replay(
    *, business_date: date, prompt_versions: Sequence[str], limit: int
) -> dict[str, object]:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    client = httpx.AsyncClient(follow_redirects=False)
    try:
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
        if settings.ai_platform_base_url is None or settings.ai_platform_api_key is None:
            raise RuntimeError("the copy replay needs the Zhipu copy provider settings")
        generator, auditor = create_zhipu_copy_models(
            client=client,
            base_url=settings.ai_platform_base_url,
            api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
            model=settings.ai_chat_model,
            connect_timeout_seconds=settings.ai_connect_timeout_seconds,
            read_timeout_seconds=settings.ai_read_timeout_seconds,
            total_timeout_seconds=settings.ai_total_timeout_seconds,
            concurrency=settings.ai_provider_concurrency,
            max_attempts=settings.ai_max_attempts,
            max_input_characters=settings.ai_max_input_characters,
            max_output_tokens=settings.copy_max_output_tokens,
            max_validation_corrections=settings.ai_max_validation_corrections,
        )
        async with session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            topics = await _load_topics(session, business_date, limit)
            # History strictly before the day, so the replayed day starts from what production
            # had seen; the replay then adds its own drafts as it goes.
            history = await load_recent_brand_usage_before(
                session,
                run_id=UUID(int=0),
                business_date=business_date.fromordinal(business_date.toordinal() - 1),
                timezone=settings.business_timezone,
                lookback_days=BRAND_ROTATION_LOOKBACK_DAYS - 1,
                claim_limit=BRAND_ROTATION_CLAIM_LIMIT,
            )
            await session.rollback()
        base_bundle = build_copy_version_bundle(settings, scoring_profile="preview")
        results = []
        for prompt_version in prompt_versions:
            auditor_version, rule_version = _PAIRED_VERSIONS.get(
                prompt_version, (base_bundle.auditor_prompt_version, base_bundle.rule_version)
            )
            bundle = replace(
                base_bundle,
                generator_prompt_version=prompt_version,
                auditor_prompt_version=auditor_version,
                rule_version=rule_version,
            )
            rotation = prompt_version in BRAND_ROTATION_GENERATOR_PROMPT_VERSIONS
            result = VariantResult(prompt_version=prompt_version)
            used_claims: list[str] = []
            used_chunks: list[UUID] = []
            for run_id, topic in topics:
                recent = RecentBrandUsage(
                    chunk_ids=tuple(dict.fromkeys([*used_chunks, *history.chunk_ids])),
                    claim_texts=tuple(dict.fromkeys([*used_claims, *history.claim_texts]))[
                        :BRAND_ROTATION_CLAIM_LIMIT
                    ],
                )
                brand = (
                    await retriever.retrieve_for_copy(topic, recent_usage=recent)
                    if rotation
                    else await retriever.retrieve_for_copy(topic)
                )
                generated = await generator.generate(
                    DraftGenerationRequest(
                        run_id=run_id,
                        topic=topic,
                        brand_context=brand,
                        version_bundle=bundle,
                        draft_version=1,
                        max_output_tokens=settings.copy_max_output_tokens,
                        recent_brand_claims=recent.claim_texts if rotation else (),
                    )
                )
                evidence = topic.evidence[0]
                draft = generated.draft.model_copy(
                    update={
                        "copywriting": render_headline_hook_copy(
                            generated.draft.copywriting,
                            title=topic.title or "",
                            source_name=evidence.source_name,
                            source_url=evidence.source_url,
                        )
                        if bundle.rule_version in HEADLINE_HOOK_COPY_RULE_VERSIONS
                        else append_copy_news_source_footer(
                            normalize_copy_standalone_heading(generated.draft.copywriting),
                            source_name=evidence.source_name,
                            source_url=evidence.source_url,
                            allow_missing_hashtags=bundle.rule_version
                            in STANDALONE_HEADING_COPY_RULE_VERSIONS,
                        )
                    }
                )
                issues = validate_material_draft(
                    draft, topic=topic, brand_context=brand, rule_version=bundle.rule_version
                )
                errors = [issue.code for issue in issues if issue.severity == "error"]
                audit_accepted: bool | None = None
                audit_issues: list[str] = []
                if not errors:
                    audit = await auditor.audit(
                        DraftAuditRequest(
                            run_id=run_id,
                            draft_version_id=run_id,
                            topic=topic,
                            brand_context=brand,
                            draft=draft,
                            version_bundle=bundle,
                            max_output_tokens=settings.copy_audit_max_output_tokens,
                        )
                    )
                    verdict = apply_copy_audit_policy(
                        audit.verdict, rule_version=bundle.rule_version
                    )
                    audit_accepted = verdict.accepted
                    audit_issues = [f"{item.code}:{item.severity}" for item in verdict.issues]
                claims = [claim for claim in draft.claims if claim.kind == "brand_statement"]
                result.drafts.append(
                    DraftOutcome(
                        topic=topic.title or "",
                        validation_errors=errors,
                        validation_warnings=[
                            issue.code for issue in issues if issue.severity != "error"
                        ],
                        audit_accepted=audit_accepted,
                        audit_issues=audit_issues,
                        brand_claims=[claim.text for claim in claims],
                        reuses_recent_phrase=reuses_recent_brand_phrase(
                            [claim.text for claim in claims], history.claim_texts
                        ),
                        copywriting=draft.copywriting,
                    )
                )
                for claim in reversed(claims):
                    used_claims.insert(0, claim.text)
                    used_chunks[:0] = list(claim.brand_chunk_ids)
            results.append(result)
    finally:
        await client.aclose()
        await engine.dispose()
    return {
        "report_version": REPORT_VERSION,
        "business_date": business_date.isoformat(),
        "topics": len(topics),
        "history_brand_claims": list(history.claim_texts),
        "variants": [summarize_variant(result) for result in results],
        "drafts": {
            result.prompt_version: [
                {
                    "topic": draft.topic,
                    "brand_claims": draft.brand_claims,
                    "validation_errors": draft.validation_errors,
                    "audit_accepted": draft.audit_accepted,
                    "reuses_recent_phrase": draft.reuses_recent_phrase,
                    "copywriting": draft.copywriting,
                }
                for draft in result.drafts
            ]
            for result in results
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    variants = report["variants"]
    names = [variant["prompt_version"] for variant in variants]
    rows = (
        ("drafts", "初稿数"),
        ("validation_passed", "规则校验通过"),
        ("audit_accepted", "审核通过（初稿）"),
        ("reuses_recent_brand_phrase", "沿用近期品牌话术"),
    )
    lines = [
        f"# 文案 A/B 回放 {report['business_date']}",
        "",
        f"- 选题 {report['topics']} 条（当天已通过的真实选题），"
        "每个版本只生成初稿，不修复、不写库。",
        "- “沿用近期品牌话术”= 品牌句与当天之前 3 天已发文案的品牌句有 8 字以上连续相同。",
        "",
        "| 指标 | " + " | ".join(names) + " |",
        "|---" * (len(names) + 1) + "|",
    ]
    for key, label in rows:
        lines.append(f"| {label} | " + " | ".join(str(variant[key]) for variant in variants) + " |")
    lines.append(
        "| 本次最常重复的品牌话术 | "
        + " | ".join(
            f"「{variant['most_repeated_phrase']['phrase']}」×{variant['most_repeated_phrase']['drafts']}"
            if variant["most_repeated_phrase"]
            else "无"
            for variant in variants
        )
        + " |"
    )
    lines += ["", "## 每条的品牌句", ""]
    drafts = report["drafts"]
    for index in range(report["topics"]):
        topic = drafts[names[0]][index]["topic"] if drafts[names[0]] else ""
        lines.append(f"- {topic}")
        for name in names:
            draft = drafts[name][index]
            claim = draft["brand_claims"][0] if draft["brand_claims"] else "（无品牌句）"
            flags = []
            if draft["validation_errors"]:
                flags.append("整条初稿校验失败:" + ",".join(draft["validation_errors"]))
            elif draft["audit_accepted"] is False:
                flags.append("整条初稿审核未通过")
            if draft["reuses_recent_phrase"]:
                flags.append("沿用近期话术")
            suffix = f"（{'；'.join(flags)}）" if flags else ""
            lines.append(f"  - `{name}`：{claim[:60]}{suffix}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--prompt-version", action="append", required=True)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--output", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    report = asyncio.run(
        run_replay(business_date=args.date, prompt_versions=args.prompt_version, limit=args.limit)
    )
    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
