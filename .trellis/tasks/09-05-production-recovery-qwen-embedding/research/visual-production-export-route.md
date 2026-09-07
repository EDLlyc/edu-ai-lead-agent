# Research: Prospective production visual export and draft handoff

- Query: After acceptance of the isolated Xiaosai visual sample, what is the smallest safe downstream integration for new weekly runs, preserving source photos, final-image audit truth, old artifacts and existing successful drafts?
- Scope: Internal source/spec research and a provider-free, read-only in-memory check of the accepted sample. No product edits, Git operations, SSH, database, model, social, or service calls.
- Date: 2026-09-07
- Code prefix `C/`: `/root/projects/edu-ai-lead-agent/.trellis/worktrees/visual-quality-preview/`.
- Task prefix `T/`: `/root/projects/edu-ai-lead-agent/.trellis/tasks/09-05-production-recovery-qwen-embedding/`.

## Findings

### Outcome and smallest integration boundary

The downstream seam is `PreparedWeeklyDraftArtifactOwner.build_child`, **not** the development-only V2 API or the accepted preview CLI. It can project a new, genuinely persisted visual run through the existing pure Xiaosai renderer into a versioned prepared child. The existing complete-three-role aggregate, immutable inbox staging and draft worker can then remain authoritative.

Two non-obvious blockers must be included in the implementation:

1. The draft preparer changes upload bytes after the current preview's audits: it always derives a smaller JPEG thumb and may normalize oversized inline images. A publication-image audit is not automatically an audit of the final upload.
2. Draft idempotency is scoped to the exact content-addressed batch. Re-rendering the old articles creates a different batch and therefore a different draft job; current successful-item protection does **not** deduplicate this across jobs.

### Files found and existing normal production chain

| File | Responsibility / anchor |
| --- | --- |
| `C/backend/app/official_account_weekly_dag_main.py:173` | Constructs production handlers; `PreparedWeeklyDraftArtifactOwner` is wired at line 201 with the shared-volume inbox and existing resolver. |
| `C/backend/app/application/services/official_account_weekly_production.py:191` | `build_article` enqueues/reuses the persisted article run and waits for ready; terminal article outcomes stop the branch. |
| `C/backend/app/application/services/official_account_weekly_production.py:237` | `plan_media` presently checks run readiness only; it does not generate, audit or render media. |
| `C/backend/app/application/services/official_account_weekly_production.py:257` | `render_handoff` delegates `build_child(run_id, role)` to the prepared artifact owner. |
| `C/backend/app/application/services/official_account_weekly_production.py:266` | `validate_child` checks the prepared child; `aggregate` at line 283 waits for all three and `finalize` at line 299 records inbox readiness. |
| `C/backend/app/infrastructure/wechat_official_account/prepared_artifacts.py:126` | Current production child exporter: verifies ready live article/draft, resolves media, substitutes private URLs in persisted HTML, writes a content-addressed prepared child. |
| `C/backend/app/infrastructure/wechat_official_account/prepared_artifacts.py:254` | Complete-three-role aggregate writer; copies children to a temporary directory and exposes the final inbox directory by rename at line 308. |
| `C/backend/app/infrastructure/wechat_official_account/prepared_artifacts.py:375` | Prepared batch loader; verifies canonical role order, exact directory set, child preflight and content fingerprints. |
| `C/backend/app/infrastructure/wechat_official_account/artifacts.py:118` | Prepared batch staging: eligibility before copy, immutable content-addressed staging, validation before/after copy. |
| `C/backend/app/infrastructure/wechat_official_account/artifacts.py:207` | Bounded inbox discovery recognizes prepared and finalized-V2 directory prefixes; no model calls. |
| `C/backend/app/application/services/wechat_official_account_draft.py:99` | Pure preparer supports both prepared and finalized-V2 inputs; all three are prepared before weekly execution. |
| `C/backend/app/application/services/wechat_official_account_draft_jobs.py:297` | Draft executor preflights, records first-write intent, calls the draft-only adapter and durably records safe success. |
| `C/backend/app/application/services/wechat_official_account_draft.py:189` | Uploads each inline image, rewrites its exact local `src`, uploads the independent thumb, then calls `add_draft` once for one article. |

