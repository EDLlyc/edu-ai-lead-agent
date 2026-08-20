# Current layered-selection gap

## Existing reusable stages

1. **Hard rules** — `score_topic_candidate()` owns governance, evidence, Tier-C-only, unverified,
   privacy/legal/safety, prohibited-marketing, delivered-repeat and stale-event vetoes. The current
   `.9` hard-tech policy never lets the below-threshold pool override those vetoes.
2. **Broad recall** — `scoring-v1-preview.9-broad-hard-tech-pool` admits governed Tier-A/B
   hard-tech plans, failures, capital, events, product releases and completed progress into the
   eligible pool while preserving typed signals and deterministic scores.
3. **LLM fine ranking** — `TopicRerankRequest` exposes at most eight already-eligible projections.
   `validate_topic_rerank_result()` requires an exact permutation and enforces priority groups;
   provider/output failures become exact deterministic-order fallback.
4. **Durable audit** — run snapshots pin scoring and rerank configuration. `topic_rerank_records`
   stores base/final orders, safe reason codes, fingerprints, usage, latency, outcome and failure.

## Concrete gap

- `apply_daily_topic_rerank()` and `apply_content_slot_rerank()` trust that the supplied durable
  outcome belongs to the just-built pool. `TopicRerankOutcome` validates its own order but does not
  bind that order to the current decision's event/version pairs. A valid outcome from another run
  can therefore fail through a lookup/exception rather than converging to deterministic fallback.
- The existing `topic-rerank-v2-zhipu-json-contract` and config describe model validation, but do
  not name an explicit automated post-model finalization policy.
- LLM rerank remains default-off. The layered architecture is therefore available but is not the
  default behavior of an enabled content pipeline.

## Minimal safe change

- Add a new immutable rerank policy identity for layered auto-finalization; keep literal v1/v2
  request/prompt/parser/snapshot behavior replayable.
- Add a pure finalizer that binds outcome `base_order` to the exact generated pool, binds each pool
  event/version to the frozen decision, reasserts eligibility/veto/priority/same-day invariants,
  then either applies the LLM order or converts to typed deterministic fallback. It must never
  create `review_required`.
- Reuse the existing rerank record and score/selection persistence; no migration or public response
  shape is required. The run snapshot carries the new policy identity and the existing audit shows
  applied/fallback/skipped behavior.
- Make rerank the default for an enabled content pipeline while retaining fail-closed settings:
  content-disabled development may keep the AI provider disabled, but content execution with
  rerank enabled requires `fake` or `zhipu`.
- Do not touch copy, image, OCR, Enterprise WeChat, delivery review, deployment or live provider
  configuration.

## Verification targets

- Cross-run outcome, event-version mismatch, missing/extra candidate, group crossing and slot
  same-day drift cannot reach persistence as an applied model order.
- All such finalization mismatches preserve the deterministic decision and store a bounded failure
  code; there is no human-wait state.
- Historical disabled/v1/v2 snapshots remain byte-for-byte round-trippable and current API/schema
  projections remain compatible.
