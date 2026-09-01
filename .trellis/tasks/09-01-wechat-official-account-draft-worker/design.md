# Design: Durable WeChat Official Account Draft Worker

## 1. Boundary

The feature is a downstream adapter, not another weekly DAG node:

```text
finalized live weekly aggregate inbox
                |
                v
strict aggregate/provenance loader
                |
                v
draft reconciler -> immutable local draft-source store -> PostgreSQL draft job
                                                           |
                                                           v
                                                    draft-only worker
                                                           |
                         uploadimg -> permanent thumb -> draft/add (one role at a time)
```

The weekly DAG remains unaware of WeChat. Its current handler is fixture-only, so the reconciler
does not treat a DAG `ready` row as production truth. Instead, it scans a configured artifact-owner
inbox and accepts only a strict finalized weekly aggregate whose live-acquisition audit and child
bindings validate. The existing HTTP adapter remains the only owner of official endpoint syntax,
token refresh, response validation, and provider error classification.

## 2. Components

### Domain and ports

- Add closed enums/value objects for job, child, and attempt state; canonical role ordering; request
  fingerprinting; and safe status projections.
- Add repository protocols for enqueue, claim, heartbeat, child side-effect
  start, child success/failure/unknown, job completion, and status lookup.
- Add a local artifact-store port whose public identity is an opaque, content-addressed ref. The
  database never receives a path.

### Preparation and artifact staging

- Split the current pure preparation responsibility from provider execution so enqueue and worker
  can reuse the exact same preflight contract without a dummy HTTP client.
- Add `load_finalized_weekly_edition(...)` beside the existing strict child loader. It validates the
  aggregate manifest/index/outer ZIP, recomputes the batch identity, requires live-acquisition
  provenance, rejects fixture truth, and validates the three canonical embedded child directories.
- `enqueue-weekly` first loads one weekly aggregate and prepares all three child sources. It then writes immutable
  content-addressed copies under a configured draft artifact root using a temporary sibling and
  atomic rename. Existing copies must byte-match; conflicts fail closed.
- Automatic reconciliation only enumerates bounded content-addressed aggregate directories under
  the configured weekly inbox and applies the same strict loader/staging path as explicit enqueue.
  A fixture-only or provenance-mismatched aggregate never creates a job or provider call.
- A stored ref carries only a versioned prefix and full artifact fingerprint. Resolution validates
  the ref grammar, derives the private path from configuration, and re-runs the finalized-child
  loader before every execution attempt.

### Durable model

Migration `20260901_0042` adds:

| Table | Purpose |
|---|---|
| `wechat_mp_draft_jobs` | One idempotent weekly batch; request/account/batch identities, status, retry schedule, lease/fencing, safe error and timestamps |
| `wechat_mp_draft_items` | Exactly three ordered roles; opaque source ref and immutable content identities, child state, side-effect marker, safe result metadata |
| `wechat_mp_draft_attempts` | Immutable per-child attempt history with job fencing identity, safe endpoint/error/result and timestamps |

Important constraints:

- unique `request_fingerprint` and unique `(job_id, ordinal)` / `(job_id, role)`;
- exactly the three closed roles and ordinals `1..3`;
- lease fields exist only in `running` job state;
- successful items have a completion timestamp and draft-media SHA-256, never the media ID;
- `outcome_unknown` is terminal and cannot be selected by the claim query;
- source refs and all SHA fields have closed grammar checks.

The account identity is `sha256(policy-version + normalized AppID)` and the AppID itself is not
persisted. The batch request fingerprint additionally binds the live aggregate fingerprint,
canonical item identities, and the comment/source policy so a policy change cannot silently reuse
an earlier job.

## 3. Execution State Machine

```text
queued -> running -> ready
   ^         |
   |         +-> retryable_failed -> queued (bounded, known outcome only)
   |         +-> terminal_failed
   |         +-> outcome_unknown
   +---------+  lease reclaim only before current item side-effect start
```

