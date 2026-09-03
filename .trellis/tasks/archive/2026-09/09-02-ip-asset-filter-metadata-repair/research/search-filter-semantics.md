# Research: IP asset search filter semantics

- Query: Trace the production text-search path and define the minimum compatible design needed to
  keep explicit request filters hard, make text-inferred role/type/orientation soft, and distinguish
  `no_filtered_candidates` from `partial_index`.
- Scope: internal
- Date: 2026-09-02

## Findings

### Current production data flow and root cause

1. The browser sends the natural-language `message` separately from the visible filter controls.
   Empty controls are omitted for `character`, `asset_type`, `source_kind`, and `orientation`, while
   non-empty `department` and `tag` are sent as explicit values
   (`frontend/src/features/ip-assets/api.ts:203-235`). This boundary already contains enough
   information to distinguish user-selected filters from inferred intent; no wire request change is
   required.
2. `POST /api/v1/ip-assets/search/text` converts those explicit request fields into one
   `IpAssetQuery`, but also copies `message` into `query`
   (`backend/app/api/v1/routes/ip_assets.py:315-334`).
3. `IpAssetService._search_text` normalizes only the current turn for filter extraction and uses up
   to four prior turns only in the embedding text. It calls `_extract_filters(current, filters)` and
   then passes the returned object to both metadata and vector retrieval
   (`backend/app/application/services/ip_assets.py:487-543`).
4. `_extract_filters` fills missing `character`, `asset_type`, and `orientation` fields from text
   substring rules (`backend/app/application/services/ip_assets.py:1022-1070`). This destroys the
   provenance distinction: after the function returns, an inferred value is indistinguishable from
   a UI/API filter.
5. Metadata search deliberately clears only the free-text `query` before calling `list_assets`; all
   structured fields remain (`backend/app/application/services/ip_assets.py:618-646`). Vector search
   receives the same merged query unchanged (`backend/app/application/services/ip_assets.py:514-522`).
6. PostgreSQL applies every non-empty structured field as equality/tag predicates in `_apply_filters`
   (`backend/app/infrastructure/db/ip_assets.py:1377-1422`). `list_assets` uses those predicates for
   the metadata candidate pool (`backend/app/infrastructure/db/ip_assets.py:356-388`), and
   `search_vectors` uses the same predicates after its ready/shared/embedding-identity boundaries
   (`backend/app/infrastructure/db/ip_assets.py:953-996`). Consequently, a phrase such as “小赛头像”
   currently becomes `character=xiao_sai AND asset_type=portrait_avatar` in both SQL paths. If that
   exact combination is absent, both lanes are empty even when semantically useful Xiao Sai images
   exist.
7. After a successful embedding call, any empty vector result is currently labeled
   `partial_index`, without checking whether the structured-filtered candidate set was empty
   (`backend/app/application/services/ip_assets.py:528-532`). Thus the six live-evaluation
   degradations can describe zero candidates caused by inferred SQL predicates, not missing vectors.

The evaluation-only repository does not cause this behavior. It delegates the query to the real
PostgreSQL repository before restricting rows to the approved 41-asset set
(`backend/evals/ip_asset_retrieval_grounded/assets.py:190-235`). Live Seed V2 also calls the same
`search_text_for_evaluation` service path with no explicit filters
(`backend/evals/ip_asset_retrieval_grounded/live.py:147-205`).

### Compatible minimum design

Use a private, provenance-preserving intent value in the application service instead of returning a
second `IpAssetQuery` whose populated fields are ambiguous. A suitable shape is:

```python
@dataclass(frozen=True, slots=True)
class _IpAssetTextSearchIntent:
    hard_filters: IpAssetQuery
    character_hint: IpAssetCharacter | None
    asset_type_hint: IpAssetType | None
    orientation_hint: IpAssetOrientation | None
```

The extraction rules should obey these invariants:

- `hard_filters` copies only request-owned `character`, `asset_type`, `department`, `source_kind`,
  `orientation`, and `tag`. Its lexical `query` may retain the bounded current text for explanation,
  but repository metadata candidate enumeration must continue to replace it with `""`.
- Infer a hint for a dimension only when the corresponding explicit hard field is absent. This
  preserves the existing “explicit control wins” rule without allowing a conflicting soft hint to
  affect the already-restricted pool.
