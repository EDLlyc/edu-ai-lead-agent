# Production Mainline

> Decided 2026-09-29: the branch that production runs is the mainline. Develop and release from it.

## The branch

- **`mainline`** is exactly what production runs (backend `app/` and `alembic/` verified byte-identical
  to the running service image and the quality-report cron image on 2026-09-29).
- Start every feature, fix and release branch from `mainline`; merge back into it after deploy.
- The production database follows mainline's migration chain (…0048 → 0049 wecom_news_infographics →
  0050 infographic_advisory → 0051 human_pick_lanes). New migrations go on top of it.

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
