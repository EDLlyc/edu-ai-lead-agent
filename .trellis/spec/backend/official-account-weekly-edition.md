# Official-Account Weekly Three-Article Edition

## 1. Scope / trigger

- Use this contract when one `Asia/Shanghai` week must produce exactly three independent local
  official-account handoffs: `official_anchor`, `industry_trend`, and `application_case`, in that
  order.
- This is an aggregate above three complete V2 handoffs. It is not the existing
  morning/noon/evening content-slot pipeline, not one Article containing three news items, and not
  a social-publishing adapter.
- The current delivery is development-only. The pure due function is scheduler-ready, but no
  scheduler, database migration, provider call, WeChat call, or WeCom call is added by this slice.

## 2. Signatures

```python
schedule = WeeklyEditionSchedule(
    weekday=0,
    target_time=time(hour=9),
    timezone="Asia/Shanghai",
    catchup_hours=24,
)
week_start = due_weekly_edition_week_start(
    now,
    schedule=schedule,
    completed_week_starts=completed_week_starts,
)
selection = select_weekly_articles(
    governed_candidates,
    week_start=week_start,
    cutoff=cutoff,
    schedule=schedule,
)
child = load_finalized_v2_child(child_directory, role=role)
binding = bind_weekly_child(selected=selected, child=child)
artifact = build_weekly_edition_artifact(
    selection=selection,
    schedule=schedule,
    children=children,
    bindings=bindings,
)
target = write_weekly_edition_artifact(artifact, fresh_output_root)
```

```bash
conda run --name edu-ai python -m app.official_account_weekly_edition_demo \
  --selection-json /path/to/weekly-selection.json \
  --child official_anchor=/path/to/finalized-official-v2 \
  --child industry_trend=/path/to/finalized-industry-v2 \
  --child application_case=/path/to/finalized-application-v2 \
  --output-dir /fresh/local/output
```

```bash
conda run --name edu-ai python -m app.official_account_weekly_edition_live_demo \
  --live-input docs/portfolio/fixtures/official-account-weekly-live-theme-clusters-YYYY-MM-DD.json \
  --output-dir /fresh/local/output
```

## 3. Contracts

- The schedule policy is versioned, fixed to `Asia/Shanghai`, and binds weekday, local target time,
  catch-up duration, and the unit `one_weekly_batch_with_three_independent_articles`. The default
  is Monday 09:00 with a 24-hour catch-up window; callers may configure weekday/time without
  changing the three-article unit.
- `week_start` is always a Monday and must equal the local week containing `cutoff`. The seven-day
  current window and fourteen-day official lookback are inclusive at the boundary and exclude
  future events.
- Weekly preference runs only after the existing immutable topic score says a candidate is
  eligible and veto-free. It never changes a threshold, score, veto, evidence, or daily-slot rank.
- Official authority is true only when stored `organization_type == "government"` or the stored
  topic-priority policy is one of the authenticated official policies. A title containing an
  agency name is not authority. If no eligible official item exists within fourteen days, the best
  current eligible candidate may fill the first role only with
  `official_source_unavailable_fallback` and `official_authority=null`.
- Industry/application affinity uses stored editorial cohort, content-signal, product-direction,
  and frontier-significance projections only as deterministic ordering preferences. All three
  selected event IDs and event-version IDs must differ.
- Every child must be a finalized V2 `quality_auto` local-only, unpublished, copy-ready artifact
  with exact passed 320/430 mobile validation and zero external requests. Event/version-to-child
  bindings include role, run, Article/content/artifact fingerprints, and child ZIP SHA-256.
- The aggregate preserves every child file and child ZIP byte-for-byte under canonical ordinal
  role directories. Its batch fingerprint binds the ordered selection, schedule, bindings, and
  all child identities. It emits `index.html`, `weekly-index.json`, `README.md`, `manifest.json`,
  and one deterministic outer ZIP. Manifest v3 and the index both expose the exact zero counters
  for news, model, Embedding, image-generation, WeChat, and WeCom; `published=false`.
- Unit fixtures may use explicit synthetic mobile bindings. A named acceptance export must instead
  consume browser reports actually produced for each exact child at 320 and 430 pixels with images
  loaded, no overflow, exact copy-root equality, and all non-local requests blocked.

## 4. Validation and error matrix

