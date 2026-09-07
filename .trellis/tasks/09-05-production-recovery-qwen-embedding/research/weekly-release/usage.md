# September 7 weekly source-preflight release

This is one incident-specific offline release, not a generic deployer. It accepts only the
`release/weekly-source-preflight-20260907` Codeup ref descending from exact production
`5c560da71bcbb61b765d3fe82c742cf2d5e676e1`. The runtime diff is exactly two weekly production
Python modules and one literal Compose inbox-path correction. The complete old Compose bytes
are independently hash-bound: no other line may change. Four named test files and specific
task/spec audit paths are the only other accepted changes. No protected configuration,
dependency, schedule, schema or provider changes are accepted. The original terminal weekly run
and two original ready article runs are protected.

The existing strict OCI/source validator is imported as a pure library from fixed commit
`f406f6bbdb439b9c699481013172944f9ba58852`, SHA-256
`3204ae61775e9d761abcbc0b1ec3b8644431096e60ac746b5d7e8e51e5cc1334`.
Its September 6 date gates, `.12` scoring activation, baseline and transaction are never called.
All staged Python commands use `-B`; the imported validator is not copied into source/runtime.

## Offline quality

```bash
WEEKLY_RELEASE_TEST_POSTGRES_PORT=25438 conda run --name edu-ai python -B -m pytest .trellis/tasks/09-05-production-recovery-qwen-embedding/research/weekly-release/test_weekly_release.py -q
conda run --name edu-ai ruff check --config backend/pyproject.toml .trellis/tasks/09-05-production-recovery-qwen-embedding/research/weekly-release
conda run --name edu-ai mypy --strict --follow-imports=silent .trellis/tasks/09-05-production-recovery-qwen-embedding/research/weekly-release/weekly_release.py
```

Independent review and product tests are required before the operator uses this artifact.
These tests do not establish production success. The SQL contract uses a loopback-only local
PostgreSQL service with synthetic development credentials and creates/drops only its unique
`edu_ai_release_test_<uuid>` database; never point it at production.

## Operator sequence

1. Commit only the reviewed source/task/spec/tests and push the exact incident ref without force.
   Run the committed `weekly_release.py build --repo ABSOLUTE_REPOSITORY --commit FULL_SHA
   --output ABSENT_ABSOLUTE_DIRECTORY --cutoff 2026-09-07T03:00:00Z` using `python3 -B`.
   The builder fetches Codeup, verifies its own committed bytes and the entire runtime diff,
   builds from committed blobs (never the caller's dirty files), selects the reviewed local
   Docker 29.1.3/containerd 2.2.1 legacy route before construction, canonicalizes and strictly
   verifies the complete OCI graph before load, then probes full image source, 12 entrypoints,
   `pip check`, revision/source/created labels and Alembic 0042. A local lock rejects concurrency.
2. Retain the printed `stage_sha256` independently. Transfer exactly the ten stage members,
   preserving a physical root-owned mode-0700 stage and mode-0600 regular files. Do not transfer
   private configuration or logs. The stage is checksum-bound and cannot contain arbitrary extras.
3. Complete/drain the authorized draft recovery first if it is running. Capture a fresh read-only
   baseline from the physical stage using `python3 -B STAGE/weekly_release.py capture
   --stage STAGE --stage-sha256 PRINTED_SHA --output ABSENT_ABSOLUTE_BASELINE_JSON`.
   Capture rejects active/unexpired leases, runnable queues, changed frozen historical jobs,
   nonterminal original weekly state, absent original successful articles, source/config drift,
   mixed images, unhealthy services and unknown delivery outcomes. Successful draft counts are
   captured as observed; they are never assumed zero. Keep the printed `baseline_sha256`.
4. Within five minutes of capture, run `python3 -B STAGE/weekly_release.py activate
   --stage STAGE --stage-sha256 PRINTED_SHA --baseline BASELINE_JSON
   --baseline-sha256 PRINTED_BASELINE_SHA </dev/null` under the existing authorized root access.
   This is the explicitly mutating command. It reacquires the normal production release lock,
   checks the whole baseline again, validates the inactive candidate, consumes a no-clobber
   commit-bound attempt directory under `/opt/edu-ai-release-backups`, stops all 12 application
   services (never PostgreSQL/MinIO), takes and validates a new standard backup by running
   `bash /opt/edu-ai-lead-agent/scripts/edu-ai-backup.sh` from the checksum-bound source,
   never the older installed `/usr/local/sbin` copy, and repeats the
   immutable gates before swapping all managed source roots including tests. Existing path
   modes are preserved; new paths are root-owned 0600/0700. The protected `.env` is not changed.
5. Both full-SHA commit markers and `.release.env` are atomically updated. All 12 services restart
   with one actual loaded immutable image identity using `--no-build --no-deps`. Readiness waits
   for health and a 15-second restart-free idle interval inside a 150-second bound. Database,
   source, protected configuration and unchanged PostgreSQL/MinIO container identities are
   checked again. Only `success.json` and
   `activation_complete` establish success; a shell exit or loaded image alone does not.

The fixed next writer boundary is September 7 11:00 CST; activation must remain before its
15-minute safety margin (10:45 CST). The driver cannot extend the date/window. If the window,
source, stage or active work drifts, stop and review a new transaction; do not alter checksums or
date constants during production execution. A completed or consumed attempt is never rerun.

## Failure and recovery

The first stop arms recovery. A partial stop, backup, source swap, marker installation or readiness
failure restores the exact previous source roots, primary/release environment bytes and both
markers, then restarts and verifies the complete old 12-service set. There is no migration,
`pg_restore`, database downgrade or queue rewrite. A changed business-state fingerprint prevents
old writers restarting; rollback verification failure attempts to stop all writers and requires
incident reconciliation. Physical file metadata drift fails closed instead of overwriting an
unproven target; do not claim successful rollback unless `rollback.json` exists.

SIGTERM/SIGHUP/SIGINT enter the same bounded recovery path. SIGKILL, host loss and power failure
cannot run a Python handler: retain the physical attempt and source backups, inspect the exact
phase/files/container identities under the release lock, and never blindly rerun the consumed
operator. Before quiescence, a failed attempt leaves production running and may retain an inactive
candidate image for audit. Candidate images/stages/backups are not automatically deleted.
The standard backup script owns its existing seven-day backup-retention policy.

Only safe phase codes, counts, hashes, image/commit and backup identities are printed. Command
failures expose stderr byte count/hash, not raw stderr, argv, environment or provider bodies.
This release creates no model requests, draft sends or public publishing; those remain solely
the existing application workers' responsibility.
