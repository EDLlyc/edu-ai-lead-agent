# Prospective strict official-account visuals

## Prospective V5 Chinese-family illustration requirements

### 1. Scope / trigger

The September 9 user requests Chinese families, elementary-/middle-school children
and Xiaosai IP for future generated Official Account illustrations. This is a
local candidate on deployed base65064b, not a deployed rule or a visual-quality
measurement. Original news photographs and historical generated articles are
outside the change.

### 2. Signatures

`OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION` is
`official-account-generated-visual-prompt-v5-chinese-family`.
`build_generated_visual_prompt(..., prompt_version=...)` retains literal V4 and
adds V5. Shared `official_account_identity_from_settings(...)` selects V5 for new
native identities; stored Article and weekly identities keep their saved version.
PlanV4, output profile, reference byte formats, native geometry and audit versions
stay fixed. V5 now selects Xiaosai-only references per the explicit user correction;
oldV4selection remains unchanged. V5is unpublished local work and has no live runs.
Candidate migration `20260909_0045` extends deployed `20260907_0043`, not the
separate unshipped R32 branch.

For the unpublished V5 presentation, `render_editor_handoff_v2_body(...,
hide_body_captions: bool = False, hide_context_rights_notice: bool = False)`
keeps historical output as its default.
`build_strict_prepared_projection` opts in only after validating homogeneous
native visual evidence whose `prompt_version` is V5. The saved evidence already
binds this choice for canonical consumer reconstruction; no new serialized flag,
layout version or migration is introduced for caption/notice display.

### 3. Contracts

New native V5 identities created by `official_account_identity_from_settings`
use `default_author="程岳"` for both strict and observe routes, even when the
configured legacy author is `赛先生`. Non-native construction keeps its existing
configured author. Freeze the choice before generation: the author-bearing prompt,
Article composition and mismatch validation, visible signature, prepared manifest,
and WeChat request must all carry that same author. No downstream renderer/client
may relabel a historical Article. Existing weekly snapshots, prepared artifacts
and manual derivatives retain their source author; new derivatives inherit their
new source's author. Original-news reporter/photographer credits, source metadata,
IP character identity and reviewer labels are not the composed author and must not
be renamed. Author is already part of the identity/fingerprints; no new version,
configuration or schema is needed for this unpublished default.

V5 requires contemporary Chinese-family learning context and clearly school-aged
children. Elementary or middle-school age follows article context; a generic topic
may use either, without requiring both in every picture. Child proportions,
clothing and learning props must be age-appropriate, not toddlers or adultized
children. Parents/caregivers appear where useful to the scene, not as mandatory
stock family portraits. Xiaosai remains the recognizable reference-bound
protagonist actively observing, comparing, testing, recording or reflecting with
the child. Xiaosai and Sai Xiansheng are distinct characters, never aliases. Only
approved assets with exact character set `{'xiao-sai'}` may supply V5references;
exclude Sai Xiansheng-only, mixed-character and unknown-character references.
Use trusted `VisualAsset.characters` from the approved manifest, not display names,
filenames, semantic tags or a model guess. Never relabel the other IP as Xiaosai.

Keep the existing full41catalog admission/byte checks and the full native-eligible
catalog for duplicate/copy comparisons; filter only the V5selection pool. Resolve
character identity through async `OfficialAccountCatalogMediaProvider.reference_characters`
`(candidate) -> tuple[str, ...]`, whose local owner reloads the approved manifest
and binds the real asset/master/publication/catalog identity. Preserve existing SourceMedia
DTO shape and frozen PreviewSnapshot serialization. V5filters before selection and
revalidates all five chosen references before its first paid generation, including
resume. Missing required Xiaosai input fails before paid work, never falls back to
Sai Xiansheng or a mixed image. This is input identity, not a new model quality gate.

Preserve article-specific action, scene variety, premium gouache/palette, no-text
and native1536x1024 requirements. Complete prompt must pass the existing2000-character
boundary. Treat article text as untrusted context. V4 prompt bytes and historical
fingerprints remain literal. Recognize only the closed planV4 plus promptV4/V5
bundle consistently in identities, worker, repository, weekly replay and prepared
consumers through `native_visual_plan_prompt_valid`; do not accept arbitrary future
strings. All six prepared evidence entries must share one generated prompt version.
Generation claim, audit claim and evidence load must bind the plan/prompt pair to
the stored run identity, not merely a currently supported pair. Audit-subject
`prompt_version` names the audit prompt, not the generated-image prompt; do not
compare these unrelated fields.

