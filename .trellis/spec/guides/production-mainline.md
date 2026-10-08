# Production Mainline

> Decided 2026-09-29: the branch that production runs is the mainline. Develop and release from it.

## The branch

- **`mainline`** is exactly what production runs (backend `app/` and `alembic/` verified byte-identical
  to the running service image and the quality-report cron image on 2026-09-29).
- Start every feature, fix and release branch from `mainline`; merge back into it after deploy.
- The production database follows mainline's migration chain (…0048 → 0049 wecom_news_infographics →
  0050 infographic_advisory → 0051 human_pick_lanes → 0052 admin_console → 0053 operator_sources →
  0054 operator_keywords). New migrations go on top of it.

## Deploying

- **Gate first**: on the commit you are about to deploy run `make predeploy-check` (all
  provider-free evaluations plus unit and contract tests against
  `backend/tests/known-failures.txt`, about five minutes) and paste its last line
  (`predeploy gate PASS @ <commit> …`) into the rollout note. A failed gate blocks the deploy
  unless the owner waives it for that release. The baseline may only shrink.
- When a copy prompt, rule or model version changes, also run `evals/copy_quality` (seeded
  defects and hook rubric; spends model calls) outside slot hours and keep the dated report.
- Quick change (Python only): build an overlay image on the server `FROM` the running digest,
  verify the overlaid base files match the parent commit, run an offline smoke test, back up
  `.env`/`.release.env`, set `APP_IMAGE` and recreate the six app services with
  `docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env up -d --no-deps …`.
- Avoid restarting workers while an acquisition, copy or long-image job is running.
- Several sessions may deploy: tell the others the new digest and build only `FROM` the running one.

## Live since 2026-10-08 17:28 (image `sha256:5a5fb24c…`, 运营后台 items 0–2, release bdb0963)

- The owner waived the evening-slot rule for this deploy ("先在就做，今天的任务不用管"). The three
  18:30 deliveries were queued and not leased when the services switched.
- The six app services run
  `offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:5a5fb24ccaccf1894e3d857e583f412fb01526dd4bd5f71f83125bd2482f92b7`.
  This is 64dc8ade plus the 35 backend files of `feat/admin-console-20261008` @ ac5f076
  (`.trellis/tasks/10-08-admin-console/rollout/`). The base hashes matched in the running
  container and the offline smoke passed.
- DB `20260928_0051` → `20261008_0054`: admin users, sessions and audit log; source ownership,
  sticky toggles, archive and `connector_config`; operator keyword versions and
  `content_slot_runs.operator_keyword_version_id`. `seed_sources` still found the same 10
  enabled seeds.
- New API `/api/v1/admin/*` (login cookie, write guard). It is on loopback only, like the rest
  of the API; there is no public entry yet (domain + nginx pending, see the rollout README).
  `APP_ENV=production`, so the session cookie is Secure.
- Behaviour is unchanged until an operator acts:
  - no keyword version → slot scoring as before;
  - seeds stay enabled until toggled;
  - generic connectors only for operator sources.
- Cron images unchanged: quality report 9c9d1c01, watchdog + ops-action 8f14b771, shadow and
  regression as before. They do not read the new tables. Rebuild them from 5a5fb24c the next
  time Settings change.
- Backups:
  - DB `/var/backups/edu-ai/postgres/edu-ai-before-admin-console-20261008T092757Z.dump` (+ `.sha256`);
  - env files `*.before-bdb0963-20261008T092757Z`.
- Rollback: restore the env pair and recreate the six services. The schema is additive, and
  64dc8ade runs on it unchanged.

## Live since 2026-09-30 15:21 (image `sha256:21c63fc9…`, release d6e6772)

- Copy prompts are `moments-generator-v27-lean-context` / `moments-auditor-v21-lean-context`. They
  are the code defaults; compose does not pass copy prompt versions. The auditor sees only the
  evidence and brand chunks the draft cites, plus the topic title and summary.
- Paired seeded-defect evaluation (`backend/evals/copy_cost/reports/`): audit input −67%, per
  post ≈−34%; blocks for the right reason 59 → 65 of 77.
- Reference selector `brand-visual-selector-v3-gated-rotation` is set by `.env`
  `IMAGE_DIVERSITY_SELECTOR_VERSION`. It needs `props` on every approved action asset in the
  private manifest; the host manifest and `visual-assets.metadata.json` were updated, with backups
  `*.before-visual-v3-20260930T152039`. Without labels it falls back to v2-novelty with a warning.
  `VISUAL_SEMANTIC_ENABLED` stays false.

## Live since 2026-10-08 09:22 (unified image `sha256:64dc8ade…`, mainline e9feebd)

