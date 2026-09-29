"""Relaxed advisory long-image review: layout and wording findings no longer drop a poster.

The inputs are the real packages whose long images production refused on 2026-09-16..29.
"""

# ruff: noqa: RUF001 -- Chinese text is the poster's exact rendering contract.

from __future__ import annotations

import pytest
from app.application.services.news_infographic_advisory import (
    AdvisoryCopyError,
    build_advisory_audit_prompt,
    build_advisory_generation_prompt,
    build_advisory_image_prompt,
    build_advisory_rich_copy,
    build_resilient_advisory_rich_copy,
)
from app.application.services.news_infographic_rich_copy import (
    ADVISORY_NEUTRAL_BODY,
    ADVISORY_NEUTRAL_PARENT_GUIDANCE,
    MomentsPackageBinding,
    RichCopyError,
    build_moments_rich_draft_plan,
    build_moments_rich_seed,
    is_frozen_claim_text,
    leading_clause,
)
from app.domain.news_infographic import ValidatedInfographicInput
from test_news_infographic_rich_copy import _binding, _case

HOOK = "当研究发现拖延背后有共同的神经基础，正好和孩子聊聊想忍住不拖延时大脑在经历什么🧠"
PROCRASTINATION_TITLE = "研究揭示非计划冲动性与拖延之间的共享神经遗传基础"
PROCRASTINATION_FACTS = (
    '拖延并非只是"不够努力"或"意志力薄弱",还与个体在长期规划、目标维持、抑制即时诱惑及权衡长远收益'
    "等方面的神经生物学差异相关。",
    "个人经历、生活环境及具体任务情境,同样会对拖延行为产生重要作用。",
)
FEEDBACK_BRAND = (
    "在赛先生科学，我们围绕孩子的提问、操作和表达讨论学习变化，帮助家长看到成长中的具体线索。"
)
LONG_FACT = (
    "中国科学院大连化学物理研究所科研团队在分子筛限域催化与分子扩散机制研究方面取得进展，"
    "提出溶剂门控概念，发现溶剂分子在孔道内的竞争吸附与空间占据可调控反应分子对微孔内部活性位的"
    "实际可达性，相关成果发表在《美国化学会志》上。"
)
SOCRATIC_BRAND = "用苏格拉底式启发教学引导孩子自己拆解和分析问题"


def _package(
    *,
    title: str,
    facts: tuple[str, str],
    brand: str,
    hook: str = HOOK,
    parent: str | None = None,
    second_brand: str = "在赛先生科学，我们用苏格拉底式启发教学引导孩子深度思考而非给出答案",
) -> tuple[ValidatedInfographicInput, MomentsPackageBinding]:
    base = _case(facts, (brand, second_brand))
    payload = base.model_dump(mode="python")
    payload["topic_title"] = title
    payload["copy_prompt_version"] = "moments-generator-v26-headline-hook"
    payload["copywriting"] = (
        f"🔎【小赛洞察】\n{title}\n{hook}\n{base.source_footer}\n#赛先生科学 #科学思维"
    )
    case = ValidatedInfographicInput.model_validate(payload)
    binding = _binding(case)
    if parent is not None:
        snapshot = binding.model_dump(mode="python")
        snapshot["copy_snapshot"]["parent_takeaway"] = parent
        binding = MomentsPackageBinding.model_validate(snapshot)
    return case, binding


def _plan(case: ValidatedInfographicInput, binding: MomentsPackageBinding):  # type: ignore[no-untyped-def]
    seed = build_moments_rich_seed(case, binding, advisory=True)
    return build_moments_rich_draft_plan(case, binding, seed, advisory_layout=True)


def test_headline_without_a_short_phrase_gets_neutral_headings() -> None:
    """2026-09-29 noon#2: no fact shares a phrase with the 24-character headline."""
    case, binding = _package(
        title=PROCRASTINATION_TITLE, facts=PROCRASTINATION_FACTS, brand=FEEDBACK_BRAND
    )

    plan = _plan(case, binding)

    assert plan.title == PROCRASTINATION_TITLE
    assert plan.news_heading == "新闻看点：发生了什么"
    assert plan.child_frame == "和孩子围绕这条新闻讨论："
    assert plan.fact.text == PROCRASTINATION_FACTS[0]
    assert plan.brand.text == FEEDBACK_BRAND
    assert build_advisory_generation_prompt(case, binding)


def test_long_fact_is_shown_by_its_verbatim_leading_clause() -> None:
    """2026-09-27 evening#3: the only bound fact has 110 characters."""
    title = "研究揭示溶剂占据调控分子筛微孔催化扩散机制"
    case, binding = _package(
        title=title,
        facts=(LONG_FACT, LONG_FACT + "这项研究由多家机构合作完成。"),
        brand=FEEDBACK_BRAND,
    )

    plan = _plan(case, binding)

    assert plan.fact.text == (
        "中国科学院大连化学物理研究所科研团队在分子筛限域催化与分子扩散机制研究方面取得进展，"
        "提出溶剂门控概念"
    )
    assert LONG_FACT.startswith(plan.fact.text)
    assert plan.fact.claim_id == "fact-1" and plan.fact.evidence_ids
    copy = build_resilient_advisory_rich_copy(
        case,
        binding,
        {
            "top": "看不见的小孔道里也有门，这条新闻适合和孩子聊聊科学家怎么找规律",
            "news": "值得追问的是溶剂为什么能像门一样起作用",
            "child": "请孩子想一想生活里哪些东西也像一扇会开关的门",
            "brand": "课堂上也会请孩子先说出自己的提问再动手验证",
        },
    )
    assert copy.exact_fact == plan.fact.text
    assert copy.news_body.startswith(plan.fact.text + "。")
    assert build_advisory_image_prompt(case, copy)
    assert build_advisory_audit_prompt(case, binding, copy)


