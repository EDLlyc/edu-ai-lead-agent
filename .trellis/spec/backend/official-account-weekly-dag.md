# Official-Account Weekly Three-Article DAG

This specification defines the durable orchestration layer above the existing weekly three-article
edition. Fixture mode remains development-only. The additive production mode freezes real governed
material packages, reuses the persisted Zhipu article worker, prepares an immutable three-child
handoff, and stops at WeChat draft creation. The DAG schedules, checkpoints, resumes, and reports
work; it does not publish, mass-send, or change homepage-pin truth.

## Scenario: Durable deterministic weekly orchestration

### 1. Scope / Trigger

Use this contract when the weekly local edition must survive process restarts, support competing
workers, retry one failed branch without rebuilding successful siblings, or expose bounded operator
status.

The prerequisite artifact contract remains
[`official-account-weekly-edition.md`](./official-account-weekly-edition.md). The execution budget,
permission, trace, and artifact-lineage contract remains
[`execution-governance.md`](./execution-governance.md). This layer must call those public contracts;
it must not duplicate their rules.

The feature defaults off. Fixture mode starts only when its worker profile is selected. Production
requires separate production, scheduler, worker, persisted-local-worker, and WeChat draft-worker
acknowledgements plus an authenticated minimum Monday. It has no public HTTP API or frontend. The
weekly scheduler and DAG worker must not import, construct, or call WeChat, WeCom, browser-login,
publish, mass-send, or homepage-pin clients; only the independent downstream draft worker owns the
WeChat draft adapter.

### 2. Signatures

#### Static graph and identities

```python
WEEKLY_DAG_VERSION = "official-account-weekly-three-article-dag-v1"
WEEKLY_DAG_MAX_ACTIVE_BRANCHES = 3
WEEKLY_DAG_DEFAULT_MAX_ATTEMPTS = 3

WEEKLY_DAG_NODES: tuple[WeeklyDagNodeDefinition, ...]  # exactly 16, contiguous order
validate_weekly_dag(WEEKLY_DAG_NODES) -> None
weekly_dag_graph_fingerprint() -> str
weekly_dag_run_id(week_start: date) -> UUID
weekly_dag_task_id(week_start: date) -> str
weekly_dag_request_fingerprint(*, week_start: date, input_fingerprint: str) -> str
weekly_dag_node_input_fingerprint(
    *,
    run_input_fingerprint: str,
    definition: WeeklyDagNodeDefinition,
    dependency_fingerprints: tuple[str, ...],
) -> str
```

The code-owned graph is:

```text
schedule
  -> select_roles
      -> official_anchor:build_article
         -> official_anchor:plan_media
         -> official_anchor:render_handoff
         -> official_anchor:validate_child
      -> industry_trend:build_article
         -> industry_trend:plan_media
         -> industry_trend:render_handoff
         -> industry_trend:validate_child
      -> application_case:build_article
         -> application_case:plan_media
         -> application_case:render_handoff
         -> application_case:validate_child
  -> aggregate  # depends on all three validate_child nodes
  -> finalize
```

#### Application and repository boundary

```python
class OfficialAccountWeeklyDagService:
    async def enqueue(
        *, week_start: date, input_fingerprint: str, now: datetime | None = None
    ) -> tuple[WeeklyDagRunSnapshot, bool]: ...

    async def enqueue_due(
        *,
        input_fingerprint: str,
        now: datetime | None = None,
        schedule: WeeklyEditionSchedule | None = None,
    ) -> tuple[WeeklyDagRunSnapshot, bool] | None: ...

    async def status(self, run_id: UUID) -> WeeklyDagStatusProjection: ...
    async def retry(
        *, run_id: UUID, node_key: str, now: datetime | None = None
    ) -> WeeklyDagStatusProjection: ...
    async def process_once(
        *, worker_id: str, lease_seconds: int = 60
    ) -> WeeklyDagStatusProjection | None: ...

class WeeklyDagRepository(Protocol):
    async def enqueue(...) -> tuple[WeeklyDagRunSnapshot, bool]: ...
    async def claim_ready(...) -> WeeklyDagClaim | None: ...
    async def heartbeat(...) -> bool: ...
    async def complete(...) -> WeeklyDagStatusProjection: ...
    async def fail(...) -> WeeklyDagStatusProjection: ...
    async def retry(...) -> WeeklyDagStatusProjection: ...

class WeeklyDagGovernance(Protocol):
    async def ensure_run(...) -> None: ...
    async def execute_node(...) -> WeeklyDagGovernedResult: ...
    async def abandon_node(claim: WeeklyDagClaim) -> None: ...
    async def complete_run(status: WeeklyDagStatusProjection) -> None: ...
```

