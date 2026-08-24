# Design: brand multimodal visual retrieval

## 1. Architecture boundary

This is a new visual-retrieval capability, not an extension of brand-document RAG. It uses the same vector
dimension only for storage compatibility; it has separate ports, tables, provider settings, version
identities, jobs and response types. Existing `brand_chunk_embeddings` and text retrieval remain unchanged.

The production data flow is:

```text
private approved manifest + PNG bytes
  -> explicit operator index command
  -> Alibaba qwen3-vl-embedding (image, independent, 2048)
  -> immutable compatible visual-asset rows in PostgreSQL

VisualBrief / ControlledVisualPlan
  -> canonical versioned query text
  -> Alibaba qwen3-vl-embedding (text, independent, 2048)
  -> compatible current-catalog cosine score map
  -> existing hard eligibility by character/role/approval/integrity/budget
  -> semantic-primary ordering inside each eligible role pool
  -> existing reference reservation and image generation
```

Provider calls happen outside database transactions. The domain selector receives only bounded semantic
scores; it never receives a client, credential, vector or provider result.

## 2. Domain and port contracts

Add a closed `VisualEmbeddingModality` (`text`, `image`) and immutable request/result contracts. Requests bind
an embedding-input hash, input-policy version, requested model and dimension. Asset derivations separately bind
the approved source checksum and normalized embedding-input hash. Results require exactly 2048 finite,
non-zero values and safe non-negative usage. The adapter binds model identity to the fixed request when the
provider omits it; an explicit conflicting model field is terminal.

`brand-visual-embedding-input-v2` is a pure bounded normalizer used for both indexed assets and image queries.
It first validates the source PNG under the existing dimension/pixel limits. Inputs already below the conservative
provider envelope may remain byte-identical; larger inputs are decoded in memory, stripped of ancillary metadata,
converted to a closed RGB/RGBA representation, resized with one fixed resampler through a bounded descending size
schedule, and re-encoded with fixed PNG parameters. The first output below the fixed raw-byte limit is accepted;
otherwise normalization fails before HTTP. The source file is never overwritten. Unit fixtures lock output hash,
dimensions and request-envelope size for each branch.

Create `VisualSemanticScore` and `VisualSemanticRanking` containing asset ID, bounded cosine similarity,
provider/model/input-policy/catalog identities and completeness. No raw vector crosses into the domain.

Add selector version `brand-visual-selector-v2-multimodal`. v1 is literal replay. v2 first executes all v1
hard eligibility and role-pool formation. Within each eligible pool it orders by:

1. semantic similarity descending;
2. existing deterministic rule score descending;
3. existing priority/novelty decisions;
4. stable asset ID.

Identity coverage, role, approval, file integrity, count and byte limits are never semantic weights. A high
cosine score cannot admit an otherwise ineligible asset.

## 3. Canonical query

`brand-visual-query-v1` serializes only closed `VisualBrief`/plan fields in a fixed order: category, title,
learning goal, scene, main action, characters, subject/cast/composition/camera and allowlisted asset tags.
It is bounded and hashed before provider use. It does not include draft body text, evidence, private paths,
filenames or arbitrary model prose.

## 4. Persistence and migration

Alembic `20260821_0024` adds the two visual-only tables. A follow-up `20260821_0025` adds the explicit normalized
`embedding_input_sha256` identity to jobs and vectors, backfills historical v1 rows from their source checksum,
and makes the field non-null:

- `brand_visual_index_jobs`: one mutable lease/attempt record per immutable asset derivation, with catalog,
  asset checksum, embedding-input checksum, provider/model/dimensions/input-policy, status, bounded error code, token/latency counters,
  timestamps and no path/request ID.
- `brand_visual_asset_embeddings`: ready immutable vectors keyed by asset checksum + catalog version +
  provider + model + dimensions + input policy + embedding-input checksum. The vector is `vector(2048)` and never
  returned by APIs.

The operator reloads and revalidates the manifest immediately before every call and revalidates the asset
again before persistence. A successful embedding is inserted only while the matching job lease is owned.
Retries are explicit operator reruns; unit/integration tests never call the live provider.

Retrieval proves complete v2 coverage for the current catalog derivation before semantic selection. Partial,
mixed-provider, mixed-model or mixed-policy indexes return typed unavailable and trigger v1 fallback rather
than biased partial ranking.

## 5. Provider adapter and secrets

Add a dedicated Alibaba adapter with an exact HTTPS Beijing workspace endpoint, fixed official REST path,
bounded Base64 PNG, response-size/timeout/concurrency limits and no automatic redirect. Settings use a
separate `SecretStr` API key and secret endpoint value; existing Zhipu configuration is untouched.

Committed defaults are disabled/provider-free. The existing local CSV is never read by application code and
never copied into Git, `.env.example`, images or task artifacts. A protected operator shell may export its
values into process environment for the explicitly authorized local indexing run.

## 6. Application integration and fallback

Add a service that obtains the canonical query vector and score map before `_prepare_image_input` invokes
the selector. The feature is enabled by a new flag and requires selector v2. On success, the selected
reference snapshot records safe semantic similarity, legacy rule score and ranking source.

On authentication, timeout, rate-limit, malformed output, identity mismatch or incomplete-index errors, the
service records only `semantic_unavailable` plus a closed reason code and invokes literal selector v1. It
does not retry inside one material attempt and never blocks image generation solely because semantic search
is unavailable.

## 7. Local operator and demo surface

Provide an explicit CLI to index the current approved catalog with bounded concurrency defaulting to one,
`--max-assets`, `--max-attempts 1`, dry-run/preflight and safe aggregate output. It never runs at API/worker
startup.

Add an internal bounded visual-search route for the personal-project demo. It accepts either short text or
one bounded PNG (not both), returns top safe references and scores, and uses the same repository. It exposes
no filename/path/bytes/vector/provider body/request ID. This route is not a factual-evidence source and has
no mutation beyond the provider query.

## 8. Rollback and compatibility

- Disable the feature flag and select selector v1 to restore byte-for-byte current selection behavior.
- New tables can remain unused; no existing row is rewritten.
- Migration 0025 downgrade removes only the normalized-input columns after confirming no v2 rows remain; 0024
  continues to own the visual-index tables.
- Never fall back across vector identities. Operational fallback is the deterministic non-vector v1 selector.

## 9. Validation strategy

- Domain tests: hard barriers, semantic-primary order, stable ties, v1 snapshots, missing/partial score map.
- Adapter contract tests: exact payload, text/image inputs, 2048 finite values, omitted/mismatched model,
  malformed/oversized responses, safe errors and zero retry.
- PostgreSQL tests: idempotent indexing, lease ownership, derivation splits, complete-index proof, cosine
  order, provider/model/policy exclusion and no-write queries.
- Application tests: direct v2 selection when healthy and exact v1 fallback with `semantic_unavailable`.
- API/CLI tests: privacy, bounds, aggregate-only output and no provider in default tests.
- Deterministic eval: sanitized mini-catalog with text/image/synonym/unrelated/tie/failure cases.
- One final explicitly approved local live run indexes all 41 approved assets under input-policy v2, followed by
  aggregate-only complete-index and retrieval checks. Each v2 asset gets at most one request. No other private
  material is sent, and historical v1 vectors remain isolated.
