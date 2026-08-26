# Research: Selected-news source image pipeline

- Query: How should a selected news article's own images be acquired during source ingestion and carried, with exact provenance and rights state, through governed topic selection, material packages, and the local official-account draft alongside approved/generated company IP images?
- Scope: internal
- Date: 2026-08-25

## Findings

### Decision and minimum production-shaped vertical slice

The requested capability is not arbitrary web/image search and is not a post-generation photo insertion command. It is an additive, acquisition-time source-media pipeline:

1. While fetching an allowlisted article detail page, extract a bounded list of images belonging to that article.
2. Resolve and validate every candidate URL before image I/O, then fetch at most two eligible images through a dedicated safe image fetcher.
3. Store original immutable bytes plus page/image provenance and an explicit, conservative rights state.
4. Carry only `ready` source images through the already-selected evidence occurrence into the material package. Topic selection itself performs no network request.
5. Build a new, exact-version mixed official-account media plan that can place zero to two source-news images among approved/generated IP images. Existing article/render/demo versions and their bytes remain unchanged.
6. Surface provenance, caption/credit, and the unverified-rights warning in the development-only local workbench. Do not publish to WeChat or WeCom.

No independent worker entry point is needed for the smallest slice. The existing acquisition worker can perform the bounded image sub-step after a detail page has been accepted and persisted. All downstream stages consume stored state and never recrawl the article.

### 1. Current acquisition contract does not retain article images

- `backend/app/domain/entities.py:35-65` — `FetchedResponse` retains requested/final URL, response headers/body/checksum/time, while `ExtractedDocument` retains title, clean text, publication/language/parser metadata; neither models image descriptors.
- `backend/app/application/ports/acquisition.py:83-101` — acquisition persistence covers detail snapshots, candidates, and observations, but exposes no source-media port.
- `backend/app/infrastructure/ingestion/connectors.py:243-313` — `HtmlConnector.extract()` selects the configured article content root, extracts text, applies the trafilatura fallback, and reads time/canonical metadata. It does not parse `og:image`, `<figure>`, `<img>`, `figcaption`, alt text, or credits.
- `backend/app/application/services/execute_acquisition.py:409-555` — detail fetch, immutable snapshot persistence, extraction, relevance/freshness checks, candidate persistence, and observation persistence form the current accepted-article path. There is no image discovery or fetch step.
- `backend/tests/fixtures/sources/*/detail.html` — the current twelve source detail fixtures contain no `<img>`, `<figure>`, `<figcaption>`, or `og:image` cases, so they cannot specify the new behavior yet.

Add a bounded `SourceImageDescriptor` to acquisition extraction output rather than embedding downloaded bytes there. Minimum fields are stable ordinal, relationship (`inline_figure`, `inline_image`, or `og_image`), exact unresolved attribute value, resolved URL, alt, caption, credit, and extraction version. The connector owns DOM membership and caption association; a separate fetcher owns network and raster validation.

An “article's own image” means an image inside the connector's selected article content root, including a containing `figure`, or a source-profile-enabled `og:image` associated with that exact detail page. The MVP must not follow related-story links, crawl galleries on another page, use a search engine, or select visually similar images from the public web.

### 2. Reusable safety, validation, provenance, and dedup patterns

