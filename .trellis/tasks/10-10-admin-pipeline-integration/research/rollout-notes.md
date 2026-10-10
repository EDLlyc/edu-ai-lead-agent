# Four-service release helper review

Ownership: rollout implementer authored `rollout/common.py`, `preflight.py`, `cutover.py`,
`postcheck.py` and `test_rollout.py`. No remote command or production mutation was executed by
this agent. Root executes the reviewed operations, retains receipts and owns frontend swap.

## Staging contract

Stage these scripts together with safe research snapshots `live-research.json` and
`legacy-all-hashes.json`. The root-built candidate supplies:

```json
{"image":"sha256:<64 hex>","source_commit":"<exact gated commit>","legacy_image":"sha256:83a41e414fee1636c8d4897ae175ee5549afd9a7d4b37df0897b838c9b714851","manifest":"manifest.json","frontend":{"relative/file":"sha256"}}
```

`manifest.json` is the build-context generator's exact full-file manifest: `legacy_files`,
`overlay_sha256` (12 entries), `expected_file_sha256`, `source_commit`, `legacy_image`.
The legacy snapshot includes 359 app, asset, migration and metadata files; the candidate has
364, including five newly introduced files. Source hashing excludes only Python bytecode/cache.
Raw Docker inspect, rendered Compose, container environments and raw logs stay in memory.
Only hashes, counts, service names, times and safe error codes are written to receipts.

## Root execution sequence

1. `sudo -n python3 STAGE/preflight.py`. Read-only admission checks all 16 container identities,
   exact original configuration, all four legacy source trees, single-mode flags/account binding,
   no active/leased/queued target work, volume mounts/content/size and sufficient backup capacity.
   Writes root-0600 `preflight-state.json`. Refresh within five minutes of cutover.
2. After final source gate, independent review and candidate offline smoke, root runs
   `sudo -n python3 STAGE/cutover.py`. It rejects the three push windows and their preceding ten
   minutes; checks frozen inventories again, gracefully stops exactly four services without a
   SIGKILL deadline (`compose stop --timeout -1`), rechecks state, and backs up configuration,
   database and two volumes. It verifies `pg_restore --list` including target tables and every
   regular archive member's bytes, owner/group and mode without extraction. It never migrates,
   seeds, enqueues, calls a provider or swaps frontend assets.
3. The production patch preserves `APP_IMAGE`, adds only `ADMIN_PIPELINE_IMAGE`, assigns that pin
   to four services and maps the existing `MODEL_SECRET_KEY` to the three model consumers. Full
   before/after rendered configuration equality permits only those changes. Actual container
   environment/commands/entrypoints/mounts/restart/resource/security settings are separately
   compared by aggregate digest, excluding only the newly granted model key. The draft consumer
   never receives a model/admin secret. All other container IDs/images/restart counts remain.
4. Root runs `sudo -n python3 STAGE/postcheck.py --observation first`, then repeats with
   `--observation final` after more than 60 seconds. Each checks exact full candidate files,
   non-overlay preservation, immutable work/journal state, current-host/current-process-start
   heartbeats on all six consumers, latest versions and clean load errors/log counters. The
   second requires the same six instances and strictly advancing heartbeat times. Empty stored
   versions prove the DB read and environment fallback; no production encrypted-key rotation
   or provider call is claimed.
5. Only `POSTCHECK_PASS_FRONTEND_MAY_FINALIZE` permits root's separate atomic frontend exchange
   and preview refresh. Root keeps previous frontend assets for matching recovery.

## Admission / historical distinctions

The 16 pending weekly nodes under terminal runs and two legacy ready draft jobs remain immutable
history in active single mode. Future queued work is rejected conservatively too. Expired single
unknown and historical article unknown rows are kept; any unexpired single unknown, or single /
article unknown updated since the exact research instant `2026-10-10T06:05:57Z`, blocks admission.
Active allocations/reservations for weekly execution also block; do not waive this if it exposes
an unresolved historical lease without review.

Single consumer polls refresh only the history-barrier `updated_at` during idle. State hashing
omits exactly that field for `key_kind=history`; its other fields and every other business row
remain exact. Heartbeat rows are observed separately. All draft/prepared artifact files are
compared by content and metadata; no business journal is rewritten by the helpers. Any existing
`*-layout.json` pin blocks this first legacy release preflight and legacy draft rollback.

## Recovery

Automatic cutover failure invokes the same recovery available to root after a failed postcheck:

```text
sudo -n python3 STAGE/cutover.py --recover /var/backups/edu-ai/admin-pipeline-<stamp>
```

Recovery drains/stops the four targets, then reads durable draft state and journal manifests. Any
new/changed journal, pin or draft SQL state, or any failed read, keeps the draft consumer stopped
and emits `ROLLBACK_FORWARD_FIX_REQUIRED`. Otherwise it may restart the original draft consumer.
The three model consumers return to the exact legacy image/environment. No database restore,
downgrade, lease reset or journal rewrite occurs. A mismatching `.env` aborts recovery to avoid
silently replacing concurrent operator settings.

The original global `APP_IMAGE` already points to admin image `da052082`, while these four live
containers started on `83a41e41`. Therefore restoring original Compose verbatim and recreating
would deploy the wrong image. Recovery preserves the dedicated four-service override pinned to
`83a41e41`, removes only the three newly added key mappings, and verifies all rendered service
configuration against original hashes with target image excluded. Root must retain/restore the
matching frontend; this script never swaps it.

## Local verification

- `python -m unittest discover -s .trellis/tasks/10-10-admin-pipeline-integration/rollout -p test_rollout.py -v`: **13 passed**.
- Scoped Ruff lint and Ruff formatting: **passed** for all five owned Python files.
- Tests cover allowlisted patching, rejected unrelated render/secret changes, APP_IMAGE
  preservation, tar content/metadata/path/link checks, missing restore-listing rejection,
  unchanged vs changed/pre-existing-pin draft rollback, DB/journal read-failure fail-closed
  behavior, graceful stop without forced kill, fresh current-host/start verified heartbeats,
  active/unknown admission rejection and secret-safe command failures.
- Independent checker reviewed the rollout scripts and independently ran the first 12 tests;
  the 13th adds explicit recovery read-error regression without changing recovery policy.

Production preflight, backup, cutover and two postcheck receipts remain root-owned acceptance;
these local tests do not claim those operations have occurred.
