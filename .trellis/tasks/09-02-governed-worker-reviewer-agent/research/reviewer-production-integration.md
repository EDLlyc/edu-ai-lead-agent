# Research: Governed Worker–Reviewer production integration

- Query: Identify the smallest high-value way to add an independently governed Reviewer and one bounded Worker repair to the official-account article pipeline, while reusing current persistence, evaluation, and execution-governance contracts.
- Scope: mixed (repository evidence plus primary external documentation)
- Date: 2026-09-02

## Findings

### Executive conclusion

The current official-account pipeline does **not** support keeping an initial article and a repaired article for one run. `official_account_article_versions.version` represents the Article bundle/schema family, not a content revision number. The repository loads a singular article by `run_id`, returns the existing row instead of inserting another, and the database has a unique `(run_id, version)` constraint. A repair therefore needs an explicit `revision`/`repair_of` lineage; using the next schema version number would corrupt two distinct concepts.

The implementation should reuse three existing systems rather than build replacements:

1. the official-account run/lease/stage state machine as recovery owner;
2. the copy pipeline's immutable v1/v2, one-repair-only orchestration pattern;
3. the execution-governance role, capability, budget, event, and artifact ledger, with the weekly DAG adapter as the integration model.

The active task should remain the parent acceptance contract, but production work should be split into four independently verifiable child tasks: contract/eval, persistence/governance, production rollout, and opt-in live A/B. This isolates the highest-collision files and prevents an unreviewable schema/runtime/eval change set.

### 1. Exact current Article lifecycle and repair support

The current executor performs this lifecycle under a claimed, heartbeat-protected run:

1. Load the source, Article bundle identity, media, and the singular stored Article (`backend/app/application/services/official_account_local.py:864`, `backend/app/application/services/official_account_local.py:920`).
2. If no Article exists, call the fixture or live generator and validate returned identity (`backend/app/application/services/official_account_local.py:922`, `backend/app/application/services/official_account_local.py:941`, `backend/app/application/services/official_account_local.py:942`).
3. Build an immutable `ArticlePackage`, run deterministic validation, then persist it (`backend/app/application/services/official_account_local.py:982`, `backend/app/application/services/official_account_local.py:1000`, `backend/app/application/services/official_account_local.py:1009`).
4. If no audit exists, invoke the current binary model auditor and persist its verdict (`backend/app/application/services/official_account_local.py:1019`, `backend/app/application/services/official_account_local.py:1049`). Rejection moves the run to manual review and stops (`backend/app/application/services/official_account_local.py:1054`).
5. Only an accepted Article proceeds to render, generated media, local draft, and later editor handoff (`backend/app/application/services/official_account_local.py:1058`, `backend/app/application/services/official_account_local.py:1346`).

The current Article port exposes `get_article(run_id)` and a singular `StoredOfficialAccountArticle`; it has no revision collection or repair lineage (`backend/app/application/ports/official_account_local.py:119`, `backend/app/application/ports/official_account_local.py:543`, `backend/app/application/ports/official_account_local.py:611`). The current audit verdict is also only `accepted: bool` plus five issue-code classes; it cannot represent manual review, repairability, evidence spans, severity, provider unavailability, or ambiguous result (`backend/app/domain/official_account_local.py:809`).

Persistence confirms that two content rounds are unsupported:

- the business bundle name is mapped to integer schema families v1 through v6 (`backend/app/infrastructure/db/official_account_local.py:121`, `backend/app/infrastructure/db/official_account_local.py:153`);
- `persist_article` first selects any Article for the run and returns it, so a later repair cannot create a second row (`backend/app/infrastructure/db/official_account_local.py:1123`, `backend/app/infrastructure/db/official_account_local.py:1135`);
- the ORM enforces one `(run_id, version)` pair (`backend/app/infrastructure/db/models.py:3961`, `backend/app/infrastructure/db/models.py:4020`);
- the active Article is stored on the run and audit fields are mutated onto that Article row (`backend/app/infrastructure/db/official_account_local.py:1225`, `backend/app/infrastructure/db/official_account_local.py:1238`).

