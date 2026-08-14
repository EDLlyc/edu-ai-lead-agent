# Daily Topic Selection Contract

## Scenario: Explainable daily Top 1 or `no_topic`

### 1. Scope / Trigger

This contract applies after factual governance has produced immutable event versions. The topic
selection stage consumes only stored event, evidence, category, entity, and source projections and
produces at most one locked topic for a business date and scoring profile. It does not browse,
re-summarize, retrieve brand knowledge, call a model for the numeric score, generate copy/images,
or publish content.

The current implemented preview is `scoring-v1-preview.6-tiered-science-tech-priority`. Its
numeric weights and threshold remain subject to later labeled calibration. Historical `.4` and
`scoring-v1-preview.5-science-education-product-fit` snapshots remain deserializable and replayable
with their original feature keys, source-priority behavior, and hard editorial boundary.

### 2. Signatures

- Manual enqueue: `POST /api/v1/topic-selection-runs` with optional
  `{"business_date": "YYYY-MM-DD"}` -> HTTP 202, durable run body, and `Location` header.
- Run query: `GET /api/v1/topic-selection-runs/{run_id}`.
- Score query: `GET /api/v1/topic-selection-runs/{run_id}/scores`.
- Daily decision: `GET /api/v1/daily-topics/{business_date}?profile=preview`.
- Scheduler/worker: `python -m app.content_scheduler_main` and
  `python -m app.content_worker_main`; root wrappers are `make content-scheduler`,
  `make content-worker`, and `make content-stack-up`.
- Migrations: `20260730_0005` creates the topic-selection schema and `20260730_0006` tightens the
  business key and event/version integrity constraints.
- Durable tables: `topic_scoring_configs`, `topic_selection_runs`, `topic_selection_jobs`,
  `topic_scores`, and `daily_topic_selections`.

### 3. Contracts

- A current run owns `(business_date, timezone, scoring_profile)` while historical revisions retain
  the same date/profile. Re-enqueueing the same immutable config returns the current run; a
  provisional `no_topic`/`all_vetoed` run may be superseded once by a later governed cutoff.
- Both scheduled and manual enqueue require a terminal acquisition run and terminal governance run
  with no queued, running, or retry-scheduled governance jobs. An unready request returns a typed
  HTTP 409 and creates no topic-selection run.
- A scoring config is immutable by `(profile, version)` and stores its canonical JSON snapshot and
  SHA-256 fingerprint. Historical responses read the run snapshot, not current process settings.
- `.6` uses positive weights of 0.30 tiered editorial priority, 0.25 product-matrix fit, 0.15 source
  trust, 0.10 source diversity, 0.10 freshness, and 0.10 communication potential. Education content
  has the strongest editorial values; qualified frontier advances have lower positive values and
  remain normal threshold-bound candidates. Theme repetition, controversy, and marketing risk
  remain explicit penalties; the threshold remains 0.62.
- The `.6` immutable snapshot records `science-tech-editorial-v2`,
  `product-matrix-fit-v2-science-pathways`, `topic-veto-v3-governed-content`, and
  `ministry-education-priority-v3`. Its explanation persists cohort, education/frontier scores,
  reason codes, product directions, threshold state, priority state, and threshold-bypass state.
- The `.5` immutable config snapshot records `science-ai-education-v1` and
  `product-matrix-fit-v1` and uses `topic-veto-v2-science-ai-education`. Its explanation stores relevance reasons, product direction IDs, raw
  feature values/components, and `source_priority_disabled_for_config`. Ministry occurrence
  metadata has no absolute priority under `.5`.
- `.4` uses its stored legacy `ai_relevance`/`parent_relevance` feature map and
  `topic-veto-v1`/`science-policy-priority-v2` semantics. Config deserialization branches on the stored feature
  keys and never reinterprets a historical value as a new editorial signal.
- `.6` retains every genuine hard veto but does not add `outside_science_ai_education_scope`.
  Acquisition and the v2 cohort own scope for new runs. A controlled Ministry occurrence in the
  v2 education cohort is eligible when no hard veto exists even below the ordinary threshold;
  persisted state then has `passes_threshold=false`, `eligible=true`, `priority_applied=true`, and
  `threshold_bypass_applied=true`. The bypass is valid only for the exact `.6` config with
  `science-tech-editorial-v2` and `ministry-education-priority-v3`; text mentioning the Ministry
  cannot authenticate this policy.
