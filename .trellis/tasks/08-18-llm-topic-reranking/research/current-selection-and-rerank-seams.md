# Current selection and LLM rerank seams

## Confirmed selection behavior

- `backend/app/domain/topic_selection.py:744-816` owns pure daily scoring, stable ordering and Top-1 selection. It is the authority for threshold, hard veto, Ministry priority and no-topic behavior.
- `backend/app/domain/content_slots.py:300-390` composes slot affinity and same-day exclusion after the same base score, then selects 1--3 items.
- `backend/app/application/services/topic_selection.py` and `content_slots.py` own lease-aware executors. Both currently call pure deterministic selectors immediately before repository persistence.
- `backend/app/infrastructure/db/topic_selection.py` reads immutable governed projections at the run cutoff and persists score rows and the selected event atomically under the claim lease.
- `TopicCandidate.priority_title` / `priority_summary`, governed reason codes, product directions and bounded numeric features are sufficient for an MVP rerank input. Full article bodies and brand document text are unnecessary.

## Compatibility constraints

- `TopicScoringConfigModel` is immutable by `(profile, version)` and fingerprints the canonical snapshot. Existing `.8` cannot silently gain model semantics.
- Reranking is a separate selection policy, not a new numeric scoring formula. Keep `.8` scoring identity and pin a separate versioned rerank config on each daily/slot run.
- Existing run and score rows have no rerank columns. A migration is required for immutable config/result audit; old rows need a disabled/default-compatible representation.
- The current `ModelInvocationModel` belongs to governance-specific durable lineage and should not be reused for topic reranking. Add a dedicated bounded record instead of weakening its foreign-key contract.
- Daily and slot APIs currently expose score rank. Additive fields can expose base rank, final rank and a safe run-level rerank summary; regenerate production OpenAPI and client types.

## Provider reuse

- Reuse the infrastructure patterns in `backend/app/infrastructure/ai/zhipu.py`: validated HTTPS endpoint, SecretStr, bounded timeouts/concurrency/retries, JSON object response, Pydantic validation, safe request fingerprint and provider-neutral usage.
- Define a topic-rerank-specific port, schemas, prompt builder, deterministic fake and Zhipu adapter. Do not import factual-analysis schemas into the topic domain.
- `content_worker_main.py` already owns the long-lived provider client and both selection executors, so it is the composition root for a shared optional reranker.

## Recommended data shape

- Add immutable `rerank_config_snapshot` and `rerank_config_fingerprint` to both `topic_selection_runs` and `content_slot_runs`.
- Add one dedicated `topic_rerank_records` table with exactly one origin FK (daily run XOR slot run), one row per origin, policy/provider/model/request fingerprints, bounded JSON arrays/maps, outcome/failure, usage and latency.
- Persist the rerank record and final selection in the same lease-checked transaction. Do not hold a database session open during the model call.

## Recommended ordering contract

- Deterministic selector remains the first pass and produces the authoritative eligible set.
- Send at most the first eight eligible/non-excluded candidates.
- Preserve Ministry/ordinary group order. Model output must be a complete permutation within those barriers.
- Reordered candidates are followed by eligible candidates outside the cap, then ineligible candidates in their original deterministic order.
- Zero eligible candidates keep no-topic. One eligible candidate skips provider. Any model/validation failure returns the unchanged deterministic order with a typed fallback record.

## Testing consequence

- The deterministic selector must remain directly testable and unchanged when the feature is disabled.
- Unit tests must call the actual output validator rather than inject final results past it.
- Integration tests must prove the model call happens outside DB sessions and that decision + rerank audit either persist together or not at all.
- Offline eval must be labelled contract conformance; a deterministic fake cannot establish live editorial quality.
