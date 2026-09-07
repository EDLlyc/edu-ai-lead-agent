# Research: September 7 weekly HTTPS failure and bounded recovery

- Query: Recover the failed `application_case` branch while preserving two ready article runs, the original weekly terminal root, attempts, and immutable input; prevent equivalent future selection failures.
- Scope: Internal, read-only source inspection; proposed recovery design only.
- Date: 2026-09-07.
- Source: `.trellis/worktrees/substantive-baseline`, supplied exact production revision `5c560da71bcbb61b765d3fe82c742cf2d5e676e1`. All code references below are relative to that worktree, not main.
- Incident supplied by parent: weekly run `0ae1c882-4254-561f-bdac-17d254c0c166`; failed package `b290e00b-1e00-43a3-a69f-8f3bdb05137f`; application article creation failed before any article run existed, exhausted three attempts at 09:02; two siblings ready; zero draft jobs/writes. These live facts were not rechecked by this research agent.
- Authorization: The user's current approval covers correcting this exact weekly incident and controlled draft-only recovery. It supersedes the task's earlier exclusion only for this incident; no terminal SQL resets, wider replay, new recipients, provider changes, or public publication.
- Context: Read workflow, PRD, design, implementation plan and relevant specs. No research JSONL exists in the supplied task listing; did not load implement/check JSONL because the research role prohibits those manifests.

## Findings

### 1. Root cause and correct prevention boundary

`backend/app/infrastructure/db/official_account_weekly_production.py:298` has a weaker `_material_is_eligible` predicate: accepted package/image states plus non-empty source and brand snapshots. It does not construct the source contract consumed by the article worker. `PostgresWeeklyProductionInputPlanner.plan` calls this predicate before event deduplication and role selection (`:81-115`).

`backend/app/infrastructure/db/official_account_local.py:192` calls `material_package_source_snapshot` before `_enqueue`. That projection builds every `OfficialAccountEvidence`, validates brand bindings, topic/copy text and inherited image quality (`:1763-1847`). Invalid evidence raises `ConflictError` before an article row or model call (`:1793`). Its source fingerprint binds original package/source/image bytes (`:1804-1829`).

`backend/app/domain/official_account_local.py:136` requires source URLs to have HTTPS, a hostname, no credentials and no fragment. Evidence and article source projections invoke the same validator. The contract is used again by HTML rendering (`:2184`, `:2254`, `:2532`).

Small production fix: preflight candidates with the existing complete `material_package_source_snapshot(package, image)` owner before event deduplication and before role assignment. Catch only the owner's expected invalid-material exception and skip that candidate; keep unexpected failures visible. Do not copy a partial `startswith("https")` validator into the planner. Preflight must precede latest-package-per-event selection so an invalid newer package does not eclipse a valid older candidate. If three qualified distinct roles cannot be selected, normal planning defers with `weekly_input_unavailable`, creating no DAG run or article call.

Also classify a deterministic invalid-source `ConflictError` reaching production `_build_article` as a nonretryable safe checkpoint/input failure. Today production `execute` catches `KeyError`, `TypeError`, `ValueError` but not `ConflictError` (`backend/app/application/services/official_account_weekly_production.py:129-154`); the outer DAG service catches it generically as retryable `capability_failed` (`backend/app/application/services/official_account_weekly_dag.py:176-183`). This is why identical validation failures consume three attempts. Prefer typed nonretryable handling at the material projection/enqueue boundary; never persist raw exception text.

### 2. Do not normalize HTTP by inventing an HTTPS address

The current article contract deliberately validates, rather than rewrites, source URLs. The source snapshot is fingerprinted evidence. A scheme-only substitution changes the cited resource without evidence that the HTTPS resource exists or contains the cited text.

The WeChat upload-response HTTP-to-HTTPS exception is restricted to official image CDN hosts and is unrelated to article citation sources (`.trellis/spec/backend/wechat-official-account-drafts.md`, Official HTTP contract). It does not authorize upgrading arbitrary publisher URLs.

For this incident, retain the old package untouched and choose an already qualifying package whose frozen source snapshot passes the complete owner contract. A future verified canonical-URL acquisition change would need fresh retrieval/provenance and a new immutable derivation; it is unnecessary here.

### 3. Ordinary retry and a second DAG UUID do not work

