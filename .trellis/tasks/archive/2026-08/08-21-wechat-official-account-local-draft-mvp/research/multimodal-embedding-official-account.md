# Research: Multimodal embedding for official-account semantic media

- Query: Determine the smallest additive integration of the existing `qwen3-vl-embedding`
  visual-retrieval slice into `official_account_local` media selection, while preserving offline
  defaults, governed-candidate barriers, deterministic fallback, historical v1--v6 artifacts, and
  the current no-WeChat/no-WeCom boundary.
- Scope: mixed (internal implementation and official Alibaba Model Studio documentation)
- Date: 2026-08-23

## Findings

### Executive conclusion

The existing multimodal embedding stack is suitable for cross-modal **section text -> approved
image** ranking, and most of the transport, vector identity, pgvector search, error mapping, and
test infrastructure can be reused. It should not replace the current deterministic planner. The
smallest safe design is a new v7 hybrid selector:

1. freeze current official-account v6 literally;
2. form the exact already-approved candidate set and fixed balanced placements before semantic
   ranking;
3. use one bounded text query per placement only in explicitly enabled live mode and only when at
   least two candidates have one exact, complete, compatible image-vector index;
4. maximize the one-to-one similarity matrix, using the current tag score and stable
   `(publication_priority, checksum, candidate_id)` order only as tie breakers;
5. if the provider/index/catalog is unavailable at any point, discard the whole embedding matrix
   and run the existing v2 deterministic tag selector;
6. persist the selected candidate/slot snapshot before rendering, so retry/recovery never repeats a
   paid query or changes an already-created article.

There is an important product limitation: a live material package currently exposes exactly **one**
qualified `ImageArtifactModel`. Therefore multimodal ranking gives no visible benefit to today's
live material-package path. It becomes useful when upstream exposes two or more approved candidates,
or when an explicit approved candidate catalog is added. The three fixture publication images are
not in the current 41-asset private visual manifest, and their publication bytes are JPEG while the
frozen embedding input policy accepts PNG masters only.

### Files found

- `backend/app/domain/visual_retrieval.py` — frozen qwen3-vl embedding identity, text/image request
  validation, deterministic PNG normalization, semantic ranking types, and bounded canonical
  visual query.
- `backend/app/application/ports/visual_retrieval.py` — reusable `VisualEmbeddingModel` and
  `VisualIndexRepository` protocols.
- `backend/app/application/services/visual_retrieval.py` — provider/error/identity validation and
  complete-index search orchestration; also contains the explicit operator indexing service.
- `backend/app/infrastructure/ai/visual_embedding.py` — one-attempt Alibaba REST adapter and
  deterministic provider-free fake.
- `backend/app/infrastructure/db/visual_retrieval.py` — exact identity/checksum/catalog filtered
  pgvector cosine search and completeness proof.
- `backend/app/domain/visual_assets.py` — approved-catalog hard gates and semantic-primary ordering
  after eligibility.
- `backend/app/application/services/material_package.py` — existing production example of text
  embedding, complete-index checking, catalog refresh fencing, semantic-primary selection, and
  `semantic_unavailable` fallback.
- `backend/app/infrastructure/db/models.py` — `brand_visual_*` embedding tables, the one-image
  `material_packages.image_artifact_id` relation, image-reference provenance, and official-account
  persistence.
- `backend/app/domain/official_account_local.py` — current v6 tag selector, balanced placement, exact
  version-family dispatch, Article Package, and content/render fingerprints.
- `backend/app/application/services/official_account_local.py` — official-account stage executor;
  this is the correct application boundary for an optional semantic ranker.
- `backend/app/application/ports/official_account_local.py` — source-media and durable repository
  ports; currently lacks embedding-source identity and a persisted selection snapshot.
- `backend/app/infrastructure/db/official_account_local.py` — eligible candidate loading and
  immutable article/media persistence; live currently returns one source image.
- `backend/app/official_account_worker_main.py` — independent worker; currently constructs only the
  optional Zhipu article client and has no visual-ranker dependency.
- `backend/app/infrastructure/storage/minio_image_store.py` — checksum-verifying immutable generated
  image retrieval that an explicit indexing command could reuse.
- `backend/app/schemas/official_account_local.py` and
  `backend/app/api/v1/routes/official_account_local.py` — current bounded media-selection API
  projection.
- `backend/tests/unit/test_official_account_article.py`,
  `backend/tests/unit/test_official_account_html.py`,
  `backend/tests/unit/test_official_account_worker.py`, and
  `backend/tests/integration/test_official_account_local.py` — focused regression seams and v5/v6
  goldens.
