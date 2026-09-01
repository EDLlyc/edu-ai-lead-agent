# Offline Official-Account Editorial Repackage

## Scenario: Repackage an inspected news/IP bundle without new provider work

### 1. Scope / Trigger

- Trigger this operator-only path when a ready `official-account-news-ip-live-demo-v1` bundle needs a new original
  mobile editorial treatment while retaining its exact evidence snapshots and generated company-IP image bytes.
- This is not a worker stage, API, acquisition path or publisher. It must not read credentials or construct HTTP,
  article-model, embedding, image-provider, WeChat, WeCom or publish clients.
- Historical render families and source output directories are immutable. A repackage always uses a fresh destination.

### 2. Signatures

Command:

```bash
cd backend
python -m app.official_account_news_editorial_demo \
  --source-dir ../output/official-account-news-ip-20260824-v1 \
  --output-dir ../output/official-account-news-ip-editorial-20260824-v2
```

Python entry points:

```python
load_source_bundle(source_dir: Path) -> EditorialSourceBundle
build_editorial_article(bundle: EditorialSourceBundle) -> ArticlePackage
render_editorial_html(article: ArticlePackage) -> str
export_editorial_bundle(source_dir: Path, output_dir: Path) -> Path
```

### 3. Contracts

Source contract:

- Exact source version: `official-account-news-ip-live-demo-v1`; `run.json`, `evidence.json`, `visual-map.json` and
  every declared manifest file must match manifest byte sizes and SHA-256 digests.
- Run and manifest stay `ready`, simulated, unpublished and share one UUID. Manual review remains `pending`.
- Distribution calls are zero. Historical image ledger is exactly ToApis / `gpt-image-2`, three attempted, three
  succeeded, one attempt per image, with zero article, embedding, Comfly and source-fetch calls in that source run.
- Evidence is exactly the two pinned Ministry of Education snapshots, including URL, retrieval URL, date, title,
  bounded quote, evidence UUID and document checksum.
- Images are exactly three distinct, metadata-free 1536x1024 JPEGs. Each visual row retains the pinned v3 visible-IP
  plan/prompt, block/request/reference-input fingerprints, approved catalog version/public ref, publication profile,
  one provider attempt and passed local IP visibility.

Article/render contract:

- The new structured `ArticlePackage` has six sections, exactly three image blocks at sections 0, 2 and 4, and a
  body count from 1,800 through 2,600 non-whitespace characters.
- Every external-fact claim uses only the two approved evidence IDs. Opinion claims carry no evidence or brand IDs;
  brand-statement claims are not admitted.
- Renderer/style/template identities are `wechat-news-editorial-renderer-v2-reference-learned`,
  `wechat-news-editorial-style-v2-paper` and `wechat-news-editorial-template-v2-mobile`.
- The renderer escapes all text and attributes. Source links are restricted to the two pinned HTTPS Ministry of
  Education URLs. Body images resolve only to `assets/body-00.jpg` through `body-02.jpg`.

Output contract:

- Required projections are `article-package.json`, `article-body.html`, `article.md`, `preview.html`,
  `evidence.json`, `visual-map.json`, `reference-learning.json`, `run.json`, `manifest.json`, `README.md`, three
  assets and a deterministic ZIP.
- The repackage writes to a temporary sibling, completes validation and archive creation, then renames into the new
  destination. It rejects any existing destination and removes a failed temporary tree.
- Run/manifest truth is `ready`, `simulation=true`, `local_only=true`, `manual_review_status=pending`,
  `copy_ready=false`, `published=false`. Current repackage external calls are zero; the three historical paid image
  calls are labeled separately as inherited provenance.
- No environment key is required or read.

### 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| Source directory/file is missing, symlinked, oversized or invalid JSON | Reject before article assembly |
| Manifest path is absolute, non-normalized, traversing, duplicate or checksum/size-mismatched | Reject the bundle |
| Run/manifest status, UUID, review, provider ledger or no-distribution boundary drifts | Reject the bundle |
| Evidence UUID/document digest/URL/date/title/quote drifts | Reject the bundle |
| Visual v3 identity, public ref, fingerprint, inspection or provider-attempt field drifts | Reject the bundle |
| JPEG MIME, dimensions, metadata, checksum or distinctness drifts | Reject the bundle |
| Article length, source set, claim binding, media placement or version drifts | Reject rendering/export |
| Destination already exists or is a symlink | Raise `FileExistsError`; preserve destination bytes |
| Any write fails before final rename | Remove the temporary tree; do not create a plausible final bundle |

### 5. Good / Base / Bad Cases

- Good: a complete inspected v1 bundle produces a six-section, 1,800--2,600-character original editorial package,
  reuses all three JPEGs byte-for-byte and records zero current external calls.
- Base: repeated source validation and article/render construction are read-only and deterministic; they do not
  require credentials or a network connection.
- Bad: editing an evidence digest, a v3 request fingerprint, an undeclared manifest file, a JPEG byte or any
  pending/unpublished/call-ledger field fails closed before a destination is installed.

### 6. Tests Required

- Assert six sections, target body length, complete claim reference coverage, every fact evidence binding and every
  opinion's empty evidence/brand bindings.
- Inject unsafe title text and source/version/binding drift; assert escaped HTML or deterministic rejection.
- Block sockets, export twice to separate parents and assert identical ZIP bytes, exact image bytes, three loaded
  image paths and zero current call counters.
- Tamper manifest-declared JSON, evidence identity, visual contract and JPEG bytes; assert source rejection.
- Pre-create a destination and inject a write failure; assert no overwrite and no remaining partial directory.
- Run focused Ruff, format check, PyCompile, mypy, pytest and `git diff --check`. Browser acceptance at both 430 px
  and 320 px must show three loaded images, zero external requests and no horizontal overflow.

### 7. Wrong vs Correct

Wrong:

```python
# Silently restyle whatever files happen to be in a directory and record the old three calls as new work.
for image in source_dir.glob("*.jpg"):
    shutil.copyfile(image, output_dir / image.name)
run["image_provider_calls_in_repackage"] = 3
```

Correct:

```python
bundle = load_source_bundle(source_dir)  # validates complete pinned evidence/manifest/visual contracts
article = build_editorial_article(bundle)
export_editorial_bundle(source_dir, fresh_output_dir)  # atomic, no-clobber, zero current calls
```

## Scenario: High-rhythm science-magazine v3

### 1. Scope / Trigger

- Use the additive v3 command when a verified source needs materially stronger mobile editorial hierarchy than the
  frozen warm-paper v2 output. Never edit the v2 module, renderer identities, output tree or ZIP in place.
- V3 reuses `EditorialSourceBundle` and `load_source_bundle` from v2 as its only source boundary. It must not copy,
  relax or bypass the manifest/evidence/visual-contract validator.

### 2. Signatures

```bash
cd backend
python -m app.official_account_news_editorial_polished_demo \
  --source-dir ../output/official-account-news-ip-20260824-v1 \
  --output-dir ../output/official-account-news-ip-editorial-20260824-v3
```

```python
build_polished_article(bundle: EditorialSourceBundle) -> ArticlePackage
render_polished_html(article: ArticlePackage) -> str
export_polished_bundle(source_dir: Path, output_dir: Path) -> Path
```

