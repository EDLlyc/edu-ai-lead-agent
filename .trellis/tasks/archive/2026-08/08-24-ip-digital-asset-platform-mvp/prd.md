# IP Digital Asset Sharing Platform MVP

## Goal

Provide one company-intranet web application where any internal colleague can upload, browse,
classify, search, preview, and download Sai Xiansheng / Xiao Sai visual assets, or create a new image
through the existing image-generation capability and save it into the same shared library. The MVP
must replace ad-hoc departmental folders and filenames with stable asset identity, controlled core
classification, canonical display names, and multimodal retrieval.

The product is a shared internal asset hub, not a public website and not an approval system.

## Background and Confirmed Constraints

- Every department currently creates separate Sai Xiansheng and Xiao Sai IP images and expression
  packs, making discovery, reuse, and naming inconsistent.
- The first version has one shared library. There are no official/department zones.
- Every intranet visitor may upload, browse, search, generate, and download. The application has no
  login, account, role, authorization, or approval workflow in the MVP.
- A successfully validated upload becomes visible to all users immediately. Embedding and thumbnail
  processing may continue asynchronously and must expose an honest processing/failed/ready state.
- The deployment boundary is a local machine or company intranet. Public-Internet exposure is out of
  scope while the application has no authentication.
- The repository already has PostgreSQL/pgvector, private MinIO storage, a fixed
  `qwen3-vl-embedding` 2048-dimensional adapter, text/image visual retrieval, and image-generation
  provider ports. The current approved visual catalog is static and complete-index gated, so the new
  continuously changing library needs separate dynamic persistence and retrieval semantics.

## Requirements

### R1. One shared asset library

- The UI shall show one responsive visual gallery with newest-first browsing, cursor pagination,
  thumbnail preview, an asset detail view, and empty/loading/error states.
- Every ready asset shall expose a browser-safe stable `asset_ref`, canonical display name, core
  classification, dimensions, media type, source kind, department/contributor labels when supplied,
  created time, and tags.
- The library shall distinguish `uploaded`, `generated`, and `seed_import` provenance without
  separating them into different access zones.
- Processing assets may appear in the gallery with status, but only validated stored bytes may be
  previewed or downloaded.

### R2. Upload and file safety

- The upload form shall accept PNG, JPEG, and WebP files up to 25 MiB, with a maximum edge of 8192
  pixels and a maximum of 32 million decoded pixels. Media type, signature, dimensions, and decoded
  raster must agree.
- Users shall provide the core character and asset type at upload time. Department, contributor,
  emotion/action, scene, intended use, and free tags are optional metadata.
- Upload shall preserve the safe original filename as provenance, store immutable original bytes in
  private content-addressed MinIO, and never expose an object key or private storage URL.
- Exact SHA-256 duplicates shall return the existing asset instead of creating another asset.
  Perceptual or embedding-near duplicates may be shown as a warning but shall not block the upload.
- The MVP has no destructive delete/archive control in the shared UI. Operational cleanup is a
  deferred maintenance action so an unauthenticated visitor cannot erase the library.

### R3. Controlled classification and canonical naming

- Core `character` values shall be `sai_xiansheng`, `xiao_sai`, `duo`, or `other`.
- Core `asset_type` values shall cover at least: identity/reference design, portrait/avatar,
  full-body pose/action, expression, meme/sticker, transparent cutout, scene illustration, poster
  element, and other.
- Secondary metadata shall use controlled dimensions for emotion, action, scene, intended use,
  style, background, orientation/aspect, department, and provenance; bounded free tags may supplement
  but not replace the two required core dimensions.
- The canonical display-name pattern shall be
  `{character}-{asset_type}-{emotion_or_action}-{scene_or_use}-{format}-{version}`. Missing optional
  segments are omitted rather than filled with invented values.
- The stored object key and stable asset identity shall never depend on the canonical or original
  filename. Canonical-name collisions shall receive a transactionally assigned `v001`, `v002`, ...
  version suffix.
- Example: `小赛-表情包-开心-科学课堂-方图-v001` with a safe downloadable filename derived from
  that name and the actual media extension.

### R4. Browse, filter, and conventional search

- Users shall be able to combine keyword search with character, asset type, department, provenance,
  orientation, and tag filters.
