# Activated: M/W/F single unpublished drafts

## Outcome at 2026-09-14 14:17 Asia/Shanghai

The checked one-shot operator completed successfully. A fresh independent runtime
check reports 12 application services, two dependencies, API and schema healthy;
all processes run the candidate digest, with no new single-edition queue activity.
Scheduler, producer and draft consumer each report single mode enabled and zero
restarts. Legacy weekly scheduler/worker flags and draft auto-enqueue are false.

- First permitted date: **2026-09-16 (Wednesday)**.
- Repeats: Monday, Wednesday, Friday; prepare 09:00, begin one draft upload 10:00,
  bounded same-day catch-up through 16:00, all Asia/Shanghai.
- Schema: `20260914_0047`.
- New editions: **0**. Imported history owner rows: **14**, including one ready
  `import-v1` barrier. This proves activation/history readiness, **not** an actual
  future draft acknowledgement. No September 14 backfill or historical replay.
- Existing sealed six legacy delivery items and 49 private manual JSON records
  remain unchanged. New ownership can now block repeated article/event delivery.
- Author, source presentation, both permanent banner bytes, existing image model
  and live Zhipu integration bytes remain unchanged. No model or social API calls
  were made by the operator or validation.

## Release identity and evidence

Application commit: `d2e709c0b6a5e47d1b91d2ec623de734aa3c0eb2`, pushed to the existing
Codeup origin release branch. No GitHub-backup push is claimed.

Immutable image reference:
`offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:baffc27e9dc4ccbd9fed5ab248e4e00784f80ecfb25f966fe8c63ee286601d8d`.
OCI config digest:
`sha256:753fb9db855beb742900756612c17aad115333a1cca6b3f9c01e95394caa0119`.
Built from the exact deployed `4782064` base with 17 committed app files and the
new migration only; validated OCI graph, all untouched source bytes, banners and
the preserved live Zhipu SHA before transfer and again in server preflight.

Artifact SHA-256:

- Image archive: `23493bf1382b2965e5a8118412ba19b9d02f07052fc937fd7c04fdbae90262a1`.
- Runtime/operator archive: `093891a2abc0e582a649dd4889ef66e7849c2c13ac87ef6e4b177d34965d4f23`.
- Candidate manifest: `1884622034997883ee3baa9233ce4831a487f6be14b04834a78ee71491b20559`.
- Reviewed operator: `b4199a4fc266f1795dc42c9e96bf781f216a444d9a068643c991b3ceeae08c30`.

Local immutable packages are retained under
`output/mwf-single-release-d2e709c0b6a5/` in the main workspace. Server staging is
`/tmp/edu-ai-mwf-upload.PZOJ0P/`; the durable protected backup and activation
receipt are under `/opt/edu-ai-release-backups/mwf-single-d2e709c0b6a5/`.
The operator verified all application writers stopped, completed DB/MinIO/shared
output/private journal/brand/config backups, then migrated and activated. No
dependency container recreation, retention deletion, database restore or downgrade.

## Remaining boundaries

Standard `release-manifest`/`current-release-state` metadata is still absent and
reported separately as `standard_release_provenance=incomplete`; runtime health
is healthy, but this offline rollout is not a bootstrapped standard pipeline.
Full-backend mypy retains two unrelated baseline errors documented in
`verification.md`; the changed product scope passed strict checking.

The next real scheduled edition still needs its own persisted draft ACK before
any delivery success claim. There is no subscriber publication/mass-send feature.
This schedule-replacement slice is complete; retain the broader recovery task as
in-progress rather than archiving unrelated parallel work.
