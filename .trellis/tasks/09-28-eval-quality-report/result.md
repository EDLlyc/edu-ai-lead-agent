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
