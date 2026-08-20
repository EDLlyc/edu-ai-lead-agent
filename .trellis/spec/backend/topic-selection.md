# Daily Topic Selection Contract

## Scenario: Explainable daily Top 1 or `no_topic`

### 1. Scope / Trigger

This contract applies after factual governance has produced immutable event versions. The topic
selection stage consumes only stored event, evidence, category, entity, and source projections and
produces at most one locked topic for a business date and scoring profile. It does not browse,
re-summarize, retrieve brand knowledge, call a model for the numeric score, generate copy/images,
or publish content.

The current implemented preview is `scoring-v1-preview.9-broad-hard-tech-pool`, with an ordinary
numeric threshold of 0.59 and an audited governed-hard-tech pool path. Its weights and threshold
remain subject to later labeled calibration. Historical `.4`,
`scoring-v1-preview.5-science-education-product-fit`, and literal
`scoring-v1-preview.6-tiered-science-tech-priority` and
`scoring-v1-preview.7-delivered-repeat-history` plus `.8-threshold-059` snapshots remain
deserializable and replayable
with their original feature keys, source-priority behavior, and repeat-history provenance.

### 2. Signatures

- Manual enqueue: `POST /api/v1/topic-selection-runs` with optional
  `{"business_date": "YYYY-MM-DD"}` -> HTTP 202, durable run body, and `Location` header.
- Run query: `GET /api/v1/topic-selection-runs/{run_id}`.
- Score query: `GET /api/v1/topic-selection-runs/{run_id}/scores`.
- Daily decision: `GET /api/v1/daily-topics/{business_date}?profile=preview`.
- Scheduler/worker: `python -m app.content_scheduler_main` and
  `python -m app.content_worker_main`; root wrappers are `make content-scheduler`,
  `make content-worker`, and `make content-stack-up`.
- Migrations: `20260730_0005` creates the topic-selection schema, `20260730_0006` tightens the
  business key and event/version integrity constraints, and `20260818_0022` adds immutable
  rerank configuration, deterministic ranks, and typed rerank audit.
- Durable tables: `topic_scoring_configs`, `topic_selection_runs`, `topic_selection_jobs`,
  `topic_scores`, `daily_topic_selections`, and the shared `topic_rerank_records` audit table.

### 3. Contracts

- A current run owns `(business_date, timezone, scoring_profile)` while historical revisions retain
  the same date/profile. Re-enqueueing the same immutable config returns the current run; a
  provisional `no_topic`/`all_vetoed` run may be superseded once by a later governed cutoff.
- Both scheduled and manual enqueue require a terminal acquisition run and terminal governance run
  with no queued, running, or retry-scheduled governance jobs. An unready request returns a typed
  HTTP 409 and creates no topic-selection run.
- A scoring config is immutable by `(profile, version)` and stores its canonical JSON snapshot and
  SHA-256 fingerprint. Historical responses read the run snapshot, not current process settings.
- `.6`, `.7`, `.8`, and `.9` use positive weights of 0.30 tiered editorial priority, 0.25 product-matrix fit, 0.15 source
  trust, 0.10 source diversity, 0.10 freshness, and 0.10 communication potential. Education content
  has the strongest editorial values; qualified frontier advances have lower positive values and
  remain deterministic ranking inputs. Theme repetition, controversy, and marketing risk remain
  explicit penalties. Literal `.6` and `.7` retain threshold 0.62; `.8` and current `.9` use 0.59.
- The `.7` and `.8` immutable snapshots record `science-tech-editorial-v2`,
  `product-matrix-fit-v2-science-pathways`, `topic-veto-v4-delivered-content`, and
  `ministry-education-priority-v3`. Literal `.6` retains `topic-veto-v3-governed-content`; `.7`
  preserves threshold 0.62, while `.8` changes only that field to 0.59. Every other weight,
  editorial/product/priority identity, penalty, and tie-break remains the same. Explanations persist cohort, education/frontier scores, reason codes, product directions,
  threshold state, priority state, and threshold-bypass state.
