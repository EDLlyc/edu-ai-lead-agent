# Research: Durable production visual pipeline after preview acceptance

- Query: What remains to let new normal official-account article-worker runs produce five native 1536x1024 reference-conditioned scenes, strict direct-Zhipu GLM-5V-Turbo final-byte review, and a relevant derived/reviewed cover without replaying old work?
- Scope: Internal, read-only inspection of candidate runtime and existing project contracts; no providers, SSH, database writes, service tests, git operations, or product edits.
- Date: 2026-09-07
- Candidate root: `/root/projects/edu-ai-lead-agent/.trellis/worktrees/visual-quality-preview`.
- Task root: `/root/projects/edu-ai-lead-agent/.trellis/tasks/09-05-production-recovery-qwen-embedding`.
- Context: The user accepted the visible sample and authorized proceeding. Main owns the exact activation/draft scope and gzh-design skill use. This report is an implementation proposal, not evidence of activation.

## Findings

### Bottom line

The new preview fixes the model adapter and native-size transport, but normal production still follows the old executor. Turning on `OFFICIAL_ACCOUNT_LOCAL_GENERATED_VISUALS_ENABLED` and `IMAGE_QUALITY_EVAL_MODE=observe` is insufficient: it sends square generation requests, accepts observation failures, keeps the old material-package cover, and has no independent durable audit intent.

The smallest robust integration reuses the article worker and its generated-visual intent/MinIO/lease machinery, adds a **new frozen visual-pipeline policy** for newly enqueued runs, and adds a **strict final-media audit intent/result layer**. Existing off/observe behavior, historical V1–V10 article/render identities, current prepared artifacts, and existing ready/failed/result-unknown jobs must stay unchanged. The local preview journal is not a substitute for those database contracts.

### Files found and responsibilities

All code paths below are relative to the candidate root unless explicitly marked root spec/task.

| File | Responsibility / important anchor |
|---|---|
| `backend/app/official_account_worker_main.py:95` | Lazy image client after application intent; executor wiring at 180. |
| `backend/app/application/services/official_account_local.py:749` | Durable article executor, existing image generation, optional nonblocking observation, local media/draft completion. |
| `backend/app/application/services/official_account_visual_generation.py:182` | Production body plan/fingerprint; final JPEG normalization at 336/495. |
| `backend/app/application/services/official_account_visual_preview.py:389` | Preview-only reference selection, stricter exact-byte audit criteria, batch image checks, new cover crop. |
| `backend/app/official_account_visual_preview_main.py:220` | Isolated transport-intent journal and one-attempt provider composition. |
| `backend/app/application/ports/official_account_local.py:37` | Frozen run identity; generated-plan/result ports at 157/190/205. |
| `backend/app/infrastructure/official_account_runtime.py:11` | Shared CLI/weekly runtime identity constructor. |
| `backend/app/api/v1/routes/official_account_local.py:677` | Separate API identity constructor; changes must remain equivalent. |
| `backend/app/infrastructure/db/official_account_local.py:215` | Idempotent enqueue, leases, generated intent/results, media lineage, final ready transition. |
| `backend/app/infrastructure/db/models.py:4234` | Generated visual, optional observer eval, and local media tables / SQL constraints. |
| `backend/app/infrastructure/official_account_catalog.py:79` | Approved reference publication adapter; 256px lower bound, exact 41-asset catalog, metadata revalidation. |
| `backend/app/application/services/official_account_media_semantic.py:96` | Optional embedding-backed selection with deterministic fallback. |
| `backend/app/infrastructure/official_account_media.py:111` | Byte resolver; generated-body validation currently excludes cover. |
| `backend/app/infrastructure/ai/factory.py:229` | Image-quality observer construction; current generic settings/max-attempts behavior. |
| `backend/app/infrastructure/ai/image_validation.py:185` | Strict HTTP/content parser and independent vision model response checking. |
| `backend/app/application/services/official_account_weekly_production.py:191` | Weekly build enqueue/poll using handler-global article identity, then prepared export. |
| `backend/app/official_account_weekly_scheduler_main.py:96` | Scheduled weekly identity and preservation of an existing weekly run. |
| `backend/app/infrastructure/official_account_weekly_dag_governance.py:60` | 15-minute node envelope and 60-minute root envelope; model calls are not counted in this DAG. |