- `.trellis/spec/backend/visual-retrieval.md` — complete-index, approved-catalog, one-attempt,
  deterministic-fallback contract.
- `.trellis/spec/backend/agent-pipeline.md` — official-account v6 and no-runtime-embedding contract.
- `.trellis/spec/backend/database-guidelines.md` — no DB transaction across embedding/provider work.

### Reusable code patterns and exact evidence

#### Model identity, requests, and provider

- `VisualEmbeddingIdentity` freezes provider/model/dimensions/input policy at
  `backend/app/domain/visual_retrieval.py:105-139`: `alibaba-model-studio`,
  `qwen3-vl-embedding`, 2048 dimensions, and input-policy v2.
- `VisualEmbeddingRequest.for_text` already canonicalizes/hash-binds a bounded text request at
  `backend/app/domain/visual_retrieval.py:201-211`. Text/image requests share the same identity and
  output type.
- `VisualEmbeddingResult` rejects wrong dimensions, non-finite vectors, and all-zero vectors at
  `backend/app/domain/visual_retrieval.py:233-257`.
- `AlibabaVisualEmbeddingAdapter` is reusable without modification for one text at a time. It pins
  the Beijing HTTPS route, disables redirects through its supplied client, bounds concurrency and
  the total timeout, performs one request, streams a bounded response, and verifies provider/model
  identity (`backend/app/infrastructure/ai/visual_embedding.py:60-205`).
- `DeterministicFakeVisualEmbedding` supplies a network-free 2048-dimensional result for unit and
  contract tests (`backend/app/infrastructure/ai/visual_embedding.py:208-229`). It is a contract
  fake, not evidence of live semantic quality.

#### Complete index and fallback

- `VisualRetrievalService.search_text` is the reusable high-level operation
  (`backend/app/application/services/visual_retrieval.py:32-47`). Its `_search` method maps provider
  failures to typed unavailable reasons, validates returned identity/fingerprints, and refuses an
  incomplete/mismatched index (`backend/app/application/services/visual_retrieval.py:82-126`).
- `PostgresVisualIndexRepository.search_complete_catalog` exact-filters catalog version,
  provider/model/dimensions/input policy, asset ID, and source checksum before cosine ordering
  (`backend/app/infrastructure/db/visual_retrieval.py:238-316`). Duplicate/missing/mixed rows make
  `complete=False`.
- The current material-package pipeline is the reference fallback pattern: build bounded query
  text, ask `VisualRetrievalService`, convert every typed failure to `semantic_unavailable`, and
  refresh/fence the catalog before selection
  (`backend/app/application/services/material_package.py:288-358` and `:755-783`).
- Approved/role/MIME/byte gates precede semantic ordering in `AssetSelector`; cosine similarity is
  only the first ordering key among eligible survivors
  (`backend/app/domain/visual_assets.py:793-837`, `:1002-1010`, and `:1088-1098`). This is the
  pattern the official-account ranker must preserve.
- The executable spec says incomplete, mixed-policy, provider failure, or catalog change must fall
  back to the previous deterministic selector and never let similarity admit an ineligible asset
  (`.trellis/spec/backend/visual-retrieval.md:60-76`).

#### Official-account insertion and recovery seams

- Current fixed placement and tag scoring live entirely in the official-account domain. Four
  sections/three candidates map to `(0, 2, 3)`; heading matches are 100 and bounded-body matches are
  20 (`backend/app/domain/official_account_local.py:549-605` and `:608-709`).
- The executor loads qualified media in a completed repository call before generation
  (`backend/app/application/services/official_account_local.py:465-481`). The correct place for an
  external semantic call is after the structured draft returns and before `persist_article`, where
  tag assignment currently occurs (`:501-549`). No repository session remains open there.
- Recovery currently recomputes source order from article sections and candidates at
  `backend/app/application/services/official_account_local.py:608-624`. A multimodal implementation
  must replace this for v7 with a persisted assignment snapshot; it must not query the provider
  again on retry.
- `ArticleImageBlock` records only slot/alt text, not candidate identity or query provenance
  (`backend/app/domain/official_account_local.py:193-203`). `ArticleVersionBundle` has no selector or
  query identity (`:309-320`). These are the principal missing persistence seams.
