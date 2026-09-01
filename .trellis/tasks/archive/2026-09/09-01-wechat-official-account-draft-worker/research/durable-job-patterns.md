# Research: durable job patterns for the WeChat Official Account draft worker

- Query: 梳理仓库内 WeCom delivery、official-account weekly DAG 及其他 durable job 的 PostgreSQL job/attempt、幂等、租约、fencing、unknown outcome、CLI/worker 模式，并给出可复用类、表、测试与配置。
- Scope: internal
- Date: 2026-09-01

## Findings

### Recommended pattern

The closest complete design is a combination of three existing implementations rather than a copy
of any single one:

1. Reuse the WeCom delivery boundary for the high-level shape: enqueue a durable job first, let an
   independent worker make provider calls outside database transactions, persist a bounded attempt,
   and make an ambiguous write terminal rather than automatically repeating it.
2. Reuse the weekly DAG repository for monotonic fencing. WeCom uses a random lease token, but the
   weekly DAG additionally increments a durable `fencing_token` and requires exact job/attempt/
   worker/fencing/lease ownership at heartbeat and completion.
3. Reuse the local Official Account worker's intent-before-I/O and `result_unknown` recovery idea.
   If an external write was started but no durable result was recorded, recovery must not assume
   failure and repeat the provider call.

For this task, use one durable job per finalized article, group the canonical three jobs by the
weekly source run, and enqueue all three identities atomically after the existing all-three local
preflight. Keep the weekly DAG itself free of WeChat imports/calls. The downstream reconciler/CLI
may discover a ready weekly result and enqueue draft jobs, while only the draft worker performs
WeChat writes.

### Files found

- `.trellis/spec/backend/wecom-delivery.md` — implemented external-delivery job/attempt, retry,
  unknown-outcome, security, and worker contract.
- `.trellis/spec/backend/official-account-weekly-dag.md` — durable PostgreSQL checkpoint, fencing,
  metadata-only artifact, retry, CLI, and worker contract.
- `.trellis/spec/backend/wechat-official-account-drafts.md` — current draft-only provider contract;
  presently documents that no worker/CLI/database layer exists.
- `.trellis/spec/backend/database-guidelines.md` — short-transaction, `SKIP LOCKED`, idempotency,
  persistence, and migration rules.
- `backend/app/application/services/wecom_delivery.py` — durable enqueue/retry/reconcile/executor and
  provider-side-effect state machine.
- `backend/app/wecom_dispatcher_main.py` — opt-in long-running dispatcher with safe disabled mode,
  concurrency, polling, and graceful shutdown.
- `backend/app/application/ports/official_account_weekly_dag.py` — repository/service protocols.
- `backend/app/infrastructure/db/official_account_weekly_dag.py` — strongest repository example for
  claims, attempts, monotonic fencing, heartbeat, completion, failure, and retry.
- `backend/app/application/services/official_account_weekly_dag.py` — service heartbeat/cancellation/
  retry-backoff orchestration.
- `backend/app/official_account_weekly_dag_main.py` — structured `enqueue`, `enqueue-due`, `status`,
  `retry`, and `worker` CLI.
- `backend/app/infrastructure/db/models.py` — current WeCom, local Official Account, and weekly DAG
  ORM models and constraints.
- `backend/app/infrastructure/db/official_account_local.py` — existing Official Account claim,
  random lease fencing, idempotent local-draft persistence, and terminal unknown result handling.
- `backend/app/application/services/official_account_local.py` — intent fence before paid/provider
  I/O and conservative unknown recovery.
- `backend/app/application/ports/wechat_official_account.py` — typed WeChat errors, including
  `wechat_mp_outcome_unknown`, and safe draft receipt/result contracts.
- `backend/app/infrastructure/wechat_official_account/client.py` — current provider adapter; every
  authenticated write timeout is typed unknown and not retried in the adapter.
- `backend/app/application/services/wechat_official_account_draft.py` — current all-local-preflight
  then body upload/thumb upload/draft-add orchestration.
- `backend/app/core/config.py`, `.env.example`, `compose.yaml` — default-disabled settings and opt-in
  process wiring patterns.
- `backend/alembic/versions/20260805_0018_wecom_delivery.py` — original WeCom job/attempt migration.
- `backend/alembic/versions/20260831_0040_official_account_weekly_dag.py` — current three-table
  durable/fenced DAG migration with populated-downgrade refusal.
