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