#### Runtime CLI and scheduler

```bash
python -m app.official_account_weekly_dag_main enqueue \
  --week-start YYYY-MM-DD --input-fingerprint <lowercase-sha256>

python -m app.official_account_weekly_dag_main enqueue-due \
  --input-fingerprint <lowercase-sha256> --now <aware-iso-datetime>

python -m app.official_account_weekly_dag_main status <run-uuid>
python -m app.official_account_weekly_dag_main retry <run-uuid> <node-key>
python -m app.official_account_weekly_dag_main worker \
  --worker-id <safe-ref> --concurrency 3 --lease-seconds 60 \
  [--once | --drain]
```

`--output-root` selects the local artifact owner, but its filesystem path is never persisted in a
DAG checkpoint. Worker concurrency is `1..3`; lease seconds are `3..3600`; poll seconds are
`0.1..60`.

`--handler-mode fixture` preserves the development commands above. `--handler-mode production`
is worker-only: direct `enqueue` and `enqueue-due` are rejected so production cannot bypass the
authenticated scheduler/planner boundary.

The portless production scheduler uses the canonical `Asia/Shanghai` schedule: Monday at 09:00,
with bounded periodic reconciliation for restart catch-up. It checks due/completed state and the
minimum Monday before reading candidates or creating artifacts. For a due week it reads recent
eligible real material packages and their persisted score/source lineage, selects exactly the
canonical three roles with the existing pure selector, writes one content-addressed frozen input,
and idempotently enqueues its deterministic run. Reconciliation outside the due window is a
read-only no-op.

| Production key | Contract |
|---|---|
| `OFFICIAL_ACCOUNT_WEEKLY_PRODUCTION_ENABLED` | Production-only explicit acknowledgement; default `false` |
| `OFFICIAL_ACCOUNT_WEEKLY_SCHEDULER_ENABLED` | Enables only the scheduler process; default `false` |
| `OFFICIAL_ACCOUNT_WEEKLY_WORKER_ENABLED` | Enables only the DAG worker process; default `false` |
| `OFFICIAL_ACCOUNT_WEEKLY_HANDLER_MODE` | Compose worker mode, `fixture` or `production`; production deployment uses `production` |
| `OFFICIAL_ACCOUNT_WEEKLY_MIN_WEEK_START` | Required ISO Monday for either production process; never before `2026-09-07` |
| `OFFICIAL_ACCOUNT_WEEKLY_RECONCILE_SECONDS` | Scheduler reconciliation interval, `30..3600`; default `300` |
| `OFFICIAL_ACCOUNT_WEEKLY_WORKER_POLL_SECONDS` | Worker polling interval, `0.1..60`; default `2` |
| `OFFICIAL_ACCOUNT_WEEKLY_WORKER_LEASE_SECONDS` | Attempt lease, `60..3600`; production default `900` |
| `OFFICIAL_ACCOUNT_WEEKLY_ARTICLE_WAIT_SECONDS` | Persisted article wait, `30..840`; production default `720` |
| `OFFICIAL_ACCOUNT_WEEKLY_ARTIFACT_ROOT` | Private durable checkpoint/work root; path never enters rows or status |

#### PostgreSQL schema

Migration `20260831_0040` is additive above execution governance `0039`:

| Table | Primary identity / purpose |
|---|---|
| `official_account_weekly_dag_runs` | Governed run UUID/task, Monday, frozen schedule/selection/DAG/graph/input/request identities, derived status, optional aggregate metadata |
| `official_account_weekly_dag_nodes` | `(run_id, task_id, node_key)`, ordinal/kind/role, checkpoint state, attempt/lease/fencing fields, safe output metadata, execution artifact and trace IDs |
| `official_account_weekly_dag_attempts` | `(run_id, task_id, node_key, attempt_no)`, worker/fencing/input identity, lease heartbeat, terminal state, safe output/error metadata |

The run row has a restrictive foreign key to its governed execution run. Node artifact and trace
IDs have same-run/task foreign keys into the execution-governance ledger. There is no arbitrary
edge JSON column; graph edges remain code-owned.

