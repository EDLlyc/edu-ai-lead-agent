# Design: IP asset filter and metadata repair

## 1. Boundaries

```text
text message + explicit UI filters
              │
      provenance-preserving intent
       ┌──────┴────────┐
 explicit hard query   inferred soft hints
       │               │
 PostgreSQL gates      in-memory metadata evidence
       └──────┬────────┘
        V2/V3 rank selector

approved 41 manifest + ready/shared DB rows + verified MinIO originals
              │
 glm-5v-turbo plan (read-only DB, <= 41 new requests; <= 43 cumulative)
              │
 private canonical plan JSON
              │
 provider-free CAS apply ── provider-free CAS restore
```

The product search repair stays in the existing application/domain/API/UI path. The batch metadata
repair is a development-only CLI and never becomes an HTTP endpoint, worker, startup hook, or web
annotation page. Canary, plan and result use v2 schemas plus v2 fingerprint domains; v1 artifacts
and the old `glm-4.6v-flash` identity cannot be loaded or reused by this execution contract.

## 2. Search intent and reason contract

Add a private `_IpAssetTextSearchIntent` containing an `IpAssetQuery` with request-owned hard
filters plus separate character, asset-type, orientation, and transparent-background hints.
Inference reads only the current turn and never mutates the hard query. Explicit values suppress a
conflicting hint for that dimension.

Metadata candidate enumeration returns a private outcome containing ranked hits and whether the
hard-filtered pool had any rows. Hints add positive deterministic metadata evidence but never a
penalty or exclusion. Generic `透明底` is an alpha hint; the stronger controlled phrases
`透明底素材` / `免抠素材` / `透明抠图` additionally hint `transparent_cutout`. Semantic-only rows
remain eligible.

Search precedence is:

1. no hard-filtered ready/shared candidate -> `degraded_metadata/no_filtered_candidates`, empty,
   zero embedding calls;
2. candidates but embeddings disabled -> `semantic_disabled`;
3. provider failure -> `provider_unavailable`;
4. successful query embedding but no compatible vector -> `partial_index`;
5. compatible vector hits -> `semantic`, null reason, normal V2/V3 merge.

The degraded reason becomes a closed backend/OpenAPI enum. The frontend maps every value to bounded
Chinese guidance and never renders raw codes. `no_filtered_candidates` is an empty-filter outcome,
not a claim that the semantic provider failed.

This changes candidate admission for both existing rank selectors but not their sort keys or
weights. The project treats V2/V3 as rank-policy identities; evaluation comparisons across this
correctness boundary must additionally bind Git SHA and must not reuse the prior live run as a
post-repair result.

## 3. Repair plan identity and privacy

The repair domain owns strict frozen Pydantic plan/result models with `extra='forbid'` and canonical
JSON fingerprints. The plan selects exactly 41 unique approved manifest checksums, maps them
one-to-one to ready/shared rows, verifies each immutable MinIO body, and sorts by safe `asset_ref`.

The public plan uses a domain-separated content commitment rather than a raw storage checksum. Its
metadata fingerprint covers only repairable fields and dimension-aware free tags. Department,
contributor, orientation, source, visibility, status, ownership, blob/media identity, embedding,
favorites, downloads, and generation lineage are immutable for this workflow.

Each item contains safe before metadata, raw controlled provider suggestion, deterministic proposed
metadata, changed fields, provider/model/policy identity, status, and a closed failure code. It never
contains paths, filenames, buckets, object keys, UUIDs, raw checksums, pixels/Base64, prompts,
provider bodies/request IDs, credentials, or user/profile/session information. Directories are
`0700`; artifacts are symlink-safe, atomically created at `0600`, fsynced, and never overwritten.
Provider failures preserve only the safe category `provider_authentication_failed`,
`provider_rate_limited`, `provider_request_rejected`, `provider_timeout`,
`invalid_provider_output`, or `provider_unavailable`; raw status bodies and exception text remain
discarded.

## 4. Recognition and proposal policy

