# IP Digital Asset Hub

## Scenario: One no-auth intranet library for dynamic IP images

### 1. Scope / Trigger

Use this contract whenever code changes the Sai Xiansheng / Xiao Sai shared image library: upload,
classification, canonical naming, gallery/search, browser-local personal collections, favorites,
download ranking, preview/download, dynamic embeddings, seed import, or image-generation-to-library
work, including the local API/UI/worker lifecycle used to exercise those capabilities.

The hub is one company-intranet library. It has no login, verified uploader, approval workflow,
department isolation, delete action, or public-sharing contract. A browser-local random profile
token groups favorites, uploads, and generated assets but is not authentication or recoverable
identity. `department` and `contributor` are self-reported labels only. Committed defaults keep the
feature disabled, and public-Internet deployment is forbidden until a separate authenticated design
is approved.

This dynamic library is not the immutable approved `VisualAssetCatalog`. Reuse the fixed visual
embedding adapter and normalization policy, but never weaken or reuse the static catalog's
complete-index proof. Dynamic search filters exact compatible rows and tolerates partial coverage.

### 2. Signatures

#### HTTP API

All routes live under `/api/v1/ip-assets`:

```text
GET  /capabilities
POST /profiles                   local token + display_name + department -> idempotent profile
GET  /profiles/me                restore local profile by token
GET  /profiles/me/assets         personal all/generated/uploaded/favorite collection
GET  /leaderboard?period=30d|all anonymous aggregate counts only
GET  /?query=&character=&asset_type=&department=&source_kind=&orientation=&tag=&cursor=&limit=
POST /                         multipart file + required character + required asset_type + metadata
POST /recognitions             transient multipart image -> advisory upload-field suggestions
GET  /{asset_ref}
GET  /{asset_ref}/thumbnail?v=1
GET  /{asset_ref}/preview
GET  /{asset_ref}/download
PUT  /{asset_ref}/favorite
DELETE /{asset_ref}/favorite
PUT  /{asset_ref}/shared         explicitly share an owned generated result
POST /downloads               {asset_refs: string[]}
POST /search/text              bounded message, prior_turns, filters, limit
POST /search/image             transient multipart image + filters
POST /generations              prompt, taxonomy, ordered 1..3 references, idempotency_key
GET  /generations/{job_ref}
```

Profile-aware routes use `X-IP-Profile-Token`. Optional-token routes ignore no profile and reject an
invalid supplied token. Required-token routes return the typed profile-setup-required response. The
raw token is never logged, returned, or persisted by the backend. Shared list, detail, and text/image
search accept the header optionally so the current browser receives an accurate `favorite` projection
without changing anonymous shared visibility.

Upload accepts only verified PNG/JPEG/WebP up to 25 MiB, maximum edge 8192, and maximum 32 million
decoded pixels. Generation is the existing provider's proved `1:1`/1024x1024 contract.

#### Database

Alembic `20260824_0031` adds the base hub. Current additive revision `20260824_0035` adds:

```text
ip_assets
ip_asset_tags
ip_asset_derivatives
ip_asset_embedding_jobs
ip_asset_embeddings      vector(2048)
ip_asset_generation_jobs
ip_asset_profiles
ip_asset_profile_memberships
ip_asset_favorites
ip_asset_generation_references
ip_asset_download_daily
```

`ip_assets.blob_sha256` is globally unique. `(naming_key, name_version)` is unique. Embeddings bind
asset/source checksum plus exact provider/model/dimension/input-policy identity. Generation
idempotency is scoped by profile (with a separate unique legacy-null path), the request fingerprint
includes the profile and ordered reference checksums, and reference rows preserve ordinals `0..2`.
`ip_assets.shared_at IS NULL` is private-to-membership; all historical assets are backfilled shared.

#### Commands

```bash
make ip-asset-worker                         # worker only; API/infrastructure already running
make ip-asset-import-dry-run MAX_ASSETS=500
make ip-asset-stack-up                       # API + one worker for a generation-capable local stack
make ip-asset-ui                             # start the standalone UI after the stack
make ip-asset-demo-preflight                 # read-only local demo readiness proof
```

`python -m app.ip_asset_import_main` is explicit and dry-run capable. It must never modify source
manifest files. When real IP generation is enabled, starting only the API and UI is an incomplete
local runtime: it can enqueue safely but cannot advance queued jobs. Start exactly one worker lane
with `make ip-asset-worker` when the existing API/infrastructure are already live, or use
`make ip-asset-stack-up` for a fresh generation-capable stack. The worker remains running after the
queue drains so later jobs are claimed automatically; do not start a second worker merely because
the current queue is idle.

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
`GET`/`POST`/`PUT`/`DELETE`/`OPTIONS`, and `Content-Type` plus `X-IP-Profile-Token`. Prefer same-origin
reverse proxy for intranet deployment.

