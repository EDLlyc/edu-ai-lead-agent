# Design: AI Creation and Personal Material Library

## 1. Architecture boundary

Extend the existing IP asset vertical slice rather than creating a second storage/catalog system.
The immutable `ip_assets` row and object-store bytes remain the canonical asset. New tables describe
local profiles, asset relationships, ordered generation inputs, and anonymous daily download counts.

Shared reads remain anonymous. Only personal actions resolve a browser-held local-profile token. This
is a bounded capability token for intranet convenience, not a full user-authentication layer. No
cookie session, password, role, or identity provider is introduced.

The end-to-end flow is:

```text
browser local profile token
  -> profile-scoped personal/favorite/generation operations

1..3 ordered shared ready assets + prompt
  -> profile-scoped idempotent generation job
  -> existing worker/provider flow outside DB transactions
  -> lease-fenced output create/reuse + personal membership + job completion
  -> explicit share changes shared visibility

successful shared original/ZIP preparation
  -> one atomic daily aggregate increment per distinct shared asset
  -> 30-day or cumulative leaderboard query
```

## 2. Persistence and migration

Add one Alembic revision after the repository's actual head at implementation time. The planned
shape is additive except for replacing the generation idempotency-key uniqueness constraint with a
profile-scoped equivalent:

### `ip_asset_profiles`

- UUID primary key, safe `ipp_<20 hex>` profile ref, SHA-256 digest of the browser token, bounded
  display name/department, and timestamps.
- Profile ref and token digest are unique. Raw tokens are never stored or returned by the backend.
- Creation is retry-safe: the browser generates and stores the token before the request; repeating
  profile bootstrap with the same token and metadata returns the same profile, while conflicting
  metadata returns a typed conflict.

### `ip_asset_profile_memberships`

- Profile, asset, source (`generated` or `uploaded`), optional generation job, and creation time.
- Unique `(profile_id, asset_id, source)` allows one asset to have several understandable sources
  without duplicate blobs. Generated rows require a matching generation job; uploaded rows do not.
- Personal aggregate queries group by asset and project a bounded source set.

### `ip_asset_favorites`

- Profile, asset, and creation time with unique `(profile_id, asset_id)`.
- Favorite/unfavorite uses insert-on-conflict/delete semantics and never changes the asset row.

### `ip_asset_generation_references`

- Generation job, ordinal `0..2`, referenced asset, source blob SHA-256 snapshot, and creation time.
- Unique `(job_id, ordinal)` and `(job_id, asset_id)` enforce bounded order and distinct references.
- Backfill each legacy non-null `reference_asset_id` at ordinal zero. Keep that legacy column as the
  ordinal-zero compatibility projection; all new domain reads use the child rows and tests enforce
  mirror consistency.

### `ip_asset_download_daily`

- Asset, configured-business-date, positive count, and update time with unique
  `(asset_id, business_date)`.
- Atomic PostgreSQL upsert increments avoid lost updates. No event, profile, network, or request
  metadata is retained.

### Existing-table changes

- Add nullable `shared_at` to `ip_assets`; backfill every historical row from `created_at` before
  enforcing gallery/search visibility through `shared_at IS NOT NULL`.
- Add nullable `profile_id` to `ip_asset_generation_jobs` for legacy compatibility.
- Replace global generation idempotency uniqueness with `(profile_id, idempotency_key)` for new jobs;
  include profile identity in the request fingerprint. Preserve historical null-profile rows and
  their readable job refs.

The migration creates no profiles, memberships, favorites, or historical download counts. Downgrade
must remove only this task's tables/columns/constraints and restore the prior generation uniqueness
contract after an explicit duplicate check.

## 3. Domain and repository contracts

Add closed validation for local-profile tokens, profile metadata, membership sources, leaderboard
periods, and ordered reference lists. The token is 32 random bytes encoded as canonical Base64URL;
the backend compares only its SHA-256 digest.