- Explicit retry accepts only `retryable_failed` with unused attempts (`backend/app/infrastructure/db/official_account_weekly_dag.py:469-473`); terminal/exhausted attempts cannot be reopened.
- Derived run status becomes terminal if any node is terminal (`backend/app/domain/official_account_weekly_dag.py:455-470`). Governance closes the root under an advisory lock after running children/reservations settle (`backend/app/infrastructure/official_account_weekly_dag_governance.py:375-455`). A closed root cannot receive fresh execution budget.
- Scheduler resolves the deterministic Monday ID and returns the existing terminal state without replanning (`backend/app/official_account_weekly_scheduler_main.py:115-128`). Fixing candidate filtering alone does not recover this week.
- DB uniqueness is `(week_start, schedule_version, selection_version, dag_version)` (`backend/app/infrastructure/db/models.py:5969-5977`). Repository enqueue hardcodes those versions (`backend/app/infrastructure/db/official_account_weekly_dag.py:79-108`). Merely supplying a new UUID conflicts.
- `weekly_dag_run_id` binds those same versions (`backend/app/domain/official_account_weekly_dag.py:245-254`), and snapshot construction rejects a foreign DAG version (`:331-340`). A task-local monkeypatch or invented version is not a proper recovery identity.

A first-class second DAG attempt would need a distinct explicit recovery key, original-run linkage, uniqueness/migration changes, historical identity compatibility and scheduler/report semantics. It is broader than required to finish this incident. Do not introduce it under the guise of a small retry fix.

### 4. Recommended incident recovery: audited operator handoff through existing owners

Keep the original weekly run honestly `terminal_failed`. Use a narrowly bound task-local operator command, with an immutable recovery plan/intent and append-only receipts, that performs only the missing article work and existing artifact assembly. It is a recovery operation with its own identity, not a fabricated successful weekly DAG run. Main approved this bounded option during research.

The existing APIs already supply the expensive-work and draft idempotency:

1. `PostgresOfficialAccountRepository.enqueue_material_package` (`backend/app/infrastructure/db/official_account_local.py:192-264`) derives article request identity from source fingerprint and full version bundle; unique request insertion returns the same existing article run on replay.
2. Production article handler waits for `ready`, rejects `review_required`, `failed`, `result_unknown`, and bounds waiting (`backend/app/application/services/official_account_weekly_production.py:188-224`). Use equivalent bounded orchestration through the existing repository; no direct provider calls in the operator.
3. `PreparedWeeklyDraftArtifactOwner.build_child` loads the persisted article, local draft and media and enforces live generation, ready status, article validation, accepted audit and simulation truth (`backend/app/infrastructure/wechat_official_account/prepared_artifacts.py:126-146`). It reads and verifies existing image bytes; it does not regenerate images or text.
4. Child output is content-addressed and fully validated (`:196-252`). Rebuilding from the same two completed run IDs must yield the exact existing child fingerprints. Prefer reuse/validation of existing artifact references from the original successful nodes where possible.
5. `aggregate` validates all three canonical roles, builds a complete directory privately and atomically renames it into the configured inbox (`:254-328`). `validate_batch` revalidates fingerprints and content (`:330-345`). No partial inbox handoff is needed.
6. Existing draft service `reconcile`/`enqueue_staged` prepares all three, derives account/batch/item policy identity and conflict-safe enqueues one normal draft job (`backend/app/application/services/wechat_official_account_draft_jobs.py:130-206`). Only the already configured draft worker handles credentials and WeChat writes. The operator must not call `add_draft`, publish, or mass-send itself.

### 5. Concrete two-stage command contract

#### Read-only plan

Bind the incident Monday, exact original run and failed package IDs; load the original input checkpoint by its stored fingerprint. Preserve its original cutoff. Check target state/attempt ceiling, no live leases/reservations, two successful full branches, failed package still has no article run, and no existing draft job or outcome-unknown external write for this weekly content.

Load the two successful article IDs from original `build_article` checkpoints, cross-check package/event/version bindings against the original role input, verify their full article version bundles match the intended unchanged Zhipu identity, and verify ready article/draft/media metadata and exact prepared child fingerprints. Do not let current defaults silently pick a new generation identity. Reads alone suffice; do not enqueue siblings as part of planning.

Run the corrected planner at the original cutoff. The cheapest defensible constrained choice is to require its first two selected package/event/version bindings equal the originals and use only its third replacement. If that equality fails, stop instead of silently changing successful siblings. A narrowly scoped pinned-role planner can be introduced only if needed; it must reuse the normal domain role ordering/qualification and cutoff, exclude both reused event IDs and the failed package, and record its explicit recovery selection semantics. Do not manually choose a high-scoring unrelated replacement or reclassify a role.

Use existing complete material preflight on all selected bindings. Freeze replacement source fingerprint, request fingerprint, original material request/score/source metadata fingerprints, candidate cutoff, role reason, article generation identity, and protected sibling/old-run fingerprints in a canonical manifest. Persist only opaque IDs, hashes, safe enum/reason codes, counts and timestamps in the operator audit; no titles, source URLs, quoted source text, prompts, secrets or private object paths. Keep needed original content in its owning storage. The local plan-file creation is the only planning write; there are no production database/artifact/provider writes.

#### Execute exact reviewed plan