- Keyword search shall cover canonical name, safe original filename, controlled metadata, and tags.
- A provider outage or an asset still waiting for an embedding shall not make normal browsing and
  metadata/keyword search unavailable.
- Search results shall have a deterministic secondary ordering so pagination does not reshuffle.

### R5. Conversational multimodal retrieval

- The UI shall provide a chat-like search surface where a user can ask in natural language, for
  example, “找一张小赛开心庆祝、适合社群推送的透明底图片”.
- The first MVP shall keep conversational context in the current browser session only; it shall not
  persist personal chat history because there is no user identity.
- Explicit controlled terms in the conversation shall become structured filters. The full bounded
  query shall be embedded with the existing visual embedding identity and ranked against compatible
  ready asset vectors using pgvector cosine similarity.
- An image may also be supplied as a similarity query. Query bytes are transient and shall not be
  stored as an asset unless the user separately uploads them.
- Each returned card shall include a bounded explanation using matched filters/tags and semantic
  similarity. It shall not expose vectors, provider bodies, request identifiers, filenames, paths,
  or object-storage locations.
- If semantic retrieval is disabled, unavailable, or an asset lacks a compatible embedding, the API
  shall return an explicit degraded state and useful metadata/keyword results instead of failing the
  entire request.

### R6. Preview and download

- The detail view shall allow full preview of a validated raster and download of the immutable
  original using the canonical safe filename.
- Preview and download shall be streamed through bounded API endpoints with correct media type,
  content length, ETag/checksum behavior, and `Content-Disposition`; private MinIO URLs shall not be
  returned to the browser.
- Users shall be able to select multiple ready assets and download a bounded ZIP package containing
  originals plus a UTF-8 JSON manifest of asset refs, names, classifications, and checksums.

### R7. Image creation and automatic library ingestion

- A creation panel shall accept a bounded prompt, character, asset type, optional one existing
  reference asset, and supported output ratio/size choices.
- Generation shall use a durable job and the existing provider-neutral image-generation port. The
  API shall never hold the request open for the whole provider operation.
- A successful generated image shall pass the same raster validation and immutable storage path as
  an upload, receive `generated` provenance and a canonical name, then enqueue its visual embedding.
- The result shall appear in the shared gallery and be searchable/downloadable without a separate
  approval step. Provider/model identity, request fingerprint, safe terminal status, and bounded
  failure code shall be persisted; secrets, raw provider responses, and transient provider URLs
  shall not be exposed.
- Generation-disabled/provider-unavailable states shall leave upload, browse, search, preview, and
  download usable and shall be explained in the UI.

### R8. Bootstrap existing assets

- A repeatable local CLI shall import the current approved manifest assets into the new shared
  library without modifying their source files or the existing static manifest.
- Re-running the importer shall be idempotent by checksum and shall report only aggregate created,
  existing, and failed counts.
- The existing static catalog, complete-index proof, material selection, and generation behavior
  shall remain compatible until a later task deliberately migrates those consumers.

### R9. Intranet/no-auth operating boundary

- Routes shall be disabled by default behind one feature flag and documented for local/intranet
  activation. No application login or authorization dependency is introduced.
- The UI shall state that the library is company-internal and unauthenticated. The deployment guide
  shall require same-origin access or an explicit intranet origin allowlist and shall warn against
  public exposure.
- User-supplied department and contributor fields are descriptive labels only and shall never be
  represented as verified identity or audit attribution.
- Mutating endpoints shall enforce bounded request sizes, rate/concurrency limits appropriate for a
  local service, typed errors, and idempotency where replay could duplicate durable work.

### R10. AI-assisted upload classification

- After a user selects a locally previewable image, the upload workflow shall be able to send the
  validated transient raster to a configured vision-language model and receive bounded suggestions
  for controlled character/type plus optional emotion, action, scene, intended use, style, and tags.
- Recognition shall start only after the user explicitly activates an “AI 辅助识别” control. File
  selection and local preview alone shall not transmit image bytes or incur a provider call.
- Suggestions are advisory form values, not approval or durable truth. The user can accept, edit, or
  ignore each result before the existing upload request is submitted; the vision call never creates
  an asset by itself.