### 3. Contracts

#### Graph and business identity

- Graph keys, ordinals, roles, kinds, dependencies, and eight closed capability names are part of
  the graph fingerprint. Definitions must be unique, contiguous, acyclic, and backward-dependent.
- The canonical role order is `official_anchor`, `industry_trend`, `application_case`. Each branch
  is `build_article -> plan_media -> render_handoff -> validate_child`.
- `aggregate` becomes ready only after all three validation nodes succeed. `finalize` depends only
  on `aggregate`. Partial or terminal children never produce an aggregate.
- A run is unique by `week_start + schedule_version + selection_version + dag_version`. Its UUID,
  task ID, request fingerprint, and graph fingerprint are deterministic. A conflicting replay is
  rejected; a compatible replay returns the existing run without overwriting checkpoints.
- `week_start` is a Monday under the existing `Asia/Shanghai` schedule contract. `enqueue_due`
  delegates due/catch-up/completed-week logic to the existing pure weekly schedule function.

#### Durable claims, leases, and retry

- A node can be claimed only when every code-owned dependency is `succeeded` and its dependency
  fingerprints exactly derive the expected input fingerprint.
- `claim_ready` locks one candidate at a time with `FOR UPDATE SKIP LOCKED`. It must not lock the
  whole ready set. Active role-branch claims are capped at three. Aggregate/finalize are exclusive.
- Claim increments a monotonic fencing token and creates one immutable attempt row. Heartbeat and
  completion require exact run/task/node, attempt number, worker, fencing token, and unexpired lease.
- An expired lease becomes `lease_expired` and may be reclaimed. A stale worker cannot heartbeat,
  fail, or complete after another attempt owns the node.
- A successful checkpoint is immutable and is never silently recomputed. Explicit retry is allowed
  only for `retryable_failed`; it resets that node and incomplete descendants, never a successful
  sibling. `terminal_failed` and exhausted-attempt nodes are not retryable.
- `SIGINT`/`SIGTERM` stops new claims, lets current `process_once` calls settle, then disposes the
  database engine. Compose provides a 90-second stop grace period.

#### Metadata-only checkpoint and status

- `WeeklyDagArtifact` contains only `opaque_ref`, lowercase SHA-256 fingerprint, media type, and
  byte size. A successful node additionally binds its execution artifact UUID and trace event UUID.
- Checkpoint/run/attempt rows must not contain article bodies, HTML, image bytes, prompts, provider
  bodies, credentials, raw tool arguments/results, private object keys, or filesystem paths.
- `WeeklyDagStatusProjection` always lists exactly 16 nodes in code-owned ordinal order and exposes
  only run/version identity, state, attempt counts, stable safe error code, timestamps, and Boolean
  artifact readiness. It does not expose lease owner, body content, or artifact path.
- Run status derives from node state: `pending`, `running`, `partial`, `retryable_failed`,
  `terminal_failed`, or `ready`. `ready` requires successful `finalize`; terminal failure points to
  the actual failed node and its real stable error code.

#### Existing weekly artifact compatibility

- Fixture handlers call the existing public selection/child builders, strict V2 child loader, child
  validator, aggregate builder, and no-clobber writer. Do not copy these implementations into DAG
  handlers.
- Reconstructing service/repository/governance/handlers after every one of the 16 checkpoints must
  produce the same batch fingerprint, every child and aggregate file byte, and outer ZIP byte as
  uninterrupted one-shot execution.
- Existing V2 gates remain authoritative: distinct event/run/Article/content/artifact/ZIP identity,
  exact mobile pass, allowed release, local-only/unpublished truth, image integrity, and manifest
  version. The DAG cannot weaken or reinterpret them.
- No partial aggregate directory is written. Local writes remain no-clobber and their private paths
  stay in the artifact owner, outside DAG rows and status output.

#### Production input and prepared draft handoff

- Production selection never rescoring raw articles at scheduling time. It reconstructs governed
  candidates from delivered material packages, their exact selected event/version, authoritative
  stored topic or content-slot score, and active source-version metadata. Ineligible, rejected,
  invalid, unaudited, or image-incomplete packages are excluded.
- The frozen input binds three distinct material/event identities, material request fingerprint,
  complete score fingerprint, source metadata fingerprint, organization type, authority evidence,
  selected role/reason, governed total, and scoring version. Replays validate the same immutable
  fingerprint; database rows retain only safe checkpoint metadata.
