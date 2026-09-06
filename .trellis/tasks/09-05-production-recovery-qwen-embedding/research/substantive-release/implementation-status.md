# Substantive release implementation checkpoint

Status: implementation complete, handed to independent checker; **not a production GO**.

The inherited four task-local files are being completed in place. No archived release file,
product file, production host, model endpoint, or Git commit is modified by this implementer.

Completed inherited pieces: exact 5c base and candidate ref, eight runtime path allowlist,
OCI/source validation, no-build/container ownership guards, protected-environment stable reads,
single-key derivation, same-filesystem replacement helpers.

Completed in this continuation:

- Connected exact single-key activation and restoration to the operator, with pre/post state hashes,
  stable descriptor reads, ownership/mode preservation, same-filesystem atomic replacement, and
  same-inode content/metadata race checks. Unrelated current environment drift fails closed.
- Bound exact image ID/RepoDigest, primary/release environment hashes, seven-job digest, and observed
  attempts/packages/copy runs/jobs/delivered counters. Added independent zero counts for .12 daily
  and slot runs/jobs, including stored snapshot and relational config identities.
- Repeated baseline, source, protected state and time checks under the global normal-deployer lock,
  immediately before quiescence, after fresh backup, before migration/start and after readiness.
- Old runtime restoration first stops writers and requires unchanged head, zero .12 durable work,
  protected state and safe time. Full source/environment/markers and all services restore together;
  no database rollback, deletion, version relabel or queue replay. A failed first source rename
  preserves its surviving original, verified before restart.
- Bound actual container scoring and three-slot schedule projections, actual weekly scheduler
  enable/minimum-week/reconcile settings, and its running domain schedule metadata. After the
  September 5 boundary expired, the one-shot validator was re-pinned to the September 6 17:00 CST
  evening preparation; it intentionally rejects use before the noon window closes or after the
  16:45 margin. Weekly first eligible producer September 7 09:00 CST is later.
  Cutoff is exact, minimum margin 15 minutes, baseline age at most one hour; business date cannot
  roll over inside the transaction. No schedule is altered to obtain a deployment window.
- Fixed independent-review findings: shared `/var/lock/edu-ai-deploy.lock`, fail-closed reserved
  namespace scan, exact root device/inode and physical identity binding, descriptor-relative
  symlink-safe task-workspace cleanup. Uncertain cleanup leaves files intact.
- Exact runtime allowlist remains eight paths. Required audit allowlist is four product test
  files, new `substantive-topic-scope.md`, and the two small index/topic-spec link edits; only
  task-owned additions are otherwise accepted. Archived scripts and dirty main products unchanged.

Validation: 134 provider-free tests pass. The new validator executes the archived adversarial
OCI/source fixtures through explicit fixture rebinding (archive is not changed); additional tests
exercise atomic-file races/failures, exact baseline identities, schedule/cutoff drift, complete
activation failures, actual file/marker rollback, and cleanup/lock guards. Ruff format/lint,
strict mypy for the validator, Bash syntax and `git diff --check` pass.

The independent checker additionally executed the extracted actual capture/operator count SQL on
isolated PostgreSQL at exact Alembic 0042: query parity, EXPLAIN and READ ONLY SELECT passed with
27 fields and four zero new-policy counts; the checker cleaned its fixture database/bucket.

Remaining gates: independent native checker approval and main's exact committed-source
build/transfer/preflight/activation.
No live capture, Docker/image build, provider/SSH/network call, deployment, or commit was performed
by this implementer. Source/image/config convergence still does not satisfy actual news delivery.