The CLI reuses `create_ip_asset_recognition_model`, `IpAssetRecognitionService`, upload validation,
pixel-only normalization, and `MinioIpAssetStore.get_verified`. A `glm-5v-turbo` canary is the first
selected asset and also its final classification. Exact returned model identity and strict schema
must pass before the remaining 40 are processed. Thinking stays disabled, concurrency stays one,
and there is no model fallback or retry multiplication.
The visual request omits `response_format` because the official API contract reserves that field
for text models. It requests deterministic generation with `do_sample=false` and enforces the
single JSON object through the bounded prompt plus strict local extraction and Pydantic validation.

The proposal policy is versioned and deterministic:

- preserve an existing non-`other` character; otherwise use the recognized character;
- accept a recognized non-`other` asset type, otherwise preserve the existing type;
- replace an optional semantic field only when the recognized value is non-empty;
- merge current dimension-`free` tags with suggested tags, normalize/deduplicate, and cap using the
  domain limit;
- preserve department/contributor and all non-repairable fields.

Provider suggestions remain labeled AI-only rather than human Gold.

## 5. Atomic apply, idempotency, and restore

Before each repository CAS, reconstruct the current object descriptor and verify its immutable bytes
outside the database transaction. An unreadable or mismatched object is `content_drift` and performs
no CAS. The repository primitive then uses one short transaction per item: it locks the row,
validates ready/shared state and the approved-set binding, reads dimensioned tag rows, recomputes
the database content commitment and metadata fingerprint, then follows this order:

- content mismatch -> `content_drift`, no write;
- current equals proposed -> `already_applied`, no write;
- current differs from before -> `metadata_drift`, no write;
- current equals before -> atomically replace repairable scalars, derived naming fields, and tag
  rows; set `updated_at`; reread and verify proposed fingerprint before commit.

When the derived naming key changes, reuse the existing advisory-lock and version-allocation logic.
Stable asset identity and foreign keys never change. Apply writes an immutable result manifest and
returns nonzero when any drift/failure exists, even if independent items succeeded.

Restore consumes the result manifest and uses the same CAS operation in reverse. It restores
semantic metadata and a correctly regenerated canonical name; it need not resurrect the exact old
name-version number if another asset has since occupied that naming sequence.

## 6. Compatibility and rollback

- No database schema or Alembic migration.
- Existing upload recognition remains explicit-click, transient, editable, and backward compatible.
- No batch API/UI route; ordinary startup and all default tests are provider-free.
- OpenAPI and generated TypeScript update only for the closed degraded-reason enum.
- Metadata restore is the operational rollback; code commits remain independently revertible.
- The previous 248-call retrieval evidence remains historical pre-repair evidence and is not
  overwritten or described as post-repair quality.

## 7. Validation

Provider-free tests cover hint provenance, explicit filters, zero candidates, partial index,
frontend copy, plan schema/fingerprints/privacy, exact-41 preflight, fake recognition, dimensioned
tags, naming, CAS, idempotency, drift and restore. Real PostgreSQL/MinIO integration proves
non-metadata state is unchanged. Ruff, format, strict Mypy, API generation/drift, frontend tests,
Grounded/IP retrieval gates, `make eval-check`, and `git diff --check` must pass.

One authorized live phase runs at most 41 new calls: one `glm-5v-turbo` canary reused as the first
plan item and, only after it passes, the remaining 40. Together with the two failed historical
canaries, the task lifecycle cap is exactly 43. The phase validates and summarizes the plan, reuses
local concurrency one and two-second pacing despite the model's higher platform capacity, applies
it, re-applies provider-free to prove zero changes, verifies distribution/non-metadata invariants,
and retains the private v2 artifacts under ignored `output/`. It does not run the 248-query paired
retrieval again.

The completed execution followed that contract exactly: the v2 canary passed with one call, its item
was reused for a 40-call serial suffix, and the final plan had 41 completed recognitions with no
failure or interrupted suffix. The first provider-free apply changed 41 rows; replay changed zero
and returned 41 `already_applied` outcomes. Post-apply verification matched every proposal and
preserved the non-metadata snapshot. The restore-ready result remains retained but was not executed.