- A production article node idempotently enqueues the existing persisted local article run using a
  frozen Zhipu identity. It waits only for the authoritative persisted run state. Review-required,
  failed, or timed-out generation never advances to preparation.
- Prepared child version `wechat-draft-prepared-child-v1` is built only from a live, accepted,
  validated ready article plus database media rows whose bytes are reverified through the owning
  object/local resolver. Private local media URLs are replaced by exact relative `assets/*` paths;
  WebP is deterministically converted to supported JPEG. No credential, database URL, object key,
  prompt, or provider response enters the handoff.
- Aggregate version `wechat-draft-prepared-batch-v1` contains exactly three canonical children and
  is exposed in the shared weekly inbox only after all children pass strict file-set, symlink,
  hash, size, image, HTML/media-binding, identity, and unpublished/draft-only checks. The downstream
  draft worker preflights all three before its first provider write.

#### Execution governance integration

- One root `orchestrator` allocation owns the run. Every node attempt has a distinct deterministic
  worker agent ID and child allocation. All deterministic nodes report zero model turns and zero
  input/output tokens.
- The registry has eight sorted capabilities: schedule, select roles, build article, plan media,
  render handoff, validate child, aggregate, and finalize. They are `business_write`, worker-only,
  task-scoped, and dependency-artifact-scoped except the root schedule node.
- Root limits are frozen to one hour, 128 tool calls, 64 MiB tool-result bytes, 16 GiB artifact
  bytes, 64 children, depth 1, and zero model/token budget. A production weekly node may reserve up
  to 15 minutes for the persisted long-form generation boundary; all nodes still reserve one tool
  call, 16 KiB tool-result metadata, 512 MiB artifact bytes, depth 1, and zero model/tokens. The
  article wait is bounded below that capability timeout, and the worker lease covers the attempt
  while periodic heartbeat retains ownership.
- Capability authorization and budget reservation happen before the handler. Permission/budget
  denial is fail-closed and downstream nodes remain blocked.
- Every success registers metadata through the execution artifact ledger. Completion validates the
  exact current attempt agent, capability, fingerprint, byte size, producer event, node target, and
  child/root causal chain; same-run but cross-node reuse is rejected.
- Cancellation, heartbeat failure, lease loss, handler failure, and stale recovery must cancel the
  handler as applicable, reconcile every open reservation, close the attempt child allocation, and
  record a stable safe error. No active child or reservation may remain after run finalization.
- Root terminal finalization uses a PostgreSQL advisory transaction lock. Concurrent workers may
  finish their active sibling branches; only one worker closes the root after no live child or
  reservation remains. A failed root event binds the actual `terminal_failed` node, not the most
  recently completed sibling.

#### Rollback and operational boundary

- Compose owns a separate default-disabled `official-account-weekly-dag` profile containing one
  scheduler and one DAG worker, both portless, plus a persistent shared output volume. Production
  additionally starts only the persisted local article worker and the independent WeChat draft
  worker; ordinary API/worker profiles do not schedule this DAG. The weekly worker receives the
  Zhipu key but no WeChat credentials, while the draft worker receives the read-only weekly inbox.
- Production activation starts at an explicit Monday (initial rollout `2026-09-07`). Rollback stops
  the three additive worker/scheduler services and restores the previous reviewed image; immutable
  checkpoints and audit rows are preserved. No historical week is backfilled automatically.
- Migration downgrade is allowed only while all three weekly DAG tables are empty. Populated rows
  refuse destructive downgrade. Existing weekly child directories and ZIPs are never deleted.
- Doctor validates worker import/help, Compose isolation, code/database head `0040`, and all three
  tables. Do not migrate a shared database merely to make Doctor green without operator approval.

### 4. Validation & Error Matrix