- The current `.9` snapshot records `science-tech-editorial-v3-broad`,
  `hard-tech-pool-v1-governed-tier-ab`, and the same weights, 0.59 threshold, delivered-history
  veto, product-fit, Ministry-priority, and rerank boundaries. It persists typed completed,
  planned/in-progress, failure/setback, capital/market, event/conference, product/service-release,
  or general-hard-tech signals. A governed Tier-A/B frontier candidate with no hard veto may enter
  the LLM pool below 0.59 with `passes_threshold=false`, `eligible=true`, and
  `threshold_bypass_reason=governed_broad_hard_tech_pool`; this never changes the numeric total.
- The `.5` immutable config snapshot records `science-ai-education-v1` and
  `product-matrix-fit-v1` and uses `topic-veto-v2-science-ai-education`. Its explanation stores relevance reasons, product direction IDs, raw
  feature values/components, and `source_priority_disabled_for_config`. Ministry occurrence
  metadata has no absolute priority under `.5`.
- `.4` uses its stored legacy `ai_relevance`/`parent_relevance` feature map and
  `topic-veto-v1`/`science-policy-priority-v2` semantics. Config deserialization branches on the stored feature
  keys and never reinterprets a historical value as a new editorial signal.
- `.6`, `.7`, `.8`, and `.9` retain every genuine hard veto but do not add `outside_science_ai_education_scope`.
  Acquisition and the run-pinned editorial cohort own scope. A controlled Ministry occurrence in
  the pinned education cohort is eligible when no hard veto exists even below the ordinary threshold;
  persisted state then has `passes_threshold=false`, `eligible=true`, `priority_applied=true`, and
  `threshold_bypass_applied=true`. The bypass is valid only for the authenticated version/veto
  pair (`.6`/`topic-veto-v3-governed-content`, or `.7`/`.8`/`.9` with
  `topic-veto-v4-delivered-content`), its pinned v2/v3 editorial identity, and
  `ministry-education-priority-v3`; text mentioning the Ministry cannot authenticate this policy.
- Hard vetoes are independent of the numeric total: unresolved governance, ineligible evidence,
  Tier-C-only evidence, unverified information, unsuitable negative incidents, privacy/legal/safety
  uncertainty, prohibited marketing claims, an audience-visible repeat inside the seven-day
  business-date window, and an event older than the configured 10-day freshness window. For v4,
  only `wecom_delivery_jobs(mode='formal', status='delivered')` reached through the typed
  selection -> copy run -> material package lineage supplies that prior date; absent, test, or any
  other job status does not. Literal `.6` and older veto identities remain selection-backed. `.5` additionally owns
  `outside_science_ai_education_scope`; `.6`/`.7`/`.8` require a qualified v2 cohort and `.9`
  requires a qualified v3 cohort before numeric score or Ministry priority can create eligibility.
  Product fit, source tier, or any high numeric
  total cannot rescue a veto or an out-of-scope `.6`/`.7`/`.8`/`.9` candidate. The `.9`
  hard-tech pool requires a v3 frontier cohort plus eligible Tier-A/B evidence and zero vetoes.
- Stable ordering is applied Ministry priority, ordinary eligible, below-threshold without veto,
  then hard-vetoed; within each group use total, source trust, event time, then UUID. Every
  considered event receives a persisted rank even when vetoed or below threshold.
- The topic-rerank stage runs only after that deterministic ordering. Current snapshots use
  `topic-rerank-v3-layered-auto-finalize`; literal `topic-rerank-v1` and
  `topic-rerank-v2-zhipu-json-contract` snapshots remain supported with their original prompt,
  request payload, parser, and replay semantics. The immutable policy selects prompt, wire payload,
  parser, and finalization behavior together; unknown identities and a request/config policy
  mismatch fail before transport.
  The independent enqueue-time snapshot/fingerprint pins enabled state, provider/model, candidate
  cap (at most eight), temperature zero, output cap, and deterministic fallback policy without
  changing the scoring fingerprint. It receives only eligible governed projections; zero/one
  candidate skips the provider, candidates outside the cap retain their deterministic order, and
  a model may reorder only within the same Ministry/ordinary priority group.
