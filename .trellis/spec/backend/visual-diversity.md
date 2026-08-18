# Controlled Visual Diversity

## Scenario: Seven-day deterministic variation with one similarity repair

### 1. Scope / Trigger

This contract applies when an accepted independent copy run reserves its one image artifact with
`IMAGE_DIVERSITY_ENABLED=true`. It keeps the approved Sai Xiansheng/Xiaosai 3D identity and varies
only a finite scene, composition, camera, cast, slot tone, subject, and approved action/style
reference set. It does not combine sibling news items or authorize a new publishing surface.

### 2. Signatures

- Pure planning: `plan_controlled_visuals(context, recent_plans, ...) -> (primary, alternate)`.
- Similarity: `evaluate_image_similarity(body, references, threshold) -> ImageSimilarityResult`.
- Persistence: Alembic `20260815_0021` adds nullable/default-compatible artifact diversity fields,
  `image_visual_plan_reservations`, `image_similarity_attempts`, and attempt-aware image
  references.
- Material API: `ImageArtifactResponse.diversity` is optional. It projects only controlled enums,
  versions, retry/warning status, booleans, bounded distance/threshold/count, and decision.
- The content worker remains the only paid-provider execution owner; API handlers only reserve or
  project durable state.

### 3. Contracts

- The reviewed version bundle is `visual-diversity-policy-v1`,
  `visual-brief-v2-controlled-diversity`, `brand-visual-selector-v2-novelty`,
  `image-prompt-v3-controlled-diversity`, `image-pipeline-v3-controlled-diversity`,
  `image-perceptual-hash-v1`, and `image-similarity-policy-v1`.
- Every controlled v2/v3 brief and prompt requires one finite three-level text group in this
  exact order: brand signature `赛先生科学`, one allowlisted category title, and one allowlisted
  short category subtitle. The group sits in a restrained deep-science-blue rounded card with a
  small orange accent and must not cover a character face, scientific object, or main action.
  Raw headlines, generated slogans, full copy, keywords, the historical long brand-value line,
  pseudo-text, and any fourth line are forbidden. Historical v1 text metadata and ordering remain
  unchanged.
- API and content worker must receive identical `IMAGE_DIVERSITY_*`,
  `IMAGE_VISUAL_BRIEF_VERSION`, `IMAGE_PERCEPTUAL_HASH_VERSION`,
  `IMAGE_SIMILARITY_POLICY_VERSION`, `IMAGE_SIMILARITY_THRESHOLD`, and bounded history settings.
  Doctor enforces equality. The master flag defaults to false and requires image generation and
  the approved selector, but OCR is an independent optional gate. `IMAGE_DIVERSITY_ENABLED=true`
  with `IMAGE_OCR_ENABLED=false` is valid: no recognizer is created or called, OCR absence is not a
  package failure, and the generated image's realization and order of the requested text remain
  explicitly unverified. Raster media/signature/size/1024x1024, storage integrity, provider
  identity, enabled visual audit, and perceptual-diversity gates remain authoritative.
- When enabled, controlled image OCR is capability-routed independently from text generation. It uses
  `IMAGE_OCR_MODEL=glm-ocr` on Zhipu `/layout_parsing`, while `AI_CHAT_MODEL=glm-5.2` remains the
  text model and the disabled image-quality auditor retains its existing OpenAI-compatible route.
  API and content worker receive identical OCR enablement, model, 10 MiB input, 1 MiB response,
  and 120-second timeout settings. Only media-gated PNG/JPEG bytes are accepted; the adapter sends
  a private Base64 data URL and never a public image URL.
- The direct HTTP image-OCR adapter decodes only the raw MaaS envelope: the configured model must
  match, `layout_details` must contain exactly one bounded nested page, and typed
  `data_info.num_pages` must equal one. It does not auto-detect or fall back to the SDK-normalized
  `json_result` envelope, because that shape has different provenance and coordinate semantics;
  normalized/error and raw-success envelopes that co-occur are terminal source conflicts. A
  present legacy `page_count` alias must agree with authoritative `num_pages` rather than being
  silently discarded.
  Raw indices are bounded, unique, nonnegative integers; zero- and one-origin and non-contiguous
  sequences are valid because the provider publishes no base or continuity invariant. Index is
  only the final geometric tie-breaker and its origin never changes ordering.
- Raw text bboxes must be finite ordered four-number lists. Bbox scale is selected once for the
  whole raw page: if every text coordinate is in `[0,1]`, the documented normalized form is used;
  if any text coordinate is above one, every text bbox is treated as raw pixels. This prevents a
  small pixel box whose coordinates happen to be at most one from being mixed with normalized
  boxes and changing geometric order. The all-at-most-one case is harmlessly ambiguous because
  either interpretation applies the same positive axis scaling and preserves `(y1, x1)` order.
  Pixel coordinates require positive bounded page width and height, x/y bounds are checked against
  the corresponding axes, and an unbound scale is never guessed. `data_info.pages`, when present,
  is the authoritative dimension source. Element `height` and `width` are independently optional
  page-axis metadata under the raw OpenAPI contract; each present value is type/range checked and
  is used as a fallback only when the required axis is unambiguous. Element/page equality is not
  required because the official executable converter uses `data_info.pages`, not element
  metadata, for normalization.