### 3. Contracts

- Exact v3 identities are `official-account-news-editorial-schema-v3-science-magazine`,
  `wechat-news-editorial-renderer-v3-science-magazine`,
  `wechat-news-editorial-style-v3-navy-cobalt-orange` and
  `wechat-news-editorial-template-v3-high-rhythm-mobile`.
- The validated Article Package contains six exact module shapes, 1,800--2,600 body characters, complete claim
  references, only approved fact evidence, unbound opinions, three media slots at sections 0/2/4 and one cover slot.
- The AI/child responsibility panel must consume one Article Package opinion list with four exact items: two
  AI-assistance items and two child-owned judgment items. The renderer cannot invent or summarize those assertions.
- HTML contains one `h1`, exactly one placeholder for each of three body images and these eight single-use markers:
  `hero`, `opening-visual`, `policy-tiles`, `parent-question-cards`, `learning-loop-rail`, `ai-child-boundary`,
  `action-timeline`, `closing-takeaway`.
- Phrase emphasis first escapes the full text, then wraps only frozen exact allowlisted substrings. Renderer-only
  labels describe layout; dates, product claims, scene claims and other factual/editorial assertions are forbidden.
  Author and image alt text come from the validated package and are escaped.
- The output file set, atomic no-clobber behavior and deterministic ZIP contract match v2 under a new v3 identity.
  Run and manifest both project each current source/article/embedding/image/Comfly/ToApis/WeChat/WeCom/publish call
  counter as zero. The three historical paid calls remain separate inherited provenance.
- No environment key is required or read.

### 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| V2 source validator rejects any source contract | Stop before v3 Article Package construction |
| V3 version, content fingerprint, section shape, list count or claim/source binding drifts | Reject build/render |
| AI/child list is absent, reordered, expanded or no longer opinion-bound | Reject build/render |
| Image placement/media slot or one-placeholder-per-ordinal contract drifts | Reject render/export |
| Any module marker is missing or duplicated | Reject render |
| Source URL is not one of the two pinned HTTPS Ministry links | Reject render |
| Existing/symlink destination or injected write failure | Preserve destination or remove temporary tree |
| Output manifest omits a per-capability zero counter | Fail focused contract tests |

### 5. Good / Base / Bad Cases

- Good: the validated source yields the current 2,182-character package, one early full-width IP image, six distinct
  editorial forms, three byte-identical JPEGs and zero current external calls.
- Base: build/render are deterministic and provider-free; repeating them against the same source yields the same
  Article and render fingerprints.
- Bad: hardcoding a new date, scene description or AI responsibility in renderer HTML bypasses the Article Package
  and is rejected by review/tests even when the string is visually attractive.

### 6. Tests Required

- Assert exact v3 identities, current body count, fingerprint, six shapes, four AI/child items, complete bindings,
  source set, image placements and media slots.
- Inject malicious title/author/list text; assert escaping and that emphasis cannot create arbitrary markup.
- Assert one `h1`, eight exact markers, three single-use placeholders and absence of v2 `READING MAP`/`FIELD NOTE`
  plus forbidden hardcoded date/scene labels.
- Block sockets, export twice, verify byte-identical images and ZIP, full manifest file integrity, per-capability zero
  counters, pending/local-only/non-copy-ready/unpublished truth, no overwrite and failed-temp cleanup.
- Browser-check 430 px and 320 px for three loaded images, one `h1`, eight markers, zero external requests and no
  horizontal overflow. Recheck the frozen v1/v2 manifest/assets/ZIP hashes after export.

### 7. Wrong vs Correct

Wrong:

```python
# Renderer silently adds editorial meaning that is absent from the Article Package.
parts.append("<p>AI 应负责分析，孩子只需确认答案。</p>")
```

Correct:

```python
boundary_items = validated_article.sections[3].blocks[2]
render_ai_items(boundary_items.items[:2])
render_child_owned_items(boundary_items.items[2:])
```

## Scenario: Approved-catalog five-image v4

### 1. Scope / Trigger

- Use this additive operator-only path when the frozen v3 editorial hierarchy needs two more company-IP cutaways
  bound to exact text blocks without another model, embedding or image-generation call.
- Keep v1--v3 modules and outputs immutable. V4 reuses v2 source validation, builds from the validated v3 Article
  Package and reads new bytes only through the approved local catalog publication adapter.
- This path is a local review export, not a worker stage, API or publisher. It never reads credentials or constructs
  HTTP, model, WeChat, WeCom or publish clients.

### 2. Signatures

```bash
cd backend
python -m app.official_account_news_editorial_asset_rich_demo \
  --source-dir ../output/official-account-news-ip-20260824-v1 \
  --catalog-manifest ../private/brand-materials/visual-assets.manifest.json \
  --output-dir ../output/official-account-news-ip-editorial-20260825-v4
```

```python
async def load_approved_catalog_publications(
    manifest_path: Path,
    *,
    provider: _CatalogProvider | None = None,
) -> ApprovedCatalogSelection: ...

def build_asset_rich_article(bundle: EditorialSourceBundle) -> ArticlePackage: ...
def render_asset_rich_html(article: ArticlePackage) -> str: ...
def export_asset_rich_bundle(
    source_dir: Path,
    catalog_manifest: Path,
    output_dir: Path,
) -> Path: ...
```

### 3. Contracts

- Exact identities are `official-account-news-editorial-schema-v4-approved-catalog-five-image`,
  `wechat-news-editorial-renderer-v4-approved-catalog-five-image`,
  `wechat-news-editorial-style-v4-navy-cobalt-orange-cutaways` and
  `wechat-news-editorial-template-v4-five-image-mobile`.
- The Article Package keeps six v3 sections and 1,800--2,600 body characters. Image placement in reading order is
  `(0, body-0)`, `(1, body-3)`, `(2, body-1)`, `(3, body-4)`, `(4, body-2)`; media slots are `body-0..4` plus
  `cover-0`. Image blocks carry no fact/brand claim references.
- Catalog input must be the complete 41-item approved set. Exact new public refs are `1bb84f2abb140b8f` for the
  parent-question cutaway and `bab27fe77a8edff4` for the AI/child-boundary cutaway. The three historical reference
  refs are forbidden for the new pair.
- Revalidate candidate identity, read publication bytes and run a final complete-catalog-current fence. The selected
  publication profiles are metadata-free JPEG `614x614` with SHA-256
  `042366d47e654a49f3bac1f710d55becec739c27ed63d8026a6ae3fdca96ea9d` and JPEG `1536x1536` with SHA-256
  `266f21c5f058ef4e321fd9c1ee0e2770d86633fccd039f9df51a87e310f7db47`.
- The two square images use escaped, contained `catalog-cutaway` modules on intentional editorial fields. V3's one
  `h1`, eight single-use module markers, escaped dynamic text, pinned HTTPS sources and three original placeholders
  remain valid; body placeholders `0..4` each occur once.
- Output provenance may include only the bounded public ref, catalog version, source-master/publication checksums,
  publication profile, semantic tags, reader copy and section/slot binding. Raw catalog ID, private path, filename,
  master bytes, vectors and prompts are forbidden.
