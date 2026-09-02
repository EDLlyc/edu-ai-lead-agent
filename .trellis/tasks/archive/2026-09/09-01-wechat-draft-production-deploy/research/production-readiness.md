# Production Readiness Findings

## Repository evidence

- `backend/app/core/config.py` currently accepts the draft worker only in development and provides
  no production activation flag or minimum eligible week.
- `backend/app/wechat_official_account_draft_main.py` runs reconciliation in the worker loop only
  when auto-enqueue is enabled; status is read-only and the remaining commands fail closed when the
  worker is disabled.
- `backend/app/infrastructure/wechat_official_account/artifacts.py` discovers deterministic
  aggregate directory names but currently has no activation boundary. It chooses the first bounded
  names before staging, so eligibility filtering must occur without letting old names starve future
  eligible aggregates.
- Weekly aggregate truth contains a manifest-bound Monday `week_start` but no trustworthy finalized
  timestamp. Mutable filesystem timestamps cannot implement the user's no-history requirement.
- `compose.yaml` owns the existing `official_account_weekly_dag_output` volume and has no WeChat
  draft worker or artifact volume.
- `deploy/release/migration-compatibility.json` points to `20260901_0042` but remains unreviewed, so
  `release_tool.py check-migration-compatibility` rejects the candidate.
- The standard release environment inputs are absent locally, while the authoritative Codeup
  remote and `edu-ai-production` SSH alias are configured.

## Product decisions

- Do not backfill historical weekly aggregates.
- Production minimum eligibility is the first Monday strictly after the activation instant.
- Use a newly reviewed, task-local, one-time offline immutable release bound to the final Codeup
  commit. Do not reuse the old operator identity and do not establish a generic local-tag path.
- Keep human publication outside the system; automation ends at three independent drafts.
- Read-only production inspection found no weekly DAG named volume. First activation therefore
  treats it as an empty inbox without creating state during preflight.
- Read-only production inspection found a mixed managed-source metadata baseline: 372
  `root:root` 0600 files, 31 `root:root` 0700 paths, three `ubuntu:ubuntu` 0664 files, and 32
  `ubuntu:ubuntu` 0700 directories. Baseline capture therefore binds type, path, mode, UID, GID,
  and file content instead of assuming every current path is root-owned; the operator recomputes
  the identical fingerprint and rejects metadata drift.

## Technical consequences

- Add an explicit production gate and a required ISO Monday cutoff for production auto-enqueue.
- Apply the cutoff to both automatic discovery and explicit enqueue. Old inputs return a typed skip
  and create neither staged artifacts nor durable jobs.
- Inspect a bounded complete candidate set before selecting eligible batches so old lexicographic
  names cannot permanently starve future ones; fail closed if the scan safety bound is exceeded.
- Add one optional, portless Compose worker sharing the weekly output read-only and owning a
  separate persistent artifact volume. It is not started by the ordinary nine-service graph.
- Review migrations as forward-applicable but declare previous-application compatibility false;
  never use Alembic downgrade or automatic database restore as rollback.
- Deployment runs with the worker disabled through image activation and migration. It atomically
  installs the production gate/cutoff and starts the optional worker only after the core service
  and database checks pass. With the next-Monday cutoff, activation has zero eligible work.

## Prior offline-release lessons retained

The prior release summaries under
`.trellis/tasks/08-17-deploy-delivered-repeat-window/research/` remain mandatory research input:
validate actual OCI/classic archive structure, include root Alembic/project files in source identity,
use exact Compose entrypoints, preserve restrictive destination modes, execute a physical script
with null stdin, inventory opaque volumes through a reviewed read-only helper, exclude only MinIO
implementation metadata, validate stale one-shot identity before removal, arm recovery only after
mutation, and never invoke a failed candidate identity twice.
The new release also binds current `0036`, image/revision, managed-source fingerprint, environment
hashes and exact services; recovery restores marker/file prior absence, and named volumes are
created only after source/Compose activation.
