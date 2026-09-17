# Prospective strict official-account visuals

Native generation failure diagnostics, proved non-applied retries, and the explicit
September 16 one-time compensated operation are specified in
[`official-account-image-recovery.md`](./official-account-image-recovery.md).
The latter preserves original unknown attempts and accepted content while advancing
only the authorized current slot projection; it never makes unknown outcomes an
ordinary automatic retry. All existing visual/publishing boundaries below remain.

## Prospective V3 resilient/advisory policy

### 1. Scope / trigger

New future runs may freeze
`official-account-visual-pipeline-v3-resilient-advisory`. This is an immutable third
policy; it does not reinterpret V1 strict, V2 observe, the September 16 recovered
run, or an already verified draft.

### 2. Signatures

- `StrictVisualPipelineVersion` includes
  `official-account-visual-pipeline-v3-resilient-advisory`.
- `RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS = 3` is the closed per-body-slot budget.
- `resilient_visual_provider_request_fingerprint(logical, physical_attempt)` derives
  the provider identity; `resilient_visual_attempt_ordinal(slot, physical_attempt)`
  maps the five slots to durable ordinals 101--115.
- `StrictGeneratedVisualClaim` returns both `provider_request_fingerprint` and
  `physical_attempt_number`; `persist_generated_visual(...)` and
  `fail_generated_visual(...)` must receive the same pair.
- Prepared artifacts use
  `wechat-draft-prepared-child-v4-resilient-advisory`.
- Alembic revision `20260916_0048` removes the policy-blind body-checksum unique
  index before any run may freeze V3.

### 3. Contracts

Each of the five body slots owns at most three physical generation attempts. The
logical plan/request fingerprint remains stable, while each physical attempt derives
a distinct provider request fingerprint from that plan and attempt number. The
existing `official_account_article_attempts` table is the durable physical ledger;
its V3 ordinals are disjoint from historical run-attempt ordinals. Claiming happens
under the fenced run/visual row lock, completed slots are reused, failed attempts are
never deleted, and success/failure persistence must prove that the supplied physical
attempt is exactly the next current ledger entry. Three consumed entries are terminal;
there is no fourth provider call after restart or concurrent claim.

Migration `20260916_0048` removes the old policy-blind unique body-checksum index,
because V3 permits exact duplication as an observation. The fenced media repository
retains the same duplicate-check rejection for V1/V2 before insert. Downgrade refuses
while any V3 run identity exists, rather than exposing that state to an old decoder.

Provider rejection, provider outage/rate/quota failure, invalid provider raster/output,
and an ambiguity observed while the current owner still holds authority may consume
the next physical attempt. Invalid credentials, invalid configuration/input, provider
result-identity mismatch, expired execution window and lost lease authority do not.
An orphaned `generating` intent is recorded as unknown with
`reason=lease_authority_lost` and remains terminal; a successor must not turn lease
loss into another paid dispatch. The one-shot transport remains one POST per physical
claim, so application-level durable claims—not hidden HTTP retries—own the budget.

V3 still executes and persists all six final-image audits. Model rejection,
unavailability/result-unknown, ordinary relevance/style/composition findings, exact
or perceptual sibling duplication, and catalogue reuse are advisory. Audit provider,
model or request-identity mismatch remains blocking. Raster decoding, native/final
geometry, byte and checksum integrity, five-body/one-cover count, stored subject and
artifact lineage, prepared HTML/media correspondence, draft-only authority and all
factual Article audits remain hard gates.

Prepared output uses the closed
`wechat-draft-prepared-child-v4-resilient-advisory` envelope. Producer, canonical
consumer and WeChat preparer must preserve the real audit statuses/codes and recompute
advisory quality findings without weakening byte, subject or lineage validation.
V1/V2 envelopes and serialized evidence remain literal.

The production switch is
`OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION=official-account-visual-pipeline-v3-resilient-advisory`.
Keep `IMAGE_MAX_ATTEMPTS=1`: the adapter is one physical call per durable claim, while
V3 owns the three-attempt policy. Apply migration `20260916_0048` before changing the
environment value. Recreate the identity-producing scheduler/worker processes after
the switch; never retrofit the value into an already frozen run.

### 4. Validation & error matrix

