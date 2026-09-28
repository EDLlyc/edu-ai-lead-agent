# R16 MinIO release-backup boundary: break-loop review (2026-09-27)

## 1. Symptom and evidence

The second R16 production attempt stopped the 12 application services and
then rejected `pre_migration_data_or_file_drift`, before any backup, clone,
migration or release receipt. Automatic pre-migration recovery refused to
claim a verified prior runtime, so the original R15 containers were inspected
and started in place. No candidate image was installed. The attempt did not
persist a per-component mismatch, so its exact mismatched component is not
known. Subsequent read-only observation proved that the `.minio.sys` subtree
of the still-running MinIO server changes while the application services are
stopped; its raw tree hash changed within roughly one minute.

## 2. Root-cause category

The operator conflated a **live service's implementation-owned filesystem**
with stable application business data. It hashed and planned to archive the
whole live MinIO volume even though it did not stop MinIO. This is a lifecycle
and consistency-boundary error, not evidence that the application objects or
database changed. `.minio.sys` churn is a strong explanation of the abort,
but the missing component-level receipt prevents attributing that specific
attempt with certainty.

## 3. Why the previous repair did not resolve it

The first attempt had been fixed by allowing in-flight database work to
finish while application containers stop and then binding one authoritative
quiescent baseline. That addressed the application-writer boundary only.
MinIO is an independent writer and remained active, so a raw-volume hash
could still change between the two captures. Merely ignoring `.minio.sys`
in the comparison would not make a full live raw-volume archive coherent or
restorable.

Independent review of the new path also found an evidence-freshness gap:
after accepting a backup receipt, the operator had only rechecked live
business state before migration intent. A receipt's success flags would not
detect later deletion or corruption of its retained MinIO files during the
clone interval. The release now re-reads the persisted manifest and both
object copies immediately before migration intent. Other older backup
archives still deserve a separate cross-artifact freshness audit; this
specific repair does not claim to solve that wider pre-existing issue.

## 4. Prevention contract

For this release, keep MinIO online but back up the configured application's
current unversioned bucket objects through its API. Bind exact object names,
supported metadata, source inventory, downloaded bytes and independent
readback to a private receipt. Refuse versioned/unsupported buckets and any
inventory or byte drift. Archive only the two inactive non-MinIO artifact
volumes. Perform bucket shape, bounded size, helper-image identity, free-space
and inode checks before stopping application writers, then recheck capacity
against the authoritative stopped-writer inventory before the first object
download. This logical backup is
not a full MinIO cold backup: historical versions and server configuration
need a separate procedure. If the online boundary cannot pass, stop before
another live attempt rather than reverting to a live raw-volume archive.

## 5. Verification and release gate

Test control-tree churn with unchanged user objects, real object drift,
unsafe keys, unsupported metadata/versioning, empty buckets, independent
download mismatch, retained-file deletion/corruption before migration, and
insufficient capacity. Exercise the exact pinned client
against disposable MinIO, then run scoped release tests, lint and type-check.
The first two attempt directories remain immutable for reconciliation. A new
source commit invalidates the earlier full OCI image and sealed bundle; no
third production apply or enablement is authorized by local tests alone.

The scheduled backup evidence from 2026-09-10 recorded 3,700 mirrored files.
It is historical, not a current count. The online path must use bounded bulk
operations, and a fresh read-only capacity/throughput check is needed before
any future downtime claim.
