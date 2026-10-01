# Rollout: release f4ff3a4 (fresh candidate pool + held human picks)

Owner asked on 2026-10-01 to deploy both, as one overlay, outside slot hours.

Branch `release/selection-human-pick-20261001` = mainline d7de3c4 + `db69ffd` (selection: score the
freshest events, newest first, cap kept; was 2718f09) + `f4ff3a4` (human pick held for review,
hook/tag edit, push; was 2a7adf6). Gate: `predeploy gate PASS @ f4ff3a4: 10 passed, 0 failed,
1 skipped`. Smoke test passed on a local copy of mainline 3a79c22's app with these 9 files.

Production services run `30f6cd0e` (app = mainline 3a79c22; the 19 repair-agent files of d7de3c4 are
not in the services and are not added here). Slot hours to avoid: 06:00–08:30, 11:00–13:30,
17:00–19:30 CST.

1. Base check: the running image is `30f6cd0e…`, and in `edu-ai-lead-agent-content-worker-1` the
   sha256 of every path in `files.txt` equals its `base` (`absent` = file must not exist).
2. Build context = this folder + the 9 files from commit `f4ff3a4` at their `files.txt` paths
   (`backend/` stripped): `docker build -q -t offline.local/edu-ai/edu-ai-lead-agent-backend:release-f4ff3a4 .`
3. Offline smoke: `docker run --rm --network none -e PYTHONPATH=/app -v $PWD/smoke.py:/tmp/smoke.py:ro
   --entrypoint python <tag> /tmp/smoke.py` → `smoke ok: release f4ff3a4 …` (it checks every
   overlaid file against `files.txt`).
4. No job running: 0 `news_infographic_jobs` queued/running, 0 `copy_generation_jobs` running,
   0 `acquisition_jobs` running, 0 `wecom_delivery_jobs` running. Human picks: none were ever made
   (`content_slot_runs.trigger='human'` = 0 on 09-30), so no pick is stranded by the hold.
5. Back up `.env` / `.release.env` as `*.before-f4ff3a4-<ts>`; set `APP_IMAGE` in `.release.env`.
6. Recreate only `acquisition-api acquisition-worker content-scheduler content-worker
   wecom-infographic-producer wecom-dispatcher` (`up -d --no-deps`). Leave the quality-report cron
   and the 21:10 repair shadow cron images alone (they never load the pool or send).
7. After ~40 s: new image on all six, acquisition-api healthy, no traceback / error in
   `docker logs --since 2m`. Route check from the server:
   `curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{}'
   http://127.0.0.1:8000/api/v1/content-slot-human-picks/00000000-0000-0000-0000-000000000000/push`
   → `422` (validation only; nothing is read or written).
8. Tell the other sessions the digest; the exhibit connector must pin it before its restart (the
   restart also turns on the exhibit's review flow). Fast-forward `mainline` to this branch, push
   to Codeup origin only, add a line to `.trellis/tasks/09-28-eval-quality-report/result.md`.
9. Watch: the next slot run's `total_scores` is about 200, not 500. The first real human pick stops
   at 待审核 until the operator pushes it.

Rollback: restore the backup pair and recreate the same six services.
