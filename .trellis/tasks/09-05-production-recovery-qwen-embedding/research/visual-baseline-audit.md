# Research: Local visual baseline versus production prepared drafts

- Query: Why do the current production illustrations lack fresh image-generation and source-news photos, and differ from the previous local outputs?
- Scope: Internal, read-only code/spec/artifact comparison. Production settings, database records and current media inspection belong to the main agent.
- Date: 2026-09-07
- Runtime reference: `.trellis/worktrees/weekly-source-preflight` (dispatched as runtime-identical to deployed `6154c78`; worktree includes later tests/evidence). No git operations, SSH, provider calls, source changes or draft changes were performed by this researcher.

## Findings

### 1. The production weekly exporter is not the polished V2 editor-handoff route

Below, `R/` means `.trellis/worktrees/weekly-source-preflight/`.

- `R/backend/app/official_account_weekly_dag_main.py:201` constructs `PreparedWeeklyDraftArtifactOwner` directly for the production handler registry. The identity comes from current settings at line 216. It does not instantiate `OfficialAccountEditorHandoffV2Service`.
- `R/backend/app/infrastructure/wechat_official_account/prepared_artifacts.py:132` checks the persisted run, article and draft. The admission condition at lines 135–145 checks live/ready, deterministic article validation, accepted text audit and ready simulation draft.
- At line 176 it uses `draft.resolved_html` directly, substitutes local media references and writes `article-body.html` at line 187. It does not use the V2 Xiaosai semantic renderer, V2 generated-visual gate, V2 release checks or exact mobile/browser acceptance. It also does not invoke the polished V10 local-review export.
- In contrast, `R/backend/app/application/services/official_account_editor_handoff_v2.py:297` loads generated visuals and evaluations, and lines 308–334 require a ready current V3 output for every body slot, exact block/reference lineage and a 1536×1024 JPEG. A catalog image placed directly cannot satisfy this V2 gate.
- Therefore successful automatic prepared-draft delivery proves transport and its narrower persisted text/media checks; it does **not** prove parity with the local V2 visual/layout acceptance contract.

### 2. Image generation is a distinct default-off per-article branch

- `R/backend/app/core/config.py:296` defaults semantic matching off, line 297 defaults article generated visuals off, and line 304 defaults image-quality observation off. Defaults are not a claim about live settings; the main agent must read those.
- `R/backend/app/infrastructure/official_account_runtime.py:38` includes generated plan/prompt versions in the run identity only for Zhipu text runs with `official_account_local_generated_visuals_enabled` true.
- `R/backend/app/official_account_worker_main.py:173` constructs the lazy image generator/store only when this flag is enabled; lines 197–213 wire the same flag and the separate image-provider/model identity into the executor.
- `R/backend/app/application/services/official_account_local.py:899` loads approved catalog candidates for current live multimodal-family articles. At line 1080 it selects the stored reference candidates. Only the conditional at line 1093 replaces them with newly generated outputs. If it is false, the body staging loop at line 1106 retains the selected source/catalog bytes.
- `_should_generate_body_visuals` at line 1371 requires the live run, flag and both persisted generated identities. Existing runs do not magically gain generated outputs when a flag changes. Identity/config mismatch fails closed at line 1378.
- Generated output per-slot provider intent is fenced and reusable; `_generate_body_visuals` at line 1397 is an explicit provider path, not the HTML renderer.
- Enabling requires the local worker and a configured image provider, and exactly one image attempt (`R/backend/app/core/config.py:744`). Image-quality observe additionally requires generated visuals (line 766).
- Existing supported generation providers are `disabled/fake/toapis/comfly`, with default generation model `gpt-image-2` (`R/backend/app/core/config.py:358`, line 363). This is distinct from Zhipu's text/vision reviewer configuration. Do not promise that setting GLM-5V-Turbo automatically supplies image generation, or silently enable a different image provider under a Zhipu-only vision instruction.

### 3. Source-news originals are persisted acquired media, not generated illustrations

