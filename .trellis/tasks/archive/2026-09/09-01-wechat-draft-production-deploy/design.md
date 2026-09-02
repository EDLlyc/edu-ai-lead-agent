# Design: Production WeChat Draft Worker and One-Time Offline Release

## 1. Architecture boundaries

The change adds one optional production process without changing the ordinary API/content/WeCom
graph:

```text
weekly DAG worker
  -> official_account_weekly_dag_output (read/write)
  -> draft worker inbox mount (read-only)
  -> manifest week eligibility + strict aggregate validation
  -> immutable draft artifact volume
  -> PostgreSQL 0042 jobs/items/attempts
  -> official WeChat draft-only API
  -> three independent unpublished drafts
```

The worker has no network listener, FastAPI route, publication endpoint, mass-send operation,
homepage state transition, or browser automation. Existing application services do not import or
construct it.

## 2. Production activation settings

Add two settings:

- `WECHAT_MP_DRAFT_PRODUCTION_ENABLED=false`: explicit production-only acknowledgement. In
  production, an enabled worker requires this flag; in non-production, setting it is rejected so a
  copied production environment cannot silently weaken local/test semantics.
- `WECHAT_MP_DRAFT_MIN_WEEK_START`: optional in development, but required as an ISO Monday whenever
  production auto-enqueue is enabled.

The existing adapter, worker, auto-enqueue, credentials, official origin, request bounds, lease,
heartbeat, and retry validations remain cumulative. All settings remain default-off.

At activation, the operator derives and records the first Monday strictly after the server's
Asia/Shanghai activation instant. This date is installed atomically with the three enable flags.
The value is explicit evidence, not recomputed on restart.

## 3. Historical eligibility

`week_start` is already bound into the strict aggregate manifest and ZIP identity. The artifact
store receives an optional minimum week and enforces it for both `stage_weekly` and discovery.

Discovery performs a bounded deterministic inspection of every matching candidate up to a hard
scan ceiling, validates each aggregate enough to recover its authenticated week, rejects unsafe or
invalid inputs with existing typed counters, records older valid aggregates under a new typed
`wechat_mp_draft_before_activation` skip code, and only then selects at most `maximum` eligible
batches. Exceeding the complete-scan ceiling fails closed rather than letting old lexicographic
names starve a future aggregate.

An old aggregate produces no artifact copy, database job, provider client, or provider request.
Explicit `enqueue-weekly` follows the same rule, preventing an operator from bypassing the boundary.

## 4. Compose topology

Add optional profile `wechat-official-account-draft` with one
`wechat-official-account-draft-worker` service:

- inherits the immutable application image and backend environment;
- waits for successful migration;
- has `restart: unless-stopped` and a bounded stop grace period;
- publishes no port;
- mounts `official_account_weekly_dag_output` at a dedicated read-only inbox path;
- mounts new `wechat_mp_draft_artifacts` read/write at a separate staging path;
- injects only the WeChat adapter/worker/cutoff settings and existing secret variables;
- runs `python -m app.wechat_official_account_draft_main worker`.

The original nine production services remain the default release graph. Release/image contract
tests treat this worker as an explicitly reviewed optional application entrypoint: it shares the
same candidate image and must pass imports/settings/Compose validation, but ordinary restore/start
phases do not start it until the activation phase.

## 5. Migration compatibility

No new schema migration is required for the production gate or week cutoff. The release reviews
the existing additive chain through `20260901_0042` and changes the declaration to:

```json
{
  "reviewed": true,
  "previous_application_compatible": false
}
```

This passes the forward migration gate without claiming that the much older live application can
be automatically restored after schema advancement. `0042` populated-downgrade refusal remains.
Backups are mandatory; automatic database restore and Alembic downgrade remain forbidden.

## 6. One-time offline release

The task creates a new checksum-bound builder, validator, fake harness, and physical operator by
adapting—not reusing—the previous research controls. Every artifact is bound to the final fetched
Codeup SHA, current production baseline, candidate image ID, source and image-source manifests,
Compose topology, entrypoint list, Alembic head, operator hash, environment hashes, and rollback
evidence.

Ordered flow:

1. Commit only task changes; run full gates; fast-forward push Codeup and fetch the exact SHA.
2. Build/validate from a clean detached worktree; no dirty workspace byte is an input.
3. Read-only production preflight: current image/source/markers, service restart counts, database
   head, infra/API health, secrets-present booleans, weekly volume candidate count, zero current
   draft work, scheduler window, and existing provider/business vectors.
   A mode-0600 checksum-bound baseline fixes current `20260825_0036`, image/revision,
   managed-source fingerprint, environment hashes, and the exact running service set. An absent
   weekly volume is candidate count zero and is not created by preflight.
4. Transfer mode-0600 artifacts into one protected mode-0700 stage and load only an isolated
   candidate tag.
5. Acquire the backup lock, stop the optional worker if unexpectedly present, then quiesce existing
   writers in the proven dependency order. Create and validate fresh PostgreSQL/object/source/env/
   marker/image evidence.
6. Activate exact source/image while all WeChat draft flags remain false. Run only Alembic upgrade
   to `20260901_0042`; do not seed, publish, enqueue, or call providers.
7. Restore and verify the ordinary production services. Atomically install the explicit production
   gate and next-Monday cutoff, create the two Compose-labeled named volumes if absent, then start
   only the optional draft worker.
8. Verify worker running/restart-zero, historical skip counters, zero jobs/attempts/provider writes,
   healthy ordinary services, exact database head, safe logs, and stable immediate/30-second
   aggregate evidence.

## 7. Failure and rollback

- Before quiescence: leave production unchanged and retain evidence.
- After quiescence but before migration: restore the exact previous source/image/env/service set;
  optional worker remains absent.
- After migration: do not downgrade or automatically restore the previous application because
  compatibility is conservatively false. Stop the optional worker and all application writers,
  retain PostgreSQL/MinIO and the candidate, and report the incident state.
- After ordinary services pass but optional activation fails: stop/remove only the optional worker,
  restore its enable flags to false, retain the candidate/core services and migrated schema, and
  verify no draft job or side effect began. If that absence cannot be proven, enter the
  post-migration incident state.
- If the one-shot operator reaches the target migration but reports a false-negative core readiness
  failure, do not invoke it again. Incident recovery may restart only the already-activated
  candidate core with draft flags false and prove the exact runtime commit/image, target head,
  restart-zero health, absent draft volumes, and zero draft rows. The remaining optional activation
  then requires a new checksum-bound one-shot continuation identity that cannot replace source,
  rerun migration, call WeChat, or consume historical work.
- Never invoke the same failed activation candidate twice and never replay `outcome_unknown` work.

## 8. Security and evidence

No evidence output contains credentials, raw environment bytes, access tokens, AppID, provider
media IDs/bodies, article content, private paths, object keys, or row identifiers. Tests use fake
clients and no network. Production validation does not call WeChat; the first provider call is
allowed only later when a genuinely new eligible weekly aggregate appears.
