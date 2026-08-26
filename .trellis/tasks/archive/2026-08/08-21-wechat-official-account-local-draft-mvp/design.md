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

## 21. Reference-learned editorial repackage

Add an offline, operator-run repackage beside the live news/IP demo. It accepts only a complete ready v1 source
bundle whose manifest, evidence identities, three JPEG publication profiles and local visual-quality result all
validate. It reads no environment credentials and constructs no HTTP or model client. The output is written through
a temporary sibling directory and atomically renamed, so an invalid input cannot leave a plausible partial bundle.

The assembler creates a structured `ArticlePackage` with a new news-editorial v2 generator/schema/rule/renderer/
style/template identity. Six units form the mobile reading path: news signal, parent questions, learning-logic
change, cross-disciplinary use, a small family practice loop and the parent's changing role. Sourced blocks carry
the two existing evidence IDs; advice and judgments remain evidence-free opinion claims. Three image blocks are
assigned after units 1, 3 and 5 and resolve only to copied `assets/body-00..02.jpg` files whose bytes match the source
manifest.

The renderer is a new escaped inline-style fragment rather than a mutation of the frozen v1--v7 families. Its visual
direction is original editorial paper: warm off-white surface, deep navy ink, restrained burnt-orange and teal
accents, hairline rules, numbered section markers, one policy-summary card, pull quotes and generous paragraph
rhythm. The standalone preview adds a strict local CSP and 430 px reading frame; article-body HTML remains suitable
for local copy inspection. Source URLs are restricted to the two pinned HTTPS Ministry of Education pages.

The repackage output contains article HTML/Markdown, evidence and visual projections, aggregate reference-learning
metadata, run/manifest/README and deterministic ZIP. It states that the three image calls are inherited historical
provenance while every call counter for this repackage is zero. Manual review stays pending, copy-ready stays false,
and published stays false.

## 22. High-rhythm science-magazine v3

Keep `official_account_news_editorial_demo.py` and its v2 bytes as a frozen source/repackage contract. Add a sibling
operator-only v3 module that imports the v2 `EditorialSourceBundle` and fail-closed `load_source_bundle` boundary,
then creates a new Article Package identity, renderer and atomic export. It never imports settings or provider
factories. A shared validated source bundle is the only bridge; v3 must not weaken or duplicate v1 manifest,
evidence, image or visual-contract validation.

The v3 article retains the six evidence-bound topics and three body slots but strengthens the headline/digest and
adds structured opinion list content required by the AI/child boundary module. It remains within 1,800--2,600 body
characters. The first body image is rendered once as a full-bleed hero; the other images remain balanced around the
learning-loop and family-action units. Render validation proves exact v3 identities, one-to-one claims, sources,
image slots and content fingerprint before producing bytes.

The renderer uses six distinct section-indexed presentation functions rather than one repeated card loop. Dynamic
article text is always escaped; phrase emphasis splits only after matching a frozen allowlist of exact substrings.
Policy tiles and timelines consume existing bullet items in order. Question cards consume existing question
paragraphs. Static labels such as `政策信号`, `家长先问`, `学习闭环`, `AI 是助手` and `20 分钟行动` add no factual
assertion. If the expected structured block shape drifts, rendering fails instead of silently falling back to a
generic layout.

The new output uses the same atomic temporary-sibling/no-clobber pattern and deterministic archive timestamps as v2.
It exports the Article Package, HTML/Markdown, evidence, visual provenance, reference-learning comparison, run,
manifest, README, three exact JPEGs and ZIP under `official-account-news-ip-editorial-20260824-v3`. All current call
counters remain zero; inherited three paid calls, source run ID and source manifest checksum remain explicit.

## 23. Approved-catalog five-image v4

Keep v3 frozen and add `official_account_news_editorial_asset_rich_demo.py` as an operator-only, provider-free
sibling. Its only inputs are the validated v1 source bundle and the configured local approved-catalog manifest.
It reuses v2's fail-closed source loader and the existing `LocalOfficialAccountCatalogMediaProvider`; it imports no
settings singleton, provider factory, HTTP client or social adapter. The CLI receives both paths explicitly.

