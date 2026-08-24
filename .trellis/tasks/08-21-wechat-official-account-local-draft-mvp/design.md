# Design — 微信公众号本地草稿 MVP

## Decision

新增一条与朋友圈短文和企业微信交付隔离的 `official_account_local` vertical slice。真实 LLM 只负责
生成和审校严格结构化的长文 Article Package；确定性 renderer、本地媒体 adapter 和本地 draft adapter
完成其余步骤。API 只 enqueue，独立 opt-in worker 执行长任务，PostgreSQL 保存权威状态。

```text
MaterialPackage / sanitized fixture
  -> OfficialAccountArticleRun (durable enqueue)
  -> ArticleGenerator (fake or configured Zhipu)
  -> deterministic claim/schema validation
  -> ArticleAuditor (fake or configured Zhipu)
  -> immutable ArticleVersion
  -> deterministic WeChatHtmlRenderer
  -> immutable RenderVersion with media placeholders
  -> deterministic MediaPlan (1--5 body, target 3--5 -> cover)
  -> LocalMediaAdapter(each body ordinal -> cover)
  -> LocalDraftAdapter(resolved HTML + cover ID)
  -> LocalDraft ready / result_unknown
  -> safe API projection + sandboxed browser preview
```

## 1. Boundaries and configuration

Use a dedicated settings namespace:

- `OFFICIAL_ACCOUNT_LOCAL_ENABLED=false` gates API capabilities and the Compose profile;
- worker enabled/poll/concurrency/lease/heartbeat/max-attempt settings follow existing bounded job patterns;
- prompt/schema/rule/renderer/style/local-adapter versions are explicit settings or frozen constants;
- default author is `赛先生`; target 1800--2600 Han characters, hard range 1200--4000;
- `live` requires `AI_PROVIDER_MODE=zhipu`, a validated HTTPS base URL and server-side key;
- `fixture` works while the AI provider is disabled and never creates an HTTP client.

Do not add `WECHAT_*`, AppID, AppSecret, token, host, IP whitelist or publish settings. The feature's
name and API projection always include `local`/`simulation` so a future real adapter cannot be confused with it.

## 2. Source and domain contracts

### Source union

The create request is a discriminated source plus generation mode:

```json
{
  "source": {"kind": "material_package", "material_package_id": "uuid"},
  "generation_mode": "live"
}
```

Fixture uses `{"kind":"fixture","fixture_id":"official-account-article-v1"}` and requires
`generation_mode=fixture`. Database checks enforce this pairing and an XOR between material package FK and
fixture ID.

A material package is eligible only when its package/image state is complete enough for manual use, copy
validation passed, copy audit accepted, image validation passed, configured image audit did not reject, and
manual review is not `rejected`. It may still be `pending`, because the new output itself is a draft for human
review; inherited review status remains visible.

### Versioned Article Package

Use frozen Pydantic/domain values with `extra="forbid"`:

- metadata: title, digest, author, lead, conclusion;
- 3--7 ordered sections with heading and ordered blocks;
- block kinds limited to paragraph, bullet list, quote/callout and application-injected image slot;
- claims with stable local key, text, `external_fact|brand_statement|opinion`, and typed source/brand IDs;
- block claim references; source projection; historical v1 has one body-media slot; current v2 has 1--5 ordered
  body-media slots plus one cover slot;
- inherited topic/source/brand/quality summary and version bundle.

The model never controls URLs, image IDs, media count/order, HTML, CSS or style names. A versioned deterministic
media planner chooses up to five distinct approved candidates and distributes their slots after distinct sections.
For three or more candidates it targets `min(5, max(3, section_count - 1))`; fewer candidates produce an explicit
safe degradation and never duplicate a checksum. Candidate order uses only pinned policy version, review/validation
status, role/topic tags, aspect suitability, priority, checksum and stable source ID. Every referenced ID must be a member of the
input snapshot; external facts require evidence only, brand statements require brand IDs only, and opinions
must not claim either binding type.

Current identities must be bumped for the changed contract (Article schema v2, media-plan v1, renderer v5 and
local adapter v3). Literal historical schema/renderer/adapter identities retain their prior one-body-slot behavior,
HTML bytes, fingerprints and recovery semantics. Mixed or unknown identities fail closed.

Canonical JSON uses stable key/order rules and yields `content_fingerprint=sha256(canonical_payload)`.
Request identity also includes source fingerprint, generation mode, provider/model, prompt/schema/rule,
length policy and author. Replay returns the existing run and never performs another model call.

