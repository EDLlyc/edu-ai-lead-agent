# ruff: noqa: RUF001  (Chinese copy used as seeded defects)
"""Known defects injected into a real headline-hook draft.

Each mutation changes exactly one thing the model could have written wrong: the hook sentence of
the Moments text, or a claim that feeds the long image. The heading, the verbatim headline and the
source footer are rendered by the system in production and are therefore never mutated.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.domain.copy_generation import ActiveBrandContext, LockedTopicContext
from app.schemas.copy_generation import DraftClaim, MaterialDraft, extract_headline_hook

Detector = Literal["validator", "auditor"]
Target = Literal["hook", "claim", "brand"]
_NUMBER = re.compile(r"\d+(?:\.\d+)?%?")
_ORGANISATION_SWAPS = (
    ("教育部", "科技部"),
    ("科技部", "教育部"),
    ("中国科学院", "中国工程院"),
    ("中国工程院", "中国科学院"),
    ("国务院", "全国人大常委会"),
    ("工业和信息化部", "国家发展改革委"),
    ("北京大学", "清华大学"),
    ("清华大学", "北京大学"),
    ("北京师范大学", "华东师范大学"),
    ("北京外国语大学", "上海外国语大学"),
)
_MEANING_SWAPS = (
    ("建立", "撤销"),
    ("印发", "废止"),
    ("发布", "撤回"),
    ("启动", "叫停"),
    ("推出", "下架"),
    ("开展", "取消"),
    ("增长", "下降"),
    ("提升", "降低"),
    ("提高", "降低"),
    ("加强", "削弱"),
    ("支持", "禁止"),
    ("鼓励", "禁止"),
    ("超过", "不足"),
)


@dataclass(frozen=True, slots=True)
class Defect:
    code: str
    label: str
    target: Target
    # Which gate is expected to stop it: the deterministic rules or the model auditor.
    detector: Detector
    # The rubric criterion a hook judge should fail for this defect, if it is a hook defect.
    rubric_criterion: str | None = None


Mutation = Callable[
    [MaterialDraft, LockedTopicContext, tuple[ActiveBrandContext, ...]], MaterialDraft | None
]


def replace_hook(draft: MaterialDraft, *, title: str, hook: str) -> MaterialDraft:
    """Swap the hook sentence and leave every system-rendered line untouched."""

    current = extract_headline_hook(draft.copywriting, title=title)
    lines = draft.copywriting.splitlines()
    if current:
        current_lines = {line.strip() for line in current.splitlines()}
        replaced = False
        kept: list[str] = []
        for line in lines:
            if line.strip() in current_lines:
                if not replaced:
                    kept.append(hook)
                    replaced = True
                continue
            kept.append(line)
        lines = kept
    else:
        footer = next(
            (index for index, line in enumerate(lines) if line.strip().startswith("新闻来源")),
            len(lines),
        )
        lines.insert(footer, hook)
    return draft.model_copy(update={"copywriting": "\n".join(lines)})


def _with_claim(draft: MaterialDraft, index: int, claim: DraftClaim) -> MaterialDraft:
    claims = list(draft.claims)
    claims[index] = claim
    return draft.model_copy(update={"claims": tuple(claims)})


def _first_claim(draft: MaterialDraft, kind: str) -> tuple[int, DraftClaim] | None:
    return next(
        ((index, claim) for index, claim in enumerate(draft.claims) if claim.kind == kind), None
    )


def _evidence_text(topic: LockedTopicContext) -> str:
    return "\n".join(
        value
        for item in topic.evidence
        for value in (item.exact_quote, item.governed_statement)
        if value
    )


def _hook(text: str) -> Mutation:
    def mutate(
        draft: MaterialDraft, topic: LockedTopicContext, _brand: tuple[ActiveBrandContext, ...]
    ) -> MaterialDraft | None:
        return replace_hook(draft, title=topic.title or "", hook=text)

    return mutate


def _number_outside_evidence(
    draft: MaterialDraft, topic: LockedTopicContext, _brand: tuple[ActiveBrandContext, ...]
) -> MaterialDraft | None:
    evidence_numbers = set(_NUMBER.findall(_evidence_text(topic)))
    for index, claim in enumerate(draft.claims):
        if claim.kind != "external_fact":
            continue
        match = _NUMBER.search(claim.text)
        if match is None:
            continue
        token = match.group()
        percent = token.endswith("%")
        value = float(token.rstrip("%"))
        for factor in (3, 7, 11):
            changed = value * factor + 1
            candidate = (f"{changed:g}" if "." in token else str(int(changed))) + (
                "%" if percent else ""
            )
            if candidate not in evidence_numbers:
                text = claim.text[: match.start()] + candidate + claim.text[match.end() :]
                return _with_claim(draft, index, claim.model_copy(update={"text": text}))
    return None


def _same_shape(left: str, right: str) -> bool:
    return (
        left != right
        and left.endswith("%") == right.endswith("%")
        and ("." in left) == ("." in right)
        and abs(len(left) - len(right)) <= 1
    )


def _number_swapped_within_evidence(
    draft: MaterialDraft, topic: LockedTopicContext, _brand: tuple[ActiveBrandContext, ...]
) -> MaterialDraft | None:
    """Every number still appears in the evidence, but it no longer says the same thing."""

    evidence_numbers = list(dict.fromkeys(_NUMBER.findall(_evidence_text(topic))))
    for index, claim in enumerate(draft.claims):
        if claim.kind != "external_fact":
            continue
        matches = list(_NUMBER.finditer(claim.text))
        # Two numbers in one claim trade places (22个省份…34个实验区 -> 34个省份…22个实验区).
        for position, first in enumerate(matches):
            second = next(
                (
                    other
                    for other in matches[position + 1 :]
                    if _same_shape(first.group(), other.group())
                ),
                None,
            )
            if second is not None:
                text = (
                    claim.text[: first.start()]
                    + second.group()
                    + claim.text[first.end() : second.start()]
                    + first.group()
                    + claim.text[second.end() :]
                )
                return _with_claim(draft, index, claim.model_copy(update={"text": text}))
        # Otherwise borrow a number the evidence uses for something else.
        for match in matches:
            other_number = next(
                (
                    number
                    for number in evidence_numbers
                    if number not in claim.text and _same_shape(match.group(), number)
                ),
                None,
            )
            if other_number is not None:
                text = claim.text[: match.start()] + other_number + claim.text[match.end() :]
                return _with_claim(draft, index, claim.model_copy(update={"text": text}))
    return None


def _swap_first(pairs: tuple[tuple[str, str], ...]) -> Mutation:
    def mutate(
        draft: MaterialDraft, _topic: LockedTopicContext, _brand: tuple[ActiveBrandContext, ...]
    ) -> MaterialDraft | None:
        for index, claim in enumerate(draft.claims):
            if claim.kind != "external_fact":
                continue
            for original, replacement in pairs:
                if original in claim.text and replacement not in claim.text:
                    text = claim.text.replace(original, replacement, 1)
                    return _with_claim(draft, index, claim.model_copy(update={"text": text}))
        return None

    return mutate


def _brand_effect_fabricated(
    draft: MaterialDraft, _topic: LockedTopicContext, _brand: tuple[ActiveBrandContext, ...]
) -> MaterialDraft | None:
    found = _first_claim(draft, "brand_statement")
    if found is None:
        return None
    index, claim = found
    text = claim.text.rstrip("。！!") + "，学员升入重点中学的比例明显高于同龄人。"
    if len(text) > 300:
        return None
    return _with_claim(draft, index, claim.model_copy(update={"text": text}))


def _brand_as_fact_binding(
    draft: MaterialDraft, _topic: LockedTopicContext, _brand: tuple[ActiveBrandContext, ...]
) -> MaterialDraft | None:
    found = _first_claim(draft, "brand_statement")
    if found is None:
        return None
    index, claim = found
    return _with_claim(draft, index, claim.model_copy(update={"kind": "external_fact"}))


DEFECTS: tuple[tuple[Defect, Mutation], ...] = (
    (
        Defect("hook_anxiety_listed", "引导语含名单内的焦虑话术", "hook", "validator", "safe"),
        _hook("孩子再不学就晚了，赶紧行动起来吧！😟"),
    ),
    (
        Defect("hook_anxiety_paraphrase", "引导语换一种说法制造焦虑", "hook", "auditor", "safe"),
        _hook("别人家的孩子都已经学起来了，你家孩子还跟得上吗？😟"),
    ),
    (
        Defect("hook_marketing_listed", "引导语含名单内的营销承诺", "hook", "validator", "safe"),
        _hook("来赛先生学习，保证提分，家长放心！🎉"),
    ),
    (
        Defect("hook_marketing_paraphrase", "引导语换一种说法承诺效果", "hook", "auditor", "safe"),
        _hook("报名赛先生的课程，孩子的成绩一定会大幅提高！🎉"),
    ),
    (
        Defect("hook_off_topic", "引导语与新闻无关", "hook", "auditor", "relevant"),
        _hook("周末带孩子去公园放风筝，感受大自然的气息吧！🪁"),
    ),
    (
        Defect("hook_fabricated_number", "引导语编造统计数字", "hook", "validator", "safe"),
        _hook("全国已有90%的小学开设了这门课，你家孩子学了吗？🤔"),
    ),
    (
        Defect("hook_fabricated_policy", "引导语编造政策（无数字）", "hook", "auditor", "safe"),
        _hook("教育部已经规定所有小学生必须学习编程，你家孩子准备好了吗？🤔"),
    ),
    (
        Defect("claim_number_outside_evidence", "事实里的数字改成原文没有的", "claim", "validator"),
        _number_outside_evidence,
    ),
    (
        Defect("claim_number_swapped", "事实里的数字换成原文里的另一个数", "claim", "auditor"),
        _number_swapped_within_evidence,
    ),
    (
        Defect("claim_subject_swapped", "事实的主体换成另一个机构", "claim", "auditor"),
        _swap_first(_ORGANISATION_SWAPS),
    ),
    (
        Defect("claim_meaning_reversed", "事实的意思被改反", "claim", "auditor"),
        _swap_first(_MEANING_SWAPS),
    ),
    (
        Defect("brand_effect_fabricated", "品牌句编造教学效果", "brand", "auditor"),
        _brand_effect_fabricated,
    ),
    (
        Defect("brand_as_fact_binding", "品牌句冒充外部事实", "brand", "validator"),
        _brand_as_fact_binding,
    ),
)


def build_mutants(
    draft: MaterialDraft,
    *,
    topic: LockedTopicContext,
    brand_context: tuple[ActiveBrandContext, ...],
) -> list[tuple[Defect, MaterialDraft]]:
    """Every applicable mutant of one draft; a mutation that changes nothing is dropped."""

    mutants = []
    for defect, mutate in DEFECTS:
        mutant = mutate(draft, topic, brand_context)
        if mutant is not None and mutant != draft:
            mutants.append((defect, mutant))
    return mutants
