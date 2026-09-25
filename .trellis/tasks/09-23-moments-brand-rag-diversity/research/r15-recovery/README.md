# R15 forward recovery: no startup copy replay

This is a one-attempt forward recovery from the already activated R14 image. It
does not restore an older image, activate PDF/RAG experiments, replay content,
or send social/WeChat messages.

The release overlay contains only the committed
`backend/app/infrastructure/db/copy_generation.py` blob. The builder verifies
the complete R14 OCI archive and source revision, committed R15 source, exact
one-file app diff, immutable migrations, OCI layer graph, hashes and loaded
application tree. `forward_activate.py` binds the current R14 image, all twelve
running services, protected host files, PostgreSQL state, active brand pointers,
copy/provider settings, business counters, idle queues, backup timer and next
business window. It takes a fresh PostgreSQL dump and verifies its TOC before
stopping the services. Once activation intent is written, failure stops all
application writers for separately reviewed forward recovery; no old-image
rollback is attempted.

The exact 2026-09-25 duplicate cohort was handled first, under a separately
verified full database backup. `suppress_duplicate_batch.sql` requires nine
version-bound new runs, their nine older counterparts and no new packages,
images, leases or queued-run attempts. Eight unstarted jobs were cancelled and
their runs terminalized; the one accepted duplicate's draft was preserved while
its run was withheld from image reconciliation. No rows were deleted. The SQL
is deliberately fail-closed after success: **do not rerun it** to make a
partially changed cohort appear valid.

Build from the clean, reviewed release worktree after committing and pushing
the branch, then require the remote branch tip to equal the requested revision:

```text
python3 forward_release.py build --repo WORKTREE --revision FULL_COMMIT \
  --previous PRIVATE_R14_CANDIDATE_JSON --output NEW_PRIVATE_OUTPUT_DIR
python3 forward_release.py smoke --manifest NEW_PRIVATE_OUTPUT_DIR/candidate.json \
  --manifest-sha256 EXACT_SHA256
```

Transfer only the validated private output bundle to a root-owned host staging
directory. Run `capture` to write a private hash-bound baseline, then `apply`
with `--apply` and that baseline SHA. The operator refuses an existing attempt
directory or source/business drift. Verify the new image on all twelve services,
healthy API, unchanged database/brand/copy identity, no new business work and
the next scheduled window. Keep all private receipts and backups on the host.