## 3. LLM generation and audit

Define application ports `OfficialAccountArticleGenerator` and `OfficialAccountArticleAuditor`. Implement
deterministic fake adapters plus a Zhipu/OpenAI-compatible adapter that reuses the existing low-level retry and
JSON-envelope utilities. Do not import the private short-copy client or alter `MaterialDraft` behavior.

The live adapter uses `temperature=0`, disabled thinking, `response_format=json_object`, bounded input/output,
HTTPS/no-redirect transport and existing provider error normalization. It records only provider/model, a safe
provider request ID, usage, latency, correction count and request fingerprint. Raw prompts/responses never leave
the adapter.

Generation prompt data is canonical JSON inside escaped, explicit data boundaries. It contains only the bounded
material package topic/copy, evidence quotes, source metadata and brand chunks needed by the existing bindings.
Instructions state that source/brand text is untrusted data, not executable instructions.

After schema parse, deterministic validation runs before audit. The auditor receives the structured article and
the same bounded evidence/brand allowlists and returns an allowlisted verdict. One generation and one audit are
the normal path; schema correction follows the existing maximum, while audit rejection is persisted as
`review_required` without automatic content regeneration.

## 4. Deterministic HTML renderer

MVP renders only Article Package v1. Use standard-library escaping and fixed builders, not a general HTML parser:

- allowlisted output tags: `section`, `p`, `h1`, `h2`, `strong`, `em`, `blockquote`, `ul`, `ol`, `li`, `span`,
  `img`, `a`, `br`;
- model/source text is always escaped;
- inline styles come only from a versioned static token map;
- source links come only from validated persisted `https` URLs and receive safe `rel`/referrer attributes;
- images are emitted as deterministic media-slot placeholders, never model-supplied `src`;
- scripts, event attributes, iframe, forms, external stylesheet/font URLs, `data:`/`javascript:` links and arbitrary
  attributes are structurally impossible.

Persist an immutable canonical content fragment and renderer/style/template versions. Local draft assembly
replaces every exact placeholder token with the matching ordinal's recorded local-media URL, verifies no placeholder
or extra replacement remains, and persists
the resolved fragment under a separate fingerprint. This preserves the future route where a real adapter replaces
the same slots with WeChat-returned URLs.

## 5. Local media and draft adapters

`OfficialAccountMediaAdapter` accepts a validated source descriptor, role, ordinal and request fingerprint.
The local implementation does not upload or duplicate provider output. It creates a role-scoped, content-addressed
record referencing the already verified image artifact (or bundled fixture image) and returns a stable local media
ID plus controlled API URL.

Each body image and the cover are separate calls and rows. New body ordinals are bounded to 0--4, cover remains
ordinal 0, and duplicate body checksums are rejected. Unique constraints include role/ordinal, preventing a cover ID
from satisfying a body slot. A draft-to-body-media association records every resolved body ordinal while the legacy
`body_media_id` continues to identify ordinal 0 for historical compatibility. The media download endpoint revalidates stored
metadata/signature/checksum and never returns MinIO internals.

The fixture catalog contains only repository-owned immutable PNG descriptors with expected checksum, byte size,
dimensions, semantic tags and explicit publication approval. Selection and byte reads are local and deterministic.
Live mode always includes the material package's accepted image artifact and may use additional candidates only when
they already have typed approved lineage; without them it safely produces fewer images. It never runs retrieval,
generation or network fetching inside this slice.

`OfficialAccountDraftAdapter` accepts resolved content HTML, title/digest/author, body media and cover media ID.
The local implementation returns `local-draft-<fingerprint-prefix>` with `simulation=true`; it performs no HTTP.
The port deliberately resembles future draft creation but has no token or account parameters.

## 6. Durable workflow and retry semantics

Normal stages:

```text
queued -> generating -> validating -> auditing -> rendering
       -> staging_body_media (each expected ordinal) -> staging_cover -> creating_local_draft -> ready
```

Public run status is `queued|running|review_required|ready|failed|result_unknown`; `current_stage` preserves detail.
The worker claims with `FOR UPDATE SKIP LOCKED`, lease token and heartbeat, then executes each external/adapter step
outside a transaction. Each successful artifact is committed before the next step.

