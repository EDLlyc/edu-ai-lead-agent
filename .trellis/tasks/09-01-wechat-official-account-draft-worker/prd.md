# 微信公众号自动草稿任务

## Goal

Turn one ready weekly Official Account batch into three independent WeChat Official Account
drafts automatically and durably. The operator should only need to open the WeChat draft box for
the later editorial/publication decision; this feature must never publish, mass-send, pin, or
claim that a draft was published.

## Background and Confirmed Facts

- The default-disabled development adapter already obtains a stable access token, uploads body
  images and a permanent cover thumbnail, and creates exactly one draft per finalized V2 child
  (`.trellis/spec/backend/wechat-official-account-drafts.md:5-13`). A real draft creation has
  already succeeded against the configured account.
- The application service already validates all three canonical roles before the first provider
  write (`.trellis/spec/backend/wechat-official-account-drafts.md:121-125`), but there is no durable
  job, scheduler, worker, CLI, or database receipt (`.trellis/spec/backend/wechat-official-account-drafts.md:9-13`).
- The weekly DAG persists only opaque artifact metadata and deliberately keeps private filesystem
  paths out of PostgreSQL (`.trellis/spec/backend/official-account-weekly-dag.md:174-182`). It must
  remain free of WeChat side effects. Its current runtime always uses fixture handlers, so a DAG
  `ready` row is not sufficient live-content provenance
  (`research/artifact-handoff.md`, "Important product-data caveat").
- The canonical weekly role order is `official_anchor`, `industry_trend`, `application_case`; one
  draft must be created for each role rather than one combined three-article draft.
- The current migration head is `20260901_0041`; this feature requires a new additive migration.

## Requirements

### R1. Independent automatic downstream trigger

- Add a separate default-disabled draft scheduler/reconciler that scans a configured weekly-artifact
  inbox and enqueues only complete, immutable weekly aggregates with validated live-acquisition
  provenance. It must not import or call WeChat from the weekly DAG itself.
- Fixture-only aggregates, including the current durable weekly DAG output, are ineligible for real
  provider execution and must produce zero WeChat calls. Automatic scans skip them with one safe
  reason code; explicit enqueue rejects them with the same stable code and a non-zero exit.
- Add an explicit `enqueue-weekly` CLI path for safe local backfill from one finalized live weekly
  aggregate directory; it uses the same provenance gate as automatic reconciliation.
- A configured local artifact owner resolves paths from opaque content-addressed references; no
  source path is persisted in a job, attempt, log, or status response.

### R2. Immutable three-child preflight

- Enqueue accepts one aggregate containing exactly the canonical three roles and stages immutable,
  content-addressed copies of the finalized V2 children.
- Add one public strict aggregate loader that validates manifest/index/outer ZIP identity, live
  acquisition audit, local-only/unpublished truth, batch fingerprint, canonical child paths, and
  every child binding before returning runtime-only source directories.
- The complete three-child set must pass the existing manifest, ZIP, release, mobile, HTML, media,
  checksum, size, and role checks before the first provider write.
- A missing, changed, duplicate, symlinked, or invalid third child creates no provider call.

### R3. Durable idempotency and progress

- PostgreSQL owns one weekly draft job, three ordered child states, and immutable attempt history.
- The request identity binds the account fingerprint, the three role/content/artifact identities,
  comment/source policy, and a versioned draft policy. Re-enqueueing the same request returns the
  existing job and cannot create another provider call.
- A succeeded child is never replayed. If the process restarts after one or two persisted successes,
  the next valid attempt resumes at the first incomplete child.

### R4. Lease, fencing, and conservative external-write semantics

- Workers claim with `FOR UPDATE SKIP LOCKED`, a bounded lease, heartbeat, monotonic fencing token,
  and bounded known-safe retry attempts.
- Provider work occurs outside database transactions. The worker durably marks the current child
  as side-effect-started before the first WeChat write.
- A known retryable provider rejection may retry within the configured bound. A transport timeout,
  cancellation/lease loss after side-effect start, or process crash in that interval becomes the
  terminal `outcome_unknown` state and is never automatically replayed.
- A lease lost before side-effect start may be reclaimed. A stale worker cannot persist success,
  failure, or heartbeat after another attempt owns the job.

### R5. Safe persistence and observability

- Persist safe business identity, status, attempt count, timestamps, stable error code, endpoint,
  uploaded-image count, and a one-way draft media fingerprint after success.
- Never persist or expose AppID, AppSecret, access token, raw provider response, provider message,
  original draft media ID, article body/HTML/image bytes, private object key, or filesystem path.
- Provide a JSON status CLI showing the batch and three ordered child states, plus structured
  transition logs. A final ready log is the MVP notification boundary; external chat/email alerts
  are deferred.

### R6. Default-off, draft-only operation

- Scheduler and worker do nothing unless both the existing WeChat adapter and the new automation
  switch are explicitly enabled in development.
- The only provider content mutation is draft creation. No API route or frontend is added.
- Draft success must retain `not_published=true` and must not change homepage pin or operator
  publication state.

## Acceptance Criteria

- [x] A valid live weekly aggregate is reconciled into one durable job with exactly three canonical
      child states, and a fake provider run produces exactly three independent draft receipts.
- [x] Automatic reconciliation skips a fixture-only or missing/mismatched-provenance aggregate with
      a safe reason code; explicit enqueue rejects it with that code and a non-zero exit. Both paths
      create no job/provider call, including for current fixture weekly DAG output.
- [x] Calling automatic reconciliation and `enqueue-weekly` repeatedly with the same content returns
      the same job identity and produces no duplicate draft calls.
- [x] Invalid or tampered input in any role fails before the first token/media/draft request.
- [x] Restart after one persisted child success skips that child and completes only the remaining
      roles.
- [x] A known retryable rejection follows the bounded retry policy; a write timeout or stale lease
      after side-effect start becomes terminal `outcome_unknown` and is never reclaimed/replayed.
- [x] Concurrent workers claim distinct eligible work or no work; stale fencing tokens cannot
      heartbeat or commit an outcome.
- [x] Status output and structured logs contain no credentials, access tokens, raw draft media IDs,
      provider bodies/messages, content bytes, object keys, or filesystem paths.
- [x] With automation disabled, ordinary API, weekly DAG, local workers, fixtures, and tests construct
      no WeChat client and make zero provider requests.
- [x] Migration/metadata parity, clean upgrade to the new head, downgrade, focused unit/contract/
      PostgreSQL integration tests, Ruff, strict mypy, task validation, and `git diff --check` pass
      without a real provider call.

## Out of Scope

- `freepublish`, mass send, scheduled publication, homepage pinning, browser/login automation, or
  interpreting a draft as a published article.
- FastAPI routes, frontend controls, public multi-tenant operation, and server deployment.
- Replacing the current fixture weekly DAG handlers with a production live-news DAG; the draft
  reconciler consumes the already-supported finalized live weekly aggregate format instead.
- Arbitrary article counts or combining three weekly roles into one WeChat draft request.
- Automatic replay or automatic reconciliation of an ambiguous `outcome_unknown` result.
- External notification integrations beyond structured logs and the status CLI.

## Blocking Open Questions

None. The user's requested default behavior is automatic draft creation only; publication remains
outside this task.
