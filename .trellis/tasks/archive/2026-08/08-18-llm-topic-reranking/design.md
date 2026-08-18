# LLM 选题重排：技术设计

## 1. Architecture

```text
governed candidates at immutable cutoff
              |
              v
existing deterministic score / veto / threshold / priority
              |
              +-- no eligible candidate --> existing no_topic
              +-- one sortable candidate --> skip provider
              |
              v
bounded eligible pool (<= 8, priority barriers retained)
              |
              v
TopicReranker port
   | fake (offline) | Zhipu JSON adapter
              |
              v
strict permutation + reason validation
   | valid                     | invalid/provider error
   v                           v
apply rerank              deterministic fallback
              \             /
               v           v
lease-checked atomic decision + rerank audit persistence
```

The deterministic selectors remain authoritative for all eligibility and risk decisions. A new application service receives their result and may only change rank/selected ordinal inside an already eligible priority group.

## 2. Domain and port contracts

Add provider-neutral types in a dedicated topic-rerank module:

- `TopicRerankConfig`: enabled, policy version, candidate limit, provider/model identity, temperature, max output tokens and fallback policy; canonical metadata + SHA-256 fingerprint.
- `TopicRerankCandidate`: event/version IDs, deterministic rank/group, bounded title/summary/time, rule score and allowlisted governed projections; optional slot/affinity fields.
- `TopicRerankRequest`: run identity, cutoff, daily/slot context and complete bounded candidate tuple.
- `TopicRerankItem`: event ID, ordinal, allowlisted reason codes and bounded Chinese explanation.
- `TopicRerankModelResult`: complete output, provider-neutral usage, latency and fingerprints.
- `TopicRerankOutcome`: `applied | skipped | fallback` plus safe failure code and base/final orders.
- `TopicReranker` protocol: one async `rerank(request)` method.

`apply_topic_rerank()` is a pure function. It validates exact ID set, uniqueness, full permutation, priority-group monotonicity and the input cap before replacing ranks. It never changes score totals or qualification fields.

## 3. Daily and slot integration

### Daily

1. Load the immutable scoring and rerank configs plus candidates.
2. Run existing `select_daily_topic()`.
3. Build the eligible pool from deterministic scores.
4. If configured and pool size >= 2, call the model after candidate-loading sessions have closed.
5. Apply or fall back; select the first final eligible candidate.
6. Persist score rows, selection and audit in the current lease transaction.

### Content slots

1. Run existing `select_slot_topics()` to compute base eligibility, slot affinity and same-day exclusion.
2. Build the pool from `eligible && !same_day_excluded` candidates.
3. Reorder only within hard priority groups, then recompute rank and selected ordinal up to the existing item limit.
4. Preserve affinity, exclusion and unfilled semantics; retry-on-conflict reloads same-day IDs and recomputes before any new rerank request.

To avoid paying for stale conflict attempts, the slot executor should acquire/recheck its same-day selection state before the provider call. If a persistence conflict still occurs after the call, normal bounded job retry applies; it must not loop model calls inside one execution.

## 4. Provider implementation

- Add a deterministic fake that orders from the request's allowlisted editorial signals without reading eval expected answers.
- Add a Zhipu adapter using the existing OpenAI-compatible chat endpoint conventions, temperature 0, `response_format=json_object`, max input/output limits, shared timeout/concurrency/retry policy and safe request fingerprint.
- Prompt input is serialized as delimited JSON data and explicitly untrusted; candidate text cannot issue instructions.
- The model returns no free-form top-level answer, score replacement or extra candidate. Pydantic uses `extra=forbid` and bounded collections/text.
- Provider exceptions are mapped to stable fallback codes. Raw body, API key and internal exception text never enter DB/API/logs.

## 5. Persistence and migration

Create one Alembic migration:

- add `rerank_config_snapshot JSONB NOT NULL` and 64-character `rerank_config_fingerprint` to daily and slot run tables, backfilled with canonical disabled config;
- create `topic_rerank_records` with daily-run/slot-run XOR foreign keys, one-record-per-origin partial unique indexes, outcome checks, safe bounded metadata, JSON array checks, usage counters and latency;
- preserve existing selected event/version foreign keys and score constraints.

Enqueue/reconcile compares rerank fingerprints along with the existing immutable run identity. Persist APIs accept a typed outcome and atomically write the audit row with final scores/selection. Old rows project `not_applied` without fabricated model data.

This does not provide provider exactly-once. A crash after provider response and before transaction commit may lead to one bounded retry; the stable request fingerprint makes that visible and replayable.

## 6. Configuration and compatibility

New settings, all bounded and default-off:

- `CONTENT_LLM_RERANK_ENABLED=false`
- `CONTENT_LLM_RERANK_POLICY_VERSION=topic-rerank-v1`
- `CONTENT_LLM_RERANK_CANDIDATE_LIMIT=8`
- `CONTENT_LLM_RERANK_MAX_OUTPUT_TOKENS` with a conservative default

Provider/model identity comes from the validated `AI_PROVIDER_MODE` and `AI_CHAT_MODEL`. Enabling requires `fake` or `zhipu`; disabled preserves current worker construction and performs no model call.

The numeric scoring identity remains `.8` because its formula is unchanged. The separate rerank policy snapshot owns the new selection behavior. Historical scoring configurations and disabled rerank runs are not reinterpreted.

## 7. API and observability

Additive daily/slot response fields:

- run-level `rerank`: outcome, policy, provider/model, candidate count, fallback code, usage and latency;
- score-level `deterministic_rank`, `final_rank`, reason codes and explanation when applied.

Logs contain only run/job IDs, policy/model identifiers, counts, safe outcome/failure code, latency and token counts. Prompts, summaries, provider response bodies and secrets are excluded.

## 8. Evaluation and quality

- Unit: config fingerprint, pool construction, priority barriers, permutation validator, final order and fallback.
- Adapter: MockTransport success/error/invalid JSON/limits and secret-safe errors.
- Service: no call at 0/1 candidate, one logical call, provider error fallback, lease loss.
- PostgreSQL: config pinning, atomic audit + selection, historical rows, daily/slot results and conflict behavior.
- Offline eval: contract cases across daily/slots, hard gates and fallback; canonical report excludes timestamps/latency.
- Contract: migrations, OpenAPI/client drift and Compose defaults.

## 9. Rollout and rollback

- Code ships with the flag off; migration is additive.
- Local implementation and verification do not activate the flag or call a real provider.
- A later production activation must be a separate authorized change with config backup, effective-value verification and observed provider/business counters.
- Runtime rollback is setting the flag false and recreating the content worker; stored audit rows remain historical evidence. Schema downgrade is not required for application rollback.