Therefore repaired versions are not “already supported.” The correct compatibility change is to keep `version` as schema/bundle version, add `revision` (1 or 2), add a same-run `repair_of_article_version_id`, change uniqueness to include revision, and load the run's `active_article_version_id`. Rendering and handoff must always bind the active exact Article ID and SHA.

### 2. Copy generator/auditor pieces to reuse

The copy pipeline already implements the desired bounded control flow:

- durable initial draft v1 creation (`backend/app/application/services/copy_generation.py:268`, `backend/app/application/services/copy_generation.py:283`);
- deterministic validation followed by model audit (`backend/app/application/services/copy_generation.py:296`);
- exactly one v2 repair with `repair_of`, bounded issues, and the previous draft (`backend/app/application/services/copy_generation.py:317`, `backend/app/application/ports/copy_generation.py:27`);
- preservation of the original durable draft when repair generation fails (`backend/app/application/services/copy_generation.py:330`);
- deterministic revalidation and re-audit of repaired content, then terminal `repair_exhausted` rather than a loop (`backend/app/application/services/copy_generation.py:354`, `backend/app/application/services/copy_generation.py:362`);
- resume by loading persisted versions/audits rather than repeating completed provider calls (`backend/app/application/services/copy_generation.py:445`);
- bounded repair instructions (at most 12 issues, bounded message length) and stable request fingerprints (`backend/app/application/services/copy_generation.py:787`, `backend/app/application/services/copy_generation.py:807`, `backend/app/application/services/copy_generation.py:843`).

Its database repository persists immutable versions and `repair_of`, and commits deterministic results, attempts, audits, issues, and checkpoints around exact draft identities (`backend/app/infrastructure/db/copy_generation.py:418`, `backend/app/infrastructure/db/copy_generation.py:449`, `backend/app/infrastructure/db/copy_generation.py:513`, `backend/app/infrastructure/db/copy_generation.py:572`).

Reuse the state-transition pattern, request fingerprinting, bounded issue projection, immutable v1/v2 lineage, and “validate then re-audit” order. Do not copy its content-specific issue taxonomy, prompt, or persistence models into the official-account domain.

The current official-account auditor should remain the legacy hard factual/privacy/safety gate during rollout. The new Reviewer should have a non-overlapping editorial/quality contract. Two general-purpose auditors judging the same dimensions would be duplicated and hard to calibrate; a hard-safety gate plus an editorial Reviewer is defensible and permits truthful observe-mode comparison.

### 3. Execution-governance and weekly-DAG reuse

The shared runtime already contains the necessary security and accounting primitives:

- `REVIEWER` is a first-class role (`backend/app/domain/execution_governance.py:20`);
- capabilities declare access, role allowlists, byte bounds, timeout, task scope, and artifact scope (`backend/app/domain/execution_governance.py:384`);
- authorization rejects Reviewer `PLAN` and `BUSINESS_WRITE`, independent of its prompt (`backend/app/domain/execution_governance.py:441`, `backend/app/domain/execution_governance.py:451`);
- the gateway validates stored identity/role/scope, durably reserves maximum budget before a call, reconciles actual usage on success/failure/timeout/cancel, and emits safe events (`backend/app/application/services/execution_governance.py:172`, `backend/app/application/services/execution_governance.py:204`, `backend/app/application/services/execution_governance.py:248`, `backend/app/application/services/execution_governance.py:307`);
- artifact metadata is opaque and contains identity, kind, media type, byte size, SHA, lifecycle, and producer binding, not article content (`backend/app/domain/execution_governance.py:352`);
- repository APIs already cover run creation, child allocation, reservations, events, artifact registration, completion, and timeline projection (`backend/app/application/ports/execution_governance.py:54`).

Recommended allocations when Reviewer mode is not `off`:

| Allocation | Role | Capability/access | Output |
|---|---|---|---|
| root | orchestrator | orchestration only | causal root |
| `official.writer.initial` | worker | `official.article.generate` / plan | Article revision 1 artifact |
| `official.reviewer.r1` | reviewer | `official.article.review` / check | exact-SHA review record artifact |
| `official.writer.repair` | worker | generate/plan | optional Article revision 2 artifact |
| `official.reviewer.r2` | reviewer | review/check | optional final review artifact |

