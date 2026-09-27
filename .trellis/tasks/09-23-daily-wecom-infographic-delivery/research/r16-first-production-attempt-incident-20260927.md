# R16 first production attempt: failed pre-migration gate and recovery

At about 10:55 UTC on 2026-09-27 the one-attempt `b803cd2` default-off
release passed its locked live admission capture, wrote `intent.json`, and
stopped the 12 application writers. Its next capture failed with
`business_identity_drift`; it wrote `forward-recovery-required.json` and exited
2. No backup, clone, migration intent, candidate installation, enablement or
infographic send occurred. The attempt directory remains single-use and
reconcile-only; it must not be renamed or replayed.

Read-only reconciliation found Alembic `20260916_0048`, both R15 revision
markers, the original image and container IDs, healthy Postgres/MinIO, and no
migration intent. The 12 original containers were started in place without
recreation; subsequent API and dispatcher checks were healthy. A root-worktree
incident record contains the operator's observed output and recovery details.

## Bug Analysis: Live fingerprint used as quiescent backup identity

### 1. Root Cause Category

- **Category:** E (implicit assumption) and D (test coverage gap).
- **Specific cause:** The real adapter latched every table's row digest while
  writers still ran and required that digest after `docker compose stop`.
  Normal commits in the stop window can violate this assumption. The precise
  changed production row was not recorded, so the live-write explanation is
  strongly supported by the code/sequence but not row-level proven.

### 2. Why Fixes Failed

Earlier read-only preflights exercised an idle live snapshot but did not stop
writers. Fake-host tests modeled identical pre/post-stop business fingerprints,
so they missed the normal stop-window commit. The generic failure path also
stopped all applications despite failure before migration intent, requiring
manual reconciliation and restart.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Make first verified stopped-writer digest authoritative; preserve the pre-stop capture as admission evidence | Done |
| P0 | Runtime | Bind dump/clone/release/enablement to a separate quiescent receipt; recheck after backup, clone and before Alembic | Done |
| P0 | Recovery | Pre-migration restart only after exact original-state proof and receipt; post-intent remains forward-only | Done |
| P0 | Tests | Simulate an actual business change during stop, later drift, forged receipt content and failed recovery | Done |
| P1 | Documentation | Add executable release scenario and thinking checklist to Trellis specs | Done |
| P1 | Residual risk | Direct out-of-band DB writes between final check and Alembic need database-level exclusion to remove the last race | Open |

### 4. Systematic Expansion

- **Similar issues:** Any release workflow comparing a live business digest to
  a stopped state, or refreshing a failed post-backup digest as the new truth.
- **Design improvement:** Distinguish admission, authoritative quiescent and
  irreversible migration boundaries explicitly in persisted receipts.
- **Process improvement:** Test real stop-window commits and post-clone drift
  before sealing a production operator; never infer stopped-state invariance
  from a read-only preflight.

### 5. Knowledge Capture

- [x] `.trellis/spec/backend/quality-guidelines.md` has a seven-part
  R16 release contract with signatures, errors and test assertions.
- [x] `.trellis/spec/guides/cross-layer-thinking-guide.md` prompts a
  live-to-quiescent boundary check.
- [ ] New clean committed OCI image, sealed bundle, read-only preflight,
  backup/clone and direct enablement receipts must still be obtained. No
  production success is claimed by this local fix.