- The raw label mapping stays finite and explicit: `text` is visible text, `image` is ignored, and
  `table`/`formula` are terminal unsupported structures. Unknown labels and case variants are
  terminal. Image `content` and `bbox_2d` are optional and ignored even when their provider-owned
  representation is not text-like; text content must be null/absent or a bounded string and text
  must have a usable bbox before it can enter the exact gate. Null/absent text content projects no
  line and therefore reaches the existing missing-text decision. The adapter sorts text by
  normalized `(y1, x1, index)`, normalizes line endings and Unicode whitespace, caps output at
  eight bounded lines, and applies the unchanged exact ordered signature/title/subtitle gate.
- Bounded top-level, `data_info`, and page-info transport extensions are discarded at this private
  boundary. Raw layout elements accept only the six documented keys (`index`, `label`, `bbox_2d`,
  `content`, `height`, and `width`); an unknown element key is terminal because an alternate
  label/content field could change exact-visible-text semantics if silently ignored. Ignored or
  rejected extension values are never logged, projected, or persisted, and the 1 MiB response
  ceiling bounds their resource/privacy exposure. The adapter emits only content-free allowlisted
  parser codes that distinguish source invalid/conflict, schema, page count, dimensions/conflict,
  index/duplicate, label, bbox shape/scale/range, content type/limit, element extra, line limit,
  table, and formula.
  The material worker routes only missing, unexpected, duplicate, and misordered exact-text codes
  through the one-repair quality path; any parser-stage code, including a tuple mixed with a text
  code, is terminal before repair, similarity, or storage and may enter only the existing safe
  validation snapshot. Raw response bodies, Base64, provider content/URLs, prompts, object keys,
  private paths, and image bytes never enter logs or durable output.
- Fixed numeric bounds exposed through Compose are tested through their real string environment
  representation. In particular, `IMAGE_DIVERSITY_MAX_REGENERATIONS="1"` must normalize to the
  reviewed literal value `1`, while any other value still fails Settings validation.
- Planning reads at most the configured rows from the last seven local business dates. A short
  PostgreSQL advisory-lock transaction reads history and reserves two different plans and their
  references. Manifest parsing precedes the lock; provider and MinIO calls follow commit.
- The request fingerprint binds both ordered plans, both ordered approved reference sets, the
  bounded history digest, and every diversity version. Replay returns the same artifact.
- Governed topic categories bound the subject vocabulary. The generic science fallback may use
  only a neutral science-book/model or experiment apparatus; robotics, AI, astronomy, and
  competition objects require the corresponding governed category and cannot be introduced only
  to improve novelty.
- After existing media, dimension, identity, enabled OCR, and enabled visual-audit gates pass,
  attempt 1 is
  perceptually compared with bounded successful history. A near duplicate activates the already
  reserved alternate exactly once with a distinct provider fingerprint. Attempt 2 that remains
  near-duplicate succeeds with `near_duplicate_after_retry`; it is not review-required and remains
  eligible for the existing delivery policy.
- Provider-output representation recovery is a separate one-use budget carried by the compatibility
  provider-rejection counter. It preserves the active controlled plan and prompt but derives a
  distinct replay-stable provider request fingerprint. A second representation failure uses the
  reserved catalog fallback; it does not activate the alternate diversity plan or permit a third
  provider call. URL/raster/security/integrity failures remain terminal before similarity.
- Raw prompt, plan seed, perceptual hash, nearest object identity, private path/object key, image
  bytes, and provider body never enter the API or logs. The local frontend is an inspection-only
  consumer and is not a production deployable.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Feature disabled or historical v1 artifact | Exact v1 reservation, replay, and optional-API behavior |
| Same input/history/version replay | Same two reservations and no duplicate provider success |
| Concurrent same-slot sibling reservation | Different complete-plan fingerprints under DB lock/unique constraints |
| Exact SHA or perceptual distance at/below threshold on attempt 1 | Persist `regenerate`, discard transient raster, activate ordinal 2 |
| Attempt 2 remains near duplicate and all other gates pass | One stored image, succeeded package, `accepted_with_warning`, no third call |
| Controlled prompt has a missing, reordered, unapproved, or extra text line | Fail before provider use when detectable from the brief; when OCR is enabled, OCR repair/failure remains authoritative for rendered text |
| Diversity enabled with OCR disabled | Make no OCR provider call and do not fail for missing OCR; continue through raster, identity/enabled-audit, similarity, storage-integrity, and persistence gates while treating rendered visual text as unverified |
| Empty/PDF/WebP/oversized/malformed OCR input | Typed provider-input failure before any HTTP call |
| OCR authentication, rejection, rate limit, timeout, or temporary provider failure | Existing bounded typed provider failure; never consume the similarity repair budget |
| Wrong OCR model identity | Terminal identity-mismatch failure before similarity/storage |
| Flat/multi-page/raw-normalized-conflicting OCR envelope, invalid page count/dimensions, unknown/extra element semantics, invalid index/content, or unsupported table/formula | Granular stage-classified terminal invalid-output before repair/similarity/storage |
| Unit bbox or page-bounded raw pixel bbox | Normalize deterministically, then preserve geometric ordering |
| Pixel bbox without both page axes, or outside a validated page | Terminal bbox scale/range code; never infer `0–1000` or another scale |
| Optional/opaque non-text `image` content/bbox or outer transport extension | Ignore without projection/logging/persistence; unknown element keys remain terminal |
| Safety/enabled-OCR/identity/media/enabled-audit failure | Existing typed failure/recovery path; similarity cannot override it |
| Provider/network failure | Existing bounded provider retry classification; does not consume the diversity retry |
| Invalid image representation | One unchanged-plan output recovery, then catalog fallback; never consume or extend the diversity retry |
| Unknown version bundle or regeneration count other than one | Startup validation fails closed |