- Export contains five distinct JPEGs. The first three match the source bytes exactly; the last two match catalog
  publication bytes exactly. Atomic no-clobber, deterministic ZIP, pending/local-only/non-copy-ready/unpublished
  truth and per-capability zero current-call ledgers remain mandatory. No environment key is required or read.

### 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| V2 source validation or v3 Article Package projection fails | Stop before catalog/output work |
| Catalog count is not 41 or public/source/publication identities are not unique | Reject before selection |
| Pinned ref, catalog version, label, semantic tags or historical-ref exclusion drifts | Reject before byte read |
| Revalidated candidate differs from the loaded public identity | Reject before publication byte read |
| JPEG checksum, byte size, metadata or exact square dimensions drift | Reject publication |
| Complete catalog changes after selected byte reads | Reject the entire selection |
| Article shape, five placements, six slots, alt text or one-placeholder contract drifts | Reject build/render |
| Five output checksums are incomplete or duplicated | Reject before temporary export |
| Destination exists/symlinks or a write fails | Preserve destination or remove temporary tree |

### 5. Good / Base / Bad Cases

- Good: the validated source and current 41-item catalog produce a 2,182-character package with five local images,
  two block-bound cutaways, exact safe provenance and zero current external calls.
- Base: repeated build/render/export to separate destinations is deterministic and provider-free; ZIP bytes match.
- Bad: reading a convenient arbitrary PNG, copying a private catalog filename to output, substituting a selected
  ref after catalog drift or cropping a square IP silhouette fails the contract even if the preview still loads.

### 6. Tests Required

- Assert exact v4 identities, six section shapes, 2,182 body characters, five reading-order image placements, six
  slots, claim-free image blocks and equality of the projected v3 Article Package.
- Block sockets; load the real approved catalog and assert the exact two public refs, checksums and square dimensions.
- Fake a revalidation drift, stale final catalog and duplicate identity; assert fail-closed ordering and zero later
  reads where applicable.
- Render malicious title/author text; assert escaping, one `h1`, five single-use placeholders, two cutaways and all
  inherited v3 markers.
- Export twice to separate parents; assert the first three source bytes and last two catalog bytes exactly, identical
  ZIPs, manifest integrity, safe catalog keys, zero call ledgers, no overwrite and failed-temp cleanup.
- Browser-check 430 px and 320 px for five loaded local images, two cutaways, one `h1`, zero external requests and no
  horizontal overflow. Recheck complete v1--v3 tree hashes after the real export.

### 7. Wrong vs Correct

Wrong:

```python
# Bypasses manifest approval and leaks a private source name into the review bundle.
body = (catalog_root / "some-ip.png").read_bytes()
visual_row = {"filename": "some-ip.png", "body": body}
```

Correct:

```python
selection = await load_approved_catalog_publications(explicit_manifest_path)
article = build_asset_rich_article(validated_source_bundle)
export_asset_rich_bundle(source_dir, explicit_manifest_path, fresh_output_dir)
```

## Scenario: Live semantic-reference generated v5

### 1. Scope / Trigger

- Use this additive operator-only path when the frozen five-image v4 article needs original 3:2 generated scenes
  for its two catalog cutaways, selected from the approved company-IP library by the existing live Qwen3-VL index.
- Keep v1--v4 modules, directories and archives immutable. This path is local review output only: it has no HTTP
  route, worker schedule, WeChat, WeCom, send or publish dependency.

### 2. Signatures

```bash
PYTHONPATH=backend conda run --no-capture-output --name edu-ai \
  python -m app.official_account_news_editorial_semantic_generated_demo \
  --source-dir output/official-account-news-ip-20260824-v1 \
  --catalog-manifest private/brand-materials/visual-assets.manifest.json \
  --output-dir output/official-account-news-ip-editorial-semantic-generated-20260825-v5
```

```python
async def select_semantic_references(...) -> SemanticSelection: ...
async def export_semantic_generated_bundle(...) -> bool: ...
async def run_live_semantic_generated_bundle(...) -> bool: ...
```

### 3. Contracts

- Load the exact 41-item approved catalog and reject any identity other than
  `alibaba-model-studio / qwen3-vl-embedding / 2048 / brand-visual-embedding-input-v2` before catalog loading,
  complete-index proof or client construction. Prove exact current index coverage before two sequential paid text
  queries.
- Query body-3 from the complete three-paragraph parent-question group and body-4 from the complete structured
  AI/child responsibility list. Persist only source/query fingerprints. Discard the whole pair on any identity,
  result-completeness or catalog fence failure.
- Globally select two distinct eligible approved references and exclude all three public refs inherited by the v1
  scenes. Revalidate each reference and read publication bytes only through the catalog adapter.
- Copy live settings to `image_provider_mode=toapis` and `image_max_attempts=1`; never mutate ordinary settings or
  instantiate Comfly. Write one exclusive safe intent before each request. There is no hidden retry, third call or
  catalog-byte substitution.
- Normalize each successful provider raster to a metadata-free 1536x1024 JPEG. Final HTML contains five local 3:2
  scenes with block-specific alt text. Safe projections omit raw source text, query text, vectors, prompts, provider
  bodies, private paths, raw catalog IDs and credentials.
- Install the final destination only for a complete ready result. A known failure or ambiguous timeout atomically
  installs a suffixed `.failed-diagnostics` or `.result-unknown-diagnostics` sibling containing safe intents and
  terminal metadata, leaving the ready destination absent.
- A ready run records exactly two embedding calls and two one-attempt ToApis successes, zero current Comfly/source/
  article/WeChat/WeCom/publish calls, manual article review pending, local-only, copy-ready false and unpublished.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Catalog is not exact 41/current/unique or Qwen identity is old/mixed | Reject before embedding client construction |
| Complete index proof is false | Reject with zero embedding and image calls |
| Either embedding/ranking/catalog fence fails | Discard both selections; zero image calls |
| Selected pair repeats a public/publication identity or a historical v1 ref | Reject before reference byte reads |
| Intent already exists | Exclusive-write failure; do not issue the corresponding paid request |
| ToApis times out after intent | One attempted call, `result_unknown` diagnostics, no retry and no ready directory |
| Provider rejects or publication JPEG validation fails | Typed `failed` diagnostics; do not start a later image call |
| Five output checksums are incomplete/duplicated or HTML/manifest/ZIP drifts | Remove temporary ready tree; never install output |

### 5. Good / Base / Bad Cases

- Good: complete active index, two bounded queries and two one-attempt ToApis calls create a ready five-scene local
  bundle while preserving the first three image bytes and all historical trees.
- Base: socket-blocked fakes prove the complete workflow, terminal diagnostics and deterministic export without
  constructing any real provider or social client.
- Bad: rank a partial index, persist raw queries/vectors, reuse a historical reference, retry a timeout, generate
  before an intent, overwrite v4, or label a local bundle published.

### 6. Tests Required

- Assert active identity and complete-index proof precede embedding context entry; exactly two complete score maps
  bind the exact source groups, exclude three historical refs and produce two distinct assignments.
- Assert safe projection keys and body-3/body-4 Article/HTML/visual-map alt equality; no query, prompt, vector, path,
  credential, provider body or raw catalog ID may escape.
