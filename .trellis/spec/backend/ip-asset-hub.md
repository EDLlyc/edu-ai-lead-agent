# IP Digital Asset Hub

## Scenario: One no-auth intranet library for dynamic IP images

### 1. Scope / Trigger

Use this contract whenever code changes the Sai Xiansheng / Xiao Sai shared image library: upload,
classification, canonical naming, gallery/search, preview/download, dynamic embeddings, seed import,
or image-generation-to-library work.

The hub is one company-intranet library. It has no login, verified uploader, approval workflow,
department isolation, delete action, or public-sharing contract. `department` and `contributor` are
self-reported labels only. Committed defaults keep the feature disabled, and public-Internet
deployment is forbidden until a separate authenticated design is approved.

This dynamic library is not the immutable approved `VisualAssetCatalog`. Reuse the fixed visual
embedding adapter and normalization policy, but never weaken or reuse the static catalog's
complete-index proof. Dynamic search filters exact compatible rows and tolerates partial coverage.

### 2. Signatures

#### HTTP API

All routes live under `/api/v1/ip-assets`:

```text
GET  /capabilities
GET  /?query=&character=&asset_type=&department=&source_kind=&orientation=&tag=&cursor=&limit=
POST /                         multipart file + required character + required asset_type + metadata
POST /recognitions             transient multipart image -> advisory upload-field suggestions
GET  /{asset_ref}
GET  /{asset_ref}/preview
GET  /{asset_ref}/download
POST /downloads               {asset_refs: string[]}
POST /search/text              bounded message, prior_turns, filters, limit
POST /search/image             transient multipart image + filters
POST /generations              prompt, character, asset_type, optional reference, idempotency_key
GET  /generations/{job_ref}
```

Upload accepts only verified PNG/JPEG/WebP up to 25 MiB, maximum edge 8192, and maximum 32 million
decoded pixels. Generation is the existing provider's proved `1:1`/1024x1024 contract.

#### Database

Alembic `20260824_0031` adds:

```text
ip_assets
ip_asset_tags
ip_asset_derivatives
ip_asset_embedding_jobs
ip_asset_embeddings      vector(2048)
ip_asset_generation_jobs
```

`ip_assets.blob_sha256` is globally unique. `(naming_key, name_version)` is unique. Embeddings bind
asset/source checksum plus exact provider/model/dimension/input-policy identity. Generation jobs
bind unique idempotency key and request fingerprint.

#### Commands

```bash
make ip-asset-worker
make ip-asset-import-dry-run MAX_ASSETS=500
make ip-asset-stack-up
make ip-asset-ui
```

`python -m app.ip_asset_import_main` is explicit and dry-run capable. It must never modify source
manifest files.

### 3. Contracts

#### Environment

| Key                                       | Contract                                                                             |
| ----------------------------------------- | ------------------------------------------------------------------------------------ |
| `IP_ASSET_HUB_ENABLED`                    | Default `false`; gates API service availability                                      |
| `IP_ASSET_WORKER_ENABLED`                 | Default `false`; requires hub enabled                                                |
| `IP_ASSET_GENERATION_ENABLED`             | Default `false`; requires hub and configured image provider                          |
| `IP_ASSET_RECOGNITION_ENABLED`            | Default `false`; requires hub plus configured Zhipu HTTPS endpoint and credential    |
| `IP_ASSET_RECOGNITION_MODEL`              | Bounded reviewed vision-model identity; default `glm-4.1v-thinking-flash`            |
| `IP_ASSET_RECOGNITION_TIMEOUT_SECONDS`    | One bounded synchronous suggestion window, maximum 180 seconds                       |
| `IP_ASSET_RECOGNITION_CONCURRENCY`        | Provider-side recognition concurrency bound `1..4`                                   |
| `IP_ASSET_RECOGNITION_MAX_REQUEST_BYTES`  | Maximum serialized provider request bytes; bounded 1..32 MiB                         |
| `IP_ASSET_RECOGNITION_MAX_RESPONSE_BYTES` | Maximum streamed provider response bytes; bounded 16 KiB..4 MiB                      |
| `IP_ASSET_POLL_SECONDS`                   | Bounded worker idle poll interval                                                    |
| `IP_ASSET_WORKER_CONCURRENCY`             | Bounded `1..4`                                                                       |
| `IP_ASSET_LEASE_SECONDS`                  | Bounded lease; heartbeat must be shorter                                             |
| `IP_ASSET_MAX_ATTEMPTS`                   | Bounded `1..6`                                                                       |
| `IP_ASSET_UPLOAD_CONCURRENCY`             | Shared upload/image-query memory concurrency bound                                   |
| `APP_BROWSER_ORIGINS`                     | Comma-separated exact HTTP(S) origins; no `*`, credentials, path, query, or fragment |

