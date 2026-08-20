# Design — layered automatic news selection

## Decision

Compose the requested four layers from the existing governed selector and reranker instead of
adding a second scoring model:

```text
immutable governed candidates
  -> hard-veto evaluation
  -> broad deterministic eligibility/order (.9)
  -> bounded LLM permutation (new immutable rerank policy)
  -> automatic finalizer over the same frozen pool
  -> atomic score/rerank/selection persistence
```

There is no human-review state in this selection flow. Valid model output is applied; model or
finalization failure uses the exact deterministic order; an empty eligible pool remains
`no_topic`. Downstream copy/image/WeCom review and delivery policy are unchanged.

## Layer contracts

### 1. Hard-rule layer

Keep `TopicVetoCode` and `.9` scoring authoritative. Only candidates with `eligible=true` and no
veto can enter the rerank pool. The LLM never sees vetoed candidates and cannot change eligibility,
source/evidence identity, threshold state or numeric score.

### 2. Broad-recall layer

Reuse the `.9` broad-hard-tech pool, deterministic score and stable ordering. Candidate count is
bounded by the existing rerank limit (maximum eight). Completed progress remains deterministically
stronger than plans/failures/capital/events/products, but every governed eligible shape can be
considered by the model.

### 3. LLM fine-ranking layer

Introduce a current immutable policy such as `topic-rerank-v3-layered-auto-finalize`. Preserve
literal v1 and v2 prompt/payload/parser/config round trips. V3 keeps the strict JSON object,
complete-permutation, allowlisted-reason, priority-barrier, temperature-zero and one-call
contracts. No second judge call is added.

The current settings key remains `CONTENT_LLM_RERANK_ENABLED`. It defaults to enabled for the
content selection feature, but the overall content stage remains default-off. When content is
enabled and rerank is enabled, settings require `fake` or `zhipu`; content-disabled development may
still use `AI_PROVIDER_MODE=disabled` without making API/import tooling unusable.

### 4. Automatic finalization layer

Add pure daily and slot finalizers that receive the deterministic decision, exact rerank pool and
the model/fallback outcome. Before applying an LLM order they assert:

- outcome base order equals the exact pool order from this run;
- every pool event and version matches an eligible score in the frozen decision;
- final order is the same complete candidate set and respects priority groups;
- slot candidates remain eligible and not same-day-excluded;
- configured candidate/item limits remain satisfied.

If an invariant fails, convert the outcome to a typed deterministic fallback and keep the original
decision order. Do not raise into a manual-review state. Persistence then retains its existing
lease, config fingerprint, date/profile lock, event/version FK and cross-slot uniqueness checks.

## Persistence and compatibility

No migration is planned. Existing run JSON snapshots pin the v3 policy identity; existing
`topic_rerank_records` already stores outcome/failure, base/final order, safe reasons,
fingerprints, usage and latency. Existing topic scores retain deterministic/final ranks. Public API
shapes remain unchanged because failure codes and policy versions are strings.

Historical migrated disabled v1 and explicit v1/v2 snapshots must preserve their exact field sets
and semantics. The finalizer is authenticated only by the new v3 policy; historical outcomes use
their existing application path.

## Failure matrix

| Condition | Automatic result |
|---|---|
| Zero eligible candidates | `no_topic`; no provider call |
| One candidate | Skip provider; deterministic selection |
| Provider timeout/error/malformed JSON | Typed fallback; deterministic selection |
| Unknown/duplicate/missing ID or group crossing | Typed fallback; deterministic selection |
| Outcome belongs to another pool/run or event-version binding differs | Finalization fallback; deterministic selection |
| Slot candidate becomes unavailable in the frozen decision | Finalization fallback; deterministic slot order |
| Lease/config/date lock/FK fails at persistence | Existing durable retry/conflict behavior; no partial decision |

## Risks and controls

- **More provider use:** maximum one call per daily/slot decision and at most eight candidates;
  zero/one candidate skips transport.
- **Model authority creep:** the finalizer reasserts deterministic boundaries and never accepts new
  facts, candidates, scores or veto changes.
- **Historical drift:** add a policy identity rather than modifying v1/v2.
- **Scope creep:** do not change copy, image, OCR, delivery, manual-review or production settings.