- Article payload is already immutable JSONB and fingerprinted, so a v7 selection snapshot can live
  in the new Article Package without a new result table
  (`backend/app/infrastructure/db/models.py:3807-3873`). However the relational article version
  check is currently `version IN (1, 2, 3)` (`:3847-3851`), so a true Article v4 needs an additive
  `0029` migration.
- Local-media `descriptor` already safely persists bounded semantic label, assigned section,
  score band, and reason code (`backend/app/infrastructure/db/official_account_local.py:800-867`).
  It can mirror the persisted v7 selection method/availability band, but it must not be the sole
  source of truth because it is created after article/render persistence.
- API detail already has a bounded `media_selection` aggregate and per-media semantic fields
  (`backend/app/schemas/official_account_local.py:128-155` and
  `backend/app/api/v1/routes/official_account_local.py:506-547`). This is an additive OpenAPI seam.

### Can text-query embedding and a complete index work for material candidates?

Technically yes, but not with today's candidate projection without additional indexing metadata.

- `VisualIndexRepository.search_complete_catalog` accepts an exact tuple of `(asset_id, checksum)`;
  it does not need file paths (`backend/app/application/ports/visual_retrieval.py:43-50`).
- `VisualCatalogIndexService.index_asset` can explicitly index any verified PNG under a pinned
  catalog version and exact identity (`backend/app/application/services/visual_retrieval.py:138-220`).
- A generated material image can be read and checksum-verified from private immutable storage via
  `MinioImageStore.get_bytes` (`backend/app/infrastructure/storage/minio_image_store.py:25-60` and
  `:85-105`). Provider work must still occur after that bounded storage read and outside a DB
  transaction.

Missing pieces are:

1. `OfficialAccountSourceMedia` needs a distinct embedding-source identity: a 64-hex indexed asset
   ID, immutable PNG checksum, candidate catalog version, and an explicit approval state. Its
   publication JPEG checksum cannot stand in for its PNG master checksum.
2. An explicit operator indexing command must create the complete candidate index. Startup and the
   article worker must never silently index or make N image-provider calls.
3. The query side should prove candidate-set coverage before a paid text query. The existing
   repository proves completeness only while computing cosine distance with an already-created
   query vector. A small `prove_complete_catalog(...)` repository method would avoid a paid query
   when the index is known incomplete; the existing `search_complete_catalog` must still recheck
   after the provider result to fence races.
4. The current visual tables/spec are named and documented as the approved private brand catalog.
   Reusing `brand_visual_index_jobs` / `brand_visual_asset_embeddings` is the least schema work only
   if Phase 10 explicitly broadens them to isolated, namespace-versioned **approved visual candidate
   catalogs**. Otherwise a separate official-account embedding table is required. Do not write
   generated-image rows into the current table silently.

Current live limitation is explicit in code: `MaterialPackageModel` has one non-null
`image_artifact_id` (`backend/app/infrastructure/db/models.py:3559-3585`), and
`load_source_media_candidates` returns a one-element tuple for every live run
(`backend/app/infrastructure/db/official_account_local.py:539-590`). An index for that one image is
valid but ranking is a no-op, so the provider should be skipped with reason
`single_candidate`.

The fixture has three candidates, but the current embedding catalog does not cover them. Their PNG
master checksums and JPEG publication derivatives are separate
(`backend/app/infrastructure/official_account_local.py:57-95`). None of the three master checksums
appears in `private/brand-materials/visual-assets.manifest.json`; the manifest remains the separate
41-asset private catalog. Default fixture execution therefore must use the current deterministic
selector and make zero external calls.

### Recommended Phase 10 contract

#### Version boundary

- Freeze v6 exactly, including article fingerprint
  `37040e36c4df436090f34ac58baf3e6ed7544a2015e6ae9041c86368fdfe6a05`, HTML SHA-256
  `14b34d9469d9f2d6986c637b309f7c040c6a49e0d4e7e75490095fa9db3704e6`, and render fingerprint
  `b72c7f84b739dcfcb0c3076c3a9888b47af96d202045652ec82022132b821989`
  (`backend/tests/unit/test_official_account_html.py:284-305`). Keep all v1--v5 goldens too.
- Add a new exact family, suggested names:
  - `official-account-article-schema-v4-multimodal-media`
  - `official-account-media-plan-v3-multimodal-hybrid`
  - `official-account-visual-query-v1`
  - `official-account-visual-selector-v3-multimodal-hybrid`
  - `wechat-html-renderer-v7-multimodal-media`
  - matching v7 style/template identities
  - `official-account-local-adapter-v5-multimodal-media`
  - `official-account-review-bundle-v4-multimodal-media`