- Mock one-attempt ToApis success, timeout, provider failure and invalid final publication; require exclusive intents,
  no second call after the first terminal failure, ready-only final output and deterministic diagnostic siblings.
- Block sockets for default tests; run Ruff, format, PyCompile, strict mypy, v2--v5 regression, manifest/ZIP checks
  and browser acceptance at 430 px and 320 px with five loaded images, no overflow and zero external requests.

### 7. Wrong vs Correct

Wrong:

```python
# Queries an unproved partial index, then retries a paid timeout and overwrites the v4 destination.
scores = await embeddings.embed_visual(query)
for _attempt in range(3):
    image = await toapis.generate(request)
output_dir = v4_output_dir
```

Correct:

```python
assert await repository.prove_complete_catalog(catalog_assets=current_41, identity=active_v2)
selection = await select_semantic_references(forbidden_public_refs=inherited_v1_refs, ...)
write_exclusive_safe_intent(selection.references[0])
image = await one_attempt_toapis.generate(build_single_reference_request(selection.references[0]))
publish_ready_only_to_fresh_v5_directory(image)
```

## Scenario: Official-source contextual news photos v6

### 1. Scope / Trigger

- Use the additive v6 command when the frozen v5 local article should retain all five company-IP scenes and also
  show two pinned official news photographs beside the relevant policy and AI sections.
- Keep the Article Package at its frozen five body-media slots. Context photos are an adjacent typed editorial
  projection, never brand assets or fact evidence, and the output stays local-review-only and unpublished.
- The ordinary network mode is an explicit operator action. Tests and default fixture paths inject a fake fetcher
  and make zero requests. A validated-local-cache mode may finish an export after a known server rejection without
  retrying; its ledger must report cache reads and prior failed attempts rather than claiming successful GETs.

### 2. Signatures

```bash
PYTHONPATH=backend conda run --no-capture-output --name edu-ai \
  python -m app.official_account_news_editorial_news_context_demo \
  --source-dir output/official-account-news-ip-editorial-semantic-generated-20260825-v5 \
  --output-dir output/official-account-news-ip-editorial-news-context-20260825-v6
```

```python
load_v5_bundle(source_dir: Path) -> ValidatedV5Bundle
fetch_news_context_photos(fetcher: OfficialPhotoFetcher) -> tuple[ValidatedNewsPhoto, ...]
export_news_context_bundle(
    source_dir: Path,
    output_dir: Path,
    *,
    fetcher: OfficialPhotoFetcher,
    acquisition: PhotoAcquisitionLedger = NETWORK_ACQUISITION,
) -> Path
run_cached_news_context_bundle(...) -> Path
```

### 3. Contracts

- The source is the exact complete v5 manifest family, including its 18 declared files, canonical five body slots,
  five visual rows, semantic-ready body-3/body-4 assignments and all zero social counters. Every source file path,
  byte size and SHA-256 is checked before the first photo operation.
- The photo set is exactly two distinct `www.moe.gov.cn` HTTPS image URLs and two exact source pages. Validate the
  whole set before any fetch so a bad second URL cannot allow the first request. Network mode uses no redirect,
  one attempt per photo, a bounded browser-compatible `Accept`/`Referer`/`User-Agent`, and no search fallback.
- Response validation requires HTTP 200, exact final URL, exact `image/jpeg`, at most 15 MiB, complete non-animated
  JPEG decode, pinned dimensions and pinned SHA-256. Write original bytes unchanged; do not crop, recompress or
  remove the visible Ministry watermark.
- Render `news-00.jpg` after policy context and `news-01.jpg` beside the AI boundary. Use relative local paths,
  natural `height:auto`, escaped captions/credits and allowlisted source links. Every projection records
  `context_only_not_evidence`, `publish_permission_unverified` and the public-release warning.
- Run/manifest acquisition truth distinguishes successful GETs, validated cache reads and known failed attempts.
  Current article, embedding, image provider, ToApis, Comfly, WeChat, WeCom and publish counts remain zero;
  inherited v5 paid calls are historical fields only.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| V5 manifest/file/article/media/projection identity drifts | Reject before photo fetch/cache read |
| Either image/source URL, public ref, filename or rights status drifts | Reject whole photo set with zero operations |
| Official server returns non-200, redirect, wrong MIME or oversized content | Stop immediately; no retry and no ready directory |
| JPEG decode, dimensions, checksum or distinctness fails | Remove temporary work; never install a plausible bundle |
| Existing/symlink destination | Fail before source or photo work; preserve existing bytes |
| Previously acquired exact bytes are available after a known rejection | Use explicit cache mode; report 0 successful GET, 2 cache reads and the known failed-attempt count |
| Acquisition ledger claims a mixed or incomplete two-photo operation | Reject before export |

### 5. Good / Base / Bad Cases

- Good: a complete v5 bundle plus two pinned official JPEGs produces seven loaded local images, exact caption/credit
  provenance, a deterministic ZIP and no model or social call.
- Base: injected bytes exercise the full exporter with sockets blocked; both identical-basename exports have
  identical archives.
- Bad: load the first URL before validating the second, paste remote `<img>` URLs into HTML, label a related photo
  as original article evidence, remove the Ministry watermark or report cache reads as successful network GETs.

### 6. Tests Required

- Assert literal official URL/page/checksum/dimension identities and whole-set zero-operation rejection.
- Tamper every v5 manifest/article/media/projection boundary and assert rejection precedes the fake fetcher.
- Inject success, checksum, dimension, MIME and final-URL responses; require atomic no-clobber behavior and no temp
  directory after failure.
- Assert five source JPEGs are byte-identical, two official JPEGs preserve source bytes, Article Package JSON is
  unchanged, HTML has two contextual modules/one rights banner/one `h1`, and provenance has seven visual rows.
- Block sockets and assert current provider/social counters are zero. Browser-check 430 px and 320 px for seven
  loaded images, no external requests and no horizontal overflow.

### 7. Wrong vs Correct

Wrong:

```python
# The first GET escapes before the second configured URL is validated; cached export then pretends it was network.
for photo in configured_photos:
    body = await client.get(photo.image_url)
run["official_photo_get_calls"] = 2
```

Correct:

```python
_validate_news_context_photo_set()  # complete exact set, before any operation
photos = await fetch_news_context_photos(fetcher)
await export_news_context_bundle(
    source_dir,
    fresh_output,
    fetcher=validated_cache,
    acquisition=PhotoAcquisitionLedger(
        mode="validated_local_cache",
        successful_get_calls=0,
        cache_reads=2,
        failed_get_attempts_before_export=1,
    ),
)
```

## Scenario: Selected-news source-image durable runtime v7

### 1. Scope / Trigger

- Use this additive runtime path when ordinary acquisition accepts a news detail page and later official-account
  generation should be able to show that selected news item's original editorial images.
- Image discovery and GETs belong only to the acquisition worker. Material packaging, Article v9 generation,
  recovery, rendering, API reads and local export consume immutable stored snapshots and must never refetch a source
  page or image.
- Source images are contextual editorial media, not fact evidence, brand knowledge or company-IP assets. Existing
  five-slot company-IP/generated body media and cover remain unchanged; v9 adds zero to two separate context figures.

### 2. Signatures

