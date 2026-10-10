# Bug Analysis: recreated legacy services inherited newer shared versions

## 1. Root Cause Category

- **Category E — Implicit Assumption**, with a **D — Test Coverage Gap**.
- The four legacy services had remained alive since September 28. Current Compose and `.env`
  were mutually consistent but no longer represented those live containers' two shared version
  values. Admission checked immutable files, identities, current render and source, but did not
  compare the actual effective environment against what a recreate would load.
- First attempt at 06:24:59 UTC backed up DB and both volumes successfully, then the strict
  runtime hash guard caught drift after recreation. New and rollback containers both inherited
  `CONTENT_SCORING_VERSION` / `CONTENT_SLOT_RANKING_VERSION` values unsupported by old Settings.
  The exact candidate source and offline fixtures were not the cause.

## 2. Why Fixes Failed

1. Comparing before/after rendered Compose correctly bounded the intended patch, but both renders
   shared the same pre-existing drift. This could not prove parity with running containers.
2. Returning to the old image did not fix inherited configuration; automatic rollback also failed
   its exact-runtime guard. Containers restarted until their original values were restored.
3. Root reconstructed the original effective configuration in memory from three independently
   unchanged legacy schedulers. Replacing exactly those two variables produced the saved full
   runtime hash for **all four** targets with **each** of the three references. This discriminated
   real environment drift from null/empty normalization or inherited image metadata.
4. At 06:27:04 UTC, explicit values on just those four service blocks restored the exact original
   runtime: scoring-v1-preview.11-qualified-authoritative-priority / slot-ranking-v1. The global
   `.env`, APP_IMAGE, other services and credentials were unchanged. A later stability check found
   zero restarts, original work hashes, unchanged journals and unchanged unrelated container IDs.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
|---|---|---|---|
| P0 | Admission | Compare actual target environment/command with effective rendered values plus image defaults before stopping anything. Fail on differing key names; never log values. | Done — 17 regression tests and independent review passed |
| P0 | Exact preservation | Keep original runtime hashes, verified nonsecret per-service version overrides, DB/journal hashes and independent untouched-container identities. Never waive the runtime mismatch. | Done |
| P0 | Recovery | Support the exact already-restored BASE pipeline pin and preserve explicit legacy values during forward switch and rollback. | Done — 17 regression tests and independent review passed |
| P1 | Tests | Reproduce pre-existing environment drift and an already-restored baseline before the next release attempt. | Done — 17 regression tests and independent review passed |
| P1 | Documentation | Capture heterogeneous image/config lineage and pre-recreate admission contract in production-mainline guidance. | Done |

## 4. Systematic Expansion

- Unrestarted legacy schedulers and pinned cron images may also differ from today's shared files.
  Never infer their next-start compatibility from a currently healthy process.
- Image rollback and runtime rollback are separate contracts. An older image with newer shared
  settings is not necessarily a valid rollback.
- Preserve actual configuration securely before reconstruction, or prove a reconstruction against
  the previously captured full hash. Do not serialize credentials into task evidence.

## 5. Knowledge Capture

- Updated `.trellis/spec/guides/production-mainline.md` with effective runtime admission and exact
  legacy restoration rules. No `src/templates/markdown/spec/` mirror exists in this application.
- Safe evidence: `runtime-drift-diagnosis.json`, `runtime-restoration.json`, and the original versus
  restored `live-research*.json` snapshots. Private config/journal inventories remain server-only.
- Original backup: `/var/backups/edu-ai/admin-pipeline-20261010T062459Z`. No DB restore, row reset,
  journal rewrite, external publication or model call was used during diagnosis/recovery.
