# Current Foundation and Reuse Boundaries

## Confirmed repository capabilities

- `backend/app/domain/visual_assets.py:18-28` defines current visual-catalog identity and safety
  limits: 25 MiB, 8192 maximum edge, and 32 million pixels.
- `backend/app/domain/visual_assets.py:179-260` models immutable PNG catalog assets with character,
  topic, pose, scene, priority, role, approval, and checksum metadata. It is a private manifest model,
  not a dynamic user-upload asset model.
- `backend/app/application/services/visual_retrieval.py:32-126` supports text and image embedding
  queries but requires a complete score map for every approved asset in one immutable catalog
  version. That invariant is correct for controlled generation references and incompatible with a
  library that changes after every upload.
- `backend/app/api/v1/routes/brand_knowledge.py:275-364` exposes a safe internal text-or-PNG search
  endpoint. Its response intentionally returns only bounded asset refs, roles, tags, similarity, and
  catalog identity.
- `backend/app/schemas/brand_knowledge.py:196-263` confirms existing browser projections exclude
  path, URL, object key, filename, bytes, full digest, vectors, and provider metadata. New preview and
  download endpoints must preserve those privacy boundaries while intentionally streaming verified
  content.
- `backend/app/infrastructure/storage/minio_image_store.py` already stores generated images in a
  private, content-addressed MinIO location and verifies bytes/checksum on read.
- `backend/app/application/ports/image_generation.py:8-48` provides a provider-neutral request and
  result contract with private reference bytes, request fingerprints, output raster metadata, and
  provider/model identity.
- `frontend/src/app/App.tsx:28-143` is one internal React SPA shell without routing. A dedicated
  asset-hub feature can be composed into this shell without introducing a separate frontend stack.
- `.trellis/tasks/08-21-brand-multimodal-visual-retrieval/result.md` records successful local v2
  indexing of all 41 current approved PNGs and one synthetic complete text query under Alibaba
  `qwen3-vl-embedding`, 2048 dimensions.

## Reuse decisions

- Reuse the existing provider adapter, fixed embedding identity, bounded image normalization,
  pgvector infrastructure, private MinIO connection, typed errors, job/lease patterns, generated
  OpenAPI types, and image-generation provider port.
- Add a new dynamic asset domain, tables, repository, services, APIs, worker job types, and frontend
  feature. Do not overload `VisualAssetCatalog`, its manifest loader, or its complete-index
  repository.
- Use compatible per-row embedding predicates for the dynamic library. A newly uploaded or failed
  asset does not invalidate semantic retrieval for every previously indexed asset.
- Keep source originals immutable. Generate any embedding normalization or thumbnail in memory or as
  a separately content-addressed derivative; never rewrite originals.
- Bootstrap the existing catalog by copy/register through an idempotent CLI. Do not mutate the old
  manifest or redirect existing material-generation selection to the new library in this task.

## Product decisions supplied by the user

- One shared library; no separate official/department zones.
- Everyone may upload.
- No authentication in the first version.
- Local/company-intranet deployment, not public Internet exposure.

## Historical search limitation

`trellis mem search` was attempted on 2026-08-24 but the installed Trellis build reported that the
OpenCode SQLite reader is temporarily unavailable. Existing task artifacts and code were used as the
authoritative evidence instead.