- `R/backend/app/application/services/material_package.py:162` freezes at most two already-ready source images reachable through the package's exact evidence snapshot IDs. Empty/missing snapshot links return an empty tuple at line 181; ready originals are selected at lines 186–188 and saved as package links at line 216.
- `R/backend/app/infrastructure/db/official_account_local.py:1043` loads those package-linked `SourceArticleImageModel` rows, not arbitrary photos found during article writing. The query requires source status `ready` at line 1075.
- Metadata and original snapshot integrity/rights checks are at lines 1082–1097. Their provenance is explicitly `context_only_not_evidence=true` and `publish_permission_unverified`, with source URL/credit retained (lines 1107–1118).
- `R/backend/app/application/services/official_account_local.py:913` loads news-context candidates for the v5 news-context schema. The selector at line 659 takes at most two eligible items. At line 744, zero items is valid `not_present`; one item is `partial`, two is `ready`.
- Thus a ready article may legally have no original photos. The production exporter does not require photo availability. Determine absence from package links/source acquisition state, not from article generation capability or the upload count alone.
- Original photo means fetched source pixels; do not synthesize a news event photograph and describe it as original reporting.

### 4. The prepared exporter does not downsample JPEG/PNG

- `R/backend/app/infrastructure/wechat_official_account/prepared_artifacts.py:487` returns JPEG and PNG input bytes unchanged after decode/format validation (lines 488–490).
- Only WebP is decoded to RGB and encoded as JPEG at quality 90 (lines 491–500); it does not resize dimensions.
- This rules out automatic JPEG/PNG recompression in this specific exporter as a blanket explanation. Main should hash-compare current stored/prepared/uploaded items before attributing quality to WeChat or compression.

### 5. Real local baselines exist, but their generation histories differ

#### A. Durable V10 local run and polished review export (strong baseline)

Directory:

`output/official-account-local-v10-optimized-20260826-123151/live-local-review-55543c53-645eb99f42/`

- `README.md`: real live-local ready run `55543c53-c083-4789-8bc6-104ae538445a`, simulation/local-only, manual review pending, no public publication. Polished cover/context-caption export described explicitly.
- `manifest.json:126`: five body images; line 188: one CAS context image. At line 296 the selection identity is Alibaba `qwen3-vl-embedding`, 2048 dimensions. Selection status at line 313 is `semantic_ready`, with all five assignments `multimodal_embedding`.
- `manifest.json:320`: V10 schema/prompt/media/render/adapter versions. Manifest is the polished live-local-review bundle V3.
- `.trellis/workspace/LiYuchen/journal-1.md:1653`: Session 73 records completed V10 five-IP-visual workflow, selected-news image pipeline and real local provider acceptance on 2026-08-26, commit `a1b811d`.
- Actual image inspected in this research: `assets/body-00.jpg`. It is an integrated illustrated scene of the branded owl and a child discussing an observation, not a bare cutout/sprite placed into the article. This is qualitative inspection, not model scoring.
- Additional comparison files: `assets/body-01.jpg` through `body-04.jpg`, `assets/context-00.png`, `assets/cover-wide.png`, `preview.html`.
- Whole-page screenshots: `output/official-account-local-v10-optimized-20260826-123151/screenshots/preview-430.png` and `preview-320.png`.

#### B. News-IP v5/v6 pipeline: earlier explicit paid reference-conditioned scenes plus real news photos

- `.trellis/tasks/archive/2026-08/08-21-wechat-official-account-local-draft-mvp/research/v5-live-semantic-generation-preflight.md` records a completed V5 run with two Qwen3-VL embedding calls and two ToApis image successes, one attempt each. Three earlier generated scenes were inherited. The resulting five distinct JPEGs are 1536×1024; browser acceptance loaded all five at 320/430 with no overflow/external requests.
- `output/official-account-news-ip-editorial-news-context-20260825-v6/run.json`: five company-IP visuals plus two original context photos. The v6 export itself made zero image calls, inherited three pre-v5 plus two v5 calls, and used validated cached originals. This is an explicit distinction between original generation and later zero-provider re-export.
- Viewable examples: `output/official-account-news-ip-editorial-news-context-20260825-v6/assets/body-00.jpg`, `assets/news-00.jpg`, `assets/news-01.jpg` and `preview.html`.

#### C. V2 reference-conditioned source: local built-in generation, not production credentials