- Infer only from the normalized current turn. Prior turns stay in the embedding input and never
  become a hint or hard filter.
- Pass only `intent.hard_filters` to `list_assets` and `search_vectors`. A type distinct from
  `IpAssetQuery` is important: it makes accidentally reintroducing inferred SQL filters harder than
  using two conventionally named `IpAssetQuery` objects.
- Feed the three hints only to deterministic in-memory metadata scoring and explanation. Add a
  positive signal when an asset's controlled field equals the hint; a mismatch receives no penalty
  and is never excluded. Existing character/type/orientation display-label maps should be shared or
  centralized rather than duplicated in extraction, scoring, and explanation.
- Preserve current lexical scoring, bounded 500-row candidate fetch, ready/shared vector boundary,
  provider identity, V2/V3 rank selector, result limit, and telemetry behavior. A soft-hint match can
  enter the metadata lane and rank ahead of weaker evidence, but a semantic-only candidate remains
  eligible.

`_search_metadata` also needs to return proof about its pre-ranking pool, not just selected hits. The
minimum private result is:

```python
@dataclass(frozen=True, slots=True)
class _MetadataSearchOutcome:
    hits: tuple[_MetadataSearchHit, ...]
    has_filtered_candidates: bool
```

`has_filtered_candidates` must be computed from `page.items` before lexical/soft-hint scoring. A
boolean is sufficient and avoids pretending that the bounded 500-row page is an exact total count.
It also handles the valid case where assets survive hard filtering but none has positive lexical
evidence.

Recommended text-search precedence:

1. Enumerate the bounded metadata pool using only hard filters and derive
   `has_filtered_candidates`.
2. If false, return empty `degraded_metadata` with `no_filtered_candidates` and do not pay for an
   embedding that cannot produce an eligible row.
3. If candidates exist but embeddings are disabled, return metadata hits with
   `semantic_disabled`.
4. If embedding generation fails, return metadata hits with `provider_unavailable`.
5. If embedding succeeds, candidates exist, and compatible vector retrieval returns no rows, return
   metadata hits with `partial_index`.
6. If at least one compatible vector returns, keep `mode=semantic`, `degraded_reason=null`, and merge
   vector plus metadata lanes as today. Partial coverage is already tolerated by the merge and does
   not need to degrade merely because some metadata candidates lack vectors.

This precedence makes `no_filtered_candidates` a retrieval-domain outcome rather than a provider
failure. It also prevents the existing UI sentence “语义服务暂不可用” from being used when the
provider is healthy and the user's explicit filter has no eligible candidates.

### Closed reason taxonomy and wire compatibility

The current response uses `degraded_reason: str | None`
(`backend/app/schemas/ip_assets.py:162-166`), so OpenAPI and TypeScript expose an arbitrary string
(`backend/openapi.json:8325-8364`, `frontend/src/lib/api/generated/schema.d.ts:4401-4413`). The
application currently emits these values:

- text: `semantic_disabled`, `provider_unavailable`, `partial_index`;
- image: the same values plus `input_normalization_failed`.

Add an application-owned `StrEnum` (for example, `IpAssetSearchDegradedReason`) with exactly:

- `semantic_disabled`
- `provider_unavailable`
- `input_normalization_failed`
- `partial_index`
- `no_filtered_candidates`

Use it in `IpAssetSearchResult`, `_metadata_result`, `_metadata_fallback`, and
`IpAssetSearchResponse`. This is additive on the wire: existing values, `mode`, status code, item
shape, and nullable behavior remain unchanged. Regenerate `backend/openapi.json` and
`frontend/src/lib/api/generated/schema.d.ts`; do not hand-edit either generated file.

The shared frontend rendering should map every reason to bounded Chinese guidance and never append
the raw internal code to user-facing copy. At minimum:

| Reason | Safe presentation intent |
| --- | --- |
| `no_filtered_candidates` | 当前筛选范围内没有可用图片；建议放宽角色、类型或构图筛选。 |
| `partial_index` | 筛选结果暂未建立兼容的语义索引；已展示可用的元数据结果。 |
| `semantic_disabled` | 语义检索尚未启用；当前按图片分类和文字信息查找。 |
| `provider_unavailable` | 语义检索暂时不可用；当前按图片分类和文字信息查找。 |
| `input_normalization_failed` | 图片查询未通过安全处理；可更换图片或使用文字检索。 |

