# Released: templates and the remaining model consumers

Completed 2026-10-10 14:33 Asia/Shanghai. Application source `f062b8221c387ecd44d6e7529832f50331d1508d`;
reviewed rollout helpers `075e44bbb67130043b51e720a9e0415f6f3a8b4e`.

## Delivered behavior

- New eligible automatic single-edition drafts read the bound account's saved template at their
  first upload. Later retries retain that choice. Pre-template legacy upload intents retain the
  original blue body; actual legacy ACK fixtures reconcile without replay, including after expiry.
- Local article, weekly DAG/single generation and governance workers now share the existing model
  key configuration mechanism. All six model consumers report current-host, current-start,
  advancing successful heartbeats. There are zero stored keys, so production currently uses
  environment fallback; actual encrypted-key rotation has not been claimed or attempted.
- The page reports a saved configuration and explains first-upload/retry behavior without claiming
  real-time worker readiness. Four template previews, three viewport widths and save wording pass.

## Production identities and preservation

- The four target services run `sha256:6226855a02fea125c842c7d4c0b9e55edb4800236627c87b777e29386d9fe02b`,
  derived from legacy `83a41e41` with exactly twelve overlays. The complete 364-file manifest passed
  offline and in all four live containers; other files/defaults/dependencies are preserved.
- Existing six core/admin services remain on `da052082`; their IDs and the three legacy scheduler
  and infrastructure identities are unchanged. Database schema remains `20261010_0061`.
- The production-only dedicated pipeline image pin and three existing-key mappings are bounded.
  Two explicit nonsecret legacy version values preserve the targets' original effective runtime;
  `.env`, global APP_IMAGE and all credentials are unchanged. Draft has neither admin nor model key.
- Two observations 70.09917 seconds apart verified all six current consumer instances, strictly
  advancing heartbeats, no restarts/log errors/load errors, exact configuration and source.
- Business row hashes and both complete durable directories are unchanged. Only idle history
  barrier timestamp and expected consumer heartbeats are permitted housekeeping updates.

## Validation

- `predeploy gate PASS @ f062b82+dirty: 10 passed, 0 failed, 1 skipped (2026-10-10T06:19:43+00:00)`.
  The sole dirty item was an untracked frontend/node_modules tooling symlink; tracked inputs matched
  the exact application commit. Skip: absent private visual-asset authoring fixture.
- Frontend 371 tests, 36 real PostgreSQL admin integration cases, 128 template/backend cases (six existing
  asset skips), 51 model/lifecycle/Compose cases and 17 isolated rollout regressions passed. These suites
  overlap; no combined total is implied. Scoped lint/types/format/API parity and independent review passed.
- Actual candidate image offline smoke verified installed AES behavior, default preservation,
  template pinning and legacy ACK recovery, importing four entrypoints with zero provider calls.
- Production browser verified five documents/reload/login/environment label,401 read protection,
 404 missing/unproxied paths, all three asset hashes and no mobile overflow/JSerrors. No production
  authenticated write was performed. Demo retains 65 fixture jobs and the updated template notice.

## Operational incident resolved

The first attempt found pre-existing actual-vs-render environment drift after recreation. Returning
only the image also inherited the incompatible shared version values. Root recovered both original
values independently from three untouched legacy schedulers; restoring only those two reproduced
**all four full original runtime hashes**, with unchanged business/journal contents. Restored
services were verified stable at zero restarts. The corrected 17-test helper checks the actual
effective configuration **before any stop** and preserves the exact proven overrides. See
`research/runtime-drift-analysis.md`, diagnosis/restoration receipts and independent review.

The final deployment used a fresh verified baseline and passed every acceptance requirement. First
attempt evidence and backup are retained; its missing-effective-runtime backup must not be passed
to automatic recovery.

## Backup, recovery and access

- Final backup: `/var/backups/edu-ai/admin-pipeline-20261010T063121Z`. Custom-format DB dump
 101876765 bytes with verified restore listing; draft 636 files / 30642052 bytes and weekly 281 files / 
 51112280 bytes archived with every file's bytes and ownership/mode verified. Raw config/journal
 inventories stay root-only on the server.
- Corrected staged recovery: `sudo -n python3 /var/tmp/edu-admin-pipeline-20261010T063108Z/cutover.py
 --recover /var/backups/edu-ai/admin-pipeline-20261010T063121Z` (one shell command). It preserves
 legacy settings and never restores DB or rewrites journals. Changed/new pins or unreadable state
 keep the draft worker stopped for compatible forward repair; retain/restore matching frontend.
- Frontend installed with verified Linux atomic directory exchange. Previous assets:
 `/var/www/edu-ai-admin.before-20261010T063121Z`, also copied in the final backup.
- Production preview: http://127.0.0.1:5180/admin/ ; read-only demo: http://127.0.0.1:5181/admin/ .
  Refreshed processes are recorded in `research/preview-processes.json`; the existing SSH tunnel
  and fixture server are preserved. Temporary validation port 5182 is stopped.
- No extra scheduled work, draft upload, external publication, model call or production key rotation
  was used for testing. Public HTTPS/domain, dashboard, poster styles and real-write acceptance are
  outside this approved batch.
