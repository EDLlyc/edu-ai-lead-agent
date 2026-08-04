# Design: Content-Driven Company IP Image Generation

## 1. Design intent

Make image generation content-aware and brand-owned without adding a second queue or vector database.
The accepted copy and topic produce a small typed visual brief. A deterministic selector resolves the
brief against a private, checksum-backed visual catalog. A versioned prompt assembler then combines the
selected IP references with the topic-specific scene and the approved editorial text layer before the
existing content worker calls Comfly.

The generated image is a standalone visual asset. It may contain the compact editorial layer seen in
the approved reference image, but never the full Moments copy. The full copy remains a separate package
field and a separate future WeCom text message.

## 2. End-to-end data flow

```text
accepted topic + accepted draft
          |
          v
VisualBriefBuilder (pure, bounded, versioned)
          |
          v
private visual manifest -> deterministic AssetSelector
          |
          +--> identity reference(s)
          +--> action reference (topic-specific)
          +--> optional style reference within byte budget
          |
          v
PromptAssembler + exact editorial text allowlist
          |
          v
ImageGenerationRequest(references=ordered tuple)
          |
          v
Comfly adapter -> output validation -> image quality checks
          |
          v
image_artifact + image_artifact_references + material package snapshot
          |
          v
API/UI displays image, brief, references, and safe validation state
```

The API still only reserves work. The content worker remains the only process that calls the image
provider. Provider calls remain outside database transactions.

## 3. Domain contracts

### 3.1 Visual brief

Add a provider-neutral domain value object with bounded fields:

```python
class VisualTextLayer:
    title: str
    learning_line: str
    keywords: tuple[str, ...]
    brand_values: tuple[str, ...]

class VisualBrief:
    category: str
    learning_goal: str
    scene: str
    main_action: str
    characters: tuple[str, ...]
    asset_tags: tuple[str, ...]
    text_layer: VisualTextLayer
    version: str
```

The text layer is `editorial_keywords_and_brand_values`:

- one short topic title;
- at most one concise learning-oriented line;
- at most four topic/process keywords;
- at most one approved brand-value phrase.

The builder normalizes the selected topic and accepted copy into a bounded brief. It uses category and
controlled keyword aliases first, then title/copy tokens, with a safe approved fallback. It never sends
the full copy as an image-text instruction and never accepts a file path from model output.

### 3.2 Visual catalog record

Extend the private manifest record with:

- `asset_id`, relative path, checksum, media type, dimensions, alpha and byte size;
- `characters`, `roles`, `topics`, `poses`, `scene_tags`, `priority`, `approved`;
- `catalog_schema_version` and optional manual-review note.

The catalog loader resolves paths relative to the configured materials root, rejects symlinks and path
escape, rechecks the manifest checksum, and reads bytes only after selection. A small private metadata
override file can hold human labels without entering text RAG or Git.

### 3.3 Asset selection

`AssetSelector` is deterministic:

1. Filter `approved=true`, valid checksum, supported media, configured size/dimension bounds, and role.
2. Score category/topic/action tag overlap, required character coverage, priority, and byte budget.
3. Prefer one combined `xiao-sai + sai-xiansheng` action/identity asset when available, because it
   preserves relative scale and reduces reference bytes.
4. Add an action or style reference only when the total encoded request remains within the configured
   reference budget.
5. Sort ties by descending score, descending priority, then asset ID.
6. Persist the selected role and reason. If the budget forces fewer images, persist
   `reference_mode=single_fallback` or `budgeted_multi_reference` explicitly.

No visual vector search is introduced in the MVP. The manifest is small, private, and better served by
structured tags and stable scoring than by an unmeasured image embedding index.

## 4. Prompt assembly

The assembler creates a bounded versioned prompt from these sections:

1. use case and asset type;
2. identity instruction referencing the supplied company IP images;
3. selected topic, learning goal, scene, and main action;
4. composition based on the approved target: square educational 3D editorial layout with a clear focal
   subject and information panels;
5. deep science blue, clean white, restrained orange, warm and trustworthy educational mood;
6. exact allowed title, learning line, keywords, and brand-value phrase;
7. negative constraints: no full copy, invented logo, extra brand marks, watermark, QR code, real child
   face, unrelated character, fabricated claim, or unrequested English text.

The raw model-generated `image_prompt` remains available as a bounded topic hint, but it cannot override
the brand template, text allowlist, reference roles, safety constraints, or selected assets.

## 5. Provider contract and compatibility

Change `ImageGenerationRequest` to carry an ordered tuple of typed reference objects containing role,
asset ID, filename, checksum, and bytes. The result contract remains unchanged.

The Comfly adapter encodes each validated reference as a bounded data URL in the existing `image` array.
It must enforce the total request bound before sending. The model capability is checked in tests and in a
bounded live smoke. If multiple references are rejected, the worker may retry once using the explicit
single-reference fallback only when the configured fallback policy permits it; it must not silently
drop identity input.

ToAPIs and fake adapters retain their existing modes. Fake mode records the request shape without network
access. Historical image artifacts are immutable and are never rewritten.

## 6. Persistence and API projection

Add an Alembic-managed `image_artifact_references` table with:

- `id`, `image_artifact_id`, `asset_id`, `reference_role`, `ordinal`;
- asset checksum, filename, catalog version, selector version, selection reason, and fallback flag;
- unique `(image_artifact_id, ordinal)` and foreign-key protection to the image artifact.

Store the bounded visual brief, render mode, selected reference summary, and selector/prompt versions in
the immutable material-package `version_snapshot` and expose only safe projections through the existing
material-package response. Do not expose private absolute paths, MinIO object keys, temporary provider
URLs, raw prompts, or credentials.

The API schema gains typed `visual_brief` and `references` projections under the image/package detail.
The frontend adds a compact “视觉 brief / 使用的品牌素材” section next to the image and quality state;
it does not add a publishing action.

## 7. Validation and repair

The worker validates in this order:

1. visual brief schema, text limits, allowlist, selected asset status, checksum and request budget;
2. provider response and existing media/signature/dimension/download safety checks;
3. OCR exact-match check for the allowed editorial text layer;
4. image-topic and IP-adherence audit through a provider-neutral port when configured;
5. persist success or one targeted repair attempt;
6. persist `review_required` after a second failure.

Deterministic hard failures cannot be overridden by a model audit. A failed image never becomes
sendable, and the enterprise-WeChat dispatcher remains downstream of the package state.

## 8. Rollout and rollback

Add a feature flag for selector mode. With it disabled, the existing one-reference path remains
available for offline rollback. New prompt/pipeline/selector versions and fingerprints prevent new
requests from reusing the old generic image. Deployment rolls out in this order:

1. manifest/catalog code and tests;
2. domain brief and prompt assembly in fake mode;
3. provider multi-reference contract and migration;
4. worker/API/UI integration;
5. controlled live smoke and one real package.

If the provider rejects multi-reference input, keep the feature flag enabled only for the explicit
single-reference fallback and record that limitation; do not weaken output URL or SSRF policy.
