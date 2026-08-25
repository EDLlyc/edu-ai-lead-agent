# AI Creation and Personal Material Library

## Goal

Turn the current IP image-generation drawer into a dedicated creative workspace where any colleague
can combine approved IP references, create new imagery, organize personally useful assets, and
discover popular shared assets without introducing a full account system.

The MVP shortens the path from “find a character asset” to “create, keep, reuse, favorite, download,
and deliberately share it” while preserving the existing no-auth intranet boundary.

## Background and Confirmed Product Decisions

- The standalone `/ip-assets` hub currently owns the shared gallery, upload, search, preview,
  download, and a one-reference AI creation drawer. Successful generation currently inserts its
  output directly into the shared gallery.
- Assets are immutable and globally deduplicated by image SHA-256. Personal organization must use
  profile-to-asset relationships instead of copying blobs or assigning one exclusive owner.
- The current generation job stores one reference asset, while the configured image-provider layer
  already accepts a bounded reference tuple. The MVP will support one to three ordered, distinct
  shared-library references per generation.
- Every department remains able to upload without username/password authentication. Personal
  actions use a lightweight local profile: first use collects a display name and department, and a
  browser-held opaque token restores the same server-side profile on that browser.
- This profile is convenience-level intranet isolation only. It has no password, verified identity,
  recovery, confidentiality guarantee, or public-Internet security claim.
- A newly created generation is personal by default and requires an explicit action to become newly
  visible in the company gallery. If exact-byte deduplication resolves to an asset that was already
  shared, its pre-existing shared visibility is not revoked and the generation still gains the
  correct personal membership.
- A new manual upload made while a local profile is active remains immediately shared and is also
  associated with that profile. Historical assets are not auto-attributed.
- The company download leaderboard defaults to the latest 30 business-calendar days and can switch
  to cumulative counts. It stores anonymous daily per-asset aggregates only.

## Requirements

### R1 — Dedicated AI creation workspace

- Add `/ip-assets/create` as a standalone route linked from the shared hub; neither route may be
  mounted in the shared development console at `/`.
- The workspace must provide prompt entry, controlled character/type selection, a one-to-three
  reference filmstrip, generation submission, queued/running/succeeded/failed status, output
  preview, and an obvious path into the personal material library.
- Remove AI creation from the hub drawer after the dedicated page is available. Upload may remain a
  hub action.
- When generation is disabled, explain the actual capability state and disable only creation;
  gallery, profile, personal organization, favorites, downloads, and leaderboard remain usable.

### R2 — Lightweight browser-local profile

- Before the first creation, favorite, or personal-library action, collect bounded display name and
  department values and create or restore one browser-persisted opaque profile token.
- The profile bootstrap must be retry-safe, the token must have high entropy, and only its digest may
  be stored by the backend. Profile-scoped requests send the token in a dedicated request header,
  never a URL or loggable query parameter.
- The UI must say the identity is local to this browser, unverified, has no password or recovery, and
  may be lost when browser data is cleared.
- Existing contributor and department labels remain self-reported metadata; the feature must not
  imply ownership, employee verification, or confidential storage.

### R3 — Ordered reference-asset picker

- Let the user search/filter and select one to three distinct `ready` assets from the shared library.
- Selected references remain visible, numbered, removable, and reorderable before submission; a
  fourth reference and a duplicate reference are rejected accessibly.
- References are resolved from safe asset refs to verified stored bytes. Arbitrary URLs, new browser
  uploads, private object paths, unready assets, and another profile's personal-only assets are not
  valid references in this MVP.
- The ordered asset identities and source checksums participate in the generation request
  fingerprint. A reference change or reorder cannot replay a different request.
- The legacy one-reference request shape remains accepted for compatibility during this migration,
  but the new frontend uses the ordered list contract.

### R4 — Personal material library and explicit sharing

- A successful generation must atomically complete its job and associate the output asset with the
  requesting profile, including exact-byte deduplication cases.
- A new manual upload made with an active profile creates an `uploaded` personal membership while
  retaining the existing shared-gallery behavior. Anonymous uploads remain supported but gain no
  invented membership.
- “My material library” exposes generated outputs, current-profile uploads, and favorites as distinct
  sources while presenting an asset only once in an aggregate view.
- A profile may preview and download an accessible ready personal asset and inspect safe generation
  provenance/status. Hidden personal media reads must not rely on bearer tokens in URLs.
- Only a profile with a generated membership may explicitly add that generation to the shared
  library. Sharing is idempotent and is not a social-media publish action.
- Shared search, semantic retrieval, gallery listing, and reference selection must exclude
  personal-only assets until they are shared.

### R5 — Favorites

- A profile may idempotently favorite or unfavorite any accessible ready asset from the shared
  gallery, detail view, reference picker, or personal workspace.