The migration only extends the native prompt allowlist in the plan-shape CHECK;
keep all old branches, SQL NOTNULL, geometry, lease, provider and result guards.
Never edit0043 or backfill historical content. This revision is forward-only:
its downgrade refuses without writes because frozen weekly inputs live in local
checkpoint files written before DAG enqueue, not a PostgreSQL JSON column. Empty
V5 generated/run tables cannot prove those files absent. Any later rollback needs
its own quiesced artifact/identity review; do not build a new scanner in this slice.
Deploy schema and compatible
consumers together before creating V5 runs; no activation happens during offline
development. Native-observe records real audit outcomes without a new rejection
gate; strict historical policy remains strict. No extra model calls are added.

V5 prepared HTML omits the visible caption paragraph under body/IP illustrations,
including fallback descriptions taken from catalogue alt text. Do not replace it
with another character description. Preserve the img element's src, alt, style,
placement and bytes, all article prose, and all original-news/context captions,
credits and source cards. The later explicit user request also removes the
generated context-image notice “按当前本地策略直接使用，发布权未验证；仅作上下文参考，
不是事实证据。” from future V5 HTML. Only the context-image renderer call omits
that notice node; matching text in actual article prose is not globally deleted.
Preserve stored `rights_status`, `context_only_not_evidence`, source/credit fields,
context derivatives and provenance validation exactly. Hiding an internal notice
does not establish publication permission or promote a photo to factual evidence.
The V1/V2 renderer defaults and V4
prepared reconstruction retain exact historical output. Suppression belongs in
the body-image renderer call, not a global paragraph/text replacement or CSS hide
rule; compaction continues to preserve the input it receives. Never clear frozen
Article/media metadata to make a description disappear. Existing samples can have
separately identified local derivatives, never in-place edits to accepted children
or upload receipts; a local preview is not a remote draft update.

### 4. Validation and error matrix

- V5 new native request: bounded Chinese-family/school-age/Xiaosai prompt.
- New native V5 with stale configured author: composed author is exactly `程岳`.
- Non-native or frozen historical identity: retain configured or saved author.
- Different nonempty model author: existing `article_author_mismatch` error.
- Validated V5 prepared evidence: no visible body captions; news attribution remains.
- Validated V5 context media: internal notice omitted; original caption/credit and
  unchanged rights/context-only metadata remain required.
- V4/default renderer: historical captions and exact bytes remain unchanged.
- V5 Sai-only/mixed/unknown reference: excluded before selection, rejected at preflight.
- No valid Xiaosai-only references: no paid work and no different-character fallback.
- Frozen V4 or legacy request: exact old prompt, fingerprint and policy.
- Unknown or mixed native bundle: reject before generation or prepared upload.
- Long normal article context: valid bounded prompt, no unrestricted escape hatch.
- Original news media: unchanged bytes, source/rights and placement contracts.
- Any downgrade of0045: explicit refusal without deleting/relabeling data.

### 5. Good / base / bad cases

Good: an elementary-school science topic shows Xiaosai and a school-age Chinese
child conducting the relevant observation, with a caregiver if useful. Base: an
older V4 Article resumes with its original prompt. Bad: every image forces two age
groups and parents into an unrelated posed portrait, or prompt text is silently
changed under V4.

### 6. Tests required

Cover elementary, middle-school and generic context; reference identity and
exact trusted Xiaosai-only/Sai-only/mixed/unknown selection, revalidation drift,
all-five-before-first-call and preserved full-catalog comparisons; unchanged DTO
and oldV4reference behavior. Cover
topic-specific action wording; normal/full-bound prompt lengths; literal V4 golden
hash and V5 deterministic distinct identity. Exercise four shared runtime identity
owners, frozen weekly replay, real native generation input and prepared consumer,
plus retained observe/strict behavior. Real isolated PostgreSQL must prove upgrade,
V4/V5 acceptance, invalid bundle rejection and unconditional downgrade refusal.
Offline prompt tests are not proof that a live generated raster realizes the rule.

Verify author selection with an explicit stale configuration for strict/observe
and the actual API/CLI/weekly callers. Exercise the real prompt/composition,
prepared/signature and outbound HTTP serialization owners without network:
`程岳` must agree throughout, incorrect model authors must still fail validation,
and original-news credit plus historical author reconstruction must remain intact.