- The model response shall use a strict allowlisted JSON schema. Unknown labels, prose, reasoning,
  prompts, raw provider responses, provider request IDs, credentials, private paths, and image bytes
  shall not be returned to the browser or persisted.
- AI recognition is optional and provider-independent upload remains usable after timeout,
  rejection, invalid output, or disabled configuration. The UI shall retain the selected file and
  existing form values when recognition fails.
- Recognition shall reuse the existing Zhipu vision boundary and configured
  `glm-4.1v-thinking-flash` capability rather than treating the 2048-dimensional
  `qwen3-vl-embedding` vector as a label generator.

## Acceptance Criteria

- [ ] AC1: With the feature enabled on a local stack, a user can upload a valid PNG, JPEG, or WebP,
      choose character/type, receive a stable asset reference and canonical name, and see the asset in
      the shared gallery without logging in or approving it.
- [ ] AC2: Invalid signatures, oversize bytes/dimensions/pixels, malformed rasters, unsafe metadata,
      and unsupported media produce bounded typed errors and create no database row or MinIO object.
- [ ] AC3: Uploading identical bytes twice returns the same asset reference and stores one immutable
      original; a near-duplicate warning does not block a distinct valid upload.
- [ ] AC4: Gallery filters and keyword search return deterministic paginated results even when the
      embedding provider is disabled.
- [ ] AC5: After an embedding job succeeds, a Chinese natural-language text query and a PNG/JPEG/WebP
      image query return compatible ranked asset cards with safe explanations; provider failure returns
      the documented degraded result instead of a 500 response.
- [ ] AC6: Preview and individual download return verified original content without exposing MinIO
      locations; a bounded multi-select ZIP contains verified originals and a manifest.
- [ ] AC7: A configured image-generation job completes asynchronously, creates exactly one generated
      asset in the same gallery, and can be found and downloaded; repeated submission with the same
      idempotency key does not create a second job or asset.
- [ ] AC8: With generation disabled, the creation panel shows an unavailable state while every
      non-generation library workflow remains usable.
- [ ] AC9: The seed importer copies/registers the approved current assets without changing the old
      manifest and is idempotent on a second run.
- [ ] AC10: No asset API response or frontend-rendered payload contains a private filesystem path,
      object key, private MinIO URL, embedding vector, provider body, provider request ID, credential,
      or claim of verified uploader identity.
- [ ] AC11: OpenAPI generation, strict backend typing/lint, frontend strict type-check, focused unit
      and API/UI tests, real PostgreSQL/pgvector migration/retrieval tests, and MinIO upload/download
      integration tests pass.
- [ ] AC12: The local deployment documentation visibly states “company intranet only / no
      authentication / do not expose publicly”, and committed defaults keep the feature disabled.
- [ ] AC13: For one selected valid image, AI assistance returns editable controlled suggestions
      without creating an asset; accepting or changing those values and submitting uses the existing
      validated upload path. Provider-disabled/failure states leave manual upload fully usable and
      expose no private/provider payload.

## Out of Scope

- Login, SSO, accounts, role-based permissions, department isolation, verified uploader identity,
  quotas, approval/review workflows, or official-versus-creative zones.
- Public Internet deployment, public sharing links, CDN distribution, social-platform publishing,
  mobile-native applications, or external customer access.
- Destructive deletion/archive controls, moderation queues, legal-rights approval, licensing
  enforcement, comments, likes, notification feeds, or usage analytics dashboards.
- Automatic AI classification as a release-blocking or authoritative dependency. The proposed
  vision-language assistant may prefill editable metadata, but user-confirmed values and the
  existing validation path remain authoritative.
- Replacing the current static approved catalog in existing material-generation pipelines.
- Bulk metadata migration beyond the repeatable importer, advanced DAM renditions, video/audio/file
  assets, PSD/AI/SVG editing, or model training/fine-tuning.

## Technical Notes

- Preserve existing upload safety limits where compatible and reuse the visual input normalizer and
  fixed embedding adapter, but do not reuse the static catalog's complete-index query contract.
- Persist mutable library rows and dynamic compatible embeddings in new tables; keep originals
  immutable and content addressed.
- Treat no-auth as a deliberately limited intranet operating mode, not as a future security model.
