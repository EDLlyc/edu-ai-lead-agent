from __future__ import annotations

from evals.copy_cost.paired import classify
from evals.copy_cost.profile import field_split, split_sections
from evals.copy_quality.runner import GateResult


def test_block_reasons_are_split_into_right_and_incidental() -> None:
    right = GateResult("blocked_by_auditor", auditor_errors=("education_anxiety",))
    incidental = GateResult("blocked_by_auditor", auditor_errors=("schema_violation",))
    rule = GateResult("blocked_by_validator", validator_errors=("unclaimed_external_fact",))

    assert classify("hook_anxiety_paraphrase", right) == "right_reason"
    assert classify("hook_off_topic", incidental) == "other_reason"
    assert classify("hook_fabricated_number", rule) == "right_reason"
    assert classify("hook_off_topic", GateResult("passed_with_new_warnings")) == "warned"
    assert classify("hook_off_topic", GateResult("passed")) == "missed"


def test_sections_start_on_a_new_line_even_when_instructions_name_the_tag() -> None:
    prompt = (
        "只能引用<EVIDENCE>中的evidence_id。\n"
        '<OUTPUT_SCHEMA>{"type":"object"}</OUTPUT_SCHEMA>\n'
        '<EVIDENCE>[{"exact_quote":"原文","source_url":"https://x"}]</EVIDENCE>\n'
        '<BRAND>[{"brand_chunk_id":"b","tone_tags":["t"],"text":"品牌"}]</BRAND>'
    )

    sections = split_sections(prompt)

    assert sections["EVIDENCE"].startswith('[{"exact_quote"')
    assert "只能引用<EVIDENCE>中的evidence_id" in sections["instructions"]
    text, meta = field_split(sections["BRAND"], {"text"})
    assert text == len("品牌")
    assert meta == len(sections["BRAND"]) - text
