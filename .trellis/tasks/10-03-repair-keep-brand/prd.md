# 修复 Agent 删掉唯一品牌句导致长图缺失

## What happened (2026-10-03, found during the owner's "你看看今天怎么样了")

Noon #1 (run 87e3b912): draft 1 was blocked for `brand_claim_repeated`. The repair agent (live
since 10-02 19:30) followed its rule "no fitting brand sentence -> drop_claim" and removed the
only brand statement. The draft passed the rules and the auditor and was delivered, but the
long-image producer requires 1-48 brand bindings (`_input_from_package`) and skipped the post
silently (`continue`, no log). Since 09-29 every post had a long image; since 09-20 this is the
only accepted draft without a brand statement. The other three agent repairs today were fine.

## Fix (6a4d660)

- `drop_claim` refuses to drop the last brand statement (`brand_claim_required`) and offers
  sentences from other brand chunks; rule 2 says swap, never remove the last one.
- Executor gate: an agent draft that lost the brand statement fails with `brand_claim_missing`
  and the regeneration runs instead.
- Tests for both; gate run.

## Rollout

`rollout/`: overlay FROM 32c89fe6 with 4 files (incl. `agent_tracing.py`, needed by the traced
repair agent). Deploy before the evening slot prepares (17:00), owner confirmation required.

## Follow-ups

- The long-image producer skips a post without any log or alert; the watchdog should flag a
  delivered post that has no long-image job (owned with the long-image session).
- The repair eval never checked downstream requirements (long image); add a "brand statement
  kept" check to evals/copy_repair.

## Rollout

LIVE 2026-10-03 14:24 (owner "好的，请你处理"): image 1f238fc2; six services healthy, 0 restarts, 0 errors;
backups `*.before-6a4d660-20261003T142446`. Verify after the evening slot.
