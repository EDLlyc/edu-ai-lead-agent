# 重复窗口以成功推送为准

## Goal

Prevent a topic from being suppressed for seven days merely because it was selected. The
`repeated_within_window` hard veto must represent audience-visible repetition: only a previous
successful formal Enterprise WeChat delivery counts as recent repetition.

## Background

- The current repository projects repeat history from `daily_topic_selections` and
  `content_slot_selections`. Downstream copy, image, package, or delivery failure is irrelevant to
  that projection.
- Production diagnosis on 2026-08-17 confirmed that the three blocked candidates had also been
  formally delivered, so those specific vetoes were correct. The defect is the broader contract:
  a selected-but-undelivered topic would also be blocked.
- `WeComDeliveryJobModel.status == "delivered"` is the durable terminal success state. The delivery
  service sets it only after every requested child is `delivered` or `skipped`.

## Requirements

- R1. For the new active scoring/veto policy, calculate `days_since_last_selection` from prior
  formal WeCom delivery jobs with terminal status `delivered`, not from selection rows alone.
- R2. A prior selection whose delivery is absent, test-mode, queued, running, partial, failed,
  cancelled, expired, or `delivery_unknown` must not trigger `repeated_within_window`.
- R3. Support both legacy daily and three-slot origins through their existing durable lineage:
  selection -> copy run -> material package -> WeCom delivery job.
- R4. Preserve the same-day exact-event exclusion based on durable selection rows. It prevents
  concurrent morning/noon/evening editions from selecting the same event before delivery and is
  outside the seven-day history change.
- R5. Preserve the existing category-based `theme_repetition` soft penalty. This task changes only
  the hard repeat-veto history basis.
- R6. Preserve deterministic replay of historical scoring configurations. Existing `.4`, `.5`,
  and `.6` snapshots retain selection-based repeat history; the delivered-history contract must
  use a new immutable scoring/veto policy identity with unchanged `.6` weights and threshold.
- R7. Do not add a migration or backfill. Existing delivery lineage is sufficient, and historical
  rows remain immutable.
- R8. Do not deploy, mutate production data, retry a production pipeline, or send a provider/WeCom
  message as part of repository implementation or verification.

## Acceptance Criteria

- [ ] A selected-but-undelivered prior daily topic does not populate the new policy's recent hard
  repeat history.
- [ ] A selected-but-undelivered prior slot topic does not populate the new policy's recent hard
  repeat history.
- [ ] Test-mode and every non-`delivered` formal job state do not count.
- [ ] A formal `delivered` job for either origin produces the exact business-date distance and
  triggers `repeated_within_window` for days 1--6; day 7 remains allowed.
- [ ] Multiple packages/jobs for one selection cannot duplicate or distort the most recent date.
- [ ] Historical `.6` config metadata still deserializes and retains selection-based behavior.
- [ ] The new default config has a distinct immutable scoring/veto identity and retains `.6`
  weights, threshold, editorial rules, priority rules, and ordering.
- [ ] Same-day exclusion and `theme_repetition` behavior are unchanged.
- [ ] Focused unit and real-PostgreSQL integration tests, Ruff, strict mypy, and relevant drift
  checks pass.

## Out of Scope

- Changing the seven-day duration, numeric threshold, freshness window, or same-day slot rules.
- Treating public/social/manual exports outside the existing formal WeCom delivery table as a
  successful push.
- Production deployment, configuration activation, data repair, or replaying 2026-08-17 slots.