Extend `IpAssetRecord` with shared visibility and introduce safe profile, personal-item, and
leaderboard records. Repository methods must distinguish:

- public shared-ready access;
- profile-accessible access (`shared OR membership`);
- generated-membership authority for explicit sharing;
- shared-ready eligibility for generation references and ranking.

All list paths keep bounded limits and stable keyset/tie ordering. Profile refs and self-reported
labels may be returned to the current browser, but internal UUIDs, token hashes, object locations,
download dates/rows, and other profiles are never projected.

## 4. Profile and media-access contracts

The browser creates a high-entropy token with Web Crypto and stores a versioned record under
`edu-ai.ip-assets.profile.v1`. It sends the token in `X-IP-Profile-Token` only to profile-aware API
methods. The exact CORS allow-header contract must be updated without wildcard origins or credentials.

API shape:

- `POST /api/v1/ip-assets/profiles` — retry-safe bootstrap from header + display name/department.
- `GET /api/v1/ip-assets/profiles/me` — restore/validate the current local profile.
- `GET /api/v1/ip-assets/profiles/me/assets` — keyset personal list with `all`, `generated`,
  `uploaded`, or `favorite` source filtering.
- `PUT|DELETE /api/v1/ip-assets/{asset_ref}/favorite` — idempotent relationship mutation.
- `PUT /api/v1/ip-assets/{asset_ref}/shared` — idempotent generated-membership share.
- `GET /api/v1/ip-assets/leaderboard?period=30d|all&limit=...` — safe aggregate ranking.

Shared asset detail/preview/download stays anonymous. For a personal-only asset, detail and media
services require a matching profile membership. The frontend obtains private preview/download bytes
with `fetch` plus the profile header, creates a revocable object URL, and never places the token in a
URL, DOM attribute, error string, analytics payload, or query key.

## 5. Generation contract and transaction

Add `reference_asset_refs` with one to three ordered distinct safe refs. Continue accepting the
legacy optional `reference_asset_ref` for a single reference; reject requests that provide both.
Responses expose the ordered safe refs and may retain the legacy first-ref projection for contract
compatibility.

Enqueue resolves every ref as shared and ready, snapshots its blob checksum, and fingerprints the
profile, normalized prompt/options, ordered `(asset_id, blob_sha256)` tuple, provider, model, and
policy version. The idempotency key is scoped to the profile. A same-key/different-fingerprint retry
is a typed conflict.

The worker loads and verifies each stored reference before one existing provider call. Provider and
object-store work stays outside database transactions. Completion remains one short lease-fenced
transaction that:

1. verifies the job lease and output fingerprint;
2. creates or reuses the globally deduplicated immutable asset;
3. leaves a new output `shared_at = NULL` but never clears an existing asset's `shared_at`;
4. inserts the requesting profile's `generated` membership;
5. links the job output and marks the job succeeded.

The output asset's legacy `parent_asset_id` remains the first reference for compatibility; the job's
ordered reference rows are the authoritative provenance. Failed jobs create no asset membership.

Manual upload remains shared by default. If a valid optional profile header is present, the asset
create/reuse transaction also inserts an `uploaded` membership. If exact bytes match a personal-only
asset, the deliberate shared upload sets `shared_at` because uploaded content is company-visible by
product contract; this is consistent with the explicitly weak, non-confidential profile boundary.

## 6. Download accounting and leaderboard

Keep object-store reads and ZIP construction outside database transactions. After all requested
bytes are verified and the direct/ZIP body is successfully prepared, increment the current
`settings.business_timezone` date in one short repository transaction, then return the response.
If aggregate persistence fails, fail the response rather than claim a successful counted download.
A later socket disconnect may still leave a prepared response counted; delivery acknowledgements are
not available in the current HTTP architecture and are outside the MVP.

ZIP counting deduplicates refs before both package construction and aggregation. Only shared-ready
assets are aggregated; personal-only downloads still work for their profile but do not affect the
company ranking.

