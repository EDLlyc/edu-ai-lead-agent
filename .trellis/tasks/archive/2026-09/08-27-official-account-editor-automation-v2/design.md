# 公众号本地自动化与视觉优化 V2：技术设计

## 1. Architecture

V2 继续是批准后状态的只读派生，不新增 worker、provider 调用或数据库 migration。它在现有 V1 旁新增
版本家族，并复用 repository/media resolver 读取 durable snapshots：

```text
run/article/render/draft/media/audits
  -> versioned release policy (manual_only | quality_auto)
  -> immutable release projection
  -> V2 semantic emphasis + layout recipe + context placement plan
  -> V2 body/preflight/content identity
  -> optional exact browser validation report
  -> V2 artifact identity + deterministic ZIP
  -> generated API contract + local workbench/export
```

V1 functions/constants remain callable and unchanged. V2 may live in the same bounded modules when names remain explicit,
or in sibling `_v2` modules if that makes accidental dispatch impossible.

## 2. Release policy

Introduce an enum/config value with a safe default of `manual_only`. The application service receives the policy rather
than reading global settings inside domain code.

- `manual_only`: current approved review and fingerprint checks, V1 behavior.
- `quality_auto`: an existing manual rejection wins and blocks; an existing valid approval produces `manual`; otherwise
  the service derives `machine` from already durable article/render/draft/media quality checks.

The machine decision is a frozen projection, not a fake manual-review row. Its fingerprint hashes policy version, run,
article, render, draft, deterministic audit and media-quality inputs. `release.json` replaces the V1-only assumption in
the V2 bundle; compatibility may retain a nullable/safe `review.json` projection, but it must never label a machine
decision as human.

No provider is called to decide release. An absent/unknown required quality status fails closed with a stable code.

## 3. V2 rendering projections

### Semantic emphasis

Tokenize existing Chinese/ASCII spans without rewriting them. Build candidates from exact substrings already present in
the paragraph, scoring title/digest/heading overlap, numeric expressions, known terms and information density. Select
1--3 non-overlapping 4--15 character spans with deterministic tie-breaking by score, start offset and length. Rendering
escapes each original slice independently. A round-trip helper/test strips markup and proves text equality.

### Context placement

For each context asset, score eligible paragraph/list/quote blocks in its assigned section against alt/caption and source
labels. Select an `after_block_index`; fall back after the first prose block. Resolve collisions in stable ordinal order,
shifting later context images so at least one visible prose block separates every image, including existing body image
blocks. Persist a safe reason code and algorithm version, not raw embeddings or prompts.

### Layout recipe

Classify from structured, local signals only:

- context/news source present -> `news_analysis`;
- list/step density -> `tutorial_list`;
- quote/case signal -> `case_opinion`;
- otherwise `analysis`.

Recipe selects only Xiaosai-blue components. It controls title size band, TOC card width/size, callout alternation and
minor spacing. Deep-blue anchor cards are capped at five; additional callouts use the registered shallow/left-rule
variant. The output remains one section fragment with inline allowlisted CSS and `span leaf`.

## 4. Identity and browser validation

Separate two hashes:

- `content_fingerprint`: release input, article, theme/recipe/emphasis/placement versions, body SHA and media hashes.
- `artifact_fingerprint`: content fingerprint plus the canonical mobile-validation record hash.

Runtime artifacts use canonical `not_run`; browser acceptance first tests the content body/media, emits a report binding
content fingerprint/body SHA/media hashes, then the local exporter builds a final `passed` artifact and ZIP. Therefore
no artifact fingerprint can name two byte variants. API/runtime never imports a fixture report from another run.

## 5. API and frontend

Extend generated schemas with release kind/policy, content fingerprint, recipe, placements and mobile report binding.
Keep the existing development-only GET resource model. The workbench:

- says `自动质量放行` versus `人工批准` explicitly;
- shows each news image's section/block placement and source/rights warning;
- distinguishes runtime `not_run` from exact fingerprint `passed`;
- keeps clipboard/download as browser effects and does not add publish controls.

## 6. Fixture and export

Use only repository-owned/local fixture bytes. The fixture includes at least three IP body assets, one news context
asset and one cover. It may use a checked-in deterministic test image or an existing approved local source asset, but
tests never fetch it over HTTP. The export writer remains non-overwriting and content-addressed.

## 7. Compatibility, rollout and rollback

- Feature flag plus release-policy setting gates V2; `manual_only` is the immediate rollback.
- No database migration or durable row mutation is required.
- Do not edit historical renderer/export dispatch or V1 constants/goldens.
- High-collision route/schema/OpenAPI/frontend/spec files require local diff inspection immediately before patching.
- WeChat/WeCom/model/Embedding/image/news adapters are never constructed by default tests or export.