- Repair agent `copy-repair-agent-v5-brand-by-id`: brand sentences are picked by id
  (`list_brand_sentences` / `use_brand_sentence`, written verbatim); the agent stops with
  `repeated_error` after the same tool error three times. Production replay 10 drafts × 2: 17/20
  vs production 7/10 (`backend/evals/copy_repair/reports/2026-10-08-brand-by-id.md`).
- The six app services and the weekly + shadow crons run
  `…@sha256:64dc8ade051c8c5fd54285aafc4ec9976eeb22397c6f51c42be372ac8a6beb45` = 1f238fc2 + every
  backend/app file changed in de22d32..e9feebd, so their app/ equals mainline e9feebd. Still on
  older images: quality report 9c9d1c01, watchdog + ops-action 8f14b771, eval regression 7bffe4ed.
- Backups `*.before-e9feebd-20261008T092226` (env files, weekly and shadow wrappers). Rollback:
  restore them and recreate the six services.

## Live since 2026-10-03 14:24 (image `sha256:1f238fc2…`, release 6a4d660); mainline = feat/repair-agent-20260930

- Incident 10-03 noon #1: the repair agent dropped the only brand statement of a draft blocked
  for `brand_claim_repeated`; the draft was delivered, but the long-image producer requires a
  brand binding and silently skipped the post. Fix: `drop_claim` refuses the last brand
  statement (`brand_claim_required`), rule 2 says swap instead, and the executor gate falls back
  to regeneration with `brand_claim_missing`. Agent version `copy-repair-agent-v4-keep-brand`.
- The six app services run `…@sha256:1f238fc2c1e2f86f7b7769057b3e0679d351ac458c3fdd40a5e58a1fda7052ec`
  = 32c89fe6 + `agent_tracing.py`, `copy_repair_agent.py`, `copy_repair_tools.py`,
  `copy_generation.py` from 6a4d660. Backups `*.before-6a4d660-20261003T142446`.
- From this point mainline is fast-forwarded to the branch: every deployed image is built from
  it. Images in use: app services 1f238fc2; delivery watchdog + `edu-ai-ops-action` 8f14b771;
  quality report 9c9d1c01; repair shadow and eval regression 7bffe4ed. Local-only tools on the
  branch (ops assistant on LangGraph, MCP over HTTP, evals) run in no service.

## Live since 2026-10-02 21:54 (approved actions, propose-only; image `sha256:8f14b771…`)

- `/usr/local/sbin/edu-ai-delivery-watchdog` and the new `/usr/local/sbin/edu-ai-ops-action`
  run `…@sha256:8f14b771fe2eab9e170d936e3092c6afbd684ca335f11e9216624983695cf640` = report image
  9c9d1c01 + 8 files from feat/repair-agent-20260930 @ 944f37a (not on mainline yet).
- When the diagnosis suggests a resend, the watchdog writes proposals for the slot's failed
  deliveries to `reports/delivery-watchdog/action-proposals.jsonl`. Operators run
  `sudo edu-ai-ops-action list | approve <id> --by <name> | reject | verify` on the server.
- Propose-only: `scripts/ops-actions.env` does not exist, so `OPS_ACTIONS_ENABLED` is false and an
  approval is only recorded. Enable after a week of proposals by writing
  `OPS_ACTIONS_ENABLED=true` there (root, 0600). Only `retry_delivery`; 3 executions per day.
- Backup `/usr/local/sbin/edu-ai-delivery-watchdog.before-944f37a-20261002T215401`. Rollback:
  restore it and remove `edu-ai-ops-action`.

## Live since 2026-10-02 21:23 (quality-report cron image `sha256:9c9d1c01…`)

- The daily quality report had failed since 09-30 21:40: its pinned image (518b16d8) rejected the
  production `.env` (selector v3). `/usr/local/sbin/edu-ai-quality-report` now runs
  `…@sha256:9c9d1c0117d2de62f06bcaa13a94f6f232d5e950d1b134b199e5c4a1a4ae6e9d` = 32c89fe6 + the
  report files and `repair_metrics` from feat/repair-agent-20260930 @ e8805a4 (not on mainline
  yet). The report gains a 修复 Agent section (agent attempted / fixed, fallbacks by reason,
  regeneration-only, tokens). 09-30 and 10-01 were backfilled.
- When the app image's Settings change, rebuild the cron images (report, watchdog, shadow,
  regression) from it: an old cron image can fail on the new `.env`.
- Backup `/usr/local/sbin/edu-ai-quality-report.before-e8805a4-20261002T212335`.

## Live since 2026-10-02 19:55 (delivery-watchdog cron image `sha256:d996df96…`)