The current component labels every non-semantic result “元数据降级结果” and displays
`语义服务暂不可用：{raw_reason}` (`frontend/src/features/ip-assets/IpAssetHub.tsx:435-453`). The
heading should special-case `no_filtered_candidates` as an empty filtered result, while other
reasons may keep a neutral metadata-result heading. Keep the existing `role=status`/`aria-live`
feedback.

### Exact affected files

Primary product changes:

- `backend/app/application/services/ip_assets.py` — intent provenance, soft-hint scoring,
  candidate-existence proof, reason precedence, and typed reason use.
- `backend/app/domain/ip_assets.py` — closed degraded-reason enum and, if label maps are centralized,
  controlled taxonomy label helpers. Existing V2/V3 rank sort functions should remain unchanged.
- `backend/app/schemas/ip_assets.py` — replace arbitrary response string with the closed enum.
- `frontend/src/features/ip-assets/IpAssetHub.tsx` — safe reason-to-guidance mapping and
  no-candidate heading.
- `backend/openapi.json` and `frontend/src/lib/api/generated/schema.d.ts` — regenerated contract
  artifacts only.

Tests that should change or expand:

- `backend/tests/unit/test_ip_assets.py` — the existing inference assertions at lines 968-1017
  encode hard inference and must be replaced with provenance assertions; add service-level reason
  and provider-call tests.
- `backend/tests/integration/test_ip_assets.py` — retain the current repository exact-filter checks
  at lines 190-202 and vector-filter checks at lines 226-239; add or extend a real PostgreSQL service
  case proving text hints do not enter `_apply_filters` while explicit filters still do.
- `frontend/src/features/ip-assets/IpAssetHub.test.tsx` — replace the raw
  `provider_unavailable` assertion at lines 393-400; cover safe copy for no candidates and partial
  index.
- `frontend/src/features/ip-assets/api.test.ts` — assert explicit non-empty controls remain present
  and empty controls remain omitted; generated reason typing should flow through without a
  handwritten response type.
- `backend/tests/unit/test_ip_asset_retrieval_grounded_eval_v2.py` and the grounded runner need no
  algorithm rewrite, but provider-free/live regression should accept and aggregate the new closed
  reason. A later authorized live run will change the six formerly misclassified observations.

No repository protocol or SQL helper signature must change for the minimum design. Keeping all
inferred hints above `IpAssetRepository` is the cleanest enforcement of “soft means never SQL.”

### Required regression matrix

Backend unit/service:

- Text-only `小赛头像` with no explicit filters: repository metadata/vector queries have
  `character=None` and `asset_type=None`; matching Xiao Sai/avatar assets receive positive soft
  evidence, while nonmatching semantic hits remain eligible.
- Text-only `透明底` and `方图`: generic terms are soft signals, not SQL filters. Confirm whether
  transparent intent matches `asset_type=transparent_cutout`, actual `has_alpha`, or both; the
  decision must be deterministic and documented.
- Explicit `character=sai_xiansheng` with text mentioning Xiao Sai: every repository query retains
  the explicit Sai Xiansheng filter and suppresses the conflicting character hint.
- Explicit role/type/orientation/source/department/tag combinations remain exact and conjunctive.
- Prior-turn role/type conflicts never appear in hard filters or hints for the current request.
- No hard-filtered candidates: `no_filtered_candidates`, empty items, zero embedding calls, and one
  ordinary `zero_results` telemetry increment; evaluation path still records no business metric.
- At least one filtered candidate but zero compatible vectors: `partial_index`, bounded metadata
  items, and exactly one embedding call.
- Candidate(s) plus provider failure: `provider_unavailable`, not `partial_index`.
- Candidate(s) plus semantic hit(s): `semantic`/null reason and deterministic V2/V3 ordering.
- Unknown or impossible degraded reason cannot be constructed at typed backend boundaries.

PostgreSQL integration:

- The same natural-language request can retrieve across multiple taxonomy values when no explicit
  filter is supplied.
- Adding the equivalent explicit filter narrows both metadata and compatible-vector queries.
- A nonexistent explicit combination returns the new reason, while an existing unindexed
  combination returns `partial_index`.
