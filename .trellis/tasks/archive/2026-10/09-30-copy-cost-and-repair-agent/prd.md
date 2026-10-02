# 文案降本（评测兜底）与会用工具的修复 Agent

## Source request (2026-09-30, owner)

"还有什么技术性，要提升的？感觉技术含量不是很高。" → recommended (1) cost/latency with the eval
as safety net and (2) a tool-using repair agent → "好的，请你处理".

## Part 1 — lean context (measured, evaluated)

Production, 14 days, v26/v20:
- **Generation:** ~8.9k input and ~430 output tokens, 7.3 s.
- **Audit:** ~8.6k input and ~30 output tokens, 2.1 s.
- **Share of daily tokens:** copy is ~70%; governance factual analysis is second.

Profile (`evals/copy_cost/profile.py`, 10 recent topics, no chat-model call):
- **Generation prompt:** EVIDENCE 47% (7 quotes of ~890 chars each), BRAND 34% (6 chunks, 39% of
  it tag/page metadata), OUTPUT_SCHEMA 8%, instructions 7%.
- **Audit prompt:** EVIDENCE 45%, BRAND 35%, instructions 8%, DRAFT 6%, schema 5%. The auditor
  receives every evidence quote and brand chunk although it only checks what the draft cites.
  It also never sees the topic title.

Change (new versions only; v26/v20 unchanged):
- `moments-generator-v27-lean-context`: BRAND keeps id, section title, claim scope, verification
  flag and text.
- `moments-auditor-v21-lean-context`: EVIDENCE and BRAND only as cited by the draft's claims
  (first evidence item if none), slim brand fields, plus the topic title and summary.
- The long-image services recognise v27 as the headline-hook family.

Acceptance:
- Seeded-defect eval on the same 10 topics: block rate not lower than baseline (86/95), control
  false blocks stay 0, hook judge unchanged within noise.
- Report input tokens per topic, baseline vs lean.

## Part 2 — tool-using repair agent (next)

Today a blocked draft gets one full regeneration with the issue list. Proposed:
- **Tools:** `read_evidence(evidence_id)`, `find_support(text)` (exact sentences in cited
  evidence), `replace_claim(claim_id, text, evidence_ids)`, `drop_claim(claim_id)`,
  `rewrite_hook(text)`, `check()` (deterministic validator), `submit()`.
- **Loop:** at most 4 tool rounds, then the existing validator and auditor. Failures stay
  review-required as today. There are no new facts: claim text must be an exact span of cited
  evidence.
- **Measure** with the seeded-defect harness, on blocked mutants:
  - auto-repaired-and-passing rate;
  - faithfulness (the judge plus the exact-span check);
  - calls and tokens per repair;
  - all against today's full-regeneration repair.

## Part 1 result (2026-09-30, paired run, `backend/evals/copy_cost/reports/2026-09-30-paired-lean-context.md`)

Setup: the same topics, drafts and seeded mutants were judged by both auditors. 9 topics
reached audit; 1 generation failed with invalid provider output; 1 candidate audit was rejected by
the provider (4xx, possibly the content filter).

- **Input tokens per call:**
  - Audit: 7,935 → 2,651 (−67%).
  - Generation: 8,230 → 7,964 (−3%). Brand metadata is mostly ASCII and tokenises cheaply;
    evidence quotes dominate generation.
  - Per post: ≈16.2k → ≈10.6k (−34%).
- **Seeded defects (77 per side):** blocked for the right reason 59 → 65 (77% → 84%), incidental
  blocks 10 → 6, warned only 8 → 6, missed 0 → 0. Controls had no false block on either side.
- **Off-topic hooks** stay warnings on both sides: v20/v21 tell the auditor to warn. The earlier
  "5/10 blocked" came from incidental schema codes.
- **Open:**
  - The auditor invents free-form error codes (a dozen names for "marketing"). The next step
    is an enumerated audit code set.
  - Watch provider rejections of the lean auditor before rollout.

## Part 1 rollout

Live 2026-09-30 15:21 (image `sha256:21c63fc9…`, release d6e6772); lean-context prompts are the code
defaults. Superseded on the generator side by v28 shared quotes (09-30-copy-call-stability) and on
the auditor side by v22 (10-01-auditor-v22-watchdog).

## Part 2 result (2026-09-30, `backend/evals/copy_repair/reports/2026-09-30-repair-agent.md`)

- One typed tool registry (`copy_repair_tools.build_repair_tool_registry`: check_draft,
  find_evidence, replace_claim, drop_claim, rewrite_hook) serves the function-calling agent
  (`copy_repair_agent.py`), the stdio MCP server (`app/copy_repair_mcp_main.py`) and the eval.
  Failures return `error_code`, `retryable`, `hint` and, for bad arguments, `fields`.
- Blocked seeded drafts repaired, agent vs production's full regeneration (same run, paired):
  v1 10/32 vs 27/32; v2 13/20 vs 18/20; v3 25/28 vs 25/28, agent then regeneration 28/28. Agent
  input per repair 5,383 tokens vs 6,084.
- Commits d15cf11, 42e636e (MCP error details). Not switched on in production: the agent runs in
  shadow mode (10-01-repair-shadow-ops) until nightly data supports a gradual rollout.

## Closed (2026-10-02)

Both parts are delivered: Part 1 live, Part 2 built, evaluated and running in shadow. The rollout
decision for the agent is tracked in 10-01-repair-shadow-ops.