#### Local runtime lifecycle

- `generation_available=true` proves that the API has an enabled provider adapter. It is not a
  worker heartbeat and does not prove queued jobs can advance.
- With `IP_ASSET_GENERATION_ENABLED=true`, the normal local platform lifecycle includes one
  `app.ip_asset_worker_main` lane alongside the API and UI. A durable `queued` row with no live
  worker is expected to remain safe and unchanged, not fail or trigger an inline API provider call.
- Start/restart recovery must reuse the durable queue. Never clone a job, call the provider directly,
  or edit job status to bypass claim, lease, heartbeat, idempotency, retry, or completion fencing.
- After startup, verify one effective worker child process, `generation_enabled=true`, and bounded
  concurrency. A `conda run` wrapper plus its Python child is one worker, not two lanes.
- Keep the worker alive after terminal completion. For authorized live recovery, monitor the exact
  pre-existing job refs to terminal state and verify success output/membership or failure integrity
  without logging credentials, provider bodies, full prompts, profile tokens, or object locations.

#### Identity, naming, and storage

- Asset browser identity is `ipa_<20 lowercase hex>`. A local profile has safe identity
  `ipp_<20 lowercase hex>` and is found from `sha256(decoded_random_token)`; only that digest is
  durable. The token is canonical unpadded base64url for exactly 32 random bytes. Full database UUID,
  raw profile token, checksum, bucket, object key,
  provider body/request ID, vector, credential, and filesystem path never appear in list/search.
- Required taxonomy is controlled `character` plus `asset_type`; optional metadata is normalized
  and bounded.
- Canonical display names are semantic and versioned, for example
  `小赛-表情包-开心-科学课堂-方图-v001`. Storage identity never depends on a filename.
- Originals are immutable under the exact key
  `ip-assets/originals/sha256/{sha256[:2]}/{sha256}.{ext}`. Existing objects are read back and
  byte/checksum verified; metadata alone is not proof.
- Gallery thumbnails use fixed policy `ip-asset-thumbnail-v1`: EXIF-normalized, metadata-free,
  non-upscaled WebP with maximum edge 640. The content-addressed object lives at
  `ip-assets/derivatives/ip-asset-thumbnail-v1/sha256/{sha256[:2]}/{sha256}.webp`; the existing
  derivative row binds source checksum, policy, dimensions, descriptor, and derivative checksum.
  Concurrent first reads converge on one verified row/object, and any mismatch is a conflict.
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
- The lease-locked generation row and its persisted ordered-reference rows are the completion source
  of truth. A worker claim is an execution snapshot only; completion must not derive profile
  membership, private/shared visibility, or reference lineage from stale claim fields.
- A stale/expired worker must not publish an asset. Heartbeat loss cancels the provider task when
  possible and fences all persistence.
- Concurrent replay recovers from uniqueness conflicts by loading the matching row; the same
  idempotency key with a different fingerprint is a conflict, never a 500 or silent reuse.
- The generation fingerprint includes profile identity, prompt, taxonomy, ratio, every ordered
  `(asset_ref, source_checksum)` pair, provider/model, department, and contributor so reordered or
  identity-distinct references cannot alias even when blobs are byte-identical. New API jobs require
  one to three distinct, ready, shared references. The legacy single-reference field remains
  input-compatible but may not be combined with the ordered field.
- A profile-owned generated output completes as `shared_at=NULL` and gets one generated membership
  in the same fenced transaction. It becomes shared only through an explicit owner action. Legacy
  profile-less worker jobs retain the historical shared-output behavior.
- Completion enqueues semantic indexing only when it inserts a new output asset and must do so
  independently of whether the job has a profile. Reusing an exact-byte asset creates the required
  membership/job link but never creates a duplicate embedding job.

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
- Numeric cosine remains in the typed API for compatibility and diagnostics, but the demo UI does
  not present it as calibrated confidence. Explanations use `画面语义相关` whenever vector evidence
  exists, including semantic-only hits, while exact metadata reasons remain explicit.
- Invalid image-query bytes are rejected even when semantic search is disabled. Valid image-query
  bytes are transient and never persisted.
- Semantic/provider failure returns explicit `degraded_metadata` results rather than breaking normal
  library use.
- Preview/download read the immutable original through verified storage and return bounded content,
  media type, length, ETag, private/no-store cache policy, and safe disposition. The versioned
  thumbnail route uses the same shared-or-owned access check, returns `image/webp`, a strong ETag,
  `Cache-Control: private, max-age=604800, immutable`, and `Vary: X-IP-Profile-Token`, and never
  increments download aggregates.