## 8. Security and failure semantics

All text stays escaped, source links remain HTTPS allowlisted, images remain controlled relative assets, and ZIP paths
remain normalized. Machine release records contain no prompts/provider bodies/private paths. Unknown quality states,
hash drift, mismatched mobile reports and placement inconsistencies fail with typed stable codes.

## 9. Block-semantic IP reference conditioning

The generated body-visual flow is distinct from direct catalog reuse:

```text
exact Article block -> bounded scene brief/query -> approved-catalog semantic selection
  -> selected Xiaosai/Sai Xiansheng publication bytes -> ImageReference input
  -> generated 3:2 scene -> output validation/IP visibility -> persisted media -> V2 handoff
```

The existing production owner remains `official_account_visual_generation`: its V3 plan binds the exact block,
reference public identity, normalized provider-input checksum, selector method, prompt version and output profile.
Qwen3-VL complete-index retrieval chooses references before the image client is constructed. A disabled/unavailable
semantic provider may use one declared deterministic whole-plan fallback, but the lineage must retain the truthful
selection method and may never claim an embedding call that did not occur.

The V2 acceptance fixture consumes a frozen reference-conditioned visual map rather than the generic body fixture.
Each row binds one generated body byte stream to its Article block and one or more safe approved reference projections,
including character labels. Fixture validation checks manifest/path/hash/dimensions, both-character set coverage and
non-duplication before building Article/media snapshots. No private path, raw asset ID, vector, prompt or provider body
enters Article/API/export. A fresh final directory and mobile report are required because body/media hashes change.

## 10. Weekly three-article edition

The weekly unit is an aggregate above three complete V2 handoffs, not a new Article schema and not a reuse of the
daily morning/noon/evening content slots:

```text
stored governed candidates -> existing eligibility/veto/score
  -> weekly role preference (official_anchor | industry_trend | application_case)
  -> three distinct ready article runs
  -> three independently finalized V2 handoffs
  -> immutable weekly index/manifest/ZIP
```

A pure versioned policy owns the `Asia/Shanghai` weekly boundary, one due instant, the seven-day primary window,
the bounded 14-day official lookback, exhaustive role order and deterministic fallback reasons. Source authority is
an explicit stored projection (`organization_type` / authenticated priority policy), never title matching. Industry
and application affinity consume the existing editorial cohort, content signals and product-direction projections
only after the existing topic score says the candidate is eligible. Role assignment never changes a veto or score.

The local aggregate accepts exactly three finalized V2 artifacts plus their safe selected-news projections. It
requires distinct event/version, run, Article/content/artifact and child-ZIP identities; validates the child manifest,
mobile `passed`, `quality_auto` release and local-only/unpublished truth; then copies each child tree byte-for-byte
under an ordinal/role directory. The aggregate fingerprint binds week start, schedule/policy identity, ordered safe
selection metadata, every child fingerprint and ZIP hash. Atomic no-clobber installation and deterministic archive
rules match the existing handoff writer.

This phase adds no social adapter and does not reinterpret the three daily content slots. Default tests use synthetic
governed candidates and local child bytes with sockets blocked. A production scheduler may invoke the same due/policy
functions, but the current delivery remains a development-only local weekly batch.

## 11. Homepage pin operator handoff

The weekly aggregate adds a pure presentation policy above the three immutable children:

```text
official_anchor   -> pinned_primary -> existing wide cover -> large-card candidate
industry_trend    -> standard       -> existing wide cover -> standard-thumbnail candidate
application_case -> standard       -> existing wide cover -> standard-thumbnail candidate
```

Each row binds its intent and purpose to the child's existing cover path, checksum and actual dimensions. The source
profile remains the V2-validated 2.35:1 cover; a center-safe/system-crop note expresses composition intent without
claiming knowledge of, or control over, WeChat's homepage crop. The projection is present in the JSON index, manifest,
HTML index, README and operator checklist. Child trees and child ZIPs remain byte-identical.

Publication and homepage pinning use a separate, versioned operator-state aggregate. The immutable weekly bundle
contains only its deterministic initial `not_published` projection. A typed `publication_confirmed` event, carrying an
event UUID, timezone-aware occurrence time, safe operator reference, exact batch identity, exact official Article
identity and an `mp.weixin.qq.com` publication URL, may produce `awaiting_manual_pin`. A second typed
`homepage_pin_confirmed` event bound to the same identities may produce `confirmed`. State transitions are linear,
event IDs cannot repeat, publication/pin times cannot run backwards and every projection has a fingerprint over its
complete audit history.

