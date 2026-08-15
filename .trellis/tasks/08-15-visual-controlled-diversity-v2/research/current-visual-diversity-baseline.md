# Current visual-diversity baseline

## Inspection date and boundary

- Inspected on 2026-08-15 Asia/Shanghai.
- Repository inspection was read-only. The production query was read-only and returned only safe
  aggregate configuration, counts, categories, scenes, reference roles, and private asset
  basenames. It did not return prompts, image bytes, object keys, credentials, or provider bodies.
- Current production image path: Comfly / `gpt-image-2`, prompt `image-prompt-v1`, pipeline
  `image-pipeline-v1`, selector `brand-visual-selector-v1`, selector enabled, at most three
  references.

## Ten-day production baseline

| Metric | Result |
| --- | ---: |
| Successful image artifacts | 23 |
| Distinct final SHA-256 values | 18 |
| Distinct `visual_brief_snapshot` values | 4 |
| Distinct categories | 4 |
| Distinct scenes | 2 |
| Distinct main actions | 4 |
| AI / science-lab images | 10 |
| Generic science / exploration-space images | 8 |
| Experiment / science-lab images | 3 |
| Robotics / science-lab images | 2 |
| Uses of one repeated action reference | 13 |
| Successful style-reference uses | 0 |

The 23 outputs are not all byte-identical, but the plan space is visibly much narrower than the
output count. Five successful artifacts repeat an existing final SHA-256, and over half of the
sample uses the same action reference.

## Code-level causes

1. `backend/app/domain/visual_brief.py` defines six finite profiles. Each category maps to exactly
   one learning goal, scene, main action, title, learning line, keyword tuple, both-character cast,
   and fixed 3D square composition instruction.
2. `build_visual_brief` returns that category profile rather than a topic-specific visual plan.
   Different articles in the same category therefore receive the same safe visual semantics.
3. `backend/app/domain/visual_assets.py` ranks primarily by category/topic/tag score and human
   priority. The run UUID seed is a late stable tie-breaker, so it cannot rotate a clearly higher
   scored asset.
4. The selector has no durable recent-use input. It cannot know that a scene, action asset,
   composition, camera, or complete plan was used yesterday.
5. The current brief always requires both characters. With a three-reference budget, identity
   coverage commonly consumes two positions and leaves one repeated action reference; no style
   reference appeared in the ten-day successful sample.
6. The current output validator checks media integrity, dimensions, OCR, and optional model audit,
   but it does not compare a new raster with recent successful images.
7. `selection_seed=str(copy_run.id)` makes a replay deterministic, which is correct for
   idempotency, but determinism alone does not create bounded novelty.

## Constraints preserved by the new design

- Brand identity and 3D style remain stable; identity references may repeat.
- Topic/evidence truth remains upstream and cannot be invented for visual novelty.
- Provider calls remain outside database transactions.
- Every independent slot selection keeps its own copy run, image artifact, package, and delivery.
- New planning and similarity decisions must be deterministic, versioned, private-path-safe, and
  replayable.
- A near duplicate is a soft quality condition. It permits one alternate-plan generation; a safe
  second result remains deliverable with `diversity_warning`.
- Historical v1 artifacts and packages remain readable and never receive fabricated v2 metadata.

## Calibration requirement

Do not choose a perceptual-hash distance threshold from intuition alone. Build a controlled
fixture matrix containing exact copies, re-encoded/resized copies, small color/lighting changes,
same-character/same-layout variants, same-character/different-scene variants, and clearly
different compositions. Version the algorithm and threshold only after this matrix separates the
intended positive and negative cases without weakening media, OCR, or identity checks.