The 30-day query sums the current business date and preceding 29 dates. The cumulative query sums all
daily rows. Both join only current shared-ready assets and order by count descending, asset creation
time descending, then asset ID descending. Results contain period, generated-at timestamp, safe asset
card projection, and count.

## 7. Frontend information architecture and visual direction

Keep the current light teal/clay visual language but sharpen it into an editorial creative-studio
workspace rather than a generic dashboard. The signature interaction is a numbered `01–03`
reference filmstrip that visually connects source assets to the output stage.

### Shared hub (`/ip-assets`)

- Retain the image-first gallery, upload, multimodal search, filters, detail, and batch download.
- Replace the creation drawer trigger with a clear link to the standalone studio.
- Add accessible favorite controls to cards/detail without stealing the card's primary preview
  interaction.
- Add a compact download-ranking rail: vertical beside the gallery on wide screens and horizontal
  above results on narrow screens, with a two-state 30-day/all-time control.

### Creation and personal workspace (`/ip-assets/create`)

- Use one page shell with a clear link back to the shared hub and a local-profile badge/boundary note.
- Desktop creation stage: asymmetric two-column grid with prompt/options/reference filmstrip on the
  left and live generation state/output on the right. Collapse to one logical focus order below
  900px.
- Below the stage, use an image shelf with source tabs: all, generated, uploaded, favorites. Cards
  show source badges, shared state, favorite state, and safe actions without dense admin-table chrome.
- The first personal action opens an accessible profile setup dialog/inline gate. Focus is trapped and
  restored; status changes use `aria-live`; favorite controls use `aria-pressed`; all tap targets are
  at least 44px.
- Use the existing CSS-module stack and shared feature components. Add only restrained stage/status
  transitions, guard them with `prefers-reduced-motion`, preserve visible focus, and avoid overlay
  layering that can intersect input focus rings.

TanStack Query owns server state. Query keys include the safe profile ref, never the token. Profile
changes/invalid restoration clear profile-scoped caches. Mutations invalidate the shared gallery,
personal source lists, detail, favorites, and leaderboard only where their contract can change.
Generation polling remains non-recursive and stops for succeeded/failed states.

## 8. Compatibility, failure, and rollback

- Feature-disabled generation renders an honest unavailable state but does not disable profiles,
  personal shelves, favorites, download counting, or shared asset use.
- Missing profile tokens produce a bounded setup-required response; invalid tokens never reveal
  whether another profile or personal asset exists.
- Historical shared assets and legacy job reads remain usable. Legacy single-reference creation is
  accepted for one compatibility cycle.
- Disable/hide the new frontend navigation to roll back UI exposure. Because historical rows are
  backfilled shared and new tables are additive, the previous shared hub can continue reading them;
  deployments must not roll old code over newly personal-only rows unless generation is disabled.
- No deployment, account integration, external publish, destructive data migration, or token-recovery
  mechanism is part of this task.

## 9. Validation strategy

- Domain/unit: token and metadata bounds, ordered distinct references, fingerprints, legacy request
  normalization, visibility/access rules, period/date calculation, deterministic ties, ZIP dedupe.
- PostgreSQL: clean upgrade/downgrade and model parity; historical backfills; concurrent profile
  bootstrap, memberships, favorites, sharing, enqueue, lease completion, dedupe, and daily upserts;
  personal/shared filters and ranking windows.
- API/OpenAPI: exact profile-header/CORS behavior, no token/query leakage, personal isolation, legacy
  generation compatibility, safe projections, private media fetch, download count exclusions, and
  feature-disabled behavior.
- Frontend: route isolation, onboarding/restore loss state, one-to-three picker, terminal polling,
  personal-source dedupe, favorite consistency, share mutation, ranking period switch, private blob
  cleanup, responsive states, keyboard focus, reduced motion, and automated accessibility.
- Final: generated contract drift, backend/frontend checks, unique Alembic head, Doctor, Compose,
  privacy/token scans, `git diff --check`, and one local browser smoke against the exact same-origin or
  configured-CORS path.