Local Vite defaults to `http://127.0.0.1:5173`; the API is normally
`http://127.0.0.1:8000`. CORS must allow only configured exact origins, methods
`GET`/`POST`/`OPTIONS`, and required content/idempotency headers. Prefer same-origin reverse proxy
for intranet deployment.

#### Identity, naming, and storage

- Browser identity is `ipa_<20 lowercase hex>`. Full database UUID, checksum, bucket, object key,
  provider body/request ID, vector, credential, and filesystem path never appear in list/search.
- Required taxonomy is controlled `character` plus `asset_type`; optional metadata is normalized
  and bounded.
- Canonical display names are semantic and versioned, for example
  `小赛-表情包-开心-科学课堂-方图-v001`. Storage identity never depends on a filename.
- Originals are immutable under the exact key
  `ip-assets/originals/sha256/{sha256[:2]}/{sha256}.{ext}`. Existing objects are read back and
  byte/checksum verified; metadata alone is not proof.
- Raster validation rejects signature/media mismatch, decompression bombs, dimension/pixel/byte
  overflow, malformed decodes, and trailing payload after the canonical PNG/JPEG/WebP end.
- Exact SHA-256 replay returns the existing asset. Perceptual near duplicates warn but do not block.

#### Jobs and fencing

- API requests enqueue durable work; provider calls remain outside database transactions.
- Embedding failure changes only semantic status. The verified asset stays conventionally browsable,
  previewable, and downloadable.
- When an embedding-capable worker starts, it atomically and idempotently enqueues at most 500
  `ready` assets whose semantic status is `unavailable` and which have no embedding job. This is the
  supported activation backfill; enabling semantics after an earlier provider-free upload must not
  leave those assets permanently undiscoverable by vectors or create duplicate jobs.
- Generation completion is one lease-fenced repository transaction: verify the current lease,
  create or reuse the exact output asset, link it, and mark the job succeeded atomically.
- A stale/expired worker must not publish an asset. Heartbeat loss cancels the provider task when
  possible and fences all persistence.
- Concurrent replay recovers from uniqueness conflicts by loading the matching row; the same
  idempotency key with a different fingerprint is a conflict, never a 500 or silent reuse.
- The generation fingerprint includes prompt, taxonomy, ratio, reference checksum, provider/model,
  department, and contributor so distinct descriptive inputs cannot alias.

#### Search and content delivery

- Conventional gallery search is stable keyset pagination over metadata/keywords.
- Text search uses the versioned `ip-asset-hybrid-v2` policy. It merges compatible `vector(2048)`
  hits with a bounded, structure-filtered pool of at most 500 metadata candidates, weights exact
  safe metadata evidence above cosine similarity, and applies deterministic timestamp/ID ties. One
  vector hit must never hide relevant assets whose embedding is missing or failed.
- Explicit request filters are authoritative. Only the current conversation turn may infer missing
  taxonomy/orientation filters; prior turns remain semantic context and cannot reintroduce a stale
  role or type. A generic “transparent background” phrase stays lexical unless the user explicitly
  asks for a transparent-cutout asset type.
- Metadata ranking covers canonical name, safe original filename, department, contributor,
  emotion, action, scene, intended use, style, and tags. Explanations may state that an original
  filename matched but never copy that detail-only filename into the search response.
- Invalid image-query bytes are rejected even when semantic search is disabled. Valid image-query
  bytes are transient and never persisted.
- Semantic/provider failure returns explicit `degraded_metadata` results rather than breaking normal
  library use.
- Preview/download read the immutable object through verified storage and return bounded content,
  media type, length, ETag, private/no-store cache policy, and safe disposition.
- ZIP download is bounded by count and aggregate bytes and contains verified originals plus a UTF-8
  manifest.

#### Advisory upload recognition

- Selecting a file and rendering its local preview never calls a provider. Recognition begins only
  after an explicit `POST /recognitions` caused by the user's “AI 辅助识别” action.