- Hard vetoes are independent of the numeric total: unresolved governance, ineligible evidence,
  Tier-C-only evidence, unverified information, unsuitable negative incidents, privacy/legal/safety
  uncertainty, prohibited marketing claims, a selection inside the seven-day business-date
  window, and an event older than the configured 10-day freshness window. `.5` additionally owns
  `outside_science_ai_education_scope`; `.6` instead requires a qualified v2 cohort before numeric
  score or Ministry priority can create eligibility. Product fit, source tier, or any high numeric
  total cannot rescue a veto or an out-of-scope `.6` candidate.
- Stable ordering is applied Ministry priority, ordinary eligible, below-threshold without veto,
  then hard-vetoed; within each group use total, source trust, event time, then UUID. Every
  considered event receives a persisted rank even when vetoed or below threshold.
- A selected event ID and version ID must form a valid pair in `event_cluster_versions`; database
  composite foreign keys enforce this for runs, scores, and daily selections.
- A day with neither an ordinary eligible score at or above threshold nor an authenticated `.6`
  Ministry threshold bypass persists `no_topic` with one of `no_candidates`, `all_vetoed`, or
  `below_threshold`. Downstream brand/model/image work must not start for that decision.
- Jobs use PostgreSQL claims, lease tokens, heartbeats, bounded attempts, and terminal states.
  Replays reuse the immutable run/config/cutoff and converge on the existing daily lock.
- Runtime is disabled by default. `CONTENT_ENABLED=true` is required before either the content
  scheduler or worker may be enabled. The schedule defaults to 07:30 `Asia/Shanghai`.

Relevant environment keys are `CONTENT_ENABLED`, `CONTENT_SCHEDULER_ENABLED`,
`CONTENT_WORKER_ENABLED`, `CONTENT_SCHEDULE_HOUR`, `CONTENT_SCHEDULE_MINUTE`,
`CONTENT_CATCHUP_HOURS`, `CONTENT_POLL_SECONDS`, `CONTENT_WORKER_CONCURRENCY`,
`CONTENT_LEASE_SECONDS`, `CONTENT_HEARTBEAT_SECONDS`, `CONTENT_MAX_ATTEMPTS`,
`CONTENT_SCORING_VERSION`, `CONTENT_SCORING_PROFILE`, and
`CONTENT_SELECTION_PRIORITY_RULE_VERSION`.

## Parallel content-slot selection

“Daily Top 1” in this document is the legacy compatibility path. The optional parallel aggregate
uses the exhaustive `ContentSlot` keys `morning`, `noon`, and `evening`; all slot-mode and per-slot
feature switches default to false. Each enabled slot owns an exact scheduled acquisition and
terminal governance lineage, immutable governed cutoff, 1--3 item limit, and independently computed
preparation/target/expiry instants in the configured IANA timezone.

`slot-ranking-v1` composes after the current `.6` selector. It may add only a bounded affinity from
stored governed/editorial/product projections when ordering already eligible candidates. It cannot
change the base total, threshold, eligibility, Ministry priority, seven-day repeat decision, or any
veto. Persist every considered score, affinity reason, same-day exclusion, stable ordering key and
explicit unfilled reason. Hold the business-date advisory lock while persisting and rely on the
relational daily-event unique constraint for cross-slot convergence.

