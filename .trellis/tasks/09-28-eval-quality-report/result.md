# Result (2026-09-28)

## Topic golden set (`backend/evals/topic_golden`, 13 cases, 7 real)

| Version | Must select eligible | Must select with priority | Should-not rejected | Passed |
|---|---|---|---|---|
| `.11` (production until 16:43) | 2/7 | 1/6 | 4/6 | 6/13 |
| `.13` (current) | 6/7 | 5/6 | 4/6 | 10/13 |

Open gaps kept visible in `canonical-report.md`:

- `g05` 政府网“融合升级 新型工业化提速” (operator asked for high priority on 08-27): out of scope —
  no industrial/intelligent-manufacturing topic terms. Adding the source on 08-27 never made the
  content qualify.
- `g07` 男子编造“某院士窃取他人科研成果”谣言，已被刑拘: **actually pushed on 2026-09-27 evening**.
  Real governed projection mentions "利用AI软件生成虚假视频" with categories
  `ai_governance_safety`/`large_generative_models`, so it scored as frontier tech; governance did not
  set `unsuitable_negative_incident`. Both copy failures that day were `provider_request_rejected`.
- `n05` trade forum with an incidental AI mention: selected by `.11`/`.13` (this is what the
  unshipped `.12` substantive filter targets).

## Daily quality report

- Code: `app/domain/quality_report.py`, `app/infrastructure/db/quality_report.py`,
  `app/application/services/quality_report.py`, `app/quality_report_main.py`; `make quality-report`.
- Production: overlay image `…@sha256:48f090443254506de19a33ba2e6fbb33b698a1accc7e97d1dafb5ce8e3c79f4c`
  (= running `.13` image + the four new files, verified absent before). Installed
  `/usr/local/sbin/edu-ai-quality-report` and `/etc/cron.d/edu-ai-quality-report` (21:40 CST).
  No service restarted. First report (2026-09-27): 9/9 slot picks, copy 7 accepted / 2 failed
  (`provider_request_rejected`), 7/7 formal WeCom delivered, 12 failed acquisition jobs
  (`conflict`×9, `parse_failure`×3), no brand-snippet repetition (top snippet 3/55 in 7 days).

## Validation

- Unit: `test_quality_report.py`, `test_topic_golden_eval.py` (+ education-policy and topic-selection
  suites) pass. Integration: `test_quality_report.py` runs every report query read-only against a
  freshly migrated schema. ruff + mypy clean.

## Fixes from the first findings (`.14`, 2026-09-28 evening)

- Golden set with `.14`: must select 7/7, with priority 6/6, should-not rejected 5/6 (only `n05`
  trade-forum incidental AI remains, the `.12` territory); must-select headlines fetched with
  priority 7/7.
- Acquisition failure diagnosis: cas-research failing every run since 2026-09-19, bnu-news since
  09-27, stdaily-tech intermittent — all `conflict` (a repository idempotency `ConflictError`, not
  HTTP). The failure log did not say which check; `acquisition_job_failed` now logs the static
  `error_message` so the next run identifies it. sensetime-news `parse_failure` since 09-12
  (likely a site redesign) — not changed.
- Selection too academic (3/9 niche materials-science picks on 09-27): operator chose to
  down-weight; `.14` adds `research-accessibility-v1` (×0.6 editorial/frontier, never excluded).

## Production rollouts (2026-09-28 night)

- 22:45 `.14` (image `…@sha256:528bd430…` = report + `.14` + SenseTime deactivation). `.env`
  `CONTENT_SCORING_VERSION=scoring-v1-preview.14-negative-incident-industrial-tech`;
  `python -m app.seed_sources` disabled sensetime-news (10 enabled sources). Recreated
  acquisition-api/worker, content-scheduler/worker. Backups `*.before-v14-20260928T224526`.
- First evening with `.13` + first formal long image (before `.14`): 3 national 教育风向 picks, two of
  them the same 高校分类改革 story; #1 long image delivered (banner 「AI生成 · 内容/排版未核实」 on top);
  #2 blocked in copy review by `unverified_superlative` on an official quote; #3 infographic
  `moments_preflight_failed` (reason not logged).
- 23:02 `a05bc78` (image `…@sha256:9cfbf9e739e63d324c9b48a70b72d7af1999d02f1ea73ca1d9013c74449b0b59`):
  unmarked long images (notice v2, prompt v5; producer and supplement send gate both unmarked),
  evidence-bound superlatives, `slot-ranking-v2-same-topic-dedup` (`.env`
  `CONTENT_SLOT_RANKING_VERSION`). Recreated acquisition-api/worker, content-scheduler/worker,
  wecom-infographic-producer, wecom-dispatcher; all healthy, infographic flags unchanged. Backups
  `*.before-a05bc78-20260928T230211`. Report cron image repointed. First runs: 2026-09-29 07:00.
