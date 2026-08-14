# Production deployment result

## Outcome

The backend-only production release completed successfully on 2026-08-13. The active runtime at
`/opt/edu-ai-lead-agent` and both release markers are pinned to `0a0988c`. PostgreSQL, MinIO, the
production `.env`, private brand materials, named volumes, Compose project identity, and all
pre-existing durable queues were preserved. No frontend, firewall, reverse-proxy, credential,
private-material, or pending-source activation change was made.

The maintenance window ran from `09:54:19Z` to `10:47:17Z` (3,178 seconds). Final and 40-second
stability samples found all intended services healthy or in their expected successful one-shot
state, with zero restart-count increases.

## Release and image evidence

- GitHub and runtime target: `0a0988cbea0ea2f3528de5418fc9a7c524e2b248`.
- Filtered archive: 262 files, SHA-256
  `7d6f33bc4a6d0431e8ff1d0af5c3f4bf0b87bc28ee1e7aab36e55164e8f2233a`.
- The active 262-file manifest matches the transferred archive. Both marker files contain the
  short release marker `0a0988c`.
- Two bounded primary Dockerfile builds failed before maintenance because the server timed out
  downloading pip from the external PyPI file host. Production remained unchanged during both
  attempts.
- The approved offline overlay reused exact dependency base
  `sha256:e0565c49a63e85d1708d1c114292ca7b350b51bf3e7934b7b5103596fe854d42`.
  The old release, target, and base all use the identical `backend/pyproject.toml` SHA-256
  `e8686a2e336a5840f1edc87558a836411c881ad8878abf8d918b529f44f57556`;
  `backend/Dockerfile` and `environment.yml` are also unchanged.
- Validated target image:
  `sha256:24b8e13f8a1db8db5cc147ce761fe8a288b069232bee35b1c1c65f5ca03b9630`.
  The image completely replaces the application/Alembic payload, removes stale application copies
  left by `pip install .`, and passes all 155 in-image target hashes, exact file-set/ownership
  checks, non-root execution, dependency/entrypoint imports, `pip check`, version/registry checks,
  and Alembic-head validation without network access.
- All nine Compose application tags resolve to that one target digest. All eight long-lived
  application containers run it with restart count zero; `backend-migrate` exited zero with it.

## Backup and rollback evidence

Fresh protected backup set `20260813T095500Z` was created only after all application writers had
stopped and PostgreSQL/MinIO remained healthy:

- PostgreSQL custom dump: 6,917,688 bytes; SHA-256
  `2271efffed5cc1f92cea9acd11cbde273994dce61107efff1fc5ef8b72ad77f0` verified.
- MinIO mirror: 409 objects; every `SHA256SUMS` entry verified. The manifest SHA-256 is
  `ff61caa85629c3177c5f5b1d1f2f4d27ca354d36e50613b280eb0c6f67255381`.
- Brand-material archive: 210,227,952 bytes; SHA-256
  `5184e5ef669bd85261dde402c90ff0520d17cfd606c34a14185a1cd0aef710e7` verified.
- Server-local rollback directory: `/var/backups/edu-ai/releases/20260813T095500Z-a2660dd`, mode
  `0700`.
- Allowlisted previous-runtime archive: 464,590 bytes / 300 members, SHA-256
  `4d3ec3c2893c8b23bfcd7de7421e07942d43049d07e3bee377f6272294ac1a3e`.
- Nine immutable service-specific rollback tags resolve to their recorded prior full image IDs:
  migration/acquisition/governance use
  `sha256:b81088c85fffd03c20b71984e1981ce904aa296514f8033a0ea314acfd246ed7`;
  API/content use
  `sha256:e0565c49a63e85d1708d1c114292ca7b350b51bf3e7934b7b5103596fe854d42`;
  and WeCom uses
  `sha256:2a5d3700c184546865dd28ad643927e70e025dae340d7c51419cc8deedabde65`.
  The inventory also retains prior markers `a2660dd` / `3383841`, zero pre-stop restart counts,
  protected-input checksums, Compose project/volume identities, and compatible restore commands.