### Current run-to-image route and durability guarantees

1. `official_account_identity_from_settings(settings, provider, model)` freezes article settings and optional generated plan/prompt version only when the provider is Zhipu and the generation flag is enabled (`official_account_runtime.py:17–47`). API has a duplicate constructor (`routes/official_account_local.py:683–714`). Image provider/model, audit policy/model, requested native geometry, cover profile, and prepared-render policy are **not** part of the current run identity.
2. `run_request_fingerprint(source_fingerprint, generation_mode, identity)` removes optional absent identity fields before hashing (`services/official_account_local.py:151–175`). Enqueue uses unique request fingerprint and returns the existing row for any status (`db/official_account_local.py:223–264`); it does not reopen a terminal row.
3. Claim selects only due queued or expired running rows, locks with `skip_locked`, increments attempt number, and writes a fresh token (`db/official_account_local.py:728–783`). It does not claim ready, failed, review-required, or result-unknown rows. `_locked_fenced_run` checks running status, token, and attempt number (`1877–1893`). The heartbeat does not abort an in-progress provider call; a stale result must remain fenced on completion.
4. Executor validates text and the legacy factual audit before render/body generation (`services/official_account_local.py:982–1072`). Catalog selection and article media snapshot are persisted, then reused against refreshed metadata (`1080–1092`). Old runs without generated versions still do zero generation even if the worker's current enable flag changes (`1371–1395`). Old generated runs with the flag disabled fail explicitly rather than silently falling back.
5. Each generated body slot has one durable intent committed **before** `ImageGenerator.generate` (`1437–1514`; repository `342–405`). The row is run/article/render/ordinal scoped, with unique request fingerprint and render+ordinal constraints. A recovered generating intent becomes result-unknown rather than being submitted again (`1464–1477`). Ready siblings are reused (`1478–1480`); failed/result-unknown visual rows are never resubmitted.
6. Generation bytes are normalized, written immutably to MinIO, optionally observed, then committed ready with the observer child atomically (`1515–1547`; repository `407–541`). This is crash-safe against **duplicate generation**, but not complete paid-output/accounting recovery: a crash during audit leaves a known stored image without durable result metadata and a parent still called `generating`.
7. Local body/context media and cover are staged, then `persist_draft` validates media rows and atomically sets the article run ready (`1246–1369`; repository `1548–1650`). There is no strict audit gate in this transaction today.

### Gap matrix

