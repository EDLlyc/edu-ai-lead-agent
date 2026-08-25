# Bug Analysis: Personal-library access and completion invariants

### 1. Root Cause Category

- **Category**: B/D/E — cross-layer contract, test coverage gap, and implicit assumptions.
- **Specific cause**: the first implementation validated individual relations but did not always
  validate their conjunction. A favorite was treated as sufficient personal-list authority, a
  worker claim was treated as durable completion truth, and a rolling date lower bound was treated
  as a complete window. Exact-byte deduplication also coupled embedding enqueue to profile
  membership even though those are independent responsibilities.

### 2. Why Fixes Failed (if applicable)

1. No repeated production fix failed. The independent review found the gaps before release.
2. Broad unit and integration gates initially passed because they covered each ordinary flow but
   did not construct adversarial combinations: orphan favorite plus private asset, future aggregate
   plus rolling window, stale claim plus locked job, and profile-less generation plus new output.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Make the lease-locked job/reference rows authoritative during completion | DONE |
| P0 | Architecture | Require ready plus shared-or-owned access before any private media or relation action | DONE |
| P0 | Test coverage | Add adversarial access, ranking, completion, embedding, and downgrade regressions | DONE |
| P1 | Documentation | Record the conjunction and rollback contracts in backend/frontend IP specs | DONE |
| P1 | Migration safety | Refuse destructive `0035 -> 0034` rollback while non-legacy data exists | DONE |

### 4. Systematic Expansion

- **Similar issues**: any future collection, reaction, label, or analytics relation can be mistaken
  for access authority; every time-window query can omit its upper bound; every leased worker can
  accidentally trust an in-memory claim after durable state changes.
- **Design improvement**: keep visibility, readiness, relationship, and job-fencing predicates
  explicit at repository boundaries instead of inferring one from another.
- **Process improvement**: review new cross-layer features with adversarial pairings, not only one
  happy-path test per requirement. Migration review must separately prove clean rollback and
  refusal-before-destruction with live new-schema data.

### 5. Knowledge Capture

- [x] Updated `.trellis/spec/backend/ip-asset-hub.md` with executable invariants and assertion points.
- [x] Updated `.trellis/spec/frontend/ip-asset-hub.md` with stable retry and deep-link eligibility.
- [x] Added regression tests for the identified combinations.
- [x] Confirmed this project has no `src/templates/markdown/spec/` mirror to synchronize.
