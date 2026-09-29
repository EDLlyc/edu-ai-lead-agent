# ruff: noqa: RUF001
from __future__ import annotations

from evals.copy_replay.runner import (
    DraftOutcome,
    VariantResult,
    render_markdown,
    reuses_recent_brand_phrase,
    summarize_variant,
)

HISTORY = ("在赛先生，我们用思维链教学法引导孩子——AI不直接给答案，而是展示完整的思考过程",)


def _draft(
    claim: str, *, errors: list[str] | None = None, accepted: bool | None = True
) -> DraftOutcome:
    return DraftOutcome(
        topic="望宇登月服研制已攻克数十项关键技术",
        validation_errors=errors or [],
        validation_warnings=["copy_length"],
        audit_accepted=None if errors else accepted,
        audit_issues=[],
        brand_claims=[claim],
        reuses_recent_phrase=reuses_recent_brand_phrase([claim], HISTORY),
        copywriting=claim,
    )


def test_recent_phrase_reuse_ignores_punctuation_and_needs_eight_characters() -> None:
    assert reuses_recent_brand_phrase(["赛先生科学的AI不直接给答案，而是一步步引导"], HISTORY)
    assert not reuses_recent_brand_phrase(["“真动手”强调孩子亲自接触材料"], HISTORY)
    assert not reuses_recent_brand_phrase(["任何句子"], ())


def test_variant_summary_and_markdown() -> None:
    old = VariantResult(
        "v24",
        [
            _draft("在赛先生，AI不直接给答案，而是展示完整的思考过程"),
            _draft(
                "在赛先生，AI不直接给答案，而是展示完整的思考过程", errors=["claim_not_in_copy"]
            ),
        ],
    )
    new = VariantResult(
        "v25",
        [
            _draft("“真动手”强调孩子亲自接触材料"),
            _draft("“真表达”重视孩子说清观察", accepted=False),
        ],
    )

    old_summary, new_summary = summarize_variant(old), summarize_variant(new)
    report = {
        "business_date": "2026-09-28",
        "topics": 2,
        "variants": [old_summary, new_summary],
        "drafts": {
            result.prompt_version: [
                {
                    "topic": draft.topic,
                    "brand_claims": draft.brand_claims,
                    "validation_errors": draft.validation_errors,
                    "audit_accepted": draft.audit_accepted,
                    "reuses_recent_phrase": draft.reuses_recent_phrase,
                }
                for draft in result.drafts
            ]
            for result in (old, new)
        },
    }
    markdown = render_markdown(report)

    assert old_summary["reuses_recent_brand_phrase"] == 2
    assert old_summary["validation_passed"] == 1
    assert old_summary["most_repeated_phrase"] is not None
    assert new_summary["reuses_recent_brand_phrase"] == 0
    assert new_summary["audit_accepted"] == 1
    assert "| 沿用近期品牌话术 | 2 | 0 |" in markdown
    assert "整条初稿校验失败:claim_not_in_copy" in markdown
    assert "整条初稿审核未通过" in markdown