Use deterministic task/agent/artifact/request IDs and bounded root/child limits. Reviewer receives only exact Article and context artifact scopes; it never receives a business-write or publishing capability. Business persistence remains in the orchestrating application service after a validated governed result.

The weekly DAG shows how to adapt this safely without another workflow runtime:

- code-owned closed graph/identity/fingerprint helpers (`backend/app/domain/official_account_weekly_dag.py:109`, `backend/app/domain/official_account_weekly_dag.py:239`);
- compatible run creation before durable work (`backend/app/application/services/official_account_weekly_dag.py:64`);
- `FOR UPDATE SKIP LOCKED`, dependency gates, immutable attempts, fencing token, heartbeat, retry, and exact-claim completion (`backend/app/infrastructure/db/official_account_weekly_dag.py:166`, `backend/app/infrastructure/db/official_account_weekly_dag.py:326`, `backend/app/infrastructure/db/official_account_weekly_dag.py:350`);
- exact cross-layer artifact/event/agent/causal-lineage validation (`backend/app/infrastructure/db/official_account_weekly_dag.py:840`);
- bounded registry, node allocation, gateway call, artifact production, child completion, and stale reservation recovery (`backend/app/infrastructure/official_account_weekly_dag_governance.py:94`, `backend/app/infrastructure/official_account_weekly_dag_governance.py:170`, `backend/app/infrastructure/official_account_weekly_dag_governance.py:458`).

Two small governance gaps matter for restart correctness:

1. `validate_artifact_scope` only checks active/same-run/same-task and does not return metadata for exact SHA/media-type/size comparison (`backend/app/infrastructure/db/execution_governance.py:484`). Add a narrow `get_artifact` or exact-binding validation API; do not build a second artifact registry.
2. duplicate child allocation and artifact registration currently map to `invalid_event`, not compatible replay (`backend/app/infrastructure/db/execution_governance.py:223`, `backend/app/infrastructure/db/execution_governance.py:384`). The official-account adapter must deterministically recover existing compatible rows, or the shared port can gain narrow `get/ensure` operations.

An execution reservation alone cannot prove whether a provider returned before a process crash. Persist a product-owned review intent before the external call. `calling` without a durable result must become `result_unknown`/manual review, never a blind repeat. Do the same for repair generation if it is provider-backed.

### 4. Minimal additive persistence and rollout semantics

The smallest clear product schema is:

1. **Alter `official_account_article_versions`:** add `revision SMALLINT NOT NULL DEFAULT 1`, nullable `repair_of_article_version_id`, and optional execution artifact binding. Add checks for revision 1/no parent versus revision 2/exactly one same-run revision-1 parent. Replace unique `(run_id, version)` with `(run_id, version, revision)`. Existing rows backfill to revision 1 without changing bytes or Article SHA.
2. **Add `official_account_article_review_requests`:** mutable provider-call intent with exact run/Article ID and SHA, source/brand/context fingerprints, reviewer prompt/schema/rubric/policy/provider/model identities, execution allocation/reservation/artifact bindings, unique request fingerprint, `pending|calling|succeeded|unavailable|result_unknown`, provider request ID if available, and safe bounded error code. Persist before the provider call.
3. **Add `official_account_article_review_records`:** immutable one-to-one terminal result bound to the request and exact Article SHA, with `accepted|manual_review|rejected|unavailable`, bounded structured issues, request/result fingerprints, usage/latency, and produced execution artifact/event IDs. JSONB is acceptable for strictly domain-validated bounded issue snapshots; core lineage/state must remain relational.

Keeping intent and immutable result separate isolates new behavior. Overloading the existing `official_account_article_attempts` with partially new `calling/result_unknown` semantics looks smaller in DDL but creates a wider compatibility refactor; that table currently records terminal stage attempts under closed stage/capability checks (`backend/app/infrastructure/db/models.py:4102`, `backend/app/infrastructure/db/models.py:4150`).

