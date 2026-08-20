# Three-Slot Independent Content Production

## Scenario: Produce and deliver independent morning, noon, and evening news items

### 1. Scope / Trigger

Use this contract when changing slot-aware acquisition, governed readiness, post-eligibility
ranking, independent copy/image/package lineage, content-edition APIs, the three-slot review board,
or slot-origin Enterprise WeChat delivery.

The legacy daily Top 1 path remains a separate compatibility contract. Slot mode is additive,
disabled by default, and never authorizes production activation, provider smoke calls, or public
social publishing.

### 2. Signatures

- Stable slot keys: `morning`, `noon`, and `evening`, displayed as `科教晨报`, `午间观察`, and
  `晚间精选`.
- Default delivery targets: 07:30, 12:30, and 18:30 in `Asia/Shanghai`; preparation defaults to
  90 minutes before target and delivery expiry to 60 minutes after target.
- Selection API:
  - `POST /api/v1/content-slot-runs` with one business date, slot, and scoring profile.
  - `GET /api/v1/content-slot-runs/{run_id}`.
  - `GET /api/v1/content-slot-runs/{run_id}/scores`.
  - `GET /api/v1/content-editions/{business_date}?profile=preview`.
- Durable tables: `content_slot_runs`, `content_slot_jobs`, `content_slot_scores`,
  `content_slot_selections`, shared `topic_rerank_records`, and `wecom_delivery_windows`, plus
  nullable typed slot-origin fields on acquisition, copy-generation, and delivery rows.
- Slot foundation revision: `20260814_0020`; current head `20260818_0022` adds shared daily/slot
  rerank snapshots, deterministic ranks, and XOR-bound typed audit.
- Runtime gates: `CONTENT_SLOT_MODE_ENABLED` plus one enable flag per slot. All default to false and
  require the existing `CONTENT_ENABLED` parent gate.
- Delivery gap: `WECOM_SLOT_PACKAGE_GAP_SECONDS`, default 60, enforced through durable window state.

### 3. Contracts

- Each enabled slot owns one idempotent scheduled acquisition identity and the exact terminal
  governance run derived from it. A terminal same-date run from another acquisition or slot cannot
  satisfy readiness.
- Slot selection reuses the stored current `.9` eligibility, Ministry priority, threshold, and veto result; literal `.7`/`.8` remain replayable.
  `slot-ranking-v1` may reorder only eligible candidates from governed/editorial/product
  projections; it cannot change eligibility, totals, threshold state, priority authentication, or
  vetoes.
- Ministry AI/science-education news remains globally first when eligible and is never held for a
  preferred column. Column affinities are soft preferences, not quotas.
- The optional shared reranker uses current `topic-rerank-v2-zhipu-json-contract` snapshots while
  literal `topic-rerank-v1` remains replayable with its legacy prompt/payload/parser. It receives at
  most the first eight candidates that remain eligible after slot affinity and same-day exclusion.
  It may reorder only within the existing Ministry/ordinary group, never changes affinity, total,
  threshold, veto, exclusion, or item limit, and leaves candidates outside the cap in deterministic
  order. Zero/one candidate skips; provider/schema/permutation failure completes with the exact
  base order and a typed audit.
- Candidate/config reads close before the provider call. Same-day state is loaded before that call
  and rechecked under the persistence lock. A late conflict ends that execution and relies on the
  bounded job retry; an executor never loops a second logical model request after one conflict.
- A slot selects 0--3 events. The business-date advisory lock and relational uniqueness enforce no
  repeated event across slots and at most nine slot selections per day. Insufficient quality
  persists explicit unfilled reasons and never lowers the threshold.
- Under `.7`, `.8`, or `.9`, seven-day repeat computation for a slot merges daily-origin and slot-origin lineages
  only when their material package has a formal Enterprise WeChat job in terminal `delivered`
  state. The SQL projection is distinct by event/version/business date before latest-date
  aggregation. Selected rows still own the category-based theme penalty, and same-day exclusion
  remains exact selection history. This merge is opt-in to the slot repository; literal `.6` and
  older replay remain selection-backed, with the legacy daily path daily-history-only.
- Every selected event has one discriminated copy origin, one full evidence-bound 180--240 Hanzi
  copy target, one independent image request/artifact, and one material package. Exactly one of the
  legacy daily origin and slot selection origin is present.
- Composite foreign keys bind acquisition/governance lineage, run/score/selection event and
  ordinal, copy origin, and delivery window/recipient/mode/target/expiry. Duplicated audit columns
  are identities and must not accept cross-wired combinations.
- A package may be prepared early but cannot start delivery before target. It may start only until
  expiry. The delivery-window row is locked before choosing the lowest currently ready ordinal;
  `next_allowed_at` advances before any provider call.
- A lower ordinal that is unready, failed, expired, or unknown does not block ready siblings.
  Text remains before image and successful child states remain durable. A lost lease after a slot
  package starts becomes `delivery_unknown` and is never automatically reclaimed or resent.
- The edition API and frontend project disabled, preparing, empty/unfilled, ready, failed, expired,
  delivered, and unknown states. Once immutable expiry passes, an unstarted item cannot remain
  `preparing`. Source links are normalized HTTPS URLs without userinfo or IP hosts.
- Doctor verifies the slot feature gates, safe counts, delivery gap, and all three target hour/minute
  pairs consistently across API, acquisition, content, and dispatcher services.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Slot or global content gate is disabled | No automatic slot acquisition, selection, generation, or delivery |
