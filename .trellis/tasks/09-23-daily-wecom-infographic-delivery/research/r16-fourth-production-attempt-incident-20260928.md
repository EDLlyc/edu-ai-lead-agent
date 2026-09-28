# R16 fourth production attempt: clone timezone and recovery command

## Outcome and discriminating evidence

The fresh `e030f061ffa6f954640b321bf160e6f7973dec98` attempt passed its
read-only preflight, captured a stopped R15 baseline and completed a new
backup. It began isolated clone rehearsal but did not write a clone receipt or
`migration-intent.json`. The release command ultimately emitted
`start_original`; its recovery-intent marker was present, but the automated
restart command failed and a forward-recovery-required marker remained. The
original 12 application containers were still stopped. After checking the
saved IDs, image/config fingerprints, unchanged R15 markers and production
schema `20260916_0048`, an operator started those exact original IDs directly.
All 12 ran and the API health endpoint returned `ok`.

The isolated clone still had schema `0048` and the same row counts as the
production database across all 110 business tables. The row digests differed
in almost every populated table. `SHOW TimeZone` returned `Asia/Shanghai` in
production and `Etc/UTC` in the clone. Running the clone fingerprint query
with `PGTZ=Asia/Shanghai` produced **exactly** the stopped baseline's full
business-identity SHA-256. This establishes a session-rendering mismatch,
not a data loss or row-count mismatch. The fingerprint uses
`to_jsonb(t)::text`, whose `timestamptz` rendering is timezone dependent.

The primary clone exception was masked by a second failure in the `finally`
recovery path. The latter used `docker compose start` with 12 service names;
Docker Compose also reran the one-shot `minio-init` container and returned an
error. The redacted command runner did not retain stderr, so the exact Docker
error is unknown. Direct `docker start` of the saved container IDs succeeded.
Do not attribute a more specific Compose failure without further evidence.

## Bug analysis

1. **Category:** E (implicit assumption) and D (test coverage gap). Clone
   sessions were assumed to render timestamps like production; fake-host
   tests had no timezone variation. Recovery tests modeled Compose start as
   if it were exact-ID start and did not model one-shot dependencies.
2. **Why the prior fix did not suffice:** Normalizing the Docker mount list
   allowed the operator past the earlier identity gate, exposing a different
   contract error in the isolated clone. The recovery path then hid that
   original error.
3. **Prevention:** Verify the production PostgreSQL session timezone before
   clone creation and give the clone client the same fixed `PGTZ`. Test both
   the matched case and a mismatched production zone. Recover only by the
   12 previously verified container IDs; assert no Compose start call.
4. **Systematic expansion:** Any fingerprint that serializes
   timezone-sensitive values must fix its session context on both sides.
   Recovery code should preserve a safe primary failure code even if its
   own action fails; that observability improvement remains a separate
   follow-up, not a reason to weaken fail-closed behavior.
5. **Knowledge capture:** The backend quality contract and fake-host tests
   record the rule. This repository has no
   `src/templates/markdown/spec/` tree to sync.

This fourth attempt is single-use. Its backup and failure evidence are
retained. A new commit, full image, authenticated bundle, preflight and attempt
are required before another production mutation.
