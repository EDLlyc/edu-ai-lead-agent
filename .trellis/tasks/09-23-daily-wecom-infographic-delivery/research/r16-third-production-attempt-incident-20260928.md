# R16 third production attempt: mount-order identity false positive

## Outcome and evidence

The sealed `27dcf93a220f3cdb0942a7736135fd2ff8c51c3e` attempt passed its
read-only preflight after the 09:00 Official Account article run reached
`ready`. It stopped the original 12 R15 application containers, captured the
stopped baseline, and wrote a backup receipt. The MinIO logical backup bound
5,784 current objects in two independently downloaded copies. Clone rehearsal
began, but the operator stopped before migration with
`pre_migration_service_identity` and wrote a forward-recovery-required marker.
There was no migration intent; the production Alembic head remained
`20260916_0048` and the original release markers/image remained R15.

Read-only comparison against the saved stopped baseline found that all 12
container IDs, image IDs/references, commands, environment fingerprints,
statuses and restart counts matched. Eleven mount-list hashes also matched.
For `acquisition-api`, the live Docker inspect mount list contained the same
two complete records in the opposite order; hashing that reversed list
exactly matched the saved baseline. No mount field or count changed. The
operator's order-sensitive list hash caused the false positive. After this
discriminating check and the unchanged `0048` schema check, an operator
started the exact saved original container IDs under the deployment/backup
locks. All 12 were running, API health was `ok`, and the isolated clone
container was stopped without deleting the attempt/backup evidence. This
attempt is single-use and must never be replayed.

## Bug analysis

1. **Root cause category:** E (implicit assumption) plus D (test coverage
   gap). Docker inspect's mount list was treated as an ordered business
   identity even though mount order has no application semantics. The fake
   host gave all application containers an empty mount list, so its recovery
   tests could not detect reordering.
2. **Why earlier fixes did not catch it:** Earlier attempts addressed business
   row churn and MinIO control-tree churn, both before this recovery check.
   The new logical backup allowed execution to advance to a previously
   unexercised two-mount production container state. This is not evidence of
   changed mounted data.
3. **Prevention:** One canonical mount-multiset hash now owns all three
   capture/recovery/candidate comparisons. Regression tests use two mount
   records and require order-only permutation to pass while changed source
   fails. The backend quality contract records the same rule.
4. **Systematic expansion:** Other Docker inspect arrays should be reviewed
   for order dependence before they become release identities. The operator
   must continue to bind all fields, duplicates and counts; sorting must not
   become a lossy projection.
5. **Knowledge capture:** This incident and the quality contract are committed
   with the code/tests. This repository has no
   `src/templates/markdown/spec/` tree to sync.

The next candidate must be a fresh commit, full image, authenticated bundle,
read-only preflight and *new* attempt directory. No result in this record is
release or enablement acceptance.