- ZIP download is bounded by count and aggregate bytes and contains verified originals plus a UTF-8
  manifest.
- Every media, download, favorite, share, and generation-reference path first requires
  `status='ready'`. Access reads then use `(shared_at IS NOT NULL) OR owned-membership`; public
  gallery/search/vector/reference paths always require shared rows. A favorite is an annotation,
  never an access grant: favorite-backed personal queries must still join a shared row or an owned
  membership, including when legacy/orphan favorite rows exist.
- Download counters increment only after every requested body is prepared successfully. One request
  counts each shared asset once, stores only `(asset_id, business_date, count)`, and never stores an
  actor/profile/IP/UA/event row. The `30d` window is the exact inclusive interval
  `[today - 29 days, today]` in the configured IANA timezone and therefore excludes future-dated
  aggregates; `all` has no date bound.

#### Migration rollback

- `0035 -> 0034` is permitted only when all profile/personal/ranking state is empty and every
  ordered reference is exactly the legacy ordinal-zero reference. The downgrade must refuse before
  dropping anything when profiles, profile-linked jobs, private assets, download aggregates,
  non-legacy reference order/identity, or duplicate cross-profile idempotency keys would lose data
  or violate the restored global constraint.

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

| Condition                                                                  | Required result                                                                            |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Hub disabled                                                               | Typed conflict/capability-disabled response; no repository/storage/provider work           |
| Recognition disabled or runtime adapter absent                             | `recognition_available=false`; typed unavailable response and manual upload remains usable |
| File selected or locally previewed without explicit recognition action     | No provider request and no durable state                                                   |
| Thumbnail derivative missing                                               | Derive from the verified original and converge on one versioned row/object                 |
| Thumbnail source/descriptor/policy differs from the immutable source       | Conflict; never serve or silently replace the mismatched derivative                        |
| Shared and profile-scoped thumbnail responses share a browser cache        | Separate by `Vary: X-IP-Profile-Token`; a token never becomes an access grant              |
| Recognition raster invalid or exceeds validation/normalization bounds      | Typed rejection before provider work; no durable state                                     |
| Recognition provider timeout/rejection/unavailability or invalid JSON      | Safe typed error; no raw provider content and no durable state                             |
| Recognition returns extra keys, department/contributor, or unknown enums   | Discard unsafe extras or reject the suggestion; never make them durable                    |
| Missing/blank required taxonomy                                            | Request validation error; no object or row                                                 |
| Unsupported, malformed, trailing-payload, oversized, or pixel-bomb raster  | Typed upload/query rejection; no durable state                                             |
| Exact duplicate upload                                                     | Existing asset, `duplicate=true`, no second original/asset                                 |
| Existing MinIO key has wrong bytes/metadata/path                           | Conflict; never trust or overwrite it                                                      |
| Semantic provider disabled/unavailable                                     | `degraded_metadata`; gallery/filter/download remain usable                                 |
| Only part of the library has compatible vectors                            | Merge vector and metadata hits; do not hide unindexed relevant assets                      |
| Semantics enabled after provider-free uploads                              | Worker startup creates one bounded job per eligible unavailable asset; replay creates zero |
| Prior turn conflicts with the current role/type                            | Current turn wins unless an explicit request filter already owns that dimension            |
| Embedding identity mismatch                                                | Exclude incompatible vector and record typed failure                                       |
| Same idempotency key, different generation fingerprint                     | Conflict; no second provider job                                                           |
| Missing/invalid local profile token on a required route                    | Typed setup-required response; no private data or provider work                            |
| Ordered generation references empty, duplicated, over three, or not shared | Typed rejection; no generation job                                                         |
| One reference changes order or checksum                                    | Distinct request fingerprint and immutable reference rows                                  |
| Worker claim profile/reference differs from the locked job row             | Persist using the locked row; stale claim metadata grants no visibility or membership      |
| Non-owner favorites or shares a private result                             | Not found/conflict; no visibility or ownership change                                      |
| Favorite row exists without shared visibility or owned membership          | Exclude from personal results; do not load media                                           |
| Direct/ZIP download preparation fails                                      | No aggregate increment                                                                     |
| Future-dated aggregate exists during a `30d` query                         | Exclude it; include only `[today - 29 days, today]`                                        |
| Concurrent identical enqueue                                               | One durable job; both callers receive its safe identity                                    |
| Generation configured but no worker is live                                | Job remains durably `queued`; API/UI stay responsive and make no inline provider call      |
| Local generation-capable platform starts                                   | Start exactly one worker lane and confirm generation-enabled startup before accepting work |
| Queue drains while the local platform remains in use                       | Worker stays alive and polls idly for later jobs; do not launch another worker             |
| Lease expires while provider runs                                          | Cancel/fence; no output asset or success transition                                        |
| Generated raster invalid                                                   | Typed terminal/retry-classified failure; no asset                                          |
| Unlisted browser origin sends preflight                                    | No allow-origin header                                                                     |
| Downgrade while hub data exists                                            | Refuse; never silently delete shared assets                                                |

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
- Good personal flow: a browser creates an unverified local profile, a generated result appears only
  on its personal shelf, can be favorited/downloaded there, and enters the shared gallery only after
  the explicit share action.