Post-export transitions are written as fresh deterministic sidecar JSON files whose names include the state
fingerprint. They never rewrite the weekly directory, archive, manifest, index or children. The operator checklist is
deterministic and instructs the operator to use the MP backend path
`群发功能 -> 已发送 -> 找到文章 -> 更多 -> 置顶到公众号主页`, then record explicit confirmation. The code does
not construct a social client, invoke public/private WeChat endpoints, automate a browser or infer success from local
state. WeChat owns the actual homepage UI and crop.

## 12. Role-distinct offline visual fixture

The weekly fixture owns a portable deterministic compositor. It reads tracked 3:2 science-scene backgrounds and the
approved local Xiaosai/Sai Xiansheng asset library, then produces metadata-free JPEGs in memory. Each role has a fixed
palette, background order, IP reference order, safe-zone placement and 2.35:1 cover source. The output lineage records
`deterministic_fixture_semantic` selection and `not_claimed` provider execution; runtime counters remain zero. Synthetic
context placeholders are explicitly labelled local/context-only and do not claim to be acquired news photographs.

Before a child is built, its Article image alt, media-selection projection, exact target-block lineage and output hashes
are rebound to that role's visual set. The aggregate decodes every cover/body payload, verifies manifest dimensions and
hashes, fingerprints decoded RGB pixels, and rejects repeated cover hashes, repeated cover pixel fingerprints or repeated
ordered body-media hash or pixel sets across roles. This validation applies equally to the CLI path loading finalized
children and also requires all nine body SHA/pixel fingerprints to be globally unique, so a one-image reuse or distinct
labels, paths or metadata cannot conceal duplicate pixels. The fixture bootstrap uses no ignored historical `output/`
directory. The manifest identity is bumped when the exact zero-call projection is added, so changed manifest/ZIP bytes
cannot retain an earlier batch fingerprint.

## 13. Opt-in live distinct-news run

The live path is a sibling development CLI, not a change to the default fixture or scheduler:

```text
exact three-role live-input JSON -> registered source profile + SafeHttpFetcher
  -> existing HtmlConnector extraction + same-host SourceImageReference discovery
  -> SafeSourceImageFetcher (max two eligible rasters per source)
  -> role-owned Article source/claim/sections/context media + local IP visual set
  -> three independently finalized V2 children -> unchanged weekly aggregate/writer
```

The live-input schema is duplicate-key rejecting and exact-field. A small code-owned registry binds every accepted
source key to organization type, publisher, HTTPS hosts/path prefixes, crawl-policy record and extraction selectors;
the JSON cannot widen those boundaries. The official role requires the registered government type. Page fetches reuse
the production SSRF, redirect, timeout and response-size controls. Image discovery and fetching reuse the production
same-host, query-free, MIME/byte/dimension/decode policy. A live run never falls back to fixture context bytes.

Each fetched record freezes requested/final/canonical URLs, response hash/size/media type/fetched time, extracted title,
published time, bounded clean text hash and one exact source quote. It also records every accepted news image's original
URL, response metadata, decoded dimensions, caption/credit and unverified-rights/context-only boundary. Event and version
UUIDs derive from canonical URL plus page hash, so changed source bytes produce a new event version. Three canonical URLs,
page hashes, evidence IDs and context-image hashes must be distinct before child construction.

Live child construction starts only from the V2 structural shell. It replaces title, digest, lead, every prose claim,
source projection, news-context snapshot and media bytes for that role, then recomputes Article/body/media/release/mobile
and child ZIP identities. Role-specific deterministic IP visuals remain local and make no model/Embedding/image-provider
claim. The final bundle adds an immutable live acquisition audit. Counters report exact page and image requests; all
model, Embedding, image-generation, WeChat and WeCom counters remain zero. Any fetch/extraction/identity error aborts the
batch rather than substituting a fixture source.

## 14. Theme-cluster live input V2

The V1 parser and build path remain frozen and operational. A version-discriminated V2 input adds one explicit weekly
theme and an ordered source cluster per article:

```text
weekly theme
  -> official/policy article:  primary government page + supporting page(s)
  -> industry/method article:  primary page + supporting page(s)
  -> application/practice:     primary page + supporting page(s)
  -> acquire every registered page/image independently
  -> bind source-scoped claims/evidence/context media
  -> validate each child at 320/430 -> aggregate weekly bundle
```

The duplicate-key-rejecting exact-field schema accepts exactly the canonical three article roles and angle enums. This
bounded MVP contains exactly one `primary` row followed by one `supporting` row per cluster because the existing Article
context snapshot accepts at most two items. A source row retains the V1 URL,
expected title/date/publisher and image URL contract. Editorial article title/digest/lead may express the shared theme,
while every rendered fact unit carries an immutable source key, relation, canonical URL and evidence ID. The durable
Article primary source remains the cluster primary for backward compatibility; a versioned source-cluster projection
alongside the Article records all supporting provenance and is rendered into body source notes.

