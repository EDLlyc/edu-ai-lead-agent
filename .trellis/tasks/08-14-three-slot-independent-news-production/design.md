# Technical design: three-slot independent news production

## 1. Architecture decision

Implement one compatibility-preserving vertical slice with staged internal gates. Do not split the
work into separately releasable child tasks: acquisition identity, slot selection, copy origin,
delivery windows and the API contract share one migration and must agree before any new scheduler is
enabled.

The existing daily Top 1 path remains intact. New behavior uses a parallel slot aggregate and reuses
the existing governed candidate scoring, copy, image, material-package and delivery components at
their typed boundaries.

```text
slot acquisition (target - 90m)
  -> existing governance for that acquisition run
  -> slot run with immutable cutoff/config
  -> existing .6 eligibility + vetoes
  -> slot-ranking-v1 ordering of eligible candidates only
  -> 0..3 ordered slot selections
  -> one copy run per selection
  -> one image + one material package per copy run
  -> one delivery window/lane per slot
  -> one formal job per ready package
  -> text then image; >=60s between package starts
```

## 2. Domain contracts

### 2.1 Stable slot identity

Add a shared exhaustive `ContentSlot` value object with exactly `morning`, `noon`, and `evening`.
One owner provides display name, stable order and settings projection. API, scheduler, persistence,
logs and frontend must consume this owner rather than duplicate strings.

`ContentSlotSchedule` contains:

- slot and display name;
- enabled flag;
- `Asia/Shanghai` target hour/minute;
- preparation lead (default 90 minutes, bounded 30--180);
- delivery lateness window (default 60 minutes, bounded 0--120);
- maximum items (default/max 3, bounded 1--3);
- immutable schedule policy version.

Helper functions compute timezone-aware preparation, target and expiry instants for a business date,
including process restart/catch-up behavior. No layer compares naive datetimes.

### 2.2 Base eligibility versus slot ordering

Refactor the pure current topic selector only enough to expose its existing score computation. The
legacy `select_daily_topic` result and every `.4`/`.5`/`.6` fixture remain byte/field compatible.

New `select_slot_topics` performs:

1. load the immutable `.6` config and governed candidate projections at the run cutoff;
2. compute the existing base score, threshold state, eligibility, Ministry priority and vetoes;
3. remove events already selected on the same business date and existing seven-day repeats;
4. derive a bounded slot affinity from stored governed/editorial reason codes, categories and
   product-direction IDs—never by rescanning raw article text;
5. order authenticated Ministry education priority first, then eligible candidates by a bounded
   ordering value, base score and the existing stable tie-break inputs;
6. take at most three; persist every considered score and explicit unfilled reason codes.

`slot-ranking-v1` is a separate immutable policy. Its affinity may alter order among eligible
candidates but never changes base total, threshold, eligibility or vetoes. Explanation snapshots
contain base scoring version, slot policy version, affinity value/reasons, prior-day/earlier-slot
exclusions and the final stable key.

### 2.3 Independent content origin

Extend the internal locked-topic projection to a discriminated origin:

- `legacy_daily`: current daily selection ID;
- `content_slot`: slot selection ID, slot and ordinal.

Exactly one origin is present. Copy prompts continue receiving one topic and its evidence; slot
metadata is operational provenance, not a reason to fuse topics or add claims. Copy/image/package
fingerprints include the selected event/version and origin ID, guaranteeing independent artifacts.

## 3. Persistence design

Create migration `20260814_0020_three_slot_independent_news.py` from current head
`20260807_0019`.

### 3.1 Scheduled acquisition identity

Add nullable `content_slot` to `acquisition_runs`.

- Historical rows remain null and retain the existing legacy scheduled unique key.
- New slot scheduled runs use a partial unique key on
  `(business_date, timezone, acquisition_version, content_slot)` where the trigger is scheduled and
  `content_slot IS NOT NULL`.
- Repository create/recovery lookups use the same typed key. Manual acquisition behavior remains
  unchanged unless an explicit slot is supplied through the new internal scheduler seam.

Governance already owns a one-run-per-acquisition relationship; no new provider boundary is needed.

### 3.2 New slot aggregate

Add:

`content_slot_runs`