- Shared/visibility and compatible embedding identity remain enforced; softening inference must not
  surface private, unready vector, or identity-mismatched rows.

Frontend/component:

- Each closed reason renders its safe bounded guidance; raw codes are absent from visible text.
- `no_filtered_candidates` does not claim the semantic provider is unavailable and preserves the
  “返回完整图库” recovery action.
- `partial_index` explains metadata fallback without presenting cosine as confidence.
- Semantic results, search errors, profile-aware favorite projection, and existing accessible live
  feedback remain unchanged.

### Edge cases

- A query containing both “小赛” and “赛先生”, or explicit dual-role terms such as “同框”, should
  create only a soft `duo` hint when no explicit character filter exists; it must not exclude
  single-character images that semantic ranking considers useful.
- Preserve phrase precedence (`表情包` before `表情`) so a longer controlled term is not reduced to
  the wrong hint.
- Negation is currently substring-blind (`不要头像`, `不要小赛`). Because hints are non-excluding,
  this becomes a ranking-quality issue rather than a zero-result correctness failure. Do not add
  ad-hoc hard negation in this repair; either suppress obvious negated hint phrases with focused
  tests or defer richer intent parsing to a separately versioned policy.
- `透明底` is not equivalent to “transparent-cutout asset type” in every user sentence. The current
  code intentionally keeps generic transparent-background wording lexical, but the current lexical
  fields do not include `has_alpha`. The repair must choose explicitly between a soft type hint and
  a separate alpha/background hint; neither may become SQL unless the API later gains an explicit
  alpha filter.
- An empty whole shared corpus has no explicit user filter but also cannot truthfully be called
  `partial_index`. Reuse `no_filtered_candidates` with UI wording “当前筛选范围” (where the shared
  visibility boundary is an implicit hard scope), or introduce a separate `no_searchable_candidates`
  reason. The five-value minimum above favors compatibility and the task's requested taxonomy.
- Metadata candidate existence and vector retrieval are separate reads. A concurrent metadata/share
  update can invalidate the first observation before the vector query. There is no unshare/delete
  product action today, so the race is narrow; do not introduce a long database transaction around
  a provider call.
- `_search_metadata` currently admits unmatched candidates whenever any structured filter exists.
  After provenance is preserved, only explicit hard filters should trigger that behavior. Soft hints
  should add scores but should not cause every unmatched corpus asset to enter the metadata lane.
- Image search shares the response type and `partial_index` behavior but has no text inference. At
  minimum it must compile with the closed enum and show safe copy. Applying the same
  candidate-existence precedence to image search is desirable for consistent error semantics, but
  it should not weaken its mandatory raster validation-before-provider rule.

### Search-version caveat

`rank_ip_asset_candidates` explicitly describes V2 and V3 as frozen rank policies
(`backend/app/domain/ip_assets.py:146-163`), and the backend spec states V2 weights/order must not be
silently changed (`.trellis/spec/backend/ip-asset-hub.md:224-226`). The proposed repair leaves the
sort keys and RRF constants unchanged, but it changes candidate admission and metadata evidence, so
historical V2/V3 outputs will not be byte-reproducible from `search_version` alone.

For the smallest user-facing repair, treat this as a pre-ranking correctness fix applied to both
configured versions, retain their sort policies, and require the planned post-repair evaluation to
record the new code commit plus asset/query hashes. If the project interprets `search_version` as
the identity of the entire retrieval pipeline rather than only the rank selector, create a new
version before changing production defaults; that alternative also requires configuration literals,
search-aggregate database constraints/migration, OpenAPI unions, eval CLI choices, and reports, and
is materially larger than the current task. The main implementation/design owner should make this
choice explicit rather than silently assuming either interpretation.

## Files found

- `frontend/src/features/ip-assets/api.ts` — generated-client wrapper that keeps message and explicit
  filter controls distinguishable on the request wire.
- `backend/app/api/v1/routes/ip_assets.py` — maps the text-search request into `IpAssetQuery` and
  projects the service result.
- `backend/app/application/ports/ip_assets.py` — defines the shared `IpAssetQuery` repository value;
  it currently has no provenance field and should remain a hard-query type.
- `backend/app/application/services/ip_assets.py` — owns inference, metadata ranking, vector merge,
  degraded reasons, and the faulty hardening of inferred terms.
