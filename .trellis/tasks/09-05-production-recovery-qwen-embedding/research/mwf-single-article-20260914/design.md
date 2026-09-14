# M/W/F single-article design direction

## Confirmed seams

Production-shaped code in `.trellis/worktrees/release-hardening`:

- `official_account_weekly_scheduler_main.py`: Monday-only cron, interval/startup
  reconciliation and deterministic weekly identity; all require replacement-mode routing.
- `infrastructure/db/official_account_weekly_production.py`: loads stored material
  packages and their exact daily/content-slot score rows; validates source snapshots
  and deduplicates by event before selecting three.
- `domain/official_account_weekly_edition.py::select_weekly_articles`: current
  seven-day event window, fourteen-day official lookback, eligibility/veto checks,
  official/industry/application allocation and deterministic affinity/score ordering.
- `application/services/official_account_weekly_production.py`: waits on persisted
  article runs; converts review-required into provider-terminal.
- `domain/official_account_weekly_dag.py::derive_weekly_dag_run_status` and DB claim
  filtering terminate all remaining work when any child is terminal.
- `application/services/wechat_official_account_draft_jobs.py`: requires the closed
  three-item envelope, despite calling the underlying prepared single-draft creator.

## Selected architecture

Introduce a versioned date-scoped single-edition owner, preserving literal legacy
weekly formats. Reuse governed material/source projection and the current article
worker, canonical prepared renderer and draft creator. Do not fake a three-child
batch using duplicate/dummy articles or use a shell cron to bypass durable effects.

Keep publisher credentials only in the existing draft consumer. The producer owns
selection and preparation; delivery becomes eligible at the frozen local target
instant. Freeze date, schedule/version, selected event/material, editorial identity,
account binding, retry policy, article/content identity and acknowledgement ownership.
Prepare ahead of the target with a bounded configurable lead time. A restart after
target may finish that day's unacknowledged edition within an explicit catch-up
window; activation must not admit dates before its prospective cutover.

Read prior independent-delivery code as a reuse candidate, not as already-live code.
Before implementation, select the minimal compatible repository/envelope seams and
resolve any additive database migration from the actual single production head.
The existing 0044 independent-delivery migration cannot be copied over the deployed
lineage. These are technical implementation decisions, not permission to widen scope.

## Selection behavior

Keep the current stored eligible/veto-free candidate and score semantics. Rank one
fresh candidate without mandatory three-category quotas; apply accountable history
exclusion for delivered article/event identity. Category diversity is a preference,
not an excuse to manufacture authority or reuse a delivered story. The present
freshness window uses governed event time (event_time_start, else version created_at),
not proof of the source page's publication time; do not describe all pool items as
newly published reports without separate evidence.

## Compatibility and activation

Turn off old weekly new admission when the new mode is enabled; reject overlapping
active modes. Keep legacy history and acknowledged/manual outcomes intact. Do not
clear unknown outcomes, reset retries, or rerun the September 14 batch. Preserve
production's existing live Zhipu bytes and immutable image release discipline.
Activation/rollback must account for new admitted work and cannot erase durable
acknowledgements. No automated subscriber publishing is introduced.