| Stage | Retry rule |
| --- | --- |
| live generate/audit transient provider error | bounded retry with same fingerprint; schema/identity/input errors terminal |
| deterministic validation/audit rejection | `review_required`; no automatic regeneration |
| render | deterministic retry; reuse accepted article version |
| body/cover local media | deterministic per-ordinal retry; reuse existing role/fingerprint record and stage only missing ordinals |
| local draft confirmed failure | bounded retry with same fingerprint |
| local draft ambiguous result | `result_unknown`; never automatic retry |

An explicit retry endpoint reopens only retryable `failed` runs and resumes at the first missing/inconsistent stage.
It refuses `ready`, active, review-required and result-unknown runs. Test adapters inject stage failures and ambiguous
draft outcomes without exposing a public failure-injection API.

## 7. Persistence model

Create additive PostgreSQL tables under an `official_account_` prefix:

1. `official_account_article_runs`: source union, generation mode, unique request fingerprint, public status,
   current stage, active artifact IDs, attempt/availability/lease/heartbeat, safe error and timestamps.
2. `official_account_article_versions`: run/version, canonical payload JSONB, content fingerprint, provider/model,
   generator/auditor/version identities, validation/audit snapshots and bounded usage/latency.
3. `official_account_article_attempts`: stage/capability/ordinal, status, request fingerprint, safe provider identity,
   request ID, usage/latency, error code and bounded safe metadata.
4. `official_account_render_versions`: article version FK, canonical placeholder HTML, renderer/style/template versions,
   byte size and unique render fingerprint.
5. `official_account_local_media`: render/source image lineage, strict `body|cover` role, bounded ordinal, immutable descriptor,
   stable local media ID, unique request fingerprint, status and safe error.
6. `official_account_local_drafts`: render FK, legacy primary body FK, cover media FK, resolved HTML, stable local draft ID, unique request
   fingerprint, `simulation=true`, state/error and timestamps.
7. additive draft/body association: draft FK, body-media FK and exact ordinal, backfilled for historical ordinal 0.

Use typed FKs for material package/image/article/render/media/draft lineage and check constraints for status/role/XOR.
JSONB is bounded by application schemas and is not used instead of core relationships. The Alembic migration is
deterministic and tests clean upgrade to head plus metadata parity against real PostgreSQL.

## 8. API and preview security

Add an `official-account-local` router:

```text
GET  /api/v1/official-account-local/capabilities
GET  /api/v1/official-account-local/article-runs
POST /api/v1/official-account-local/article-runs
GET  /api/v1/official-account-local/article-runs/{run_id}
POST /api/v1/official-account-local/article-runs/{run_id}/retry
GET  /api/v1/official-account-local/media/{media_id}
GET  /api/v1/official-account-local/drafts/{draft_id}/preview
```

Create/retry return `202` + durable ID/Location. Detail returns structured article text, safe source/claim binding,
quality/version/usage projections, ordered body-media URLs plus the compatibility primary body, preview URL and simulation state; it omits canonical/resolved raw
HTML, object paths, brand chunk bodies and provider content.

The preview endpoint wraps the persisted resolved fragment in a fixed document and sends CSP (`default-src 'none'`,
same-origin image, inline static style only, no base/form/object), `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer` and private/no-store caching. It is the only HTML response.

## 9. Frontend

Add `frontend/src/features/official-account-local/` with generated wire consumption, pure view-model mapping,
TanStack Query keys/hooks, bounded polling and focused components. Lazy-load it only for development when
`VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED=true`.

The panel contains a permanent “本地模拟，未同步公众号” boundary banner, eligible material selector, explicit
“调用模型生成长文” action, separate fixture action, run list, stage timeline, article/source/quality/version detail,
an ordered body-image gallery/selection explanation, cover media and a mobile-width iframe whose `src` is the preview
URL and whose `sandbox` has no permissions.
There is no `dangerouslySetInnerHTML`, publish/send/login/account/secret state or local-storage copy of server data.

## 10. Local runtime

Add an opt-in `official-account-local` Compose worker profile and Make targets. A foreground local-dev command should
bring up infrastructure, migrate, start API/worker/frontend, seed/enqueue the fixture once idempotently, print only
loopback URLs and stop only the processes it owns. A second opt-in live-smoke command accepts a material package ID,
uses existing server-side AI settings and prints only run/provider/model/usage/status summaries.

Default Compose and tests leave the feature disabled. The worker does not construct a Zhipu client for fixture-only
jobs or when live generation is unavailable.

## 11. Compatibility, rollback and risks