- Only the delivery-watchdog cron changed: `/usr/local/sbin/edu-ai-delivery-watchdog` runs
  `…@sha256:d996df96668d60e981a69180936cf3f58dcc6a34ebea355de35b85ea3a55b174` = 32c89fe6 +
  `agent_tracing.py`, `ops_diagnosis.py`, `delivery_watchdog_main.py` from
  feat/repair-agent-20260930 @ 92c80df (not on mainline yet; merge with the branch). The six app
  services stay on 32c89fe6; the shadow and regression crons are unchanged.
- On a slot problem, a read-only diagnosis agent (glm-5.2, ops role, ~5 calls) appends stage,
  cause and a suggested action to the alert and the JSONL record; reruns are suggestions only.
- Backup `/usr/local/sbin/edu-ai-delivery-watchdog.before-92c80df-20261002T195533`. Rollback:
  restore it.

## Live since 2026-10-02 19:30 (image `sha256:32c89fe6…`, release de22d32)

- A blocked first draft is repaired by the tool-using repair agent first (`COPY_REPAIR_MODE`
  code default `agent_first`; compose and `.env` do not set it). The agent's draft becomes draft 2
  only after the same rules and the run's auditor; otherwise a `workflow`/`failed` attempt with a
  `repair_agent_*` code records why and the full regeneration runs as before. `repair_count` stays 1.
- Look for `copy_generation_attempts.safe_metadata->>'repair_method' = 'agent'` on an accepted
  draft 2, or a `repair_agent_*` error code on a workflow attempt.
- Env backups `*.before-de22d32-20261002T193042`. Rollback: restore both env files and recreate the
  six services. Cron images are unchanged.

## Live since 2026-10-02 13:31 (image `sha256:b8fa7ada…`, release 11ad19c)

- The controlled planner knows the action pool: a subject+cast with no fresh approved action image
  (prop gate, exact cast, within the 6 MiB reference budget, outside the 12-pick cooldown) loses
  1,500 points, one left loses 300. Active only with selector v3 and a prop-labelled manifest.
- The 12 action PNGs over 3.5 MB were resized to a 1536 px longest edge (all ≤ 3.5 MB) and the host
  manifest rebuilt; their asset ids changed, so their cooldown history restarted once. Backups:
  `/var/backups/edu-ai/brand-materials/before-visual-pool-20261002T133009/` (12 PNGs + manifest)
  and `visual-assets.manifest.json.before-visual-pool-20261002T133009`.
- Replay over 186 production briefs (`backend/evals/visual_replay/plan_sim.py`): reuse of a cooled
  image 56% → 2%, distinct action images 15 → 21, top image share 16% → 8%.
- Env backups `*.before-visual-pool-20261002T133121`. Rollback: restore the 12 PNGs and the
  manifest, restore both env files, recreate the six services.

## Live since 2026-10-01 23:12 (image `sha256:5887bce7…`, release 765fe1e)

- Selection scores the freshest events (about 200), not the first 500 by id.
- A human pick is held at 待审核 until an operator reviews, optionally edits the hook and tags, and
  pushes it from the exhibit's review mode. Each edit is kept as a before/after pair in
  `material_packages.copy_snapshot` (`operator_edits`, `operator_push`). Daily slot pushes are
  unchanged.
- The exhibit connector must pin this digest before its restart (owner go-ahead required).

## Live since 2026-10-01 22:30 (image `sha256:7bffe4ed…`, mainline 72a4930 app)

- Copy auditor `moments-auditor-v22-enumerated-codes` (closed code table, severity decided by the
  system; off-topic hooks and outcome promises block) is the code default; generator v28 and rules
  v13 are unchanged. On the same seeded drafts, v22 blocks 26/26 vs v21's 18/26 with 0/5 clean
  drafts blocked. The regression on this image: 16/16 blocked, 0/3 clean blocked, 0/19 inconsistent
  over three audits each. On 20 accepted production drafts it would block 3, all for one
  paraphrased brand sentence.
- Brand-repeat check: a first draft whose brand sentence repeats a recent accepted one (similarity
  >= 0.85) gets `brand_claim_repeated` as an error and so one repair; on the repair it only warns.
- Scheduled one-off jobs, all on the pinned image `…@sha256:7bffe4edfe8cc073b081e7e4d71eb175697f99383745472f0ec407000cff5646`:
  `edu-ai-delivery-watchdog` (07:42/12:42/18:42; alerts go to `OPS_ALERT_WEBHOOK_KEY` from
  `scripts/ops-alert.env` once it exists, log only until then), `edu-ai-copy-repair-shadow` (21:10),
  and `edu-ai-eval-regression` (21:25; runs when copy versions change or weekly; reports and
  trend.csv in reports/eval-regression).
- Backups `*.before-v22-20261001T223016`. Rollback: restore both env files and recreate the six
  services.

## Read-only ops role and repair shadow job (since 2026-10-01 11:43)