| Requirement | Current implementation | Required additive behavior |
|---|---|---|
| Native 1536x1024 | Request at `services/official_account_local.py:1490` omits `output_size`; port default is 1024x1024 (`ports/image_generation.py:37`). Publication uses `ImageOps.fit` to 1536x1024 (`visual_generation.py:495–535`). | New plan version binds requested native geometry and exact prompt hash, explicitly sends landscape, rejects non-native raw output before normalizing. Leave all old plan fingerprints/default callers frozen. |
| Complete references, no tiny avatar | Catalog admits 256px dimensions (`official_account_catalog.py:93–94`); returned candidate currently omits width/height (`106–124`). Preview filters minimum short-edge 512 (`visual_preview.py:391–402`). | Versioned generation-reference eligibility using verified decoded/publication dimensions before any paid call. Do not globally reject one old tiny asset from the exact 41-item catalog and break historical selection. |
| Exactly five scene slots | Media V4 chooses min(candidate count, five, sections); article generation V7 supplies 5–7 sections. Preview can use three approved references across five distinct block anchors. | Preflight the whole new run's five anchors and reference assignments. Distinct output scenes are mandatory; whether five distinct references are mandatory must be explicit. Filtering to three reference candidates must not silently reduce the article to three body slots. |
| Deterministic reference truth | Semantic ranker disabled path returns deterministic fallback without model construction (`official_account_media_semantic.py:120–128`). | Keep deterministic selection while Qwen is unavailable. Pin selection version/input hashes and record real `deterministic_tag`; no embedding-call claims. |
| Strict final-body audit | Observer is optional and nonblocking (`services/official_account_local.py:1577–1696`); failures become unavailable evidence. | Separate immutable strict policy; accepted must be literal true, issues empty, exact request/model/route identity, correct publication SHA. Warning, rejection, unavailable, malformed/mismatched responses cannot create a ready draft. |
| Direct Zhipu and one shot | Factory uses independent model setting now, but accepts arbitrary HTTPS base URL and uses global `AI_MAX_ATTEMPTS` (`factory.py:253–270`; adapter `image_validation.py:119–153`). | New strict construction validates direct Zhipu endpoint and exact `glm-5v-turbo`, uses an owned one-attempt transport with redirects/environment proxy behavior reviewed. Do not set global AI attempts to one and accidentally change text workflows. |
| Audit intent and crash accounting | Eval table is result-only and unique per generated visual (`models.py:4398–4493`); no `calling` row or attempt bound before audit. | Add independent durable intent/status/result for each final body/cover subject; one committed claim/intent permits one POST. Reclaimed ambiguous call becomes result-unknown, never a new call. Keep legacy observer table/semantics unchanged. |
| Relevant cover | Multimodal branch calls `repository.load_source_media(claimed)` (`services/official_account_local.py:1248–1252`), i.e. the old material image, not a new body scene. | Freeze deterministic selection of a current accepted body scene, derive safe cover bytes, bind source visual/SHA/crop/profile to the final asset and audit that actual final cover. No sixth generation is inherently necessary. |
| Derived cover lineage | Repository rejects generated visual media for non-body roles (`db/official_account_local.py:1377–1392`); resolver also requires body and exact original generated hash (`official_account_media.py:201–234`). | Add a strictly typed/versioned generated-cover derivative branch, not a fake source image/fixture/generated-body row. Preserve parent visual identity and separate derivative SHA/profile; verify its exact stored bytes. |
| Final upload-byte audit | Downstream researcher found WeChat preparer re-crops/re-encodes covers to <64 KiB (`wechat_official_account_draft.py:521,743`). | Normalize the upload cover before its strict audit and prove downstream new-policy preparation preserves those exact bytes; otherwise a separate audited derivative is required. A passed preview 1536x654 crop is not proof of the later thumbnail. |
| Near-duplicates/catalog substitutions | Normal executor checks exact output SHA uniqueness only (`services/official_account_local.py:1103`, `1181`). Preview adds dHash and catalog comparators (`visual_preview.py:658–687`). | Reuse/extract provider-free batch validation as a shared pure helper, with named thresholds/version and durable bounded verdict. Do not regenerate on failed quality under the same request identity. |
| Prospective identity | Weekly build uses `self._article_identity` loaded at worker startup (`weekly_production.py:195–198`). | Bind intended article/visual policy to new frozen weekly input or a before-enqueue article link. Retried old weekly nodes must not silently enqueue a second article after settings changed. |

### Important compatibility details