- Additive migration/API fields/feature flag mean rollback is disabling the profile and UI flag; existing copy/material/WeCom
  semantics and rows remain unchanged.
- Do not wire this executor into automatic content scheduling. Every live generation begins with an explicit local UI
  or smoke command action.
- One material package may have too little evidence for a long analysis; deterministic/audit gates prefer
  `review_required` over unsupported expansion.
- Before implementation, re-check the dirty worktree and current migration head. High-collision files are config,
  DB models/migration tests, API app/router, OpenAPI artifacts, App.tsx, Compose, Makefile and env examples.
- No real WeChat path exists to roll back; adding one later requires a new task, account verification and fresh spec.

## 12. Validation strategy

- domain/unit: strict historical/current Article Package schemas, deterministic distinct media planning, safe degradation,
  canonical fingerprints, claim allowlists, provider identity, fake adapters, renderer escaping/tag/URL/multi-slot invariants;
- provider contract: MockTransport success, schema correction, malformed/oversized output, timeout/auth/rate limit,
  usage and raw-response redaction;
- PostgreSQL integration: migration/backfill, ordinal constraints, draft/body associations, concurrent enqueue, leases,
  per-ordinal persistence, idempotent replay, partial multi-image restart/resume, role separation and result-unknown non-retry;
- storage/API: descriptor checksum/signature, safe media response, 202/Location, terminal retry rules, preview headers,
  zero publish/credential operations in OpenAPI;
- frontend: generated mapping, explicit live action, fixture flow, polling stop, simulation banner, accessible iframe,
  no publishing controls and no unsafe HTML injection;
- runtime: Compose config/build without credentials, fixture demo with zero egress, opt-in one-run live smoke with a
  configured provider, then full backend/frontend quality gates.

## 13. Refinement design — semantic media, derivatives and human review

### Version boundary

Introduce new current identities for article schema/media plan/renderer/style/template/local adapter/export bundle
and fixture generator/rules as needed. Literal historical identities through renderer v5, media-plan v1, adapter v3
and bundle v2 dispatch to their frozen builders and bytes. Enqueue and restore validate the exact version tuple.

### Deterministic semantic assignment

Extend approved media candidates with bounded `semantic_tags`, `semantic_label`, publication priority and safe
caption/alt templates. Normalize section heading plus a bounded body excerpt locally. Compute an integer score from
exact normalized tag matches, with heading matches weighted above body matches; solve the bounded one-to-one
candidate/placement assignment deterministically and expose only score bands/reason codes, not article/private text.
No embedding, model or network call occurs. Balanced three-slot placement for four sections is `(0, 2, 3)`; the
historical v1 planner remains `(0, 1, 2)`.

### Publication derivatives

Masters remain the existing immutable PNGs. Add versioned derived JPEG/PNG assets created during development with
metadata removed, original pixel dimensions/aspect retained, a documented encoder policy and byte bound. The fixture
catalog pins derivative path/media type/size/checksum/dimensions. Media serving and export choose the extension from
the allowlisted media type and reject mismatches; historical bundles keep their `.png` tree.

### Human review aggregate

Add `official_account_manual_reviews` in a new migration on the actual head. It stores immutable run-scoped final
decision (`approved|rejected`), bounded reviewer label/note, request fingerprint and reviewed timestamp; a unique
run identity makes same-payload replay idempotent and a conflicting decision `409`. Pending is the absence of a row.
Only ready local drafts can be reviewed. Model audit and inherited material review remain separate fields.

Add `POST /api/v1/official-account-local/article-runs/{run_id}/manual-review`. The safe detail projection includes
`manual_review.status`, reviewer label/note and timestamp, never credentials/private paths. The development-only
React panel renders a restrained editorial review rail with accessible decision controls, confirmation language and
terminal feedback. It is not a publish action.

Export has two immutable modes: review bundle for pending/rejected state retains the warning; copy-ready export
requires an approved review row and omits only the warning chrome from reader HTML. Its manifest records approval
identity and `copy_ready=true`; output path/fingerprint/ZIP include review fingerprint. Approval never overwrites an
existing pending bundle.

### Refinement failure matrix