- `backend/tests/integration/test_official_account_weekly_dag.py` — PostgreSQL idempotency,
  concurrency, fencing, resume, cancellation, and lineage tests.
- `backend/tests/integration/test_wecom_slot_delivery_concurrency.py` — PostgreSQL provider-lane
  serialization and stale-running-to-unknown tests.
- `backend/tests/unit/test_wecom_delivery.py` — eligibility, idempotent enqueue, candidate filtering,
  and safe defaults.
- `backend/tests/unit/test_official_account_worker.py` — local draft/provider unknown-result tests.
- `backend/tests/contract/test_wechat_official_account_client.py` — exact no-replay assertion for a
  WeChat write timeout.

### PostgreSQL job and attempt schema

The WeCom job row is a practical single-side-effect-job baseline. It persists immutable source and
content identity, a unique request fingerprint, status, attempt count, availability/backoff time,
lease ownership, heartbeat, bounded error code, and timestamps
(`backend/app/infrastructure/db/models.py:4851-4916`). Its constraints enforce a closed status set,
non-negative attempt count, a unique request fingerprint, and a claim index over status/time/lease
(`backend/app/infrastructure/db/models.py:4918-4953`). The child attempt table records kind, attempt
number, stable child request fingerprint, safe provider request/code fields, result state, and
bounded latency without raw provider bodies or temporary media IDs
(`backend/app/infrastructure/db/models.py:4988-5023`).

The weekly DAG models add the fencing fields missing from the WeCom job. Each node has
`attempt_count`, `max_attempts`, `available_at`, lease owner/expiry/heartbeat, and a monotonic
`fencing_token` (`backend/app/infrastructure/db/models.py:5982-6007`). The migration makes
running/non-running lease shape a database invariant and indexes the claim tuple
(`backend/alembic/versions/20260831_0040_official_account_weekly_dag.py:117-176`). Every attempt has
a composite immutable identity `(run_id, task_id, node_key, attempt_no)`, records the exact fencing
token/worker/input fingerprint, and has a closed state set including `lease_expired`
(`backend/alembic/versions/20260831_0040_official_account_weekly_dag.py:185-237`).

The new draft tables should use the latter ownership shape even if the job is simpler than a DAG:

- Job: UUID; typed weekly source identity; canonical role; article/content/artifact fingerprints;
  account fingerprint (never raw AppID); request/policy version fingerprint; closed status;
  `attempt_count`, `max_attempts`, `available_at`; lease owner/expiry/heartbeat; monotonic
  `fencing_token`; provider-write-intent state; safe error code; timestamps.
- Attempt: `(job_id, attempt_no)` primary/unique identity; fencing token; worker; input/request
  fingerprint; status; safe endpoint/error/provider code; `provider_write_started_at`; completion.
- Keep article HTML, image bytes, credentials, raw provider bodies/errors, local paths, access
  tokens, and temporary material IDs out of job/attempt/status projection. Database guidelines
  explicitly require short claim/result transactions and no transaction across external I/O
  (`.trellis/spec/backend/database-guidelines.md:87-105`).

The current unique Alembic head is `20260901_0041`
(`.trellis/spec/backend/database-guidelines.md:5-12`), so the next revision is `0042` only if no
parallel task advances the head first. Follow the weekly migration's conservative downgrade: an
empty additive table set may be removed, but populated delivery audit data must refuse destructive
downgrade (`backend/alembic/versions/20260831_0040_official_account_weekly_dag.py:240-262`).

### Enqueue and idempotency

`enqueue_wecom_delivery` validates eligibility before insert, derives a stable request fingerprint
from provider namespace, source package, recipient/mode/version/content and message-kind flags, and
returns the locked existing row on a compatible replay
(`backend/app/application/services/wecom_delivery.py:68-167`). It also handles the concurrent insert
race by relying on the database unique constraint, rolling back `IntegrityError`, and reloading the
winning row (`backend/app/application/services/wecom_delivery.py:169-223`). This is the pattern to
reuse; a Python check alone is not enough.

The weekly DAG is stricter when a deterministic business identity is replayed. It performs an
`INSERT .. ON CONFLICT DO NOTHING`, locks the resulting row, validates every frozen identity field,
and only creates child rows on the first insert
(`backend/app/infrastructure/db/official_account_weekly_dag.py:65-145`). The new draft enqueue should
similarly distinguish:

- exact compatible replay: return the existing job ID with `created=false`;
- same business key with changed article/content/artifact/account/policy identity: fail closed;
- concurrent exact replay: exactly one row and one future provider action.

Do not use raw AppID as an account key because the current WeChat settings treat it as a secret.
Derive a stable application-owned account fingerprint in memory and persist only that digest. Bind
the idempotency identity at least to account fingerprint, canonical role, Article/content/artifact
fingerprints, mode `draft_only`, and worker/policy version. A provider media ID must never be the
idempotency key.

### Claim, lease, heartbeat, and fencing

The strongest claim implementation is `PostgresOfficialAccountWeeklyDagRepository.claim_ready`:

- validates bounded worker/lease inputs;
- selects one candidate with `FOR UPDATE SKIP LOCKED` rather than locking the ready set;
- expires the old attempt before reclaim;
- enforces maximum attempts;
- increments both attempt count and monotonic fencing token;
- writes the immutable running attempt in the same transaction;
- returns a frozen claim containing the exact ownership identity
  (`backend/app/infrastructure/db/official_account_weekly_dag.py:166-324`).

Heartbeat and completion/failure look up the row with exact run/job identity, running state, worker,
attempt number, and fencing token. Completion additionally requires an unexpired lease
(`backend/app/infrastructure/db/official_account_weekly_dag.py:326-395` and
`backend/app/infrastructure/db/official_account_weekly_dag.py:617-682`). On lease expiry the prior
attempt is durably changed to `lease_expired` and the job becomes retryable before a replacement
claim is created (`backend/app/infrastructure/db/official_account_weekly_dag.py:574-605`).

The local Official Account repository is a useful simpler reference, but it uses a random UUID
lease token plus attempt count rather than a dedicated monotonic fence: claim uses `SKIP LOCKED` and
records a token (`backend/app/infrastructure/db/official_account_local.py:728-783`), while all later
writes re-lock and compare running state/token/attempt number
(`backend/app/infrastructure/db/official_account_local.py:1877-1906`). Prefer the weekly DAG's
explicit `fencing_token` for the new worker.

The application service should run the provider work and heartbeat concurrently. The weekly service
cancels work when heartbeat wins/fails, maps lease loss to a stable retryable code, and guarantees
task cleanup (`backend/app/application/services/official_account_weekly_dag.py:135-195` and
`backend/app/application/services/official_account_weekly_dag.py:220-285`). A stale worker must be
unable to persist success, failure, or a provider receipt after a replacement owns the job.

### Provider writes and unknown outcomes

This task is more conservative than deterministic weekly DAG work. The existing WeChat port exposes
`WeChatMpOutcomeUnknownError` with `unknown=True`
(`backend/app/application/ports/wechat_official_account.py:41-73` and
`backend/app/application/ports/wechat_official_account.py:152-159`). The HTTP adapter applies
`unknown_on_timeout=True` to every authenticated media/draft write and converts timeouts to that
typed error without an internal replay (`backend/app/infrastructure/wechat_official_account/client.py:208-231`
and `backend/app/infrastructure/wechat_official_account/client.py:291-335`). Its contract test proves
one upload call, an unknown code, and no token/raw-detail leakage
(`backend/tests/contract/test_wechat_official_account_client.py:401-422`).

Therefore the durable worker must persist a write intent before the first upload. Recovery rules:

- expired lease before any provider-write intent: safe to reclaim under a new fencing token;
- known retryable provider rejection where the adapter confirms no accepted write: bounded backoff
  may return the same job to queued state;
- timeout/ambiguous transport at upload, thumb, or draft-add: terminal `outcome_unknown`, never
  automatic retry;
- process/lease loss after write intent but before a receipt: conservatively terminal
  `outcome_unknown`, never automatic reclaim or resend;
- confirmed draft-add success: persist success under the still-current fence, then clear lease.