- The generator/auditor prompts and reader-copy rules need not change merely because app-owned
  media ranking changes. Reuse the current generator/rule pair unless the prompt or public article
  copy also changes.
- Add selector/query identity to `OfficialAccountVersionIdentity` and the run fingerprint. Old
  bundles must deserialize with absent fields and must remove those absent fields from historical
  canonical fingerprints, exactly as `media_plan_version=None` is handled today
  (`backend/app/application/services/official_account_local.py:78-92`). Unknown/mixed families fail
  closed.

#### Candidate and query contract

- Hard-filter candidates before any embedding: existing upstream validation/audit must pass,
  checksum/MIME/size/source lineage must be complete, human-rejected material remains excluded, and
  semantic ranking cannot introduce a new asset.
- Use embedding only for an exact set of 2--5 candidates. Zero candidates fails as today; one
  candidate takes deterministic `single_candidate` degradation with no provider request.
- Build one bounded query for each already-planned placement from only allowlisted reader-safe
  fields: topic title, section heading, and the same first 360 normalized body characters. Do not
  include evidence quotes, brand chunks, prompts, provider responses, raw HTML, object paths, or
  credentials. A new pure official-account query serializer is clearer than overloading
  `canonical_visual_query`, whose allowlist models an image-generation brief
  (`backend/app/domain/visual_retrieval.py:484-514`).
- Query each placement through the existing frozen `VisualEmbeddingRequest.for_text` and model
  identity. Three fixture-like slots mean at most three text embedding requests; the existing
  article maximum is five.
- Require one complete exact candidate catalog before the first request and recheck it after each
  result. Any disabled/auth/timeout/output/identity/index/catalog error discards all semantic scores
  and invokes v2 tag assignment; no partial mixed semantic/tag plan.
- With a complete score matrix, maximize total cosine similarity one-to-one. For equal totals use
  the current integer heading/body score, then the current priority/checksum/candidate-ID order.
  Embedding changes ordering only; balanced section indexes, candidate eligibility, byte gates,
  duplicate-checksum refusal, and output count remain application owned.

#### Persistence and recovery

- Add a required v7 `media_selection` snapshot to the Article v4 payload. Recommended bounded
  fields: selector/query versions, status (`semantic_ready|semantic_unavailable|single_candidate`),
  closed unavailable reason, candidate catalog version/fingerprint, embedding provider/model/
  dimensions/input-policy, query fingerprints, and ordered slot assignments containing candidate
  ref/checksum, section index, selection method, reason code, and similarity band. Never persist
  vectors, full query text, image bytes, private paths, API keys, or provider bodies.
- Use the persisted ordered assignments for render/media recovery. Once `persist_article` succeeds,
  retries must not call the embedding provider or recompute a different order.
- Persist a bounded semantic attempt summary in existing `official_account_article_attempts.safe_metadata`
  if operational audit is needed; the Article Package remains the source of truth.
- Add migration `20260823_0029` from current head `20260823_0028` to accept relational article
  version 4. No additional migration is necessary for selection JSON if existing embedding tables
  are explicitly broadened; otherwise add a separate immutable official-account candidate-vector
  table rather than silently mixing scopes.
- Downgrade must refuse while v4 article rows exist, matching the existing 0028 refusal pattern.

#### Runtime and API

- Add `official_account_local_visual_semantic_enabled=false` as a separate safe default. It may
  reuse the frozen global visual embedding identity and secrets, but enabling ordinary material
  semantic retrieval must not implicitly change official-account bytes.
- The official-account worker should receive an optional lazy `OfficialAccountMediaSemanticRanker`.
  Do not create an Alibaba HTTP client for fixture-only/default execution. Instantiate/use the real
  adapter only after an explicitly live claimed run has two or more index-compatible candidates.
- Reuse `AlibabaVisualEmbeddingAdapter`, `DeterministicFakeVisualEmbedding`, and
  `PostgresVisualIndexRepository`; do not call the API process or the brand-search HTTP route from
  the worker.
- Add safe `media_selection` fields: `selection_mode`, `semantic_status`,
  `semantic_unavailable_reason`, `visual_query_version`, `visual_selector_version`, and a bounded
  embedding identity projection. Per-image output may expose `selection_method` and
  `similarity_band`; preserve historical reason enums. Do not expose raw vectors/query text/private
  asset IDs beyond the existing bounded reference policy.