### 5. Good / Base / Bad Cases

- Good: ten related news items produce at least eight complete controlled plans while every image
  remains in the same approved 3D brand language.
- Base: no comparable historical hash exists; the first safe image succeeds with an accepted
  similarity attempt and no repair.
- Bad: repeatedly call the provider until an image looks different, randomize plans without a
  persisted history snapshot, expose hashes/prompts, or turn a second safe near duplicate into a
  delivery veto.

### 6. Tests Required

- Domain tests cover the full controlled vocabulary, invalid combinations, deterministic ranking,
  relaxation, primary/alternate difference, prompt isolation, the exact three-line text allowlist,
  provider-rejection and representation recovery, and v1 dispatch/metadata compatibility.
- Settings/material tests prove diversity accepts OCR-off configuration, makes zero recognizer
  calls, and still reaches similarity and safe storage/persistence. OCR-on provider contract tests
  mirror both official raw representations: documented normalized boxes
  and the MaaS pixel boxes exercised by the official SDK converter/tests. They cover zero-/one-
  origin and non-contiguous indices, flat/multi-page envelopes, optional and malformed dimensions,
  missing or unbound scale, page-level scale selection including a small pixel bbox at/below one,
  bbox range, explicit raw labels, ignored image/outer-extension values, rejected element extras,
  malformed text content, table/formula, granular safe issue codes, and exact text projection.
- Fixture similarity tests cover exact, near, distinct, threshold boundary, bounded reference
  count, and invalid thresholds without provider access.
- Real PostgreSQL tests cover clean upgrade/metadata drift/guarded downgrade, exact composite FKs,
  concurrent reservation, idempotent replay, sibling uniqueness, two attempts, one MinIO write,
  and no third provider call using fake providers.
- API/OpenAPI/frontend tests assert v1 absence, safe v2 projection, alternate-plan warning text,
  accessibility, and absence of private hashes/seeds/prompts.
- Full gates include backend/frontend checks, API drift, unique Alembic head, Doctor, full Compose,
  shell syntax, and secret/private-path scans. Ordinary gates never call a live image or WeCom
  provider.

### 7. Wrong vs Correct

#### Wrong

```python
while perceptually_similar(image):
    image = await provider.generate(random_prompt())
```

#### Correct

```python
primary, alternate = reserve_two_plans_under_lock(history_snapshot)
image = await generate(primary)
if safe_and_near_duplicate(image):
    image = await generate_once(alternate, distinct_provider_fingerprint)
persist_safe_image(image, diversity_warning=safe_and_near_duplicate(image))
```

The controlled prompt and optional OCR gate share the same finite text contract when OCR is enabled:

```python
expected_text = ("赛先生科学", allowlisted_title, allowlisted_subtitle)
assert prompt_renders_exactly(expected_text)
if settings.image_ocr_enabled:
    assert ocr_result.recognized_lines == expected_text
```

### 8. Break-loop prevention: raw provider contract drift

- Root-cause categories are cross-layer contract, implicit assumption, and test-coverage gap. The
  first decoder encoded the API prose/examples as stronger invariants (`index > 0`, mandatory
  `[0,1]` bbox, paired/equal dimensions) even though the official executable SDK preserved index
  zero and normalized raw pixel coordinates. Local fixtures repeated those assumptions, so they
  could not discriminate the deployed provider representation.
- A broad `image_ocr_layout_invalid` code had near-zero diagnostic value: zero index, pixel scale,
  optional fields, unknown label, and genuinely malformed content all produced the same safe
  observation. Retrying a paid/live request before splitting these offline classes is prohibited.
- Future provider-boundary changes require a pinned primary-source matrix that distinguishes raw
  HTTP and SDK-normalized envelopes, fixtures derived from both official prose and executable
  examples, one content-free code per actionable parser class, and material tests proving every
  parser code is terminal before repair/similarity/storage. Compatibility may relax only provider
  metadata representation; the finite label mapping and exact visible three-line gate stay closed.