The next migration should descend from `20260901_0042`, which is the current declared head (`.trellis/spec/backend/database-guidelines.md:5`; `backend/alembic/versions/20260901_0042_wechat_mp_draft_jobs.py:1`). A likely revision is `20260902_0043`. Empty-feature downgrade can restore the old constraint; downgrade must refuse before DDL if review rows, revision 2 rows, repair links, or new execution bindings exist. All hard-coded head declarations and release compatibility metadata must move together.

Mode must be snapshotted into each new run's immutable identity/fingerprint; changing environment configuration must not reinterpret an active or historical run:

| Mode | Exact behavior |
|---|---|
| `off` | Existing flow byte-for-byte: no Reviewer call, review row, governance allocation, or repair. |
| `observe` | After deterministic validation and legacy audit acceptance, run the governed Reviewer and persist its truthful outcome. Never repair and never let any Reviewer outcome alter render/run/handoff eligibility. Do not label an observed non-acceptance as accepted. |
| `enforce` | Legacy gates pass first. Reviewer accepted proceeds; manual/unavailable/result-unknown stops at stable `review_required`; repairable rejection permits exactly one Worker repair, deterministic validation, legacy audit, and second Reviewer pass. Any second non-acceptance stops with no loop. |

Enforce activation should require an explicit, externally reviewed live/human calibration report identity and acknowledgement. Provider-free fixtures prove contracts and safety, not production quality uplift. Existing historical runs without Reviewer rows remain valid under their frozen old policy.

Editor handoff must inspect the persisted Reviewer policy/result when enforce mode is frozen, bind the exact final review and Article revision into its release fingerprint, and fail closed on mismatch. Observe mode may expose “observed/not enforced” truth but must not fabricate a human or machine approval. This follows the current read-only gate/fingerprint model (`backend/app/application/services/official_account_editor_handoff_v2.py:160`, `backend/app/application/services/official_account_editor_handoff_v2.py:344`).

### 5. Focused verification seams and collision map

Provider-free tests should cover:

- domain: strict verdict schema, bounded issues/evidence, closed decisions, repairability policy, identity/fingerprint determinism;
- authorization: Reviewer can check exact scoped artifacts but cannot plan, write, spawn, or publish; denials happen before handler invocation;
- orchestration: off compatibility, observe non-blocking truth, enforce accepted/manual/rejected/unavailable/result-unknown, one repair only, repaired deterministic/legacy/reviewer rechecks;
- restart: every boundary before/after intent, reservation, provider call, review record, Article revision, artifact registration, and completion; ambiguous outcomes never call twice;
- persistence: concurrent compatible replay, conflicting fingerprint rejection, same-run repair FK, exact active Article binding, downgrade refusal with feature data;
- privacy: traces/logs contain only safe names/counts/hashes and never prompt, article, repair text, provider body, credentials, or private paths;
- handoff: exact final revision/review lineage in release fingerprint; observe and historical semantics remain truthful.

Existing executable seams worth extending are:

- official-account PostgreSQL concurrency, lease fencing, `result_unknown`, and resume tests (`backend/tests/integration/test_official_account_local.py:225`, `backend/tests/integration/test_official_account_local.py:313`, `backend/tests/integration/test_official_account_local.py:379`, `backend/tests/integration/test_official_account_local.py:407`);
- copy one-repair/restart/bounded-prompt unit cases (`backend/tests/unit/test_copy_generation.py:1231`, `backend/tests/unit/test_copy_generation.py:1481`, `backend/tests/unit/test_copy_generation.py:1877`);
- execution-governance pre-handler denial and concurrent budget/trace tests (`backend/tests/unit/test_execution_governance.py:1`, `backend/tests/integration/test_execution_governance.py:94`, `backend/tests/integration/test_execution_governance.py:310`);
- weekly-DAG once-only/fencing, checkpoint restart, cancellation reconciliation, and lineage tests (`backend/tests/integration/test_official_account_weekly_dag.py:325`, `backend/tests/integration/test_official_account_weekly_dag.py:557`, `backend/tests/integration/test_official_account_weekly_dag.py:599`, `backend/tests/integration/test_official_account_weekly_dag.py:659`);
- editor-handoff gate/fingerprint matrix (`backend/tests/unit/test_official_account_editor_handoff_v2.py:520`).

