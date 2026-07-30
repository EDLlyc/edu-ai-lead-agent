# Design: Daily Topic Selection and Locking

## Boundary

Consume current governed event versions and produce one immutable daily selection or `no_topic`.
Do not browse, summarize, retrieve brand context, generate copy, or call an LLM for the score.

## Data Flow

```text
business-date cutoff
  -> load eligible current event projections
  -> hard veto evaluation
  -> deterministic feature normalization
  -> scoring-v1-preview weights/penalties
  -> stable rank and threshold
  -> short-transaction Top 1 lock / no_topic
  -> query API and downstream content trigger
```

## Contracts

- A scoring config is immutable and contains feature definitions/ranges, weights, penalties,
  threshold, veto/rule versions, recent-selection window, and tie-break order.
- A run records its business date/timezone, governed-event cutoff, active config fingerprint,
  considered event versions, status, selected event/version, and no-topic code.
- Each score row stores raw+normalized features, veto codes, positive/negative components, total,
  eligibility, rank, and explanation.
- A daily lock has a unique business key and references the exact immutable event/config versions.
- Preview configs may schedule the internal functional MVP when explicitly marked `preview`; a
  production profile later requires explicit approval and a new immutable version.

## Scoring Evaluation

Create controlled cases for each veto/range/tie/threshold plus a labeled real-event set. Report
precision-oriented errors: false eligibility, false veto, undesirable Top 1, and excessive
no-topic. The functional MVP first exposes a clearly labeled preview config. Later product approval
records the tuned config version/fingerprint and evaluation artifact, not an unversioned choice.

## Persistence and Concurrency

Use Alembic/SQLAlchemy async, UUIDs, UTC instants plus separate business date/timezone, named
constraints, and short transactions. Multiple schedulers may create the same run safely. Final
locking rechecks the active config/cutoff and uses uniqueness plus row/advisory locking. Replays
reuse score rows for the same event/config/cutoff fingerprint.

## API and Runtime

- `POST /api/v1/topic-selection-runs` -> 202 durable run.
- `GET /api/v1/topic-selection-runs/{id}` and `/scores`.
- `GET /api/v1/daily-topics/{business_date}` -> selected/no-topic explanation.
- A content scheduler/worker shell may be introduced here, but only selection job kinds are enabled.

## Rollout

Deploy schema/code disabled, seed the preview config, run focused controlled+real checks, then enable
the internal functional path. Later calibration activates a new production config version. Rollback
deactivates config/scheduler and preserves scores/selections.
