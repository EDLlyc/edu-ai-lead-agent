# Research: Isolated fresh visual preview using existing article snapshots

- Query: Smallest reusable route to create five paragraph-conditioned scenes, a matching cover, Zhipu GLM-5V-Turbo visual review and a polished mobile preview from one ready September 7 article, without changing current drafts or old article rows.
- Scope: Internal code/spec research; no provider, SSH, database, git or runtime operations.
- Date: 2026-09-07
- Runtime code prefix `R/`: `.trellis/worktrees/weekly-source-preflight/`.

## Findings

### Recommended architecture: snapshot in, preview-only artifact out

Use one small additive operator runner with two phases:

1. Main obtains an allowlisted, read-only snapshot of one ready run: exact Article Package, article/render IDs and fingerprints, accepted text-audit/validation identity, five existing approved reference records/bytes, original context snapshot/media/bytes. Serialize a fresh immutable source directory with a SHA manifest. Preserve the Article/evidence/source-photo bytes unchanged.
2. An isolated runner takes only this snapshot, explicit configured image-generation capability, explicit Zhipu `glm-5v-turbo` judge and a fresh output directory. It creates five new body scenes with one fenced request per slot, a crop derived from the most appropriate accepted scene as the new cover, checks all final assets, renders a V2-style local preview and performs exact mobile acceptance. It has no queue, WeChat client, inbox writer or old-run database mutation capability.

This is smaller and safer for the approved first sample than enabling a production worker flag or invoking the ordinary live CLI. It produces a **new preview identity with source-run lineage**, not a claim that the old durable article run generated these images or that a new production release has passed.

### Existing commands are useful as read-only sources, not fresh-visual preview runners

- `R/backend/app/official_account_local_cli.py:57` provides `fixture`, `live`, `export`.
- `live` calls `repository.enqueue_material_package` at line 122 and waits for normal worker execution; it does not preserve the existing exact Article. Do not use it for the frozen-article sample.
- `export --run-id ... --allow-live-local-export` calls the read-only export path at line 182, loads existing ready snapshots and verifies media. It makes no models calls, but exports existing media only; it cannot itself replace five images and cover.
- `R/backend/app/official_account_news_editorial_semantic_generated_demo.py:926` has a local filesystem-intent/failure/publish pattern for generation. It is pinned to an older frozen article and two slots, so reuse the bounded orchestration idea, not its fixed source/selection assumptions or private helpers wholesale.
- `R/backend/app/official_account_editor_handoff_v2_demo.py` builds a deterministic fixture from frozen reference-conditioned images and a pinned article. It should not be run unchanged on a real source or relabeled as a fresh production run.
- The 120-call panel command `backend/app/image_quality_panel_main.py` exists only in dirty main here and belongs to a frozen evaluation experiment. It is not the minimal five-image sample judge.

### Generation building blocks already available in the release tree

`R/backend/app/application/services/official_account_visual_generation.py`:

- `select_generated_visual_block_anchor` at line 71 selects the first substantial exact readable block in each assigned section and computes its fingerprint. No language model is needed to rewrite the source article.
- `build_generated_visual_prompt` at line 121 carries the exact topic/section/block as untrusted content, requires the approved visible IP protagonist, scientific/education context, 3:2 digital-gouache style and no lettering/logo/QR/watermark.
- `plan_generated_body_visual` at line 182 takes transient `StoredOfficialAccountArticle`, `StoredOfficialAccountRender`, ordinal 0–4, approved `OfficialAccountSourceMedia`, provider/model and reference bytes. It validates normalization and fingerprints the exact block, reference, output profile and prompt hash.
- The plan accepts a caller-supplied preview UUID; it does not itself write to the database. Preserve source article/render IDs as provenance and make the preview identity distinct.
- `prepare_generated_visual_result` at line 336 validates provider/model/request identity and produces metadata-free 1536×1024 JPEG publication bytes. The judge must inspect these **final** bytes, not only the raw provider image.

`R/backend/app/application/ports/image_generation.py`:

- `ImageGenerationRequest` carries the bounded prompt, typed `ImageReference` entries and request fingerprints.
- `ImageGenerator.generate` is the existing provider-neutral seam; `create_image_generator` in infrastructure can construct the authorized configured ToApis/Comfly adapter.
- Do not substitute a different model silently. Generation provider and image judge are separate capabilities; Zhipu GLM-5V-Turbo is the requested judge here.

Reference selection for this first sample:

- Reuse current approved source/reference bytes after manifest/checksum verification, retaining the real selection method. A generation prompt still binds each scene to the article even if the old selection was deterministic.
- If replacing references to improve identity consistency, do it explicitly within the preview plan with approved public references and honest `deterministic_tag` selection. Do not report `multimodal_embedding` unless that actual selector ran.
- Do not make paid Qwen embeddings a hidden dependency of the sample; production semantic unification can be separate once the visual output is accepted.

### GLM-5V-Turbo judge: reuse port, selectively bring in the right request profile

- Release already contains `ImageQualityAuditRequest`, `ImageQualityAuditResult`, `ImageQualityAuditor` in `R/backend/app/application/ports/image_validation.py:67–132`.
- Release `OpenAICompatibleImageQualityAuditor` in `R/backend/app/infrastructure/ai/image_validation.py:319` sends final image plus typed reference data and strictly parses only accepted/bounded issue codes. It enforces returned model identity. The compatibility-protocol class name does not imply the request is sent to OpenAI.
- **Release factory gap:** `R/backend/app/infrastructure/ai/factory.py:265` uses `settings.ai_chat_model` for vision. On current production this would select the text model, not an independent GLM-5V-Turbo judge. `image_quality_audit_model` exists in dirty main (`backend/app/core/config.py:449`), not release.
- **Release request-profile gap:** release uses one generic JSON-object profile with `response_format` and temperature. Dirty main has an explicit `_VisionRequestProfile.ZHIPU_VISION` at `backend/app/infrastructure/ai/image_validation.py:241` using `thinking={type:disabled}` and `do_sample=false`, while preserving the separate OCR JSON profile. Audit selects it at line 397.
- Dirty main regression `backend/tests/unit/test_image_validation_ai.py:251` checks the exact audit payload keys, disabled thinking, deterministic sampling and absence of `response_format`; existing OCR regression keeps JSON-object behavior.
- Smallest coherent adaptation: selectively port the Zhipu audit request-profile fix plus focused tests into the chosen isolated worktree, then explicitly construct the auditor with model `glm-5v-turbo` and the existing Zhipu credentials/endpoint. Keep text generation settings unchanged. Do not wholesale copy dirty main or route through a model panel.
- The adapter returns protocol provider label `openai-compatible`; preview ledger should also record the configured/validated route owner `zhipu`, requested/returned model and safe endpoint identity, so user-facing evidence does not falsely imply an OpenAI provider.
- Set provider `max_attempts=1`, bounded timeouts/input/output, and local exclusive judge intents. A missing result remains unknown/unavailable, not pass, and must not silently issue another request.
- Reuse final-output criteria from `R/backend/app/application/services/official_account_local.py:1719` (semantic match, character identity, no text, defects, layout). Current criteria truncate scene context to 120 characters; for preview, use bounded complete important scene context while respecting the port's 200-character-per-criterion limit and eight-criterion maximum.

### Review semantics and the actual gate

- The existing `IMAGE_QUALITY_EVAL_MODE=observe` is explicitly evidence-only; it must not be silently redefined into enforcement. See `.trellis/spec/backend/image-quality-evaluation.md:30`.
- Define a new preview acceptance policy, separate from production observe. It may require five final body-image audits and one final cropped-cover audit to be available and accepted, then mobile checks, before marking the **preview** accepted.
- `ImageQualityAuditResult` is accepted plus bounded issues, not a numeric scoring rubric. Do not fabricate 0–100 scores or call model output human labels.
- Reuse closed issue mappings and `build_image_eval_issue`, `build_image_eval_observation`, `decide_image_eval_batch`, `active_image_eval_rubric` from `R/backend/app/domain/image_quality_eval.py`. Warnings/unavailable should remain review-needed rather than being silently accepted.
- Per-image assessment cannot prove batch diversity. Five distinct hashes are deterministic evidence against exact duplication, not semantic diversity. Explicitly inspect the five-scene series or add a separate bounded batch review if later requested.
- Do not backfill the old ready generated-visual tables with paid audit calls; sample ledger is isolated and truthful.

