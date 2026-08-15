# 配图受控多样性 v2 — Technical Design

## 1. Architecture outcome

The current one-profile-per-category image path becomes a deterministic, history-aware visual
planner while preserving the existing provider, private catalog, one-image artifact, material
package, and delivery boundaries.

```text
accepted independent copy + governed topic/slot identity
    -> bounded topic visual signals
    -> recent seven-day diversity snapshot (PostgreSQL)
    -> short locked reservation + controlled visual-plan selection
    -> v2 VisualBrief + approved reference reservation
    -> v3 brand prompt assembly
    -> provider call outside transaction
    -> media/integrity/OCR/identity checks
    -> deterministic perceptual comparison with recent successful images
       -> distinct: persist final image
       -> near duplicate on attempt 1: use reserved alternate plan once
       -> near duplicate on attempt 2: persist safe image + diversity_warning
    -> independent material package and existing delivery lane
```

The planner is stateful only through an explicit, bounded PostgreSQL history projection. Pure
domain functions still own eligibility, scoring, relaxation order, tie-breaks, fingerprints, and
similarity calculation.

## 2. Version bundle

Use new explicit versions rather than changing v1 behavior in place:

- `visual-brief-v2-controlled-diversity`
- `visual-diversity-policy-v1`
- `brand-visual-selector-v2-novelty`
- `image-prompt-v3-controlled-diversity`
- `image-pipeline-v3-controlled-diversity`
- `image-perceptual-hash-v1`
- `image-similarity-policy-v1`

Stored v1 prompt/brief/selector/pipeline versions dispatch to the historical code path. New
defaults remain behind one master feature flag until migration, replay, fixture calibration, and a
bounded live acceptance are complete.

## 3. Controlled visual vocabulary

### 3.1 Plan dimensions

Add immutable enums/value objects for:

- `scene_variant`: at least science lab, AI control room, robotics workshop, classroom demo,
  competition arena, maker space, observatory, space station, field expedition, science library,
  museum/exhibition, and project studio;
- `composition_variant`: at least subject hero, character-left/editorial-space,
  character-right/editorial-space, duo dialogue, over-shoulder observation, tabletop experiment,
  isometric environment, and staged discovery path;
- `camera_variant`: close, medium, wide, top-down, and restrained low/isometric angle;
- `character_cast`: Xiaosai solo, Sai Xiansheng solo, or approved duo;
- `slot_tone`: morning clear/energetic, noon explanatory/structured, evening reflective/deep;
- `subject_variant`: a finite topic-matched object vocabulary such as robot arm, AI network,
  telescope, spacecraft, microscope, experiment vessel, science book, competition project,
  classroom model, and outdoor observation kit.

The vocabulary is not a Cartesian free-for-all. A compatibility table declares which scenes,
subjects, compositions, cameras, casts, and slots can combine. At least three compositions remain
eligible per slot. Invalid combinations fail before provider use.

### 3.2 Safe topic mapping

Extend `AcceptedVisualContext` with safe identifiers and projections already stored by the
pipeline: content slot, business date, selected event/version ID, editorial cohort/product
directions, and bounded governed entity/category IDs. Do not pass raw evidence or unrestricted
model prose into the planner.

Map those signals to the finite subject/scene vocabulary through deterministic alias rules. The
generic category remains a fallback, not permission to invent a specific robot, institution,
person, result, or product claim.

### 3.3 Stable brand layer

Every plan retains:

- approved Sai Xiansheng/Xiaosai identity rules;
- polished 3D cartoon rendering;
- deep science blue, clean white, and restrained orange accents;
- no real child face, QR code, invented logo, promotional promise, or unrestricted text;
- one compact three-level text group in a deep-science-blue rounded card with one restrained
  orange accent: exact brand signature `赛先生科学`, one allowlisted category title, and one
  allowlisted category subtitle, in that order;
- reserved editorial placement that never covers a face, scientific object, or main action;
- exact OCR equality with those three lines and no keywords, historical long brand-value line,
  fourth line, pseudo-text, or model-authored/source-authored prose.