- Database role `edu_ai_ops_ro` (`scripts/ops/ops_readonly_role.py`, idempotent): SELECT on 25
  tables and on six more column by column, without recipient identifiers or raw payloads. It is
  NOINHERIT, cannot CREATE or use TEMP (`REVOKE TEMPORARY ON DATABASE edu_ai FROM PUBLIC`; every
  application role is a superuser), and has read-only default transactions with 5 s statement,
  1 s lock and 30 s idle-in-transaction timeouts and 4 connections. Its connection string is in
  `/opt/edu-ai-lead-agent/scripts/ops-readonly.env` (root 0600, compose network) and locally in
  `~/.config/edu-ai/ops-db.production.env` (0600, SSH tunnel to 127.0.0.1:15432). Every consumer
  checks the role first and refuses one that can write.
- Copy repair shadow job: `/etc/cron.d/edu-ai-copy-repair-shadow` runs
  `/usr/local/sbin/edu-ai-copy-repair-shadow` at 21:10. It is a one-off container of the pinned
  image `…@sha256:2e43a0784a9fbc25596d52296b47d74e1c78778ad563a4a6104e671c1e0c3523`
  (30f6cd0e + 19 app files of c9d12f9; service defaults unchanged). It replays the repair agent on
  drafts production blocked yesterday and today (headline-hook rules only) and writes JSON lines
  plus `summary.md` to `/opt/edu-ai-lead-agent/reports/copy-repair-shadow/`. It caps model calls
  at 120 per night and never writes production data. The six services stay on 30f6cd0e.
- Local MCP servers (`scripts/ops/run_mcp.sh ops|repair|workbench`) and the day trace dashboard
  (`python -m app.ops_trace_report_main`) read production only through this role.

## Output standard (operator-approved 2026-09-29)

- **Moments copy** (`moments-generator-v26-headline-hook`, rules v13; since 2026-09-30 15:21 the lean-context versions v27/v21 run the same contract): `🔎【小赛洞察】` / news headline
  (main line + 「sub line」 when it splits at a space or 破折号) / one parent-child hook sentence ending
  in one emoji / 新闻来源 / 原文链接 / `#赛先生科学 #… #…`, no blank lines, no brand sentence in the
  text. Facts and one rotated brand sentence stay structured claims for the long image only.
- **Long image**: 新闻看点 / 亲子探究 / 教学启发 cards and **no footer text** (footer-v6-none: no
  link, news date or source). Since 2026-09-30 (operator request) the empty band below the last
  card is trimmed: a formal poster ends 36 px (the side margin) below its last painted row
  (`daily-news-infographic-trim-v1-blank-bottom`, height 1600–2048). A painted bottom is kept.
- **Long-image review** (advisory policy v14, 2026-09-29): layout and wording findings never drop
  a poster. Headings fall back to neutral wording, a long frozen claim is shown by its verbatim
  leading clause, unusable model text is repaired or replaced by a neutral sentence and recorded
  as a warning. Only lineage (package / source / claim), ineligible packages, control characters,
  provider identity, raster checks and the daily image ceiling still stop a poster.
- **Daily long-image allowance** (2026-09-29): the scheduled slots share
  `WECOM_INFOGRAPHIC_DAILY_IMAGE_LIMIT` paid image calls per business date (default 12; nine
  posters plus room for re-versioned packages). Operator human picks are outside it: their
  posters are neither counted nor skipped by it. `WECOM_INFOGRAPHIC_HUMAN_PICK_DAILY_IMAGE_LIMIT`
  (default 30) is only a guard against a runaway caller, not a business limit.
- **Copy prompts** (2026-09-30): generator `moments-generator-v28-shared-quotes` (v27 lean
  context + each evidence quote written once) with auditor `moments-auditor-v21-lean-context`.
  Zhipu content-filter refusals (HTTP 400 code 1301) get one identical retry; the provider code
  is kept in the copy attempt's `safe_metadata.provider_error_code`.
- Changing this standard needs the operator's approval.

## Work not yet on mainline

`feature/daily-wecom-infographic-default-off` diverged from the production line in late August and
holds work production never ran. Port it onto mainline when it is needed, feature by feature,
instead of merging the branches:

- the exhibit / visitor display (`frontend/src/features/visitor-display`, `app/visitor_display*`),
  which runs locally against production through a read-only connector;
- IP-asset tooling, brand-RAG diversity experiments (two-lane retrieval), eval tooling, observability;
- official-account reviewer and manual-review work, including that branch's own migrations
  `0043_official_account_reviewer_observe`, `0044_official_account_reviewer_enforce`,
  `0045_manual_review_observability` and `0046_brand_table_normalization`. They were never applied to
  production and reuse revision numbers of mainline's chain; re-create them on top of mainline's head
  when ported. That branch's `0047_wecom_news_infographics` is superseded by mainline's 0049/0050.
