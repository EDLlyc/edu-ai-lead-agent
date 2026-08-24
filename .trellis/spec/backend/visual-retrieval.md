# Brand Multimodal Visual Retrieval

## Scenario: Approved-catalog multimodal retrieval and automatic visual selection

### 1. Scope / Trigger

This contract applies to indexing and retrieving the approved private Sai Xiansheng visual catalog.
It is separate from brand-document RAG and factual evidence. Alembic `20260821_0024` adds
`brand_visual_index_jobs` and `brand_visual_asset_embeddings`; `20260821_0025` separates approved
source checksums from normalized embedding-input hashes. The embedding table remains a dedicated
`vector(2048)` space.

### 2. Signatures

- Provider/model: `alibaba-model-studio` / `qwen3-vl-embedding`.
- Dimensions/active input policy: `2048` / `brand-visual-embedding-input-v2`.
- Historical `brand-visual-embedding-input-v1` rows remain readable only through an explicit v1
  identity. The old v1 derivation-key formula is frozen; v2 keys additionally bind the normalized
  embedding-input SHA-256. V1 and v2 rows never satisfy one complete-index proof together.
- Migration `20260821_0025` backfills only historical v1 rows. If any non-v1 policy row already
  exists at `0024`, upgrade fails closed instead of claiming its source checksum was the actual
  embedding input.
- Compose/environment input uses the ordinary string `"2048"`; Settings normalizes only that exact
  representation to integer `2048` and rejects every other dimension.
- Canonical query/selector: `brand-visual-query-v1` /
  `brand-visual-selector-v2-multimodal`.
- An asset derivation includes catalog version, asset ID/source checksum, actual embedding-input
  checksum, provider, model, dimensions, and input policy. Rows are immutable and are never reused
  across a mismatched identity.

### 3. Contracts

#### Input-policy v2 normalization

- Validate source PNG bytes under the catalog's 25 MiB, 8192-edge and 32-million-pixel limits and
  fully decode the raster in memory. Never overwrite a source file or manifest.
- Inputs at or below the 7 MiB raw provider budget may remain byte-identical after validation.
  Larger inputs convert to RGB/RGBA, discard ancillary metadata, and use the fixed LANCZOS maximum-
  edge schedule `4096, 3072, 2560, 2048, 1792, 1536, 1280, 1024, 768, 512, 384, 256`.
- Encode every candidate as PNG with `optimize=false` and compression level 9. Accept the first
  metadata-free output at or below 7 MiB; otherwise fail before HTTP. The complete serialized JSON
  request must remain below 10 MiB.
- Indexing and image-query search call the same pure normalizer outside the event loop. Persistence
  keeps both the approved source checksum and the actual normalized input checksum.

#### Index and query contract

- Only an explicit local operator indexes assets; API/worker startup never does so.
- Reload and validate the manifest and recheck PNG bytes/checksum before each provider call and
  again after the provider returns and before persistence. Store no path, filename, image bytes,
  request ID, provider body, or workspace. The lease must outlast the configured provider timeout.
- A lease-owned job may persist exactly one ready vector. Re-running a ready derivation is
  idempotent; a changed catalog/checksum/policy produces a distinct derivation.
- Text and PNG queries use the same adapter. Retrieval requires exact identity and complete current
  approved-catalog coverage before returning a score map.
- Paid-query consumers call `prove_complete_catalog` on their exact candidate projection before
  constructing the provider client or embedding any text, then `search_complete_catalog` rechecks
  the same identity after every result. A successful preflight is not permission to reuse a later
  partial or changed score map.
- API results expose only a 16-character asset reference, approved role/kind/tags, catalog version,
  bounded cosine similarity, and `evidence_eligible=false`.
- The provider adapter accepts only the active frozen identity, bounds the serialized request before
  HTTP, includes concurrency-queue wait inside the overall timeout, streams a bounded response,
  performs one attempt, and rejects any explicit conflicting model/provider echo. Repository
  failures cross the application boundary only as typed unavailable states.

#### Selection and fallback

Identity coverage, approved state, role, PNG/integrity bounds, reference count, and byte budget run
before semantic ranking. Inside each eligible role pool, order by cosine similarity, existing rule
score, priority/novelty, then stable asset ID. A semantic score can never admit an ineligible asset.

On disabled provider, authentication/timeout, malformed output, identity mismatch, partial index, or
catalog change, persist only `semantic_unavailable` plus a closed reason and execute the previous
deterministic selector. Do not retry within the attempt or block image generation solely for this
degradation.

Semantic reference snapshots include bounded similarity, the legacy deterministic rule score, and
`semantic_primary`. When the feature is disabled, omit these fields and the semantic snapshot so the
legacy selector order, fingerprint, and stored snapshot remain literal. The search route validates
exactly one bounded, structurally valid PNG or text query even while disabled.