- Rerank output is a strict full permutation with 1--3 allowlisted reason codes and a bounded
  explanation per candidate. Unknown/duplicate/missing IDs, group crossings, provider failures,
  parsing failures, or input limits produce a typed fallback to the exact deterministic order.
  Candidate projections are serialized as JSON data, with literal angle brackets escaped before
  delimiter insertion so untrusted titles or summaries cannot terminate the data-only block.
  Current Zhipu requests use JSON-object mode, disabled thinking, and disabled sampling. Their
  exact prompt names the object/item shape, all seven reason codes, complete permutation,
  consecutive integer ordinal, priority barrier, and no-Markdown/no-prose rules. Content parsing
  accepts only the shared bounded one-object envelopes before unchanged strict schema and semantic
  validation; literal v1 continues to require an exact JSON object. V3 additionally names news
  value and breakthrough significance as ranking dimensions without changing literal v2 text.
  Under v3, an automatic deterministic finalizer revalidates the exact run request fingerprint,
  complete bounded pool, event/version pairs, hard vetoes, eligibility, priority groups, same-day
  exclusions, and configured item/candidate limits before applying the model order. Any missing,
  cross-run, stale-version, unavailable-candidate, barrier, or cap mismatch becomes a typed
  deterministic fallback; it never reaches downstream selection as an unvalidated model result.
  Final scores preserve both `deterministic_rank` and final `rank`; one XOR-bound audit row stores
  safe orders, reasons, fingerprints, usage, latency, outcome, and failure code without raw prompts
  or provider bodies. Completion, JSON-envelope, and schema failures have bounded internal
  diagnostics, while durable/public failure remains `invalid_provider_output`; post-response
  fallback retains safe prompt fingerprint, usage, and latency. Historical migrated runs have the
  canonical disabled v1 snapshot and may legitimately project `not_applied` when no audit row
  exists.
- A selected event ID and version ID must form a valid pair in `event_cluster_versions`; database
  composite foreign keys enforce this for runs, scores, and daily selections.
- A day with neither an eligible score at or above threshold, an authenticated `.6`/`.7`/`.8`/`.9`
  Ministry threshold bypass, nor a `.9` governed-hard-tech pool candidate persists `no_topic` with one of `no_candidates`, `all_vetoed`, or
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
`CONTENT_SELECTION_PRIORITY_RULE_VERSION`. Rerank keys are
`CONTENT_LLM_RERANK_ENABLED`, `CONTENT_LLM_RERANK_POLICY_VERSION`,
`CONTENT_LLM_RERANK_CANDIDATE_LIMIT`, and `CONTENT_LLM_RERANK_MAX_OUTPUT_TOKENS`; the feature is
enabled by default only inside an enabled content-selection pipeline. The global
`CONTENT_ENABLED=false` default keeps local development provider-free; an enabled content pipeline
may explicitly disable reranking, otherwise it requires the already validated `fake` or `zhipu`
AI provider mode.

## Parallel content-slot selection

“Daily Top 1” in this document is the legacy compatibility path. The optional parallel aggregate
uses the exhaustive `ContentSlot` keys `morning`, `noon`, and `evening`; all slot-mode and per-slot
feature switches default to false. Each enabled slot owns an exact scheduled acquisition and
terminal governance lineage, immutable governed cutoff, 1--3 item limit, and independently computed
preparation/target/expiry instants in the configured IANA timezone.

`slot-ranking-v1` composes after the current `.9` selector. It may add only a bounded affinity from
stored governed/editorial/product projections when ordering already eligible candidates. It cannot
change the base total, threshold, eligibility, Ministry priority, seven-day repeat decision, or any
veto. Persist every considered score, affinity reason, same-day exclusion, stable ordering key and
explicit unfilled reason. Hold the business-date advisory lock while persisting and rely on the
relational daily-event unique constraint for cross-slot convergence.