- Rollback: restore the matching backup pair and recreate the same services with
  `sudo docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env up -d --no-deps …`.

## Relaxed review (2026-09-28 late, operator: 放宽审核限制)

- Copy `moments-rules-v12…`: an unbound superlative about the news is now a warning; one in a
  sentence about the brand (赛先生/小赛/我们…) stays an error. Evidence-quoted superlatives pass.
  This week's review_required runs (2) were both `unverified_superlative`.
- Long image advisory layout: title prefers the real news headline (≤34 chars, 【…】 removed), the
  child card heading is 「亲子探究：和孩子一起想一想」 (no repeated anchor), and when the only
  topic-sharing fact is too long for the 96-char card a shorter exact fact of the same package is
  used with an anchor from the headline (09-28 evening #3 `moments_preflight_failed`: 100-char
  fact left 11 chars vs 16 minimum). Advisory copy/generation versions v6. Preflight failures now
  log the static rule message.
- `.14` repeat history counts provider-rejected copy (7 of 20 failed/review runs 09-21..28 were
  `provider_request_rejected`; one astronomy story was picked and rejected four days running).
- 23:48 `d5fc861` (image `…@sha256:d0acb505fe16806b683f236e67e870ed8335b1b8aa418ac57b382c118a6dfc84`):
  Moments brand rotation, generator prompt `moments-generator-v25-brand-rotation` (config default).
  Cause of the repeated 「AI不直接给答案」: the fixed brand query returned the same six chunks for
  every topic (83/84 runs since 09-18) and the most-cited interview chunk (63/84) also carries the
  思维链 sentence. Now: topic-only query + a positioning-card (7真) lane with two reserved slots;
  chunks cited by / sharing an 8-char phrase with brand statements of accepted copy in the last 3
  days go last (cards cycle least-recently-used first); prompt lists ≤12 recent brand statements.
  Read-only replay of the six 09-28 topics (simulated sequential rotation): six different angles
  (真动手/真思考/6-8人小班/真表达/真作品/真反馈), none repeated the old line; 5 validated + audited on
  the first draft, 1 had an unrelated `source_note_unlinked` (normal single repair). Same six
  services recreated; backups `*.before-d5fc861-20260928T234819`.
- 09-29 00:2x report v2 `9f59f93` (`production-quality-daily-v2`): fixed the brand_usage inner join
  on brand_sections that hid section-less chunks (v1 showed 真助力 5; actual top chunk 37/52);
  added brand-phrase repetition, today's brand angle per copy, selection audit
  (negative incident → critical, same-day same-topic pairs, specialised-research tag), copy
  prompt versions, failure codes and failing sources; folded in the human-pick report hunks.
  Report cron image → `…@sha256:edfe02dd7ce3aaf96f3aa91ebb194f502947e752d3b8f98b8a58e44204312c86`
  (d0acb505 + 3 report files; script backup `edu-ai-quality-report.before-9f59f93-*`);
  09-28 regenerated with v2 (v1 kept as `2026-09-28.v1.*`). No service restarted.
- 09-29 00:36 scoring `.15` `6c8df55` (image `…@sha256:f4b0cff0c4c15c576991b17da237d86f247eb42a7d2c97456ae6e6637396b59e`
  = human-pick image `3c89845f` + 4 topic files): gov.cn 要闻 priority only for science /
  technology / industry / education headlines (diplomacy and trade never; 16 of the 23
  09-19..09-28 priority picks lose priority, the 7 science/industry ones keep it); repeat window
  14 days (水利/望宇登月服 were re-delivered 7 days apart). Operator chose to keep filling three
  per slot, so ungated news can still fill a thin pool by score. `.env`
  `CONTENT_SCORING_VERSION=scoring-v1-preview.15-gov-yaowen-topic-gate`; backups
  `*.before-6c8df55-20260929T003542`. Golden set 17 cases: `.15` 16/17 (n05 pre-existing).