| Condition | Result |
| --- | --- |
| Semantic score ties | Stable priority/checksum/source-ID tie-break; deterministic assignment |
| Candidate has no approved derivative or type/extension/checksum mismatch | Reject candidate; never use master path implicitly |
| Pending/rejected run requests copy-ready export | Fail closed; review bundle remains available |
| Same manual-review payload repeats | Return original immutable decision |
| Conflicting final decision for the same article run | HTTP 409; preserve first review event |
| Review attempted before a ready local draft | HTTP 409; no review row |
| Historical run resumes | Use its pinned single/multi-image and banner/export behavior exactly |

## 14. Multimodal approved-catalog refinement

### Version and ownership boundary

Add a new exact Article v4 / renderer v7 family with
`official-account-media-plan-v3-multimodal-hybrid`, a pinned official-account visual-query and
visual-selector version, v7 renderer/style/template, adapter v5 and review-bundle v4. Keep the
generator/auditor prompt and public-copy rule pair unchanged because the model still returns no
media identity. The media-plan identity implies the frozen query/selector identity and participates
in enqueue and content fingerprints. Literal v1--v6 families omit the new snapshot from canonical
payloads and preserve their exact bytes.

Migration `20260823_0029` advances from the actual `20260823_0028` head, allows Article version 4
and refuses downgrade while v4 rows exist. The immutable Article JSONB owns the bounded selection
snapshot, so do not add a second result table. Reuse the existing isolated `brand_visual_*` vector
tables only for their already documented 41-item approved brand catalog; do not insert material,
fixture, publication-derivative or arbitrary official-account rows into that index.

### Candidate and query data flow

```text
explicit live run + approved material package
  -> generated structured article
  -> load current 41-item approved visual manifest
  -> hard-filter body-publishable candidates
  -> prove exact current qwen3-vl index coverage
  -> section-safe text queries outside DB transactions
  -> complete similarity matrix
  -> deterministic one-to-one assignment
  -> persist Article v4 + selection snapshot
  -> render v7 -> publication derivatives -> local draft
```

Use only approved catalog metadata and verified PNG bytes. Eligibility checks approval, catalog
version, source checksum, body-safe role/kind, byte/signature/dimensions, distinct checksum and a
bounded candidate count. Asset identity remains a 16-character public reference; filenames and
paths never cross the catalog adapter. The material package's validated primary image remains the
cover source and is not silently treated as an indexed catalog vector.

For each balanced placement serialize one query from allowlisted topic title, section heading and
the first 360 normalized body characters. Each query is fingerprinted and passed through the
existing `VisualEmbeddingModel` with the exact Qwen3-VL identity. A new repository preflight proves
complete candidate/catalog/provider/model/dimension/input-policy coverage before the first paid
query; the existing cosine search rechecks coverage after each result to fence races.

For up to five placements and up to 41 candidates, use bounded dynamic programming over placement
bitmasks rather than factorial permutations. Maximize total cosine similarity, then total frozen
integer tag score, then stable priority/source-checksum/public-reference order. Similarity changes
only ordering: it cannot change placement count, section indexes, eligibility or duplicate rules.

### Fallback, persistence and media bytes

The semantic attempt is whole-plan atomic. Disabled configuration, fewer than two eligible
candidates, incomplete/mixed index, any provider or result error, or catalog/checksum change yields
one closed status and discards all semantic scores. Run the previous deterministic tag selector on
the same eligible candidates; do not combine some embedding slots with fallback slots. Provider
calls occur after generation and outside repository transactions, with one attempt per placement
and no correction/retry loop.

Persist before rendering: selector/query versions, `semantic_ready|semantic_unavailable|single_candidate`,
closed unavailable reason, catalog identity/fingerprint, bounded embedding identity, query
fingerprints and ordered assignment records containing public candidate reference, source checksum,
section index, selection method/reason and a bounded similarity band. Persist no vector, raw score,
query text, PNG bytes, path or provider body. Recovery consumes this ordered snapshot and never
requeries the provider after Article persistence.

The catalog adapter resolves the selected asset only at the media boundary, revalidates manifest
identity/checksum, reads the PNG outside transactions and creates a deterministic metadata-stripped
publication derivative under adapter v5. The derivative has its own checksum/type/size/dimensions;
the source master remains unchanged and private. Review-bundle v4 binds the Article selection
snapshot and exports only derivative bytes.

### Runtime, API and UI

Add `OFFICIAL_ACCOUNT_LOCAL_VISUAL_SEMANTIC_ENABLED=false`. It is independent of ordinary visual
retrieval flags and cannot make default fixture/API startup construct an Alibaba client. The worker
receives optional catalog/ranker ports directly; it never calls an internal HTTP route. Real
semantic work requires explicit live generation, the feature flag, complete provider settings and
an operator-built complete current catalog index.