Likely high-collision files are `backend/app/domain/official_account_local.py`, `backend/app/application/ports/official_account_local.py`, `backend/app/application/services/official_account_local.py`, `backend/app/infrastructure/ai/official_account_local.py`, `backend/app/infrastructure/db/official_account_local.py`, `backend/app/infrastructure/db/models.py`, `backend/app/core/config.py`, `backend/app/official_account_worker_main.py`, `.env.example`, `compose.yaml`, the handoff V2 service/tests, and migration-head assertions. The worker unit test's in-memory repository implements the full official-account port, so any new abstract method will collide there (`backend/tests/unit/test_official_account_worker.py:529`). Prefer new Reviewer domain/provider/eval/governance-adapter modules and additive repository collaborators over expanding one large protocol unnecessarily.

For evaluation, reuse the provider-free frozen-observation/canonical drift pattern in `backend/evals/image_quality`, the safety/contract metrics in `backend/evals/agent_workbench`, and the opt-in live paired/human-review pattern in `backend/evals/ip_asset_retrieval_grounded` (`backend/evals/ip_asset_retrieval_grounded/live.py:41`, `backend/evals/ip_asset_retrieval_grounded/runner.py:38`, `backend/evals/ip_asset_retrieval_grounded/runner.py:215`). Keep frozen and live tracks visibly separate and do not turn fixture scores into résumé claims.

### 6. Task decomposition

Keep `.trellis/tasks/09-02-governed-worker-reviewer-agent` as the parent PRD and acceptance/rollout record. Split implementation into:

1. **`reviewer-contract-eval`** — strict domain verdict/taxonomy/rubric, provider-free dataset, canonical safety/permission metrics. No production integration.
2. **`reviewer-persistence-governance`** — migration, Article revision/repair lineage, durable review intent/result, exact artifact lookup/binding, and official-account governance adapter. Depends on contract.
3. **`reviewer-production-rollout`** — provider/prompt, executor state transitions, off/observe/enforce wiring, handoff gate, one repair, and restart matrix. Depends on the first two.
4. **`reviewer-live-ab`** — explicitly opt-in provider run, paired baseline/treatment output, human review worksheet, cost/latency/quality report, and enforce activation evidence. Depends on production rollout and provider authorization; it should not fabricate or block provider-free completion.

Each child has an independently testable artifact and a narrow collision surface. Combining contract/eval and persistence is possible if task overhead is a concern, but merging all four would couple schema, runtime, calibration, and external-provider evidence into one risky review unit.

### Duplicate or overengineered approaches to avoid

- Do not add a second LangGraph/checkpointer or generic workflow runtime inside the official-account executor; its database run stage, lease, and attempts already own recovery.
- Do not build a swarm, reflection loop, recursive reviewer, or more than one repair.
- Do not authorize Reviewer business writes, planning, provider configuration changes, delivery, or publishing.
- Do not represent repair as `Article version=7`; `version` is a schema family.
- Do not create a shadow repaired-article table that forces renderer/handoff union logic.
- Do not create another permission, budget, trace, or artifact ledger.
- Do not rely on a reviewer system prompt for separation of duties; use stored role and capability authorization.
- Do not let two model auditors own the same general taxonomy; keep current hard factual/safety gates and give Reviewer an explicit editorial scope, with shared strict parsing/mapping where appropriate.
- Do not store raw Article, prompt, repair instructions, model response, or provider error body in execution traces.
- Do not blindly replay a call after an ambiguous provider outcome.
- Do not use an LLM judge as sole truth, auto-promote from frozen fixtures, or claim live quality/cost numbers that were not measured.
- Do not add a publishing/HITL delivery tool to this task; the existing editor handoff remains the human release boundary.

## Files Found

