# 视觉多样性生产启用与单条验收 — Implementation Plan

## Phase 0 — Read-only production gate

- [x] Confirm deployed commit/image, Alembic 0021, eight long-lived service health/restart counts,
  PostgreSQL/MinIO health, flags false, and provider modes without printing secrets.
- [x] Snapshot image/plan/similarity/package/WeCom counts and require zero running content/image/
  delivery work before quiesce.
- [x] Create a timestamped mode-600 `.env` backup and fresh protected PostgreSQL dump with SHA-256.

## Phase 1 — Quiesce and isolated acceptance environment

- [x] Stop WeCom dispatcher, then content scheduler and content worker; require API/upstream and
  PostgreSQL/MinIO remain healthy and no running job remains.
- [x] Create one generated temporary database and restore the verified dump.
- [x] Create one generated private MinIO acceptance bucket; prove it differs from production.
- [x] In the temporary database, deterministically select the newest accepted copy whose existing
  successful package has no WeCom job, then remove only that cloned v1 package/image lineage.
- [x] Prove the clone now has exactly one accepted copy without a package and all other accepted
  copies remain covered.

## Phase 2 — One bounded live image

- [x] Start one isolated content worker with temporary DB/bucket, WeCom/schedulers disabled, v2/OCR
  enabled, quality audit disabled, and max artifact attempts 2.
- [x] Allow reconciliation to create exactly one controlled package and monitor it to a terminal
  state; stop the one-off worker immediately at terminal.
- [x] Assert one package, one artifact, two distinct plan reservations, one or two similarity
  attempts, no more than two image attempts, no copy-generation attempts, and no WeCom rows.
  Checked with one image attempt and zero similarity attempts; the missing similarity decision was
  a terminal acceptance failure.
- [x] Assert 1024×1024/media/storage gates and exact ordered OCR/title-card metadata without printing
  private prompt/hash/path/provider response data. The media gate passed at 1024×1024, then OCR
  failed with `provider_request_rejected` before storage or title-card evidence existed.
- [ ] Download the isolated final image to a protected temporary path and visually inspect brand
  identity, topic fit, title hierarchy, occlusion, pseudo-text, extra text, watermark, and QR rules.
  No final object existed after the OCR failure, so this gate could not be performed or waived.

## Phase 3 — Production activation or failure close

- [x] On acceptance failure, keep both flags false, restore content services and dispatcher, verify
  health/counters, record the typed failure, and stop without another news item.
- [ ] On acceptance pass, atomically set `IMAGE_DIVERSITY_ENABLED=true` and
  `IMAGE_OCR_ENABLED=true`; run Compose render and real Settings equality probes.
- [ ] Force-recreate acquisition API and content worker on the existing target image, restore content
  scheduler, and require health/running/restart-zero gates.
- [x] Require production visual/package/WeCom counters unchanged by acceptance, then restart WeCom
  dispatcher without enqueue/retry/resend calls.
- [x] Run a 30-second stability sample, bounded secret-safe log scan, backup/config checksum checks,
  and final version/flag/service/database evidence.

## Phase 4 — Cleanup and record

- [x] Drop only the exact generated temporary database and remove only the exact generated acceptance
  bucket after their checksum/count evidence is recorded.
- [x] Remove the protected transient dump and acceptance state after evidence capture while retaining
  the `.env` rollback copy through the final gate. No transient image existed to remove.
- [x] Update `result.md` with pass/fail, bounded call counts, OCR/similarity decision, production flag
  state, zero-delivery proof, and any deferred provider issue.
- [x] Run task artifact diff/secret checks and independent Trellis review. Do not modify unrelated
  `reports/**` or skill edits. Local whitespace/diff and task secret scans passed; the independent
  review confirmed the fail-closed result and removed two JSONL template sentinel rows.
- [ ] Archive the task and record the session after the task-record commit.

## Rollback Points

- Before `.env` edit: restart stopped production content/WeCom services; no production data changed.
- After `.env` edit but before service recreation: atomically restore the timestamped `.env` copy.
- After service recreation: restore `.env`, recreate only acquisition API/content worker, resume
  scheduler/dispatcher in order, and retain 0021.
- Any unknown provider/delivery outcome is a failure; never retry another item or resend.