- 09-29 ~01:30 evaluation suite (`29071d7`, `1b14217`, this commit):
  - `evals/selection_replay` (production data, read-only, no LLM): 09-19..09-28, 30 slot runs.
    gov.cn priority production 28 / `.14` 22 / `.15` 6 (off-topic 21/16/0); 14-day same-event
    repeats 18/11/0; similar-article cross-day repeats remain ~11 (same theme on consecutive days,
    e.g. 先进制造业 ×3) — candidate for a cross-day theme rule (operator decision).
  - `evals/same_topic_golden`: production headline clause precision 0.438 on 20 real pairs
    (开幕式并致辞, years/amounts, issuing bodies, 北京师范大学, column prefixes); a
    boilerplate-stripping candidate 1.0 at equal recall — not deployed, awaiting decision.
  - Quality report v3 (cron image `…@sha256:f354b56e88b1300eb3d4552fc4f93f652b791c7c8eb5bbb92049df073732f9e4`
    = f4b0cff0 + report files; script backup `edu-ai-quality-report.before-1b14217-*`): repeats vs
    delivered news, gov priority off-topic check, match kinds, 7-day trend. 09-28 regenerated
    (v2 kept as `.v2.*`).
  - `evals/copy_replay`: v24 vs v25 on 09-28 — recent brand phrase reuse 6/6 vs 2/6.
  - `make eval` runs the offline suites (topic golden, same-topic, brand retrieval).
- 09-29 10:00 slot-ranking v3 `ed390cf` (image `…@sha256:00aedca2caf80082e9abbe4dec260a02fb8d88d64fd36e77db864af3cd1fbebc`
  = f4b0cff0 + config.py + content_slots.py; the overlaid content_slots.py is the human-pick
  0d3742c version + the ed390cf patch). `.env` CONTENT_SLOT_RANKING_VERSION=slot-ranking-v3-strict-headline-dedup;
  backups `*.before-ed390cf-20260929T100027`. Headline same-topic clause precision 0.44 → 1.0 on
  the golden pairs. Operator declined a cross-day same-theme rule. Report cron image
  `…@sha256:518b16d8f88eae7311d7638969241625ce47c018deeaea2685fff77e44f49141`.
- 09-29 07:00 first run with v25 copy + `.15`: 3 picks, 3/3 copy accepted first pass with three
  different brand angles (小班直播 / 真表达 / 真思考), 3 WeCom deliveries, 3 long images.
- 09-29 10:20 acquisition fix `f1a45bd` (image `…@sha256:d89e8ed7f7152707cbb762bdd0d7e20781bee9ac7830feb49ec09c91ee3ced77`
  = 00aedca2 + execute_acquisition.py / ports/acquisition.py / db/repositories.py; backups
  `*.before-f1a45bd-20260929T102041`). Root cause of the bnu-news / cas-research / stdaily-tech
  `conflict` since 09-24: source-image discovery ran for re-fetched known articles against a new
  detail snapshot (page HTML changed) → "source image detail lineage is invalid" aborted the job.
  Images now follow only the candidate's own snapshot. Integration test reproduces the production
  error without the fix.
- 09-29 11:00 acquisition fix verified: noon fetch — bnu-news, cas-research (7 new), stdaily-tech (7 new)
  all succeeded; all 10 sources succeeded.
- 09-29 11:02 Moments headline-hook template `73fbc5c` (image `…@sha256:4244fb81…`; backups
  `*.before-73fbc5c-20260929T110241`): 🔎【小赛洞察】 + headline (main + 「sub」) + one hook + source +
  tags; facts/brand stay structured long-image material. Noon 09-29 was the first run: 2 accepted,
  1 `invalid_provider_output` (model added an extra claim field), long images 1 ready / 1
  `moments_preflight_failed` (pre-existing layout limitation). 72c9ce1: no split at a space before a
  quoted term.
- 09-29 11:15 no link on delivered long images `33dcfd8` (footer-v5-no-link; image `…3f2af5b3…`),
  11:21 `f2eaa42` supplement gate also accepts the byte-identical footer-v4 for posters made before
  the switch (image `…@sha256:10a455e78a9bb4c971926384ffd3108d482402b16a9107e83049a0ee4587c233`;
  backups `*.before-f2eaa42-20260929T112126`). Operator requests (teacher): copy template and
  图片上不放链接.
- 09-29 11:42 footer v6 `cd2cb51` (image `…@sha256:e6b3ebf9a87d05c589334f42afad20b7c432aaf47ffd8683817188e946c673cf`;
  backups `*.before-cd2cb51-20260929T114150`): operator asked to also drop 新闻日期/新闻来源 — delivered
  long images carry no footer text and end on the model's reserved background band; advisory footer
  OCR recorded as footer_ocr_unavailable; send gates accept v6/v5/v4 (byte-identical to originals).