```python
SourceImageFetcher.fetch(
    reference: SourceImageReference,
    profile: SourceProfile,
) -> ValidatedSourceImage

AcquisitionRepository.reserve_source_image(...) -> SourceArticleImageIntent
AcquisitionRepository.complete_source_image(...) -> None
AcquisitionRepository.fail_source_image(...) -> None

OfficialAccountRunRepository.load_news_context_candidates(
    claimed: ClaimedOfficialAccountRun,
) -> tuple[OfficialAccountSourceMedia, ...]
```

Database and wire signatures:

- Migration head: `20260825_0036`, after `20260824_0035`.
- New tables: `source_article_images`, `material_package_source_images`,
  `official_account_article_context_images`.
- `official_account_local_media` adds the exclusive `source_article_image_id` source and `context` role, ordinals
  `0..1`.
- `GET /api/v1/official-account-local/article-runs/{run_id}` adds `context_images` and
  `context_media_status`; media rows may expose safe provenance fields but never `source_article_image_id`, bucket,
  object key or final image URL.

### 3. Contracts

- Connector extraction is deterministic and I/O-free: prefer `og:image`, then figures inside the selected article
  root; normalize relative URLs, deduplicate, retain at most five discoveries and bound alt/caption/credit.
- A text-only fallback such as Trafilatura does not establish a safe DOM image root. If every versioned selector
  misses, accept the text with zero content-root images rather than scanning the full document. When live markup
  changes, add the narrow source-specific root ahead of historical selectors and bump that source's connector and
  parser versions; preserve prior selectors for historical fixtures and source versions.
- The initial fetch policy accepts only query-free HTTPS URLs on the exact article host and configured source path.
  Validate public DNS before every hop, reject cross-host redirects, preserve accepted JPEG/PNG/WebP bytes and limit
  each image to 15 MiB, one frame, `320x180..8192x8192` and at most 40 million pixels. Fetch at most ordinals 0 and 1.
- Reserve the discovery intent before GET. A typed `AppError` may degrade only that image to failed/rejected without
  dropping the accepted news item. Unknown storage, database or programming errors must be logged and re-raised so
  the parent acquisition attempt retries while the discovery intent remains replayable.
- Bind every ready image to the exact detail snapshot. A material package may link only ready images reachable from
  its frozen evidence `snapshot_id` list. Article context rows use composite package/source and article/run lineage;
  unrelated images cannot enter through candidate, publisher or event similarity.
- Article v9 uses `official-account-news-context-selection-v1`, renderer/style/template v8 and local adapter v6.
  Families v1--v8 require `context_media_plan_version=None`; mixed tuples fail closed. Zero images is
  `not_present`, one is `partial`, two is `ready`.
- Local media resolution checks the source-image row, Article selection row, immutable snapshot kind/MIME/size/SHA
  and content-addressed object key before returning bytes. It performs no HTTP operation.
- Current rights are always `publish_permission_unverified` and `context_only_not_evidence=true`. Local review may
  display the original pixels with escaped caption/credit/source link; copy-ready export containing such an image
  raises an error. No environment key is added.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Cross-host, query URL, private DNS, unsafe redirect or disallowed path | Reject before the unsafe GET/hop |
| Wrong MIME, decode failure, animation, tiny/oversized raster or decompression bomb | Typed per-image failure; keep the news item |
| HTTP/network failure represented by a typed acquisition error | Persist safe failed/rejected image state; no hidden retry inside the image fetcher |
| Text succeeds only through a fallback without a selected DOM root | Keep the article and extract zero root images; never scan page chrome |
| A live source adopts a new stable article-root selector | Add a source-specific selector, bump connector/parser versions and activate a new immutable source version |
| Unknown snapshot-store/repository/programming exception | Log safe run/job/source/ordinal metadata, re-raise and leave intent replayable |
| Candidate does not own the exact detail snapshot/source version | Reject repository reservation |
| Material package cannot reach the image through frozen evidence snapshots | Omit/reject the image; never select by loose event similarity |
| Stored MIME/size/SHA, package/source or article/run lineage changes | Fail local media resolution/recovery before bytes leave storage |
| V1--v8 carries a context identity, or v9 lacks its exact identity | Reject the version bundle |
| Copy-ready output contains unverified-rights context media | Fail closed; local review remains available |

### 5. Good / Base / Bad Cases

- Good: acquisition accepts a detail page, stores two valid same-host images, the selected material package freezes
  both links, and Article v9 renders them near distinct semantic sections while retaining five company-IP images.
- Base: no valid image is available; the news remains accepted, package/article status is `not_present`, and the
  local draft completes with existing company-IP media and zero source GETs after acquisition.
- Bad: the renderer follows a remote `<img>` URL, a retry repeats a GET for a failed intent, a package selects an
  image from another detail snapshot, or the API leaks storage/internal IDs.

### 6. Tests Required

- Connector/fetcher contract tests inject HTML and raster bytes and assert extraction order/bounds, exact byte
  preservation, private DNS/cross-host redirect rejection, MIME mismatch, size/frame/dimension/decompression errors
  and zero real sockets.
- Source-specific selector regressions must include representative current composite classes plus plausible
  header/navigation/recommendation images, assert the exact selected-root metadata and image set, preserve the
  historical fixture selector, and prove the version bump changes `source_version_id` without changing `source_id`.
- Executor/repository tests assert reserve-before-GET, maximum two fetches, typed optional degradation, unknown-error
  rethrow, retry idempotency, candidate/detail ownership and ready/failed database result shapes.
- PostgreSQL migration tests assert unique head `20260825_0036`, model/metadata parity, composite lineage FKs and
  downgrade refusal when new artifacts exist.
- Domain/service/renderer/media tests assert v1--v8 compatibility, v9 zero/one/two deterministic placement, five
  original body slots plus context placeholders, escaped natural-aspect figures, stored-snapshot-only reads and
  unverified-rights copy-ready rejection.
- API/OpenAPI/frontend tests assert safe context fields, partial/unavailable UI, “新闻原图” versus “公司 IP 图”, no
  `source_article_image_id`/private path/final image URL, and generated-contract drift checks.

### 7. Wrong vs Correct

Wrong:

```python
# Rendering refetches a loosely related remote image and hides an unexpected storage failure.
image = await http_client.get(article.image_url)
try:
    await snapshot_store.put(image.content)
except Exception:
    await repository.fail_source_image(intent_id, "source_image_internal_failure")

# Text fallback succeeded, so scan every image in the document.
content_root = soup
```

Correct:

```python
intent = await repository.reserve_source_image(exact_detail_snapshot, reference)
try:
    validated = await source_image_fetcher.fetch(reference, source_profile)
    snapshot = await snapshot_store.put_immutable(validated.response.body, validated.response.media_type)
    await repository.complete_source_image(intent.id, snapshot.id, validated)
except AppError as error:
    await repository.fail_source_image(intent.id, error.code)
except Exception:
    logger.exception("source_image_acquisition_internal_failure")
    raise  # parent retry; official-account stages read only the immutable snapshot

# No versioned root matched: keep text, but safely expose no root image candidates.
content_root = selected_root  # None until a source-versioned selector is added and tested
```

## Scenario: Durable V10 five-visual local run and polished review export

### 1. Scope / Trigger