- `backend/app/infrastructure/db/ip_assets.py` — applies every structured `IpAssetQuery` field as SQL
  and correctly should not receive inferred hints.
- `backend/app/domain/ip_assets.py` — owns search modes/versioned rank policies and is the compatible
  home for a closed search degraded-reason enum.
- `backend/app/schemas/ip_assets.py` — exposes the currently stringly typed reason.
- `frontend/src/features/ip-assets/IpAssetHub.tsx` — renders one inaccurate sentence plus raw reason
  for every degraded outcome.
- `backend/evals/ip_asset_retrieval_grounded/live.py` — proves live evaluation exercises the same
  production service path without explicit filters or business telemetry.
- `backend/evals/ip_asset_retrieval_grounded/assets.py` — bounds the live corpus after the real
  repository filters; not the source of inferred hard filtering.
- `backend/tests/unit/test_ip_assets.py` — current service, inference, merge, telemetry, route, and
  response tests.
- `backend/tests/integration/test_ip_assets.py` — real PostgreSQL metadata/vector filter coverage.
- `frontend/src/features/ip-assets/IpAssetHub.test.tsx` — current component test expects a raw
  provider reason and must change to user-safe guidance.
- `backend/openapi.json` and `frontend/src/lib/api/generated/schema.d.ts` — checked-in generated wire
  contract artifacts.

## Code patterns

- Preserve explicit request ownership: optional UI controls are omitted rather than populated from
  message text (`frontend/src/features/ip-assets/api.ts:212-230`).
- Keep current-turn inference separate from historical embedding context
  (`backend/app/application/services/ip_assets.py:495-521`).
- Continue fetching a bounded metadata pool with `query=""` before in-memory ranking
  (`backend/app/application/services/ip_assets.py:618-646`).
- Keep exact hard predicates centralized in `_apply_filters`
  (`backend/app/infrastructure/db/ip_assets.py:1377-1422`).
- Continue deterministic lane fusion through the versioned domain selector
  (`backend/app/application/services/ip_assets.py:1123-1170` and
  `backend/app/domain/ip_assets.py:146-163`).
- Regenerate, never hand-edit, OpenAPI-derived frontend wire types
  (`.trellis/spec/frontend/type-safety.md`, “OpenAPI-generated wire types”).

## External references

None. This is an internal application/data-flow correction and does not require a new external
library, provider feature, protocol, or version.

## Related specs

- `.trellis/spec/backend/ip-asset-hub.md:213-241` — current RRF, explicit-filter authority,
  current-turn inference, metadata ranking, and degradation contracts. Lines 228-231 currently say
  inferred terms may be filters and must be updated because they conflict with this task's PRD.
- `.trellis/spec/backend/ip-asset-hub.md:315-335` — current error matrix for provider degradation,
  partial vector coverage, structured candidates, and history conflicts; it lacks the requested
  zero-candidate/partial-index distinction.
- `.trellis/spec/backend/ip-asset-hub.md:427-432` — required search unit/live-corpus regression shape.
- `.trellis/spec/frontend/ip-asset-hub.md:127-141` — UI contract for semantic/degraded results,
  qualitative explanations, favorite projection, and preserving the gallery on failures.
- `.trellis/spec/frontend/type-safety.md` — generated OpenAPI types own wire enums; no handwritten
  duplicate reason union.
- `.trellis/spec/backend/error-handling.md` — expected domain outcomes should be typed results, not
  unhandled exceptions; user guidance should expose a safe next action rather than internal detail.
- `.trellis/spec/frontend/quality-guidelines.md` — component tests should assert visible accessible
  behavior and generated-contract drift must pass.

## Caveats / Not Found

- No `design.md` or populated `implement.md` was present when this research was performed; this file
  should inform those artifacts before implementation decisions are finalized.
- Per Trellis researcher role isolation, `implement.jsonl` and `check.jsonl` were not read.
- The current code has no repository method that directly reports compatible-vector coverage for a
  filtered pool. The minimum design intentionally needs only “metadata candidates exist” plus the
  existing empty/non-empty vector result; it does not claim an exact coverage count.
- The requested metadata dry-run/apply pipeline is a separate research topic and is not analyzed
  here.
- No provider was called, no database was queried or mutated, and no product/spec/generated file was
  changed by this research.