The seven-day projection for a slot run merges prior `daily_topic_selections` and prior
`content_slot_selections` for the same timezone/profile before computing
`days_since_last_selection`; the most recent business date wins. This merge is opt-in at the slot
repository boundary. The legacy `load_topic_candidates` path remains daily-history-only so `.4`,
`.5`, and `.6` daily replays are not reinterpreted by rows created by the parallel slot aggregate.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Content stage disabled | Manual enqueue returns a typed 409 conflict |
| Same date/profile and same config | Return the existing durable run; do not create another job |
| Same date/profile and different config | Typed 409 conflict before scoring or locking |
| No governed events at the run cutoff | Persist `no_topic/no_candidates` |
| Every candidate has a hard veto | Persist `no_topic/all_vetoed`; total cannot rescue it |
| `.5` product fit is 1.0 but science/AI-education scope is false | Add `outside_science_ai_education_scope`; remain vetoed |
| `.6` product fit and other components exceed threshold but v2 cohort is out of scope | Remain ineligible; product fit cannot create qualification |
| `.6` controlled Ministry education content is below threshold with no veto | Eligible in priority group; persist threshold bypass |
| `.6` Ministry content has any genuine hard veto | Ineligible; priority cannot apply |
| Old or unknown feature config names Ministry v3 | Do not bypass; exact `.6`/v2/v3 identity is required |
| `.6` ordinary frontier content is below threshold | Ineligible; no source or product rescue |
| Eligible Ministry event and eligible non-Ministry event under `.5` | Rank by score/tie-break only; no source override |
| Historical `.4` config is loaded | Preserve old feature map and Ministry policy-priority semantics |
| Some candidates have no veto but all totals are below threshold | Persist `no_topic/below_threshold` |
| Selected event/version do not belong together | Reject through application validation or database FK |
| Lease is lost before persistence/completion | Do not overwrite the decision; let durable retry converge |
| Expired lease reaches `CONTENT_MAX_ATTEMPTS` | Mark job/run failed unless a decision was already persisted |
| Unknown or Tier C source tier | Trust contribution is zero; it cannot become eligible evidence |

### 5. Good / Base / Bad Cases

- Good: a `.6` run uses the exact 30/25/15/10/10/10 weights, ranks education above comparable
  frontier content, narrowly bypasses the threshold for authenticated Ministry education content,
  and retains every feature, reason, direction, penalty, veto, and tie-break input.
- Base: an empty or entirely vetoed governed pool creates an inspectable `no_topic` daily row and
  performs no downstream provider call.
- Bad: ask an LLM for an unexplained final score, read the live event projection instead of the
  run cutoff/version, let a high score override a veto, create a second date/profile run for a new
  config, or delete old scores when a config changes.

### 6. Tests Required

- [`test_topic_selection.py`](../../../backend/tests/unit/test_topic_selection.py): exact `.6`
  weights and rule identities, Ministry below-threshold selection, every hard-veto non-bypass,
  frontier ordinary-threshold behavior, education/frontier rank, product-fit non-rescue, exact
  `.4`/`.5` replay, stale-event cutoff, seven-day boundary, tie-break, and all `no_topic` branches.
- [`test_topic_selection_delivery.py`](../../../backend/tests/unit/test_topic_selection_delivery.py):
  scheduler/worker behavior, heartbeat/lease loss, bounded attempts, projection boundaries, and
  safe response mapping.
- [`test_topic_selection_repositories.py`](../../../backend/tests/integration/test_topic_selection_repositories.py):
  PostgreSQL enqueue idempotency/conflict, claims, immutable cutoff reads, authenticated Ministry
  SourceVersion-policy propagation, score/explanation persistence, event/version constraints, and
  daily lock behavior.
- [`test_topic_selection_api.py`](../../../backend/tests/integration/test_topic_selection_api.py):
  202 enqueue, run/scores/daily response shapes, Location URL, and disabled/not-found/conflict paths.
- [`test_governance_migrations.py`](../../../backend/tests/integration/test_governance_migrations.py):
  unique head `20260730_0006`, required tables, constraints, and preserved governance schema.
- Regenerate `backend/openapi.json` and
  `frontend/src/lib/api/generated/schema.d.ts`; `make api-contract-check` must report no drift.

### 7. Wrong vs Correct

#### Wrong

```python
# A model's opaque preference is neither reproducible nor auditable.
winner = await llm.choose_best(events)
```

#### Correct

```python
decision = select_daily_topic(
    candidates,
    as_of=claimed.cutoff_at,
    config=stored_config,
)
await repository.persist_decision(claimed=claimed, config=stored_config, decision=decision)
```

Use stored governed projections, a versioned deterministic configuration, independent vetoes,
stable ranking, and one durable daily lock.
