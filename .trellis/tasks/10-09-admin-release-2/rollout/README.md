# Rollout: 运营后台 release 9eaaaf3 (polish + 公众号 3/4/5 + 排版模板 + 模型配置)

**Not deployed yet.** It needs the owner's go-ahead and runs outside slot hours
(06:00–08:30, 11:00–13:30, 17:00–19:30 CST).

- 42 backend files from `feat/admin-console-20261008` @ 9eaaaf3, overlaid on the running image
  `5a5fb24c` (= mainline a8d0af6 app): 24 new files and 18 changed, with no deletions and no
  dependency changes.
- Checked read-only on 2026-10-09:
  - all 18 base hashes match `acquisition-api`, and none of the 24 new files exist;
  - `Crypto` and `psycopg` 3.3.4 are importable;
  - the DB is at `20261008_0054`.
- Gate: `predeploy gate PASS @ 1a4851c+dirty`, i.e. the 9eaaaf3 tree. The offline smoke passed
  on the branch.
- Migrations 0055–0059 are additive (new tables plus defaulted columns), so the old image runs
  unchanged on the new schema: migrate first, then switch.
- Behaviour without operator data is unchanged:
  - no WeChat account is bound until step 12;
  - no layout choice means byte-identical drafts;
  - with no stored model key, every process uses its env keys.

**What this release does not reach.** Seven services still run the 09-28 image `83a41e41`: the
公众号 pipeline (draft worker, weekly DAG, local worker, weekly scheduler), governance worker and
scheduler, and the acquisition scheduler.
- 排版模板 choices take effect only after the draft worker is upgraded. The page says so.
- Rotated model keys reach only acquisition-api, content-worker and wecom-infographic-producer.
  The 模型配置 page lists the other three key holders as 未接入. The server's env keys must stay
  valid.
- All app services use `${APP_IMAGE}`. Recreate only the six named below. Recreating any of the
  seven would move it to this image untested.

## Steps

1. **Base check.**
   - The six services run `…@sha256:5a5fb24c…` and the DB head is `20261008_0054`.
   - For every line of `files.txt`, the sha256 of `/app/<path>` in `acquisition-api` equals
     `base` (`absent` = the file does not exist).
2. **Build.** The context is this folder plus the 42 files from the branch, at their `files.txt`
   paths (`backend/` stripped):
   `docker build -q -t offline.local/edu-ai/edu-ai-lead-agent-backend:release-9eaaaf3 .`
3. **Offline smoke.**
   `docker run --rm --network none -e PYTHONPATH=/app -v $PWD/smoke.py:/tmp/smoke.py:ro --entrypoint python <tag> /tmp/smoke.py`
   must print `smoke ok: release 9eaaaf3 …`.
4. **Nothing running.** 0 rows in each of:
   - `acquisition_jobs` running;
   - `content_slot_jobs` queued/running;
   - `copy_generation_jobs` running;
   - `news_infographic_jobs` queued/running;
   - `wecom_delivery_jobs` running.
5. **Backups** (`<ts>` = UTC stamp):
   - `pg_dump -Fc` to `/var/backups/edu-ai/postgres/edu-ai-before-admin-release-2-<ts>.dump`,
     checked with `pg_restore --list`;
   - copy `.env`, `.release.env` and `compose.yaml` to `*.before-9eaaaf3-<ts>`.
6. **Keys.** Generate both keys in the new image and append them to `.env` without ever printing
   them:
   `sudo sh -c 'k=$(docker run --rm --network none --entrypoint python <tag> -c "from app.domain.secret_box import new_key; print(new_key())"); printf "ADMIN_SECRET_KEY=%s\n" "$k" >> .env'`
   Then the same for `MODEL_SECRET_KEY`. Check with `grep -c` only: each name appears exactly
   once.
7. **Compose** (the server file differs from the repo; edit the server copy only):
   - `acquisition-api` environment gets `ADMIN_SECRET_KEY: ${ADMIN_SECRET_KEY:-}` and
     `MODEL_SECRET_KEY: ${MODEL_SECRET_KEY:-}`.
   - `content-worker` and `wecom-infographic-producer` get `MODEL_SECRET_KEY: ${MODEL_SECRET_KEY:-}`.
   - Verify with `docker compose config --no-interpolate | grep -n "SECRET_KEY: \${"`. It must
     show 4 lines and no values.
8. **Image.** Set `APP_IMAGE` in `.release.env` to the new image's digest.
9. **Migrate.** `docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env run --rm --no-deps backend-migrate`.
   Afterwards the head is `20261009_0059` and `sources` still has the same enabled seeds.
10. **Recreate** only these six, with `up -d --no-deps`:
    `acquisition-api acquisition-worker content-scheduler content-worker wecom-infographic-producer wecom-dispatcher`.
11. **After about 90 s.**
    - All six run the new image, `acquisition-api` is healthy, and `docker logs --since 3m` shows
      no traceback and no `console_model_keys_unavailable`.
    - `curl -s -o /dev/null -w '%{http_code}'` on `/api/v1/admin/auth/me`,
      `/api/v1/admin/models` and `/api/v1/admin/wechat/status` returns `401` for each.
    - `select service from model_key_consumers` lists acquisition-api, content-worker and
      wecom-infographic-producer. This proves the heartbeat and the sync DB path in production.
12. **Bind the production 公众号** (item 5), with the name the owner gives. Put the four values
    in a root-only temp env file so they never appear on a command line:
    ```sh
    sudo sh -c 'umask 077; f=$(mktemp /run/edu-wx-import.XXXXXX)
      grep -E "^(WECHAT_MP_APP_ID|WECHAT_MP_APP_SECRET)=" .env > "$f"
      for v in DATABASE_URL ADMIN_SECRET_KEY; do
        printf "%s=%s\n" "$v" "$(docker exec edu-ai-lead-agent-acquisition-api-1 printenv $v)" >> "$f"; done
      docker run --rm --network edu-ai-lead-agent_default --env-file "$f" --entrypoint python <tag> \
        -m app.wechat_accounts_main import-env --name "<名称>"
      rm -f "$f"'
    ```
    It prints `已绑定 …（…，密钥末四位 ••••）`. Then the 数据 page syncs after 10:00 the next day,
    or now with 立即同步.
13. **Do not publish anything.** A real 发布 happens only when the owner says so.
14. **Tell the others and record it.**
    - Send the new digest to the other sessions. The exhibit connector `IMAGES` pin needs it.
    - Fast-forward `mainline` to the branch and push to origin only.
    - Add a "Live since" entry to `.trellis/spec/guides/production-mainline.md`, and update the
      memory.

Rollback:
- Restore `.env`, `.release.env` and `compose.yaml` from step 5, then recreate the same six.
- The schema stays: the old image ignores the new tables and columns.
- Downgrades refuse once operators have saved accounts.