The assembler starts from the validated v3 article and creates a new version family. It adds `body-3` after the
three parent-question paragraphs and `body-4` after the structured AI/child responsibility list. The complete image
placement is therefore `(0, body-0)`, `(1, body-3)`, `(2, body-1)`, `(3, body-4)`, `(4, body-2)`, with `body-0..4`
plus the existing cover slot in the Article Package. The first three image blocks and bytes retain their v3
semantics; the new blocks carry bounded reader-facing alt text but no factual claim.

Catalog resolution is deterministic and exact. Load the complete 41-item approved set, locate the two pinned public
refs, reject the three historical reference refs and duplicate source/publication identities, revalidate each
candidate, then read only the adapter-produced publication bytes. The export records catalog version, 16-character
public ref, source-master checksum, publication checksum, semantic tags and section binding. It never records raw
asset ID, source path, filename, master bytes, vectors or prompts. The selected pair is:

- `1bb84f2abb140b8f`: thinking/discussion cutaway for the parent-question module.
- `bab27fe77a8edff4`: AI/observation cutaway for the AI/child responsibility module.

The v4 renderer preserves the established science-magazine hierarchy while adding two distinct `catalog-cutaway`
modules. Square catalog derivatives use `object-fit: contain` on controlled warm/blue fields instead of the 3:2
scene crop, so the IP silhouette is not clipped. Rendering validates the full six-section shape, exact five slots,
single-use placeholders, exact module markers, one `h1`, escaped dynamic text and pinned source links before export.

Export uses a temporary sibling directory, fsynced local writes where already provided by the versioned exporter,
exclusive no-clobber rename and deterministic ZIP timestamps. It writes five relative JPEG assets, Article Package,
HTML/Markdown, evidence, visual provenance, reference-learning, run, manifest and README. The three generated rows
are marked inherited byte-exact paid provenance; the two catalog rows are marked approved local publication
derivatives. All current external-call counters are zero, and manual article review remains pending with no publish
capability.

## 24. Live semantic-reference generated v5

Keep the complete v4 module and output frozen. Add
`official_account_news_editorial_semantic_generated_demo.py` as an explicit operator-only sibling. Its CLI accepts
the validated v1 source bundle, approved catalog manifest, fresh destination and live provider settings. It imports
no social adapter and exposes no API or background worker route. The command refuses an existing destination and
does not create a final bundle until every semantic and image result is ready and validated.

The selector builds exactly two bounded queries from the already-validated v4 Article Package: the complete parent
question paragraph group that owns `body-3`, and the structured AI/child responsibility list that owns `body-4`.
It loads the complete eligible 41-item catalog projection, proves exact active Qwen3-VL v2 index coverage before
client construction, and calls the existing text-query/search boundary once per block. The whole two-row matrix is
fenced against catalog/identity drift, then each placement chooses the highest cosine result after existing
approval/role/integrity gates and stable tie breaks. The two selected references must be distinct and must not be
one of the three historical v1 references. Safe output retains only query/selector versions, public ref, catalog
version, bounded similarity band, semantic tags and checksums; raw query text, asset IDs, vectors and private paths
remain transient.

For each selected placement, the command writes an exclusive safe intent JSON under a temporary sibling before the
paid request. The intent binds placement, safe public reference, input checksum, plan/prompt/request fingerprints,
provider/model and publication profile, but excludes prompt text, credentials and provider data. The existing
ToApis single-reference request builder receives the normalized approved reference and a transient v3-visible-IP
scene prompt derived from the exact block. `IMAGE_MAX_ATTEMPTS=1` is mandatory. A timeout after intent creation
writes `result_unknown`, makes no retry and aborts the ready export; known typed failures write `failed` and also
abort. No third image call or catalog-byte fallback exists in this explicit live path.

Successful outputs pass the existing bounded raster decoder and deterministic metadata-free 1536x1024 JPEG
publication transformer. V5 rebuilds the five-image Article Package with the three inherited byte-exact scenes and
the two new 3:2 scenes at the existing body-3/body-4 anchors. Its renderer preserves v3/v4 information hierarchy,
changes both cutaway frames to ordinary 3:2 scene frames and requires five single-use local JPEG placeholders,
semantic alt text, strict local CSP, one `h1`, escaped dynamic text and the two pinned Ministry sources.