def test_brand_statement_without_a_whole_run_anchor_is_still_used() -> None:
    """2026-09-18 noon#2: the brand sentence is one 22-character run."""
    case, binding = _package(
        title="丁薛祥出席第23届中国－东盟博览会开幕式并会见与会外国政要",
        facts=(
            "在广西期间，丁薛祥还前往中国-东盟国家人工智能应用合作中心调研人工智能合作发展等工作",
            "第23届中国-东盟博览会暨中国-东盟商务与投资峰会于9月17日在广西南宁开幕",
        ),
        brand=SOCRATIC_BRAND,
    )

    plan = _plan(case, binding)

    assert plan.brand.text == SOCRATIC_BRAND
    assert plan.brand_heading == "教学启发：孩子自己拆解和分析问题"
    assert build_advisory_generation_prompt(case, binding)


def test_guidance_with_a_number_is_replaced_not_fatal() -> None:
    """2026-09-19 noon#3: the parent takeaway quoted 5.18亿年前."""
    case, binding = _package(
        title=PROCRASTINATION_TITLE,
        facts=PROCRASTINATION_FACTS,
        brand=FEEDBACK_BRAND,
        parent="一块5.18亿年前的化石能帮科学家解开演化之谜，每一个为什么都能帮孩子打开理解世界的大门。",
    )

    with pytest.raises(RichCopyError, match="guidance is unsafe"):
        build_moments_rich_seed(case, binding)
    seed = build_moments_rich_seed(case, binding, advisory=True)

    assert seed.parent_guidance_review_only == ADVISORY_NEUTRAL_PARENT_GUIDANCE
    assert "5.18" not in build_advisory_generation_prompt(case, binding)


def test_headline_with_a_prompt_like_word_does_not_cost_the_poster() -> None:
    title = "量子密钥分发网络建成 我国科学家取得新突破"
    case, binding = _package(title=title, facts=PROCRASTINATION_FACTS, brand=FEEDBACK_BRAND)

    with pytest.raises(RichCopyError, match="unsafe editorial instructions"):
        build_moments_rich_seed(case, binding)
    seed = build_moments_rich_seed(case, binding, advisory=True)
    plan = build_moments_rich_draft_plan(case, binding, seed, advisory_layout=True)

    assert seed.body_text_review_only == ADVISORY_NEUTRAL_BODY
    # The prompt-like headline is not painted; the title names its safe second half.
    assert plan.title == "和孩子聊聊我国科学家取得新突破"
    assert plan.news_heading == "新闻看点：我国科学家取得新突破"
    assert build_advisory_generation_prompt(case, binding)


def test_source_mismatch_stays_a_hard_failure() -> None:
    case, binding = _package(
        title=PROCRASTINATION_TITLE, facts=PROCRASTINATION_FACTS, brand=FEEDBACK_BRAND
    )
    payload = case.model_dump(mode="python")
    payload["copywriting"] = case.copywriting.replace(case.source_url, case.source_url + "x")
    with pytest.raises(ValueError, match="footer"):
        ValidatedInfographicInput.model_validate(payload)
    other_source = binding.model_copy(update={"source_url": case.source_url + "x"})
    with pytest.raises(RichCopyError, match="does not match accepted package"):
        build_moments_rich_seed(case, other_source, advisory=True)


def test_unusable_model_fields_are_repaired_or_replaced() -> None:
    case, binding = _package(
        title=PROCRASTINATION_TITLE, facts=PROCRASTINATION_FACTS, brand=FEEDBACK_BRAND
    )
    draft = {
        "top": "古人没有文字记录也能用基因当证据还原族群来源……",
        "news": "，值得追问的是大脑在做长期规划时到底发生了什么",
        "child": "请孩子记录一次自己拖延的经过，" + "再想想当时的感受，" * 8 + "最后说给家人听",
        "brand": "新闻来源：某网站 https://example.com",
    }

    with pytest.raises(AdvisoryCopyError):
        build_advisory_rich_copy(case, binding, draft)
    copy = build_resilient_advisory_rich_copy(case, binding, draft)

    assert copy.top_summary == "古人没有文字记录也能用基因当证据还原族群来源"
    assert copy.news_body.endswith("值得追问的是大脑在做长期规划时到底发生了什么")
    assert len(copy.child_body) <= 90 and copy.child_body.endswith("。")
    assert "example.com" not in copy.brand_body
    assert copy.brand_body == FEEDBACK_BRAND + "把这条新闻变成一次可以动手验证的小探究。"
    assert "copy_layout_warning" in copy.warning_codes
    assert build_advisory_image_prompt(case, copy)