Each worker attempt performs these steps:

1. Claim one job with `FOR UPDATE SKIP LOCKED`; increment fencing and create the running attempt.
2. Resolve and preflight all three immutable children before any provider request.
3. Skip already-succeeded items and select the first incomplete ordinal.
4. In a short fenced transaction, mark that item `running` and `side_effect_started_at`.
5. Outside the transaction, invoke existing draft-only preparation/execution for that one item while
   a heartbeat renews the job lease.
6. In one fenced transaction, persist either success, known failure/retry scheduling, or unknown.
7. Repeat from the next child; after all three succeed, mark the job `ready` and emit the safe ready
   log.

If the process disappears after step 4, the next claim reconciliation terminalizes the current
item and job as `outcome_unknown`. If it disappears before step 4, the expired lease can be safely
reclaimed. This deliberately favors no duplicate drafts over automatic recovery from ambiguity.

## 4. Process and CLI

Add `app.wechat_official_account_draft_main` with:

```text
enqueue-weekly WEEKLY_AGGREGATE_DIR
reconcile [--once]
status JOB_UUID
worker [--once | --drain]
```

- `reconcile` discovers finalized live weekly aggregates and idempotently stages/enqueues them;
  current fixture weekly DAG aggregates fail the provenance gate.
- The long-running worker lets its first loop reconcile before claiming, matching the existing
  independent dispatcher pattern without making the weekly DAG call WeChat.
- Worker concurrency is fixed to one for the initial account-scoped implementation. Scaling across
  accounts is deferred; process-local stable-token coalescing remains effective.
- New settings cover automation enabled, poll interval, lease/heartbeat, max attempts, retry base,
  weekly artifact root, and draft staging root. Defaults are disabled and bounded.
- A Compose profile may expose the independent process for local demonstration, but this task does
  not deploy or activate it on a server.

## 5. Error Mapping

| Error | Durable result |
|---|---|
| Fixture or missing/mismatched live provenance | Auto scan skips; explicit enqueue exits non-zero with the same stable code; zero job/provider calls |
| Local aggregate/source/ref/preflight invalid | `terminal_failed` / safe preparation code; zero provider calls |
| Known provider rate/transient rejection | `retryable_failed`; bounded retry of only the incomplete child |
| Provider input/permission/invalid response | `terminal_failed` |
| Adapter `wechat_mp_outcome_unknown` | item/job `outcome_unknown`; no automatic retry |
| Cancellation, crash, or lease expiry before side-effect marker | reclaimable after lease expiry |
| Cancellation, crash, or lease expiry after side-effect marker | item/job `outcome_unknown`; no reclaim |
| Fencing mismatch | stale worker result rejected; current owner remains authoritative |

## 6. Compatibility and Rollback

- Existing direct `create_draft` and `create_weekly_drafts` callers remain compatible.
- Existing API, fixture weekly DAG, editor handoff, weekly exporter, WeCom delivery, and publication
  truth do not change.
- Disabling automation stops new reconciliation/claims but preserves durable status.
- Migration downgrade removes only the three new tables/indexes/constraints. The content-addressed
  staging tree is immutable and may be removed separately only by an explicit maintenance action.
- No live provider request is part of automated tests or implementation verification.

## 7. Trade-offs

- PostgreSQL plus a local content-addressed source store is more work than a one-shot script, but it
  is required for restart-safe idempotency and to keep private paths/content out of durable rows.
- Requiring the aggregate live-acquisition audit deliberately excludes the current fixture DAG.
  This is safer than treating orchestration readiness as content provenance; a future live DAG can
  emit the same validated aggregate without changing this worker.
- Persisting only a media-ID fingerprint means status cannot deep-link to the provider draft. This
  is intentional: the project-wide persistence contract forbids raw temporary/provider media IDs,
  and the draft is visible in the official WeChat backend.
- Unknown outcomes stop automation and require external inspection. Automatic replay would be more
  convenient but could create duplicate drafts, so it is outside the MVP.