### Cover: derived from a new relevant scene, independently reviewed

- Prefer an accepted generated scene that represents the article's main message, then derive a wide 2.35:1 cover. This requires five generation requests total, not necessarily a sixth cover-generation call.
- Existing crop helper `R/backend/app/application/services/official_account_editor_handoff.py:605` safely keeps already-wide images or produces a top-biased/centered crop, with max raster checks. V10 export also has `_export_cover_asset` at `official_account_export.py:1529` with crop provenance.
- Both helpers are private; either extract a tiny public reusable seam with tests or implement the preview cover policy explicitly under its own version without relabeling a changed policy as the old helper's identity.
- Record source generated SHA, final cover SHA, dimensions and crop box. Check the **final crop** with the requested judge; body acceptance alone does not prove the cropped face/action survived.
- A deterministic crop is not another image-generation call. Do not reuse the unrelated original cover just because it has a valid ratio.

### Render: reuse V2 pure renderer, do not fake a durable V2 release

- `R/backend/app/domain/official_account_editor_handoff_v2.py:508` exposes `render_editor_handoff_v2_body(article, media)`. It supports up to five body slots by ordinal, safe local media, semantic emphasis, Xiaosai component layout and block-bound source-photo placements. It does not depend on provider or database state.
- `EditorHandoffMediaAsset` is in `R/backend/app/domain/official_account_editor_handoff.py:146`: safe relative asset path, SHA, dimensions, body/context/cover role, original source/credit/rights fields. Supply freshly generated media with the existing article's section/slot bindings and original context metadata/bytes.
- The helper `_build_media_assets` in `application/services/official_account_editor_handoff.py:472` demonstrates strong snapshot/media validation but is private and expects original article alt/context consistency. A preview can make presentation-only alt/caption overrides explicit without mutating the frozen source Article.
- **Important contract trap:** `build_editor_handoff_v2_artifact` at `application/services/official_account_editor_handoff_v2.py:625` requires `EditorHandoffRelease` and `BodyVisualLineage`. The latter currently distinguishes only frozen fixture and persisted durable output (`domain/official_account_editor_handoff_v2.py:214–265`). A new filesystem-only provider run should not be falsely labeled a fixture or a database-persisted result, nor given fabricated manual approval.
- Minimal solution for this sample: a new `visual-preview-v1` manifest around the pure V2 renderer with source article identity, actual local provider ledger, no social readiness/release claim and `published=false`. Keep `article.json`/evidence/source snapshots unchanged, and record new presentation/media mappings separately.
- A complete durable V2 production rollout can subsequently add explicit local-preview lineage or persist a genuinely separate derived visual run under reviewed contracts. It is not required merely to show the first isolated sample.
- `ReviewBundleInput`/`export_live_local_review_bundle` is another available read-only renderer/exporter, but it assumes persisted media/resolved lineage. Passing fake old run hashes with replaced images violates those assumptions; do not abuse it to pretend the new preview was the old stored draft.

### Mobile checks and output isolation

- Existing `EditorHandoffMobileValidation` in `R/backend/app/domain/official_account_editor_handoff_v2.py:289` shows the acceptance contract: exact content/body/media hashes, ordered 320/430 widths, zero external requests and exact copy-root equality. Actual browser checks must also verify every image loaded and no horizontal overflow.
- `bind_editor_handoff_v2_mobile_validation` at `application/services/official_account_editor_handoff_v2.py:699` only finalizes a matching artifact. For the new preview wrapper, bind equivalent report fields to its own content/media fingerprint rather than impersonating a V2 release.
- No dedicated reusable standalone official-account browser CLI was found in the release tree; use the existing Playwright environment to open a loopback-served preview and create the bounded report/screenshots. Browser network must stay local after provider work.
- Stage outside `/app/output/weekly-inbox`, `/app/input/official-account-weekly-editions` and draft staging volumes. No prepared-weekly/prepared-manifest or queue-compatible package should be written to any watched path.
- Use a fresh exclusive directory; refuse existing/symlinked paths; validate the complete source manifest before constructing any provider client. File intent/result writes use atomic/exclusive creation. Preserve a terminal failure/unknown ledger without overwriting successful siblings or retrying unknown charged calls.
- Record `source_run_id`, source article/request/render fingerprints separately from new preview UUID/fingerprint; record source read counts, five generation intents/results, six judge intents/results (if cover judge included), and exact zero DB mutation/WeChat/WeCom/draft/publish counts.