Identity references are exempt from novelty penalties. Action/style references and plan
dimensions are novelty inputs.

## 4. Diversity planning and relaxation

### 4.1 History projection

Load only the last seven local business dates of successful/reserved v2 plans, bounded by a
configurable hard maximum. Project IDs, plan enums, reference asset/variant IDs, slot/date,
fingerprints, hashes, and safe outcomes; never load image bytes or prompts.

### 4.2 Ranking

For each topic, enumerate only compatible plan candidates and compute an explainable tuple:

1. topic/subject relevance;
2. slot affinity;
3. full-plan novelty;
4. scene novelty;
5. composition novelty;
6. camera novelty;
7. cast novelty;
8. action/style reference novelty;
9. stable hash tie-break over policy version, event version, copy run, business date, and slot.

Product relevance and slot affinity can order compatible plans but cannot authorize an unsupported
visual subject. The selected primary and alternate plans are both persisted before a provider
call. The alternate must differ in composition and at least one of scene, camera, cast, or action
reference.

The v2 artifact/package request fingerprint includes the ordered primary and alternate plan
fingerprints, their ordered approved reference checksums, the bounded history-snapshot digest, and
all diversity/similarity versions. A retry with the same reservation returns the same artifact;
history changing after reservation cannot silently replace its plans.

### 4.3 Hard and soft repetition rules

- Hard: no identical complete-plan fingerprint among siblings in the same business date/slot.
- Hard: primary and alternate plans for one artifact cannot have the same complete-plan
  fingerprint.
- Initial seven-day preference: exclude repeated complete plans and prefer unused action/style
  variant groups.
- Controlled relaxation: camera -> cast -> composition -> scene/action reuse, in an explicit
  versioned order, while preserving same-slot sibling uniqueness and topic compatibility.
- Identity reference reuse is always permitted.
- Every relaxation emits a bounded reason code; no random retry loop is allowed.

## 5. Persistence and concurrency

Create Alembic `0021` and matching SQLAlchemy models for a durable visual-diversity reservation and
attempt audit. Exact column/table names may be refined during implementation, but the following
relational contract is required:

### 5.1 Artifact additions

`image_artifacts` receives nullable/default-compatible v2 fields:

- diversity/similarity policy versions;
- selected final plan fingerprint and selected attempt ordinal;
- perceptual-hash version/value;
- bounded closest-distance result;
- `diversity_retry_count` constrained to 0--1;
- nullable bounded `diversity_warning` code (`near_duplicate_after_retry`), with null meaning no
  warning;
- a safe JSON similarity summary with an object-shape check.

Legacy rows retain null/default values and unchanged API semantics.

### 5.2 Plan reservations

A reservation row links one image artifact/copy origin to business date, timezone, slot, policy,
primary/alternate ordinal, complete plan fingerprint, scene/composition/camera/cast/subject enums,
reference combination fingerprint, relaxation codes, and timestamps. Composite uniqueness binds
attempt ordinal and prevents same-slot sibling duplicate fingerprints.

Reference rows become attempt-aware (legacy default ordinal 1) or gain an equivalent child table,
so the primary and alternate approved reference sets are both auditable. The final package/API
projects only the selected attempt by default while retaining both attempts internally.

### 5.3 Short reservation transaction

Use a PostgreSQL transaction-scoped advisory lock with a fixed application namespace, or an
equivalent explicitly tested lock row, around:

1. bounded recent-history read;
2. primary/alternate plan and reference selection;
3. artifact/package/reservation/reference insertion.

Manifest parsing may happen before the lock, and reference bytes/provider calls/MinIO operations
must happen after commit. A uniqueness conflict retries only the short reservation calculation;
it never repeats a provider side effect.

## 6. Prompt and provider attempts