Renderer/prepared tests must prove all five V5 body captions are absent while image
src/alt/order and original-news caption/credit/rights survive. Reconstruct the real
V5 projection through the consumer; retain mixed-evidence and rehashed-tampering
rejection plus V1/V2/V4 golden bytes. A matching phrase in article prose must not
be removed. New local sample derivatives require exact preservation outside the
five caption removals, unchanged media bytes, and actual gzh/mobile checks.
For the later prospective notice change, cover zero/multiple context images,
retained actual captions/credits and identical rights/source fields, same-notice
text in prose, and default/V4 notice retention. Producer/consumer reconstruction
must agree on both V5 display options without relaxing provenance or mixed-proof
checks. Earlier delivered samples/derivatives are not rewritten by this rule.

### 7. Wrong vs correct

Wrong: append Chinese-family instructions to the existing V4 builder, or allow
V5 only in Python while SQL still rejects it. Correct: add V5, freeze it for new
native runs, extend compatible consumers and the one exact SQL allowlist, and
retain unchanged old prompt reconstruction.

Wrong: clear `asset.alt_text`, remove every paragraph after every image, or infer
caption policy from today's settings. Correct: after the existing complete evidence
validation, pass `hide_body_captions=(evidence[0].prompt_version == V5)` to the
shared renderer. The separate `hide_context_rights_notice` option is selected by
the same validated V5 identity; it removes only the generated internal notice,
never the actual context caption/credit or stored rights/source fields. Wrong:
mark unverified rights as approved simply because a notice is no longer visible.

## Scenario: standardized V5 Xiaosai final CTA with an unassigned QR reserve

### 1. Scope / trigger

Future native V5 prepared Articles replace the legacy signature-only ending with
one deterministic final region after the unchanged source cards. Historical V1,
default V2, V4 and already-prepared artifacts retain their exact ending. The QR
destination and image are not yet assigned, so this revision reserves layout only;
it does not create, upload or claim a working QR code.

### 2. Signatures

- `XiaosaiFooterAsset` is a frozen typed projection with
  `version=official-account-xiaosai-final-cta-v1`, `role=footer`, `ordinal=0`,
  `path=assets/xiaosai-footer.jpg`, approved exact `characters=("xiao-sai",)`,
  catalog/ref/master/publication identity, decoded geometry and byte identity.
- `LocalOfficialAccountCatalogMediaProvider.load_xiaosai_footer(article)` and
  `OfficialAccountLocalMediaResolver.read_xiaosai_footer(article)` return the typed
  footer plus its verified publication bytes.
- `render_editor_handoff_v2_body(..., footer: XiaosaiFooterAsset | None = None)`
  and `build_strict_prepared_projection(..., footer: XiaosaiFooterAsset | None = None)`
  preserve their historical default; V5 prepared ownership supplies the footer.

### 3. Contracts

The footer reuses the Article's already-frozen assignment zero approved reference,
not a generated body image or a news/context image. The real producer reloads the
catalog, verifies approval and exact character set `{'xiao-sai'}` before and after
the byte read, and binds catalog version, public ref, master SHA, publication SHA,
size and dimensions. The pure consumer reconstructs from the frozen Article,
evidence, descriptor and bytes without selecting from current settings. This local
hash/projection boundary proves consistency with the frozen producer inputs; it is
not a cryptographic signature against wholesale replacement of every trusted input.

Validated V5 evidence requires exactly one footer; non-V5 evidence forbids it.
Keep it outside the five generated body assets and six model-audit subjects. Its
manifest role/path is distinct from `body`, `context` and `cover`, but it participates
in the canonical file set, child fingerprint, HTML image correspondence, escaped
upload-URL reserve and actual WeChat inline upload order.

The final visible order is conclusion, unchanged sources, then one combined region:
the exact `Article.author` signature, one Xiaosai image, restrained Xiaosai/family
science-learning copy, one follow prompt and one labeled `二维码待补` reserve. The
reserve is a styled non-image element: it has no `img`, `src`, URL, encoded payload,
generated QR bytes or claim that scanning currently works. Do not emit the legacy
likes/在看/转发 CTA in addition to this region. A future real QR needs a separate
typed purpose/destination/byte contract and must not be smuggled into this placeholder.

### 4. Validation and error matrix

| Condition | Required behavior |
| --- | --- |
| Homogeneous V5 evidence plus exact approved Xiaosai assignment zero | Require and render one footer media item and one blank QR reserve |
| V5 footer absent, duplicated or on another role/path/ordinal | Reject canonical prepared construction before upload |
| V4/default renderer carries a footer | Reject prepared construction; historical renderer output remains exact |
| Sai Xiansheng, mixed/empty characters, catalog drift or changed publication bytes | Reject at the real catalog/resolver boundary |
| Descriptor, Article assignment, evidence, geometry or bytes disagree | Reject producer/consumer reconstruction and make zero provider calls |
| QR image/link/payload or functional scan promise appears | Reject acceptance; no QR media exists in this revision |

