# Execution

1. Refresh task context to this user-approved recovery slice.
2. Implement bounded typed diagnostics and safe retry classification with tests.
3. Independently inspect existing recovery/derivation and release mechanisms;
   freeze exact-target compensation preconditions and immutable history guards.
4. Independently check the code plus recovery operator using fake clients/isolated DB.
5. Commit only scoped changes; construct and verify an immutable current-base image.
6. Recheck production target and affected active work, deploy the checked candidate,
   and execute only the approved September 16 compensation.
7. Observe complete images/prepared output/WeChat draft ACK and repeat-pass dedupe.
   Report real failures promptly; do not erase unknown outcomes to force success.

## Prospective retry and permissive-review implementation

1. Add a versioned future-run visual policy with three durable physical attempts per image
   slot; preserve V1/V2 decoding, hashes and recovery semantics.
2. Extend the existing claim/attempt boundary so provider, output-integrity and ambiguous
   outcomes can claim the next distinct physical request identity while invalid config/input,
   expiry and lease loss remain terminal. Persist safe diagnostics for every attempt.
3. Keep deterministic raster/geometry/count/byte/subject gates. Under the new policy, persist
   vision and batch-quality findings as advisory and allow readiness despite reviewer rejection,
   unavailability, duplicate/reuse or ordinary relevance/style findings.
4. Add restart/concurrency/budget tests, three-failure exhaustion, success-after-retry, partial
   five-slot reuse, historical replay and permissive-review matrices. Run focused Ruff, format,
   strict mypy, unit and real PostgreSQL integration tests.
5. Independently review the combined diff, then build and deploy a scoped immutable release with
   rollback/config fences. Do not replay the already recovered September 16 edition or publish.

## Checked implementation outcome

- V3 code, migration and historical compatibility are complete. Independent review fixed
  lost-lease replay, stale-attempt persistence and downstream duplicate gates before release.
- The combined image failure/compensation/V3/strict/prepared suite passes 245 tests; focused
  Ruff, format, strict mypy and diff checks pass.
- Release tooling binds the exact deployed base, committed application blobs and only migration
  0048. It quiesces writers, verifies a full PostgreSQL backup, migrates 0047 to 0048, keeps
  `IMAGE_MAX_ATTEMPTS=1`, then switches only the prospective visual policy from V2 to V3.
- Pre-migration failures restore the prior image/config. After a migration attempt, recovery is
  forward-only on 0048 with V2 restored; uncertain recovery leaves official-account writers
  stopped. The release operator contains no model, WeChat, replay or publication path.
- The September 16 draft was already recovered and officially read back through the separately
  reviewed manual route. Deployment must preserve it and must not execute the obsolete
  compensation/replay steps in the original execution outline above.