| Condition | V3 result |
| --- | --- |
| Provider rejection, outage/rate/quota response, invalid raster/output, current-owner ambiguity | Persist the attempt and claim the next distinct attempt when fewer than three are consumed |
| Third retryable failure | Persist terminal failure; never issue a fourth provider request |
| Invalid credentials, configuration or input limit | Terminal; no next physical request |
| Provider/model/request result-identity mismatch | Terminal; do not accept or retry the mismatched result |
| Lost lease or orphaned generating intent | Persist `lease_authority_lost` as unknown/terminal; successor performs no paid retry |
| Expired frozen execution window | Terminal before provider dispatch |
| Reviewer rejected/unavailable/result-unknown; ordinary relevance/style/composition issue | Persist as advisory and continue |
| Exact/perceptual sibling duplicate, catalogue reuse or reference echo | Persist as advisory and continue only for V3 |
| Audit provider/model/request identity mismatch | Hard-block readiness |
| Bad raster, geometry/count/checksum, subject/lineage, HTML/media or draft authority | Hard-block readiness |

### 5. Good / base / bad cases

- Good: attempts one and two return invalid output, attempt three succeeds under a
  third provider key, five body images and six audits reach a draft-only ready state.
- Base: the first request succeeds; the remaining V3 budget is never consumed and a
  restart reuses the content-addressed artifact.
- Good advisory: two body slots contain identical bytes or echo the approved reference;
  V3 records the finding and continues, while V1/V2 still reject it.
- Bad: a successor worker sees an orphaned paid call and sends another request, a stale
  attempt writes into the current slot, an inner HTTP retry hides extra POSTs, or an
  existing V1/V2 run is reinterpreted as V3.

### 6. Tests required

Required regressions cover success after two failures, three-failure exhaustion,
distinct physical provider keys, ready-slot reuse, restart/concurrent claim fencing,
lost-lease no-retry, stale physical-result rejection, V1/V2 parity, advisory review
matrices and the V3 prepared-envelope round trip through the real draft consumer.
Migration tests must assert upgrade from 0047, absence of the checksum index, V1/V2
repository-level duplicate refusal, V3 duplicate acceptance, downgrade success before
V3 data, and downgrade refusal after a V3 run exists.

### 7. Wrong vs correct

Wrong: set `IMAGE_MAX_ATTEMPTS=3`, let the provider adapter retry internally, remove
all image checks, or drop duplicate checks globally.

Correct: keep one physical call per claim, persist each attempt under its own key,
advance only under the fenced V3 repository transition, retain deterministic
byte/subject/lineage gates, and make only the named quality findings advisory.

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

## Scenario: standardized V5 fixed Cheng Yue/Xiaosai framing

### 1. Scope / trigger

Future native V5 prepared Articles add one deterministic Cheng Yue introduction
banner before the existing cover and replace the legacy signature-only ending with
one deterministic Xiaosai final region after the unchanged source cards. Historical V1,
default V2, V4 and already-prepared footer-v1 artifacts retain their exact ending
and remain reconstructable. On September 11 the user supplied and approved one
fixed `小赛AI星球` banner containing its QR code; that asset supersedes the temporary
blank-QR decision for newly built V5 artifacts only. On September 14 the user
required the already-approved `程岳` introduction banner and that footer to frame
every future automatically prepared Article; this does not rewrite old children.

### 2. Signatures

- Legacy `XiaosaiFooterAsset` remains a frozen typed projection with
  `version=official-account-xiaosai-final-cta-v1`, `role=footer`, `ordinal=0`,
  `path=assets/xiaosai-footer.jpg`, approved exact `characters=("xiao-sai",)`,
  catalog/ref/master/publication identity, decoded geometry and byte identity.
- New `XiaosaiMarketingFooterAsset` uses
  `version=official-account-xiaosai-final-cta-v2`, `role=footer`, `ordinal=0`,
  `path=assets/xiaosai-marketing-footer.jpg`, `qr_state=ready`, and purpose
  `follow-xiaosai-official-account`. It binds the exact packaged 2,092,946-byte
  2048x1152 PNG master SHA-256
  `f4026a63229b6239997e2b8d0bac540d9a06c1ead8a933ff8dd0365333556996`
  and the deterministic 383,664-byte JPEG publication SHA-256
  `9040f474f43e20289e26a0de52c385e7c86f7f2ea3aa1e287525160bf355c3b4`.
- `ChengyueIntroductionHeaderAsset` uses
  `version=official-account-chengyue-intro-header-v1`, `role=header`, `ordinal=0`,
  `path=assets/chengyue-top-intro.jpg`, and purpose
  `introduce-chengyue-xiaosai-guide`. It binds the exact 5,882,944-byte 3840x1920
  PNG master SHA-256
  `8821b4f367ea2aac7309a38171794c6dc4b3f90ee5a62a75510a3508d28169ee`
  to the 716,140-byte JPEG publication SHA-256
  `bf3a505a4f61738132c869901f889a5f172d1291509b8963a6ce2d4785988223`.
- `normalize_official_account_upload_header` owns
  `official-account-upload-header-v1`: convert the RGB master with JPEG quality 88,
  `optimize=True` and 4:4:4 (`subsampling=0`), without crop or resize.