- Require exact manifest SHA, policy/version and pinned incident identity; recheck current protected source/run/package/article/draft state. Acquire a single-host lock plus durable no-clobber incident intent in the task-owned production recovery area before the first enqueue. Re-execution must resolve the same intent and exact plan, never choose a fresh replacement automatically.
- Record append-only phase receipts linked to the intent: article request accepted/resolved, article ready, each child validated, aggregate handoff, final observed draft job result. Each receipt is content-addressed or create-only; do not overwrite original DAG rows or previous evidence. A pending intent after crash is resumable only with matching plan/state.
- Enqueue only the replacement package using the frozen full article identity. If a compatible run already exists, reuse it. Wait with the existing bounded ready/terminal semantics; a timeout leaves a resumable intent and known article ID, not a new article or queue reset. A terminal/review-required/unknown article is an explicit failed recovery receipt.
- Revalidate protected original/sibling state before handoff. Reuse or rebuild and verify the two unchanged child artifacts; build and validate the new child. Require three distinct event/package/article/content identities and exact canonical roles before `aggregate`.
- Invoke existing `aggregate` and `validate_batch` with the real production inbox only after all preceding checks. This final inbox write is authorized and will be discovered by the configured draft worker. Do not add an audit file inside the batch directory: the strict loader rejects extra root files (`prepared_artifacts.py:439-440`).
- Observe the normal durable draft job and its three item outcomes. Rerunning reconcile must return the same job with no second send. Preserve `outcome_unknown`; do not bypass the worker's refusal to replay ambiguous writes.
- Record success as “original DAG failed; authorized recovery batch ready; normal draft job completed.” Do not report the old DAG itself as recovered/ready or set any publication/homepage-pin confirmation.

### 6. Minimal affected files and meaningful tests

Runtime prevention changes:

- `backend/app/infrastructure/db/official_account_weekly_production.py`: reuse complete material-source preflight before candidate deduplication/selection.
- `backend/app/application/services/official_account_weekly_production.py`: map expected deterministic invalid-source enqueue failure to safe nonretryable input/checkpoint failure, without changing transient provider behavior.
- `backend/tests/unit/test_official_account_weekly_production.py`: valid HTTPS material admitted; HTTP/fragment/userinfo/malformed evidence, brand and topic inputs rejected; invalid newer package does not eclipse valid older event package; fewer than three valid roles defers; handler does not consume three retries for deterministic source invalidity. Use real owner models/projection, not mocks that reproduce the bug.
- Add focused isolated PostgreSQL planner tests if current tests do not prove stored snapshot and duplicate-event package behavior.

Task-local recovery additions:

- A single exact-incident operator module and focused tests under this task's `research/` (names chosen by main/implementer).
- Tests for changed manifest/source/version/cutoff rejection before enqueue; successful two article IDs never regenerated; same plan replay resolves one new article; timeout/crash resumes same identity; failed/unknown new article never reaches inbox; canonical three unique inputs; child tampering prevents aggregate; second aggregation/reconcile returns same batch/job; old DAG/node/attempt/root and sibling rows unchanged.
- An isolated PostgreSQL end-to-end test should preserve the terminal original cohort and audit hashes while creating exactly one replacement article, a complete batch and one normal draft job with three role items. Provider/WeChat adapters remain fakes for these tests.

No schema migration, original DAG identity change, schedule change, model call from research, or raw SQL reset is required by this recommendation.

## Related Specs

- `.trellis/spec/backend/official-account-weekly-dag.md`: terminal retry prohibition, immutable checkpoints, same-run artifact lineage, root finalization, canonical role dependencies.
- `.trellis/spec/backend/execution-governance.md`: closed root allocations and immutable budget/attempt truth.
- `.trellis/spec/backend/wechat-official-account-drafts.md`: draft-only, all-three preflight, input/account identity, immutable staging, known/unknown outcome handling.
- `.trellis/spec/backend/official-account-weekly-edition.md`: normal role qualification/order, cutoff and distinct-identity contracts.

## External References

None required or consulted. This recommendation relies on exact production-source contracts and internal specs. No network, SSH, model, WeChat, or git operations were performed by this researcher.

## Caveats / Not Found

- Production incident facts and replacement-candidate availability are supplied by main and need main's fresh read-only verification before execution.
- No existing public recovery/supersession API was found. Existing CLI retry cannot recover a terminal root.
- Main and current top-level weekly spec have development-only language that is stale relative to the supplied production adapter. Source truth for this incident is the specified exact production worktree; main should update the relevant learned spec with the implemented recovery boundary.
- A task-local append-only operator audit is not a new weekly DAG row or execution-governance root. If a first-class durable recovery-run ledger is required later, design it explicitly; do not imply that this smaller incident repair provides it.
- Strict HTTPS is an application contract, not independently verified here as a universal WeChat citation requirement. Keep the distinction in user-facing explanation.
