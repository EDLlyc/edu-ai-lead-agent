# Forward release baseline, 2026-09-22

The user authorized completion and deployment of the permanent automation repair after accepting the corrected unpublished draft.

- Live application revision: `abfb89d9371d56b1fc651e9ea0a11f50bed37724`.
- Live immutable image: `sha256:c98c7004a19274a7897ac267784cc376f9ad41e28570de28edfd57ecee5a9bd6`.
- Twelve application services and PostgreSQL/MinIO were running and healthy; backup timer active.
- Actual schema remains `20260916_0048`; the existing health declaration still expects `20260914_0047`, producing `schema_head_mismatch`.
- Single M/W/F mode is enabled, legacy weekly scheduler/worker and draft auto-enqueue are disabled, and outer image attempts remain `1`.
- The current host follows the previously audited offline OCI release path. Standard `.release-manifest.json` and `/var/lib/edu-ai/releases/current.json` are absent; do not manufacture them.
- The exact live base image is cached locally, with its immutable OCI archive and checked manifest in `output/wechat-header-spacing-abfb89d/`.
- Next natural window under the existing schedule: 2026-09-23, 09:00 preparation and 10:00 draft delivery, Asia/Shanghai.

Historical unknown outcomes must remain quarantined and visible. Their preservation is compatible with healthy future scheduling; only current/active unknown outcomes or lease anomalies block current runtime health.

These observations are a pre-implementation baseline, not a deployment receipt. Final activation requires fresh locked capture, backup, reviewed candidate checks, and post-switch verification.

## Additional read-only topology checks

- Both `.release-commit` and `RELEASE_COMMIT` are regular root-owned mode-0600 files containing the complete previous revision and one trailing newline.
- The four host overlay files exist: migration compatibility (0644), production health checker (0700), local doctor (0755), release deployer (0600), all root-owned. Deployment must preserve each exact mode, not normalize the active files to broader permissions.
- There are three non-PostgreSQL named volumes: MinIO, weekly DAG output, and the durable WeChat draft journal. All three, plus brand files and protected runtime configuration, belong in the backup scope.
- The backup directory is an existing root-owned mode-0700 directory; the deployment lock is root-owned mode-0600.
- Five application containers mount the same brand-materials directory read-only: API, content worker, weekly DAG producer, local article worker, and WeCom dispatcher. Scheduler and draft consumer have no brand bind and must not be required to acquire one.
- Seven old copy jobs remain queued with zero attempts, exactly one each for August 4, 5, 7, 8, 9, 10, and 11. Preserve their canonical stable-state fingerprint; they are outside the current-date copy worker claim predicate. Acquisition, governance, topic, slot, WeCom, and legacy WeChat draft pending counts were all zero.

## Local validation before final candidate

- Existing one-time backfill/badge/redraft regressions: 78 passed, fake providers only.
- Existing V4 geometry and AI chest-badge regressions: 153 passed, including isolated PostgreSQL geometry recovery.
- Independent release/health review: 113 passed after adding empty/multiple/invalid/drifting schema-read rejection before any initializer, migration or seed. Strict typing, lint/format, shell syntax, six-profile Compose rendering and read-only PostgreSQL aggregate checks passed.
- These are component gates, not a claim that the new fallback runtime or final deployment has already passed.
