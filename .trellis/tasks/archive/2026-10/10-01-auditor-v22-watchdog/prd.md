# 审查 v22、品牌句去重、漏发告警、评测回归

Backfilled 2026-10-02 from commits and the rollout log; the work was done on 2026-10-01.

## Source request (2026-10-01, owner)

"评测我们做的，怎么样了。你看看还有什么技术，需要优化的。" → six items proposed → "好的，都做吧。";
deploy: "确认".

## Goals

1. The auditor uses a closed set of error codes and the system decides severity, so off-topic hooks
   and outcome promises block reliably (v21 invented free-form codes and warned on them).
2. A first draft that repeats a recent accepted brand sentence gets one repair.
3. An alert when a slot did not go out as planned, without ever writing to the formal delivery group.
4. Evals can be repeated (verdict consistency) and rerun automatically when copy versions change.
5. The deploy gate starts from an empty known-failure baseline.

(The sixth item, scoring the freshest events instead of the first 500 by id, was the a8 session's
09-30-selection-fresh-candidate-pool; this session deployed it on 10-01 23:12.)

## What was built

- `moments-auditor-v22-enumerated-codes` as the default (d9b534b); provider contract tests cover
  the v21 and v22 formats.
- Domain `repeated_brand_claim_issues` (similarity >= 0.85 to a recent accepted brand sentence):
  error on the first draft, warning on the repair.
- `app/delivery_watchdog_main.py`: checks topic run, copy runs and deliveries per slot through the
  read-only ops role; alerts go only to `OPS_ALERT_WEBHOOK_KEY`; log only without a key.
- `evals/copy_audit_compare`: paired auditor comparison with `--repeats`, `regression.py`
  (runs when copy versions change or weekly, trend.csv), `accepted_replay.py` (re-audit of
  accepted production drafts).
- Known-failure baseline 28 → 0 (fc3e732, 9644d63, 72a4930).

## Acceptance and results

- Seeded drafts: v22 blocks 26/26 vs v21 18/26, clean drafts blocked 0/5
  (`backend/evals/copy_audit_compare/reports/2026-10-01-auditor-configs.md`).
- Regression on the deployed image: 16/16 blocked, 0/3 clean blocked, 0/19 inconsistent over
  three audits each.
- On 20 accepted production drafts v22 would block 3, all for one paraphrased brand sentence
  (`2026-10-01-accepted-replay.md`).
- Gate `predeploy gate PASS @ 72a4930` with an empty baseline.

## Rollout

Live 2026-10-01 22:30: image `sha256:7bffe4edfe8cc073b081e7e4d71eb175697f99383745472f0ec407000cff5646`;
bundle v28/v22/v13; six services healthy, 0 restarts, 0 errors. Crons on the pinned image:
watchdog 07:42/12:42/18:42, regression 21:25. Backups `*.before-v22-20261001T223016`.
Rollback: restore both env files and recreate the six services.

## Open

- The owner still has to provide an internal ops group webhook key; until then alerts are log only.
