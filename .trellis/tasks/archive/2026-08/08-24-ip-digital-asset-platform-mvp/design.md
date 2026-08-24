# Technical Design: IP Digital Asset Sharing Platform MVP

## 1. Architecture and boundaries

The feature is an additive vertical slice inside the existing FastAPI + React application:

```text
React IP Asset Hub
  -> generated OpenAPI client
  -> FastAPI /api/v1/ip-assets
      -> IpAssetService / IpAssetSearchService / IpAssetGenerationService
          -> PostgreSQL + pgvector (metadata, states, compatible embeddings, jobs)
          -> private MinIO (immutable originals and bounded derivatives)
          -> existing VisualEmbeddingModel adapter
          -> existing ImageGenerator adapter
          -> bounded Zhipu vision adapter for transient upload suggestions
  -> dedicated IP asset worker claims embedding and generation jobs
```

The new library is deliberately separate from the immutable
`brand-visual-assets-v2` manifest/catalog domain. Shared low-level safety and provider primitives may
be extracted only when doing so preserves the old behavior and test suite.

Committed defaults disable the entire feature. An intranet deployment enables it explicitly and
serves the SPA/API same-origin or through an explicit intranet-origin allowlist.

## 2. Domain model

### 2.1 Asset identity

- `asset_id`: UUID primary key, never derived from a filename.
- `asset_ref`: short opaque browser identifier derived/stored independently from object locations.
- `blob_sha256`: full unique checksum for exact deduplication and verified reads; never returned in
  ordinary list/search responses. Detail/download may return an ETag or bounded checksum ref.
- `canonical_name`: Unicode display name generated from controlled metadata.
- `canonical_slug`: safe ASCII/Pinyin-like or enum-based download stem; it does not identify storage.
- `name_version`: transactionally allocated within a normalized naming key.
- `variant_group_id` / `parent_asset_id`: optional linkage for generated or manually uploaded variants.

### 2.2 Controlled taxonomy

Store the required `character` and `asset_type` as enums. Store secondary controlled dimensions in a
normalized `ip_asset_tags` table with `(asset_id, dimension, value)` uniqueness. Free tags use the
`free` dimension and bounded safe values. This prevents a single unstructured tag bag from becoming
the source of truth while allowing departments to add vocabulary incrementally.

The initial controlled values are:

| Dimension    | Initial values / behavior                                                                                                                                        |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| character    | `sai_xiansheng`, `xiao_sai`, `duo`, `other`                                                                                                                      |
| asset_type   | `identity_reference`, `portrait_avatar`, `full_body_action`, `expression`, `meme_sticker`, `transparent_cutout`, `scene_illustration`, `poster_element`, `other` |
| emotion      | bounded allowlist plus optional free tags                                                                                                                        |
| action       | bounded allowlist plus optional free tags                                                                                                                        |
| scene        | science classroom, event, social/community, festival, office, neutral, other                                                                                     |
| intended_use | avatar, emoji, article, poster, social post, presentation, generation reference, other                                                                           |
| style        | 3D, flat, line, realistic, sticker, brand default, other                                                                                                         |
| background   | transparent, solid, scene, unknown                                                                                                                               |
| orientation  | square, portrait, landscape, derived from dimensions                                                                                                             |
| provenance   | uploaded, generated, seed import                                                                                                                                 |

Department and contributor remain bounded descriptive strings because no authenticated identity
exists. They must be labeled “self-reported” in API descriptions and the UI.

### 2.3 Canonical naming

The service creates a normalized naming key from required and supplied controlled segments, then
allocates `name_version` under a database uniqueness constraint:

```text
display: {角色}-{类型}-{情绪或动作}-{场景或用途}-{规格}-vNNN
download: {character}-{asset_type}-{semantic-segments}-{format}-vNNN.{ext}
```

Optional empty segments are omitted. `format` is derived (`方图`, `竖图`, `横图`, optionally
`透明底`). A collision retries allocation inside a bounded transaction. Renaming storage objects is
never required.

## 3. Persistence

Add additive migrations for:

### `ip_assets`

- identity: UUID, opaque ref, checksum, safe original filename
- immutable raster descriptor: media type, byte size, width, height, alpha, private object key
- naming: key, canonical display name/slug, version
- core metadata: character, asset type, source kind, department/contributor labels
- lifecycle: `processing | ready | failed`, safe failure code, timestamps
- optional provenance: parent asset, variant group, generation job

`blob_sha256` is unique. Object keys remain internal-only and content addressed.

### `ip_asset_tags`

Normalized dimension/value records with indexes supporting filter joins and deterministic output.

### `ip_asset_derivatives`

Verified descriptors for thumbnails/previews, keyed by source checksum and derivative-policy
version. Originals remain untouched. The initial implementation may stream the original for full
preview and generate only one bounded gallery thumbnail.

### `ip_asset_embedding_jobs` and `ip_asset_embeddings`

Lease-safe durable job state plus one compatible `vector(2048)` row per asset and immutable
provider/model/dimension/input-policy/source-checksum identity. Search filters rows by the exact
active identity but does not require complete-library coverage.

