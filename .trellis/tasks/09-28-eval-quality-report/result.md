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
- 09-29 15:08 relaxed long-image review `87b7e75` (advisory policy v14 / copy v7 / generation
  prompt v7; image `…@sha256:52411a2d804991baa10988f985aafa4bab8b0d122ac274b840654bf01bf8eadd` =
  e6b3ebf9 + rich_copy / advisory / producer; backups `*.before-87b7e75-20260929T150808`).
  Operator asked to loosen long-image review. Replay on 09-15..09-29 packages: preflight 90/99 →
  98/99 (remaining refusal = real source mismatch), copy step 39/40 → 60/60 (3 repaired). Preview
  of the 09-29 noon#2 poster (refused at noon) generated with the new path and reviewed.
  Not changed: daily image ceiling (9 image intents per day, shared with human picks).
- 09-29 15:53 daily long-image allowance `80018cf` (branch `fix/infographic-daily-ceiling`):
  scheduled limit is a setting, default 12 (was a fixed 9); posters of operator human picks are
  neither counted nor skipped by it and only have a runaway guard of 30. Operator decisions:
  raise to 12 (this session) and 人工加推不受限 (exhibit session). Production before the change:
  the ceiling was never hit, no human-pick runs yet. Overlay image built and smoke-tested on the
  server: `…@sha256:b3ee53d5b055633ae81aa793ceb6d79beac314b7041458ee25e9c7c03b0ad963` = 52411a2d +
  wecom_news_infographic.py + config.py.
- 09-29 16:19 daily long-image allowance DEPLOYED on the operator's go-ahead: six app services on
  `…@sha256:b3ee53d5b055633ae81aa793ceb6d79beac314b7041458ee25e9c7c03b0ad963`; backups
  `*.before-80018cf-20260929T161923`; no job was running; services healthy, no errors in the
  first logs; effective settings 12 / 30, review mode advisory, max ordinal 3.
- 09-30 10:08 long-image blank bottom trimmed `6912996` (trim-v1; image
  `…@sha256:797dc3063388365bb8f0f5613bb652333e8d1225c26cbba5ea8ee3270c159fab` = b3ee53d5 +
  footer / producer / supplement + the 4 files that had drifted (3 quality_report, text-overlay
  tool), so the service app/ now equals mainline; backups `*.before-6912996-20260930T100805`).
  Operator asked to remove the empty band left by footer-v6: formal posters end 36 px below the
  last painted row (1600–2048 high), painted bottoms kept, send gates accept untrimmed v6. On 11
  real posters the 6 v6 ones trimmed 2048 → 1879–1954. No job was running; services healthy.
- 09-30 15:56 copy call stability `ba78146` (generator v28 shared quotes + auditor v21; zhipu
  1301 retried once, provider code kept): image
  `…@sha256:30f6cd0e176b6b1645282f1654472ad4d4882b77a2b39a4c93888921dcd3c25e` = 21c63fc9 + 8 app
  files; backups `*.before-ba78146-20260930T155556`; gate PASS; no job running; six services
  healthy, no errors; live bundle v28/v21. Owner: "现在就上线吧". Details and measurements:
  `.trellis/tasks/09-30-copy-call-stability/prd.md`.
- 10-01 11:32–11:43 read-only ops role + repair shadow job `c9d12f9` (feat/repair-agent-20260930):
  role `edu_ai_ops_ro` created outside delivery, after the noon slot's content was finished; seven
  write and privacy probes refused through the tunnel. Shadow image
  `…@sha256:2e43a0784a9fbc25596d52296b47d74e1c78778ad563a4a6104e671c1e0c3523` (30f6cd0e + 19 app
  files, base hashes verified 8/8). Gate `predeploy gate PASS @ c9d12f9`. Cron 21:10 installed, no
  service restarted. First replay: 6 blocked drafts since 09-24; 5 on v12 rules are now refused as
  not applicable; 1 valid (both arms passed). Owner: "现在就处理，不用等". Details:
  `.trellis/tasks/10-01-repair-shadow-ops/prd.md`.
- 10-01 22:30 auditor v22 + brand-repeat check + delivery watchdog + eval regression (mainline
  72a4930; owner: "确认"): image `…@sha256:7bffe4edfe8cc073b081e7e4d71eb175697f99383745472f0ec407000cff5646`
  = 30f6cd0e + app files of d9b534b + backend/evals; base hashes 10/10 verified; gate
  `predeploy gate PASS @ 72a4930` with an empty known-failure baseline; no job running; six
  services running, 0 restarts, 0 errors; live bundle v28/v22/v13. Backups
  `*.before-v22-20261001T223016`. Watchdog test run: evening OK (log only, no alert key yet).
- 10-01 23:12 fresh candidate pool + held human picks, release head 765fe1e (b564e95 selection,
  cdbbfb8 + 779e019 human pick; owner: "确认部署选题修复"): image
  `…@sha256:5887bce7440dee1bea94a9a32026e58403a78ccd7e4a0d2016fbace8d768980e` = 7bffe4ed + 9 app
  files; base hashes 9/9 matched the running image; gate `predeploy gate PASS @ 765fe1e` (0 known
  failures); offline smoke ok; no job running, 0 human picks ever; six services healthy, 0
  restarts, 0 errors; push route 422 (validation only). Backups `*.before-765fe1e-20261001T231206`.
  Cron images (watchdog, shadow, regression, quality report) unchanged, as the runbook says.
- 10-02 13:31 pool-aware cast planning + resized action images, release 11ad19c (owner: "确认"):
  image `…@sha256:b8fa7adaecbf24b0c5371245b9f8fec40ca3ad31b43c1cb5e23d36427117cba2` = 5887bce7 + 3 app
  files + plan_sim; base hashes 3/3 matched; gate `predeploy gate PASS @ 11ad19c`; host manifest and
  the 12 originals were byte-identical to the local ones; smoke on staged and then live materials:
  41 assets verified, 26 action images within budget (largest 3,494,296 B); no job running; six
  services healthy, 0 restarts, 0 errors. Backups `before-visual-pool-20261002T133009` (materials)
  and `*.before-visual-pool-20261002T133121` (env).