- Current `OfficialAccountVersionIdentity` has optional plan/prompt fields but no visual policy field (`ports/official_account_local.py:37–59`). Proposed common seam: optional `visual_pipeline_version`, omitted for **every** old/off/fixture fingerprint. A strict literal can map to a fully validated immutable policy snapshot: native size, generation provider/model, reference policy, judge route/model/rubric, cover profile, prepared-render profile, and fixed call ceilings. If these remain configurable, freeze their actual values too rather than merely recording a policy label.
- Adding a run policy does **not automatically require** changing the ArticlePackage text schema or canonical renderer. `ArticleVersionBundle` deliberately lacks generated plan fields (`domain/official_account_local.py:505–523`). Keep text/render V10 frozen and add only run-level visual policy if possible; if changing local adapter or canonical render identities, add a supported new exact tuple instead of pretending it is old V10.
- New native plan cannot reuse V3 under a new request shape. Existing plan digest at `visual_generation.py:249–275` binds publication profile, not native size. Preview wraps its base fingerprint under a preview-specific identity (`visual_preview.py:449–459`); this is explicitly **not** canonical durable planning.
- Existing SQL `ck_official_generated_visuals_plan_shape` enumerates V1/V2/V3 literals (`models.py:4308–4335`). Add a reviewed Alembic migration plus synchronized ORM/repository validation for a new plan/profile. Do not edit old migrations or reassign the `OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION` alias without freezing literal V3 replay branches.
- Generated result schema allows bytes only for `ready` and none for failed/result-unknown (`models.py:4364–4375`). Strict audit rejection should not erase a successfully generated artifact or pretend its generation failed. Persist generation success separately before strict audit, and gate final article/draft readiness on accepted media audits. This does not alter the old observer's ready+eval atomic contract because it is a distinct policy/table.
- Existing eval rows have a composite FK `(generated_visual_id, run_id, publication_sha256)` and are unique per generated visual. A cover has different bytes and cannot be squeezed into that body observer row. A separate audit subject contract for body and derived cover is the cleaner small addition.
- The local-media SQL source-XOR already admits `generated_visual_id` regardless of body/cover (`models.py:4571–4581`), but application/resolver forbid cover. A derived-cover contract may reuse that parent FK with a new closed descriptor kind and separately verified derived bytes; do not relax the existing generated-body equal-SHA checks.
- `_identity_from_bundle` currently enumerates recognized fields and ignores extras (`db/official_account_local.py:1934–1985`). Old worker code can therefore read a future bundle while silently losing the new policy. Safe rollback must fence zero new strict runs/requests, or keep compatible consumers for those rows. Image rollback alone after new rows exist is not sufficient.
- `claim` accepts `max_attempts` but does not apply it to repeated expired running-lease claims (`728–782`). New per-image/audit cardinality constraints and status fencing must bound paid work independently of run attempt count. Do not equate overall retry count with actual paid POST count.
- Existing generator result contains `attempts` but durable success attempts record zero tokens/latency and no provider task ID (`ports/image_generation.py:52–63`; repository `507–538`). This is a logical-generation receipt, not a physical-call journal or monetary accounting. Record truthful one-shot dispatch/result counts; do not infer currency spend without real provider usage/pricing evidence.

### Recommended smallest reuse path

This is a proposal for main/design review, not implemented signatures:

1. **New opt-in frozen policy only for new inputs.** Add a literal strict production visual policy and immutable configuration projection. Keep old run bundles unchanged. Freeze it in new weekly inputs/one-shot article enqueue linkage and both runtime/API constructors; reject mixed or unknown bundles before any provider work.
2. **Reuse existing generation intent/result table with additive native plan support.** Preflight all five block/reference identities and provider capabilities. Generate each slot once using existing one-attempt Comfly adapter at native 1536x1024. Persist immutable result bytes and ready generated metadata immediately under the new policy, with an exact before-call intent. Preserve successful siblings and their raw/result identities. Do not invoke the legacy observer concurrently for this policy.
3. **Prepare actual final body and cover media, then run a strict durable audit stage.** Persist local body byte identity, derive final upload-suitable cover from a frozen body choice, and persist derivative lineage. Add a narrow audit request/result table keyed by exact run/article/render/media/role/ordinal/SHA plus policy/ref/criteria/model fingerprint. Reuse the reviewed `ImageQualityAuditor` adapter and extracted pure preview criteria/gate, but never import the preview's source-run allowlist or filesystem journal as a database repository.
4. **Ready is a repository-verified gate.** `persist_draft` under the new policy must recompute/validate five distinct generated bodies, accepted exact final-media audits, cover derivative lineage, and batch-quality result before committing ready. A forged/unavailable/stale/warning audit row cannot be bypassed by simply calling the draft repository method.
5. **Prepared export consumes, never repairs or calls models.** It selects the new gzh/V2 body projection from the frozen run policy and verifies final bytes / audit fingerprints. Existing exports remain old-byte-compatible. The WeChat preparer either preserves final audited cover bytes for this new policy or creates a separately accounted audited derivative before upload; no hidden transformation after an acceptance claim.

### Suggested strict-audit lifecycle

`pending/prepared -> calling (committed before POST) -> completed(accepted/rejected/unavailable) | result_unknown`