- The endpoint reuses upload signature/media/dimension/pixel/trailing-payload validation, then
  re-encodes pixels without source filename or metadata into a maximum-1568-edge, maximum-8-MiB
  PNG/JPEG provider input. Source bytes remain transient.
- A provider-neutral `IpAssetRecognitionModel` owns the call. The configured Zhipu adapter uses one
  bounded attempt, an HTTPS endpoint, a fixed allowlisted JSON projection, and a prompt that treats
  image text as untrusted data. Unknown keys/labels, reasoning, prose, prompt content, raw provider
  bodies/request IDs, paths, credentials, fingerprints, and image bytes never enter the API result
  or durable state.
- The response may suggest only controlled `character`/`asset_type` plus bounded emotion, action,
  scene, intended use, style, and tags. It never supplies department, contributor, approval,
  ownership, rights, or application-invented confidence.
- Recognition creates no asset, object, row, job, chat turn, or history. Suggestions remain editable
  browser form values; only a later ordinary upload can make user-confirmed metadata durable.
- Disabled configuration, provider rejection/timeout/unavailability, and invalid output are safe,
  typed failures independent from manual upload. Capability is true only when the hub, recognition
  flag, and runtime service are all available.

### 4. Validation & Error Matrix

| Condition                                                                 | Required result                                                                            |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Hub disabled                                                              | Typed conflict/capability-disabled response; no repository/storage/provider work           |
| Recognition disabled or runtime adapter absent                            | `recognition_available=false`; typed unavailable response and manual upload remains usable |
| File selected or locally previewed without explicit recognition action    | No provider request and no durable state                                                   |
| Recognition raster invalid or exceeds validation/normalization bounds     | Typed rejection before provider work; no durable state                                     |
| Recognition provider timeout/rejection/unavailability or invalid JSON     | Safe typed error; no raw provider content and no durable state                             |
| Recognition returns extra keys, department/contributor, or unknown enums  | Discard unsafe extras or reject the suggestion; never make them durable                    |
| Missing/blank required taxonomy                                           | Request validation error; no object or row                                                 |
| Unsupported, malformed, trailing-payload, oversized, or pixel-bomb raster | Typed upload/query rejection; no durable state                                             |
| Exact duplicate upload                                                    | Existing asset, `duplicate=true`, no second original/asset                                 |
| Existing MinIO key has wrong bytes/metadata/path                          | Conflict; never trust or overwrite it                                                      |
| Semantic provider disabled/unavailable                                    | `degraded_metadata`; gallery/filter/download remain usable                                 |
| Only part of the library has compatible vectors                           | Merge vector and metadata hits; do not hide unindexed relevant assets                      |
| Semantics enabled after provider-free uploads                             | Worker startup creates one bounded job per eligible unavailable asset; replay creates zero |
| Prior turn conflicts with the current role/type                           | Current turn wins unless an explicit request filter already owns that dimension            |
| Embedding identity mismatch                                               | Exclude incompatible vector and record typed failure                                       |
| Same idempotency key, different generation fingerprint                    | Conflict; no second provider job                                                           |
| Concurrent identical enqueue                                              | One durable job; both callers receive its safe identity                                    |
| Lease expires while provider runs                                         | Cancel/fence; no output asset or success transition                                        |
| Generated raster invalid                                                  | Typed terminal/retry-classified failure; no asset                                          |
| Unlisted browser origin sends preflight                                   | No allow-origin header                                                                     |
| Downgrade while hub data exists                                           | Refuse; never silently delete shared assets                                                |

### 5. Good / Base / Bad Cases

- Good: a colleague asks for a happy Xiaosai image, receives exact emotion/scene matches before weak
  vector-only matches, changes the next turn to Sai Xiansheng without retaining stale Xiaosai
  filters, and downloads the exact verified original.
- Base: provider features are disabled. Upload, metadata search, preview, individual/ZIP download,
  and dry-run import still work; semantic and generation surfaces explain their unavailable state.
- Bad: one indexed asset suppresses dozens of metadata-relevant unindexed assets, a prior Xiaosai
  turn overrides the current Sai Xiansheng request, or worker restarts create duplicate jobs.
- Good recognition: selecting an image stays local; one explicit recognition request returns
  allowlisted editable suggestions, and only the later ordinary upload persists user-confirmed data.
- Base recognition: the adapter is disabled or times out; the selected file and manual upload path
  remain usable without repository, MinIO, or job work.
