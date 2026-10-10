# Execution plan

- [x] Record user approval of the selected first two gaps; create isolated mainline worktree/task.
- [x] Research actual legacy source/flags/queues, template ACK compatibility and model restart closure.
- [ ] Fix legacy layout pin recovery, bounded account lookup and truthful template UI; add regressions.
- [ ] Add source Compose mappings/pins and deterministic twelve-file legacy image build/smoke helpers.
- [ ] Verify model watcher registration/draining with fake provider-free process tests.
- [ ] Independent review of application, candidate closure, stop/backup/recovery and live checks.
- [ ] Full applicable frontend/backend tests, real PostgreSQL integration, lint/types/API parity.
- [ ] Update executable specs; commit final source; run make predeploy-check on that exact source.
- [ ] Candidate offline smoke, repeat live idle admission, backups, four-service cutover and postchecks.
- [ ] Refresh exact frontend/preview; record images/hashes/receipts; archive/journal; fast-forward mainline.

## Commands / evidence

Use PYTHONPATH=backend and /root/anaconda3/envs/edu-ai/bin/python from this worktree. Existing
frontend node_modules may be symlinked without committing it. Full frontend lint/typecheck/Vitest,
API schema parity and relevant PostgreSQL layout/model integration are required. Candidate smoke
must run inside the legacy-derived image with --network none and no production env/mounts. The
production predeploy gate must pass before candidate deployment. Do not re-run broad checks without
new source changes or unresolved concerns. Any new release blocker must be resolved before cutover.

## Ownership

Template implementer owns delivery pin compatibility, bounded DB lookup, template page/tests and
related regression tests. Model/release implementer owns Compose, deterministic image-context and
offline smoke helpers plus model lifecycle tests. Root owns remote inventory/backup/cutover/postchecks,
specs, integration validation and release. Independent checker owns review and coordinated fixes.

## Authorization

The user's latest “好的，请你处理” follows the concrete proposal to process exactly these two gaps
and create their task. Existing session authorization covers this bounded implementation and its
necessary reviewed service upgrade; do not ask again for the same scope. New business publication,
key rotation or broader unrelated pipeline changes require a separate user request.
