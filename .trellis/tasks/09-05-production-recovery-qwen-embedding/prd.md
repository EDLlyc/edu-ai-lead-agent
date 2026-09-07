# Production recovery before staged Qwen embedding migration

## Goal

Prove that the deployed acquisition -> governance -> selection -> generation -> Enterprise
WeChat delivery workflow works again. The user's priority is operating production. Qwen
unification remains the follow-on direction, not a prerequisite for the first recovery release.

## Background and Confirmed Facts

- User approved task creation/planning and then approved the final recovery-first summary with
  "继续" on 2026-09-05. Implementation is authorized within this scope.
- The initial September 5 observations at 19:13-19:17 CST are in
  `research/production-baseline.md`: all 14 services ran, but the latest successful delivery was
  still September 2 at 12:30. Natural production then supplied the missing post-hotfix evidence
  on September 6: three accepted morning copy runs produced validated, audit-accepted packages
  and three formal text+image deliveries at 07:30-07:32 CST. More than two hours of subsequent
  two-second scheduler/dispatcher polling created no duplicate. Safe lineage and protected-state
  evidence are in `research/production-recovery-observation-2026-09-06.json`.
- Same-version terminal runs are not automatically recreated
  (`backend/app/infrastructure/db/copy_generation.py:168`).
- Production uses Zhipu brand embeddings. Qwen endpoint/key are absent from the protected
  environment, the content worker has no Qwen key, and both visual embedding tables are empty.
- Previous release/rollback evidence is in
  `.trellis/tasks/archive/2026-09/09-04-production-brand-embedding-hotfix/result.md`.

## Requirements

- R1 [P0]: Trace one fresh legitimate production run through all actual services. Separate
  process health, provider success, content acceptance, and terminal message delivery.
- R2 [P0]: Preserve configured recipient, review/quality gates, time windows, idempotency,
  delivered/unknown-outcome records and the seven historic queued copy jobs. Do not reopen
  terminal jobs, extend expired windows, or bump a version merely to force replay.
  Window source: `backend/app/domain/content_slots.py:74`; delivery authority:
  `.trellis/spec/backend/wecom-delivery.md`.
- R3 [P0]: Diagnose with bounded no-delivery checks, then correct only evidenced blockers.
  Keep current embedding/chat/image/reviewer providers for the first recovery release.
  Release only task-scoped changes; preserve the 59 pre-existing dirty worktree entries.
- R4 [P1]: Keep brand queries in the active index's identity. Any explicit provider pin must
  belong to a reversible config/image release. The auto resolver prefers Alibaba visual mode
  (`backend/app/core/config.py:554`); enabling it without migration can empty brand retrieval.
- R5 [P1]: Defer Qwen live cutover until authorized credentials, complete replacement indexes,
  relevance checks and rollback are available. The brand reindex tool is development-only
  (`backend/app/brand_embedding_reindex_main.py:277`); governance directly builds Zhipu
  embeddings (`backend/app/infrastructure/ai/factory.py:355`). This is not config-only work.
- R6 [P0]: Use only authorized configured accounts and bounded calls. Never expose private
  content, secrets, provider bodies or private object locations in task evidence.
- R7 [P0]: For future selection, require technology, AI or science education to be the
  substantive subject. General current affairs, diplomacy and trade cannot qualify solely from
  incidental technology/education keywords. Preserve genuinely substantive AI governance,
  scientific research, technology progress/products and science-education practice. Introduce
  an immutable new rule/config identity; preserve historical editorial/scoring replay. Do not
  blacklist names, countries or government sources, or reinterpret this relevance policy as
  a provider-safety classifier. The user explicitly approved this proposed boundary with
  "好的，请你处理" after the content review on September 5.

## Acceptance Criteria

- AC1 (R1, R6): Timestamped baseline/post-change evidence identifies release, service health,
  exact pipeline stage, and safe error codes.
- AC2 (R1, R3): A newly eligible selection yields accepted copy, a validated package and a formal
  `wecom_delivery_jobs.status=delivered` through the configured dispatcher. Record safe lineage
  IDs/timestamps. Until observed, recovery remains unverified, not complete.
