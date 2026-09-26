# Local Daily-News Infographic Trial

## 1. Scope / Trigger

This contract applies only to the operator-triggered `news_infographic_local_main` trial. It
reuses frozen, accepted material-package snapshots to test a portrait news poster. It does not
schedule daily work, change the selected topic, create a social draft, or publish anything.

## 2. Signatures

```text
python -m app.news_infographic_local_main prepare --package-id UUID [--package-id UUID ...] --api-base-url http://127.0.0.1:8000 --output-dir FRESH_DIR
python -m app.news_infographic_local_main preflight --input-bundle INPUT_JSON --output-dir FRESH_DIR
python -m app.news_infographic_local_main run --input-bundle INPUT_JSON --output-dir FRESH_DIR --execute
python -m app.news_infographic_local_main run --input-bundle ONE_CASE_INPUT_JSON --reuse-accepted-copy-run PRIOR_LOCAL_RUN --output-dir FRESH_DIR --execute
python -m app.news_infographic_local_main repair-footer --input-bundle ONE_CASE_INPUT_JSON --prior-run EXISTING_LOCAL_RUN --output-dir FRESH_SIBLING_DIR
python -m app.news_infographic_local_main report --run-dir EXISTING_DIR
```

The input has one to three distinct package and event-version identities. `prepare` performs only
loopback detail GETs. `preflight` and `report` make no model calls. `run` is the sole paid entry point.
The reuse option is single-case only and skips new copy-generation/audit calls; it does not skip
poster-prompt preflight, image intent, raster checks or manual acceptance.
`repair-footer` is provider-free: it reads one matching prior generated run and creates a fresh
sibling directory. It never rewrites or relabels the prior provider raster.

## 3. Contracts

- `ValidatedInfographicInput` preserves package, draft, event-version, source publication date,
  external evidence bindings and brand chunk/document/version identities. A frozen accepted package
  is not proof of the current active draft pointer or a fresh RAG retrieval.
