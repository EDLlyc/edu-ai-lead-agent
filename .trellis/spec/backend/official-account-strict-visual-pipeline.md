# Prospective strict official-account visuals

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

Use the unchanged pure V2 renderer and project-owned theme `xiaosai-moyu-layout-v1`, then the
new `xiaosai-strict-inline-compact-v1` lossless projection. Runtime never reads personal skill
paths. Main's independent gzh-design validation remains a release artifact check.

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
  text and computed styles/geometry, including inherited relative CSS edge cases.
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
