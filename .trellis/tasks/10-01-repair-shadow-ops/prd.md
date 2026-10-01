# Repair agent shadow mode, read-only ops role, day trace, injection eval

Branch `feat/repair-agent-20260930` (from mainline 3a79c22). Owner request 2026-09-30:
"好的，请你处理" for items 2 (shadow mode) and 3 (tracing and cost dashboard) of the technical plan,
then the rest of the list (4: prompt-injection eval).

## Goals

1. Get production evidence for the tool-using copy repair agent without changing what is
   published: replay it nightly on drafts production blocked, next to production's own full
   regeneration.
2. One read-only path to production data for tools: a SELECT-only database role used by the
   local ops/repair MCP servers, the trace dashboard and the shadow job.
3. A per-post trace (rerank → generation → audit → repair → image → long image → delivery) with
   model, calls, tokens, latency and status, plus daily usage by stage and model (p50/p95).
4. Measure whether instructions hidden in crawled evidence hijack the generator or the auditor.

## Design

- Registry reuse: the repair tools (`copy_repair_tools`) serve function calling, MCP and evals;
  the ops tools (`ops_tools`) serve MCP, the HTML dashboard (same `get_day_trace` reader) and
  scripts.
- Role `edu_ai_ops_ro` (`scripts/ops/ops_readonly_role.py`): idempotent; SELECT on 25 tables;
  six tables column by column without recipient identifiers or raw payloads; NOINHERIT, no
  CREATE/TEMP (TEMP revoked from PUBLIC; every application role is a superuser, checked);
  `default_transaction_read_only`, 5 s statement, 1 s lock, 30 s idle-in-transaction timeouts,
  4 connections. The SCRAM verifier is computed locally and sent over stdin; production grants
  fail loudly on a missing table; the grant transaction uses a 3 s lock timeout.
- Every consumer calls `verify_read_only_role` first and refuses a superuser or any role that
  can write, create or use TEMP.
- Shadow job (`app/copy_repair_shadow_main.py`): selected runs with a draft version 2 in the window →
  draft 1 + its stored blocking issues → `CopyRepairAgent` → production rules + the run's own
  auditor version → one JSON line next to production's draft 2 outcome. Idempotent by run id,
  model calls capped (120 per night), one bad run does not stop others.
- Deploy shape follows `edu-ai-quality-report`: `/usr/local/sbin/edu-ai-copy-repair-shadow`
  runs a one-off container of a pinned image at 21:10; no service is restarted; output in
  `/opt/edu-ai-lead-agent/reports/copy-repair-shadow/`.

## Verification

- Unit, contract and integration tests for every new module; full unit+contract run has the same
  28 failures as clean mainline; workbench eval 42/42.
- Local role: writes, CREATE, TEMP, reading `recipient_id` and unlisted tables refused even with
  `default_transaction_read_only = off`.
- Headless Claude Code session diagnosed a real (local) run through the ops MCP tools.
- Production checks are recorded in the rollout note below.

## Rollback

- Shadow job: remove `/etc/cron.d/edu-ai-copy-repair-shadow` (and the sbin script).
- Role: `REASSIGN OWNED BY edu_ai_ops_ro TO edu_ai; DROP OWNED BY edu_ai_ops_ro; DROP ROLE
  edu_ai_ops_ro;` and `GRANT TEMPORARY ON DATABASE edu_ai TO PUBLIC;` to restore the default.
- No service image changes, so nothing else to roll back.

## Rollout note (2026-10-01)

- 11:32: the noon slot's copy, images and long images were finished, with no copy job running and
  no long transaction. The role was created; production grants are strict, and 25 tables plus 6
  column-granted tables exist.
- Probes through the SSH tunnel as `edu_ai_ops_ro` with read-only switched off: UPDATE, DELETE,
  CREATE TABLE, CREATE TEMP TABLE, reading `wecom_delivery_jobs.recipient_id` and
  `news_infographic_jobs.recipient_id`, and reading `material_packages` were all refused. All
  five ops tools returned real data for 09-30 and 10-01.
- Day trace dashboard for 09-29..10-01 (local file `tmp/trace/trace-2026-10-01.html`): 09-29
  8/9 delivered, 116 model calls, 1 failure; 09-30 9/9, 113 calls, 0 failures; median generation
  time 3.3 min.
- Shadow, first replay (image 590befac, 11:35): 6 blocked drafts. Five were v12 standalone-heading
  runs, where the headline-hook tools break the format (agent 1/6 vs regeneration 4/6). Fixed in
  c9d12f9: such runs are refused and logged as not applicable; the five records were moved to
  `not-applicable-rule-version.jsonl.bak`. Re-run on 2e43a078: 5 not applicable (0 model calls),
  1 valid case, which both arms repaired.
- Injection eval (`backend/evals/copy_injection/reports/2026-10-01-injection.md`): the generator
  followed 0 of 30 injected instructions; the auditor's block rate was unchanged by "approve this"
  (one off-topic case 1→0 of 5). Auditor v21 alone blocks 1/5 off-topic hooks and 3/5 paraphrased
  marketing hooks.
