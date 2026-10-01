# Rollout: release on mainline 1d4d8b2 (fresh candidate pool + held human picks)

Owner asked on 2026-10-01 to deploy both, as one overlay, outside slot hours.

Branch `release/selection-human-pick-20261001`, rebased on mainline 1d4d8b2 (the app production
runs since 2026-10-01 22:30, image `7bffe4ed`): selection fresh candidate pool, human pick held for
review / hook-tag edit / push, and each operator edit kept as a before/after pair
(`copy_snapshot.operator_edits`, `copy_snapshot.operator_push`). Deploy the files of the branch
head named in the commit that added this line. Gate PASS on it (10 passed, 0 failed, 1 skipped);
the offline smoke passed on a copy of mainline 1d4d8b2's app plus these 9 files. No migration.

Slot hours to avoid: 06:00–08:30, 11:00–13:30, 17:00–19:30 CST.

1. Base check: the running image is `7bffe4ed…`, and in `edu-ai-lead-agent-content-worker-1` the
   sha256 of every path in `files.txt` equals its `base` (`absent` = file must not exist).
2. Build context = this folder + the 9 files from the branch head at their `files.txt` paths
   (`backend/` stripped): `docker build -q -t offline.local/edu-ai/edu-ai-lead-agent-backend:release-f4ff3a4 .`
3. Offline smoke: `docker run --rm --network none -e PYTHONPATH=/app -v $PWD/smoke.py:/tmp/smoke.py:ro
   --entrypoint python <tag> /tmp/smoke.py` → `smoke ok: release f4ff3a4 …` (it checks every
   overlaid file against `files.txt`).
4. No job running: 0 `news_infographic_jobs` queued/running, 0 `copy_generation_jobs` running,
   0 `acquisition_jobs` running, 0 `wecom_delivery_jobs` running. Human picks: none were ever made
   (`content_slot_runs.trigger='human'` = 0 on 09-30), so no pick is stranded by the hold.
5. Back up `.env` / `.release.env` as `*.before-<head>-<ts>`; set `APP_IMAGE` in `.release.env`.
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
