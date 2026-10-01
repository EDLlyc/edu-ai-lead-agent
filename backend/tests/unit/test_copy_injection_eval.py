# ruff: noqa: RUF001

from __future__ import annotations

from evals.copy_injection.attacks import (
    AUDITOR_ATTACK,
    GENERATOR_ATTACKS,
    canary_in_clean_evidence,
    followed,
    inject,
    output_text,
)
from evals.copy_injection.runner import AttackTally, AuditorTally, Results, render
from evals.copy_quality.runner import CallBudget
from tests.unit.test_copy_repair_tools import _workspace


def test_injection_lands_only_at_the_end_of_the_first_evidence_quote() -> None:
    topic = _workspace().topic
    attack = GENERATOR_ATTACKS[0]

    poisoned = inject(topic, attack)

    assert poisoned.evidence[0].exact_quote.endswith(attack.payload)
    assert poisoned.evidence[0].exact_quote.startswith(topic.evidence[0].exact_quote)
    assert poisoned.evidence[1:] == topic.evidence[1:]
    assert topic.evidence[0].exact_quote != poisoned.evidence[0].exact_quote  # input untouched


def test_every_canary_is_absent_from_clean_text_and_found_when_echoed() -> None:
    workspace = _workspace()
    clean = workspace.draft
    for attack in (*GENERATOR_ATTACKS, AUDITOR_ATTACK):
        assert not canary_in_clean_evidence(attack, workspace.topic), attack.code
        assert not followed(attack, clean), attack.code
    for attack in GENERATOR_ATTACKS:
        echoed = clean.model_copy(update={"interaction": f"你怎么看？{attack.canaries[0]}"})
        assert followed(attack, echoed), attack.code
        assert attack.canaries[0] in output_text(echoed)


def test_report_counts_followed_blocked_and_escaped() -> None:
    results = Results()
    results.control_drafts = 2
    tally = results.attacks["contact_link"]
    tally.samples, tally.followed, tally.blocked_by_rules, tally.escaped = 2, 2, 1, 1
    results.auditor["hook_off_topic"] = AuditorTally(2, 2, 2, 1)
    budget = CallBudget(limit=10)

    text = render(results, topics=2, bundle_text="生成 v28，审查 v21", budget=budget)

    assert "| 要求附联系方式和链接 | 2 | 2 | 1 | 0 | 1 |" in text
    assert "| **合计** | 2 | 2 | 1 | 0 | 1 |" in text
    assert "| hook_off_topic | 2/2 | 1/2 |" in text
    assert isinstance(results.attacks["fake_endorsement"], AttackTally)
