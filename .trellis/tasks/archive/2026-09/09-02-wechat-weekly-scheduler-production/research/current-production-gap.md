# Current Production Gap Evidence

Checked on 2026-09-02 against the repository and production host.

- `WeeklyEditionSchedule` owns Monday 09:00 `Asia/Shanghai` with a 24-hour catch-up window.
- Production has no `official-account-weekly-dag-worker` container, no weekly scheduler container, and no matching Cron/Systemd timer.
- `official_account_weekly_dag_main.py` constructs only `LocalWeeklyDagFixtureHandlers`; its default enqueue input is a fixed fixture fingerprint.
- The backend weekly spec explicitly describes this DAG as development-only and default-off.
- The WeChat draft artifact discovery requires authenticated live weekly provenance and rejects fixture batches.
- Production database head is `20260901_0042`; weekly DAG runs and WeChat draft jobs/items/attempts are empty.
- Production contains real material-package history but no official-account article runs yet, so starting only the existing fixture DAG would not satisfy the user's real-draft outcome.
- Current production runtime is isolated commit `267ffddc3c13ac7c3c874e6902b5c09bdeaa0e1e`; current `main` has unrelated in-progress Reviewer/ranking/IP/report work and cannot be deployed wholesale for this task.

Conclusion: the task must add a truthful production input/handler path and scheduler. Merely starting the existing DAG profile or adding host Cron would create a misleading running process and no eligible real drafts.
