# Result: WeChat Official Account Draft Worker Production Deployment

## Outcome

The optional WeChat Official Account draft worker is active on the production server. It remains
draft-only, has no publish or mass-send capability, and will ignore weekly aggregates whose
authenticated `week_start` precedes `2026-09-07`. Activation itself created no job, item, attempt,
artifact, or WeChat write.

## Final identities

- Codeup `main` fix: `61b7c44a142f18346aea1875fc0f1e85f52dcca4`.
- Codeup `main` release-ref support: `4fbab0172d6a1aafff91e53dede4e4250a35aee2`.
- Codeup `main` one-shot operator: `5d73942ab52a725140dabf39773356049c8d0959`.
- Isolated Codeup release ref:
  `release/wechat-draft-client-hotfix-20260902` at
  `267ffddc3c13ac7c3c874e6902b5c09bdeaa0e1e`.
- The isolated release differs from the prior runtime under `backend/app` only at
  `infrastructure/wechat_official_account/client.py`; the unrelated IP-asset service change on
  `main` is not in the production runtime.
- Candidate image ID:
  `sha256:eabffa5565affc5b6da154329d9f94d85fd07d4bc72a8235c30c81b313c88bbf`.
- Client-hotfix operator SHA-256:
  `b12277584b4ab3dbf54d06576e4899ff864dd234d9c8c07c7f50e8a65c7c6164`.

## Migration and backups

- Initial production head: `20260825_0036`.
- Final production head: `20260901_0042`.
- The forward migration was applied once by the original reviewed candidate; neither incident
  continuation nor client hotfix reran a migration or downgrade.
- Migration backup: `20260902T031125Z` (`postgres_bytes=33523275`, `minio_files=2738`,
  `brand_bytes=210227952`).
- Final hotfix backup: `20260902T040320Z` (`postgres_bytes=33588539`, `minio_files=2738`,
  `brand_bytes=210227952`).

## Incident and recovery record

1. The first operator identity failed before migration because the old release environment used a
   mutable tag. Production was restored and the baseline was recaptured with an immutable digest.
2. The migrated candidate reached `0042`, but a fixed five-second API observation saw `starting`.
   The consumed operator was not replayed; the same candidate core was recovered with draft flags
   disabled and later verified healthy.
3. The first no-migration continuation started the optional worker, which then restarted with the
   stable error `wechat_mp_config_disabled`. Its protection path removed the worker, restored all
   four flags to false, retained the healthy core, and proved draft counts `0:0:0`.
4. Root cause was a stale development-only environment check in the settings-bound HTTP client.
   The fix aligns it with the canonical rule: development, or production with explicit draft
   acknowledgement. A real production-settings client-construction regression uses a fake
   transport and makes no network request.
5. A new checksum-bound hotfix operator loaded the isolated candidate, created a fresh backup,
   replaced source/image, restored ordinary services, enabled the worker, and passed its bounded
   30-second stability gate. The consumed operator identity has a server-side attempt marker.

## Production evidence

- WeChat access-token preflight succeeded with a 7200-second lifetime; no token value was logged.
- `postgres`, `minio`, the eight ordinary application services, and
  `wechat-official-account-draft-worker` are all `running` with restart count `0`.
- PostgreSQL, MinIO, and `acquisition-api` health checks are `healthy`.
- All nine application processes use the exact candidate image ID above.
- Enabled flags are the four reviewed draft adapter/worker/auto-enqueue/production switches; the
  fixed minimum Monday is `2026-09-07`.
- Draft database counters after stable activation: jobs `0`, items `0`, attempts `0`.
- Provider writes caused by deployment: `0`.
- Worker failed-log count over the bounded post-activation tail: `0`.
- The final evidence directory identity is
  `wechat-draft-client-hotfix-b12277584b4a-20260902T040316Z`.
- The existing noon content run remained `succeeded`; its one Enterprise WeChat job remained
  durably queued for the pre-existing 12:30 delivery window while the dispatcher returned healthy.

## Verification

- 66 focused client/settings/CLI tests passed on the isolated release commit.
- Strict targeted Ruff format/lint and mypy passed on the two affected Python files.
- 54 release tests, the task-local fake recovery harness, shell syntax, artifact validator,
  Compose/image import probes, task validation, and the production-settings network-disabled
  client probe passed.
- A re-attempted repository-wide gate exposed pre-existing, unrelated state on current `main`:
  three Ruff-format findings, two `local_exact_target_selection.py` Literal type findings, and a
  full pytest run with 1825 passes plus 33 failures involving shared integration state/private
  weekly assets/current unfinished ranking expectations. None arose in the fixed client contract;
  these unrelated files were not modified or deployed by the isolated release.

## Effective behavior

When the next eligible finalized weekly aggregate appears, reconciliation can enqueue it exactly
once and the worker can create exactly three independent unpublished drafts. There is still no
automatic publication, mass send, homepage pinning, or browser automation.