- `output/official-account-editor-handoff-v2-reference-conditioned-source-20260827/README.md`: three newly generated scenes conditioned on three approved references; fixture semantic selection, no embedding call claimed; explicitly authorized local built-in image generation.
- Its `visual-map.json:9` records `kind=built_in_imagegen_reference_conditioned`, `provider_call_claim=authorized_local_generation_completed` and `image_generation_calls=3`.
- Viewable files: `assets/body-00.jpg` through `body-02.jpg` and approved `references/reference-00.jpg` through `reference-02.jpg`.
- Do not call this proof that the server has the same built-in image capability or that an OpenAI account was used in production. It is a distinct historical local asset creation path.

#### D. Later local weekly V2 acceptance also contains deterministic composites

Directory:

`output/official-account-weekly-live-theme-clusters-acceptance-20260831/official-account-weekly-edition-c6177340787557db/`

- Root `README.md`: three finalized V2 children. This live-local execution fetched source pages/photos but made zero model/embedding/image-generation/WeChat/WeCom calls.
- `articles/01-official_anchor/body-visuals.json:7`: `generation_kind=frozen_reference_conditioned_fixture`; at line 18 `provider_execution=not_claimed`, reference catalog `weekly-local-approved-ip-compositor-v1`, and selection `deterministic_fixture_semantic`.
- Actual image inspected: `articles/01-official_anchor/assets/body-00.jpg`. It is a designed composite: child/science-scene background and a large framed area with both approved 3D character cutouts. It is not a newly generated model image in this weekly run.
- Other useful files: per-role `preview.html`, `assets/context-00.jpg` (application uses PNG), `body-visuals.json`, `placements.json`, `mobile-validation.json`.
- Do not state that every attractive previous local weekly artifact called an image model for each new article. The local assets/rendering were prepared differently, and some reused/composited already-created art with stronger layout checks.

## Files Found

- `R/backend/app/infrastructure/wechat_official_account/prepared_artifacts.py` — current production draft admission and byte-preserving export.
- `R/backend/app/official_account_weekly_dag_main.py` — production registry selects the prepared-artifact route.
- `R/backend/app/infrastructure/official_account_runtime.py` — persisted generated identity controlled by settings.
- `R/backend/app/official_account_worker_main.py` — lazy actual image provider construction.
- `R/backend/app/application/services/official_account_local.py` — catalog versus generated branch and optional context selection.
- `R/backend/app/infrastructure/db/official_account_local.py` — stored source-news context candidates.
- `R/backend/app/application/services/material_package.py` — immutable package linkage to acquired originals.
- `R/backend/app/application/services/official_account_editor_handoff_v2.py` — stricter V2 generated-body gate absent from prepared route.
- Local output directories above — preserved real comparison images, manifests, previews and provenance.

## Related Specs

- `.trellis/spec/backend/official-account-editorial-repackage.md:697` — exact V10 five-generated-scene/news-context and polished local-export contract.
- `.trellis/spec/backend/official-account-editor-handoff-v2.md` — default-off development-only V2 route, ready generated-body gate, semantic layout and exact mobile proof.
- `.trellis/spec/backend/official-account-weekly-edition.md:216` — role-distinct offline fixture visuals, truthful non-provider execution and acquired news provenance.
- `.trellis/spec/backend/index.md` — package index and persisted media/source/social boundary.

## External References

None fetched. This question is answerable using installed project code, preserved local artifacts and live operational evidence from the main agent. No current external API capability claim is made.

## Caveats / Not Found

- This researcher has not read current production settings, queried current production runs or downloaded the current prepared media; that independent work is owned by the main agent. Defaults and code paths alone do not establish current counts.
- User did not identify one exact earlier local bundle; several truthful baselines are documented instead of conflating them.
- Historical V10 manifest exposes semantic selection and output artifacts but not the complete generated-provider call ledger. Use the journal/spec as historical acceptance support, or a bounded existing ledger read if exact V10 provider/count is needed. V5/v6 and V2-source call histories are explicit.
- No new model score, human annotation, public release permission or visual equivalence certification is claimed.
- Recommended direction, not performed here: align production with a selected local visual baseline, explicit generation/semantic configuration and photo-availability policy, plus an enforceable visual/layout gate before draft enqueue; produce a new preview/run identity rather than mutate immutable previous records.
