# September 22 forward V4/fallback release

This is a fixed-base offline operation, not a generic release framework. It accepts
only the deployed `abfb89d9371d56b1fc651e9ea0a11f50bed37724` image
`sha256:c98c7004a19274a7897ac267784cc376f9ad41e28570de28edfd57ecee5a9bd6`
and existing database head `20260916_0048`. It never calls migrations, seeds,
model providers, WeChat, or a database write. No standard release manifest is
invented: the existing incomplete provenance remains explicit in its receipt.

The main session owns the real build, local Docker smoke, artifact transfer and
production apply. Implementation/review tests use fake subprocesses only.

## Build after the reviewed commit exists

The builder obtains the reviewed application overlay and four host-file bytes
from Git blobs, and preserves the immutable production base underneath. The
running operator must itself equal the version in that commit. Dirty unrelated
workspace files are not exported. The complete base-to-candidate app diff is
hash-bound; dependencies, Dockerfile, Compose, migrations, and unrelated host
changes are rejected.

Exactly one pre-existing base/Git discrepancy is explicitly retained:
`infrastructure/ai/zhipu.py`. The pinned production OCI's last effective copy is
48,896 bytes with SHA-256
`b9aa021414acc1dcb25068bac707c97da3b52cbd5fc5cb3195ed1a3174514cd9`;
both baseline and candidate Git blobs must remain
`3e63bf9d40131c3be51ee4351e8acec8832319f24ba5e5bfc9aab5e256f0345e`.
This preserves an earlier offline release's live OCR integration rather than
deploying an unrelated OCR change. The builder verifies the final bytes by
reading the hash-verified base layers; this path cannot appear in the new layer.
`preserved_base_files` records the exact exception in the manifest. The
validator rejects missing/extra exceptions, altered hashes, changed Git bytes,
or an application-tree projection using the repository OCR bytes. Every other
file remains under the unchanged strict Git-overlay/full-image comparison.

```bash
python3 -B .trellis/tasks/09-22-wechat-draft-scheduler-backfill/research/forward-release/forward_release.py build \
  --repo /root/projects/edu-ai-lead-agent/.trellis/worktrees/wechat-draft-backfill-20260922 \
  --revision FULL_REVIEWED_COMMIT \
  --base-archive /root/projects/edu-ai-lead-agent/output/wechat-header-spacing-abfb89d/backend-image.oci.tar.gz \
  --output /root/projects/edu-ai-lead-agent/output/wechat-forward-FULL_REVIEWED_COMMIT
```

Save the emitted `manifest_sha256`. The output directory must be new. It contains
`candidate.json`, `forward_release.py`, `host-files.tar.gz`, and the complete
`backend-image.oci.tar.gz`. Validate the operator/package hashes before transfer.
The source of truth for application code is the immutable image; the host's
existing backend source is captured and preserved, and the four reviewed health/
release files are installed with their previous owner/group/mode.

Load the candidate archive into the local Docker cache, after confirming its
unique transport tag is absent or already bound to the candidate digest, then
run the same smoke used by production before quiescence:

```bash
python3 -B /ABSOLUTE_ARTIFACT_DIRECTORY/forward_release.py smoke \
  --manifest /ABSOLUTE_ARTIFACT_DIRECTORY/candidate.json \
  --manifest-sha256 EXACT_MANIFEST_SHA256
```

This creates only short-lived, network-disabled, read-only containers. It
verifies all app files, unchanged Alembic/config source, all 12 application
imports, Settings, OpenAPI, `pip check`, and actual Alembic head `0048`.

## Server capture, default read-only plan, then one apply

Use the existing verified SSH alias `edu-ai-production`, a root-owned private
stage outside the protected source directories, and the exact same immutable
artifact bytes. Do not print `.env`, Docker's complete inspection data, baseline
JSON, journal files, object names, provider IDs, or article content.