### 5. Good / base / bad cases

Good: a new V5 Article ends once with `程岳`, its frozen Xiaosai reference image,
brief follow copy and a visibly empty `二维码待补` box; the image is the final inline
upload. Base: a V4 prepared child retains the prior signature-only bytes. Bad: append
a local footer image in HTML without manifest bytes, relabel Sai Xiansheng as Xiaosai,
or use an empty/fake QR `src` and tell readers to scan it.

### 6. Tests required

Exercise the real catalog and resolver, actual prepared owner, canonical consumer,
draft preparer and `httpx.MockTransport`. Assert one author/signature, unchanged
news sources and credits, exact final footer upload/order, one non-image
`二维码待补`, and zero QR URL/bytes/scan claim. Cover V5-required/V4-forbidden,
Sai-only/mixed/empty roles, catalog drift during read, every footer descriptor and
byte tamper with zero HTTP calls, stable historical goldens, gzh validator with zero
warnings/errors, and 320/430 rendering without overflow or broken images.

### 7. Wrong vs correct

Wrong: concatenate `<img src="">` and marketing prose after rendering, leaving the
manifest and uploader unaware. Correct: carry one exact Xiaosai `footer` asset through
catalog resolution, frozen prepared projection, canonical validation and upload;
render the QR reserve as ordinary labeled HTML with no media or destination.

## R30 extension: prospective native-observe draft readiness

### 1. Scope / trigger

The September 8 user explicitly cancelled future image-quality rejection. New
Articles may opt into `official-account-visual-pipeline-v2-native-observe`.
The strict-v1 contracts below remain unchanged for historical/frozen strict runs.
Implementation and live activation status are separate recovery-task evidence.

### 2. Signatures

The existing `OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION` and frozen
`OfficialAccountVersionIdentity.visual_pipeline_version` select the new policy.
`NATIVE_VISUAL_PIPELINE_VERSIONS` and
`native_visual_audit_releases(policy, status, issue_codes)` centralize recognized
native policy and policy-dependent readiness. `ObserveVisualAuditSubject` extends
only the new subject; `ObserveVisualMediaEvidence` carries `audit_status`,
`audit_issue_codes`, `audit_subject` and `quality_issue_codes`. The new closed
envelope is `wechat-draft-prepared-child-v3-native-observe`; strict-v1 evidence and
its v2 envelope must not acquire serialized default fields.

### 3. Contracts

Observe means the model verdict is not draft eligibility. Keep five native V4
images, normalized cover, direct Zhipu `glm-5v-turbo`, one durable attempt per
audit, real terminal results and exact upload-byte fingerprints. Rejected,
unavailable or result_unknown audit records and perceptual resemblance warnings
do not block. Never set `accepted=true` merely to continue; no numeric score or
human review is implied. Missing audits still require their one legitimate
attempt; dispatched unknowns must not be paid-retried. Cancellation and lost
ownership remain fenced rather than treated as an audit outage.

Generation uncertainty, missing/invalid files, geometry/byte/subject/lineage
mismatch, exact-copy/duplicate output integrity, source/HTML rules and no-public-
publishing remain enforced. New prepared reconstruction binds six real audit
records, actual statuses/codes, stored policy, exact assets and canonical HTML.
Consumer validation must not reconstruct an observe audit as accepted/empty issues.
Keep literal V4 planning/prompt/output versions and old prepared bytes stable.

Observe-only audit codes use `observe_visual_audit_codes_valid` and its shared
closed vocabulary, not merely
the `strict_visual_` prefix; arbitrary text/control characters cannot cross DB or
prepared-evidence boundaries. Compare provider-returned raw bytes to catalogue
publications before any JPEG re-encoding: a transform changes SHA and must not
disguise an exact reference echo as a new generated scene. Complete the generated
intent as `failed/strict_visual_catalog_exact_reuse`, preserve prior ready images
and make no retry; perceptual similarity alone remains allowed.

Activation changes the one future policy key after compatible consumers are
deployed, preserves other provider/environment/schedule settings and never resets
old failed runs. Changing today's settings must not reinterpret an old strict
Article or weekly input. Retain compatible observe consumers after any observe
state exists; unchanged SQL schema is not unconditional rollback permission.

### 4. Validation & error matrix

| Condition | Observe behavior |
| --- | --- |
| Audit rejected / unavailable / result_unknown with valid subject | Record truth, continue other audits and allow unpublished draft |
| Same result under frozen strict-v1 | Preserve existing rejection |
| Perceptual resemblance only | Record warning, no regeneration or draft veto |
| Audit identity tampered or a required subject absent | Reject projection/readiness |
| Generation unknown / missing / invalid bytes / lost lease | Preserve hard failure/fence, no blind paid retry |
| Future config changes after old run frozen | Old identity and result remain unchanged |