| Exact acquisition/governance lineage is incomplete | Remain preparing/retry readiness; create no slot decision or provider work |
| Candidate is vetoed, out of cohort, or below ordinary threshold | Ineligible; slot affinity and product fit cannot rescue it |
| Authenticated Ministry education candidate has no hard veto | Preserve the exact `.6`/`.7`/`.8`/`.9` priority/bypass behavior before slot ordering |
| Only 0--2 candidates qualify | Select only those candidates and persist unfilled reasons |
| Event was formally delivered from a prior daily/slot selection inside the `.7`/`.8`/`.9` seven-day window | Exclude it with a stored explanation |
| Prior `.7`/`.8`/`.9` slot is selected but absent, test-only, or not terminal-delivered | Keep it out of hard-repeat history; retain it for theme history |
| Event was selected by an earlier slot on the same business date | Exclude it immediately without waiting for delivery |
| Concurrent decisions approach the daily limit | Advisory lock plus database constraints converge at no more than nine selections |
| Copy/image/package fails for one selection | Only that selection fails; ready siblings continue independently |
| Package is ready before target | Keep it queued with `not_before=target`; zero provider calls |
| Delivery start is less than the configured gap after the prior package | Do not claim it; use persisted `next_allowed_at` |
| Job expires before start | Persist `delivery_window_expired` with zero attempts/provider calls |
| Running slot job loses its lease | Persist unresolved child/job as unknown; do not automatically reclaim or resend |
| Edition item has no delivery job after expiry | Project `expired`, not `preparing` |
| Composite lineage/window fields disagree | PostgreSQL rejects the row |
| Historical daily row is queried or replayed | Preserve the legacy API shape, daily history rules, and stored version semantics |
| Same-day excluded, hard-vetoed, below-threshold, or out-of-cap candidate is favored by model text | It never enters/changes the bounded rerank pool |
| Model crosses the Ministry priority barrier or returns an invalid permutation | Persist typed fallback and retain deterministic slot order |
| Persistence conflict occurs after a provider result | End the execution; no in-execution second model call |

### 5. Good / Base / Bad Cases

- Good: morning selects three eligible events, creates three independent copy/image/packages, and
  starts each ready package in ordinal order with at least the durable configured gap.
- Good: noon immediately excludes an event selected in morning and excludes an event formally
  delivered by a slot two days ago, while allowing a two-day-old selected-but-undelivered event and
  keeping literal `.6` replay unchanged.
- Base: only one candidate qualifies; the slot succeeds with one independent package and two
  explained unfilled positions.
- Base: no candidate qualifies; the slot succeeds empty and performs no model, image, or delivery
  provider call.
- Bad: add slot keywords to the `.9` total, treat selection alone as a v4 audience-visible repeat,
  query the latest unrelated governance run, combine
  siblings into one draft/image, use an in-process sleep for the package gap, or reclaim an unknown
  slot send after lease loss.

### 6. Tests Required

- Pure domain tests cover all three schedules, timezone-aware cross-midnight preparation, bounds,
  Ministry ordering, affinity reasons, stable ties, 0/1/2/3 selections, same-day exclusion, and the
  nine-item ceiling.
- Topic repository tests prove `.7`/`.8`/`.9` daily/slot formal-delivered history participates in seven-day
  repeat scoring, absent/test/non-delivered states do not, duplicates collapse, theme history and
  same-day exclusion remain selected-row based, and literal `.6` replay remains unchanged.
- Real PostgreSQL migration tests cover clean upgrade, metadata parity, composite foreign-key
  cross-wire rejection, origin XOR, daily uniqueness/max-nine behavior, and safe downgrade refusal
  when live slot-origin rows exist.
- Service/API tests cover exact lineage, idempotent replay, empty/partial/mixed states, safe source
  URLs, expired projection, sibling isolation, immutable rerank pins, safe summary/rank projection,
  single-call conflict behavior, and unchanged daily endpoints.
- Shared unit/adapter tests and `python -m evals.topic_rerank.runner --check` cover morning/noon/
  evening fixtures, same-day exclusion, priority barriers, strict JSON, and provider-free fallback.
- Delivery tests use a controlled clock and real PostgreSQL to prove no early claim, concurrent
  lowest-ready selection, persisted gap at 59/60 seconds, expiry without provider calls, stale
  running-to-unknown behavior, and legacy recovery compatibility.
- Frontend tests use generated OpenAPI types and cover all three stable columns, 0/1/3 items,
  partial failures, polling termination, source links, accessibility, and absence of publishing
  controls.
- Final gates are Ruff format/lint, strict mypy, the complete backend suite, generated-contract
  drift, frontend format/lint/type/test/build, Compose rendering, doctor, shell syntax, unique
  Alembic head, and `git diff --check`.

### 7. Wrong vs Correct

#### Wrong

```python
# Reinterprets eligibility and loses durable delivery coordination.
candidate.total += slot_keyword_bonus(candidate.raw_text)
await asyncio.sleep(60)
await send_next_package(candidate.package)
```

#### Correct

```python
decision = select_slot_topics(
    candidates=stored_governed_candidates,
    slot=content_slot,
    prior_selected_event_ids=prior_selected_event_ids,
)

# The dispatcher later locks the persisted delivery window, claims the lowest ready ordinal,
# advances next_allowed_at, commits, and only then calls the provider.
claimed = await delivery_service.claim_next_slot_job(worker_id=worker_id, now=clock())
```

Reuse immutable eligibility and evidence, keep every item independent, and make PostgreSQL the
authority for lineage, uniqueness, timing, and recovery.