The safe detail projection adds selection mode/status/closed reason, query/selector versions and
bounded embedding identity; each chosen image may expose selection method and similarity band. The
development-only UI explains the method and fallback. It never exposes vectors, raw queries,
private catalog identifiers, approval claims or publish controls.

### Multimodal failure matrix

| Condition | Result |
| --- | --- |
| Feature disabled or fixture run | No visual provider/client; deterministic fallback snapshot |
| Fewer than two eligible candidates | `single_candidate`; zero embedding calls |
| Catalog index incomplete/mixed before query | `semantic_unavailable:index_incomplete`; zero embedding calls |
| One query/provider/result fails | Discard full matrix; deterministic fallback; no hidden retry |
| Catalog/checksum changes after query | Fence semantic result and fall back on the reloaded eligible set |
| Retry after Article v4 persistence | Reuse stored assignments; zero embedding calls |
| Selected asset path/checksum/type changes before staging | Fail the media stage; never substitute another file |
| Similarity prefers an ineligible/wrong-role asset | Asset never enters the rankable set |
| Historical v1--v6 recovery | Exact historical dispatch with no semantic fields or provider work |

## 15. Follow-up design — v8 first-call structured output

The v7 multimodal family remains immutable. A new v8 family changes only the generator/auditor prompt identities:
generator v5 and auditor v2. Before the first Zhipu completion, its versioned system instruction includes the
canonical validation schema; audit adds the bounded conditional invariant that JSON Schema alone cannot express.
The v1--v7 system instruction and user prompt remain byte-for-byte replayable. Every textual system/user part is
counted before a request, and the existing single correction is the only allowed logical retry. Article numeric v5 is
stored through additive migration `20260823_0030`, whose downgrade refuses to discard v5 data. Renderer, media plan,
visual selection and local-only draft adapter stay v7/v5 identities respectively.

## 16. Follow-up design — explicit live-local review export

Keep the existing fixture export and its default rejection of real runs. A separate explicit CLI flag unlocks review-
mode local export only for a ready simulated live run; no web route is added. The exporter writes a new immutable,
idempotently reusable `live-local-review-*` directory plus deterministic ZIP, rewriting controlled local media URLs
to relative assets. Manifest, README and preflight retain pending/approved/rejected review truth while fixing
`export_scope=live_local`, `copy_ready=false` and `published=false`. The API media route and CLI share one
infrastructure resolver: it validates the durable row and then reads the approved catalog derivative or source image
outside its database transaction. Any mismatch fails closed and deletes the temporary tree.

## 17. Approved supplement — manual IP-reference visual review

The 41-item manifest-approved 小赛／赛先生 catalog can also guide a user-directed, operator-run local visual
review exercise. This is not a new worker stage: a manual image-authoring session receives only selected local
reference files and creates original, section-specific review illustrations in a fresh output directory. The map
records catalog version, four-or-fewer public asset references, section index/heading, output checksum and bounded
semantic brief. It must not retain or export a master, source path, raw asset ID, vector, raw prompt or provider
body. Generated images are reviewed separately for character fidelity, no readable text/labels/QR/watermark,
editorial fit and rights. The default official-account fixture/API/export remains provider-free and unchanged;
integrating these images into Article Package, media staging or HTML requires a future versioned contract rather
than a hidden substitution.

## 18. Approved follow-up — automatic approved-IP body visuals

`official_account_local_generated_visuals` is an additive v1 output ledger keyed by current render and body ordinal.
It records only durable safe identity: run/article/render IDs, ordinal/section, catalog version/public reference,
source/publication checksums, selector method/band, request/plan/prompt fingerprints, provider/model, status and
validated output MIME/size/hash/dimensions. It never records the prompt, raw catalog ID/path, reference bytes,
embedding/vector, or provider body. `official_account_local_media.generated_visual_id` is a third exclusive source
beside a source artifact or fixture; generated rows are permitted for `body` only and must already be `ready`.

After the v8 Article selection snapshot is persisted, an explicitly enabled live worker revalidates each selected
catalog candidate and derives a bounded transient prompt from the assigned section. It first commits a `generating`
intent under the run lease, then performs reference-byte read, image-port call and content-addressed private write
outside a transaction. Only a newly created intent may make the one provider call. A recovered `generating` intent
is terminal `result_unknown`; a known failed output is terminal failed. There is no automatic image-level retry.

