# Readable-source production release — 2026-09-14

## Authorization and scope

The user explicitly approved deploying the already reviewed readable-source fix.
Application commit: `47820643219700d8ca7e616bd0205d6baad925d5`, pushed to the
existing Codeup release branch. The six application-file diff is the complete
runtime change. No generation, media upload, draft creation/update, publication,
provider configuration, frontend, schema or data migration belongs to this release.

## Exact offline image identities

- Previous canonical release: `a020588a68135093cfbae646ae8e232f5ccd4b59`.
- Previous running image: `sha256:a471122e65c0fbda9665befadc27faf9bdceb67f879c4e2098c1a46eb18c654c`.
- Candidate: `offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:4a8f3a945cb81267d76796b3d43389ac3b6b98b4959f814dd05bc0a142e113a0`.
- Candidate config: `sha256:f86ed162417065f0b9b0a6406af6f289c68cdf6e23dcebc20ed0af52e080032b`.
- Canonical archive SHA256: `1a21b65c67207d67fc6d9214b77ca42f8963e7285f97c805ccdda317263e68e0`.
- Candidate JSON SHA256: `a9c86ef3adad0d211682e1703560d601e65d6fa9d8cc96c07cd317e29b95171e`.

Build happened locally, never on production. The exact production base image was
loaded locally; only six committed application files were overlaid. Existing live
Zhipu integration bytes differ from the Git baseline and intentionally remain
unchanged (`b9aa021414acc1dcb25068bac707c97da3b52cbd5fc5cb3195ed1a3174514cd9`).
The existing OCI canonicalizer and full graph validator passed; canonical local
reload resolved the candidate tag and RepoDigest to the candidate manifest ID.
Network-disabled probes passed readable-source rendering, legacy rendering,
permanent banner loading and preserved live Zhipu bytes.

## Operational boundaries

Production baseline: 12 healthy applications, two healthy dependencies, unchanged
Alembic head `20260914_0046`, 39 GiB free, active backup timer. Standard release
manifest/current-state metadata remain absent; this is an explicitly scoped
offline activation, not proof of a bootstrapped standard release pipeline.

Snapshot the primary environment, digest environment and both release markers.
The old legacy `RELEASE_COMMIT` contains `27ed2a75606d629003f83aef65cac1dce0e7186b`;
the canonical `.release-commit` correctly contains the previous release. Update
both markers to the candidate only on activation; rollback restores each exact
old value. Preserve `.env`, Compose, volumes, database and all unrelated image files.

## Historical queue cohort

A generic zero-queued check found seven August copy-preview jobs. They are not
current work: the actual copy claim predicate requires the current business date,
and the worker supplies current time. Neither `preview` nor a pipeline-version
difference is the non-claimability reason. Running container hashes of the claim
repository, copy service and worker entrypoint match the inspected sources.

The only allowed retained cohort is the exact seven queued, attempt-zero, unleased
jobs for August 4, 5, 7, 8, 9, 10 and 11. Bind complete joined job/run JSON ordered
by job ID with canonical UTF-8 JSON (sorted keys, compact separators):
`19bb31ea5747b84aade2ff0837238f1634da84b5d052ddb813c48603654c82ca`.
Check the identity before/after queue counts and after restart; do not blanket
ignore preview jobs or old dates. No jobs may be deleted, reset or replayed.

## Status

Deployment completed successfully on 2026-09-14 (confirmed at 13:11 Asia/Shanghai).
The reviewed operator exited zero after `start_candidate` and `completed`.
Its protected receipt is
`/opt/edu-ai-release-backups/source-presentation-4782064/result.json`;
the exact previous protected configuration and markers remain in that directory
for rollback. Operator SHA256:
`2956e2f4869265cad874771e2210659369087c12d60835cb0b89998c64d79c8b`.
The operator's 31 focused tests, Ruff and mypy passed before execution.

A fresh `edu-ai-production-check.sh` exited zero after the switch and reported:

- Release marker `47820643219700d8ca7e616bd0205d6baad925d5` and candidate digest above.
- Twelve healthy application services and two healthy dependencies.
- Schema alignment and API health OK; runtime health OK.
- Delivery queue counts: queued, live-running, stale-running and ambiguous all zero.
- Standard provenance still incomplete (missing release manifest/current state).

A separate read-only probe inside the running draft worker passed the six source
file hashes, readable-source deduplication, unchanged legacy rendering, both
permanent banners and the preserved live Zhipu module hash. Both release markers
match the application commit. A copy of the reviewed operator is retained as
`operator.py` alongside the private deployment receipt.

The deployment receipt confirms no migrations, model calls or social calls, and
all seven sealed historical copy jobs retained unchanged. Existing draft content,
provider configuration and marketing banner assets were not changed by this release.
Local canonical image and reviewed source/operator archive are retained under
`output/readable-source-release-20260914/` in the main workspace; no environment
file or credentials are included. The broader production-recovery task remains active.
