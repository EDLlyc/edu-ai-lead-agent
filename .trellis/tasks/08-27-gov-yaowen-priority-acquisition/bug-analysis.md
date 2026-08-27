## Bug Analysis: Same-day scoring upgrade restarted the content scheduler

### 1. Root Cause Category

- **Category**: B/E — Cross-layer contract and implicit assumption
- **Specific cause**: the repository correctly rejected a second content-slot run whose immutable
  date/slot identity already existed with an older scoring snapshot, while the long-lived scheduler
  assumed every reconciliation conflict was fatal. A same-day production scoring upgrade made that
  assumption visible at process startup.

### 2. Why Fixes Failed

1. Recreating the container only replayed the same startup reconciliation and conflict.
2. Preserving the new scoring configuration was necessary; rewriting the stored historical run
   would have hidden the symptom by violating replayability.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Runtime | Catch the typed scheduled-reconcile conflict, preserve history, and continue the scheduler | DONE |
| P0 | Test | Prove both conflict-skip and successful-run return paths | DONE |
| P1 | Documentation | Record immutable-run conflict behavior in backend quality guidelines | DONE |
| P1 | Monitoring | Retain a structured conflict event without provider bodies or stored content | DONE |

### 4. Systematic Expansion

- **Similar issues**: any scheduler that reconciles a date-scoped immutable run across an in-day
  configuration upgrade can encounter the same boundary.
- **Design improvement**: manual commands may expose conflicts, but periodic reconciliation must
  interpret an existing incompatible historical identity as a no-op rather than mutate it.
- **Process improvement**: release health checks must inspect restart counts after the initial
  healthy state, not only container creation success.

### 5. Knowledge Capture

- [x] Updated `.trellis/spec/backend/quality-guidelines.md`.
- [x] Added scheduler conflict regression tests.
- [x] Preserved the existing run and made no database rewrite.
