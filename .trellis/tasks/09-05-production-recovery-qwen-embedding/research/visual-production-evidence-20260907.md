# September 7 production visual-quality diagnosis

Evidence collected on 2026-09-07, approximately 10:53–11:04 Asia/Shanghai. This is
a read-only diagnosis, not a completed visual-quality repair. No new model call,
configuration change, deployment, draft replacement or public publication was made.
Local comparison and code references are in `visual-baseline-audit.md`.

## Actual article and provider evidence

Production runtime: immutable release `6154c78f1c5f19cb0650f75df730e5d9c854647b`.
The inspected prepared batch is
`4d25b6c7c81055c101101100d18682d3aedf61d52228d662710b397b422248c5`.

| Role | Article run | Catalog body images | Source-news images | Upstream generated cover |
| --- | --- | ---: | ---: | ---: |
| official_anchor | `85f62fb9-0e96-4a9e-95c0-48a99043fdd3` | 5 | 0 | 1 |
| industry_trend | `24ad4ddc-7c1e-46e3-a787-acff86a1f102` | 5 | 0 | 1 |
| application_case | `1c8a0cc8-b960-4b33-82ff-e7204def40f6` | 5 | 1 | 1 |

- Read the actual article worker's allowlisted settings, not only Compose defaults:
  `official_account_local_generated_visuals_enabled=false`,
  `official_account_local_visual_semantic_enabled=false`,
  `image_quality_eval_mode=off`, `image_quality_audit_enabled=false` and
  `image_ocr_enabled=false`.
- All three persisted version bundles have null generated-visual plan and prompt
  identities. Each article has one successful Zhipu / `glm-5.2` text-generation
  attempt and one successful text-audit attempt. There are no `visual_generation`
  attempts, generated-body records or generated-visual evaluation records for
  these runs. This is a disabled branch, not a failed image-provider request.
- All 15 body descriptors say `source_kind=approved_catalog` and
  `selection_method=deterministic_tag`. There are only seven distinct body-image
  checksums across the batch; 11 assignments have `selection_reason_code=stable_fallback`.
- Do not claim there was no image generation anywhere: all three covers reference
  earlier successful material-package image artifacts, provider `comfly`, model
  `gpt-image-2`, one attempt each, 1024×1024 PNG. Their creation dates are August 31,
  September 2 and September 7. Article production reused them; this investigation
  did not invoke that provider.

## Pixel-level inspection

Copied the exact prepared batch into a fresh diagnostic directory:
`/var/tmp/edu-ai-visual-audit-20260907.wys2Nj/`.
The source files remain unchanged. JPEG/PNG export is byte-preserving in the
prepared adapter; this inspection did not retrieve WeChat's post-upload bytes,
so no downstream compression equivalence is claimed.

- `articles/01-official_anchor/assets/body-1.jpg` is a bare flat owl avatar,
  **281×276**, 9,915 bytes. Checksum:
  `f54a792151babee7761d4f52e800d0bd07739304c1cfd07ce0d40966187c16d9`.
  It appears in all three articles. The HTML uses `width:100%;height:auto`, allowing
  a small avatar to occupy the full body-image slot rather than an editorial scene.
- `articles/02-industry_trend/assets/body-0.jpg` is a 1536×1536 plain-background
  two-character catalog image. It lacks a scene specific to the article's news.
- Official article title: “电池技术正在重塑孩子未来，家长如何引导科学探索”. Its
  `assets/cover-0.png` visibly says “具身智能 / 看见机器人如何感知与行动”. This is a
  concrete article/cover topic mismatch, despite the cover itself being generated.
- `articles/03-application_case/assets/context-0.png` is a 1004×620 source-news
  composite, unchanged from the acquired image checksum
  `815f1c8f352aa0da0a33c7e7df87c8c7437580b2072864c49644ea0b7f32ed8a`.
  It is not a newly generated news photo.
- Inspected local V10 `output/official-account-local-v10-optimized-20260826-123151/`
  `live-local-review-55543c53-645eb99f42/assets/body-00.jpg`: a 1536×1024 integrated
  illustrated scene showing the branded character with a child and science
  observations. This qualitative comparison is not a model score or human label.

## Why two articles have no original news photos

Queried package-source-image links and source-image records for the exact evidence
candidates, then read and checksum-verified the original stored HTML snapshots
from private object storage. Re-ran only the pure installed extractor; no news
page/image fetch or acquisition job was triggered.

| Package | Stored source | Selected body root | Body image nodes | Approved extracted image references | Package image links |
| --- | --- | --- | ---: | ---: | ---: |
| `5ca4d0ba-5234-4c96-9bfd-f453617d50a7` | Government news, battery industry | `.pages_content` | 0 | 0 | 0 |
| `d6c1825a-c022-4db7-bc3c-40debfa8ce2d` | Government news, China–ASEAN Expo | `.pages_content` | 0 | 0 | 0 |
| `198969a7-056d-482b-81f4-8219cbd2106b` | Science and Technology Daily, science centers | `.content` | 1 | 1 | 1 |

The two Government pages each contain 16 page-level image nodes and one Open Graph
image entry, but none inside the selected news body and none admitted by source
image policy. These must not be counted as 16 missing editorial photos. The
article builder only uses already-linked ready source images; zero is permitted.
There is no evidence here of a news image being lost between article and draft.

Stored HTML checksums respectively:

- `cf08c635acd6df6b4f20dd8ebf8b1860ea308cba8e2518fab4572f9eb3214ad1`
- `e30f6475e7db7d7915be30cb2e8383b85471a506281891888bd38920eddabb66`
- `329fe8071d2d5dd368ba986145afd06d40c01fa8a92bdae3a5f095e407570f8d`

The existing original remains marked `publish_permission_unverified` and
`context_only_not_evidence=true`. Draft acceptance is not publication permission.

## Diagnosis and bounded next change

The prior recovery verified draft delivery, not visual parity with the local
acceptance artifacts. Production preserves a catalog-only body configuration and
uses the simpler prepared exporter, not the polished V10/V2 editor-handoff path.
Text audit and upload success therefore allowed low-resolution avatars, repeated
generic art and an unrelated cover. This is a configuration/integration and
acceptance-gap diagnosis, not proof that a generation model's quality regressed.

Proposed, not executed:

1. Select an explicit local baseline and align production's generated scene,
   reference selection, cover, captions and mobile layout with it. Enabling one
   boolean alone is insufficient: live `image_max_attempts=3`, while the current
   generated-body configuration contract requires exactly one attempt.
2. Add pre-draft checks for usable resolution, image role, cross-article repetition,
   article/cover and section/scene relevance. Wire the user-selected Zhipu vision
   review path separately from the image-generation provider; no new provider
   authorization is implied by choosing GLM-5V-Turbo for judging.
3. Retain real source photos when available and properly attributed; when absent,
   record absence or select another approved source, never fabricate news originals.
4. Validate one fresh preview before creating replacement drafts. Preserve old run
   identities, failure history and existing drafts unless replacement is approved.

Some attractive historical local exports reused previously generated or composed
assets and made zero new image calls. Do not equate every local export with a
fresh generation run, or claim the server has the local built-in image tool.