The seven-day projection for a `.7`, `.8`, or `.9` slot run merges prior daily-origin and slot-origin formal
delivered lineages for the same timezone/profile before computing `days_since_last_selection`; SQL
projects distinct event/version/date rows before the most recent business date is aggregated.
Selected daily/slot rows still supply `prior_version_ids` for `theme_repetition`, and same-day
cross-slot exclusion still reads exact selected event IDs. This merge is opt-in at the slot
repository boundary. The daily path remains daily-origin-only, and literal `.6` or older snapshots
remain selection-backed.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Content stage disabled | Manual enqueue returns a typed 409 conflict |
| Same date/profile and same config | Return the existing durable run; do not create another job |
| Same date/profile and different config | Typed 409 conflict before scoring or locking |
| No governed events at the run cutoff | Persist `no_topic/no_candidates` |
| Every candidate has a hard veto | Persist `no_topic/all_vetoed`; total cannot rescue it |
| `.5` product fit is 1.0 but science/AI-education scope is false | Add `outside_science_ai_education_scope`; remain vetoed |
| `.6`/`.7`/`.8`/`.9` product fit and other components exceed threshold but the pinned cohort is out of scope | Remain ineligible; product fit cannot create qualification |
| `.6`/`.7`/`.8`/`.9` controlled Ministry education content is below threshold with no veto | Eligible in priority group; persist threshold bypass |
| `.6`/`.7`/`.8`/`.9` Ministry content has any genuine hard veto | Ineligible; priority cannot apply |
| Old, unknown, or mismatched scoring/veto identity names Ministry v3 | Do not bypass; an exact authenticated identity pair is required |
| `.6`/`.7`/`.8` ordinary frontier content is below threshold | Ineligible; historical rules gain no new bypass |
| `.9` governed Tier-A/B frontier content is below threshold with no veto | Eligible for the bounded LLM pool; persist policy and bypass reason |
| `.9` hard-tech content is unverified, stale, repeated, unsafe, lacks eligible evidence, or is Tier-C-only | Ineligible; the pool policy cannot remove a veto |
| `.7`/`.8`/`.9` prior selection has no formal delivered job | Keep `days_since_last_selection=null`; do not add repeat veto |
| `.7`/`.8`/`.9` prior job is test, queued, running, partial, failed, cancelled, expired, or unknown | Ignore it for hard-repeat history |
| `.7`/`.8`/`.9` formal delivered lineage has duplicate packages/jobs | De-duplicate event/version/date before latest-date aggregation |
| Eligible Ministry event and eligible non-Ministry event under `.5` | Rank by score/tie-break only; no source override |
| Historical `.4` config is loaded | Preserve old feature map and Ministry policy-priority semantics |
| Some candidates have no veto but all totals are below threshold | Persist `no_topic/below_threshold` |
| Selected event/version do not belong together | Reject through application validation or database FK |
| Lease is lost before persistence/completion | Do not overwrite the decision; let durable retry converge |
| Expired lease reaches `CONTENT_MAX_ATTEMPTS` | Mark job/run failed unless a decision was already persisted |
| Unknown or Tier C source tier | Trust contribution is zero; it cannot become eligible evidence |
| Rerank is disabled or has fewer than two eligible candidates | Skip provider and persist the deterministic order/audit |
| Rerank output has an unknown, duplicate, missing, or out-of-group candidate | Persist typed fallback and use the exact deterministic order |
| Provider times out, rejects, or returns malformed JSON | Complete selection through deterministic fallback; expose no raw body |
| Candidate is vetoed, below threshold without authenticated bypass, or outside the top-eight pool | Never enter or be rescued by model ordering |

### 5. Good / Base / Bad Cases