- Request fingerprint binds: run ID, article/render IDs, role+ordinal, final-media SHA and normalization profile, source generated visual/ref checksum, exact criterion hash, prompt/rubric/policy versions, direct provider route identity and judge model. Do not persist criterion/prompt prose.
- At most six audit requests for the initial five-body+one-cover policy. No auto-repair or new intent after unknown result. A future known-quality repair needs a distinct explicitly bounded version/intent, not an incremented attempt on the same request.
- Reserve/claim with DB lock/unique key and actual lease token/attempt. Return a typed ownership outcome (`newly_claimed`, `in_flight`, `completed`, `result_unknown`), not an ambiguous existing row that a caller mistakes for permission to call.
- Same-attempt concurrent joining is a no-op; later reclaim of `calling` is unknown. Persist safe status and conservative call accounting on timeout, cancellation, read failure, malformed result, and exception. A DB failure after a response leaves the committed `calling` fence, preventing a duplicate.
- Keep every successful generated image and accepted audit sibling recoverable. A crash after all six results but before draft completion should only finish local persistence, with zero provider calls.
- A final accepted boolean means model review, not human annotation or copyright permission. Preserve source-news `publish_permission_unverified` and `context_only_not_evidence=true` independently.

### Weekly scheduling and activation risks

- `ProductionWeeklyDagHandlers` waits 720 seconds by default and permits 30–840 seconds (`weekly_production.py:111–124`). Its outer governed node is capped at 900 seconds and root at one hour (`official_account_weekly_dag_governance.py:60–85`). Five serial image calls plus six audits can exceed this even while the independent article worker is healthy. Do not guess an ETA or merely extend a timeout without checking the complete 3-role execution envelope.
- A polling timeout currently returns retryable capability timeout; the same frozen article identity yields the same run on retry (`weekly_production.py:217–222`). With a changed handler-global identity, however, that retry can create a second article. Freeze the input/link before enabling and test restart under config drift.
- The scheduler already refuses to recreate an existing weekly run regardless of its current state (`official_account_weekly_scheduler_main.py:115–128`). Do not change this to replay September 7 or to activate the new visual profile. New Monday work is the normal prospective route; immediate replacement of old drafts is a separate explicit operation/identity.
- The weekly DAG governance budgets set `model_turns=0` because it delegates durable article production through a business capability. They do not account for the new image/audit calls (`official_account_weekly_dag_governance.py:64–85`). Keep accounting owned by the article/media layer; do not claim that the unchanged DAG trace proves actual model-call counts.
- Before rollout, read-only check current generated/audit rows, all queued/running article and weekly jobs, provider configuration, next natural schedule, protected article/draft identities, and schema head. No deployment approval is inferred by this report.

### Bounded implementation ownership chunks

1. **Visual policy, planning, and adapter wiring.** Own a new pure visual-policy/quality module, `application/services/official_account_visual_generation.py`, `core/config.py`, `infrastructure/official_account_runtime.py`, API identity constructor delegation, `official_account_worker_main.py`, and focused unit tests. Freeze legacy literals; add native plan/reference eligibility and strict direct-one-shot auditor composition. Coordinate port changes with chunk 2 rather than two editors sharing a large file.
2. **Durable media/audit execution and repository.** Own `application/ports/official_account_local.py` plus a narrow new audit port, executor integration (prefer a new service rather than further growing the old one), `infrastructure/db/official_account_local.py`, new audit repository/model section, additive Alembic migration, `infrastructure/official_account_media.py`, and isolated PostgreSQL tests. Own call ownership/results/recovery, derived cover lineage and final draft readiness guard. No provider calls or production operations in worker subtask.
3. **Prospective weekly input and prepared/draft byte contract.** Own weekly input/planner/handler serialization and timeout/continuation review, prepared export, WeChat preparation, gzh-compatible rendering projections, and final-byte regression tests. Dispatch renderer and thumbnail changes from frozen run policy; preserve old child/aggregate/draft semantics. Downstream researcher has the detailed route; avoid duplicate implementations.

Main owns skill instructions, task/spec decisions, exact execution envelope, release/rollback transaction, local/production evidence, scoped commit, and any authorized real calls. Independent check should review the assembled cross-layer flow, not just per-chunk green unit tests.

### Existing tests to extend and acceptance matrix

