# Result — 评测门禁、埋雷测试、人工标注导出与文案模板评测

Branch `feat/eval-gates-20260929` (worktree `.trellis/worktrees/eval-gates-20260929`), based on
mainline `4540a63`. Not committed, not deployed; no `app/` change.

## 1. Pre-deploy gate — done

- `backend/evals/gate/` + `make predeploy-check` / `make predeploy-check-fast`;
  `backend/tests/known-failures.txt` (28 entries, may only shrink); guide updated
  (`.trellis/spec/guides/production-mainline.md`: gate first).
- First full run 2026-09-29 16:28 CST: **PASS** — 10 suites passed, 1 skipped (private visual
  asset manifest), unit + contract tests 28 known failures, no new failure; 276 s.
- Found on the way, fixed: `topic_rerank` (`priority-barrier`) and four selection unit tests were
  red on mainline. Cause: fixtures built `TopicScoringConfig` with the default scoring version and
  the obsolete Ministry priority rule, which disables priority
  (`ministry_priority_disabled_for_config`), so the barrier cases had no priority candidate.
  Fixtures now use `build_topic_scoring_config(Settings(_env_file=None))`. Verified with the
  production config that a crossing rerank falls back with `priority_barrier_violation`.
- Not part of the gate: `ip_asset_grounded_authoring` needs the private manifest; the 28 baseline
  failures are official-account / IP-asset fixture tests that need private assets.

## 2. Human review export — done

- `backend/evals/human_review/` + `make human-review-report STORE=…`; read-only; works on the
  current store (0 reviews → explains the routine).
- Exhibit (feature branch, main worktree, uncommitted): `visitor_review_store.py` records
  source URL, snippet, tier, score, threshold, rank and reasons taken from the server-side news
  pool; older files are upgraded with `ALTER TABLE`. Needs a connector restart to take effect.

## 3 + 4. Seeded defects and hook rubric — code done, first full run scheduled

- `backend/evals/copy_quality/` (`mutations.py`, `rubric.py`, `runner.py`), 13 defect types,
  call budget with a hard cap, `--plan` dry run, human spot-check sheet and `agreement`.
- Smoke run 2026-09-29 17:01 CST, 1 real topic, 15 calls (1 generation, 6 audits, 8 judge),
  45,964 input / 1,669 output tokens: control accepted; 9 defects applicable, 8 blocked (4 by the
  rules, 4 by the auditor), 1 warned only (hook unrelated to the news: `brand_fit`,
  `copy_fluency` warnings — it would still be pushed), 0 missed. The judge failed all 7 seeded
  bad hooks and passed the production hook. One topic, one trial: an observation, not a rate.
- Full run (10 topics, cap 220 calls) is scheduled for 19:37 CST, after the evening slot.

## Tests

`test_eval_gate.py` 7, `test_human_review_export.py` 5, `test_copy_quality_eval.py` 9; selection
suites green; ruff, format and mypy clean on the new code.