- ID, business date, timezone, slot, scoring profile;
- exact acquisition/governance lineage and governed cutoff;
- scoring config ID/fingerprint/snapshot and slot policy version/fingerprint/snapshot;
- preparation/target/expiry instants and item limit;
- status, total/eligible/selected/unfilled counts, unfilled reason codes and timestamps;
- unique immutable business key for date/timezone/slot/profile/policy identity.

`content_slot_scores`

- run, event/version pair and all existing base scoring projections;
- slot affinity value/reasons, same-day exclusion state, final ordering value/key and rank;
- nullable selected ordinal;
- unique `(run_id, event_id)`, `(run_id, rank)` and selected ordinal constraints.

`content_slot_selections`

- run, duplicated typed date/timezone/slot for constraints/audit, ordinal 1--3;
- selected event/version and the owning score row;
- unique `(run_id, ordinal)`, `(run_id, event_id)` and
  `(business_date, timezone, selected_event_id)` to enforce cross-slot daily uniqueness for new
  selections;
- composite event/version FKs and immutable creation time.

Run creation/decision holds a transaction-level advisory lock derived from business date/timezone.
It queries legacy daily selections as an exclusion during a transition day, then relies on the new
cross-slot unique constraint for concurrent slot decisions.

### 3.3 Copy origin compatibility

Add nullable `content_slot_selection_id` to `copy_generation_runs`; make
`daily_topic_selection_id` nullable and add a check constraint requiring exactly one non-null origin.
Keep the existing legacy unique key and add a slot-selection/version-fingerprint unique key.

All historical rows satisfy the legacy branch without updates. Repository projections resolve the
origin through an explicit union, not optional JSON fields.

### 3.4 Delivery windows and persistent throttling

Add `wecom_delivery_windows`:

- date/timezone/slot, projected recipient, provider and formal mode;
- target, expiry, configured package gap and `next_allowed_at`;
- unique date/timezone/slot/recipient/provider/mode key;
- created/updated timestamps.

Add nullable window ID, slot selection ID, sequence ordinal, `not_before`, and `expires_at` to
`wecom_delivery_jobs`. Legacy jobs retain null fields and their current behavior.

Slot job creation is unique by package/request fingerprint and window/ordinal. Claiming a slot job:

1. selects a non-expired ready job with the lowest currently ready ordinal;
2. locks its delivery-window row in the same transaction;
3. requires `next_allowed_at <= now`;
4. marks the job running and advances `next_allowed_at = now + gap` before the external call;
5. performs provider calls outside the transaction under the existing lease.

If a job reaches expiry before it starts, persist a typed `delivery_window_expired` terminal result
without a provider call. A not-ready/failed/unknown lower ordinal does not block a ready higher
ordinal. Text/image child state and unknown-result behavior remain unchanged.

The current date-wide formal guard remains authoritative for legacy-origin packages. Slot-origin
automatic reconciliation instead requires the typed window, one job per package, ordinal identity,
quality predicates, target/expiry checks and the final enqueue guard.

## 4. Scheduling and orchestration

### 4.1 Feature flags and defaults

Add shared bounded settings and Compose wiring:

- `CONTENT_SLOT_MODE_ENABLED=false`;
- `CONTENT_MORNING_ENABLED=false`, `CONTENT_NOON_ENABLED=false`,
  `CONTENT_EVENING_ENABLED=false`;
- per-slot target hour/minute defaults 07:30, 12:30, 18:30;
- `CONTENT_SLOT_PREPARE_LEAD_MINUTES=90`;
- `CONTENT_SLOT_DELIVERY_LATE_MINUTES=60`;
- `CONTENT_SLOT_MAX_ITEMS=3`;
- `CONTENT_SLOT_RANKING_VERSION=slot-ranking-v1`;
- `WECOM_SLOT_PACKAGE_GAP_SECONDS=60`.

When slot mode is false, existing daily acquisition/content scheduling and delivery are unchanged.
When true, only enabled slots schedule; the legacy daily content cron is not also run.

### 4.2 Acquisition and governance

The acquisition scheduler registers one cron per enabled slot at `target - prepare_lead`. Startup
reconciliation evaluates every enabled slot independently against catch-up bounds. Each source keeps
its existing cursor/rate limit, so later slot runs are incremental and safe.

The governance scheduler continues reconciling each terminal acquisition run. Slot readiness names
the exact acquisition and governance runs; unrelated terminal runs on the same date cannot satisfy
the gate.

### 4.3 Selection and material preparation

The content scheduler poll loop:

1. finds enabled slot acquisition/governance pairs that are terminal and lack a slot run;
2. creates one immutable run/cutoff and selection job;
3. after selection completes, creates one copy run per selected item;
4. existing content workers independently generate copy, image and material package;
5. automatic delivery reconciliation creates window-bound formal jobs for packages that become
   eligible before expiry.

No provider is called for vetoed candidates, unfilled positions, `no_selection`, expired delivery
opportunities or replayed completed content.

## 5. API and frontend contracts

Add compatible endpoints:

- `POST /api/v1/content-slot-runs` for bounded manual/admin enqueue by date and slot;
- `GET /api/v1/content-slot-runs/{run_id}`;
- `GET /api/v1/content-slot-runs/{run_id}/scores`;
- `GET /api/v1/content-editions/{business_date}?profile=preview` returning all three slot states,
  0--3 ordered selections, unfilled reasons and downstream safe status links.

Existing acquisition responses may add an optional `content_slot`; old clients tolerate the
OpenAPI-versioned optional field. Existing daily topic endpoints retain their current response and
do not synthesize a misleading multi-slot Top 1.

Material-package projections add optional slot, ordinal, target and expiry fields. The frontend adds
a date-oriented three-slot board and reuses the existing material package card/panel for every
independent item. Empty, partial, preparing, ready, expired and failed states are explicit and
accessible. All wire types come from regenerated OpenAPI.

## 6. Compatibility and migration

- No historical acquisition, topic score, daily selection, copy, image, package or delivery row is
  rewritten.
- Legacy daily scheduling remains the default and exact rollback path until production explicitly
  enables slot mode.
- `.4`, `.5`, `.6` config deserialization and `select_daily_topic` behavior remain covered by exact
  tests. `slot-ranking-v1` composes after `.6`; it is not a `.7` reinterpretation.
- Alembic upgrade verifies current data against the XOR and new constraints. Downgrade removes only
  new slot structures/nullable fields and restores the legacy non-null copy origin after verifying
  no slot-origin rows remain; downgrade with live slot rows fails safely rather than deleting them.
- Public API changes are additive. Generated backend OpenAPI and frontend types update together.

## 7. Error and recovery matrix

| Condition | Result |
|---|---|
| Slot disabled | No acquisition/selection/delivery work for that slot |
| Preparation time missed outside catch-up | Persist/emit safe skipped reconciliation; no backfill storm |
| Exact acquisition/governance not terminal | Retry readiness polling; no slot run or provider call |
| 0 eligible candidates | Succeeded slot run with selected=0 and explicit reason |
| 1--2 eligible candidates | Select only available candidates; persist unfilled count/reasons |
| Concurrent slot selection | Advisory lock + unique constraints converge to one run/items |
| Same event appears in later slot | Excluded and explained; no downstream work |
| One copy/image fails | Only that item becomes failed/review-required; siblings continue |
| Package ready before target | Enqueue with `not_before=target`; no early send |
| Package becomes ready within late window | Enqueue and send under remaining window/gap |
| Package/job expires before start | Typed terminal expiry; zero provider call |
| Provider result unknown | Preserve `delivery_unknown`; no automatic resend; siblings continue |
| Dispatcher concurrency/restart | Window lock and `next_allowed_at` preserve package gap |
| Legacy package reconciliation | Existing date-wide guard remains unchanged |

## 8. Security and observability

- No crawler safety control, source authentication, evidence requirement, provider host rule, image
  validation, MinIO privacy or WeCom credential boundary changes.
- Slot metadata is bounded enum/time/count data. Logs include IDs, slot, ordinal, versions, counts,
  target/actual timestamps and safe codes only—never copy text, image bytes, prompts, object keys,
  source passages, authenticated URLs or credentials.
- Readiness, selection, generation, window enqueue, start, child result, expiry and rollout evidence
  are separately observable.
- Doctor/evidence checks report feature mode, enabled slots, configured windows/gap, current slot
  counts and nonterminal/unknown delivery counts without sending content.

## 9. Rollout

Implementation and tests cover all slots while defaults remain off. Production activation is a
separate deployment task:

1. enable slot mode + morning only;
2. require two successful morning editions with no duplicates/misdelivery/unknown;
3. enable noon and require two successful combined days with cross-slot dedupe;
4. enable evening;
5. any gate failure stops expansion; rollback toggles the new slot mode off and does not downgrade
   data or resend old packages.