### `ip_asset_generation_jobs`

Idempotency key/request fingerprint, bounded prompt, character/type/options, reference asset ref,
provider/model identity, job state/attempts/lease, safe error, and output asset ID. Raw provider
responses, secret values, transient URLs, and generated bytes are not stored in the row.

PostgreSQL owns durable states and uniqueness. MinIO owns immutable bytes. No filesystem path is
durable business state.

## 4. Upload and ingestion flow

```text
multipart upload
  -> bounded streaming read to temporary memory/spool
  -> signature/media/decode/dimension/pixel validation
  -> SHA-256 exact duplicate lookup
       -> existing: return existing asset + duplicate=true
       -> new: put-or-verify immutable MinIO object
  -> create asset + tags + naming version + ingestion/embedding job atomically
  -> return processing asset
  -> worker creates the compatible embedding (thumbnail derivatives are reserved for a later task)
  -> ready (or ready with semantic_unavailable when only embedding fails)
```

Object write/database failure handling must not leave an unreferenced mutable object. Because keys
are content addressed, a retry can safely put-or-verify; an unused immutable blob is recoverable by
offline reconciliation and never exposes data.

The base asset becomes `ready` once the original is verified and browser preview/download can be
served. Embedding failure is recorded separately and does not change the base asset to failed.

### 4.1 AI-assisted recognition before upload

Recognition is an explicit, transient form-assistance operation and remains separate from durable
asset ingestion:

```text
select local image
  -> browser preview only (no provider call)
  -> user clicks “AI 辅助识别”
  -> POST /ip-assets/recognitions with the selected raster
  -> existing raster safety validation + bounded model-input normalization
  -> IpAssetRecognitionModel.suggest() using configured Zhipu vision
  -> strict allowlisted JSON projection
  -> browser prefills editable upload fields and marks them as AI suggestions
  -> user edits/confirms and submits the existing POST /ip-assets request
```

The recognition response contains suggested `character`, `asset_type`, `emotion`, `action`,
`scene`, `intended_use`, `style`, and bounded tags plus provider/model capability identity and one
safe status. It contains no confidence invented by the application, department/contributor value,
raw model prose/reasoning, prompt, image bytes, provider request ID, fingerprint, path, or storage
descriptor. The user-confirmed upload payload remains the only durable classification authority.

The endpoint is synchronous and bounded because the result is needed only to populate the open
form; it creates no job, asset, database row, MinIO object, or chat history. It validates and
normalizes the transient raster before the provider call, uses one bounded attempt window, and
returns a typed unavailable/rejected/invalid-output state without clearing the selected file or
manual form values. The implementation defines a dedicated provider-neutral recognition port and
an async Zhipu adapter; it reuses the reviewed JSON/allowlist/security patterns from the offline
catalog annotator rather than importing that synchronous repository script into the application.

## 5. Retrieval design

### 5.1 Conventional query

`GET /ip-assets` uses keyset pagination and combines:

- exact enum/dimension filters;
- PostgreSQL full-text or bounded `ILIKE` search over canonical name, safe filename, department,
  contributor, and tag projection;
- stable `created_at DESC, asset_id DESC` or explicit supported sort.

### 5.2 Conversational text search

`POST /ip-assets/search/text` accepts a bounded current message plus bounded prior browser-session
turns. The server:

1. normalizes the conversation and deterministically extracts recognized controlled vocabulary;
2. applies explicit structured filters as authoritative constraints;
3. creates one text embedding with the current `VisualEmbeddingIdentity`;
4. retrieves compatible ready vectors with cosine distance;
5. blends semantic score with exact metadata/text matches under a versioned ranking policy;
6. returns safe asset cards and short deterministic match explanations.

A generative chat model is not required for the first release. The chat metaphor provides iterative
search; the browser supplies recent turns, while the server remains stateless about identity/history.

### 5.3 Image similarity search

`POST /ip-assets/search/image` accepts one bounded PNG/JPEG/WebP. It decodes and normalizes the image
through the same active embedding-input policy, calls the existing adapter, and never persists query
bytes. Structured filters may accompany the image.

### 5.4 Degraded behavior

If semantic retrieval is unavailable, the service returns `degraded_metadata` with lexical/filter
results and a safe reason enum. Missing embeddings exclude only those rows from semantic candidates;
they remain discoverable conventionally. This differs intentionally from the static catalog's
complete-index proof.

## 6. API surface

Suggested additive routes, all under `/api/v1/ip-assets`:

| Method/path                  | Purpose                                     |
| ---------------------------- | ------------------------------------------- |
| `GET /`                      | Cursor-paginated gallery/filter search      |
| `POST /`                     | Multipart upload and metadata               |
| `POST /recognitions`         | Transient AI upload-field suggestions       |
| `GET /{asset_ref}`           | Safe detail metadata                        |
| `GET /{asset_ref}/preview`   | Verified inline raster stream               |
| `GET /{asset_ref}/download`  | Verified immutable original attachment      |
| `POST /downloads`            | Bounded ZIP for selected refs plus manifest |
| `POST /search/text`          | Conversational semantic + structured search |
| `POST /search/image`         | Similar-image semantic + structured search  |
| `POST /generations`          | Idempotent durable generation enqueue       |
| `GET /generations/{job_ref}` | Safe generation status/output ref           |