- `backend/app/infrastructure/ingestion/fetcher.py:28-183` — `SafeHttpFetcher` already provides source crawl-policy enforcement, host/path validation on every redirect, public DNS resolution, bounded redirects, content-type checks, `Content-Length` and streamed byte limits, safe response metadata, checksum, and retrieval time. Its accepted media types are text/JSON/XML/HTML, so changing it in place to accept raster images would weaken an established contract.
- `backend/app/core/security.py:71-177` — reusable HTTPS URL normalization, userinfo/fragment/non-default-port/IP-literal rejection, traversal/encoded-separator protection, allowlist validation, and non-public-address rejection.
- `backend/app/infrastructure/ai/image_generation.py:785-870` — generated-image download demonstrates bounded streaming, no redirects, public DNS validation, content-type checks, retries, and raster signature validation; `backend/app/infrastructure/ai/image_generation.py:1034-1041` and `:1139-1185` contain signature and dimension parsing patterns. This implementation is provider/output-profile-specific and should not be used directly for article images.
- `backend/app/official_account_news_editorial_news_context_demo.py:64-127` — the existing one-off v6 demo has a useful typed `NewsContextPhoto` provenance shape: page URL, image URL, alt/caption/credit, dimensions, checksum, and `rights_status`.
- `backend/app/official_account_news_editorial_news_context_demo.py:190-235` — that demo's downloader intentionally performs an exact-URL, no-redirect bounded fetch, but lacks the acquisition fetcher's DNS/public-resolution protection. It is not a production source-media fetcher.
- `backend/app/official_account_news_editorial_news_context_demo.py:290-316` — its full JPEG decode, animation, dimensions, and checksum checks are reusable validation ideas.

Recommended new `backend/app/infrastructure/ingestion/source_image_fetcher.py` contract:

- Resolve relative `src`, a bounded `srcset`, and explicitly supported lazy-load attributes against the detail response's final URL.
- Validate the complete bounded descriptor set before starting image I/O. Reject `data:`, `blob:`, `file:`, userinfo, IP literals, unsafe ports, traversal, fragments, and non-HTTPS URLs.
- Keep article hosts and image hosts separate. Same approved host/path is the safest initial default. A CDN is eligible only when an immutable source-version media-host/path allowlist explicitly permits it; do not silently widen the article crawl allowlist.
- Validate every redirect hop or, for the smallest slice, reject redirects. Never let the HTTP client follow redirects automatically.
- Accept only JPEG, PNG, and WebP; require response MIME, file signature, and full non-animated decode to agree. Reject SVG, GIF/animation, icons, logos, avatars, QR-like tiny assets, and tracking pixels.
- Bound request count (two per article), redirects, timeout, response bytes (suggested 15–20 MiB), dimensions (suggested maximum edge 8192 and 32 MP), and minimum useful dimensions (suggested 320×180). Exact limits should be constants covered by tests or source-version settings.
- Preserve original bytes, including an existing publisher watermark; do not crop, re-encode, or remove marks during acquisition.
- Treat alt/caption/credit as bounded, escaped, untrusted source text. A caption is context, not independent evidence.

Deduplicate normalized URLs before fetch and checksums after fetch within one article, retaining the earliest descriptor with the richest caption/credit. The object store may deduplicate identical bytes globally, but database provenance rows must remain per source page/occurrence. Two publishers serving the same file are still two provenance records.

Important URL caveat: `FetchedResponse` currently persists a `safe_url()` representation that strips query strings. Some media CDNs require signed query parameters, while the requirement is to retain the exact image URL. The implementation must define a separate bounded exact-media-URL persistence policy, including redaction of known credential parameters, or reject signed-query media in the MVP. Exact unsafe URLs must not enter logs.

### 3. Persistence and current Alembic head

`conda run --name edu-ai alembic heads` was run from `backend/` and returned one unique head: `20260824_0035 (head)`. `backend/alembic/versions/20260824_0035_ip_asset_personal_library.py:9-11` confirms its parent is `20260824_0034`.

- `backend/app/infrastructure/db/models.py:318-352` — `SourceSnapshotModel` stores immutable list/detail payload provenance and object-store metadata. Its kind check currently permits only `list` and `detail`.
- `backend/app/infrastructure/db/repositories.py:489-539` — snapshot persistence uses source version, kind, requested/final URL, and checksum for race-safe provenance-key idempotency.
- `backend/app/infrastructure/storage/minio_snapshot_store.py:16-61` — immutable content-addressed storage under `source-snapshots/sha256/...` is suitable for original image bytes, but the port currently lacks a verified read operation needed by downstream local rendering.
- `backend/app/infrastructure/db/models.py:355-409` — `EvidenceCandidate` owns a primary text/detail snapshot; it has no media relationship.
- `backend/app/infrastructure/db/models.py:610-669` — `ArticleOccurrenceModel` retains candidate, observation, detail snapshot, source version, page URLs, and observed timestamps. This is the correct lineage anchor because exact-content dedup can make multiple source occurrences point to one candidate.
- `backend/app/infrastructure/db/repositories.py:542-613` — candidate content dedup confirms that media must not be attached only to the deduplicated candidate.