- The new generator instance explicitly requests `1152x2048`; the default shared instance remains
  `1024x1024`. After the user's 2026-09-23 authorization, this local trial alone selects
  `gpt-image-2.5-sunburst` rather than an environment override to `gpt-image-2`. Do not change the
  global image model, provider, size or reference set. The local image generator has
  `max_attempts=1`. [Official OpenAI model guidance](https://developers.openai.com/api/docs/guides/image-prompting)
  permits this custom size, but does not prove the separate Comfly relay supports it.
- Build the complete poster prompt, run the **same shared request prompt validator used by the
  adapter** before reserving an image intent, and use its normalized return value as the exact
  prompt in the private snapshot, request fingerprint and image request. A negative instruction
  containing a lexically prohibited term still fails the policy; do not weaken the shared policy.
- Reuse only a prior local run whose `manifest.json` says `copy=accepted` and whose frozen input
  fingerprint/package/source footer match the current case. Require `copy.json` to equal the copy
  in that run's private `01-image-request.json` exactly; reject a missing/tampered snapshot before
  creating a fresh output directory. Mark the new copy `reused_accepted` and
  `copy_provenance=prior_local_accepted_run`, without reserving new copy/audit intents. This is
  provenance reuse, **not** a claim that a fresh semantic audit ran.
- Before each paid call, an exclusive `private/*.intent.json` is fsynced. Before the image POST, a
  `0600` request snapshot freezes exact copy, prompt, reference SHA256 values, geometry, model and
  request fingerprint. A reserved intent is counted conservatively even if the process crashes.
- `quality.json` and `manifest.json` contain only allowlisted states and safe reasons. Never store
  provider bodies, signed image URLs, credentials, private brand excerpts or raw prompt text there.
  A known `ImageOutputValidationError.reason` may be projected as `reason_code`; unknown exceptions
  remain the generic `image_stage_failed`. Do not discard the typed reason into one generic label:
  it prevents diagnosis of a failed first capability trial without another paid request.
- Save the provider's original raster bytes only after full decode, media and exact-dimension checks.
  `preview.html` displays only actual generated images and escaped, evidence-bound public copy.
  OCR, visual audit, human inspection and user approval are separate verdicts; disabled checks are
  `unavailable`, not passed.
- Never treat the image model's rasterized source URL as exact citation data. In the first real
  2.5-route output the footer URL visibly differed from the frozen URL despite valid geometry.
  `render_exact_source_footer(original_bytes, case)` now draws date, source and the exact URL
  from `ValidatedInfographicInput` into a separate 1152×2048 PNG. It preserves every original
  pixel for `y < 1858`; the original raster and SHA stay under `image` / `image_sha256`, while
  `derived_image` / `derived_image_sha256` identify the local corrected PNG. `preview.html` uses
  the derived image only when `footer=passed`. Never call the derived image provider-original.
- The deterministic footer uses `/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` and
  records `footer_version`, `footer_font_sha256` and `footer_source_url_lines`. Joining those
  lines must exactly equal the frozen URL. Render date/source/URL/note at fixed readable sizes,
  without truncation or silent shrinking; reject missing font, oversized text or unsafe raster.
  Preflight this font/layout with the frozen case **before any copy or image intent/model call**.
- The offline repair command verifies prior manifest/quality/copy/private request identity and
  raw image SHA against the frozen input before creating a fresh sibling output. Its manifest
  records `repair.model_calls=0`, raw and derived hashes; human/user approval remains pending and
  OCR/visual audit are not inherited as passed for the new derived pixels.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Input lacks selected topic, accepted copy/audit, exact source footer, fact or brand binding | Reject before a paid call |
| Finalized poster prompt fails shared prompt policy | Local deterministic rejection; no image intent and no image POST |
| Frozen date/source/URL cannot fit exact footer or CJK font is missing | `blocked_preflight` before any copy/image intent or model call |
| Prior accepted-copy record is missing, changed or not byte-equivalent to the private frozen copy | Reject before new output directory/model construction; no image POST |
| First image is valid 1152×2048 original bytes | Save it; permit remaining distinct cases within the three-image ceiling |
| Provider returns a square, corrupt, unsafe-URL or other invalid output | Preserve the allowlisted output reason; stop the remaining cases; no retry |
| Timeout or ambiguous 5xx after dispatch | `result_unknown`; preserve intent; never replay the same run directory |
| Provider rejects a request deterministically | `failed`; preserve safe status, not body |
| OCR or visual judge disabled | `unavailable`, with no false judge-call intent |
| Real image lacks manual inspection or user approval | Batch acceptance remains false |
| Image is valid portrait but its rasterized source URL differs from frozen source | Keep local sample, record visual rejection; never publish as accepted |
| Offline prior image SHA, copy, source, manifest or path differs from frozen case | Reject before creating sibling; no model/network call |
| Exact deterministic footer succeeds | Preserve provider bytes; save distinct derived PNG/hash, exact drawn URL lines and pending human/user verdict |

## 5. Good / Base / Bad Cases

- Good: three distinct accepted snapshots pass preflight, one image POST per case produces original
  portrait bytes, and the preview reports each independent quality observation.
- Base: the first poster fails exact geometry or output validation; the other two are marked
  `skipped_after_first_portrait_gate` and the failed run remains inspectable.
- Bad: silently stretching a square image, retrying after an unknown result, labeling historical
  news as today's, or calling an unavailable OCR/visual judge “passed.”
- Reuse good: the same frozen case and exact prior audited copy reach one image request without
  chat intents. Reuse bad: a later-edited `copy.json` or missing private request snapshot is
  called “audited.”
- Footer good: the derived URL lines join exactly to the frozen URL, remain legible and retain
  1152×2048 while all pixels above row 1858 match the provider original. Footer bad: cropping
  the whole poster, replacing the raw bytes, silently truncating a long URL, or claiming an
  offline repair performed a fresh model generation.

## 6. Tests Required

- Input tests reject mismatched source footer, missing/dangling evidence or brand IDs, repeated
  event versions, unsafe API origin/redirect and corrupted frozen input before model construction.
- Adapter tests cover square-default regression and opt-in portrait payload/output checks across
  direct raster, Base64, URL and asynchronous result paths.
- Fake end-to-end tests assert one image call, exclusive intent and private request snapshot,
  no rerun in an existing directory, 503/timeout/invalid dimensions/corrupt raster states,
  safe typed output-reason projection, exact shared prompt-policy preflight (including a negated
  prohibited term), `gpt-image-2.5-sunburst` local selection despite a global `gpt-image-2`
  override, disabled-judge `unavailable`, escaped preview and no accidental social/database mutation.
- Reuse tests assert exact copy equality against the prior private request, matched
  input/package/footer, no chat calls/intents, one image request and fail-closed tampering.
- Footer tests assert exact line-join equality, date/source identity, top-pixel equality,
  immutable raw bytes, two hashes, fresh sibling/no overwrite, preflight before model calls,
  long URL/font failure and tampered prior image/manifest/input rejection.
- A live trial is separate evidence: unit tests cannot prove gateway support or visual fidelity.
  Inspect actual bytes, Chinese text, both characters and every Xiaosai AI badge before acceptance.

## 7. Wrong vs Correct

### Wrong

```python
except ImageOutputValidationError:
    outcome["reason_code"] = "image_stage_failed"
    retry_image()
```

### Correct

```python
except ImageOutputValidationError as error:
    outcome["generation"] = "invalid_output"
    outcome["reason_code"] = error.reason  # closed, content-free allowlist
    stop_portrait_capability_trial()
```

Two 2026-09-23 local runs returned `invalid_output` before any image POST because the poster
prompt's negative wording contained terms blocked by the shared lexical policy. A dry-run of
`_payload()` alone missed this earlier validator and led to an incorrect initial provider-failure
hypothesis. Test the *complete* pre-dispatch path, not only payload construction. Those historical
run directories remain immutable; their image intent files are conservative reservations, not
evidence of provider requests. The subsequent Sunburst selection is separately authorized by the
user, not an automatic fallback.

For copy reuse, **wrong** is trusting `manifest.cases[0].copy == "accepted"` while loading a
possibly edited `copy.json`. **Correct** is comparing that exact copy with the prior private
image-request snapshot and rejecting any missing or mismatched artifact before creating a new
run. A manifest status alone is not a content-integrity proof.

The 2026-09-23 controlled Comfly request carrying `model=gpt-image-2.5-sunburst` produced a
fully decodable 1152×2048 PNG. This proves that route/size worked for that request, not the
relay's internal upstream-model identity or precise Chinese-text fidelity. Local OCR and visual
audit were disabled, and the visible footer URL was wrong; the run is a model-capability sample,
not an accepted publishable poster.

For exact citations, **wrong** is presenting a rasterized model footer as verified because the
HTML side panel has the correct link. **Correct** is displaying the separate deterministically
drawn PNG only when its `footer=passed`, `footer_source_url_lines` join to the frozen URL and
its raw/derived hashes are both recorded. The first local offline repair produced such a PNG
without a model call; that fixes citation rendering, not the still-pending human/user verdict.

## Scenario: Explicit evidence-first model-rendered comparison (local only)

### 1. Scope / Trigger

Use when comparing integrated model-rendered Chinese body text with a rejected
opaque-panel overlay. This is a local one-case preview, not a production
rendering-policy switch or permission to send.

### 2. Signatures

```text
python -m app.news_infographic_local_main run \
  --input-bundle ONE_CASE_INPUT_JSON --output-dir FRESH_DIR \
  --approved-asset-root PROJECT_ROOT --exact-text-quality-trial \
  --evidence-first-copy-trial --model-rendered-text-trial --execute
build_model_rendered_image_prompt(case: ValidatedInfographicInput, copy: PosterCopy) -> str
```

### 3. Contracts

- Require both exact-text and evidence-first flags; forbid copy reuse. Build
  frozen-claim copy deterministically and retain an independent copy audit
  before one separately versioned image intent. A new directory is not a
  replay waiver for an ambiguous same-package/policy request.
- The image model paints headline, summary, cards and illustration. Apply no
  opaque body overlay. Only the narrow source/date/URL footer is drawn from
  frozen input. Keep original, footer and exact group-JPEG hashes distinct.
- News context in the image prompt comes from bound copy, not an unbound topic
  title. Ask for no placeholder bars, pseudo-text, unsupported mechanisms or
  brand promises. Require the approved character reference and Xiaosai AI
  badge.
- Accepted JSON copy is not verified pixel text. Keep
  `body_text_verification=not_checked`, `send_ready=false` and independent
  OCR/visual/human states until the final JPEG is checked. Disabled judges
  are unavailable, not passed.
- Provider unavailable after dispatch remains `generation=result_unknown`
  even with a safe typed reason; preserve the request and do not replay.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Invalid flag combination or old output path | Reject before paid intent |
| Prompt imports unbound title/claim | Provider-free test/preflight rejection |
| Valid 1152×2048 raster | Preserve bytes; exact footer/JPEG; body OCR and visual still pending |
| Provider unavailable or ambiguous | One intent, `result_unknown`, no image/send/replay |
| Wrong Chinese, placeholders or phone-illegible type | Reject final JPEG; no send |

### 5. Good / Base / Bad Cases

- Good: one frozen case gives a fresh integrated-text image and exact source
  footer, pending all pixel-content checks.
- Base: audit accepts but image service is unavailable; no preview exists.
- Bad: treating copy audit as rendered-text OCR, reusing the overlay verdict,
  or retrying an unknown result in a new directory.

### 6. Tests Required

- Test CLI flag combinations, independent policy/fingerprint, one intent and
  no replay, no body overlay, exact footer/asset hashes, and unchanged old
  overlay and production behavior with fake adapters.
- Test bound prompt context and safe non-sendable projections; real final-JPEG
  OCR, visual and phone inspection remain separate activation evidence.

### 7. Wrong vs Correct

```python
# Wrong: a JSON-valid copy is not proof of painted Chinese characters.
send_ready = copy_audit.accepted and image_generated

# Correct: preserve the image under the new policy with unverified body text.
send_ready = False
body_text_verification = "not_checked"
```

## Scenario: One-case v9 advisory automatic local preview

### 1. Scope / Trigger

Use this when an operator wants to see one **new** automatically drafted
Moments-rich infographic even if its independent content review is negative or
malformed. It is a local no-send preview of the formal v9 prompt, character
reference and rendering contract; it does not create a formal database job or
prove that the painted Chinese is publication-ready. Do not replay a consumed
historical package/policy intent merely by choosing a new output directory.

### 2. Signatures

```text
python -m app.news_infographic_advisory_preview_main \
  --input-bundle FROZEN_INPUT_JSON \
  --package-detail EXACT_PACKAGE_DETAIL_JSON \
  --copy-run-detail SAME_PACKAGE_ACCEPTED_RUN_DETAIL_JSON \
  --approved-asset-root PROJECT_ROOT \
  [--output-dir FRESH_PROJECT_OUTPUT_DIR --execute]

preflight_advisory_preview(...) -> AdvisoryPreviewPreflight
execute_advisory_preview(...) -> dict[str, object]
```

The three JSON inputs come from exact read-only package and accepted-copy-run
GETs. The CLI never accepts a loose article URL or model-written provenance.

### 3. Contracts

- Provider-free preflight validates the same package, event, active draft,
  business date, source snapshot, accepted Moments text, pinned character
  reference and footer/notice font. It must also check the global v9 intent
  ledger read-only; an already reserved generation, audit or image stage is a
  blocked preflight, not `preflight_valid`.
- `--execute` requires a fresh output directory. Before each paid Zhipu
  generation/audit or Comfly image call, reserve an exclusive 0600
  package/policy/stage intent under
  `output/daily-news-infographic-advisory-v9-intents/`. A timeout or unknown
  result consumes that stage; there is no automatic retry or cross-directory
  replay. Keep prompts, model responses and request details in 0700/0600
  private files; emit only safe hashes/statuses in `summary.json`.
- Use the same v9 four-field rich prompt, advisory copy assembly and audit
  prompt as the formal producer. A negative, unavailable or schema-invalid
  audit remains a warning and may proceed to one image request; it is never
  relabeled accepted. A structurally unusable four-field draft or wrong
  frozen source cannot form an image request.
- `LocalInfographicAI` pins Comfly `gpt-image-2.5-sunburst`; do not inherit the
  unrelated global square-image setting. Use the formal v9 **character-only**
  reference contract, not the two-reference historical style comparison.
  Paint the visible `AI生成 · 内容/排版未核实` notice, exact formal source/date/full
  URL footer, bounded 1152×2048 <=2 MiB group JPEG and 390px phone preview.
  All output remains `send_ready=false`, with OCR/visual/human status truthful.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Package/run/source/draft/reference/font mismatch | Block before a paid intent |
| Existing v9 stage intent or reused output path | Block preflight/execute; no replay or overwrite |
| Negative or schema-invalid independent audit | Preserve warning and private raw observation; continue to one local image when the draft and source are usable |
| Image transport unknown or invalid post-response raster/JPEG | Retain image intent, report non-sendable unknown/quality failure; no retry |
| Known valid raster, exact footer and <=2 MiB JPEG | Save raw/notice/footer/group/phone hashes; still `send_ready=false` |
| Painted text clips, repeats claims or invents detail | Human review records issue; preview is not approved for sending |

### 5. Good / Base / Bad Cases

- Good: a fresh current-date accepted package with same-package Moments draft
  and a malformed independent audit yields one visibly warned local JPEG, an
  exact source footer and a phone preview, without a WeCom call.
- Base: preflight finds an already reserved v9 intent and makes no paid call
  or new output directory.
- Bad: claim a successful image request means exact Chinese/brand copy passed,
  or use a historical local style reference and call it the formal v9 result.

### 6. Tests Required

- Fake-model tests assert same-package preflight, zero-call dry-run, occupied
  ledger refusal, one exclusive intent per stage, negative/schema-invalid
  audit continuation, unknown no-retry and no DB/WeCom side effect.
- Assert character SHA and exact model identity, visible warning, frozen
  source URL/date, 1152×2048 JPEG size/SHA and 390px output. Inspect every
  live final JPEG and phone preview manually; record clipping, repeat and
  badge issues instead of promoting it to `send_ready=true`.

### 7. Wrong vs Correct

```python
# Wrong: a dry-run that ignores a spent image request invites a duplicate call.
return {"status": "preflight_valid"}

# Correct: read the global intent ledger before claiming an executable preview.
assert_no_reserved_v9_intent(package_id, policy_version)
return {"status": "advisory_preview_preflight_valid", "send_ready": False}
```

## Scenario: One-case v12 concise advisory automatic local preview

### 1. Scope / Trigger

Use this forward-only policy when the v9 automatic poster is too verbose for
the user-approved blue/green/purple reference. The old v9, rejected v10 and
approved local v11 intents and pixels remain immutable. This command is a local visual trial,
not a WeCom send, a formal enablement switch, or an Official Account change.

### 2. Signatures

```text
build_advisory_generation_prompt(case, binding) -> str
build_advisory_rich_copy(case, binding, raw_draft) -> AdvisoryRichCopy
build_advisory_image_prompt(case, copy) -> str
python -m app.news_infographic_advisory_preview_main \
  --input-bundle FROZEN_INPUT --package-detail FROZEN_PACKAGE \
  --copy-run-detail FROZEN_MOMENTS --approved-asset-root PROJECT_ROOT \
  [--output-dir FRESH_DIR --execute]
```

### 3. Contracts

- Version the changed title/claim selection, formal policy, copy and generation
  prompt, plus the local intent namespace together as v12. A dry-run checks
  the exact accepted package/copy-run/reference identity and occupied v12 ledger
  without making any paid request or creating an output directory.
- An accepted run may retain a rejected historical draft; only its exact active
  draft must be accepted and byte-identical to the package's accepted prose.
  Compare claim IDs, kinds, text and binding-ID sets, ignoring only the order
  of those IDs. A changed or duplicated binding ID remains a mismatch.
- A neutral title may use a safe CJK noun phrase that occurs exactly in both
  the frozen topic title and one same-source bound external fact. If the first
  eligible fact cannot fit the measured card, select another eligible fact
  from that same package; never truncate or import another news item's fact.
- The model returns exactly `top`, `news`, `child`, `brand`. Final **visible**
  budgets are 58/96/90/108 characters respectively, including the frozen
  full news fact, child frame, bound brand statement and needed sentence
  separator. The editorial continuation has a nonempty minimum; headings
  have measured CJK-width preflight. A long fixed claim may make this concise
  policy unavailable; do not silently omit, shrink or truncate it.
- The top introduction is a discussion hook, not a second news-fact summary:
  it cannot reuse an Arabic-number token from the bound blue-card fact.
  Each card has one role and must end above the deterministic y1858 source
  footer; the y0–100 advisory notice remains visible on the final JPEG.
- If a model field begins with one byte-exact copy of its *matching* fixed
  fact/frame/brand prefix, remove only that duplicated prefix before applying
  all bounds and provenance checks. Reject broken, misplaced or emptied
  prefixes; do not rewrite paraphrases or replace unsupported assertions.
  Preserve the raw private response and SHA-256, plus the normalized field
  names, in the local result. The immutable exact fact and brand statement
  remain in the assembled copy and image prompt.
- The local result stays `send_ready=false` even if the audit is negative or
  schema-invalid and an image is produced. Retain truthful warning codes,
  exact source date/name/full URL, byte and pixel checks, one intent per
  package/policy/stage and unknown-result no-retry. The displayed image is
  the final group JPEG plus a 390px preview of those exact bytes.
- For future failed image trials, keep the existing non-replayable status and
  add only a closed `image_failure` projection: provider exception class/code
  (and sanitized typed HTTP status/response kind when the adapter supplies
  them, revalidated at the summary boundary), provider-result validation, or
  deterministic derivative step. Never
  print an exception string, HTTP body, credential, prompt or raw response;
  a generic exception remains `other_exception` / `provider_outcome_unknown`.
  Diagnostic enrichment does not reset a consumed image intent.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Occupied v12 intent or reused output directory | Refuse before a paid call; never replay old v9/v10/v11 attempts |
| Fixed span already exhausts its visible budget or heading is too wide | `AdvisoryCopyError`; no image request |
| Editorial field repeats a partial/inside fixed passage, exceeds its combined budget or copies a bound numeric fact into `top` | `rich_copy_unusable`; preserve raw-response SHA, no audit/image intent |
| Exact matching fixed prefix appears once at field start with a valid continuation | Normalize that duplicate once; rerun all copy and image checks |
| Audit rejects or is schema-invalid but a valid portrait arrives | Keep warnings truthful and a local unverified preview; never mark it approved |
| Provider result unknown, wrong geometry, wrong source/footer or group JPEG over 2 MiB | No send-ready image; no automatic retry |
| Image provider throws, returned result fails validation, or a derivative fails | Keep the spent intent and distinct allowlisted `image_failure` category; no raw error text or replay |

### 5. Good / Base / Bad Cases

- Good: one accepted same-package Moments snapshot produces short distinct
  intro/news/inquiry/teaching text and a 1152×2048 local JPEG with all three
  cards fully above the exact source footer, still `send_ready=false`.
- Base: the model repeats the exact child frame at the start; remove only
  that duplicate and record the raw hash. If the top also repeats the blue
  card's numeric fact, stop without an image.
- Bad: shorten by cropping the purple card, reducing text below readable
  size, stripping a non-identical phrase, or reusing the consumed v10 draft
  under a new output directory while claiming it was newly generated.

### 6. Tests Required

- Assert version/ledger changes, all four combined limits, separator cost,
  exact prefix normalization, rejection of partial/inside prefixes and
  numeric top/blue overlap, source/brand identity and immutable raw hash.
- Fake-provider and PostgreSQL producer tests must accept legitimate topic
  overlap, keep warning truth, and leave original text/image delivery and
  Official Account drafts unchanged. Run Ruff, strict mypy, scoped unit and
  integration tests; a provider-free real-package preflight is not proof of
  model compliance.
- On a real generated final JPEG, inspect native and 390px text, clipping,
  exact source and Xiaosai AI mark. OCR/visual and human verdicts remain
  separate; no WeCom send/deployment follows from a single local image.

### 7. Wrong vs Correct

```python
# Wrong: a small model field can still overflow after the fixed fact is added.
if len(raw_draft["news"]) <= 96:
    image.generate(...)

# Correct: normalize only a matching fixed prefix, then bound visible text.
news = remove_one_exact_leading_fixed_fact(raw_draft["news"], frozen_fact)
if len(frozen_fact + sentence_separator + news) > 96:
    raise AdvisoryCopyError("advisory copy exceeds concise visible-text budget")
```

## Scenario: Rich-copy proposal preflight (default off)

### 1. Scope / Trigger

Use this only to test whether a frozen accepted news package can support the
user's three-paragraph infographic standard. It does not select the daily
production copy, call a model, render an image, or authorize WeCom delivery.

### 2. Signatures

```text
build_rich_copy_proposal(case: ValidatedInfographicInput) -> RichCopyProposal
validate_rich_copy(case: ValidatedInfographicInput, proposal: RichCopyProposal) -> None
preflight_rich_layout(case: ValidatedInfographicInput, proposal: RichCopyProposal) -> RichLayoutReport
```

### 3. Contracts

- Policy `daily-news-infographic-rich-copy-proposal-v1` is separate from
  `PosterCopy` and the formal evidence-first producer. A proposal carries the
  frozen input fingerprint, exact source name/date/URL, deterministic cited
  title, ordered news/child/brand cards and typed spans with claim IDs.
- External fact spans must equal a frozen `external_fact` claim and retain its
  same-source evidence binding. Brand spans must equal a frozen
  `brand_statement` claim with a bound brand chunk. Editorial spans use only
  reviewed role-specific wording and cannot introduce a number. Require at
  least two distinct news facts and two brand statements; each paragraph is
  48–150 characters, not generic padding.
- Layout proposal v1 measures 1152×2048 using the installed SHA-recorded Noto
  CJK font, reserves the footer below y1858, limits title/summary/card line
  counts, and projects 390px type size. This is a design envelope, **not** an
  implemented renderer or a visual/phone readability verdict.
- `RichLayoutReport.rich_content_review_passed`, `renderer_implemented`,
  `independent_audit_passed` and `exact_jpeg_verified` must all remain false.
  The current deterministic proposal duplicates the deck's facts in the first
  card and uses generic child/brand editorial language; its character count
  and measured fit do not satisfy the approved rich-content example. A future
  contextual proposal requires separate semantic review and exact-image gates.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Source/date/URL/fingerprint differs | `RichCopyError`; no image intent |
| Fact or brand text/ID/binding changed, or editorial adds unsupported content/number | `RichCopyError`; do not relax the older `PosterCopy` validator |
| Fewer than two distinct supported facts or brand statements, or paragraph sparse | `RichCopyError`; no fabricated filler |
| Measured line, font, panel or footer bounds fail | `RichCopyError`; no silent font shrinking |
| Bound copy fits but contextual richness, renderer or exact JPEG is unreviewed | Keep all readiness flags false; no send |

### 5. Good / Base / Bad Cases

- Good preflight: a frozen case with two cited facts and two bound brand claims
  produces a typed proposal and measured layout report, still non-sendable.
- Base: the approved WorldSkills case passes mechanical checks but repeats
  itself between the deck and blue card; richness review remains false.
- Bad: mark it accepted solely because it has 48 characters, fits four lines,
  or returns a 1152×2048 image.

### 6. Tests Required

- Assert exact title/fact/brand/source binding, distinct evidence, paragraph
  density, unsupported-number rejection and fail-closed sparse/long cases.
- Assert policy/card-order tampering cannot bypass validation and all readiness
  fields remain false after preflight. Keep legacy infographic tests passing.
- Before future activation, add contextual non-duplication/semantic tests and
  inspect each actual transmitted JPEG with OCR, visual audit and 390px human
  review on at least three distinct current-news packages.

### 7. Wrong vs Correct

```python
# Wrong: typography plus provenance do not prove the reference's content quality.
send_ready = preflight_rich_layout(case, proposal) is not None

# Correct: reserve image and send decisions for separately verified stages.
report = preflight_rich_layout(case, proposal)
assert not report.rich_content_review_passed
assert not report.exact_jpeg_verified
```

## Scenario: Case-pinned rich WorldSkills image-chain trial (local only)

### 1. Scope / Trigger

Use this only to compare the existing Comfly portrait-image chain with one
user-reviewed rich-text WorldSkills sample. The prose is pinned human-reviewed
input, **not** automatically drafted daily copy; the run is historical and
cannot be treated as a current formal news package or WeCom send.

### 2. Signatures

```text
python -m app.news_infographic_local_main run \
  --input-bundle FROZEN_WORLDSKILLS_INPUT_JSON \
  --output-dir FRESH_PROJECT_OUTPUT_DIR \
  --approved-asset-root PROJECT_ROOT \
  --rich-worldskills-trial --execute

build_reviewed_rich_worldskills_copy(case: ValidatedInfographicInput) -> PosterCopy
validate_reviewed_rich_worldskills_copy(case: ValidatedInfographicInput, copy: PosterCopy) -> None
```

### 3. Contracts

- Require exactly one frozen package ID `2e1b6d31-68c1-4f43-b77e-cd580e171595`,
  input fingerprint `38c32c4ba43e2ef812d4e26bc2b64d8f40752fa47e733ba82084d3f7469e3ad0`,
  source/date/URL and exact cited fact/brand bindings. The approved copy Markdown
  has SHA-256 `5e25f60674d6d7733f6a3b4a11d1e9bc4cfe6b68d8cab3199950b81f24f272fa`;
  the style-only reference PNG has SHA-256
  `c81c1557befd9b412473e38e15388a9957abd249b7d3e89649f358e0dacb2935`.
  Also require the existing pinned Xiaosai character reference. Reject changed,
  missing, symlinked or out-of-root inputs before a paid intent.
- Use a separate copy/prompt/trial/visual version and separate validation
  function; never relax `validate_poster_copy` for the old production policy.
  Brand claims must be quoted in the rich body, Arabic-numeral tokens must
  come from frozen claims, and editorial interpretation must remain distinct
  from source assertions. Run the independent rich-copy semantic audit and
  font/prompt/reference preflight **before** image intent.
- The exact image path is Comfly `gpt-image-2.5-sunburst` at 1152×2048, at
  most one image request for this package/policy. Reserve an exclusive
  cross-directory intent and private request snapshot; a new output directory
  cannot replay an unknown result. Preserve raw PNG, exact-source footer PNG,
  bounded final group JPEG and 390px preview with distinct hashes.
- The result always reports `send_ready=false`, `body_text_verification=not_checked`
  until actual final-JPEG OCR/visual/human review. A returned image does not
  prove exact Chinese or stable `赛先生`/`AI` marks. No WeCom, Official Account,
  scheduler, database or production-policy mutation is allowed.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Wrong case, source, claim/brand binding, approved-copy SHA or reference SHA | Reject before audit/image intent |
| Symlinked `output` root or reused run directory | Reject before writing outside project or replaying an attempt |
| Deterministic rich copy, layout or independent audit fails | No image intent or image POST |
| Image provider returns ambiguous/timeout | `result_unknown`, preserve intent, no automatic replay |
| Valid portrait image returns but exact JPEG OCR/visual is unavailable | Keep preview inspectable and `send_ready=false` |

### 5. Good / Base / Bad Cases

- Good trial: one bound historical case, accepted independent copy audit and
  one image request produce separately hashed raw/footer/JPEG/phone assets.
- Base: copy passes but image result is unknown; record one intent, no raster
  and no new-directory retry.
- Bad: call this one manually pinned sample “daily rich-copy automation”,
  infer painted text fidelity from accepted JSON copy, or send the image merely
  because its JPEG is below 2 MiB.

### 6. Tests Required

- Provider-free tests assert exact case/copy/style hashes, fact/brand/number
  rejection and independent audit refusal before image intent.
- Fake-provider tests assert one durable cross-directory image reservation,
  fresh policy fingerprint, exact footer/JPEG/phone hashes, unchanged old
  modes and truthful non-sendable states. Test symlinked output-root refusal.
- For a live trial, inspect the **final group JPEG** at native and 390px,
  then run exact body-region OCR and visual/badge review before any readiness
  claim. Three distinct current-news cases and formal rollout gates remain.

### 7. Wrong vs Correct

```python
# Wrong: a successful image POST is not proof that approved Chinese was painted.
send_ready = generated and copy_audit.accepted

# Correct: preserve a reviewable but unsendable local artifact.
send_ready = False
body_text_verification = "not_checked"
```