| Condition | Stable result / state | Handler or aggregate runs? |
|---|---|---:|
| Graph key/ordinal/dependency/role/capability drift or cycle | Construction `ValueError` | No |
| Non-Monday week, invalid ref/media type/hash, negative size, naive time | Construction `ValueError` | No |
| Compatible duplicate enqueue | Existing run, `created=false` | No duplicate run |
| Same business key with different frozen identity | `invalid_checkpoint` / conflict | No |
| Dependency missing, non-successful, wrong order, or fingerprint mismatch | `invalid_dependency` | No |
| Selection identity invalid | `invalid_selection` | No downstream branch |
| Child identity, release, mobile, manifest, media, or byte validation fails | `invalid_child` | No aggregate |
| Fewer than three valid children | `partial_children` | No aggregate |
| Artifact metadata or attempt lineage conflicts | `artifact_conflict` / `invalid_checkpoint` | No completion |
| Unknown/unregistered handler or governance permission denial | `permission_denied` | No handler |
| Any governance dimension exceeds reservation | `budget_exhausted` | No handler or no success |
| Capability times out or raises retryably | `capability_timeout` / `capability_failed`, then retry backoff | Already started, fully reconciled |
| Terminal provider or validator failure | `provider_terminal` or precise child error, `terminal_failed` | No retry/aggregate |
| Lease lost, heartbeat fails, or caller cancels | `lease_lost`, `retryable_failed`, resources reconciled | Handler cancelled/abandoned |
| Attempts reach maximum | `attempts_exhausted`, `terminal_failed` | No retry |
| Stale worker heartbeat/fail/complete | Fencing rejection | No write-back |
| Explicit retry targets `succeeded`, `running`, or `terminal_failed` | Reject | No reset |
| Aggregate/finalize sees partial, duplicate, tampered, or cross-node artifacts | Fail closed | No partial output |
| Scheduler/worker enabled without production acknowledgement or minimum Monday | Settings `ValueError` | No process construction |
| Minimum Monday precedes `2026-09-07` | Settings `ValueError` | No process construction |
| Reconciliation is not due or is before activation | Safe `due=false` log | No candidate read/artifact/run |
| Due input has fewer than three valid governed roles | Deferred `weekly_input_unavailable` | No run/provider call |
| Production CLI attempts direct enqueue | Reject | No run/provider call |
| Frozen material, score, source, article, or media lineage drifts | `invalid_checkpoint` or terminal validation failure | No downstream draft |
| Prepared child/batch has private URL, symlink, extra file, bad hash/image/HTML, or wrong role order | Fail closed | No aggregate/provider call |
| Populated `0040` downgrade | `RuntimeError` | No table drop |

Infrastructure exceptions and raw provider errors must not escape into persisted error text or
operator status.

### 5. Good / Base / Bad Cases

- Good: `select_roles` succeeds, three workers claim different role branches concurrently, each
  branch validates independently, aggregate waits for all three, and finalize marks one ready run.
- Good: The industry render node loses its lease. Its handler is cancelled, governance usage is
  reconciled, the attempt becomes retryable, and later reclaim continues without rebuilding the
  already validated official article.
- Good: One branch becomes terminal while two siblings are still active. The siblings finish safely;
  advisory-locked root finalization preserves the true failed-node/error parent and leaves zero open
  allocations/reservations. Aggregate never runs.
- Base: The process exits after any checkpoint. A new service and worker reconstruct state from
  PostgreSQL and opaque artifact ownership, then produce bytes identical to uninterrupted execution.
- Base: Re-enqueue the same week/version/input fingerprint. The same run is returned and all
  successful checkpoints remain untouched.
- Good: Monday 09:00 reconciliation selects three real delivered packages, freezes their stored
  scoring/source lineage, and three persisted Zhipu runs converge into one prepared draft-only
  inbox batch; the independent worker creates three drafts and no publication state.
- Base: The production services start on Wednesday with minimum week `2026-09-07`. Reconciliation
  reports `due=false`, creates no checkpoint or row, and makes zero Zhipu/WeChat calls.
- Bad: A caller uses fixture enqueue to fabricate a production input, reads current mutable scores
  after the run starts, or gives WeChat credentials to the weekly worker. Construction or
  validation must reject the attempt.
- Bad: Persist an output directory or article body in `output_artifact_ref`; reuse an execution
  artifact from another node in the same run; let a stale token complete; or reset a successful
  sibling during retry. All must fail closed.
- Bad: Mark root terminal immediately while siblings still own reservations, choose the most recent
  successful event as a failure parent, or force-close live workers. These corrupt causality and are
  forbidden.

### 6. Tests Required

- Domain/unit: assert exactly 16 nodes, contiguous ordinal order, canonical roles, closed kinds and
  capabilities, acyclicity, graph fingerprint stability, aggregate dependencies, deterministic
  run/task/request/input identities, strict metadata shapes, state derivation, and bounded status.