The analogous WeCom slot code marks any stale running provider job `delivery_unknown`, records an
unknown attempt for the unresolved child, clears its lease, and does not reclaim it
(`backend/app/application/services/wecom_delivery.py:543-595`). The PostgreSQL test verifies a stale
running job becomes `delivery_unknown` while the next ordinal may proceed
(`backend/tests/integration/test_wecom_slot_delivery_concurrency.py:1183-1225`). The local Official
Account visual path similarly creates a durable intent before provider I/O; if a later worker sees
the still-generating intent, it records `result_unknown` instead of issuing a second paid call
(`backend/app/application/services/official_account_local.py:1449-1475`).

Do not blindly reuse legacy WeCom's non-slot reclaim behavior: it can reclaim expired `running` jobs
(`backend/app/application/services/wecom_delivery.py:596-671`) and is safe there only because child
success is checkpointed and already-delivered children are skipped. The current WeChat draft service
has no durable per-upload checkpoints, so replaying the whole article after an interrupted write can
duplicate material or drafts.

### Retry and status rules

WeCom separates automatic retry from operator retry. Known retryable errors requeue the same job with
bounded exponential backoff; unknown outcomes are terminal; explicit retry may reopen selected
terminal states but never delivered (`backend/app/application/services/wecom_delivery.py:284-317`
and `backend/app/application/services/wecom_delivery.py:802-861`). The weekly DAG allows explicit
retry only for `retryable_failed`, preserves succeeded siblings, and refuses active, succeeded, or
terminal nodes (`backend/app/infrastructure/db/official_account_weekly_dag.py:441-489`).

For the new draft worker, keep the stricter rule: automatic and explicit retry must both refuse
`outcome_unknown` because repeating `draft/add` can create a duplicate. A manually verified
operator may create a new, explicitly distinct job only through a separately designed recovery
operation; that is outside the default automation. Successful draft state remains draft-only and
must not mutate publication/pin state, as required by the current WeChat contract
(`.trellis/spec/backend/wechat-official-account-drafts.md:9-13` and
`.trellis/spec/backend/wechat-official-account-drafts.md:155-169`).

The status projection should expose only job ID, source/run identity, role, article/content
fingerprints, closed state, attempt count, safe error code, timestamps, and `not_published=true`.
Avoid lease owner/token/fence, local path, HTML, image/material identifiers, provider response text,
and credentials. The weekly DAG's bounded metadata-only projection is the reference
(`.trellis/spec/backend/official-account-weekly-dag.md:174-185`).

### CLI, worker, and configuration

The weekly CLI is the best operator interface reference. It has separate `enqueue`, `enqueue-due`,
`status`, `retry`, and `worker` commands and emits deterministic JSON
(`backend/app/official_account_weekly_dag_main.py:36-139`). Its worker validates bounded concurrency
and poll settings, supports `--once`/`--drain`, handles SIGINT/SIGTERM, stops new claims, and prints
safe status projections (`backend/app/official_account_weekly_dag_main.py:144-196`).

The WeCom dispatcher is the long-running process reference. It exits into a safe idle state before
constructing a database engine or HTTP client when disabled, creates one unique worker ID per
process/concurrency lane, gives one lane reconciliation ownership, polls without busy spinning, and
disposes resources on shutdown (`backend/app/wecom_dispatcher_main.py:24-105`). Compose makes it an
explicit profile with no published port and passes only opt-in settings
(`compose.yaml:601-633`). The weekly worker profile additionally uses a 90-second stop grace period
and a persistent artifact-owner volume (`compose.yaml:390-414`).

Add draft-worker-specific settings instead of overloading `WECHAT_MP_ENABLED`:

- `WECHAT_MP_DRAFT_WORKER_ENABLED=false` (must imply current `WECHAT_MP_ENABLED=true`);
- `WECHAT_MP_DRAFT_AUTO_ENQUEUE_ENABLED=false` if automatic ready-run reconciliation is separate;
- bounded poll, concurrency, lease, heartbeat, maximum attempts, and retry-base settings;
- validate heartbeat strictly shorter than lease, following the existing WeCom invariant
  (`backend/app/core/config.py:535-549`);
- keep existing `WECHAT_MP_MODE=draft_only`, exact API origin, credential validation, image and
  response bounds (`.env.example:276-285`).

Because `WeChatOfficialAccountHttpClient` currently rejects every non-development environment
(`backend/app/infrastructure/wechat_official_account/client.py:338-349`), a local-only worker can
reuse it unchanged. Do not silently wire a server/production Compose path unless the task explicitly
changes that environment boundary. The user asked for code automation, not deployment.