- The UI can label “多模态语义匹配” versus “确定性标签回退” and the closed reason. It remains a
  development-only explanation, not approval or publish state.
- No code in this phase may call WeChat, WeCom, web search, or image generation. The approved
  candidate catalog must exist before the article run.

### Focused tests

- Domain:
  - freeze v1--v6 prompt/article/HTML/render/export goldens;
  - v7 exact version-family dispatch and mixed-family rejection;
  - query serializer bounds/redaction/stability;
  - 2--5 candidate similarity-matrix assignment, tag-score secondary ordering, stable ties,
    balanced placement, checksum uniqueness, and single-candidate no-op;
  - whole-plan fallback on one missing query score or candidate identity.
- Application/worker:
  - default fixture constructs no visual HTTP client and records zero embedding calls;
  - explicit fake semantic mode produces deterministic v7 assignments without network;
  - live provider is called only after generation and outside repository transactions;
  - incomplete-index preflight makes zero provider calls;
  - provider disabled/auth/timeout/malformed/wrong dimension/catalog race falls back exactly once to
    current tag selection and still reaches a local draft;
  - retry after article persistence performs zero additional semantic calls and reuses the stored
    candidate order;
  - live one-candidate package performs zero semantic calls and remains safely degraded to one
    image.
- Repository/PostgreSQL:
  - exact candidate-catalog coverage and mixed catalog/provider/policy/checksum refusal;
  - v4 Article Package round trip and immutable semantic snapshot;
  - clean `0028 -> 0029 -> 0028` behavior, metadata parity, and downgrade refusal with v4 rows;
  - no transaction held while a blocking fake embedding model waits.
- Provider contract:
  - retain existing `MockTransport` text request, one-attempt, timeout, response bound, identity,
    2048-dimension, finite/non-zero vector, and secret-redaction tests in
    `backend/tests/contract/test_brand_visual_embedding.py`;
  - add only official query/fallback wiring tests, not a live provider call.
- API/frontend/export/runtime:
  - OpenAPI/generated TypeScript drift, semantic-ready/fallback/single-candidate projections,
    historical response compatibility, no vector/query/private path fields;
  - UI labels the method without changing manual review/publish semantics;
  - review and copy-ready ZIP fingerprints bind the v7 selection snapshot;
  - default fixture, tests, and export make zero external requests; Compose keeps the feature off by
    default.

### External references

- Alibaba Model Studio, [Multimodal-Embedding API reference](https://help.aliyun.com/zh/model-studio/multimodal-embedding-api-reference):
  confirms that `qwen3-vl-embedding` supports text and image inputs in one vector space, 2048 as a
  supported output dimension, Base64 image data URIs, and the dedicated multimodal REST endpoint.
- Alibaba Model Studio, [qwen3-vl-embedding model information](https://help.aliyun.com/zh/model-studio/qwen3-vl-embedding):
  describes text/image unified representations and cross-modal retrieval as supported use cases.
- Alibaba Model Studio, [OpenAI-compatible embedding interface](https://help.aliyun.com/zh/model-studio/embedding-interfaces-compatible-with-openai):
  states that multimodal embedding models such as `qwen3-vl-embedding` do not use the
  OpenAI-compatible embedding endpoint. The repository's dedicated adapter is therefore the right
  transport to reuse.

## Caveats / Not Found

- No external provider was called during this research. Only documentation pages were read.
- No current material-package schema or repository method exposes more than one final image
  candidate. Multimodal selection cannot improve current live image variety until that upstream
  contract changes or a separate approved visual candidate catalog is deliberately introduced.
- The fixture PNG masters/publication JPEGs are not members of the current private visual manifest
  and therefore do not have a proven complete qwen3-vl index under the existing catalog identity.
- Existing `VisualRetrievalService` embeds the text before discovering incomplete index coverage.
  A preflight completeness method is not currently present.
- Reusing the `brand_visual_*` tables for generated/material candidate catalogs is a scope change to
  the current visual-retrieval spec. It is acceptable only with explicit versioned catalog
  namespaces and a later spec update; otherwise use a separate table.
- Current approved refinement explicitly says no embedding/model/network call at
  `.trellis/tasks/08-21-wechat-official-account-local-draft-mvp/design.md:278-285`. The main session
  must update PRD/design/implement with a new approved Phase 10 before implementation.
- Research role isolation intentionally did not load `implement.jsonl` or `check.jsonl`; evidence was
  taken from the approved task artifacts, executable specs, current source, and focused tests.
