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
- Every controlled v2/v3 image uses one finite, OCR-verifiable three-level text group in this
  exact order: brand signature `赛先生科学`, one allowlisted category title, and one allowlisted
  short category subtitle. The group sits in a restrained deep-science-blue rounded card with a
  small orange accent and must not cover a character face, scientific object, or main action.
  Raw headlines, generated slogans, full copy, keywords, the historical long brand-value line,
  pseudo-text, and any fourth line are forbidden. Historical v1 text metadata and ordering remain
  unchanged.
- API and content worker must receive identical `IMAGE_DIVERSITY_*`,
  `IMAGE_VISUAL_BRIEF_VERSION`, `IMAGE_PERCEPTUAL_HASH_VERSION`,
  `IMAGE_SIMILARITY_POLICY_VERSION`, `IMAGE_SIMILARITY_THRESHOLD`, and bounded history settings.
  Doctor enforces equality. The master flag defaults to false and requires image generation, the
  approved selector, and exact OCR validation; startup fails closed if OCR is disabled.
- Planning reads at most the configured rows from the last seven local business dates. A short
  PostgreSQL advisory-lock transaction reads history and reserves two different plans and their
  references. Manifest parsing precedes the lock; provider and MinIO calls follow commit.
- The request fingerprint binds both ordered plans, both ordered approved reference sets, the
  bounded history digest, and every diversity version. Replay returns the same artifact.
- Governed topic categories bound the subject vocabulary. The generic science fallback may use
  only a neutral science-book/model or experiment apparatus; robotics, AI, astronomy, and
  competition objects require the corresponding governed category and cannot be introduced only
  to improve novelty.
- After existing media, dimension, OCR, identity, and visual-audit gates pass, attempt 1 is
  perceptually compared with bounded successful history. A near duplicate activates the already
  reserved alternate exactly once with a distinct provider fingerprint. Attempt 2 that remains
  near-duplicate succeeds with `near_duplicate_after_retry`; it is not review-required and remains
  eligible for the existing delivery policy.
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
| Controlled prompt has a missing, reordered, unapproved, or extra text line | Fail before provider use when detectable from the brief; otherwise OCR repair/failure remains authoritative |
| Safety/OCR/identity/media/audit failure | Existing typed failure/recovery path; similarity cannot override it |
| Provider/network failure | Existing bounded provider retry classification; does not consume the diversity retry |
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
  provider-rejection recovery, and v1 dispatch/metadata compatibility.
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

The controlled prompt and OCR gate also share the same finite text contract:

```python
expected_text = ("赛先生科学", allowlisted_title, allowlisted_subtitle)
assert prompt_renders_exactly(expected_text)
assert ocr_result.recognized_lines == expected_text
```
