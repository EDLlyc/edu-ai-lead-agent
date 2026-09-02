# PRD: WeChat Official Account Draft Worker Production Deployment

## Goal

Make the committed, draft-only WeChat Official Account worker safe to run on the production
server, then release and activate it without changing the existing news/content delivery behavior.
The observable outcome is exactly three independent unpublished WeChat drafts for each eligible new
weekly aggregate, with durable job state and no automatic publication or mass send.

## Background and confirmed facts

- Commit `755050b` implements a durable three-role draft worker and migration
  `20260901_0042`; migration `20260901_0041` precedes it.
- The worker and automatic reconciliation are default-off. Current settings reject an enabled
  draft worker whenever `APP_ENV != development`.
- Current Compose and the production release service inventory contain no draft-worker process.
- The release contract rejects the committed migration changes because
  `deploy/release/migration-compatibility.json` still declares `reviewed: false`.
- The existing weekly DAG output is a named Compose volume. A production draft worker must consume
  that output through a read-only mount and keep its own content-addressed staging artifacts on a
  separate persistent volume.
- Current reconciliation discovers matching aggregate directories in deterministic name order.
  A new database has no historical draft-job fingerprints, so every valid historical aggregate in
  the mounted inbox is eligible unless activation adds an explicit boundary.
- The user chose not to backfill historical aggregates. Production activation must set the minimum
  eligible `week_start` to the first Monday strictly after activation. The manifest-bound weekly
  date, rather than mutable filesystem time, owns this decision.
- The direct adapter creates drafts only. It has no `freepublish`, mass-send, homepage-pin,
  browser-login, or publication-state capability.
- Repository `main` is ahead of `origin/main`, and the shared worktree contains unrelated dirty
  changes. Production inputs must come from a clean committed/fetched revision, never the dirty
  working tree.
- The reviewed standard release entrypoint exists and the `edu-ai-production` SSH alias is
  configured, but `RELEASE_IMAGE_REPOSITORY` and `RELEASE_SSH_HOST` are currently unset. The prior
  local-tag/offline deployment was explicitly a one-time exception and is not automatically
  reusable for this release.
- The user explicitly authorized a newly reviewed one-time offline immutable release for this
  final commit. The exception does not authorize an ad-hoc pull/build, reuse of stale candidate
  identities, or a future generic local-tag deployment path.

## Requirements

### R1. Production safety gate

- Keep all draft automation off by default.
- Permit production execution only behind a new explicit production activation setting in
  addition to `WECHAT_MP_ENABLED`, `WECHAT_MP_DRAFT_WORKER_ENABLED`, and the existing `draft_only`
  mode.
- Fail closed when credentials, official API origin, worker/auto-enqueue dependency, lease timing,
  or production activation is invalid.
- Never expose AppSecret, access tokens, provider bodies, media IDs, article content, or private
  artifact paths in health output or logs.

### R2. Runtime topology

- Add one dedicated Compose worker with no published network port.
- Mount weekly DAG output read-only as the inbox and a separate named volume read-write for staged
  immutable artifacts.
- Require one explicit ISO `WECHAT_MP_DRAFT_MIN_WEEK_START` Monday when production auto-enqueue is
  enabled. Discovery and explicit enqueue must reject older aggregates with a typed, non-error
  eligibility reason before creating a job or calling WeChat.
- Start only the `worker` command; automatic reconciliation runs inside that bounded loop when the
  explicit auto-enqueue switch is enabled.
- Do not alter ordinary API, scheduler, content worker, WeCom dispatcher, or weekly DAG construction.

### R3. Migration and release compatibility

- Review `0041` and `0042` as additive forward migrations, document previous-application
  compatibility truthfully, and make the release compatibility gate pass.
- Apply Alembic to unique head `20260901_0042` before starting the new worker.
- Preserve the populated-downgrade refusal for durable draft audit rows; rollback must prefer
  stopping the worker and rolling back application code rather than deleting draft history.

### R4. Controlled activation

- Deploy and migrate with the new worker still disabled.
- Verify database head, Compose contract, volume ownership, credential presence without printing
  values, WeChat API IP allowlist connectivity prerequisites, and zero running draft jobs before
  activation.
- Enable only unpublished draft creation. Do not call a provider as a deployment smoke test and do
  not manually enqueue a business aggregate merely to prove connectivity.
- Set the first production minimum week to the first Monday strictly after activation, so rollout
  never consumes the pre-existing inbox. Filesystem creation/modified times are not eligibility
  evidence.
- After activation, inspect safe job counts/status and logs; do not expose raw media identifiers.

### R5. Source and deployment integrity

- Isolate these changes from unrelated dirty news-ranking/report work.
- Run focused unit/contract/PostgreSQL migration tests, strict type checks, Compose/release contract
  checks, secret scan, and `git diff --check` on the committed candidate.
- Fast-forward push only to the authoritative Codeup `main`; do not force-push or push GitHub.
- Build from the exact fetched clean commit and deploy through a new task-local, checksum-bound
  offline image/source/operator set independently reviewed against the current live baseline.
- Invoke the protected production operator at most once for the final candidate. Pre-mutation
  failures may be corrected only by producing a new operator/candidate identity and repeating the
  full review; no improvised server mutation or second activation attempt is allowed.

## Acceptance Criteria

- [ ] Production configuration rejects accidental enablement unless every explicit draft-only and
      production activation gate is true.
- [ ] Compose defines one bounded, restartable, portless draft worker with the weekly inbox mounted
      read-only and an independent persistent artifact volume.
- [ ] Release migration compatibility validation passes for head `20260901_0042`.
- [ ] Focused worker, adapter, settings, migration, Compose, release, type, and secret checks pass on
      a clean committed candidate.
- [ ] Codeup `main` contains the exact reviewed commits through a fast-forward push.
- [ ] A clean Codeup checkout produces one immutable offline image/source/operator set whose
      hashes, entrypoints, Alembic head, Compose topology, and final commit are cross-checked before
      transfer.
- [ ] Production reaches Alembic `20260901_0042` with existing services healthy and no unrelated
      business/provider/delivery action caused by the release.
- [ ] The draft worker is activated only after preflight; it remains draft-only and has no publish,
      mass-send, or homepage-pin capability.
- [ ] Historical aggregates below the explicit minimum Monday are reported as skipped, create no
      job/artifact copy, and cause zero provider calls; the next eligible weekly aggregate can
      enqueue exactly once.
- [ ] Safe post-activation evidence records service health and job-state counts without secrets,
      article content, private paths, or raw provider media IDs.

## Out of Scope

- Automatic publication, mass send, homepage pinning, browser automation, or manual-login CLI.
- Reworking news selection, content generation, weekly article structure, or existing delivery
  schedules.
- Pushing unrelated dirty workspace changes or deploying from the current dirty checkout.
- Using a real WeChat write as a synthetic smoke test.
- Claiming that the one-time offline transport establishes reusable standard release readiness;
  registry-backed digest deployment remains a separate deferred task.

## Risks and deferred items

- The production database is many migrations behind the candidate. Compatibility is reviewed but
  conservatively declared as not eligible for automatic previous-runtime rollback after migration;
  a post-migration core failure leaves application writers stopped for incident handling rather
  than downgrading or restoring the database automatically.
- Starting the worker may create real drafts only when an eligible future weekly aggregate appears.
  Deployment verification itself has no eligible aggregate and makes zero WeChat write calls.
- Standard registry/digest deployment remains deferred until the required image repository and
  credentials are provisioned.