The v3 prompt includes the selected finite scene, composition, camera, cast, slot tone, and subject
while preserving the exact controlled text hierarchy. The brief builder owns the six finite
category title/subtitle pairs; prompt assembly and provider-rejection recovery may only project
that allowlist. OCR reads the same helper so prompt and post-generation validation cannot drift.
Raw headline/copy, keywords, the v1 long brand-value phrase, and private metadata remain excluded.
The v1 builder and metadata serialization do not gain an empty signature field. Enabling the
controlled bundle requires exact image OCR at settings validation; a deployment cannot silently
activate v2 planning while leaving the three-line output gate disabled.

Attempt 1 uses the primary reserved plan. If deterministic similarity marks it near-duplicate,
discard its transient raster after recording only safe hash/distance/attempt metadata, derive a new
provider-request fingerprint from the artifact plus alternate-plan fingerprint, and call the same
provider/model once with the alternate reserved plan. This is separate from network retry and
from the existing safety/OCR repair budget; no path may exceed the reviewed total call bounds.

The selected final attempt owns the persisted MinIO raster, final references, and effective brief.
The first near-duplicate attempt does not become a second material package or a deliverable image.

## 7. Perceptual similarity

Implement a deterministic Pillow-based perceptual hash after signature/dimension validation and
before MinIO persistence. The exact algorithm, normalized raster preparation, hash width, distance
threshold, and comparison rule belong to `image-perceptual-hash-v1` /
`image-similarity-policy-v1`.

The policy compares against a bounded last-seven-day set of successful hashes:

- exact SHA-256 match always means duplicate;
- perceptual near-duplicate requires the calibrated distance rule;
- null legacy hashes are skipped rather than backfilled with invented values;
- nearest distance, threshold, candidate count, match boolean, and policy version are persisted;
- thresholds are settings with strict safe bounds but production defaults cannot be chosen until
  the fixture matrix passes.

Attempt 1 near-duplicate selects attempt 2. Attempt 2 near-duplicate plus all other quality gates
passing produces a succeeded artifact with
`diversity_warning=near_duplicate_after_retry`; it never becomes a hard veto,
third provider call, or automatic-delivery block.

## 8. API and local frontend

Add backward-compatible optional fields to material-package image/detail responses:

- safe plan labels (slot tone, scene, composition, camera, cast, subject);
- diversity and similarity policy versions;
- diversity retry/warning status;
- near-duplicate boolean and bounded distance/threshold values;
- safe relaxation reason codes;
- selected reference display names already allowed by the current projection.

Do not expose plan seeds, private paths, full prompts, raw hashes if not needed, nearest private
object identity, or provider bodies. The local-only material detail UI may display a compact
“visual variation” section; it remains outside production deployment and still passes the frontend
quality gate.

## 9. Settings, rollout, and rollback

Add bounded settings shared by API/content scheduler/content worker/Doctor as required:

- master diversity flag, default false;
- policy/brief/prompt/pipeline/selector/similarity versions;
- lookback days fixed/default seven with a bounded range;
- maximum history rows;
- calibrated perceptual threshold;
- maximum diversity regeneration fixed at one.

Rollout order:

1. migrate to 0021 while the feature remains disabled;
2. validate historical replay and current catalog coverage;
3. run fake-provider and PostgreSQL concurrency/replay gates;
4. capture production baseline and backup;
5. with separate authorization, generate at most one live candidate and inspect identity/topic/
   variation quality without Enterprise WeChat delivery;
6. enable consistently across required services and observe seven-day metrics.

Rollback disables the master flag and restores the v1 version bundle. New audit rows remain
readable; successful v2 artifacts/packages are not deleted or rewritten.

## 10. Observability and security

Emit safe structured events and Doctor/evidence counts for plan reservations, relaxation reasons,
attempt-1 similarity retry, attempt-2 warning, distinct plan ratio, repeated-plan count, dominant
non-identity reference share, and provider call count. Logs contain no prompts, reference bytes,
credentials, object keys, or raw provider responses.

The seven-day activation review compares the current baseline with:

- distinct full-plan ratio;
- scene/composition/camera/cast coverage;
- exact/near-duplicate rate;
- similarity retry and warning rate;
- dominant action/style reference share;
- image success, provider failure, latency, and cost deltas.

These are observation metrics, not fabricated resume numbers; report only measured results.