### 5. Good / base / bad cases

Good: a valid five-image Article with one rejected visual audit enters the draft
path with that rejection visible in its evidence. Base: an old strict prepared
child still reconstructs exactly and rejects missing/failed proofs. Bad: catching
the executor exception while the independent repository/consumer still rejects,
or falsifying accepted audit rows to bypass those gates.

### 6. Tests required

Exercise ordinary observe enqueue/worker/repository/export/consumer with real
isolated PostgreSQL and fake providers: rejected, outage, unknown, all six audit
attempts, one-post ownership, idempotent resume, exact thumbnail bytes, policy and
subject tampering. Pair every relaxed case with an unchanged strict negative.
Test four equal settings-derived identities, weekly frozen replay, old JSON/schema
stability and regenerated API contracts. No live provider/upload is part of tests.
Include actual native-size catalogue echoes before normalization, separately
resealed arbitrary issue strings, cancellation/orphan resume with no repeated
paid audit and retained successful siblings.

### 7. Wrong vs correct

Wrong: `audit.accepted = True` or a global `skip_validation` toggle.
Correct: preserve the audit result and independently compute draft readiness from
the run's frozen observe policy plus complete, valid media/subject evidence.

## 1. Scope / trigger

This contract covers only Article identities opting into
`official-account-visual-pipeline-v1-native-strict`. Implementation is on the isolated
visual-quality release branch; release status and checks belong in the recovery task evidence.
An accepted isolated preview is not a durable Article, deployment, or public publication.

The normal path generates five contextual native scenes, prepares final upload bytes, audits
those five images plus a derived thumbnail, and exports through the vendored Xiaosai renderer.
Legacy absent-policy runs, literal V1–V3 plans, snapshots and prepared children retain their
original meaning. Existing completed weekly editions and drafts are never replayed for activation.

## 2. Signatures and ownership

- `OfficialAccountVersionIdentity.visual_pipeline_version: StrictVisualPipelineVersion | None`
  is part of a new run identity; absent/null must be omitted from legacy fingerprints.
- `official_account_identity_from_settings(...)` is the API/worker/scheduler composition owner.
- `official_account_visual_pipeline.py` owns immutable provider, geometry and audit criteria;
  `official_account_visual_generation.py` owns new literal V4 planning and reference preflight.
- `normalize_official_account_upload_body/cover/context(content: bytes)` returns an immutable
  `OfficialAccountUploadDerivative`: content, MIME, dimensions, source SHA, upload SHA and policy.
- `execute_strict_visuals(...)` integrates generation, immutable storage and durable audits.
- `claim_strict_generated_visual(...)` and `claim_strict_visual_audit(...)` return typed
  `newly_claimed | in_flight | completed | result_unknown | lease_lost` ownership results.
- `complete_strict_visual_audit(...)` persists only a fenced terminal result.
- `load_strict_visual_evidence(run_id)` exposes six verified `StrictVisualMediaEvidence` entries;
  the repository also independently gates `persist_draft`, not only the application caller.
- `build_strict_prepared_projection(...)` and `validate_strict_prepared_projection(...)` share
  the exact pure child projection; `PreparedWeeklyDraftArtifactOwner.build_child` dispatches
  from the stored run policy, not the current global toggle.
- `compact_strict_xiaosai_html(body_html, *, version=STRICT_LAYOUT_PROJECTION_VERSION)`
  retains literal compact-v1 as its default. The prepared builder accepts a typed
  `layout_projection_version`; the current strict owner explicitly chooses
  `STRICT_LAYOUT_PROJECTION_V2_VERSION`. The validator dispatches from the saved manifest
  value through `strict_layout_projection_version(value)`, never today's producer default.
- Candidate migration `20260907_0043` extends actual production head `20260901_0042`; it adds
  generated-intent ownership/geometry columns and `official_account_strict_visual_audits`.
  Do not mix later unrelated Reviewer migration branches into this release.

## 3. Contracts

### Configuration and immutable identities

`OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION` defaults absent/null and selects identity,
not execution capability. Compose supplies it only to API, weekly scheduler/DAG and Article
worker. These four owners must select the same full V4 identity even where image credentials
are absent. Strict policy requires local Zhipu Articles with semantic reference retrieval off;
deterministic selection must not claim embedding retrieval.

