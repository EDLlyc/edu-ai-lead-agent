# Design: Delivered Repeat Window

## Policy versioning

The existing `.6` scoring snapshot names `topic-veto-v3-governed-content` and has already been
persisted in production. Its behavior cannot be changed in place because `(profile, version)` is
immutable and replays must remain deterministic.

Introduce `scoring-v1-preview.7-delivered-repeat-history` as the new default scoring identity and
`topic-veto-v4-delivered-content` as its veto-rule identity. `.7` retains all `.6` weights, editorial/product rule identities,
Ministry priority behavior, threshold, freshness, ordering, and vetoes except for the provenance
of recent hard-repeat history. `.4`/`.5`/`.6` remain deserializable and use the legacy
selection-backed projection.

The stored veto-rule identity is the repository switch:

- legacy veto identities -> selection-backed `last_selected`
- new delivered-history veto identity -> delivery-backed `last_delivered`

This avoids an unversioned runtime flag and makes the behavior visible in every immutable run
snapshot and fingerprint.

## Data flow

For the new policy, a prior date qualifies only through existing typed lineage:

```text
daily_topic_selection OR content_slot_selection
  -> copy_generation_run
  -> material_package
  -> wecom_delivery_job(mode=formal, status=delivered)
  -> event_id + event_version_id + business_date
```

Use `DISTINCT` at the SQL projection boundary because one selection can have more than one package
or delivery job. Aggregate the latest qualifying business date by `event_id` exactly as the current
domain candidate expects. A newer failed/test job must not hide an older successful formal
delivery. The pure domain veto remains based on `days_since_last_selection`; only the
infrastructure provenance changes.

`status=delivered` is authoritative. The dispatcher reaches it only when every requested child is
`delivered` or `skipped`; no attempt-row reconstruction or provider response parsing is needed.

## Preserved behavior

- Historical selection rows continue to supply `prior_version_ids` for the existing
  category-Jaccard `theme_repetition` penalty.
- Same-day cross-slot exclusion remains exact `event_id` selection history. Waiting for delivery
  there would allow concurrent editions to select duplicates.
- The seven-day boundary remains `days < recent_selection_window_days`: days 1--6 veto, day 7
  allowed.
- No schema or OpenAPI change is required.

## Compatibility and rollout

- Application config recognizes both `.6` and `.7` as tiered editorial configurations and applies
  the same Ministry priority defaults, authenticated threshold bypass, and tiered feature map.
- Settings, `.env.example`, and the independent Compose interpolation default all move to `.7`.
  A production environment that explicitly pins `.6` will intentionally retain legacy behavior
  until a separately authorized config/release change.
- Repository tests must prove both version branches rather than mutating a historical snapshot.

The existing integration fixture in
`backend/tests/integration/test_wecom_slot_delivery_concurrency.py` already creates three complete
slot selection/copy/package/formal-job lineages. Extend that real-PostgreSQL boundary rather than
adding a mock-only SQL assertion, and add one minimal daily-origin lineage because no current
integration fixture exercises `daily_topic_selection_id` through delivery.

## Failure safety

An absent or incomplete delivery lineage produces no delivered-history entry, so it cannot create
a false hard veto. Query execution remains read-only inside the existing short SQLAlchemy session.
No provider call or external side effect is introduced.