- PostgreSQL concurrency: prove idempotent enqueue, competing `SKIP LOCKED` claims, active branch cap
  3, heartbeat, lease expiry/reclaim, stale fencing rejection, immutable successful checkpoint,
  retryable-only retry, successful sibling preservation, and max-attempt terminal state.
- Governance: assert role/task/artifact default deny occurs before handler; deterministic zero tokens;
  budget exhaustion; cancellation/heartbeat/lease-loss reconciliation; stale child recovery; exact
  attempt/capability/artifact/trace/causal lineage; true root error; advisory-locked concurrent root
  finalization; zero active children and open reservations at terminal state.
- Artifact compatibility: restart all services after each of 16 checkpoints and compare final batch
  fingerprint, every child/aggregate file, child ZIPs, and outer ZIP byte-for-byte with the public
  one-shot builder/writer. Assert zero social calls, local-only, and unpublished truth.
- Failure matrix: duplicate/tampered/partial/cross-node child, permission/budget denial, retryable and
  terminal handler failure, cancel, lease loss, and aggregate prevention.
- Migration: `0039 -> 0040` creates the three tables/FKs/checks/indexes; empty downgrade succeeds;
  populated downgrade refuses; all historical head assertions and release declaration report `0040`.
- Runtime: CLI help and bounds, `enqueue`/`enqueue-due`/`status`/`retry`, worker once/drain/polling,
  SIGINT/SIGTERM behavior, Compose profile isolation/no port/persistent volume/90-second grace,
  Docker image command, and Doctor checks.
- Production: assert stored-score/source reconstruction, latest eligible package per distinct
  event, immutable input fingerprint, canonical role selection, scheduler due/minimum/idempotency,
  direct-enqueue rejection, persisted article polling, prepared child and complete batch identity,
  WebP conversion, no private media URLs, three-child preflight, and zero WeChat calls in the DAG.
- Deployment acceptance: against production data, run the planner read-only; after optional
  services start outside the due window assert scheduler `due=false`, all weekly run/node/attempt
  and draft job/item/attempt counts unchanged, no provider-write log, no published port, zero
  restarts, and ordinary services healthy.
- Regression: existing weekly edition/V1/V2/live, execution governance, migration/downgrade, release
  contract, Ruff, format, strict mypy, full backend pytest, shell syntax, and `git diff --check`.
  Prove unrelated dirty-worktree failures before excluding them.

### 7. Wrong vs Correct

#### Wrong

```python
# Dynamic edges, content-bearing checkpoints, and post-handler accounting are forbidden.
plan = await model.generate_dag(article_prompt)
checkpoint = {
    "html": rendered_html,
    "image_paths": local_paths,
    "dependencies": plan["edges"],
}
result = await handlers[node_key](checkpoint)
node.used_bytes += len(result.body)
node.status = "succeeded"  # no lease or fencing check
```

#### Correct

```python
definition = WEEKLY_DAG_NODE_BY_KEY[node_key]       # code-owned edge set
claim = await repository.claim_ready(               # SKIP LOCKED + lease + fencing
    worker_id=worker_id,
    now=aware_now,
    lease_seconds=60,
)
governed = await governance.execute_node(            # authorize and reserve first
    claim=claim,
    handler=registry.get(claim.node),
)
status = await repository.complete(                  # exact attempt lineage
    claim,
    result=governed.result,
    execution_artifact_id=governed.execution_artifact_id,
    trace_event_id=governed.trace_event_id,
    now=aware_now,
)
# The checkpoint stores only opaque ref/hash/media type/size and execution IDs.
```

Authorization, reservation, lease ownership, fencing, exact lineage, and dependency fingerprints
must all succeed before a node can become a durable successful checkpoint.

For production, the correct entry boundary is the scheduler and frozen planner, never the fixture
CLI:

```python
# Wrong: bypass authenticated due/minimum checks with a caller-chosen fingerprint.
await service.enqueue(week_start=week_start, input_fingerprint=user_value)

# Correct: derive and persist one real immutable input before idempotent enqueue.
planned = await planner.plan(week_start=due_week, cutoff=aware_now)
artifact = checkpoints.put_json(planned.as_dict())
assert artifact.fingerprint == planned.fingerprint
await service.enqueue(week_start=due_week, input_fingerprint=planned.fingerprint, now=aware_now)
```