Responses use generated Pydantic/OpenAPI contracts. No response exposes object keys, private URLs,
full checksums in list/search, vectors, provider request IDs, or verified-uploader claims.

## 7. Generation flow

```text
creation form
  -> validate prompt/options/reference asset
  -> create idempotent generation job
  -> dedicated IP asset worker claims job
  -> verified reference bytes loaded from MinIO
  -> existing ImageGenerator.generate()
  -> validate provider result
  -> content-addressed put-or-verify
  -> create generated ip_asset + tags + canonical name
  -> enqueue embedding/thumbnail work
  -> generation job links output asset
```

The initial UI requests one output per job and at most one reference asset, matching the narrowest
existing provider path. The MVP exposes only the existing `1:1` / 1024×1024 output contract;
additional ratios require a later provider-port change and must not be accepted then silently
ignored. Variants are separate assets linked to a shared variant group.

## 8. Frontend experience

Create `frontend/src/features/ip-assets/` as a standalone lazy page at `/ip-assets`; do not compose it
inside the shared Brand Knowledge development console at `/`. `Application.tsx` owns a deterministic
three-way pathname boundary (`console | ip-assets | not-found`). The primary surface contains:

- a compact header that visibly states `公司内网 · 无登录`, using a calm warm-neutral enterprise
  library language rather than an industrial console;
- a chat-like search bar and optional similar-image control in one compact search surface;
- horizontal primary filters with secondary filters behind progressive disclosure;
- an accessible responsive asset grid with processing/degraded states;
- a full-width gallery as the dominant page surface, with semantic match explanations kept on their
  cards;
- a detail drawer with metadata, full preview, individual download, and “use as reference”;
- a multi-select download tray;
- upload and creation drawers opened from explicit actions, with progressive disclosure and clear
  validation feedback instead of persistent form columns.

After a valid image is selected, the upload drawer shows local preview and an explicit
“AI 辅助识别” button. The button shows bounded pending/success/failure states, remains independent
from the final upload submit, and is disabled when recognition capability is unavailable. A
successful result prefills the editable classification fields and visibly says that AI suggestions
must be checked; it never changes department/contributor or submits automatically. Selecting a new
file clears stale suggestions but still does not call the provider until the button is pressed.

Only ready assets are previewable/selectable/downloadable/referenceable. Processing, failed, and
broken previews render named fallbacks. Every drawer traps focus, skips controls hidden in closed
disclosures, supports Escape/backdrop/close controls, and restores focus. Generation polling stops at
terminal state, refreshes only the gallery list, and links a successful job to its output detail.

TanStack Query owns server state. Form/search/transient conversation/selection state stays local or
in URL search parameters where shareable. Wire types come only from generated OpenAPI types.

The standalone route owns its document title, skip link, single `main`, single `h1`, loading state,
and fail-closed flag-disabled state. `/` must not load or mount the IP page. Unknown paths must not
fall back to either product surface. Vite supports the local deep link; production hosting must
rewrite `/ip-assets` to the SPA `index.html` without rewriting API paths.

## 9. Compatibility, rollout, and rollback

- Add new tables/routes/components behind `IP_ASSET_HUB_ENABLED=false` and a corresponding frontend
  build/runtime flag. Existing catalog/search/material-generation APIs do not change.
- Keep `IP_ASSET_RECOGNITION_ENABLED=false` as the committed default. Enabling it requires the hub,
  a validated Zhipu HTTPS endpoint/API key, and the reviewed vision model; disabling or rolling it
  back removes only the assistance button capability and leaves manual upload unchanged.
- Expose the frontend only at `/ip-assets` and keep it in its own lazy chunk. Removing or disabling
  the route leaves the shared development console unchanged.
- Import current assets only through an explicit idempotent CLI after migrations and Doctor checks.
- Rollback first disables the feature/worker claims. Additive tables and immutable objects can remain
  for inspection. Migration downgrade is permitted only when no new asset/job data exists, or must
  refuse with a clear message; it must not silently delete shared assets.
- The existing static catalog remains the source for current automated material generation.
- Local operational docs require backup before migrations/import and prohibit public exposure in
  no-auth mode.

## 10. Main trade-offs

- **No authentication:** fastest internal adoption, but uploader labels are unverified and public
  deployment is unsafe. The MVP compensates with an intranet boundary and no destructive UI.
- **User-confirmed core taxonomy:** the vision model reduces form work by suggesting values, but the
  editable user-confirmed upload payload remains authoritative. This costs one optional provider
  call only after an explicit button press and keeps manual upload deterministic when AI is absent.
- **Separate dynamic index:** duplicates some retrieval persistence, but preserves the static
  catalog's strong complete-index invariant and avoids breaking current generation.
- **Immediate visibility:** matches the requested open collaboration model; technical validation and
  explicit processing states remain mandatory.