- AC3 (R2): A repeat scheduler/dispatcher pass creates no duplicate delivery; protected historic
  jobs and already-delivered/unknown-outcome records remain unchanged.
- AC4 (R3, R4): Relevant unit/contract/integration tests, lint/type/format checks and applicable
  immutable-release gates pass. Verify coherent source/image/config rollback before activation.
- AC5 (R5): Handoff clearly separates delivered recovery from deferred Qwen work, partial-source
  failures and official-account paths with no actual execution evidence.
- AC6 (R7): Provider-free positive/negative/boundary cases prove substantive relevance before
  numeric eligibility, broad-pool admission or authoritative-source ordering. Cover incidental
  mentions in diplomatic/trade meetings, genuine AI governance, school science education,
  research/product news, title/body disagreement and title-only acquisition. Old literal
  editorial v2/v3 and scoring .6-.11 configurations retain their original semantics and hashes.
  New-version rollout must not replay expired selections or mutate frozen historical records.

## Out of Scope for the First Recovery Release

Qwen credential provisioning/live cutover; wholesale indexing or event reclustering; broad replay,
manual SQL queue resets, schedule extensions, new recipients, public WeChat publishing; unrelated
Reviewer, evaluation, resume or local WIP changes. Do not enable unused workflows just to report
all services green.

## Decisions and Deferred Items

### September 7 authorized official-account recovery

The user approved correcting the diagnosed weekly failure with "请你优化这个，问题，允许。"
after reviewing the September 7 production diagnosis. This extends the task to the already-enabled
official-account draft workflow. It does not authorize public publishing or unrelated model changes.

- R8 [P0]: Align prospective weekly material selection with the complete deterministic article
  source contract. Preserve original evidence and HTTPS validation; do not fabricate upgraded URLs.
  Reject incompatible inputs before paid generation and report a bounded deterministic reason.
- R9 [P0]: Recover the September 7 edition while preserving the two successful article runs and
  all original terminal attempts/checkpoints. A terminal run cannot be resumed through ordinary
  retry; use a reviewed explicit recovery identity/path if necessary. Complete three validated
  articles through the existing draft-only worker without duplicate drafts or public publishing.
- R10 [P0]: The weekly producer and draft consumer must resolve the same inbox on their shared
  volume. Correct the evidenced consumer path mismatch without changing credentials, mounts,
  read-only access, model providers, schedules, or publication permissions.
- AC7: Tests reproduce HTTP-source admission followed by article-input failure, prove selection
  excludes incompatible materials and supports eligible replacements, and classify deterministic
  input conflicts without exhausting transient retries.
- AC8: Production evidence identifies the recovered edition and draft job/items, retained original
  failed run and successful articles, with repeat-pass idempotency. If upstream generation or
  draft staging remains unsuccessful, report its actual state rather than marking recovery done.
- AC9: A mount-relative path regression proves producer/consumer inbox equivalence. Actual normal
  draft reconciliation discovers the exact recovered prepared batch and stages its three roles;
  later service polling or restart does not create another job or draft attempt.

Observed production run `0ae1c882-4254-561f-bdac-17d254c0c166` was scheduled at September 7
09:00 CST and became terminal at 09:02:11. Its `application_case:build_article` exhausted three
attempts because package `b290e00b-1e00-43a3-a69f-8f3bdb05137f` contains two HTTP source URLs.
No article run or model request was created for that material. At initial diagnosis two sibling
articles were ready with no WeChat draft jobs/items/attempts. The authorized compensation completed
the third article and prepared aggregate at 09:53 CST, preserving both siblings. The next actual
consumer check exposed a second defect: its inbox setting lies outside the shared volume mount.
At that diagnosis production was `5c560da` with Alembic 0042. The prevention release
`6154c78` subsequently completed; current evidence is in `research/weekly-recovery-status.md`.
The September 6 substantive-topic rollout is still pending; its dated operator is now expired.
Implement this repair on a separate exact-production worktree without mixing that policy change.