- Bad personal flow: the raw token is stored or placed in a query key/log, a favorite grants private
  access, generated output is shared automatically, or ranking stores per-download actor events.
- Good local operation: API, UI, PostgreSQL, MinIO, and one generation-enabled worker start together;
  queued jobs reach durable terminal states and the same worker remains available after the queue
  drains.
- Good demo media: the first gallery page requests at most sixteen versioned WebP thumbnails, then
  refresh reuses the private immutable browser cache while detail/flipbook/download retain originals.
- Base local operation: API and UI are live without a worker; submission remains safely queued and
  the UI truthfully says it awaits the independent service.
- Bad local operation: report provider availability as worker liveness, start a second lane for an
  idle queue, manually rewrite a queued row, or call the provider outside the durable worker.

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
- Personal-library integration: canonical token digest/idempotent bootstrap, upload membership,
  ordered 1..3 reference persistence, profile-scoped replay, private completion, owner-only access,
  explicit share, favorite semantics, anonymous daily upsert, 30-day/all ranking, and clean
  `0035 -> 0034` downgrade when the new state is empty.
- Adversarial personal-library regression: orphan favorite rows do not expose private assets;
  future-dated aggregates do not enter `30d`; stale claim profile/reference fields cannot override
  the lease-locked job; a legacy profile-less generation still enqueues a new output embedding; an
  exact-byte output reuse does not enqueue another embedding; and `0035 -> 0034` refuses before any
  destructive change whenever new personal/private/ranking/multi-reference state exists.
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
- Thumbnail unit/integration/API: deterministic <=640 WebP, alpha preservation, no upscale, exact
  derivative-key verification, concurrent first-read convergence in real PostgreSQL/MinIO, source
  mismatch rejection, shared/private access, strong ETag, one-week private immutable caching,
  `Vary`, generated OpenAPI `image/webp`, and no download-count mutation.
- Demo preflight: loopback-only URLs without credentials, exactly one effective worker, healthy
  PostgreSQL/MinIO, sixteen ready gallery cards, WebP signature/cache/ETag/`Vary`, and one bounded
  semantic search of at most eight results. It creates no business asset/profile/favorite/download/
  generation state; first thumbnail access may materialize only its deterministic derivative cache.
- Local live recovery (explicitly authorized only): snapshot exact queued refs/counts, prove no
  worker exists, start one supported lane, observe generation-enabled startup, and verify each
  authorized job reaches terminal state. Success requires one ready output and one matching
  generated membership; failure requires no output/membership and only a safe error code. Verify
  zero queued/running rows, no duplicate job fingerprints/idempotency identities, one surviving
  worker lane, and healthy API/PostgreSQL/MinIO without issuing an extra provider request.
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

#### Wrong

```bash
# API + UI advertise generation capability, but no process can claim the durable queue.
make acquisition-api
make ip-asset-ui
```

#### Correct

```bash
# Fresh local generation stack: API and exactly one worker, then the standalone UI.
make ip-asset-stack-up
make ip-asset-ui

# If API/PostgreSQL/MinIO are already running, start only the missing worker once.
make ip-asset-worker
```

#### Wrong

```python
# A gallery card reloads the multi-megabyte original on every visit.
thumbnail_url = f"/api/v1/ip-assets/{asset_ref}/preview"
```

#### Correct

```python
# Cards use the versioned derivative; original preview/download paths remain unchanged.
thumbnail_url = f"/api/v1/ip-assets/{asset_ref}/thumbnail?v=1"
headers = {
    "Cache-Control": "private, max-age=604800, immutable",
    "Vary": "X-IP-Profile-Token",
}
```

## Design decision: dynamic partial index remains separate

The approved static visual catalog requires complete current-catalog coverage before semantic
ranking because it supplies identity-critical generation references. A continuously uploaded shared
library cannot preserve that invariant without disabling all search after every upload. Therefore
the hub owns separate tables/repository semantics, reuses only fixed embedding/normalization
identity, and degrades per row/provider rather than per catalog.