Recommended additive migration: `backend/alembic/versions/20260825_0036_selected_news_source_media.py`, with `down_revision = "20260824_0035"` after rechecking the head immediately before implementation.

The minimum schema is:

- Widen `source_snapshots.kind` to include `media`, without changing historical rows.
- Add `source_article_media` with UUID id; candidate, article occurrence or observation, article detail snapshot, nullable media snapshot, and source-version foreign keys; stable ordinal and extraction key; relationship; exact source page/resolved image/final image URLs; alt/caption/credit; extraction/parser version; status (`discovered`, `ready`, `failed`, `rejected`) and typed failure code; MIME, byte size, checksum, width, height, retrieval time; request/provenance fingerprint; and `rights_status` defaulting to `publish_permission_unverified` (or an equally conservative `unknown`).
- Enforce one stable descriptor per article snapshot and ordinal, plus a race-safe provenance uniqueness rule. Do not globally unique the checksum at the provenance-row layer.
- Add `material_package_source_media` with material package id, source-media id, stable ordinal, and selection reason. The link is the immutable record of what crossed into the package.
- Add nullable `source_article_media_id` to `official_account_local_media` and extend its exact-one-source constraint from three source kinds to four. Existing rows and slot semantics remain valid.
- Widen the official-account article version check for the new exact numeric version. `backend/app/infrastructure/db/models.py:3808-3874`, especially `:3848-3852`, currently bounds the article schema family; do not reuse an old version number.

The downgrade should refuse while new source-media, package-link, or new-version official-account artifacts exist, following the repository's data-bearing migration convention.

### 4. Governed selection lineage into material packages

- `backend/app/infrastructure/db/models.py:1226-1345` — event cluster versions bind a representative normalized article and memberships.
- `backend/app/infrastructure/db/topic_selection.py:478-560` — topic loading joins the representative normalized article to its evidence candidate and uses memberships/occurrences/source versions for source diversity and priority.
- `backend/app/infrastructure/db/topic_selection.py:777-899` and `backend/app/domain/topic_selection.py:476-515` — the governed `TopicCandidate` is constructed from stored event/version/text/facts/features and contains no media.
- `backend/app/application/services/topic_selection.py:182-229` — topic selection loads stored candidates, decides, and persists the selected event/version. This service must remain network-free.
- `backend/app/infrastructure/db/models.py:1366-1466` — daily selection preserves the selected event/version identity.
- `backend/app/infrastructure/db/models.py:2666-2785` — copy-run origins retain daily/slot selection plus selected event/version.
- `backend/app/infrastructure/db/models.py:3560-3644` — material packages already freeze topic/copy/source/brand/validation/audit snapshots.
- `backend/app/application/services/material_package.py:3535-3633` — the current source snapshot is assembled from claim/evidence bindings and retains candidate, passage, occurrence, detail snapshot, exact source URL, source tier/date, and quote.
- `backend/app/application/services/material_package.py:3651-3709` — copy/version snapshots become the accepted material-package input.

The material-package projection should join `ready` source media only through the package's already-bound evidence occurrence/detail snapshot. It must not take “any image attached to the event,” the newest image from the publisher, or another article's image. A photo remains contextual media and cannot satisfy a claim-evidence requirement.

### 5. Coexistence with approved/generated IP images and byte compatibility

