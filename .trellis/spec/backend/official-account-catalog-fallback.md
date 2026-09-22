# Prospective single-draft catalog fallback

## 1. Scope / trigger

This contract applies only to future date-scoped single editions frozen with
`official-account-visual-pipeline-v4-resilient-tolerant-geometry`. It keeps a provider outage
from blocking an otherwise accepted unpublished draft. It does not authorize historical replay,
another paid attempt, reset of unknown results, or publication. Existing V1/V2/V3 identities
remain unchanged. See [single editions](./official-account-single-edition.md) for ownership,
scheduling, lease fencing, and intent/ACK delivery.

## 2. Signatures

- `load_catalog_fallback_source(sessions, edition, *, now) -> CatalogFallbackSource` is the
  read-only database proof boundary.
- `PreparedSingleDraftArtifactOwner.build_fallback_child(*, edition, now, catalog)` reads
  approved immutable material and creates one content-addressed prepared directory.
- `build_catalog_fallback_projection(...) -> StrictPreparedProjection` constructs the pure
  manifest/HTML/media contract; `validate_catalog_fallback_projection(manifest, files)` rebuilds
  it independently before the consumer may upload.
- Prepared version: `wechat-draft-prepared-child-v6-approved-catalog-fallback`.
- Artifact media type: `application/vnd.wechat.approved-catalog-fallback-child+directory`.
- Status: `python -m app.official_account_weekly_dag_main single-status`.
- SQL schema remains `20260916_0048`; there is no fallback migration or historical backfill.

## 3. Contracts

Activate V4 through `OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION`; do not silently override an
explicit V3 setting during admission. Frozen edition/run policy and physical request fingerprints
must agree. `IMAGE_MAX_ATTEMPTS=1` disables hidden adapter retries; the existing durable visual
ledger owns the three physical attempts for a slot. Changing configuration never changes an old
edition's identity or creates a second account/date edition.

Fallback requires all of the following:

- The producer owns a current, unexpired edition lease and is inside its same-day preparation/
  delivery window. Edition, account, material package, run, frozen identity and retry expiry agree.
- The live Article run is terminally failed/result-unknown for an allowed visual reason, has no
  active lease or local ready draft, and still owns its accepted Article and matching render.
- The Article passed deterministic validation and its frozen editorial release rule. No visual
  fallback can bypass factual, account, identity, ownership or content checks.
- Earlier completed visual slots remain intact. The failed slot has three complete, matching
  durable failed attempt records, including physical ordinal/request identity, logical identity,
  stage/provider, V4 policy and closed safe failure diagnostics. Reject additional same-slot/
  logical-key records, incomplete attempts, an existing prepared child/ACK, or a shifted business
  date. Top-level `attempts_exhausted` alone is insufficient. Use the existing strict diagnostic
  decoder, including its complete key/type contract, rather than a looser reconstructed decoder.
- All five selected catalog references are the Article's already frozen assignments; catalog
  version, source master and publication checksums still match, and trusted character metadata
  identifies Xiaosai only. Do not search for replacement images after failure.

The prepared child contains five catalog source rasters and deterministic upload derivatives,
retains original-news media and its source/credit/rights binding, and preserves accepted text,
author and fixed header/footer framing. It uses the existing no-reader-link source presentation
and compact layout. No generated image is mixed into the five-image fallback set.

Record `origin=approved_catalog_fallback` and `single-catalog-fallback-evidence-v1`, including
the exhausted slot, logical request fingerprint and all three physical proofs. Bind every file,
Article/render identity, layout/source version, manifest and child fingerprint. Do not create
generated-visual success rows, synthetic audit passes or a paid-attempt-4 request. The original
failed run and all unknown attempts remain unchanged; a successful draft does not erase the
provider failure. Existing journaled single delivery still exclusively owns WeChat writes.

The status command performs a SQL `READ ONLY` transaction and reports bounded date/status/error
summaries, local receipt acknowledgements, visual provenance, queue/lease counts, configured
planes, legacy mutual exclusion and the next eligible Shanghai window. Its
`contract_scope=local_automation_not_remote_publication_readback` is mandatory: a stored ACK is
not evidence that a human has not subsequently published, edited or deleted the draft. It does not
construct a provider/WeChat client, import ownership or mutate a history barrier.
Report `publication_state=not_checked` and `publishing_capability=False`, not `published=False`.
Configuration describes `current_process_environment`; check the actual service containers
separately before claiming all three deployed planes are enabled.

## 4. Validation and error matrix

| Condition | Result |
| --- | --- |
| Three complete V4 503/timeout or other allowlisted retryable/unknown proofs | Whole-set frozen catalog fallback; zero further paid requests |
| Only one/two failures, missing completion or mismatched physical identity | Reject budget/proof; no fallback or upload |
| Authentication, configuration, invalid raster or identity failure | Preserve hard failure; no broad outage fallback |
| Wrong policy, date, lease, account, content, render or retry expiry | Reject before producing a deliverable child |
| Catalog/source/news bytes or trusted character metadata drift | Reject before upload; do not silently reselect |
| Manifest, originals, derivatives, HTML or fingerprints differ on reconstruction | Consumer rejects the prepared contract |
| Original provider result remains unknown | Preserve its uncertainty; fallback never reconciles it to generated success |
| WeChat intent without ACK | Existing unknown no-replay rule; catalog fallback grants no new delivery authority |

## 5. Good / base / bad cases

Good: the third image slot exhausts three timeout attempts after earlier slots completed; preserve
those records, use all five frozen catalog images, and acknowledge one unpublished draft.

Base: generation succeeds, or a frozen V3 run fails. The pre-existing generation/prepared rules
remain in force; this V4-only fallback is not applied retroactively.

Bad: mix two generated pictures with three stock images, erase a failed run, label stock images
as model output, replace the selected catalog set, reopen yesterday's edition, or infer current
remote publication state from `delivered` alone.

## 6. Required tests

- Unit: exact prepared reconstruction, source/derivative/manifest tampering, complete five-image
  selection, original-news media and framing retention, explicit origin, closed diagnostics,
  physical request-policy separation and no generated-evidence fabrication.
- Isolated PostgreSQL: three persisted unknown proofs, unchanged attempts/run state, no fourth
  dispatch, valid producer lease and expiry, wrong policy/identity/audit/content refusal.
- Consumer/producer: successful generated path unchanged, V4 failure reaches only the fallback
  owner, malformed child refuses delivery, existing journal ACK prevents duplicate add.
- Status: SQL read-only behavior, bounded safe output, next-window timezone/min-date logic,
  explicit V3/V4 configuration, no remote-publication claim and no provider construction.
- Release: schema/health declaration and runtime stay at `0048`; deployment changes only future
  policy, preserves historical rows and journal files, and verifies all 12 applications.

## 7. Wrong vs correct

```python
# Wrong: invent success and retry indefinitely.
failed_visual.status = "ready"
await image_provider.generate(another_request)

# Correct: prove exhaustion, preserve the failed ledger, build and independently validate
# the separately versioned approved-catalog child; existing fenced delivery owns side effects.
source = await load_catalog_fallback_source(sessions, edition, now=now)
```

An unchanged SQL schema does not authorize an old-application rollback after a new prepared
contract exists. Recover with the compatible candidate (optionally restoring future V3 admission)
or leave writers stopped; never downgrade or delete the new durable inputs.