No rollback was required. The fresh database backup is the exact pre-seed restore point; it must
not be restored automatically after writers have reopened.

## Migration, registry, and durable state

- `minio-init` and `backend-migrate` exited zero.
- Alembic remained at `20260807_0019`.
- Source seeding reported one new source. Enabled active sources changed only from 9 to 10 and now
  include Xinhua Education.
- CAST and EdSurge remain pending in code, with zero production source rows and zero acquisition
  jobs. No pending parser was activated and no pending-source live request was made.
- Final safe totals are 30 acquisition runs, 162 evidence candidates, 30 governance runs, 11 daily
  selections, 47 copy runs, 23 material packages, and 13 WeCom jobs.
- All six durable job families had zero running rows at the final sample.
- The seven pre-existing historical copy jobs remain queued with aggregate attempt count zero;
  current-date queued/running copy jobs remain zero.

## Expected current-date automation

Reopening the already-enabled schedulers performed only normal 2026-08-13 reconciliation:

- Acquisition created one scheduled v5 run, completed all 10 source jobs, retained 39 new
  candidates, and recorded zero failed source jobs.
- Governance reached typed terminal state `partially_succeeded`: 32 jobs succeeded, seven required
  review, and zero failed or remained queued/running.
- Content reconciled the already-existing scheduled August 13 selection into one accepted copy,
  one succeeded image, and one `awaiting_manual_use` package. It did not claim any historical job.
- That pre-deployment daily selection immutably uses historical scoring `.4`. The target correctly
  replayed it with compatible code; no replacement selection was manufactured. Running defaults
  are acquisition v5, scoring `.6`, and Ministry priority v3 for future new selections, while
  `.4`/`.5` compatibility checks pass.

The new package passed all direct-delivery quality predicates but was excluded by the target's
business-date-wide formal-delivery guard because August 13 already had delivered formal jobs.
Starting WeCom therefore created zero jobs and zero attempts and made zero provider calls. Final
WeCom state remains exactly 13 jobs: 12 delivered, one failed, no queued/running/partial/unknown,
zero duplicate request-fingerprint groups, and the unchanged documented one-group/two-row
historical content-fingerprint baseline.

## Final operational verification

- API health reports `production` / `Asia/Shanghai`.
- PostgreSQL and MinIO are healthy. API, PostgreSQL, MinIO API, and MinIO Console bindings remain
  loopback-only; workers, schedulers, and dispatcher expose no host ports.
- `.env` retains its pre-deployment checksum and mode `0600`.
- Private brand materials remain 256 files; manifest SHA-256 remains
  `dbf0d94b6bf8abbae88bf769f0f319365ccdd40ba0f028be6aae8dc8ef2f4290`, readable but non-writable
  from the non-root content worker.
- Named volumes remain `edu-ai-lead-agent_postgres_data` and
  `edu-ai-lead-agent_minio_data`.
- UFW and the backup timer are enabled/active. The host retains 62 GB free and 96% free inodes.
- Redacted evidence was refreshed at `/var/lib/edu-ai/deployment-evidence.txt`, mode `0600` and
  root-owned.
- Bounded logs and the evidence artifact passed secret/authenticated-URL scans. Counts for
  traceback, critical errors, `delivery_unknown`, and WeCom provider-send events were all zero.

## Validation performed

Local gates passed before transfer: full-profile Compose render, `git diff --check`, Ruff, strict
mypy, all 680 backend tests, and `make doctor`. Remote gates covered archive/staging/active hashes,
offline image source and dependency provenance, Compose service/image identity, one-shot exits,
health, SQL registry/queue/delivery invariants, protected mounts, bindings/firewall, backup timer,
backup and rollback checksums, bounded logs, evidence generation, and a final stability sample.

## Follow-ups

- Rotate the password shared through chat and move routine administration to SSH keys.
- Diagnose or mirror the production host's PyPI dependency path before a future release that
  changes dependencies; the offline overlay was valid here only because all dependency inputs were
  byte-identical.
- CAST and EdSurge remain separate parser/live-gate follow-ups and must not be activated by seeding
  until those gates pass.