- Retain working Zhipu wiring until production delivery is proven. Investigate source errors,
  but expand connector fixes only if they block a qualifying run.
- The September 6 natural morning preparation/target completed without manual replay and now
  satisfies AC2/AC3. A separate `.12` release must not reuse the expired September 5 release
  baseline. Its reviewed one-shot transaction is fenced to the September 6 afternoon safe period,
  after the noon delivery window closes and before the evening preparation margin expires.
- No unresolved product question blocks this bounded recovery plan. Qwen deployment is deferred;
  the final planning summary has been approved for implementation.
- The subsequent substantive-topic proposal is now approved. Earlier content-review records
  correctly describe the decision as pending at their observation time; this approval supersedes
  that pending status without rewriting those historical records. Existing HTTP-400 handling
  already isolates a refused job, so no provider/retry change or repeat refused-input call is
  included. A narrower candidate policy does not itself prove production delivery recovery.

### September 7 approved visual-quality repair and one-preview gate

After the image diagnosis and proposed fix/one-preview summary, the user approved with
"好的，请你处理". This authorizes implementation and bounded existing-provider generation
for one new preview, not replacement of the three existing drafts or public publishing.

- R11 [P0]: Produce one fresh scene-illustrated preview from the existing application-case
  article, preserving its text, factual/source bindings and actual news-image bytes. Use the
  existing configured image-generation channel and approved brand references. Do not place
  catalog avatars directly as new body illustrations or fabricate news photographs.
- R12 [P0]: Separate vision-review identity from text generation. Image review uses direct
  Zhipu `glm-5v-turbo` only. Generation and judging remain separate capabilities; do not enable
  another judge, import unrelated local evaluation WIP or migrate Qwen indexes.
- R13 [P0]: Check final body/cover resolution, integrity, repetitions and article/section
  relevance before declaring the preview accepted. Preserve strict unavailability/unknown
  outcomes; no invented scores, human labels, database records or publication-ready claims.
- R14 [P0]: Use a fresh private preview directory and actual before-call intent/result ledger;
  keep existing production configuration, workers, drafts, article runs and source packages
  unchanged. A subsequent preview approval is required before any draft replacement or live
  automatic-pipeline activation.
- AC10 (R11, R13): One preview contains five distinct reference-conditioned 1536×1024 JPEG
  scenes, an article-relevant landscape cover and the original acquired context image; article
  and source hashes match the captured baseline. Exact 320/430 px checks prove images load,
  no horizontal overflow and no external browser requests.
- AC11 (R12, R13): Tests and real bounded call evidence identify `glm-5v-turbo`, not
  `AI_CHAT_MODEL`, and bind each body/cover verdict to the final delivered bytes and required
  criteria. Unavailable, rejected, malformed or model-mismatched results cannot pass the new
  preview gate. Existing production `observe` remains non-blocking and default-off.
- AC12 (R14): Repeat invocation cannot repeat billed generation for an existing intent or
  unknown outcome; bounded input/path/hash and no-clobber tests pass. Live evidence proves
  the three existing article/draft identities and attempt counts remain unchanged. Handoff
  explicitly separates the accepted preview from the not-yet-activated production fix.

Scope and diagnosis: `research/visual-production-evidence-20260907.md`,
`research/visual-baseline-audit.md`, and `research/visual-preview-route.md`. No unresolved
product decision blocks this one-preview implementation; the later activation gate is retained.

September 7, 11:49 Asia/Shanghai: isolated-preview AC10-AC12 are now evidenced in
`research/visual-preview-live-evidence-20260907.md`: five actual native landscape generations,
six accepted GLM final-image audits, original source/media preserved, gzh and exact mobile checks
passed, unchanged production article/draft identities. The preview is machine-accepted only;
user sample approval, commit-plan confirmation and production integration remain pending.

### Accepted sample and proposed prospective production integration

The subsequent user message, "好的，我感觉没有什么大问题，请你处理吧", accepts the visible
sample and requests continuing the production integration. This is conversational acceptance;
the original machine evidence and `human_approved=false` creation record stay immutable. No
database manual-review row is fabricated. The user also explicitly asks to keep using `gzh-design`.