The feature flag defaults to disabled and the worker creates its image generator lazily only when enabled. It requires
the existing single-attempt image configuration and preserves default fixture zero egress. The existing semantic
selector decides the approved public reference; incomplete/disabled semantic capability has already produced the
deterministic selector snapshot, so no arbitrary file or secondary ranking is admitted. Generated images replace
selected catalog body media for staging, while the existing material image remains the independent cover.

No image-review state or API is added. Article manual review remains a separate ready-draft event and its export
gate is unchanged. Safe API detail exposes generated result metadata only; media resolver/export revalidate the row
then read from content-addressed storage outside the transaction. No path, object key, prompt or provider response
crosses that boundary, and no WeChat/WeCom/publish integration exists.

## 19. Approved follow-up — v2 block anchors and publication profile

Migration `20260824_0033` extends the immutable ledger without rewriting `0032`. Historical v1 rows keep all new
columns null and retain their original request fingerprint, transient section-first-360 prompt, provider request
bytes and stored output. A complete v2 row additionally pins `block_index`, allowlisted `block_kind`, a SHA-256
fingerprint of the normalized exact block, reference-input normalization version/checksum and output-profile
version. Mixed or partial shapes fail closed in the database and repository.

For each assigned section, select the first eligible semantic paragraph/bullet/quote/callout with enough bounded
content, otherwise the first readable eligible block. The selection is deterministic and never crosses the section.
Build the transient scene instruction from the exact selected block, topic and heading, then bind prompt hash and
safe anchor identity to the new request fingerprint. Persist no raw block content, scene brief or prompt.

At the provider boundary, v1 continues its PNG-only exact-byte builder. The v2 reference-input adapter validates the
approved publication checksum: valid PNG takes an identity fast path with unchanged bytes, while exact JPEG is
orientation-normalized and encoded as deterministic metadata-free PNG. The resulting checksum/version are verified
against the persisted plan before either ToApis upload or Comfly data-URL construction. No test or fixture makes a
network request.

After one successful provider response, validate provider identity and raw bytes, then center-crop/resize and encode
the actual v2 publication artifact as metadata-free JPEG at exactly 1536×1024 with bounded bytes. Persist that
derivative's MIME, dimensions, checksum and private object; media staging, HTML preview and export all resolve the
same artifact. The workbench therefore uses the same 3:2 composition as the final local output and obtains bounded
semantic alt text from the persisted section/block purpose. It displays the new timeline stage with ready/total
computed from the safe generated-result list and planned body-image count.

An `ImageProviderTimeoutError` after durable intent is not a known rejection. The executor immediately persists
`result_unknown`, ends the run unknown and performs no automatic call on recovery. Deterministic provider rejection,
identity mismatch, invalid media or output-profile failure remains known `failed`. All calls remain outside database
transactions; no WeChat, WeCom or publish adapter exists.

## 20. News-backed visible-IP v3 and isolated ToApis demo

Keep the v2 prompt and `official-account-generated-visual-request-v2` fingerprint path literal. The current v3 pair
adds only the stronger visual semantic: the approved 小赛／赛先生 reference is mandatory identity guidance and the
same character must remain fully visible as the scene protagonist. Block anchor, reference-input normalization and
3:2 publication profiles remain unchanged; v3 uses a new request fingerprint namespace. Migration `20260824_0034`
only recreates the generated-visual check constraints so v1, v2 and complete v3 tuples coexist.

`official_account_news_ip_live_demo.py` is an operator-only local acceptance flow, not an acquisition scheduler or a
publishing adapter. It verifies bounded Ministry of Education HTML, persists source URL/date/body checksum/short exact
quote and claim bindings, deterministically assembles parent-facing reader copy, revalidates three pinned public refs
against the exact approved 41-item catalog, then sequentially performs at most three ToApis single-reference calls.
Each exclusive file intent is fsynced before its call. Any typed timeout writes `result_unknown` and exits; no fourth
call or substitute image is allowed.

The output is an isolated content-addressed review bundle with relative 1536×1024 JPEGs, escaped HTML, source links,
evidence/visual/run metadata, manifest and deterministic ZIP. Local visual inspection records whether the company IP
is actually visible and whether text/logo/QR/watermark is absent. The inspection can mark failure but never launches
another provider call. The article/embedding/Comfly/WeChat/WeCom/publish call counts remain zero.