The existing production HTML path is concretely different from the accepted sample:

- `prepared_artifacts.py:176` starts from `draft.resolved_html`; lines 177–186 only rewrite local media URLs. It never calls the V2 renderer.
- Files and content identity at lines 187–216 bind the old draft fingerprint plus exported files. Media projection at lines 162–172 contains hashes/dimensions/role only, not generated-output audit lineage, context rights or renderer identity.
- The currently loaded rows are every ready media row for the run (`prepared_artifacts.py:347`); the new path needs exact expected-slot coverage and role/lineage validation, not merely nonempty ready media.
- JPEG/PNG are preserved byte-for-byte by `_normalize_supported_media` at line 487. WebP is explicitly converted to JPEG. Source-original identity must not be silently assigned to a conversion.

### Pure V2 renderer versus full V2 release builder

Use `C/backend/app/domain/official_account_editor_handoff_v2.py:508`, `render_editor_handoff_v2_body(article=..., media=...)`:

- It is a pure function: no DB, model, browser, release approval or social capability.
- It returns body HTML/SHA, layout recipe, emphasis and deterministic context placements (`:595`). Body image ordinals map to exact `ArticleImageBlock` slots (`:570`).
- `plan_context_placements` at `:441` keeps the source image in its assigned section, selects an eligible prose block, and refuses unsafe/colliding placement instead of dropping the image.
- It calls the same escaped Xiaosai inline components and source/author footer as the accepted preview; the preview invokes it at `C/backend/app/application/services/official_account_visual_preview.py:969`.
- Supply typed `EditorHandoffMediaAsset` (`C/backend/app/domain/official_account_editor_handoff.py:146`) and canonical `media_asset_path` (`:188`). These require `body-00`…`body-04`, `context-00`…`context-01`, `cover-wide`, not the current prepared path spelling `body-0` / `cover-0`.

Do **not** enable/reuse the entire V2 handoff entry point as a production shortcut:

- `C/backend/app/api/v1/routes/official_account_local.py:555` explicitly makes editor handoff development-only. Its V2 selection also requires `quality_auto` (`:607`).
- `C/backend/app/application/services/official_account_editor_handoff_v2.py:145` implements a read-only release projection with current Article/render/draft validation, immutable review handling, generated-output lineage, release policy and media integrity. `build_editor_handoff_v2_artifact` owns a different local-only release/bundle/mobile identity.
- `OfficialAccountEditorHandoffV2Service.inspect` checks text/image inheritance at `:189`–`:219`, render/draft identity at `:221`–`:263`, and rejects an existing human rejection at `:265`–`:287`.
- The sample manifest truthfully says it is a local preview, not a durable V2 release. Do not fabricate generated rows, manual approval or browser evidence to feed it through the finalized-V2 loader.
- Preserve V1/V2 golden bytes and old version meanings. A new production prepared policy can reuse the pure renderer without changing those public release APIs.

### Source photo and rights projection

The new exporter should require an exact correspondence between the frozen Article `news_context_media` and persisted context results before resolving/exporting any image. The existing private helper is useful as a reference, not an unreviewed import contract:

- `C/backend/app/application/services/official_account_editor_handoff.py:472`, `_build_media_assets`, requires contiguous body ordinals and exact image-block bindings (`:485`–`:502`).
- Context count must equal the Article snapshot (`:506`–`:509`). It validates section, SHA, MIME, dimensions, alt, source page, caption, credit, rights and context-only truth (`:532`–`:546`).
- Typed assets carry all those fields (`:555`–`:570`). The pure renderer visibly discloses source-image rights at `C/backend/app/domain/official_account_editor_handoff.py:520` and appends factual source links at `:552`.

For the new prepared format:

- Preserve original acquired JPEG/PNG bytes and `source_page_url`, `credit`, `rights_status=publish_permission_unverified`, `context_only_not_evidence=true` in a hash-bound structured projection as well as the visible context annotation.
- Retain section/block placement metadata from the actual pure renderer. Do not label a deterministic text-overlap placement as a model retrieval result.
- Generated illustrations are separate body/cover artifacts and never replace a news photograph or become factual evidence.
- If the source photo must be converted for upload size/format, preserve original bytes separately and bind an explicit source-SHA → upload-SHA derivative. Do not claim the upload is unchanged original bytes.
- Adding auxiliary files is a format change: current child path validator at `wechat_official_account_draft.py:451` permits only `article-body.html` or `assets/*`. Either use bounded typed lineage fields in the v2 manifest or explicitly version/allowlist the new auxiliary files; do not weaken the global v1 loader.

