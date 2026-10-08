# 修复 Agent：品牌句按编号选 + 同一错误连续出现提前停

## Source (2026-10-08 data review, owner "好的，请你处理")

All 10 blocked drafts given to the repair agent (10-02..10-08) were blocked on the brand sentence.
The agent fixed 7; the other 3 failed the same way: six replace_claim calls refused with
claim_not_in_brand (could not copy a brand sentence verbatim), round limit, fallback.

## Built (da2d2a3, e9feebd)

- Tools `list_brand_sentences` / `use_brand_sentence` (by id, written verbatim with its chunk);
  rule 2 and the per-issue hint route brand problems to them.
- Agent stops with `repeated_error` after the same tool error three times in a row.
- use_brand_sentence needs approval in the ops assistant, confirmation in the repair MCP server,
  and counts as an edit tool in the trajectory eval.
- Agent v5-brand-by-id, tools v4-brand-by-id. Gate PASS @ da2d2a3.

## Evaluation (evals/copy_repair/reports/2026-10-08-brand-by-id.md)

Production replay, 10 drafts × 2 (real model, run's own auditor): v5 17/20 (85%) vs production
7/10; no claim_not_in_brand, no round limit, 9.6k input tokens per repair (production ~12k);
the 3 previous failures: 3/6. Remaining failures: the auditor finds the chosen brand sentence off
topic (falls back to regeneration as before).

## Rollout (owner confirmation required)

Unified image `sha256:64dc8ade051c8c5fd54285aafc4ec9976eeb22397c6f51c42be372ac8a6beb45`
(tag release-e9feebd) = app image 1f238fc2 + every backend/app file changed in de22d32..e9feebd
(app/ = mainline e9feebd); bases 29/29; smoke ok. Plan: six app services and the weekly + shadow
crons move to it (outside slot hours, no job running).