## Suggested Minimal Ownership Split

1. **Preview runner owner:** additive application preview service and CLI; source manifest validation, transient plan generation, local intents/results, media/provenance, cover derivation, pure renderer and manifest. No production worker/queue/compose changes. Unit tests for all source, idempotency and no-egress boundaries.
2. **Judge adapter/check owner:** isolated selective Zhipu profile/model routing fix and focused adapter tests; independent sample gate review. Must not change OCR/text model routing accidentally.
3. **Main operator:** production read-only source export, actual authorized generation/judge calls, local browser acceptance and before/after presentation. No draft replacement until explicit sample acceptance.

If only one implementation worker is available, keep both code responsibilities in one new worktree and use a separate check agent after it completes; avoid multiple editors on `image_validation.py`.

## Tests to Require

- Zero provider calls on changed Article/evidence/source-photo/reference checksum, malformed source schema, symlink/escape path, existing output or missing approved model/credentials.
- Exactly five distinct slot plans, exact immutable text block anchors, normalized approved references, one generation attempt per slot, final output 1536×1024 metadata-free JPEG.
- Retry/restart never repeats an unknown paid intent; known completed slot reused only when complete input/output checksums match.
- Source Article/evidence/context pixels unchanged before/after; new cover derived from accepted generated pixels with distinct provenance, not old unrelated cover.
- Judge exact `glm-5v-turbo` model and Zhipu profile, returned-model mismatch fail, references included and normalized, final rather than raw/cropped-away bytes judged, strict schema/privacy and unavailable-not-pass.
- New sample policy independent of production observe; critical/warning/unknown outcomes cannot be mislabeled accepted. No invented numeric/human scoring.
- Five body images plus exact original context-image count retained with source/credit/rights; no screenshot-as-news or catalog fallback hidden as generation.
- No repository enqueue/mutation, MinIO object overwrites, watched-inbox output, WeChat/draft/publish client creation.
- Mobile at exact 320/430: loaded images, no overflow, no external requests, one article copy root, bytes/hash-bound report and fresh final output.
- Existing regression targets: `test_official_account_visual_generation.py`, `test_image_validation_ai.py`, `test_image_quality_eval.py`, `test_official_account_editor_handoff_v2.py`, `test_official_account_local_cli.py`, and `test_official_account_news_editorial_semantic_generated_demo.py`.

## External References

None consulted or needed for this internal architecture research. Current provider capability/credential checks and any API documentation verification before live calls remain the main operator's responsibility.

## Related Specs

- `.trellis/spec/backend/official-account-editorial-repackage.md:697` — V10 body/news-context/export immutability.
- `.trellis/spec/backend/official-account-editor-handoff-v2.md` — V2 release/lineage/mobile truth.
- `.trellis/spec/backend/image-quality-evaluation.md` — final-output observations, no change to production release semantics, strict issue taxonomy.

## Caveats / Not Found

- No existing end-to-end CLI satisfies **existing exact Article + new image generation + no database writes + new local preview** unchanged. The additive wrapper is the real gap.
- Dirty main contains useful Zhipu-only vision changes and a large evaluation panel, but the runtime tree does not contain them. Selectively port only a tested minimal change; preserve all existing dirty work.
- Research did not execute source extraction or provider requests and cannot claim credential validity, live generation success or model-judged quality.
- The requested production improvement still needs a subsequent safe rollout once the sample is accepted; a good sample alone does not change scheduled production behavior.