| Condition | Required result |
|---|---|
| Naive `now`/`cutoff`, non-Monday `week_start`, or cutoff belongs to another local week | Raise a stable `ValueError`; do not select |
| Duplicate candidate event or event-version identity | Reject before ranking |
| Candidate is ineligible, vetoed, future-dated, or older than fourteen days | Exclude it; weekly affinity cannot rescue it |
| No bounded candidate, or fewer than two distinct current candidates after the official slot | Raise a stable insufficiency error; emit no partial batch |
| Official reason lacks authenticated stored authority, or fallback claims authority | Reject the selection projection |
| Role reason/affinity fields disagree, a total is non-finite, or projection fingerprint changes | Reject deserialization |
| Child is not released/local/copy-ready/unpublished/passed, or a file/hash/ZIP/path changes | Reject before aggregation |
| Any event/version, run, Article/content/body/artifact, title, or child-ZIP identity repeats | Reject the weekly batch |
| Selected event and child binding disagree | Reject instead of silently cross-wiring articles |
| Theme-cluster order/relation changes, the official primary is not registered government, or a source identity repeats across clusters | Reject before building a child; never widen or substitute a source |
| A source-scoped claim, evidence row, or context image is projected under another cluster/source | Reject aggregation instead of treating the shared theme as evidence |
| Output or temporary target already exists | Never overwrite; install no partial directory |

## 5. Good / base / bad cases

- Good: a current authenticated official event plus two current eligible role-affine events become
  three distinct finalized handoffs and one byte-stable local weekly ZIP.
- Base: no current official item exists, but an eligible official item at exactly fourteen days is
  selected with `official_14_day_lookback`; the other two articles remain current-window items.
- Honest fallback: no eligible official item exists within fourteen days, so the first role records
  `official_source_unavailable_fallback` without claiming official authority.
- Theme-cluster good: one shared editorial theme relates six independently fetched sources while
  every rendered fact, evidence row and image remains labelled primary/supporting and source-bound.
- Bad: infer authority from a title, reuse one Article under three labels, accept a vetoed event,
  fabricate browser validation, overstate a headline beyond its sources, treat a call for submissions
  as proof of a successful application, mutate child bytes while aggregating, or invoke any social client.

## 6. Tests required

- Unit-test the Shanghai due instant, catch-up boundary, completed-week suppression, current
  seven-day boundary, official fourteen-day boundary, older exclusion, truthful fallback,
  affinity ordering, veto preservation, duplicate identities, insufficient pools, and strict
  projection fingerprints.
- Unit-test three distinct event-to-child bindings, deterministic replay, byte preservation,
  child manifest/file/ZIP tampering, cross-wiring, no-clobber writes, and socket-blocked fixtures.
- Regress V1/V2 handoff tests and the existing content-slot tests to prove this aggregate changed no
  historical bytes or morning/noon/evening semantics.
- For a named local export, run the gzh validator on all three clean bodies to zero errors/warnings,
  Playwright on every child at exact 320/430 with zero external requests, outer/child ZIP integrity,
  focused Ruff/format/mypy/pytest, task validation, and `git diff --check`.
- Theme-cluster regressions must cover V1 compatibility, exact twelve-call MockTransport ordering for
  six sources, global identity uniqueness, cluster containment, editorial-title boundaries, page-chrome
  and ceremonial-roster filtering, rendered-slot fact priority, solicitation-as-context wording, and
  machine-enum exclusion from operator-facing Markdown/HTML.

## 7. Wrong vs correct

Wrong:

```python
# The title is untrusted content and cannot authenticate the source.
is_official = "教育部" in candidate.priority_title
weekly_articles = (one_article, one_article, one_article)
```

Correct:

```python
governed = WeeklyGovernedCandidate(
    candidate=candidate,
    score=immutable_score,
    organization_type=stored_source.organization_type,
    source_metadata_fingerprint=stored_source.config_fingerprint,
)
selection = select_weekly_articles(
    candidates,
    week_start=week_start,
    cutoff=cutoff,
    schedule=schedule,
)
# Build and bind three independently finalized V2 children in canonical role order.
```

Wrong:

```python
editorial_title = "AI 通识课已经全面落地"  # The two sources only describe events.
rendered_fact = supporting_source.sentences[0]  # May be page chrome or a ceremonial roster.
```

