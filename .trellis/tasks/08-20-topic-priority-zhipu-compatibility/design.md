# Design — substantive science-education priority and minimal rerank wire

## Decision

Introduce two new immutable identities and leave all historical identities untouched:

```text
governed candidate
  -> existing hard veto + broad hard-tech score
  -> new substantive Ministry science-education priority rule
  -> bounded candidate pool
  -> new Zhipu minimal ID-order wire
  -> local deterministic item projection
  -> existing automatic finalizer and atomic persistence
```

The correction is not a global Ministry boost and not a permissive provider parser. It narrows both
authority boundaries: the Ministry override must prove substantive science-education content, and
the model may return only an ordering of IDs already present in the immutable request.

## 1. Immutable priority policy

Keep `ministry-education-priority-v3` byte-for-byte for `.9` replay. Add a v4 rule and a new current
scoring identity (for example `scoring-v1-preview.10-substantive-science-education-priority`). The
new scoring config retains `.9` threshold, broad-recall, delivered-history and veto semantics, but
authenticates v4 rather than v3.

V4 composes three facts:

1. the source/run carries the authenticated `moe-science-top1-v1` policy;
2. the governed candidate is in the science/technology education cohort and has no hard veto;
3. title/summary/content signals prove a substantive policy, teaching/curriculum, talent-development
   or frontier-education action, rather than only a meeting/event wrapper.

Reuse the narrow `science_policy_priority` classifier where it is authoritative and extend the new
v4 rule with explicit, typed substantive practice signals. Do not broaden old helpers in a way that
changes historical behavior. Stable rejection reasons should distinguish missing policy, missing
topic, event-only content and excluded promotion/homonym shapes.

## 2. Minimal Zhipu wire

Keep rerank v1/v2/v3 branches literal. Add `topic-rerank-v4-minimal-order-contract` with a new prompt
and strict response model. The preferred wire is deliberately small:

```json
{"order":["event-uuid-1","event-uuid-2"]}
```

The response object forbids extra keys; `order` must be a bounded list of strict UUID strings and a
complete permutation of the request candidates. Do not accept aliases, markdown fences, prose,
partial lists or recursively discover an `order` field. The shared JSON-object extractor may keep
its already-reviewed top-level JSON decoding behavior.

The adapter converts a valid order into the existing domain result. It assigns ordinals locally,
derives an allowlisted reason such as `model_rank_order`, and uses a fixed safe explanation such as
`模型在固定候选池内调整顺序`; provider-authored explanations never cross the boundary. If the
existing reason-code allowlist cannot represent this without mutating old versions, add one code
that is only emitted by v4 and keep old output snapshots unchanged.

## 3. Validation and fallback

Existing domain validation remains authoritative:

- same complete candidate set, no duplicate/unknown/missing IDs;
- same priority groups and no group crossing;
- unchanged event/version and base-order binding;
- one provider call at most, deterministic fallback on every invalid result;
- automatic daily/slot finalization before atomic persistence.

Do not add schema-correction retries. `max_attempts` remains the transport retry setting used by
normal runtime, while the one-time compatibility probe explicitly sets it to one.

## 4. Configuration and persistence

- Update current Settings, `.env.example`, Compose and Doctor to the new scoring and rerank versions.
- No migration is expected: current config snapshots and rerank audit records store bounded strings
  and JSON projections.
- Update provider-free eval canonical artifacts only after the deterministic contract changes pass.
- Public OpenAPI is expected to remain unchanged; still run drift checks.

## 5. One-time compatibility probe

After focused/full deterministic gates, run a task-local, isolated probe against the configured
official Zhipu endpoint with a frozen synthetic request. It must:

- perform exactly one HTTP attempt (`max_attempts=1`);
- avoid repositories, schedulers, workers, local business DB and publication services;
- print/store only typed success/failure, safe usage and latency;
- never preserve raw response content or retry after failure.

This probe validates transport compatibility only. It must not be presented as a fresh news run or
as evidence that the production pipeline was deployed.

## Failure matrix

| Condition | Result |
|---|---|
| Ministry event-only item below threshold | no priority; normal below-threshold handling |
| Substantive authenticated science-education action | priority eligible if no veto |
| Valid complete v4 ID order | local item projection, then existing finalizer |
| Unknown/duplicate/missing/extra ID | typed invalid permutation, deterministic fallback |
| Cross-priority order | priority-barrier fallback |
| Provider JSON/schema/timeout/error | typed fallback, no correction call |
| Compatibility probe failure | stop; no retry and no business side effect |

## Rollback

Rollback is configuration-only: restore the prior current defaults. Historical records remain
readable because v3/.9 and rerank v1/v2/v3 stay supported. No data rewrite or migration downgrade is
needed. Production deployment is outside this task.