- `normalize_official_account_upload_footer` owns
  `official-account-upload-footer-v1`. It retains 2048x1152 geometry and the full
  composition, performs no crop/downscale/repaint, and converts the oversized PNG
  only because the WeChat inline byte limit is `1024*1024-1`.
- `OfficialAccountLocalMediaResolver.read_official_account_marketing_framing(article)`
  atomically returns header/publication and footer/publication independently of
  Article assignment zero or the mutable private catalog. The legacy
  `read_xiaosai_footer`/catalog behavior remains for exact persisted replay.
- `CHENGYUE_HEADER_BODY_SPACING_VERSION` is
  `official-account-chengyue-header-body-spacing-v1`.
  `render_editor_handoff_v2_body(..., header_body_spacing=None)` keeps the
  historical header-to-cover bytes; new canonical prepared construction passes
  the versioned value and records it as `header_body_spacing_version`.
- Renderer and prepared-projection inputs accept the typed v1/v2 union while their
  `None` defaults remain historical. New V5 ownership always supplies the current
  header plus footer-v2.

### 3. Contracts

Both source masters and both publication derivatives are repo-owned runtime assets
included by `COPY app ./app`. The loader verifies exact paths, no symlinks, hashes,
sizes and deterministic master-to-publication output for the complete pair before
the owner packages either publication. The pure consumer validates each literal
descriptor, publication hash, size, MIME and dimensions. Neither current settings
nor Article reference selection can substitute another framing asset. Footer-v1
keeps its old assignment-zero catalog validation path for persisted-artifact replay.

New validated V5 ownership requires exactly one header and one footer; non-V5
evidence forbids both. Keep them outside the five generated body assets and six
model-audit subjects. Their manifest roles/paths are distinct from `body`, `context`
and `cover`, but both participate in the canonical file set, child fingerprint,
HTML image correspondence, escaped upload-URL reserve and actual WeChat inline order.
Canonical current manifests place the header descriptor first and footer descriptor
last; historical V5 footer-v1 children without the new header remain reconstructable.

The first visible block and first `<img>` are the header banner, before the existing
generated cover. New prepared artifacts insert exactly one WeChat-visible blank line
between the closing header wrapper and that cover, represented by one inline-styled
`p > span[leaf] > br` spacer rather than source-code whitespace. The spacer is not
part of the header image wrapper and must not change the image bytes or image style.
Header-bearing V5 artifacts created before this rule have no
`header_body_spacing_version`; canonical validation must interpret that absence as
the historical no-spacer rendering instead of silently upgrading their bytes. The
final visible order is conclusion, unchanged sources, the exact
`Article.author` signature once, then the footer banner as the last visible content.
Both wrappers have `margin:0`; both images use
`max-width:100%;height:auto;display:block;margin:0 auto`, with no forced
`width:100%`, crop or rounded-corner treatment and no visible caption. Remove
footer-v1's separate portrait, duplicated marketing prose and `二维码待补` block from
new artifacts. Do not emit the legacy likes/在看/转发 CTA in addition to this region.

### 4. Validation and error matrix

| Condition | Required behavior |
| --- | --- |
| Homogeneous V5 evidence plus exact packaged framing | Render header first and footer last, each exactly once |
| New V5 manifest carries `official-account-chengyue-header-body-spacing-v1` | Render exactly one visible blank line after the header and before the cover |
| Historical header-bearing V5 manifest omits `header_body_spacing_version` | Rebuild its original no-spacer HTML byte-for-byte |
| Spacing version is unknown, duplicated, or used without the fixed header | Reject canonical construction/validation before upload |
| Current V5 header/footer absent, duplicated, reordered or on another role/path/ordinal | Reject canonical prepared construction before upload |
| V4/default renderer carries framing | Reject prepared construction; historical renderer output remains exact |
| Either packaged master, deterministic derivative, descriptor, geometry or publication bytes disagree | Reject producer/consumer reconstruction and make zero provider/social calls |
| A caller tries to substitute the mutable catalog/Article assignment for v2 | Ignore it and resolve only the sealed packaged asset |

### 5. Good / base / bad cases

Good: a new V5 Article begins with the sealed Cheng Yue banner and ends once with
`程岳`, followed by the sealed Xiaosai banner; uploads preserve that first/last order.
Base: a V4 child retains signature-only bytes and an existing
footer-v1 child rebuilds with its old portrait/blank reserve bytes. Bad: upload the
masters despite the inline limit, regenerate/repaint the supplied designs, bind v2
to assignment zero, or append an image without manifest bytes.

### 6. Tests required