- Bad recognition: file selection silently calls the provider, raw model output reaches the API, or
  a suggestion creates or classifies an asset without a separate user upload.

### 6. Tests Required

- Unit/API: PNG/JPEG/WebP decode, signature mismatch, trailing payload, limits, metadata/tags,
  canonical names, duplicate result, safe projections, preview/download/ZIP headers and privacy,
  invalid image query with semantics disabled, CORS OPTIONS allow/deny, and feature defaults.
- Recognition unit/API: safe-off/fail-closed configuration, transient raster normalization,
  explicit endpoint invocation, strict enum/tag projection, prompt-injection/reasoning/raw-body
  exclusion, provider timeout/invalid-output translation, capability projection, and proof that no
  repository, MinIO, or job boundary is touched. Automated tests use only fake/mock transports;
  live vision acceptance requires separate authorization and a non-sensitive image.
- Real PostgreSQL/pgvector: migration/model parity, dedupe, concurrent naming/enqueue, keyset order,
  tag filters, compatible vector isolation/order, idempotency conflicts, lease expiry/heartbeat loss,
  atomic generation completion, concurrent/idempotent unavailable-asset backfill, and downgrade
  refusal with data.
- Search unit/live-corpus: assert metadata-only hits merge with partial vector results, exact
  emotion/action/scene evidence outranks weak cosine-only hits, explicit filters beat inferred
  terms, the current turn beats conflicting history, safe keyword fields remain searchable without
  filename leakage, and ordering is deterministic.
- Real MinIO: new and pre-existing put-or-verify reads exact bytes; wrong metadata/body/key fails;
  preview/download never return object locations.
- Fake provider: one successful generated asset, retryable/terminal failure classification,
  cancellation/fencing, retry exhaustion, and generation-disabled independence.
- CLI: dry run reads no source bytes, live import is checksum-idempotent, invalid sources are bounded,
  second replay creates zero assets, and source files/manifest stay byte-identical.
- Final gates: focused hub tests, `make backend-check`, `make frontend-check`, migration/Doctor,
  OpenAPI drift, Compose render, scoped privacy scan, and `git diff --check`. Concurrent unrelated
  worktree failures must be identified rather than silently attributed to this feature.

### 7. Wrong vs Correct

#### Wrong

```python
# Provider returned bytes, so publish the asset before proving the worker still owns the lease.
asset = await repository.create_asset(upload)
await repository.complete_generation(claim, asset.id)
```

#### Correct

```python
# One repository transaction fences the lease, creates/reuses the exact asset, links it, and succeeds.
asset = await repository.complete_generation_asset(
    claim=claim,
    upload=validated_output,
    descriptor=verified_private_object,
    metadata=metadata,
    semantic_enabled=semantic_enabled,
)
```

#### Wrong

```python
stat = minio.stat_object(bucket, key)
if stat.metadata["sha256"] == expected:
    return descriptor
```

#### Correct

```python
stored = minio.get_object(bucket, exact_content_addressed_key)
assert len(stored) == descriptor.byte_size
assert sha256(stored).hexdigest() == descriptor.sha256
```

#### Wrong

```python
# A single compatible vector hides every relevant asset that has not been indexed yet.
return semantic_hits if semantic_hits else metadata_hits
```

#### Correct

```python
# Preserve authoritative filters and merge partial semantic coverage with bounded metadata evidence.
metadata_hits = await search_metadata(current_turn, explicit_or_inferred_filters)
return merge_hybrid_v2(semantic_hits, metadata_hits, stable_ties=("created_at", "asset_id"))
```

#### Wrong

```python
# File selection or durable upload implicitly delegates classification authority to the provider.
suggestion = await vision_model.suggest(raw_upload)
return await repository.create_asset(metadata=suggestion)
```

#### Correct

```python
# The explicit transient endpoint returns advisory values only; the ordinary upload stays separate.
normalized = normalize_ip_asset_recognition_request(validated_upload)
return project_allowlisted_suggestion(await recognition_model.suggest(normalized))
```

## Design decision: dynamic partial index remains separate

The approved static visual catalog requires complete current-catalog coverage before semantic
ranking because it supplies identity-critical generation references. A continuously uploaded shared
library cannot preserve that invariant without disabling all search after every upload. Therefore
the hub owns separate tables/repository semantics, reuses only fixed embedding/normalization
identity, and degrades per row/provider rather than per catalog.
