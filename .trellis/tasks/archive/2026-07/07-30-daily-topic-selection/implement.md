# Implementation Plan: Daily Topic Selection Preview

- [x] Define transparent `scoring-v1-preview` vetoes, factor ranges, weights, penalties, threshold,
      seven-day repetition, and stable tie-breaks from the technical report.
- [x] Implement pure scoring/rank/no-topic rules and focused critical unit cases.
- [x] Add minimal versioned config/run/score/daily-selection persistence and Alembic migration.
- [x] Add short repositories for governed-event cutoff, idempotent score rows, and one daily lock.
- [x] Add manual/daily trigger, lightweight worker path, and run/score/daily-result APIs.
- [x] Run focused PostgreSQL/API checks and demonstrate rankings on current real governed events.
- [x] Record observed ranking limitations and production calibration backlog.
- [x] Update specs, check, commit, and archive the child.

Deferred: large labeled evaluation, exhaustive contention/crash recovery, weight-management UI,
and production scoring activation. Upgrade seams and historical versioning are required now.