- Use the exact V10 family when a governed selected-news material package must produce a local-only official-account
  draft with five generated company-IP scenes plus separately governed source-news context media.
- Use the polished review export only after the durable run is `ready`. It may derive local presentation bytes and
  accessibility copy, but it must not mutate the stored Article Package, canonical render, provider artifacts or
  database lineage.
- This family never publishes. WeChat, WeCom, social-send and publish clients are outside the worker and export
  dependency graph. Live model, embedding and image calls are allowed only in the durable worker; re-export reads
  persisted PostgreSQL/MinIO state and makes zero provider or source requests.

### 2. Signatures

Current version tuple:

```text
generator_prompt_version = official-account-generator-v7-five-to-seven-sections
article_schema_version = official-account-article-schema-v5-news-context
media_plan_version = official-account-media-plan-v4-five-blocks
context_media_plan_version = official-account-news-context-selection-v1
renderer/style/template = wechat-*-v8-news-context
local_adapter_version = official-account-local-adapter-v7-disjoint-attempt-ordinals
```

Export command and key domain signatures:

```bash
cd backend
python -m app.official_account_local_cli export \
  --run-id <ready-run-uuid> \
  --output-dir ../output/<fresh-directory> \
  --allow-live-local-export
```

```python
plan_body_media_slots(
    *, section_count: int, candidate_count: int,
    media_plan_version: str = OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
) -> tuple[int, ...]

validate_article_package(...) -> tuple[ArticleValidationIssue, ...]
export_review_bundle(bundle: ReviewBundleInput, output_dir: Path) -> ReviewBundleResult
```

Database attempt namespace for adapter V7:

```text
body ordinal    = attempt_number * 100 + body_ordinal       # 0..4
context ordinal = attempt_number * 100 + 20 + context_ordinal  # 0..1
failure ordinal = attempt_number * 100 + 90
```

### 3. Contracts

- `article_version_bundle_kind()` recognizes V10 only for the exact tuple above. V9 remains frozen on generator
  V5/V6, media plan V3 and adapter V6; current code must not silently route those persisted identities into V10.
- Generator V7 emits 5--7 sections and retains the V6 length contract. Media plan V4 selects
  `min(candidate_count, 5, section_count)` distinct section indexes; the current complete catalog and V7 therefore
  yield exactly five body slots. Each slot uses one distinct approved company-IP reference and one one-attempt
  generated 1536x1024 publication JPEG.
- Source-news images remain `publish_permission_unverified` and `context_only_not_evidence=true`. They use the
  Article v5 context snapshot and local `context` media role; they never replace a body slot or support a fact claim.
- Provider intent and result records are durable and run/article/render scoped. A generating intent recovered
  without a known result becomes `result_unknown`; the worker never sends a second paid request under that identity.
- Adapter V7 uses the disjoint ordinal namespaces above under
  `uq_official_account_article_attempts_stage_ordinal`. Body ordinal zero, context ordinal zero and a terminal
  staging failure therefore cannot collide.
- Polished local review versions are `official-account-review-bundle-v6-news-context-export-polish` and
  `official-account-live-local-review-bundle-v3-news-context-export-polish`. The presentation identity records
  `official-account-news-context-export-polish-v1`,
  `official-account-cover-export-derivative-v1-top-biased` and
  `official-account-context-display-fallback-v1`.
- A non-wide cover is safely decoded and deterministically cropped to 2.35:1. Portrait/square sources use a
  one-third top-biased vertical crop; overly wide sources use a centered horizontal crop. Already-wide inputs keep
  their exact bytes. Manifest media metadata uses the derived byte size, SHA-256 and dimensions while retaining
  the source checksum and crop box as provenance.
- Generic context display text such as `新闻原图` is replaced only in the export presentation with bounded escaped
  article-title and assigned-section copy plus `仅作上下文说明，不作为事实证据`. Rich source alt/caption text is
  preserved byte-for-byte. `article.json` remains the immutable runtime snapshot; HTML, preview, manifest and
  sources expose the effective presentation value and its version/source.
- The bundle contains five body images, zero to two context images, one cover, only normalized relative asset paths,
  no `/api/` or remote image reference, a complete SHA-256 manifest and a deterministic ZIP. It stays
  `simulation=true`, `local_only=true`, `copy_ready=false`, `published=false` and manual-review pending.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Version tuple mixes V9 and V10 identities | Reject before generation/render/export |
| V7 output has fewer than five sections, invalid claims, unsafe markup or hard length drift | Persist validation failure; do not audit, render or generate images |
| Complete catalog cannot supply five distinct current references | Fail before image provider work |
| Embedding or generated-image intent/result is incomplete, timed out or ambiguous | Stop with typed failure or `result_unknown`; no hidden retry |
| Body/context/failure attempt ordinals overlap | Reject in tests; adapter V7 must use the disjoint namespace |
| Context lineage, MIME, size, SHA, source page or rights status changes | Fail before stored bytes leave the adapter |
| Copy-ready is requested with unverified context media | Reject; local review remains available |
| Cover decode fails, exceeds raster/byte bounds or derivative MIME/ratio drifts | Reject the export; do not install a plausible bundle |
| Generic context fallback contains unsafe/unbounded input | Normalize, bound and escape it before HTML; never emit raw markup |
| Existing/symlink output or incomplete manifest/archive | Preserve the destination or remove the temporary tree |

### 5. Good / Base / Bad Cases

- Good: a governed ready package produces a 5--7-section accepted Article, five distinct 3:2 company-IP scenes,
  one stored CAS context image, disjoint staging attempts and a polished local bundle whose cover passes 2.35:1.
- Base: re-exporting the same ready run reuses persisted bytes, returns the same ZIP hash and performs zero article,
  audit, embedding, image, source, WeChat, WeCom or publish calls.
- Bad: change media-plan V3 in place to return five slots, reuse four run-scoped failed-run images in a new run,
  assign body/context ordinal zero to the same attempt key, treat the CAS image as evidence, or rewrite
  `article.json` merely to improve display copy.

### 6. Tests Required

- Assert exact V9 and V10 bundle recognition and frozen V5/V6 prompt hashes. For media plan V4, assert five distinct
  placements for 5, 6 and 7 sections and retain V3 historical expectations.
- Provider/fake/worker tests must assert V7 schema-first output, deterministic validation before audit, five semantic
  queries, five distinct references and one generated-image attempt per slot.
- PostgreSQL integration must persist body ordinal zero and context ordinal zero in one run, assert V7 attempt
  ordinals `100..104`, `120..121` and `190` for attempt one, and prove the unique constraint does not collide.
- Export tests must cover already-wide byte preservation, deterministic square/portrait and overly-wide crops,
  safe raster limits, exact derived checksum/dimensions/provenance and preflight ratio success.
- Assert generic alt/caption replacement across HTML/preview/manifest/sources, rich-source preservation, escaped and
  bounded malicious text, immutable `article.json`, five body plus context image counts, no external references and
  deterministic ZIP reuse.
- Run Ruff, format, mypy, focused unit/contract/integration tests, OpenAPI drift checks and `git diff --check`.
  Browser acceptance at 430 px and 320 px requires every image loaded, one `h1`, no horizontal overflow and zero
  external requests.

### 7. Wrong vs Correct

Wrong:

```python
# Changes a persisted media-plan meaning and reuses one attempt key for two roles.
target_count = min(candidate_count, 5, max(3, section_count - 1))  # edited under V3
attempt_ordinal = attempt_number * 10 + ordinal  # body-0 == context-0
article.news_context_media.items[0].alt_text = generated_caption  # mutates runtime truth
```

Correct:

```python
assert article_version_bundle_kind(article.versions) == "v10"
placements = plan_body_media_slots(
    section_count=len(article.sections),
    candidate_count=len(approved_catalog),
    media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
)
body_attempt = _adapter_v7_staging_attempt_ordinal(
    attempt_number=1, role="body", ordinal=0
)
context_attempt = _adapter_v7_staging_attempt_ordinal(
    attempt_number=1, role="context", ordinal=0
)
assert body_attempt != context_attempt
export_review_bundle(immutable_ready_run_projection, fresh_output_dir)
```

## Editor-handoff V1: approved local WeChat editor projection

### 1. Additive identity and read-only ownership

The editor handoff is a downstream, development-only projection. It does not join the V1--V10
Article renderer tuple and must not change historical review/copy-ready bytes. Its fixed identities
are `wechat-editor-handoff-renderer-v1-gzh-xiaosai`,
`wechat-editor-handoff-style-v1-xiaosai-blue`,
`wechat-editor-handoff-template-v1-moyu-layout`,
`official-account-editor-handoff-bundle-v1`,
`wechat-editor-handoff-preflight-v1`, and
`editor-handoff-context-rights-v1-direct-use-disclosed`.

`backend/app/domain/official_account_editor_handoff.py` owns the pure Article Package renderer and
preflight. The Xiaosai theme tokens are a project-owned static definition with a canonical SHA-256;
runtime code never reads a personal skill directory or accepts caller-supplied HTML, Markdown, CSS,
or template paths. `OfficialAccountEditorHandoffService` only rereads the existing run, Article,
render, draft, immutable review and media snapshots, verifies their lineage and bytes, and builds an
in-memory projection. It writes no row/object, creates no job, and constructs no model, embedding,
image, news, WeChat, or WeCom client.

### 2. Eligibility and preflight

The endpoint is available only when `APP_ENV=development`, `OFFICIAL_ACCOUNT_LOCAL_ENABLED=true`,
and `OFFICIAL_ACCOUNT_EDITOR_HANDOFF_ENABLED=true`. Artifact resources require a ready run, a
supported and fingerprint-valid Article Package, passed deterministic validation, accepted model
audit, a fixed render, a ready simulated draft whose resolved fingerprint matches its immutable
render lineage, and an approved manual review whose request fingerprint matches its immutable
review input. Pending, rejected, failed, `result_unknown`, incomplete, or tampered state returns a
stable blocking code and no plausible body/ZIP.

The render gate must also prove that `render.article_version_id` equals the selected Article
version and recompute both canonical HTML and `render_fingerprint` with that Article's frozen
historical renderer identity. Presence of a render row alone is never sufficient approval lineage.

The pure body is one `<section>` fragment using controlled tags, attributes, inline CSS, HTTPS
source links, `span leaf`, and package-relative assets. It contains one to five distinct body images,
all selected context images at their Article section anchors, and no cover. Across body, context and
cover, paths and content hashes are unique; the single cover is exactly or deterministically cropped
to the 2.35:1 tolerance. Placeholders, remote/private/API image references, dangerous markup and a
preview/body mismatch are blocking.
The HTML preflight parses exactly one balanced root, rejects duplicate attributes or duplicate
image references, and permits only the renderer's enumerated inline CSS properties in addition to
the unsafe-value blacklist.

`publish_permission_unverified` context images are intentionally retained only in this new handoff.
They produce the nonblocking `context_image_rights_unverified_direct_use` warning and retain source,
credit and `context_only_not_evidence=true` in HTML/API/rights/manifest. This never means licensed,
cleared or evidence, and historical copy-ready export continues to reject the same rights state.
Runtime mobile status stays honestly `not_run`; a loopback-only Playwright fixture records 320/430
browser evidence separately.

### 3. HTTP and bundle contract

The existing local router adds typed metadata, body, preview, asset and ZIP GET resources. Metadata
returns blocked state as a displayable 200 projection; artifact resources fail closed. Responses use
`private, no-store`, `nosniff` and `no-referrer`; body/preview use restrictive CSP and asset/ZIP
downloads use generated attachment names. OpenAPI must contain no publish/send/account/AppID/
AppSecret/token fields.

The deterministic ZIP contains body/preview, Markdown and safe Article JSON, sources, rights,
review, preflight, honest mobile status, canonical theme, README, manifest and generated relative
assets. Member order, timestamp, mode and compression are fixed; every path is traversal-safe and
every member is reread byte-for-byte after construction. The manifest binds run/request/content/
render/draft/review/theme identities, file hashes and media metadata. Rebuilding the same immutable
input must return the same handoff fingerprint, body bytes and ZIP SHA-256.

### 4. Validation and error matrix

| Condition | Required result |
|---|---|
| Environment or either handoff flag is disabled | Return a stable development-only conflict; do not build artifacts |
| Run/draft/review is incomplete, rejected, failed or result-unknown | Metadata reports a typed blocking code; body/preview/assets/ZIP fail closed |
| Article/render/draft/review lineage or fingerprint differs | Reject as integrity failure before returning copyable bytes |
| HTML has multiple roots, duplicate attributes/images, unknown CSS, remote images or private paths | Preflight error; `copy_ready=false` |
| Context rights are `publish_permission_unverified` | Retain the image and source under this V1 policy; return a nonblocking warning |
| Asset, manifest member or ZIP path/hash/size differs | Reject the artifact; never return a plausible partial package |

### 5. Good, base and bad cases

- Good: a ready simulated run with an immutable matching approval returns one stable metadata
  projection and byte-identical body, preview, assets and ZIP across repeated reads.
- Base: pending approval remains inspectable through typed metadata and existing local media, but
  no handoff artifact resource claims copy readiness.
- Bad: accepting a render merely because a row exists, allowing an unlisted CSS property, or
  rewriting an unverified rights status to licensed bypasses the handoff integrity boundary.

### 6. Tests required

- Unit-test renderer escaping, one-root/span-leaf/CSS/image allowlists, exact body/context placement,
  cover ratio, rights warnings, deterministic fingerprints and ZIP verification.
- API-test both development gates, every run/review state, Article/render/draft/review tampering,
  security headers, CSP origins, safe asset names and the absence of publish/credential contracts.
- Preserve historical Article/export/media goldens. Run generated OpenAPI drift checks and assert
  default tests construct no provider, news, WeChat or WeCom client.
- Run the project-independent gzh validator and loopback Playwright at 320/430 px with every
  non-loopback request blocked.

### 7. Wrong versus correct

Wrong:

```python
if render is not None and review.decision == "approved":
    return build_handoff(render.resolved_html)
```

Correct:

```python
artifact = await service.build(run_id)
# The service revalidates Article/render/draft/review lineage and media bytes, then renders from the
# structured Article Package under the additive handoff identity.
return artifact
```

## Editor-handoff V2: automatic local release and block-bound news media