- Good: a `.9` run uses threshold 0.59 and the exact 30/25/15/10/10/10 weights, ranks completed
  progress above equivalent generic hard-tech content, narrowly bypasses the threshold for
  authenticated Ministry education or governed Tier-A/B frontier content, and retains every
  feature, signal, reason, direction, penalty, veto, and tie-break input.
- Base: an empty or entirely vetoed governed pool creates an inspectable `no_topic` daily row and
  performs no downstream provider call.
- Bad: ask an LLM for an unexplained final score, read the live event projection instead of the
  run cutoff/version, let a high score override a veto, create a second date/profile run for a new
  config, or delete old scores when a config changes.

### 6. Tests Required

- [`test_topic_selection.py`](../../../backend/tests/unit/test_topic_selection.py): exact `.6`/`.7`/`.8`
  metadata parity except scoring/veto identity, Ministry below-threshold selection, every hard-veto non-bypass,
  `.9` governed-hard-tech below-threshold admission and veto non-bypass, education/frontier rank,
  product-fit non-rescue, exact
  `.4`/`.5` replay, stale-event cutoff, seven-day boundary, tie-break, and all `no_topic` branches.
- [`test_topic_rerank.py`](../../../backend/tests/unit/test_topic_rerank.py) and
  [`test_topic_rerank_provider.py`](../../../backend/tests/contract/test_topic_rerank_provider.py):
  cap/skip/permutation/group barriers, daily and slot application, fallback parity, prompt
  isolation, strict provider JSON, safe error mapping, usage, and latency.
- [`test_topic_selection_delivery.py`](../../../backend/tests/unit/test_topic_selection_delivery.py):
  scheduler/worker behavior, heartbeat/lease loss, bounded attempts, projection boundaries, and
  safe response mapping.
- [`test_topic_selection_repositories.py`](../../../backend/tests/integration/test_topic_selection_repositories.py):
  PostgreSQL enqueue idempotency/conflict, claims, immutable cutoff reads, authenticated Ministry
  SourceVersion-policy propagation, score/explanation persistence, event/version constraints, and
  daily lock behavior.
- [`test_wecom_slot_delivery_concurrency.py`](../../../backend/tests/integration/test_wecom_slot_delivery_concurrency.py):
  real-PostgreSQL daily/slot delivery lineage, absent/test/non-delivered exclusion, duplicate-row
  de-duplication, older formal success surviving newer failed/test jobs, selected-row theme history,
  literal `.6` replay, and projected day-6/day-7 boundary behavior.
- [`test_topic_selection_api.py`](../../../backend/tests/integration/test_topic_selection_api.py):
  202 enqueue, run/scores/daily response shapes, Location URL, and disabled/not-found/conflict paths.
- [`test_governance_migrations.py`](../../../backend/tests/integration/test_governance_migrations.py):
  unique head `20260818_0022`, required tables, constraints, and preserved governance schema.
- `python -m evals.topic_rerank.runner --check` verifies provider-free synthetic fixture contract
  conformance only; it is not a claim about live editorial quality.
- Regenerate `backend/openapi.json` and
  `frontend/src/lib/api/generated/schema.d.ts`; `make api-contract-check` must report no drift.

### 7. Wrong vs Correct

#### Wrong

```python
# A model's opaque preference is neither reproducible nor auditable.
winner = await llm.choose_best(events)

# This silently mutates literal .6 replay and couples the theme penalty to delivery.
repeat_rows = selected_rows
prior_version_ids = [row.event_version_id for row in repeat_rows]
```

#### Correct

```python
decision = select_daily_topic(
    candidates,
    as_of=claimed.cutoff_at,
    config=stored_config,
)
await repository.persist_decision(claimed=claimed, config=stored_config, decision=decision)

repeat_rows = (
    delivered_formal_rows
    if stored_config.effective_veto_rule_version == "topic-veto-v4-delivered-content"
    else selected_rows
)
prior_version_ids = [row.event_version_id for row in selected_rows]
```

Use stored governed projections, a versioned deterministic configuration, independent vetoes,
stable ranking, and one durable daily lock.
