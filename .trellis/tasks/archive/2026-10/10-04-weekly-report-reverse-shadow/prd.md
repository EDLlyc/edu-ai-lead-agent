# 每周汇总 + 反向影子

## Source request (2026-10-04, owner)

"就是你说的要积累的数据，你积累了吗？" → automatic data was accumulating but scattered, the
shadow job had lost its control arm, human labels and operator edits were 0 → "好的，请你处理"
for (1) a weekly summary and (2) a reverse shadow. Both read-only; no production behaviour change.

## Built

- Reverse shadow (810834c): the shadow job runs the arm production did not use (agent ↔ full
  regeneration) on each blocked draft; production's own agent fallbacks need no call; the
  workspace gets production's full brand context. Records copy-repair-shadow-v2.
- Weekly summary (d904e5e, 51c91df): `app/weekly_report_main.py`; this week vs last week from the
  database (READ ONLY) and the watchdog / action / shadow logs; Markdown, JSON, trend.csv. Each
  watchdog slot counts once; image reuse only for selector v3.

## Rollout (2026-10-04 16:57)

- Ops cron image `sha256:6d14ef27553589f1ed5f80c59ae6c310ba973098596b260b738546f784878d6e`
  (tag ops-51c91df) = app image 1f238fc2 + every backend/app file changed in de22d32..51c91df
  (its app/ equals mainline 51c91df); bases 29/29; smoke ok; gate PASS @ 51c91df.
- `/usr/local/sbin/edu-ai-weekly-report` + `/etc/cron.d/edu-ai-weekly-report` (Mondays 09:20);
  first report `reports/weekly/week-2026-10-03.md` written.
- `/usr/local/sbin/edu-ai-copy-repair-shadow` repinned (backup
  `*.before-51c91df-20261004T165726`); next run 21:10 tonight; shadow dry-run found 8 runs.
- Not changed: the six app services (1f238fc2), the report / watchdog / ops-action / regression
  crons.

## Notes

- The 10-03 agent-repaired runs were already recorded by the v1 shadow (agent replayed), so they
  have no regeneration arm; from 10-04 on, both arms are recorded.
- Still 0: human labels (labelling page is stopped) and operator edits (no human pick used yet).