Atomic export writes a fresh `official-account-news-ip-editorial-semantic-generated-20260825-v5` directory and
deterministic ZIP containing the Article Package, HTML/Markdown, evidence, safe semantic selection, safe visual/run
provenance, manifest, README and five JPEGs. It records exactly two embedding calls and two ToApis attempts for a
ready run, zero Comfly/article/source/WeChat/WeCom/publish calls, pending manual review, local-only, copy-ready false
and published false. Temporary reference PNGs, intents and unknown/failed diagnostics never enter a ready export.

## 25. Official-source contextual news-photo v6

Keep the v5 Article Package, renderer, five media slots and ready bundle frozen. Add an operator-only sibling module
that first validates the complete v5 bundle, then acquires two exact official-source photos through an injected
async byte fetcher. Production construction uses a bounded `httpx` client with HTTPS-only exact URL membership,
`www.moe.gov.cn` host fencing, no cross-host redirects, a 15 MiB response cap and one attempt per photo. Unit tests
use an injected in-memory fetcher and cannot reach the network.

The exact source/photo set is immutable for this version:

- related national basic-education conference photo, source page
  `https://www.moe.gov.cn/jyb_xwfb/s6052/moe_838/202607/t20260722_1444692.html`, image
  `https://www.moe.gov.cn/jyb_xwfb/xw_zt/moe_357/2026/2026_zt09/jdt/202607/W020260723357821146376.jpg`,
  SHA-256 `0d2427caf395ba0d55eaf66678e2d67dd9bc581e2813d5860505e232c2e3811d`, 575×354;
- “人工智能+教育” press-conference photo, source page
  `https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/t20260410_1433382.html`, image
  `https://www.moe.gov.cn/fbh/live/2026/77927/tpwd/202604/W020260410433219993653.jpg`, SHA-256
  `ea635b7ecca51e8073ae3bd7954d8fc03234f49dda52e3a675f2591d75a7afb5`, 800×535.

Decode each response fully as JPEG, reject animation/progressive identity drift, unexpected dimensions/checksum or
duplicate bytes, but write the validated source bytes unchanged. A frozen `NewsContextPhoto` projection owns the
safe public ID, contextual relation, exact URLs, caption, photographer/source credit, MIME, dimensions, checksum and
`publish_permission_unverified`. This projection is adjacent to—not part of—the five-slot Article Package because
the photos are contextual editorial material rather than evidence-bound generated body media.

Render two new `news-context-photo` modules into stable v5 anchors. Use `height:auto`, no crop/object-fit transform,
escaped captions and exact allowlisted source-page links. The visible watermark and source credit remain intact.
The first module follows the opening policy signal; the second sits beside the AI responsibility section. The
standalone preview and article fragment reference only copied `assets/news-00.jpg` and `assets/news-01.jpg` files;
they never auto-load remote media.

Atomic export writes a fresh `official-account-news-ip-editorial-news-context-20260825-v6` tree and deterministic
ZIP containing the unchanged v5 Article Package/five images plus two official photos, HTML/Markdown, evidence,
visual map, news-photo provenance, run, manifest and README. The current v6 call ledger records exactly two official
source image GETs and zero embedding, image-generation, article-model, Comfly, ToApis, WeChat, WeCom and publish
calls; inherited v5 paid calls remain historical only. Manual review remains pending and every surface carries the
permission warning, `local_review_only=true`, `copy_ready=false` and `published=false`.

## 26. Selected-news source-image acquisition and durable context media v7

### Ownership and data flow

```text
approved detail HTML
  -> connector extracts bounded SourceImageReference values
  -> accepted evidence detail snapshot + durable image discovery row
  -> paced SafeSourceImageFetcher GET outside transaction
  -> strict raster validation + immutable source snapshot
  -> source_article_images ready/failed provenance
  -> selected material package evidence snapshot IDs
  -> deterministic max-two context selection persisted with Article v9
  -> renderer v8 context placeholders
  -> local context media + resolved local-only HTML/API/workbench
```

Acquisition owns every source request. The official-account worker never refetches a URL and never searches the web;
it joins `material_packages.source_snapshot[*].snapshot_id` to ready source-image rows. This preserves the current
material package JSON contract and makes unrelated, merely similar images ineligible by construction.

