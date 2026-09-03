# Bug Analysis: Provider batch continued and partial plans remained applicable

## 1. Root Cause Category

- **Category**: B + E — Cross-Layer Contract and Implicit Assumption
- **Specific Cause**: the provider adapter correctly classified a rate limit, timeout, or
  unavailability, but the batch orchestrator treated every item failure as independent and the
  apply service treated a structurally valid diagnostic plan as mutation-ready. The implicit
  assumption was that a passing first canary proved the provider would remain available for all
  remaining calls. That assumption was not encoded in the plan/apply contract.
- **Observed evidence**: the corrected one-call canary returned the safe category
  `provider_rate_limited`. The artifact did not retain provider bodies or an upstream business error
  code, so the exact quota/window/account cause remains unknown and is not inferred.

## 2. Why Earlier Fixes Were Incomplete

1. **Canary-only guard**: it protected the first compatibility request, but not a shared transient
   failure after several successful batch items.
2. **Per-item failure modeling**: it preserved diagnostic evidence, but the loop continued to spend
   the remaining external-call budget after a failure likely shared by the whole provider lane.
3. **Schema validation at apply**: it verified fingerprints, counts and identity, but did not
   distinguish a valid diagnostic checkpoint from a complete mutation plan. Earlier changed items
   could therefore be applied even when later items had failed or were never called.
4. **Concurrency-one assumption**: serial execution prevented bursts but provided no inter-request
   pacing. Concurrency and request rate are separate controls.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Stop batch calls after the first `provider_rate_limited`, `provider_timeout`, or `provider_unavailable`; retain completed items and fill the remaining ordered set as `not_called` without suggestions. | DONE |
| P0 | Runtime | Require every item to have a completed recognition and zero plan failures before apply; perform this check before the first repository CAS. | DONE |
| P0 | Test coverage | Prove all three transient categories stop call consumption and that partial apply performs zero in-memory and PostgreSQL mutations. | DONE |
| P1 | Rate control | Pace only provider-bound calls with a fingerprinted default of 2 seconds and a CLI-safe bound of 0.5–60 seconds; keep one attempt per image. | DONE |
| P1 | Artifact contract | Keep an exact 41-item, canonical, private diagnostic plan after interruption; completed results remain reusable evidence and uncalled items contain no invented suggestion. | DONE |
| P2 | Operations | Before another live run, determine account-specific limits outside repository artifacts; do not parse or persist raw provider bodies as a shortcut. | TODO |

## 4. Systematic Expansion

- **Similar issues**: any provider-backed batch that models item failures but later performs a
  whole-batch mutation needs separate `diagnostic-valid` and `mutation-ready` gates.
- **Design improvement**: transport categories must reach orchestration policy without leaking raw
  response data. The orchestrator, not the adapter, decides whether a category is item-local or
  batch-shared.
- **Process improvement**: review provider workflows as `preflight → canary → paced batch → complete
  plan gate → mutation`, and test failure at the beginning, middle and end of the batch.
- **Knowledge gap**: a successful canary proves request compatibility at one instant; it does not
  prove quota, availability or latency for the rest of the run.

## 5. Knowledge Capture

- [x] Update `.trellis/spec/backend/ip-asset-hub.md` with pacing, circuit-break and complete-apply
      contracts.
- [x] Update `.trellis/spec/guides/cross-layer-thinking-guide.md` with the general batch-provider
      checklist.
- [x] Record the implementation evidence in the task implement notes.
- [x] Add provider-free unit, CLI and PostgreSQL/MinIO integration regressions.
- [ ] Resolve the account-specific 429 cause operationally before requesting another live run.