- `backend/app/domain/official_account_local.py:154-183` — the present source snapshot expects one material/fixture source image and has no news-source media list.
- `backend/app/domain/official_account_local.py:228-297` — Article Package image blocks and media slots define body ordinals 0–4 plus cover.
- `backend/app/domain/official_account_local.py:346-423` — the current persisted media selection snapshot is catalog-specific and supports deterministic-tag or multimodal-embedding selection. It should not be widened in place.
- `backend/app/domain/official_account_local.py:603-644` — the Article Package limits media to its current slots and exact versioned invariants.
- `backend/app/application/ports/official_account_local.py:198-221` — resolved media currently supports artifact, fixture, catalog, and generated origins but not source-article provenance/rights.
- `backend/app/infrastructure/db/official_account_local.py:708-889` — fixture mode provides three images; a live material package currently provides one primary image artifact as a safe degradation path.
- `backend/app/application/services/official_account_local.py:628-740` — live current versions load approved brand-catalog candidates and persist selection before rendering.
- `backend/app/application/services/official_account_local.py:815-975` — selected candidates fill body slots; successful generation replaces those selected body refs, while the material primary image remains the cover.
- `backend/app/infrastructure/db/models.py:4167-4271` — local media enforces exactly one of image artifact, fixture, or generated source plus body/cover ordinal rules.
- `backend/app/infrastructure/db/models.py:4347-4398` — draft body-image association already uses media role and ordinal, so mixed origins do not require a second body-slot system.

Create a new discriminated `ArticleMixedMediaSelectionSnapshot` and a new exact article/media-plan/renderer/adapter version family. Do not add fields to the historical catalog snapshot and do not route old rows through new rendering logic. Each mixed assignment records final section/ordinal and is one of:

- `source_news`: source-media public id/checksum, exact source page and image URL, caption, credit, rights state, and `context_only_not_evidence=true`.
- `approved_ip` or `generated_ip`: the existing catalog reference, catalog/publication checksum, selection method, and generated artifact linkage.

Keep the existing total of three to five body slots. Use at most one or two `ready` source images and retain at least three IP/brand slots when enough approved assets exist. If no eligible source image exists, produce the exact new-version deterministic IP-only fallback; if one exists, use one. Image generation runs only for IP-designated slots and must never overwrite a source-news slot.

The app, not the language model, chooses image URLs, count, order, and provenance. A new renderer may show exact source caption/credit and a rights warning, but must not use a caption to introduce an unsupported factual claim. Historical short-copy, material, WeCom, official-account version, and v6 offline-demo bytes remain untouched.

The prior v6 context-photo work is deliberately a one-off compatibility-preserving demo. `.trellis/spec/backend/official-account-editorial-repackage.md:441-552` freezes the five-slot Article Package, places two pinned MOE photos in an adjacent typed projection, preserves original bytes, labels them `context_only_not_evidence` and `publish_permission_unverified`, and supports zero-network cache/tests. It is a useful proof of provenance and warnings, but does not satisfy the future acquisition/selection pipeline and should not be edited to do so.

### 6. API, OpenAPI, and local workbench

- `backend/app/schemas/material_package.py:216-231` — material-package output exposes generic source dictionaries. The first vertical slice does not need a broad public material-package API change if only the official-account local workbench consumes the carried media.
- `backend/app/schemas/official_account_local.py:132-154` — `OfficialAccountMediaResponse` currently omits source page, caption, credit, rights, and provenance kind.
- `backend/app/schemas/official_account_local.py:253-265` — official-account detail already returns media, body images, selection, generation, and draft state.
- `frontend/src/features/official-account-local/api.ts:372-439` — the frontend parser normalizes current media/selection responses.
- `frontend/src/features/official-account-local/OfficialAccountLocalPanel.tsx:623-790` — the panel renders article sources and its gallery/captions; this is the smallest UI surface for origin and rights disclosure.