Correct:

```python
editorial_title = "从 AI 嘉年华到科技夏令营：学校需要哪些准备"
rendered_fact = select_complete_source_fact(
    supporting_source,
    exclude_page_chrome=True,
    exclude_ceremonial_rosters=True,
    required_slot="supporting_follow_up",
)
```

## 8. Homepage pin operator handoff

- Apply the versioned role policy exactly: `official_anchor` is `pinned_primary` with
  `homepage_pinned_large_card_candidate`; `industry_trend` and `application_case` are `standard`
  with `homepage_standard_thumbnail_candidate`.
- Reuse each child's one `assets/cover-wide.*` file without changing it. Decode the cover bytes and
  require the manifest checksum, byte size, media type and actual width/height to agree before
  projecting the 2.35:1 source profile. Composition guidance is center-safe intent only; WeChat
  owns the actual homepage card, crop and UI.
- Keep the same role order, display intent and cover purpose visible in `weekly-index.json`, the
  manifest, `index.html`, `README.md` and both operator-checklist formats. The immutable bundle
  contains only the deterministic `not_published` state. Batch identity binds the manifest, index,
  presentation, display-policy, operator-state and checklist versions so changed projection bytes
  cannot reuse an earlier content-addressed batch name.
- A safe, identity-bound `publication_confirmed` event with an HTTPS `mp.weixin.qq.com` article URL
  advances to `awaiting_manual_pin`. Only a later explicit `homepage_pin_confirmed` event advances
  to `confirmed`. Reject skips, replayed event IDs, time reversal, type drift and batch/official
  Article identity mismatch.
- Serialize later states as deterministic, fingerprint-named, no-clobber sidecars outside the
  immutable weekly directory. Never rewrite the weekly manifest, ZIP, indexes or child bytes.
- The checklist must direct the operator through
  `群发功能 -> 已发送 -> 找到文章 -> 更多 -> 置顶到公众号主页`. This slice constructs no WeChat,
  WeCom, provider, network, private-endpoint or browser-automation client and never infers external
  publication or pin success.

Required tests cover the exact three-role mapping and cross-format parity, decoded cover dimensions,
strict event/state projection, invalid publication URLs and operator references, sidecar no-clobber
and immutable-directory rejection, child byte preservation and deterministic outer ZIP integrity.

## 9. Role-distinct offline fixture visuals

- The default weekly fixture must build three role-specific visual sets from frozen local science-scene
  backgrounds and approved Xiaosai/Sai Xiansheng assets. It must not read ignored historical `output/`
  trees, construct a provider client, or claim news acquisition, Embedding, model, image-generation,
  WeChat, or WeCom execution.
- Every role owns one metadata-free JPEG homepage cover at `1923x818` and three metadata-free JPEG body
  visuals at `1536x1024`. Covers must differ by file SHA-256 and decoded RGB pixel SHA-256. The three
  ordered body-media hash sets must differ across roles, all nine body SHA/pixel fingerprints must be
  globally unique, and a fixture article may not repeat one body payload within its own set.
- Each body visual must retain visible Xiaosai and Sai Xiansheng elements, an exact target-block binding,
  a bounded role-specific scene brief, safe reference identities and checksums, and its generated output
  checksum. Fixture lineage uses `deterministic_fixture_semantic` and `provider_execution=not_claimed`;
  it never fabricates a multimodal or paid-generation call.
- Synthetic context images are layout fixtures only. Their alt, caption, and credit must explicitly say
  they are local placeholders rather than news-scene originals or factual evidence.
- Weekly aggregation decodes and validates declared media bytes before copying children. It fails closed
  on cover hash reuse, cover pixel reuse, repeated ordered body hash/pixel sets, manifest hash or size
  drift, and decoded dimension drift. Regression tests must include metadata-only JPEG mutations for
  both cover and body sets to prove that distinct file hashes cannot conceal identical decoded pixels.

## 10. Explicit live distinct-news export

- Live acquisition is available only through the development CLI with an explicit `--live-input`
  JSON file. The file must contain the canonical three-role order and exactly one code-registered
  HTTPS source page plus one or two same-source preferred images per role. It cannot widen host,
  path, crawl-policy, publisher, authority, selector, redirect, size, MIME, or raster boundaries.