```bash
python3 -B /ABSOLUTE_STAGE/forward_release.py capture \
  --manifest /ABSOLUTE_STAGE/candidate.json \
  --manifest-sha256 EXACT_MANIFEST_SHA256 \
  --output /ABSOLUTE_STAGE/baseline.json

python3 -B /ABSOLUTE_STAGE/forward_release.py plan \
  --manifest /ABSOLUTE_STAGE/candidate.json \
  --manifest-sha256 EXACT_MANIFEST_SHA256 \
  --baseline /ABSOLUTE_STAGE/baseline.json \
  --baseline-sha256 EXACT_CAPTURED_BASELINE_SHA256

python3 -B /ABSOLUTE_STAGE/forward_release.py apply --apply \
  --manifest /ABSOLUTE_STAGE/candidate.json \
  --manifest-sha256 EXACT_MANIFEST_SHA256 \
  --baseline /ABSOLUTE_STAGE/baseline.json \
  --baseline-sha256 EXACT_CAPTURED_BASELINE_SHA256
```

`capture` writes only its named private receipt. `plan` makes no writes. `apply`
holds both deployment and backup locks, reloads/checks the candidate, compares the
live baseline again, stops exactly 12 applications, then backs up and verifies:

- PostgreSQL custom dump, including a successful `pg_restore --list`;
- all three non-Postgres named volumes: MinIO, weekly output and draft journal;
- brand materials; host runtime/configuration and original file metadata.

MinIO's full volume is backed up. Stable equality concerns the business-object
namespace, excluding naturally changing `.minio.sys` control metadata. Every
other backup is compared byte-for-byte with its frozen source. PostgreSQL and
MinIO containers and volumes are never recreated.

The only intended configuration edits are `APP_IMAGE` in `.release.env` and
`OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION` from
`official-account-visual-pipeline-v3-resilient-advisory` to
`official-account-visual-pipeline-v4-resilient-tolerant-geometry` in `.env`.
`IMAGE_MAX_ATTEMPTS=1`, the single-edition windows, credentials, draft-only mode,
legacy exclusions, all other environment entries and file permissions remain
bound. Release commit markers and four reviewed host files are installed.

The operation is intentionally closed before 2026-09-23 08:40 CST, ahead of the
09:00 prepare / 10:00 delivery window. The baseline expires after two hours.
Active, stale-leased, current unknown, or pending work rejects the release. Seven
fixed historical preview copy jobs and expired lease-free historical single
unknowns are preserved and fingerprinted, not replayed or cleared.

## Acceptance and recovery

Success requires 12 candidate application instances, unchanged dependencies,
zero abnormal restarts, real runtime environment equality, `0048` standard
health, preserved historical prepared/receipt/visual/attempt/ownership/journal
fingerprints, and the read-only `single-status` next window. Receipt is stored at
`/opt/edu-ai-release-backups/forward-<revision-prefix>/activation-receipt.json`.
It proves this operator makes zero model/social calls; it does not fabricate a
future automatic draft or claim a real-provider fallback trial took place.

Any existing attempt directory prevents another apply. Inspect its private
intent, verified backup and receipt before deciding a next action; never remove
it or change the prefix to bypass an unknown outcome.

Before activation intent, a failure may restart the same original containers
only after stopping the complete writer set and verifying unchanged files,
queues, database, source, brand and business-volume fingerprints. Original health
and the complete baseline are checked again after restart. Otherwise it leaves
writers stopped. Once activation intent exists,
the operator **never restarts the old image**, restores the database, downgrades
schema, or automatically retries the release. Any candidate identity/config/data
drift stops all 12 application writers immediately. Only ordinary startup health
and the refreshed history barrier receive bounded readiness waits.

Forward incident recovery must use the already verified candidate (or a new
reviewed compatible candidate) with all OA writers stopped until health and
historical fingerprints are proven. If a deliberate recovery is necessary,
the compatible candidate may run with V3 configured for future admissions after
reviewing the frozen V4/fallback data and repeat/unknown boundaries. Changing
the policy does not change existing identities and does not make the old image
safe. The operator deliberately stops writers and does not automate this
recovery decision. Never restore the old image after V4/fallback data might exist.

## Offline checks

```bash
pytest -q --no-cov .trellis/tasks/09-22-wechat-draft-scheduler-backfill/research/forward-release
ruff check .trellis/tasks/09-22-wechat-draft-scheduler-backfill/research/forward-release
ruff format --check .trellis/tasks/09-22-wechat-draft-scheduler-backfill/research/forward-release
mypy --strict .trellis/tasks/09-22-wechat-draft-scheduler-backfill/research/forward-release/forward_release.py
```