- `backend/app/application/services/official_account_local.py` — current singular Article generation/audit/render state machine.
- `backend/app/application/ports/official_account_local.py` — official-account provider and repository contracts.
- `backend/app/domain/official_account_local.py` — Article bundle and current binary audit domain.
- `backend/app/infrastructure/db/official_account_local.py` — Article schema-version mapping and singular persistence behavior.
- `backend/app/infrastructure/db/models.py` — Article, attempt, execution-governance ORM constraints.
- `backend/app/application/services/copy_generation.py` — existing bounded single-repair orchestration.
- `backend/app/infrastructure/db/copy_generation.py` — immutable copy version/repair/audit/checkpoint persistence.
- `backend/app/domain/execution_governance.py` — roles, capabilities, authorization, safe artifacts/events.
- `backend/app/application/services/execution_governance.py` — closed registry, gateway, budget reservation/reconciliation.
- `backend/app/infrastructure/db/execution_governance.py` — durable governance replay, allocation, artifact, and scope behavior.
- `backend/app/infrastructure/official_account_weekly_dag_governance.py` — closest product adapter for governed work and stale recovery.
- `backend/app/infrastructure/db/official_account_weekly_dag.py` — closest fencing/restart/exact-lineage persistence pattern.
- `backend/app/application/services/official_account_editor_handoff_v2.py` — downstream immutable gate and release fingerprint.
- `backend/evals/ip_asset_retrieval_grounded` — opt-in live, paired comparison, and human-review precedent.

## Code Patterns

- Immutable v1/v2 plus `repair_of`, bounded issues, revalidation, and one terminal retry: `backend/app/application/services/copy_generation.py:268`.
- Durable reservation before bounded capability execution and exact-once reconciliation: `backend/app/application/services/execution_governance.py:204`.
- Reviewer write denial enforced outside the prompt: `backend/app/domain/execution_governance.py:451`.
- Fenced claim and exact execution lineage before committing success: `backend/app/infrastructure/db/official_account_weekly_dag.py:166`, `backend/app/infrastructure/db/official_account_weekly_dag.py:840`.
- Release fingerprint binds persisted inputs instead of fabricating approval state: `backend/app/application/services/official_account_editor_handoff_v2.py:344`.

## External References

- [LangGraph Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api) — durable task-result/checkpoint semantics and idempotency guidance. The repository pins LangGraph 1.2.10 and checkpoint-postgres 3.1.0 (`backend/pyproject.toml:18`). This supports deterministic replay principles but does not justify adding another checkpoint owner here.
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) — pending-write behavior; the existing official-account business rows remain the appropriate source of truth.
- [PostgreSQL explicit locking](https://www.postgresql.org/docs/17/explicit-locking.html) — row/advisory lock semantics relevant to short transactional claims and compatible replay.
- [PostgreSQL advisory lock functions](https://www.postgresql.org/docs/current/functions-admin.html) — transaction-level lock option when a typed row does not yet exist; existing unique/idempotent row patterns remain preferable.

## Related Specs

- `.trellis/spec/backend/execution-governance.md` — shared role/capability/budget/event/artifact contract; explicitly forbids Reviewer plan/write.
- `.trellis/spec/backend/official-account-editorial-repackage.md` — current Article generation, audit, persistence, and render contract.
- `.trellis/spec/backend/official-account-weekly-dag.md` — governed DAG allocation, fencing, restart, lineage, and bounded branch behavior.
- `.trellis/spec/backend/official-account-editor-handoff-v2.md` — read-only release gate, truthful approval semantics, and exact fingerprint binding.
- `.trellis/spec/backend/database-guidelines.md` — PostgreSQL source-of-truth, short external-call transactions, durable request fingerprints, migration/downgrade rules, and current head.

## Caveats / Not Found

- The configured `edu-ai-lead` Conda environment was not present, so an Alembic `heads` command could not be executed. The unique head `20260901_0042` is corroborated by the revision chain, deployment compatibility file, tests, and database spec; implementation must still run the real migration checks in the project-supported environment.
- No production model was called and no live Reviewer quality uplift, false-positive rate, latency, or cost was measured in this research task. Those claims require the opt-in live A/B child plus human labels.
- Execution artifact scope validation currently proves scope, not exact requested SHA/size/media type; production integration must close that narrow gap before claiming exact artifact-bound review.
- Existing initial Article generation has its own historical restart semantics. The new mode must not silently broaden replay guarantees in `off`; observe/enforce paths should use durable intents for every new governed provider boundary.