Only the Article worker receives the global `OFFICIAL_ACCOUNT_LOCAL_GENERATED_VISUALS_ENABLED`
value as execution permission. Shared service defaults pin it false and image quality mode off.
Strict execution additionally requires enabled images, the existing Comfly `gpt-image-2` route,
exact vision base `https://open.bigmodel.cn/api/paas/v4`, nonblank direct Zhipu credentials and
`IMAGE_QUALITY_AUDIT_MODEL=glm-5v-turbo`; Compose injects the audit model only into that worker.
A running strict worker without generated execution rejects before engine construction/claim.
Do not distribute new provider secrets to make policy-only processes pass validation.

For absent-marker legacy compatibility, Compose maps the same global generated opt-in into
`OFFICIAL_ACCOUNT_LOCAL_LEGACY_GENERATED_VISUAL_POLICY_ENABLED` for the three policy-only
owners. This internal default-false alias grants no execution and is not another user-facing
switch. The pure identity builder selects generated policy from strict marker OR executor flag
OR legacy alias (Zhipu only), with strict precedence. Existing direct Settings legacy behavior,
literal V3 bundles and one-attempt legacy execution validation remain intact.

Changing future policy does not remove already-frozen strict runs: retain compatible execution
capability until they drain. Otherwise fail explicitly with `strict_visual_configuration_changed`, never
silently run the legacy path or create a replacement paid Article.

The new immutable planning literals are:

- `official-account-generated-visual-plan-v4-native-strict`
- `official-account-generated-visual-prompt-v4-native-strict`
- `official-account-generated-body-jpeg-v2-native-strict`

The new plan requests native `1536x1024` and validates decoded provider geometry. Five slots can
reuse genuine approved references with decoded short edge at least 512; only a strict snapshot
discriminator permits repeat reference bindings. Generated scenes themselves must be distinct
and must not be exact/perceptual catalog copies. Do not invent catalog identities or lower the
legacy catalog admission policy globally.

The complete V4 prompt must pass the existing 2,000-character image-prompt boundary before a
paid intent is dispatched. Test with full normal V10 sections, not only short synthetic text;
do not set the unrestricted prompt escape hatch or alter literal V3 bytes. Every Article image
count consumer must dispatch the strict five-scene policy consistently, including generic
multimodal validation after strict reference selection.

`ArticleMediaSelectionSnapshot.reference_policy_version` uses field-level omitted-null
serialization (`Field(exclude_if=...)` on the locked Pydantic version). Preserve the closed typed
serialization/OpenAPI schema as well as legacy bytes. A wrap serializer returning an untyped
dictionary can erase the public output schema even when JSON golden tests pass; test both the
model's serialization schema and the actual FastAPI schema, then regenerate OpenAPI/TypeScript
from this candidate runtime rather than copying a dirty workspace's generated files.

New weekly input `official-account-weekly-production-input-v2-frozen-article` freezes the full
Article identity. V1 retry resolves a proven historical identity/link, or rejects ambiguity;
current strict defaults must never produce a second paid Article for an old input. Preserve
weekly DAG identity, schedule, terminal checkpoints and the three separate article roles.

### Storage, auditing and side effects

One newly claimed intent permits one physical POST. Lazy owned HTTP transports are constructed
only inside the post-intent generation/audit operation; they do not change general provider
retry settings. Generation may use the existing bounded result download/task-poll protocol.
Every next paid boundary requires current durable lease ownership. In-flight ownership is not
permission for another executor to dispatch. An orphaned or ambiguous dispatched intent becomes
`result_unknown`, never an automatic retry or a fresh output directory pretending to be a retry.

Persist each successful generated image as immutable `ready` before auditing. A rejected image,
late sibling failure, storage error or audit outage must not delete prior successful outputs.
Audit intent/result identity includes run, Article, render, body/cover role and ordinal,
parent generated image/plan/reference, publication and exact upload SHA, geometry, normalization
policy, criteria identity, direct provider/model/route and audit versions.

Only literal accepted=true, zero issues, and matching request/provider/model identities pass.
Warning, rejected, unavailable, unknown or missing audit results cannot make a strict draft ready.
Machine review is not a human annotation, source evidence or publication permission.

Final body JPEG: 1536×1024 and less than 1 MiB. Final thumbnail JPEG: 1175×500 and less than
64 KiB, derived from the designated generated cover parent **before** its independent audit.
The strict draft consumer preserves those exact approved bytes; it must not apply the legacy
thumbnail crop or JPEG compression after audit. Descriptors retain closed parent/derivative
lineage; the media resolver verifies it and the repository checks all five bodies plus cover.