Acquisition flattens the three clusters only for bounded concurrent/sequential fetching, then reconstructs the exact
input order. Existing registered profiles, safe page fetcher, connector extraction and safe image fetcher remain the
only network boundary. The V2 validator requires one government primary for the official cluster and globally unique
canonical URL, page hash, event/version identity, evidence ID and accepted context-image hash across the complete batch.
Source records and media rows carry an owning article role and cluster relation; containment assertions reject any
claim, evidence or image referenced by a different cluster.

`live-acquisition.json` audit v3, the child Article JSON/HTML, weekly index and manifest expose the shared theme, article angle,
ordered primary/supporting source summaries, source-scoped evidence and adopted image lineage. The audit records exact
variable `source_pages` and `news_images` calls plus total `news`; it keeps model, Embedding, image-generation, WeChat and
WeCom at zero and records that no social client was constructed. News images remain context-only with unverified publish
permission and preserved source marks.

The named CLI runs the existing local browser validator for every rebuilt child at widths 320 and 430 before weekly
aggregation. A passing observation binds exact body/media/content values, all images loaded, exact preview/copy-root
equality, no overflow and zero browser external requests. MockTransport/resolver tests exercise V2 without network;
the default fixture and V1 behavior are unchanged. A real acceptance input is a tracked allowlisted manifest, and every
run installs a fresh no-clobber output rather than rewriting R12 artifacts.

## 15. Opt-in WeChat Official Account draft adapter

The WeChat MP boundary is a new sibling to the existing WeCom infrastructure. A small application protocol owns typed
requests and safe receipts; the infrastructure client alone owns `api.weixin.qq.com`, stable-token authentication,
multipart encoding, WeChat error envelopes and the in-memory token cache. The default dependency graph does not build
this client. Configuration uses secret fields, an explicit enable switch and `draft_only` mode; production publication
is intentionally absent.

```text
validated finalized V2 article + exact local media resolver
  -> verify local-only HTML/media/hash/path/quality identities before network
  -> upload each referenced body JPEG/PNG via media/uploadimg
  -> replace exact relative src values with returned HTTPS WeChat image URLs
  -> upload the bound wide cover via material/add_material?type=thumb
  -> draft/add with one article
  -> safe receipt (no token/secret, not_published remains true)
```

The token path uses `cgi-bin/stable_token`; its cache expires early from the server-provided TTL and a request retries
only once for the explicit invalid/expired-token errcodes. Each HTTP response is byte bounded and parsed with duplicate
key rejection. Non-2xx, non-JSON, malformed success fields and non-zero WeChat errors map to stable typed failures whose
messages contain endpoint labels and errcodes but never request URLs, query strings, credentials, token values or raw
provider bodies.

The stable-token cache accepts the documented remaining lifetime through 7200 seconds and coalesces concurrent rejection
of the same stale token into one `force_refresh=true` request. HTTP 401/403 alone is not an explicit WeChat token errcode
and therefore never triggers the refresh replay. Draft validation follows the current official limits: title at most 32
characters, author at most 16, digest at most 120, body fewer than 20,000 characters and below 1 MiB, source URL at most
1 KiB, inline JPEG/PNG below 1 MiB, and permanent JPEG thumb below 64 KiB.

The draft service receives already validated article metadata and a closed set of local media descriptors. It parses
only the existing allowlisted HTML shape and rewrites exact local `img src` attributes; it never downloads arbitrary
URLs or accepts data/blob sources. It verifies safe relative paths, no symlink traversal, exact bytes/hash/media type,
one independently bound cover and no missing or unused media before constructing the first network request. Every call
creates one draft article; the canonical weekly role order may be orchestrated as three calls, never one three-article
payload. Draft creation is not publication and cannot advance the local homepage-pin state machine.

All three children, upload filenames, HTML size, immutable ZIP/file/media identities, comment policy and receipt-clock
awareness are validated before the first weekly provider write. Cover and oversized inline normalization is deterministic
and in-memory; the finalized child directories and archives remain byte-identical.

Contract tests inject `httpx.MockTransport` and a fake clock. They assert exact methods/paths/multipart/JSON, early token
expiry, single refresh, response limits, duplicate-key rejection, timeout/error redaction and three independent draft
receipts. Existing fixtures, local exporters, workers and API routes remain unchanged and construct no WeChat client;
there is no live acceptance until the user supplies credentials and an allowlisted stable egress IP.