- The three registered source keys, projected publishers, local event dates, canonical URLs, event
  IDs, event-version IDs, evidence IDs, page hashes, and context-image hashes must be distinct. A
  repeated date or publisher fails before the first network request.
- Reuse `SafeHttpFetcher`, `HtmlConnector`, and `SafeSourceImageFetcher`. The official role requires
  a registered `government` source; page title, canonical URL, local publication date, and every
  preferred image discovered on that exact page must match before any child is built. A fetch,
  extraction, image, rights-provenance, or identity failure aborts the complete batch.
- Each child replaces the structural shell's title, digest, lead, source, claims, evidence, prose,
  context media, run identity, and every dependent fingerprint with its own fetched event. Never
  inherit one role's source, evidence, context image, or event identity into another role. News
  originals remain `context_only_not_evidence=true` and
  `rights_status=publish_permission_unverified`; preserve existing source marks and watermarks.
- Evidence excerpts are bounded only at complete sentence or complete source-line-group boundaries.
  A closing `”`, `’`, or `》` belongs to the preceding sentence even when source HTML puts it at the
  start of the next paragraph. Xinhua photo captions containing reporter/photo credits are excluded
  before excerpt selection; caption removal must not truncate a neighboring factual source line.
- The aggregate includes `live-acquisition.json` with exact requested/final/canonical URLs, source
  and event identities, page/image media types, byte sizes, SHA-256, raster dimensions, fetch times,
  credit/rights boundaries, and exact call counts. Source-page and news-image calls are non-zero only
  for this explicit run; model, Embedding, image-generation, WeChat, and WeCom remain zero.
- The named live CLI writes each staged child to a temporary local directory and runs the exact
  repository Playwright acceptance at 320/430 before binding `passed`; it must not manufacture a
  passed mobile projection. Unit tests may inject the existing synthetic binding only while using
  `MockTransport` and never present that result as the named live acceptance export.
- The default fixture and every unit test remain network-free. Live tests use `MockTransport` plus a
  controlled public resolver and prove distinct source/page/image identities, same-host enforcement,
  authority rejection, failure propagation, exact counters, and no provider or social construction.

## 11. Theme-cluster live input V2

- `official-account-weekly-live-input-v2` is additive to the single-source V1 contract. It requires
  one explicit shared theme and the canonical ordered angles `official_policy`, `industry_method`,
  and `application_practice`. Each article cluster owns one primary and at least one supporting
  code-registered HTTPS source; this bounded MVP fixes that to exactly one supporting source because
  the existing Article context snapshot accepts at most two items. The official cluster's primary
  remains authenticated government.
- Fetch only the explicitly registered pages and preferred images through the existing safe page and
  image fetchers. Do not widen hosts, paths or crawl depth. Across the whole batch, canonical URLs,
  page hashes, event IDs, event-version IDs, evidence IDs and context-image hashes must all be unique.
- Claims, evidence and context images remain contained by their owning article cluster and exact
  source. A shared editorial theme can relate sources but cannot substitute for source evidence.
  Preserve primary/supporting labels in Article JSON/HTML, weekly indexes/manifests and the versioned
  acquisition audit. News originals stay context-only with unverified publish permission and source
  marks preserved.
- Editorial titles and synthesis prose must remain within what the paired sources can support. Before
  evidence slicing, remove page chrome such as publication labels/view counts, photographer captions
  and complete ceremonial attendee/roster sentences. Relevance preference is not enough by itself:
  the preferred method/application fact must occupy a slot that the renderer actually emits. A call
  for submissions or evaluation framework is context for later replication checks, never proof that
  the primary practice already succeeded.
- Machine JSON retains exact enums such as `publish_permission_unverified`; operator-facing Markdown,
  HTML and indexes render localized explanations instead of leaking internal enum tokens.
- Call counters are variable but exact: one page and one image call for every accepted source in the
  current bounded input, while model, Embedding, image generation, WeChat and WeCom stay zero. Default
  fixtures remain zero-network; tests use `MockTransport` and a controlled resolver.
- A named live export must run the real repository Playwright acceptance for each exact staged child
  at 320 and 430 before final aggregation. All images load, the copy root matches the clean body, and
  external browser requests remain zero. Any failed child aborts the weekly batch.