Original news JPEG/PNG bytes remain separate, with source URL, credit, rights, exact placement,
and `context_only_not_evidence=true`. If upload conversion is required, preserve the original
and bind an explicit deterministic source-to-upload derivative. News images are not fabricated
when the governed source contains none, nor represented as model-generated evidence.

### Prepared layout and upload budget

`wechat-draft-prepared-child-v2-native-strict` is separate from literal V1. The producer and
consumer verify all six audit/media entries, the complete file set, Article/source projections
and canonical hashes. All three children must have the same frozen visual policy. Export has
no model/provider capability; it must not fabricate DB review records or enable development-only
handoff release APIs.

Use the unchanged pure V2 renderer and project-owned theme `xiaosai-moyu-layout-v1`. Preserve
literal `xiaosai-strict-inline-compact-v1` byte-for-byte for existing artifacts; new strict
exports explicitly use `xiaosai-strict-inline-compact-v2`. Runtime never reads personal skill
paths. Main's independent gzh-design validation remains a release artifact check.

Compact-v2 may consolidate narrowly recognized neutral wrappers, group adjacent canonical body
paragraphs and factor equivalent inherited typography within the bounded frozen-renderer tree.
Preserve every leaf/text node, emphasis effect, paragraph spacing, image, source/rights/caption
and final media byte. Unknown relative metrics are not equivalent absolute values. Account for
browser default style boundaries (notably source-link color); equal leaf text alone does not
prove equal link decoration or layout. This is not a general arbitrary HTML/CSS optimizer.

An empty `leaf` attribute may use its equivalent bare spelling only in validated compact-v2
strict children. The draft HTML validator keeps its legacy default strict and permits this
normalization only after exact version-bound canonical projection validation. The strict child
envelope remains v2 because its closed fields are unchanged; the saved layout version participates
in the child fingerprint. Changing only the version field or rehashing modified HTML must fail
independent reconstruction, before upload. Do not edit a prepared artifact in place.

The initial strict accepted **escaped rendered upload URL** limit is 256 characters. Reserve
that exact bound per inline image before any upload; enforce the same bound on each returned
URL before rewrite or draft creation. HTML remains at most 19,999 characters and below 1 MiB.
Do not truncate Article text or raise final limits. An oversized provider URL is an explicit
invalid result, with existing first-write/unknown-outcome records retained and no implicit retry.
A sample fitting this budget does not prove every future article fits.

## 4. Validation and error matrix

| Condition | Required behavior |
| --- | --- |
| Policy absent/null | Exact legacy decoding, identity and execution |
| Strict policy-only API/weekly process, no image credentials | Same full V4 identity; no image client construction |
| Active strict Article worker, execution disabled | Reject before database engine or queue claim |
| Strict executor missing key or wrong pinned model/route | Settings rejects before provider work |
| Frozen strict run, execution capability subsequently disabled | Explicit strict_visual_configuration_changed; no legacy/text/image fallback |
| Unknown/mixed policy or V4 without strict marker | Reject before provider dispatch |
| No eligible complete reference | Fail preflight; zero image-generation calls |
| Native result has wrong dimensions | Reject; never upscale and label it native |
| Same-attempt concurrent claim | One owner calls; other observes in-flight |
| Expired lease, orphaned calling intent, ambiguous result | Fence completion/calls; preserve unknown outcome |
| Earlier generated sibling ready, later failure | Retain earlier immutable result |
| Audit warning/reject/unavailable or identity mismatch | Block strict readiness; do not fall back to observe |
| Five bodies/cover/six proofs incomplete or bytes changed | Repository and prepared consumer reject |
| News upload conversion | Preserve original and exact derivative/rights binding |
| HTML reserve exceeds bound | Reject before the first social upload |
| Saved compact-v1 child under a compact-v2 producer | Rebuild exact v1 bytes; never silently upgrade |
| Unknown layout version, version-only swap, rehashed HTML/style/media edit | Reject canonical projection before upload |
| Bare leaf in legacy/v1 input | Preserve the original HTML allowlist rejection |
| Returned escaped URL exceeds 256 | Reject before rewrite/add_draft; retain write history |
| Old weekly retry after config changes | Proven legacy identity, never new current strict identity |
| Populated strict migration downgrade | Refuse; never erase audit or sent/draft history |

Nullable SQL columns used in strict CHECK expressions require explicit `IS NOT NULL` in that
branch; PostgreSQL accepts UNKNOWN and a comparison/regex alone is not a non-null constraint.

## 5. Good / base / bad cases

Good: a new frozen strict run reuses three approved references across five distinct native
scenes, stores every generated success, audits five upload JPEGs and its upload thumbnail once,
and creates only its new three-role unpublished draft batch after exact-byte validation.