Exercise both deterministic master conversions, packaged atomic loader, resolver,
actual prepared owner, canonical consumer, draft preparer and `httpx.MockTransport`.
Assert one author/signature, unchanged news sources/credits, exact first/last
publication uploads and CDN rewrites, no duplicate copy/placeholder or banner
captions, mobile-safe styling and two extra inline uploads. Cover either
master/publication/descriptor/order tamper with zero HTTP calls,
V5-required/V4-forbidden, footer-v1 replay, stable goldens, gzh zero warnings/errors,
and 320/430 rendering without overflow or broken images.
For the header/body gap, assert the exact order `header -> one spacer -> cover`,
the serialized version, unknown-version rejection, unchanged upload URL rewriting,
and a fixed historical header-bearing V5 HTML/fingerprint with the field absent.

### 7. Wrong vs correct

Wrong: copy image URLs into HTML without typed media or recreate either design through
a model. Correct: bind each exact master to its deterministic byte-bounded derivative,
carry typed `header`/`footer` through prepared projection/canonical validation, and
upload the same bytes first/last without changing either supplied composition.

Wrong: append a spacer whenever a header happens to be present, which changes the
bytes reconstructed for existing prepared artifacts. Correct: opt new construction
into the versioned spacing contract and treat a missing manifest field as the frozen
historical no-spacer behavior.

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
- Migration `20260907_0043` adds generated-intent ownership/geometry columns and
  `official_account_strict_visual_audits`; `20260909_0045` adds the Chinese-family prompt;
  `20260914_0046` broadens only the native model check to legacy `gpt-image-2` plus current
  `gpt-image-2.5-sunburst`, without rewriting historical rows. Its downgrade refuses while a
  current-model strict row exists.

## 3. Contracts

### Configuration and immutable identities

`OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION` defaults absent/null and selects identity,
not execution capability. Compose supplies it only to API, weekly scheduler/DAG and Article
worker. These four owners must select the same full V4 identity even where image credentials
are absent. Strict policy requires local Zhipu Articles with semantic reference retrieval off;
deterministic selection must not claim embedding retrieval.

Only the Article worker receives the global `OFFICIAL_ACCOUNT_LOCAL_GENERATED_VISUALS_ENABLED`
value as execution permission. Shared service defaults pin it false and image quality mode off.
Strict execution additionally requires enabled images, the Comfly relay
`gpt-image-2.5-sunburst` route, exact vision base `https://open.bigmodel.cn/api/paas/v4`, nonblank
direct Zhipu credentials and `IMAGE_QUALITY_AUDIT_MODEL=glm-5v-turbo`; Compose injects the audit
model only into that worker. `IMAGE_MODEL` owns the current Comfly default, while
`TOAPIS_IMAGE_MODEL="gpt-image-2"` remains the provider-specific ToAPIs default. Strict persistence
accepts both values so historical rows remain readable, but every other model remains invalid.
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
| Strict generated visual uses legacy/current Comfly model | Preserve legacy rows and accept current rows under `20260914_0046` |
| Strict generated visual uses any other model | Repository and PostgreSQL constraint reject it |
| Downgrade requested while a current-model strict row exists | Refuse at `20260914_0046`; do not rewrite or delete the row |
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

Good: upgrading from `20260909_0045` retains an existing `gpt-image-2` strict row byte-for-byte,
then accepts a new `gpt-image-2.5-sunburst` row with the same geometry and lineage constraints.

Base: existing absent-policy ready Articles and their already-successful draft job remain
unchanged after deploying compatible code. Observe remains observational, not a strict verdict.

Bad: restarting an old weekly input under today's strict settings generates replacement
Articles; or a reviewed 1536×654 preview cover is subsequently cropped to a different unreviewed
1175×500 upload. Neither is an acceptable implementation of this contract.

Bad: changing only the Settings default while leaving the strict policy, repository, ORM check or
database constraint pinned to the old model; the process may start but fail after a paid result.

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
- `test_official_account_image_model_migration.py` upgrades a populated `20260909_0045` database,
  verifies both model identities in real PostgreSQL, rejects an unsupported model, preserves the
  legacy row, and proves current-model data fences downgrade.
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

Wrong: update `IMAGE_MODEL` and the worker startup validator but leave the strict database model
check at `gpt-image-2`.

Correct: update the provider default, strict policy, repository validators, ORM metadata and a
forward Alembic constraint together; accept the old identity only for compatibility and never
rewrite its provenance.

Wrong: change compact-v1's implementation or raise the upload bound to fit a long article.

Correct: explicitly select a new version for new exports, retain v1 replay, reserve the same
256 characters per uploaded URL, and prove actual three-role visual parity and final size.
