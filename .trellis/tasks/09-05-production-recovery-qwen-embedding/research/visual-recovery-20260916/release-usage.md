# September 16 resilient-visual release operator

Scope: exact production revision `01ff75eed1ed82f5951580af994b6c5c750e53ae`, image
`sha256:febd216660c4fdf3919a8cd2c7da8c233d69d1e53503ff50b27df00c2aa58655`
and schema `20260914_0047`, plus one reviewed immutable source overlay. The overlay contains
the complete reviewed V3 application file set and exactly
`backend/alembic/versions/20260916_0048_resilient_visual_policy.py`.

This release activates only future runs. It must not replay or mutate the recovered September 16
edition, call an image/review model, add/update a WeChat draft, publish, or mass-send.

## Candidate construction

- Commit the reviewed application, migration, release-script and documentation files first.
- The builder reads every runtime byte with `git show REVISION:path`; dirty worktree bytes are not
  accepted as candidate input.
- The reviewed application set and the single 0048 migration must both be exact. Dependency,
  Dockerfile, Compose or additional Alembic changes fail closed.
- A documentation-only `.env.example` difference is allowed but is not copied into the image.
- The original base layers, runtime configuration, labels and history stay byte-bound. The
  candidate adds one app-owned layer containing only reviewed application files and migration
  0048.
- The manifest binds application and migration hashes, exact 0047→0048 schema transition,
  V2→V3 configuration transition, `IMAGE_MAX_ATTEMPTS=1`, production snapshot, OCI graph and
  all operator/helper hashes.

Use a new protected output path and a reviewed full commit:

```sh
python .trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-recovery-20260916/release-snapshot.py \
  --remote --output /tmp/visual-resilient-snapshot-20260916.json

python .trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-recovery-20260916/release-build.py \
  --repo /root/projects/edu-ai-lead-agent/.trellis/worktrees/release-hardening \
  --revision REVIEWED_FULL_COMMIT \
  --base-archive /root/projects/edu-ai-lead-agent/output/no-source-links-01ff75eed1ed/backend-image.oci.tar.gz \
  --production-snapshot /tmp/visual-resilient-snapshot-20260916.json \
  --output-dir /root/projects/edu-ai-lead-agent/output/visual-resilient-REVIEWED_COMMIT
```

Snapshot mode is read-only. It binds protected history hashes, exact target metadata, protected
file metadata, Alembic 0047 and the exact unique partial body-checksum index. Receipts are mode
0600 and must not be committed.

## Checked execution order

Transfer the whole bundle into a new root-owned directory. Verify `artifacts.sha256`, the
out-of-band manifest digest and operator digest before executing Python.

```sh
sudo -n python3 -B /PROTECTED_BUNDLE/release-deploy.py \
  /PROTECTED_BUNDLE/candidate.json --manifest-sha256 REVIEWED_MANIFEST_SHA256

sudo -n python3 -B /PROTECTED_BUNDLE/release-deploy.py \
  /PROTECTED_BUNDLE/candidate.json --manifest-sha256 REVIEWED_MANIFEST_SHA256 --execute
```

The first command validates only. The executing transaction:

1. Verifies the exact live revision/image, schema 0047, expected unique partial index, frozen
   history, idle queues, V2 visual policy and `IMAGE_MAX_ATTEMPTS=1`.
2. Quiesces all application writers while keeping PostgreSQL and MinIO running, then repeats the
   history/config/schema/index fence.
3. Creates a PostgreSQL custom-format dump, validates its TOC with `pg_restore --list`, performs a
   full offline decode to `/dev/null`, fsyncs it and stores its digest beside protected config,
   runtime and history snapshots.
4. Loads and network-isolated-smokes the immutable overlay. The 0048 migration byte is checked
   inside the loaded image, then the stopped-writer history/config/schema/index fence is repeated
   immediately before migration.
5. Runs only `alembic -c alembic.ini upgrade 20260916_0048` through the candidate
   `backend-migrate` service. It does not run seed commands.
6. Verifies exact schema 0048 and absence of the retired body-checksum index.
7. Atomically changes the protected `.env` visual policy from
   `official-account-visual-pipeline-v2-native-observe` to
   `official-account-visual-pipeline-v3-resilient-advisory`. No other `.env` field changes and
   `IMAGE_MAX_ATTEMPTS` remains `1`.
8. Atomically switches immutable image/revision markers, recreates the twelve application
   services and verifies image, schema, protected configuration, dependency identities, health
   and frozen history before writing the success receipt.

## Failure behavior

- Any failure before a migration attempt restores the exact prior image, revision markers and
  protected `.env`, then proves readiness again on schema 0047.
- Once migration has been attempted, the operator never issues a downgrade and never restores
  the old image over schema 0048. It recovers forward using the candidate image with the V2
  visual policy restored. If the first migration did not commit, the exact 0048 migration may be
  retried transactionally.
- If 0048/V2 health cannot be proven, all Official Account writer services are stopped and the
  operator reports `forward_recovery_incomplete` (or the stricter writer-stop failure). Current
  database data is never erased.

The protected backup directory is
`/opt/edu-ai-release-backups/visual-recovery-REVISION_PREFIX/`. Preserve it until an independently
reviewed retention decision.

## Focused verification

```sh
ruff check \
  .trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-recovery-20260916/release-{build,common,deploy,journal,snapshot,test,validate}.py

ruff format --check \
  .trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-recovery-20260916/release-{build,common,deploy,journal,snapshot,test,validate}.py

python -m py_compile \
  .trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-recovery-20260916/release-{build,common,deploy,journal,snapshot,test,validate}.py

pytest -q \
  .trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-recovery-20260916/release-test.py

git diff --check -- \
  .trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-recovery-20260916/release-\*.py \
  .trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-recovery-20260916/release-usage.md
```

The release suite covers manifest strictness, committed-blob construction, exact OCI graph,
migration membership, environment patching, backup validation, execution ordering, pre-migration
rollback, post-attempt forward recovery and absence of model/social/downgrade routes. These tests
do not constitute a deployment receipt.