Base: existing absent-policy ready Articles and their already-successful draft job remain
unchanged after deploying compatible code. Observe remains observational, not a strict verdict.

Bad: restarting an old weekly input under today's strict settings generates replacement
Articles; or a reviewed 1536×654 preview cover is subsequently cropped to a different unreviewed
1175×500 upload. Neither is an acceptable implementation of this contract.

## 6. Required tests and release evidence

- `test_official_account_strict_compose.py`: render actual full-profile Compose with synthetic
  production values, then parse every Python role with cleared environment and
  `Settings(_env_file=None)`. Disabled, strict and legacy-generated matrices cover all 15
  roles, exact credential-key projection, four equal identities and actual worker startup
  through one idle claim. Include policy-only scheduler/DAG construction and early rejection.
- Policy/reference/native planner tests preserve old fingerprints, reject mixed identities,
  allow genuine repeated references only in strict snapshots, and enforce scene diversity.
- A normal strict material-package enqueue must execute through the real repository and worker
  into prepared-consumer validation. Directly rewriting a legacy test row into a strict identity
  is useful for repository edge cases, but cannot substitute for this integration regression.
- Real adapter MockTransport tests prove exact GLM route/model, final JPEG inputs, one physical
  POST even on timeout, and unchanged unrelated retry configuration.
- Real isolated PostgreSQL tests cover upgrade from populated legacy 0042, zero-data downgrade,
  populated downgrade refusal, SQL NULL negatives, concurrent claims, stale completion,
  calling/unknown recovery, retained siblings and independent six-audit readiness.
- End-to-end prepared consumer tests cover source/rights parity, byte-identical thumbnail,
  tampering/missing proofs, three-role policy consistency, pre-upload length rejection,
  escaped URL 256/257 boundaries and repeated-pass draft idempotency.
- Actual gzh validator: zero errors/warnings. Actual Chromium 320/430: no broken images or
  overflow, exact final body identity, and no external requests. Compaction must preserve
  text and visible computed styles/text-Range geometry, including inherited relative CSS and
  browser-default anchor-color edge cases. Compare complete screenshots and source/media
  bindings; anonymous wrapper counts are not an invariant. Test all actual replacement roles,
  not just the first over-budget article, and retain the unmodified baseline assets.
- Full relevant lint/type/tests with baseline failures explicitly classified. Scoped success
  is not an all-green general release gate.
- Fresh immutable source/image/config identity, backup, protected history, real safe window,
  migration and rollback checks precede activation. Existing dated operators are not reusable.
  Code/config rollback to an old application requires proving all incompatible state absent,
  including new weekly v2 checkpoints and governance inputs created before any strict Article,
  generation or audit rows. Otherwise retain compatible consumers or use a forward fix.
  The migration's populated-row downgrade fence alone is insufficient; old decoders silently
  ignoring the marker are not safe consumers for new strict state.
- Five sequential generation windows plus six audit windows may exceed one weekly wait/node
  budget. Verify total worker/queue/root timing before activation; frozen retry identity alone
  is not proof that the weekly edition reaches a terminal draft within its envelope.
- `test_official_account_weekly_queue_timing.py` uses real handlers, governance and retry
  seams with a serial fake producer and controlled clock. Keep concurrency 1, Article wait
  720 seconds, node allocation 900 seconds and root budget 3600 seconds. Queue time counts:
  three simulated 288.249-second Articles finish by observation at 866 seconds, with the third
  reusing its identity after the first timeout; accumulated root elapsed is 1732 seconds,
  not merely wall time. A 1000-second-per-Article case must expose root delegation denial
  while independent Articles complete; `result_unknown` never triggers regeneration.
  These are timing/identity regressions, not real model latency or whole-DAG completion claims.

## 7. Wrong vs correct

Wrong: `if audit.accepted: ready = True`, then legacy upload normalizes the cover again.

Correct: normalize upload bytes first; commit a lease-owned audit subject containing their SHA;
accept only identity-matched zero-issue completion; independently verify all six subjects in the
repository; revalidate the prepared projection; upload the exact bytes without transformation.

Wrong: propagate generated execution to every service, then add image keys everywhere to
silence Settings errors.

Correct: propagate only immutable policy to its four identity owners; restrict execution and
strict model prerequisites to the Article worker, preserving existing secret ownership.

Wrong: change compact-v1's implementation or raise the upload bound to fit a long article.

Correct: explicitly select a new version for new exports, retain v1 replay, reserve the same
256 characters per uploaded URL, and prove actual three-role visual parity and final size.