The local official-account v7 consumer is stricter: it validates the complete 2--41 approved
body-candidate projection and all at-most-five bounded section queries before preflight. It uses a
placement-bitmask assignment over complete score maps. Any query/result/catalog failure discards
the entire matrix, reloads and validates the complete catalog, and performs one deterministic
fallback. Its persisted Article snapshot contains public references, query fingerprints and
similarity bands only; retry never re-embeds.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Source is not an approved bounded PNG, exceeds 25 MiB/8192 edge/32 MP, or cannot fully decode | `input_normalization_failed` before HTTP; no ready row |
| Normalized image cannot fit the fixed 7 MiB budget or serialized JSON reaches 10 MiB | Typed input failure before HTTP; never send an oversized request |
| Provider times out while waiting for concurrency or during HTTP, rejects auth/rate/availability, or returns malformed output | One typed unavailable result; no retry inside the attempt |
| Provider explicitly echoes a conflicting provider/model/dimension | `identity_mismatch`; no vector persistence |
| Manifest, approval, checksum, catalog, source hash, normalized-input hash, policy, lease or request fingerprint changes | Fence the result and fail the claimed derivation |
| Current catalog has partial, duplicate, v1-only, mixed-policy or mixed-provider rows | `index_incomplete`; deterministic selector-v1 fallback |
| Migration 0025 sees any pre-existing non-v1 visual row | Refuse upgrade before backfill; never invent a normalized-input hash |
| Downgrade is requested while v2 rows exist | Refuse downgrade until the application and v2 rows are explicitly retired |
| Semantic feature is disabled | Literal selector-v1 order, fingerprint and snapshot; no semantic-only fields |
| Semantic feature is enabled with exact complete v2 coverage | Rank only hard-gate survivors; persist bounded similarity, legacy rule score and `semantic_primary` |
| Any official-account candidate/query fails before preflight | Zero client/provider/search calls; no partial candidate fallback |
| An official-account query or catalog fence fails after earlier results | Discard all results; reload the full catalog and use one deterministic whole-plan fallback |

### 5. Good / Base / Bad Cases

- Good: all 41 approved assets have exact current-catalog v2 vectors; a bounded text query returns one complete
  score map, and each eligible role pool uses semantic-primary ordering without changing identity or byte gates.
- Good: the official-account worker proves coverage once, makes at most one call per placement,
  rechecks every result, then persists one complete bounded assignment before rendering.
- Base: the provider is disabled/unavailable or the index is incomplete; the package uses byte-stable selector-v1
  behavior and stores only a closed `semantic_unavailable` reason.
- Bad: combine 36 historical v1 rows with five v2 rows, embed a large PNG without normalization, retry a paid
  provider call invisibly, persist provider bodies/paths/vectors, or allow cosine similarity to admit an
  unapproved/wrong-role asset.

### 6. Tests Required

- Domain/adapter tests cover exact 2048 vectors, text/image payloads, fixed normalization hashes and
  dimensions, metadata removal, request-envelope bounds, hard barriers, stable ties, malformed
  output, one attempt, and secret-safe errors.
- Consumer tests prove all queries validate before complete-index preflight, incomplete indexes make
  zero calls, one late failure discards earlier results, refreshed catalog races cannot retain stale
  candidates, and persisted official-account recovery performs no query.
- Real PostgreSQL tests cover lease ownership, idempotency, derivation scope, complete-index proof,
  and cosine order. Migration, OpenAPI, Compose, Doctor, Ruff, strict mypy, and secret scans remain
  green.
- Default tests/builds use disabled or fake providers and make no external request. A live catalog
  run is a separately coordinated final operation with aggregate-only output.

### 7. Wrong vs Correct

#### Wrong

```python
# Raw high-resolution bytes can exceed the provider envelope, and v1/v2 rows are mixed.
request = VisualEmbeddingRequest.for_image(source_png)
rows = repository.search_without_identity_filter(query_vector)
selection = sorted(all_assets, key=lambda asset: cosine[asset.asset_id], reverse=True)
```

#### Correct

```python
normalized = normalize_visual_embedding_image(source_png, identity=v2_identity)
claim = await repository.claim_asset(
    source_checksum=source_checksum,
    embedding_input_sha256=normalized.embedding_input_sha256,
    identity=v2_identity,
)
ranking = await repository.search_complete_catalog(
    catalog_assets=approved_catalog_assets,
    identity=v2_identity,
    query=query_embedding,
)
# AssetSelector applies identity/role/approval/integrity/count/byte gates before ranking survivors.
```