Confirmed downstream facts are in `research/visual-production-export-route.md`: normal export
does not use the sample's V2 renderer; current draft preparation changes final cover bytes; and
re-exporting old Articles creates new draft jobs, not replacements. Existing code has no safe
draft-update/replacement capability. The following implementation/activation scope is proposed
for a single final confirmation, not represented as already deployed:

- R15 [P0]: Apply the accepted visual style to future legitimate weekly runs through a new
  frozen per-run/per-week policy; retain original ready, queued, terminal and unknown-outcome
  identities and literal legacy processing. Do not replay or re-export the delivered September 7
  edition or alter its three existing drafts.
- R16 [P0]: Use five native landscape reference-conditioned generations and six strict direct-GLM
  audits with durable pre-call intents and no ambiguous paid replay. Audit the exact final
  generated upload images and cover derivative, not only a larger publication image. No catalog
  fallback, old unrelated cover, invented score or unavailable-as-pass outcome.
- R17 [P0]: Use the project-owned `gzh-design` Xiaosai renderer for new prepared children;
  retain original news images and rights/source metadata, with explicit derivative provenance
  where upload conversion is necessary. Preserve old prepared formats and final audited bytes
  through the draft consumer. Reject invalid/over-budget HTML before social writes.
- AC13 (R15): Restart and config-change tests prove old runs keep old policy; new weekly branches
  share their frozen policy. Before/after activation preserves all original Article/render/draft
  IDs and successful/unknown attempt counts; repeated reconciliation creates no duplicate.
- AC14 (R16): New durable execution proves exact native source dimensions, final upload byte SHA
  and six issue-free accepted GLM results; a missing/rejected/unknown audit prevents ready export
  before any social side effect. New cover bytes are not transformed again after audit.
- AC15 (R17): Representative new artifacts with zero/one/two source images pass gzh compliance,
  320/430 mobile checks, source/rights parity, prospective prepared-format integrity and URL-size
  budgets. Legacy fixtures/identities remain literal. Production success requires actual normal
  new-run/draft evidence, not the already-completed local sample.

Out of scope: replacing/deleting existing drafts, public publish/mass send, historical catch-up,
Qwen migration, new providers, schedule/recipient changes, redefinition of production observe,
and importing unrelated dirty main work. Strict failures stay visible for review.

The user subsequently confirmed the final new-run-only summary with "好的，请你处理". R15–R17
and AC13–AC15 are approved for implementation. Existing drafts remain unchanged; no publication,
mass send, historical replay or new provider is authorized. Commit and production activation must
still satisfy their executable quality/release gates; approval does not imply those steps are done.

### Approved minimal startup and queue repair

The user accepted the release-preflight findings and requested: "好的，请你处理，也不需要这么严格，
能跑起来就行。" Prioritize the concrete startup/wiring blockers and a useful queue regression;
do not expand this stage into unrelated historic-test cleanup or a release-framework rewrite.

- R18 [P0]: Make the strict feature start correctly through the real per-service Compose topology.
  Policy-only API/scheduler/DAG processes can freeze the same strict Article identity without
  acquiring model execution capability. Keep the actual Article worker's provider checks.
- R19 [P0]: Demonstrate how three concurrent weekly Article waits complete or fail visibly behind
  the existing single generator. A timed-out wait must reuse the same Article on retry, without
  extra generation or changing old drafts. Keep current schedule, concurrency and budget values.
- AC16: Actual full-profile Compose environment projections construct real Settings in both
  default-off and strict configurations; exact policy identity agrees across its owners and
  secret presence does not expand. Missing/wrong executor credentials/model/base remain rejected.
- AC17: Fast provider-free three-role queue/retry tests show completion within the existing budget
  for a representative controlled duration, correct timeout/unknown outcomes and no duplicate
  Article generation. Synthetic timing evidence is not a live latency guarantee.

No new provider calls, production configuration change, push, migration, old-week replay or
publication is included in this local repair approval. Preserve the implemented exact-byte audit
and durable idempotency protections; "make it run" is not permission to forge accepted results.