The injection-safe focused source of truth is
[`official-account-editor-handoff-v2.md`](./official-account-editor-handoff-v2.md); this mirror keeps
the relationship to frozen V1 repackages explicit.

### 1. Scope / trigger

- Use this sibling path only for a development-only editor handoff when both the V2 flag and
  `quality_auto` policy are explicit. `manual_only` continues to dispatch the frozen V1 path.
- V2 is a read-only projection of persisted run, Article, render, draft, audit and media state. It
  has no worker, migration, provider, acquisition, WeChat, WeCom, send or publish capability.
- V2 owns new identities and a fresh output directory. V1 constants, renderer output, golden files
  and ZIP bytes remain immutable.

### 2. Signatures

```python
service = OfficialAccountEditorHandoffV2Service(
    session_factory=session_factory,
    resolver=resolver,
    release_policy="quality_auto",
)
inspection = await service.inspect(run_id)

artifact = build_editor_handoff_v2_artifact(...)
finalized = bind_editor_handoff_v2_mobile_validation(artifact, exact_report)
target = write_editor_handoff_v2_artifact(finalized, fresh_output_root)
```

```bash
PYTHONPATH=backend conda run --no-capture-output --name edu-ai \
  python -m app.official_account_editor_handoff_v2_demo \
  --output-dir output/official-account-editor-handoff-v2-staging \
  --browser-report /tmp/editor-handoff-v2-mobile.json
```

### 3. Contracts

V2 is a sibling of the frozen V1 handoff. It owns
`wechat-editor-handoff-renderer-v2-gzh-xiaosai-semantic`,
`wechat-editor-handoff-style-v2-xiaosai-adaptive`,
`wechat-editor-handoff-template-v2-block-interleaved-mobile`,
`official-account-editor-handoff-bundle-v2`, `wechat-editor-handoff-preflight-v2` and the versioned
release/placement/emphasis/recipe/mobile identities. V1 constants, renderer output and ZIP bytes do
not change.

`manual_only` dispatches the V1 compatibility path. `quality_auto` is available only behind the
development-only V2 flag. It consumes persisted run, Article, render, draft, model-audit, image
quality and generated-visual state; it constructs no provider. A valid approval yields a truthful
manual release, no review may yield a machine release, and an immutable rejection always blocks.
Machine release is a projection in `release.json`, never a fabricated review row.

- Context images retain their Article section, score exact alt/caption terms against visible text
  blocks, and persist an `after` block placement with a bounded reason. Stable collision shifting
  keeps a visible prose block between images. Context media never replaces a body image block.
- Semantic emphasis selects one or two exact 4--15-character source units for ordinary text and at
  most three for long text. It never truncates a long clause to the maximum length, rejects
  function-word fragments and unbalanced quotation marks, and renders escaped slices whose
  concatenation equals the input.
- The deterministic Xiaosai recipe is `news_analysis`, `tutorial_list`, `case_opinion` or
  `analysis`. It changes component rhythm, title/TOC bands and callout variants only; one Xiaosai
  theme, inline allowlisted CSS, `span leaf` and relative local images remain mandatory.

#### Content and artifact identity

`content_fingerprint` binds release inputs, Article identity, recipe, placement, body SHA and media
hashes. `artifact_fingerprint` additionally binds the canonical mobile report. Runtime output uses
`not_run`. A final `passed` artifact can be built only when a loopback browser report matches the
exact content fingerprint, body SHA and ordered media hashes, reports 320/430 checks, zero external
requests and exact preview/copy-root equality. Therefore one artifact fingerprint never names both
not-run and passed bytes.

The deterministic V2 bundle includes `release.json`, `placements.json`, `emphasis.json`,
`recipe.json`, `body-visuals.json`, the canonical mobile report, clean body/preview, safe Article/source/rights
projections, media, manifest and ZIP. It remains `simulation=true`, `local_only=true` and
`published=false`; no WeChat or WeCom capability exists.

Every V2 body slot must resolve to a newly generated, current V3 reference-conditioned output.
Directly placing approved catalog bytes is insufficient. The safe lineage binds the exact Article
block fingerprint, approved public reference, provider-input normalization checksum, truthful
selection method, character labels, plan identity and generated output hash. The offline fixture
validates a frozen exact-field visual map and calls no provider; never relabel its deterministic
fixture-semantic choice as a Qwen3-VL embedding result.

A named final directory must be rebuilt after the last semantic/render/projection change and
hash-match a current-code in-memory rebuild. Context source, credit, rights and block placement must
agree across Markdown, JSON, manifest, generated API and workbench projections.

### 4. Validation and error matrix

| Condition | Required result |
|---|---|
| V2 flag is off, policy is `manual_only`, or environment is not development | Keep V1 dispatch or fail closed; never enter automatic V2 |
| Persisted run/draft, Article/render lineage, deterministic/model/image gate is unknown or failed | Return a stable blocking check before media export |
| A valid human approval exists | Emit `kind=manual` with its immutable fingerprint |
| Any human rejection exists | Block before machine release; automatic quality cannot override it |
| Context media cannot bind a safe visible block or remain separated from images | Fail V2 placement preflight without dropping or replacing media |
| Emphasis bounds rewrite text, overlap, use generic transition fragments or exceed three spans | Fail deterministic emphasis checks/tests |
| Browser report does not bind exact content/body/ordered media hashes, `(320, 430)`, zero external requests and exact copy root | Reject finalization and keep runtime `not_run` truthful |
| Output target already exists, a path is unsafe, or archive verification fails | Preserve the existing target and do not install a partial bundle |

### 5. Good / base / bad cases

- Good: all durable quality gates pass with no manual row, so a machine release creates three IP
  body images plus block-bound news context images, one cover, a passed exact mobile report and a
  deterministic local ZIP.
- Base: runtime/API projection has canonical `mobile_validation=not_run`; repeated construction from
  the same snapshots has identical content/artifact identities and bytes, while V1 remains exact.
- Bad: fabricate an approved review, accept a rejected run, use one browser result for another
  article, silently drop a context image, treat it as evidence/licensed, or call any external/social
  client.

### 6. Tests required

- Cover machine/manual/rejected gate ordering, unknown or failed image quality, generated-visual
  failure, tampered lineage, deterministic replay, archive safety and V1 byte regressions.
- Assert semantic spans are exact and nontruncated, placements carry nonempty semantic matches in
  the news fixture, three IP body images remain, and one or two news images keep source/credit/
  rights/context-only truth.
- Generate OpenAPI/TypeScript from the backend contract. Run the independent gzh validator to zero
  errors/warnings and Playwright at 320/430 with all images loaded, plan-derived order, no overflow
  and zero external requests.
- Hash-match the final directory against a current-code in-memory rebuild and assert Markdown,
  JSON, manifest and API/UI retain the same context source/credit/rights/placement values.

### 7. Wrong vs correct

Wrong:

```python
# A missing review is falsely represented as a human approval.
review = StoredOfficialAccountManualReview(decision="approved", reviewer_label="automation", ...)
```

Correct:

```python
release = EditorHandoffRelease(
    policy="quality_auto",
    kind="machine",
    input_fingerprint=durable_gate_fingerprint,
    gate_codes=passed_gate_codes,
    manual_review_fingerprint=None,
)
```