Add only the safe optional response fields required by the local workbench: `provenance_kind` (`source_news`, `approved_catalog`, `generated_ip`, `material_primary`, or `fixture`), `source_page_url`, `caption`, `credit`, `rights_status`, and `context_only_not_evidence`. Do not expose MinIO keys, internal storage paths, or secret-bearing original request metadata. The panel should label “新闻原图” versus “公司 IP 图,” link to the exact source page, show caption/credit, and display a prominent “发布权限未验证” warning.

Regenerate `backend/openapi.json` and `frontend/src/lib/api/generated/schema.d.ts` in the same contract change. They are generated, high-collision files; inspect overlapping diffs first.

Local review may display an immutable source snapshot with its warning. Copy-ready/publish-ready state must fail closed while a selected source image has unverified publication permission, or a separately versioned export must omit that image. Approval of article copy is not proof of image reuse permission.

### 7. Failure, degradation, and zero-network defaults

Required terminal behavior:

- No own-article image: record or report `not_present`; do not issue an image request; continue topic/copy/material/official flow with IP-only media.
- Unsafe/external URL: store `rejected` plus a typed safe reason; make zero requests for that descriptor.
- Fetch, MIME, decode, size, or dimension failure: keep the accepted article candidate; store `failed` safely; downstream consumers ignore it.
- Timeout: a bounded acquisition GET is safe to retry because it has no provider-side creation effect, but a timeout never becomes `ready` and never implies rights.
- Duplicate within article: select one descriptor deterministically. Identical bytes on different pages may share object storage, but retain both provenance rows.
- Later page/image disappearance: use the immutable stored snapshot and exact checksum; never silently refetch or substitute another image during material/article generation.
- Storage checksum/MIME drift: fail the new run closed; do not replace the asset.
- Unverified rights: allow explicitly warned local review only; block copy-ready/publication or omit in a separately versioned export.

Default fixtures and tests must make zero external requests. Existing reusable test patterns include `backend/tests/contract/test_safe_fetcher.py:38-65` (`httpx.MockTransport`), `backend/tests/contract/test_source_connectors.py:55-96` (all connector fixtures), `backend/tests/unit/test_official_account_worker.py:685+` (refusing unexpected `AsyncClient` network), and `backend/tests/unit/test_official_account_news_editorial_news_context_demo.py:472+` (injected fetch/cache behavior). Add small local PNG/JPEG/WebP fixtures and sanitized article HTML fixtures; do not fetch publisher assets in tests.

Focused tests for the vertical slice:

- Connector contract: inline figure caption/credit, relative URL, bounded lazy/srcset handling, enabled `og:image` fallback, and exclusion of nav/logo/off-domain/data/SVG candidates.
- Safe image fetcher: DNS/private-address rejection, host/path checks, redirect validation, MIME/signature mismatch, declared/streamed byte bounds, dimensions/pixel bounds, animation, timeout, and exact request count.
- Acquisition service: zero/one/two images, article acceptance despite image failure, deterministic maximum, idempotent replay/races, URL/checksum dedup, and no request for rejected descriptors.
- PostgreSQL/migration: unique head/metadata, constraints, occurrence/detail-snapshot lineage, content-addressed byte sharing with separate provenance, clean upgrade, and downgrade refusal with data.
- Material package: only source media from already-bound evidence occurrences crosses the package boundary; snapshots and ordering are immutable.
- Official account: exact new mixed-version invariants, 0/1/2 source-photo cases, three-to-five total body slots, generation limited to IP slots, historical golden bytes unchanged.
- Resolver/API/UI: checksum verification, safe provenance fields, origin labels, rights warning, no storage-path leakage, and no publication call.

### 8. Exact implementation ownership and collision map

Smallest vertical-slice file ownership:

1. Acquisition/source media:
   - `backend/app/domain/entities.py`
   - `backend/app/application/ports/acquisition.py`, or a new focused `backend/app/application/ports/source_media.py`
   - `backend/app/infrastructure/ingestion/connectors.py`
   - new `backend/app/infrastructure/ingestion/source_image_fetcher.py`
   - `backend/app/application/services/execute_acquisition.py`
   - `backend/app/infrastructure/storage/minio_snapshot_store.py`
   - `backend/app/infrastructure/db/models.py`
   - `backend/app/infrastructure/db/repositories.py`
   - new `backend/alembic/versions/20260825_0036_selected_news_source_media.py`
   - connector/fetcher/acquisition/PostgreSQL fixtures and tests.
2. Material lineage:
   - `backend/app/application/services/material_package.py`
   - the new package-media repository/link model and integration tests.
3. Official-account mixed plan:
   - `backend/app/domain/official_account_local.py`
   - `backend/app/application/ports/official_account_local.py`
   - `backend/app/application/services/official_account_local.py`
   - `backend/app/infrastructure/db/official_account_local.py`
   - `backend/app/infrastructure/official_account_media.py`
   - official-account schema/route/domain/service/repository tests.
4. Contract/workbench:
   - `backend/app/schemas/official_account_local.py`
   - `backend/app/api/v1/routes/official_account_local.py`
   - `backend/openapi.json`
   - `frontend/src/lib/api/generated/schema.d.ts`
   - `frontend/src/features/official-account-local/api.ts`
   - `frontend/src/features/official-account-local/OfficialAccountLocalPanel.tsx`
   - its module CSS and focused tests.

Highest-collision files are `backend/app/infrastructure/db/models.py`, `backend/app/infrastructure/db/repositories.py`, `backend/app/application/services/material_package.py`, `backend/app/domain/official_account_local.py`, `backend/app/application/services/official_account_local.py`, `backend/app/infrastructure/db/official_account_local.py`, `backend/openapi.json`, `frontend/src/lib/api/generated/schema.d.ts`, and `OfficialAccountLocalPanel.tsx`. Inspect their current dirty diffs immediately before editing and assign each to one implementer. Also treat `backend/app/core/config.py`, API/worker entry points, compose/env/Makefile/README, and migration-head tests as high-collision task files; the minimum slice can avoid new worker wiring and broad runtime changes.

Do not modify the one-off v6 demo module, `MaterialDraft`/short-copy semantics, WeCom code, or historical renderers. Do not add a web-search provider or a publication call.

## Related Specs

- `.trellis/spec/backend/database-guidelines.md:5-13` — current single-head migration baseline and database rules.
- `.trellis/spec/backend/governance-event-organization.md:96-106` — stored-source-only governance, occurrence provenance, and evidence binding.
- `.trellis/spec/backend/topic-selection.md` — persisted event/version selection boundary.
- `.trellis/spec/backend/content-production.md` — claim/evidence/material-package contracts.
- `.trellis/spec/backend/visual-content-production.md` — generated/approved visual artifact rules.
- `.trellis/spec/backend/official-account-editorial-repackage.md:441-552` — existing v6 adjacent context-photo compatibility contract.
- `.trellis/spec/backend/agent-pipeline.md` — worker orchestration and zero-network fixture conventions.

## External References

None. This research intentionally used only repository code, fixtures, specs, and local migration metadata. No network, provider, image-search, social-platform, WeChat, or WeCom call was made.

## Caveats / Not Found

- The exact publisher DOM patterns for caption and credit are not represented in current fixtures; source-specific selectors must be derived from sanitized local examples before implementation.
- Cross-host publisher CDN policy is not currently modeled. The smallest safe slice should permit same-host media only until explicit immutable media host/path rules are added to source versions.
- Signed-query image URL retention/redaction needs a deliberate security decision; current snapshot URL sanitization strips queries.
- No existing right/licence metadata proves reuse permission. `rights_status` must default to unverified/unknown, and source-page publication must never be presented as permission.
- Suggested file name `20260825_0036_selected_news_source_media.py` is valid only if `20260824_0035` remains the unique head at implementation time. Recheck immediately before creating the migration.
- This note defines the vertical slice but does not authorize live publisher image fetches, paid image generation, or platform publication during tests/local fixture runs.