### Extraction and fetching

Add a frozen `SourceImageReference` value to `ExtractedDocument`. `HtmlConnector` gathers at most five candidates in
stable DOM order: a valid `og:image` first, then `img` elements inside the exact selected content root, with `figure`
captions where present. Normalize relative URLs against the final detail URL, remove fragments, reject credentials,
data/blob/javascript URLs, SVG/tracking/icon shapes and duplicates, and require the source profile's existing
host/path policy. Connector extraction performs no I/O.

After the text item passes freshness/relevance and is durably accepted, the acquisition executor reserves at most
two image rows, uses the existing source lease/request-slot pacing, then calls an injected image-only fetcher
outside transactions. The fetcher reuses public-DNS validation, exact allowlisting, bounded redirects and
`trust_env=false`, but accepts only JPEG/PNG/WebP and a 15 MiB maximum. Full Pillow decode rejects animation,
truncation, decompression bombs, dimensions below the editorial minimum or above the pixel bound. Known per-image
failures are stored safely and do not change the accepted article outcome. Tests omit/inject the image fetcher.
The first frozen version permits only query-free same-host media URLs within the article profile's existing path
allowlist; signed-query and cross-host CDN media are rejected until a source-versioned media allowlist/redaction
contract exists.

### Persistence and idempotency

Migration `20260825_0036` advances from `20260824_0035`, extends `source_snapshots.kind` with `image`, and adds
`source_article_images`. Core FKs bind the detail snapshot, source version and optional ready image snapshot; a
unique discovery fingerprint owns replay. Complete ready rows require immutable MIME/size/hash/dimensions and no
error; failed/rejected rows require a safe code and no image snapshot. Caption, credit, role, ordinal, extraction
version and `publish_permission_unverified` are bounded columns. Discovery reservation commits before the GET;
completion is an idempotent short transaction.

Add `material_package_source_images`, binding each new package to only the ready source-image rows reachable through
its frozen evidence occurrence/detail-snapshot set. This is the immutable handoff record; topic selection remains
network-free and does not choose from unrelated images on the same event or publisher.

Add `official_account_article_context_images`, binding Article v9 to the selected source-image rows with exact
ordinal, section index, selection version and semantic alt/caption snapshot. Extend local media with an exclusive
`source_article_image_id` and `context` role for ordinals 0--1. Historical rows retain their existing three-way
source XOR and body/cover constraints; the new four-way shape applies only to context media.

### Deterministic selection and rendering

The new Article v9 family retains the v8 structured generator/auditor and five-slot multimodal/IP plan, but adds an
application-owned `news_context_media` snapshot and new article schema/render/style/template/local-adapter identities.
Hard eligibility precedes scoring: exact selected evidence snapshot lineage, ready status, supported raster,
distinct checksum, natural dimensions and bounded safe metadata. Rank lead images ahead of body images, then score
bounded caption/alt tokens against topic/section text; stable ties use evidence order, source-image ordinal, checksum
and public reference. Select zero to two images and spread two across distinct sections.

Renderer v8 adds escaped natural-aspect `news-context-photo` modules at persisted section anchors and emits separate
context placeholders. Local staging reads the immutable image snapshot through the existing private snapshot store,
revalidates bytes, and resolves every body/context/cover placeholder exactly once. API and the development workbench
show context role, semantic alt, caption/credit, source page, rights state and `context_only_not_evidence`; they never
expose bucket/object keys. Zero eligible images is a visible safe degradation, not a run failure.

### Rights, compatibility and failures

Source pages do not automatically grant republication rights. Current acquisition therefore records
`publish_permission_unverified`; local preview may display it for review with source attribution, but a copy-ready
export containing it fails closed. A later governed rights workflow may add a new status/version; it must not mutate
historical rows. Watermarks and pixels remain untouched.

Every historical source version, candidate, material package and official-account v1--v8 family dispatches through
its literal existing contract. New version identities participate in run/content/render/media fingerprints. Image
timeout/unavailability is a known optional-acquisition failure, while a checksum/lineage/identity drift during
official-account staging fails the new run. No path constructs WeChat/WeCom/publish clients.