### Final upload derivative audit: concrete verified gap

`C/backend/app/application/services/wechat_official_account_draft.py:467` validates publication media first and then constructs upload media:

- Every cover goes through `_normalize_cover_thumb` (`:521`, implementation `:743`). It center-crops to exact 47:20, caps dimensions at 1175×500, and lowers JPEG quality/dimensions until below the configured 64 KiB limit.
- Inline media larger than the strict 1 MiB boundary is normalized at `:534` using `_normalize_inline_image` (`:799`), preserving aspect ratio but possibly reducing resolution and converting PNG to JPEG.
- These are the bytes sent at `:197` and `:212`, not necessarily the publication artifact bytes.

A provider-free in-memory diagnostic used the existing parser/normalizer on the **accepted sample**, without creating or modifying any file:

| Observation | Value |
| --- | --- |
| Body HTML characters / UTF-8 bytes | 18,936 / 23,078 |
| Inline body images | 6 = five generated scenes + one news original; the preview's seventh image is the separate cover. |
| Existing local draft HTML allowlist / size checks | Passed |
| Audited sample cover | 1536×654, 266,833 bytes |
| Current actual upload derivative | 1175×500, 62,034 bytes |
| Audited publication cover SHA-256 | `90641cd0b910aa796c4b05149bfaa10ea9640e57e1ca847f2f6ee12b48941c56` |
| Current upload thumb SHA-256 | `84c69ec693a1db1cc772bf57033ca08bd14f3e8cd9243a1035b40b471502fbae` |

Thus the sample's six GLM audit successes do not establish acceptance of the current upload thumb. No new audit was performed in this research.

Recommended new production contract: expose a narrowly typed, deterministic upload-derivative preparation seam. Before audit, derive the final body upload bytes and exact thumb bytes; persist/manifest-bind source and output hashes, dimensions, role and transform-policy identity. Audit these final generated upload images/cover with the agreed durable audit owner. The new child preparer then verifies and **uses the frozen validated bytes unchanged**. Legacy prepared-v1 and finalized-V2 branches retain existing normalization behavior. Never call the judge in the draft worker after social side effects start.

Also guard HTML-size headroom. The sample has only 1,063 characters below the local 19,999-character ceiling (`C/backend/app/application/ports/wechat_official_account.py:17`). `create_prepared` lengthens local paths into escaped WeChat URLs at `wechat_official_account_draft.py:205`, but final HTTP request validation happens later (`client.py:621`), after body/thumb uploads. Provider URLs may be up to 2,048 characters (`client.py:574`). A production rendering policy needs a deterministic reserved URL budget or a reviewed compact representation, plus final bound checking, so a technically valid longer article does not fail only after uploads. Do not silently truncate prose or alter frozen V2 styles to fit.

### Versioning and replay boundaries

Recommended minimum, subject to integration design:

1. Freeze a prospective visual/export policy in the new article run identity. The upstream researcher proposes optional `OfficialAccountVersionIdentity.visual_pipeline_version`, absent for legacy runs, and a typed new native-generation/strict-audit policy snapshot. The exporter must dispatch from **stored** identity, not the process's current enabled flag. `C/backend/app/infrastructure/official_account_runtime.py:11` currently constructs the runtime identity; the shared policy must include renderer/export and upload-derivative/audit identities, directly or by immutable policy version.
2. Add a new prepared **child** version for the audited Xiaosai projection. Preserve literal `wechat-draft-prepared-child-v1` generation/loading, its current fingerprints and byte semantics. The child should bind original run/article/render/source identities, actual generated-media/plan/reference evidence, strict final-output audit evidence, renderer recipe/placements, source rights and upload derivatives. No raw prompt/provider body or private object location.
3. Keep the existing prepared batch/ref formats if their generic content-addressed/canonical-three-role semantics remain unchanged. The batch embeds child/content hashes; a changed child produces a new aggregate naturally. Add explicit child-version dispatch to both producer validation and consumer preparation. If the proposed implementation changes batch or opaque-ref semantics, add a new literal branch in the ports/store/loaders; do not merely repoint existing constants.
4. The three branches of a new weekly input should share one frozen visual/export policy, preventing mixed old/new-policy aggregates on restart. Current weekly input `as_dict()` (`C/backend/app/application/ports/official_account_weekly_production.py:140`) contains selection/material inputs but **no runtime article/export policy**; production `_build_article` currently reads constructor `_article_identity` (`official_account_weekly_production.py:195`). Either freeze the identity in a new compatible input version and dispatch old inputs literally, or provide an equivalently proven new-run-only construction boundary. A current-config-only switch cannot prove old pending branches will replay with the old identity.
5. Leave DAG business identity/version and historical successful checkpoints untouched; do not bump the weekly DAG version or request fingerprint merely to rerun the already-delivered September 7 edition. Existing successful `render_handoff` artifacts remain immutable references.

### Existing draft duplicate prevention and why it does not support replacement

- `C/backend/app/domain/wechat_official_account_draft_jobs.py:321` fingerprints account + aggregate + batch + each role's source/article/content/presentation-policy identity. It does not use a global `(week, article)` replacement lane.
- `C/backend/app/infrastructure/db/wechat_official_account_draft_jobs.py:54` conflict-safely returns the existing exact request, verifies every stored identity and creates role items only for a newly created job.
- Claims only select queued/retryable jobs and incomplete items (`:40`, `:134`, `:175`); successful roles are never claimed again within that job. The old job can safely continue to appear in inbox discovery.
- A newly rendered version of the same three articles has different content/aggregate fingerprints and therefore a **new** job identity. It would create three additional drafts. Do not use re-export/reconcile as an implicit update mechanism.
- The public port has only `upload_inline_image`, `upload_thumb`, `add_draft` (`C/backend/app/application/ports/wechat_official_account.py:211`). No draft-update, draft-delete, provider draft-readback or replacement operator was found in the corresponding client/service/CLI.
- The durable worker persists only the SHA fingerprint of the raw returned draft media ID (`wechat_official_account_draft_jobs.py:350`–`:355`; DB item field `models.py:6235`). It does not retain a recoverable raw ID suitable for addressing an existing draft update.
- First-write intent (`wechat_official_account_draft_jobs.py:323`), lease fencing, unknown-outcome handling and successful-item checkpoint preservation should remain unchanged. New visual gates must run before that first social write.

Safe activation for this task is therefore **future legitimate weekly runs only**, with exact old article/draft counters preserved. Replacing the three old drafts would require a separately designed and authorized operation: exact remote target discovery/readback, protected ID handling, optimistic content fencing, intent/outcome ledger, and no ambiguous replay. Merely having sample approval does not make such an implementation exist.

### Bounded ownership suggestion

- **Upstream durable visual owner** (separate researcher/implementer): frozen prospective policy, native reference-conditioned generation, persisted strict final-output audits and derivative cover lineage; no prepared exporter edits until contract agreed.
- **Prepared/export owner**: `infrastructure/wechat_official_account/prepared_artifacts.py`, a new pure projection/validation module if useful, new tests. Reuse the existing pure V2 renderer unchanged; own exact body/context/cover projection and new child format. Coordinate typed upload-derivative inputs with upstream.
- **Consumer compatibility owner** (may be same implementer): `application/services/wechat_official_account_draft.py`, narrowly scoped artifact-store/port dispatch if format requires it, and corresponding unit tests. Add new-version byte-preserving validated upload path; retain v1 behavior and social client API unchanged.
- **Main/integration owner**: frozen weekly-input policy if required, task/spec records, generation/consumer integration seams, reviewed release, gzh-design skill interpretation, real output/mobile checks and safe production activation. No old-draft replacement for this integration.
- **Independent checker**: review all affected shared identity/serialization paths and complete producer-to-consumer offline test before any activated new run.

### Required tests / existing regression anchors

Existing anchors:

- `C/backend/tests/unit/test_official_account_weekly_production.py:331`: article/checkpoint replay stability.
- `C/backend/tests/unit/test_official_account_weekly_production.py:551`: complete-three-child prepared discovery/staging/opaque resolution; extra file and nested symlink rejection at `:576`, `:584`.
- `C/backend/tests/unit/test_wechat_official_account_draft.py:150`: complete-three-article local preparation; oversized PNG normalization at `:272`.
- `C/backend/tests/unit/test_wechat_official_account_draft_worker.py:799`: successful roles resume once, repeat reconcile/worker is zero-call.
- `C/backend/tests/integration/test_wechat_official_account_draft_jobs.py:90`: actual PostgreSQL enqueue idempotency and ordered-item resume.

New minimum cases:

1. Exact old prepared-v1 fixture/body/manifest/child/batch/request identity unchanged after deployment; old finalized-V2 input still loads. Existing succeeded job reconciliation produces zero provider writes.
2. New stored visual identity takes Xiaosai renderer; legacy identity always takes legacy path even with new config on. Restart between branches cannot mix a new policy into frozen old weekly input.
3. New generation/audit row missing, unavailable, rejected, warning-bearing, wrong model/hash/slot/reference/cover/transform policy => no complete child/inbox/job; no provider call in export/preparation.
4. Five current generated bodies and one independently audited final-upload thumb; exact body-slot and source-context count. No catalog fallback and no old unrelated cover.
5. Original news bytes/rights/source/credit and actual section/block placement round-trip across structured projection and visible HTML; tampering each field fails closed. Explicit source-to-upload derivative when required.
6. New-version consumer sends exact hash-bound, audited upload bytes. Prove thumb normalization is not performed again; cover/media tamper invalidates new child. Old-version normalizer bytes unchanged.
7. New child is deterministic and no-clobber; unsupported version, duplicate JSON keys, extra/missing files, nested symlink, role reorder, source/content/hash drift and partial aggregate fail before all social writes.
8. Pure-rendered output passes independent gzh validator and actual 320/430 mobile checks for representative 0/1/2-news-image articles; do not fabricate per-article browser `passed` when production never runs a browser.
9. HTML long-article and URL-expansion boundaries fail before any social write (or use explicitly tested compact policy), not after expensive uploads.
10. Demonstrate that deliberately re-exporting old content yields a different request lane and is excluded by activation policy; do not incorrectly assert repository dedup covers it.

## External References

No external sources needed or consulted: this is a code-owned downstream architecture question. WeChat limits above are observations of the current adapter's executable contract, not a claim that external API documentation was freshly verified. Main should verify current official API docs if changing provider limits or adding any replacement API.

## Related Specs

- `.trellis/workflow.md` — role-isolated research, prospective implementation and preserved evidence.
- `.trellis/spec/backend/official-account-editor-handoff-v2.md` — pure rendering versus development-only full release and source/rights/mobile truth.
- `.trellis/spec/backend/official-account-visual-preview.md` — accepted sample is isolated, not production activation or draft replacement.
- `.trellis/spec/backend/wechat-official-account-drafts.md` — draft-only writes, artifact preflight, upload derivation, idempotency, leases and unknown outcomes.
- `.trellis/spec/backend/official-account-weekly-dag.md` — static graph, immutable successful checkpoints and full aggregate dependency.
- `T/research/visual-preview-live-evidence-20260907.md` — prior actual sample/model/gzh/mobile evidence; research did not repeat paid calls.

## Caveats / Not Found

- Upstream durable policy/cover/audit work is not complete merely because these seams are identified; its proposed `visual_pipeline_version` is not yet an implemented contract. Coordinate with `visual_production_route` findings before implementation.
- Current spec headings retain historical development-only wording in places; the inspected production handler/prepared branch already exists. Do not remove development-only V2 API restrictions to reconcile those wording differences.
- The research role did not load implement/check JSONL manifests despite the dispatch's general request: researcher context remains role-isolated. It read the supplied root PRD/design/implementation plan, workflow, relevant specs and target source.
- The read-only sample diagnostic proves local HTML compatibility and a cover-byte mismatch only. It does not prove new prepared-v2 implementation, actual WeChat upload acceptance, live model calls, production activation or remote draft replacement.
- No product file was changed. This document is the only written deliverable.