### Tests to reuse and extend

Minimum PostgreSQL behavior should mirror these existing assertions:

- Idempotent exact enqueue and metadata-only terminal result:
  `backend/tests/integration/test_official_account_weekly_dag.py:141-235`.
- Concurrent claims yield exactly one owner; expiry increments fencing; stale owner cannot write;
  prior attempt becomes `lease_expired`:
  `backend/tests/integration/test_official_account_weekly_dag.py:325-384`.
- Retry is branch/job-local and does not recompute successful work:
  `backend/tests/integration/test_official_account_weekly_dag.py:241-318`.
- Service reconstruction after each checkpoint resumes from PostgreSQL:
  `backend/tests/integration/test_official_account_weekly_dag.py:557-594`.
- Cancellation clears durable ownership/governance resources:
  `backend/tests/integration/test_official_account_weekly_dag.py:599-652`.
- Provider-lane contention and stale-started work become unknown rather than replayed:
  `backend/tests/integration/test_wecom_slot_delivery_concurrency.py:1095-1177` and
  `backend/tests/integration/test_wecom_slot_delivery_concurrency.py:1183-1225`.
- WeChat write timeout makes exactly one call and returns unknown:
  `backend/tests/contract/test_wechat_official_account_client.py:401-422`.
- Settings remain default disabled and client construction makes no real provider call; current
  WeChat spec requires fake transports for default tests
  (`.trellis/spec/backend/wechat-official-account-drafts.md:171-189`).

Add task-specific tests for atomic enqueue of the canonical three roles, compatible replay,
conflicting identity, `SKIP LOCKED` contention, heartbeat, lease loss before write intent (reclaim),
lease/process loss after write intent (terminal unknown), known retryable backoff, max attempts,
successful fenced receipt, status redaction, CLI bounds/JSON, graceful worker shutdown, disabled
zero-client construction, migration upgrade/empty downgrade/populated-downgrade refusal, and zero
`freepublish`/publication-state mutations.

## External references

No external reference was needed for this query. The repository's implemented specs, PostgreSQL
models, migrations, and executable tests are the authoritative sources. The provider behavior used
here is already frozen in `.trellis/spec/backend/wechat-official-account-drafts.md` and the WeChat
HTTP contract tests.

## Related specs

- `.trellis/spec/backend/wechat-official-account-drafts.md`
- `.trellis/spec/backend/wecom-delivery.md`
- `.trellis/spec/backend/official-account-weekly-dag.md`
- `.trellis/spec/backend/database-guidelines.md`
- `.trellis/spec/backend/error-handling.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`

## Caveats / Not Found

- The current WeChat draft slice deliberately has no durable job, worker, scheduler, CLI, or
  migration (`.trellis/spec/backend/wechat-official-account-drafts.md:9-13`); this task must extend
  the spec rather than claim those pieces already exist.
- WeCom's legacy job has lease tokens but no monotonic fencing column. Use its delivery state and
  unknown-outcome semantics, not its ownership model.
- Weekly DAG handlers are deterministic/checkpointed work. Its full execution-governance allocation
  ledger is likely unnecessary for a narrow downstream provider adapter; reuse the repository
  fencing mechanics without importing the entire 16-node governance graph.
- Current WeChat orchestration performs several writes in one method. Without per-write durable
  checkpoints, the safe recovery boundary is coarse: once provider write intent starts, an
  interrupted attempt must become unknown. Finer resume would require a larger redesign and durable
  handling of provider media/CDN references, with additional security and retention decisions.
- The current receipt carries a draft media ID in memory
  (`backend/app/application/ports/wechat_official_account.py:190-208`), while existing delivery specs
  prohibit persisting temporary media IDs. Decide explicitly whether the returned draft ID is a
  durable operator reference or must be stored only as a digest; do not expose it in default status
  merely because the in-memory receipt contains it.
- Artifact-owner/path resolution and the exact foreign key from a ready weekly DAG run to each
  finalized child are outside this research topic. The DAG persists opaque artifact refs and never
  filesystem paths (`.trellis/spec/backend/official-account-weekly-dag.md:174-199`); the draft worker
  must resolve those refs through an artifact owner rather than persist local paths in job rows.
- The Alembic head can move while other agents work. Re-check the unique head immediately before
  choosing a revision ID or updating Doctor/migration assertions.
