# Current IP Asset Seams

## Confirmed repository behavior

- `backend/app/infrastructure/db/models.py:4679` defines globally SHA-256-deduplicated `ip_assets`;
  there is no visibility, profile, membership, favorite, or download aggregate model.
- `backend/app/infrastructure/db/models.py:4904` defines generation jobs with one nullable
  `reference_asset_id`, a globally unique idempotency key/fingerprint, one output, and lease state.
- `backend/app/application/services/ip_assets.py:430` owns lease-safe generation processing;
  `backend/app/application/services/ip_assets.py:480` stores output and
  `backend/app/infrastructure/db/ip_assets.py:633` fences exact-asset creation plus job completion.
- `backend/app/application/services/ip_assets.py:524` loads one reference and
  `backend/app/application/services/ip_assets.py:548` fingerprints/enqueues the one-reference request.
  The underlying image-generation request accepts a reference tuple, so the IP feature is the
  one-reference bottleneck.
- `backend/app/api/v1/routes/ip_assets.py:254` prepares ZIP responses,
  `backend/app/api/v1/routes/ip_assets.py:330` serves previews, and
  `backend/app/api/v1/routes/ip_assets.py:345` serves original downloads. No route records download
  analytics, and preview has a distinct route.
- `backend/app/api/v1/routes/ip_assets.py:270` accepts generation creation and
  `backend/app/schemas/ip_assets.py:116` exposes only `reference_asset_ref`.
- `frontend/src/app/pathResolver.ts:1` recognizes only `/` and `/ip-assets`.
  `frontend/src/features/ip-assets/IpAssetHub.tsx:103` holds one reference and
  `frontend/src/features/ip-assets/IpAssetHub.tsx:421` renders creation in a dialog;
  `frontend/src/features/ip-assets/IpAssetHub.tsx:999` contains the creation form.
- `frontend/src/features/ip-assets/api.ts:245` maps generation creation and
  `frontend/src/features/ip-assets/api.ts:282` performs ZIP download. Direct shared download is a
  normal anchor at `frontend/src/features/ip-assets/IpAssetHub.tsx:1302`, which cannot attach a local
  profile header for personal-only media.
- The committed Alembic chain currently ends at `20260824_0034`; the IP hub base schema is
  `20260824_0031`.

## Planning consequences

- Personal state must be relational; copying blobs or adding a single owner column would violate
  global deduplication and prevent one asset from appearing under several profile sources.
- New generated assets need explicit shared visibility. Historical assets must be backfilled as
  shared so the current hub remains unchanged after migration.
- Generation fingerprints and idempotency must be profile-scoped. Otherwise two profiles submitting
  the same request could reuse a job owned by only one profile.
- Ordered references need a child table. Keep the legacy single-reference column as an ordinal-zero
  compatibility projection during this task rather than destructively dropping it.
- Personal-only `<img>` and download access needs authenticated-header fetch plus object URLs; putting
  the opaque token into preview/download URLs would leak it through browser and server metadata.
- A daily aggregate table is enough for 30-day and cumulative ranking and avoids storing a
  per-download behavioral trail.