- Favorites are profile-scoped relationships and never duplicate the underlying asset.
- Favorite state must remain consistent across all surfaces and query-cache transitions.
- Do not display favorites as verified unique-person counts because local profiles are self-created.

### R6 — Anonymous download leaderboard

- Add a company-wide leaderboard for shared `ready` assets with “latest 30 days” as the default and
  “all time” as the alternate period.
- Bucket counts by the configured `Asia/Shanghai` business date without storing profile identity,
  department, IP address, object location, user agent, raw request metadata, or per-download rows.
- Count a successfully prepared direct original download once. For a successfully prepared ZIP,
  count each distinct included shared asset once.
- Preview/render requests, failed downloads, repeated ZIP refs, personal-only downloads,
  generation/reference reads, and recognition/search image reads do not change the leaderboard.
- Order by download count and stable asset tie-breakers. Zero-download assets do not outrank assets
  with downloads, and responses expose only safe card data, period, and aggregate count.

### R7 — Compatibility, privacy, and operational safety

- Backfill every historical asset as already shared, backfill existing single generation references
  at ordinal zero, and leave historical jobs profile-less. Do not invent profile memberships,
  favorites, or download history.
- Preserve immutable storage, SHA-256 deduplication, verified reads, preview and ZIP bounds, safe
  public refs, semantic degradation, lease fencing, exact CORS origins, provider-free test defaults,
  generated OpenAPI types, and feature-disabled behavior.
- Existing shared preview and download URLs remain anonymous and usable. Personal-only media uses
  header-bearing fetches and revocable browser object URLs.
- No UI, API, documentation, or log may claim authentication, privacy, rights ownership, verified
  attribution, or automatic publication.

## Acceptance Criteria

- [ ] AC1: `/ip-assets/create` renders a dedicated accessible creative workspace, `/ip-assets`
      remains the image-first shared hub, `/` remains the development console, and the old creation
      drawer is absent.
- [ ] AC2: the first personal action creates or restores one retry-safe browser-local profile from a
      high-entropy token after collecting bounded display name and department, and the UI presents
      the no-password/no-recovery boundary.
- [ ] AC3: the user can select, order, and remove one to three eligible shared references; duplicate,
      fourth, unready, arbitrary, and inaccessible references are rejected, and ordered references
      are bound into idempotency.
- [ ] AC4: a generation is enqueued once, polling stops at a terminal status, and successful output
      is atomically linked to the requesting profile without newly entering the shared gallery.
- [ ] AC5: exact-byte output deduplication reuses the immutable asset, creates the correct personal
      membership, never unshares an already-shared asset, and completes the job under its lease.
- [ ] AC6: a current-profile manual upload remains shared-visible and appears under that profile's
      uploads; an anonymous upload remains supported and no historical row is auto-attributed.
- [ ] AC7: the personal aggregate view deduplicates assets while source-specific generated, uploaded,
      and favorite views remain accurate; personal-only previews/downloads enforce profile access
      without putting a token in a URL.
- [ ] AC8: explicit add-to-shared is idempotent, is available only for a profile's generated
      membership, and makes a newly personal asset available to gallery/search/reference queries.
- [ ] AC9: favorite/unfavorite is idempotent and consistent across gallery, detail, picker, and
      personal workspace, including query invalidation and accessible pressed states.
- [ ] AC10: direct and ZIP downloads update anonymous daily aggregates exactly once under the stated
      rules; previews, failures, duplicates, personal-only reads, and internal image reads do not.
- [ ] AC11: the leaderboard defaults to the latest 30 `Asia/Shanghai` dates, switches to cumulative,
      returns deterministic shared-ready results, and exposes no profile or storage details.
- [ ] AC12: generation-disabled mode is truthful and leaves all non-generation asset functions
      usable; existing one-reference API requests and historical shared assets remain compatible.
- [ ] AC13: PostgreSQL migration/model parity, generation/favorite/download concurrency,
      API/OpenAPI mapping, exact CORS headers, frontend accessibility/responsiveness, privacy scans,
      lint, strict types, tests, build, and local browser flows pass.

## Out of Scope

- Username/password, SSO, verified employee identity, role authorization, cross-device sync or
  recovery, public-Internet deployment, row-level security, or confidential personal storage.
- Profile editing/deletion, token rotation/recovery, asset delete/archive/version replacement,
  folders/collections, comments, review/approval workflow, quotas, billing, or cost dashboards.
- Arbitrary URL or fresh-upload generation references, more than three references, prompt history,
  generation variants/batches, or editing an existing image in place.
- Unique-human favorite/download analytics, per-user download history, IP/user-agent tracking, or
  historical analytics reconstruction.
- Automatic sharing, WeChat/social-media publishing, or any external distribution action.

## Planning Note

This is one complex cross-layer task because the migration, generated API contract, generation
transaction, and frontend state are tightly coupled. Implementation is intentionally ordered into
independently checkable phases rather than split into child tasks that would concurrently edit the
same schema and feature boundary.