- `backend/tests/unit/test_official_account_visual_generation.py:256`: frozen V1/V2 plan and prompt identities. Add literal V3 stability and new native/profile digest differences.
- `backend/tests/unit/test_official_account_worker.py:1022`: approved-catalog generated body flow; add exactly five native requests, no tiny references/direct reuse, strict accepted audit sequence and current-scene cover.
- Same file `1109` and `1143`: observer unavailable still ready and no historical ready backfill. Preserve exactly.
- Same file `1211`, `1277`, `1341`: generating recovery, failed visual recovery and provider-timeout no-replay. Extend with distinct durable audit calling/completed/unknown ownership.
- Same file `157`, `176`, `257`: settings/version tuple rejection, independent observe flag and complete CLI identity. Add default-off equality, unknown/mixed strict-policy rejection and API/CLI/weekly parity.
- `backend/tests/integration/test_official_account_local.py:313`, `379`, `407`, `439`, `834`: stale-token fencing, result-unknown refusal, retained render on retry, explicit retry contract and generated-media lineage.
- `backend/tests/integration/test_image_quality_eval_migration.py:20`: existing observer migration downgrade pattern. New migration must support empty upgrade/downgrade and refuse destructive downgrade while new strict artifacts exist.
- `backend/tests/unit/test_official_account_visual_preview.py`: reusable exact final-byte criteria, warning rejection, checksum/perceptual batch checks, native references and physical-call limits. Keep frozen accepted sample replay deterministic if pure helpers are extracted.
- `backend/tests/unit/test_official_account_preview_image_geometry.py`: native Comfly payload and decoded geometry in every result branch; old square defaults remain supported.
- `backend/tests/unit/test_content_worker_validation_wiring.py`: independent vision model. New strict official-account auditor must use one attempt/direct route without altering normal observer/text configuration.
- Add DB tests for duplicate concurrent audit claims, same-attempt join, later reclaim unknown, provider success followed by transaction failure, cancelled process, stale completion, accepted sibling reuse, and final ready transaction with one absent/mismatched/rejected cover audit.
- Add golden old-bundle/default-off fingerprint and prepared ZIP regressions. Test no mutation/no second enqueue when a historical weekly build is restarted under new settings.
- Add pre-generation complete-reference preflight failure with **zero text/image/audit calls where practical**, five distinct block anchors and five image outputs even if only three reusable reference identities are selected by the new policy.
- Verify final cover uploaded bytes match audited SHA exactly, body JPEGs are unchanged through preparation, source-news bytes/rights remain intact, and no browser/check artifact falsely claims current provider work.

## External references

No external browsing was required or performed: this is an internal implementation trace, not a provider-capability or pricing claim. Existing approved preview/model-contract evidence is in task research and the root specs. No new account, model, provider, price, or production-support claim is inferred here.

## Related specs

- Root `.trellis/spec/backend/official-account-editorial-repackage.md:697` — frozen durable V10, five images, one-attempt generation, unknown-result behavior, separate polished export.
- Root `.trellis/spec/backend/official-account-visual-preview.md` — preview-only native plan wrapper, safe ledger, direct GLM audits, exact browser acceptance; explicitly not durable activation.
- Root `.trellis/spec/backend/image-quality-evaluation.md:1` — `off|observe` default-off/nonblocking, atomic ready+observer-child and no historical paid backfill.
- Root `.trellis/spec/backend/official-account-editor-handoff-v2.md` — pure V2 media/body projection and strict durable lineage; current service is development-only, not a shortcut to enable production.
- Root `.trellis/spec/backend/official-account-reviewer.md` — useful independent intent/accounting/unknown-state design, but candidate production base does not include that newer reviewer runtime/migrations. Do not import unrelated dirty Reviewer work.
- Root `.trellis/spec/backend/weekly-production-source-preflight.md` and `.trellis/spec/backend/wechat-official-account-drafts.md` — prospective valid inputs, preserved terminal checkpoints and draft-only side effects.

## Caveats / Not Found

- This report did not verify live service state, row counts, provider latencies, credential values, catalog-wide eligible-reference counts or current sample artifacts. Main owns those checks.
- Per role-isolation instructions, did not load `implement.jsonl` or `check.jsonl`; read native supplied task path, workflow, task PRD/design/implement, relevant specs and candidate code directly.
- Native geometry and independent parser code exist in the candidate; no claim here that they are deployed.
- No numeric quality scores, provider monetary spend, model consensus, human annotation or source-photo republication license is established by six accepted audit booleans.
- The exact new policy/table/version names above are proposed. Freeze them in design before parallel implementation; schema revision number must be selected against the actual candidate Alembic head, not guessed from newer dirty-root Reviewer specs.
- Cover final-upload transformation is a downstream research finding shared by `visual_draft_export_route`; its own report is authoritative for precise prepared-artifact/draft ownership details.