@pytest.mark.parametrize("raw", (None, {}, {"top": 1}, "not json"))
def test_missing_model_draft_falls_back_to_the_hook_and_neutral_sentences(raw: object) -> None:
    case, binding = _package(
        title=PROCRASTINATION_TITLE, facts=PROCRASTINATION_FACTS, brand=FEEDBACK_BRAND
    )

    copy = build_resilient_advisory_rich_copy(case, binding, raw)

    assert copy.top_summary == HOOK.removesuffix("🧠")
    assert copy.news_body == (
        PROCRASTINATION_FACTS[0] + "值得追问的是，这件事和我们的生活有什么关系？"
    )
    assert copy.child_body.startswith("和孩子围绕这条新闻讨论：请孩子说一说")
    assert copy.exact_brand == FEEDBACK_BRAND
    assert copy.warning_codes[-1] == "copy_layout_warning"
    assert build_advisory_image_prompt(case, copy)


def test_usable_draft_is_kept_as_written() -> None:
    case, binding = _package(
        title=PROCRASTINATION_TITLE, facts=PROCRASTINATION_FACTS, brand=FEEDBACK_BRAND
    )
    draft = {
        "top": "拖延不只是懒，这条新闻适合和孩子聊聊大脑怎样做选择",
        "news": "值得追问的是大脑在做长期规划时发生了什么",
        "child": "请孩子记录一次自己拖延的经过，再说说当时的感受",
        "brand": "课堂上也会请孩子先说出自己的提问再动手验证",
    }

    assert build_resilient_advisory_rich_copy(case, binding, draft) == build_advisory_rich_copy(
        case, binding, draft
    )


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    (
        (LONG_FACT, 80, LONG_FACT[:50]),
        (
            "研究团队完成了第一阶段的全部实验。第二阶段将在明年启动，届时会有更多机构参与",
            30,
            "研究团队完成了第一阶段的全部实验",
        ),
        ("在广西期间举行的这次大会上，丁薛祥前往合作中心调研", 20, None),
        ("专家表示“这项技术很重要，值得长期投入”并给出了建议，随后会议结束", 24, None),
        # A comma inside a number is not a clause boundary.
        ("这一年全国各地累计投入的科研经费达到1,000亿元，覆盖多个省份", 22, None),
        ("短句，没有足够长度", 80, None),
    ),
)
def test_leading_clause(text: str, limit: int, expected: str | None) -> None:
    assert leading_clause(text, max_chars=limit) == expected


def test_only_a_boundary_cut_prefix_counts_as_frozen_claim_text() -> None:
    claims = frozenset({LONG_FACT})

    assert is_frozen_claim_text(LONG_FACT, claims)
    assert is_frozen_claim_text(LONG_FACT[:50], claims)
    assert not is_frozen_claim_text(LONG_FACT[:49], claims)
    assert not is_frozen_claim_text(LONG_FACT[:50] + "并获奖", claims)
    assert not is_frozen_claim_text("提出溶剂门控概念", claims)


@pytest.mark.parametrize(
    ("brand", "heading"),
    (
        # The curated classroom card names its own heading.
        (
            "在赛先生科学，“真动手”强调孩子亲自接触材料、尝试操作并观察现象，让实践成为理解科学问题的路径。",
            "教学启发：真动手",
        ),
        (
            '"真表达"理念让孩子说清自己的观察、做法与发现，把表达变成整理思路的一部分',
            "教学启发：真表达",
        ),
        # After a number the measure word is dropped: 6到8人小班直播的方式 -> 小班直播的方式.
        (
            "在赛先生科学，我们用6到8人小班直播的方式，让每个孩子都有提出问题和获得回应的机会",
            "教学启发：小班直播的方式",
        ),
        # No run reads as a phrase: the heading stays neutral.
        ("我们用3D打印", "教学启发：课堂上的做法"),
    ),
)
def test_brand_heading_names_a_whole_phrase(brand: str, heading: str) -> None:
    case, binding = _package(
        title=PROCRASTINATION_TITLE,
        facts=PROCRASTINATION_FACTS,
        brand=brand,
        # No usable phrase either, so the first statement decides the outcome.
        second_brand="我们用3D建模",
    )

    plan = _plan(case, binding)

    assert plan.brand.text == brand
    assert plan.brand_heading == heading


def test_news_heading_skips_a_phrase_cut_by_latin_letters_or_digits() -> None:
    case, binding = _package(
        title="AI时代大学教育应走向“人技共鸣”",
        facts=(
            "AI时代大学教育应走向人与技术的共鸣，让学生学会和工具一起思考。",
            "多所高校已开设人工智能通识课程。",
        ),
        brand=FEEDBACK_BRAND,
    )

    plan = _plan(case, binding)

    assert plan.title == "AI时代大学教育应走向“人技共鸣”"
    assert plan.news_heading == "新闻看点：人技共鸣"
    assert plan.child_frame == "和孩子围绕“人技共鸣”讨论："
