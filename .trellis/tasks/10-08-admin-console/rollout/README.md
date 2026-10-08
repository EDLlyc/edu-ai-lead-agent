# Rollout: 运营后台 items 0–2 (login + audit, 新闻源, 关键词)

**Done 2026-10-08 17:28 CST** by this session, after the owner granted `Bash(ssh edu-ai-production:*)`
and waived the evening slot. Steps 1–8 all passed:
- base hashes: 0 mismatches;
- offline smoke ok;
- 0 running jobs (three 18:30 deliveries queued, unleased);
- DB dump 95 MB, verified with `pg_restore --list`;
- migration 0051 → 0054, still 10 seeds enabled;
- six services on `5a5fb24c…`, 0 restarts;
- `/api/v1/admin/auth/me` → 401, write without the guard → 403;
- no errors in the logs.
Next: step 9 (owner account) and the domain setup.

Owner said "上线吧" on 2026-10-08 11:57 (in the noon slot), so the deploy waits for 13:30. This
session cannot reach production (the classifier denies production SSH). Whoever deploys follows
these steps, after the owner grants the permission or instructs the deploy window directly.

- Branch `feat/admin-console-20261008` on mainline cd44772 (app = e9feebd = the running image
  `64dc8ade`). The files are those of commit ac5f076 (bdb0963 only adds the journal). 35 backend
  files, 20 of them new, including migrations 0052–0054.
- Gate: `predeploy gate PASS @ 2c9e6d6+dirty: 10 passed, 0 failed, 1 skipped` on the item-2 tree
  (committed as ac5f076). Offline smoke passed on the branch.
- The migrations are additive: new tables, plus nullable or defaulted columns. The running image
  works unchanged on the migrated schema. So migrate first, then switch the image. A rollback
  needs only the old image; the downgrades refuse once operators have saved data.
- Behaviour with no operator data is unchanged:
  - no keyword version: slot runs score exactly as before;
  - `seed_sources` keeps setting `enabled=True` until an operator toggles a source;
  - generic connectors are used only by operator-added sources.

Slot hours to avoid: 06:00–08:30, 11:00–13:30, 17:00–19:30 CST.

1. **Base check.** All six services run `…@sha256:64dc8ade…`. In
   `edu-ai-lead-agent-content-worker-1`, for every line of `files.txt`, the sha256 of `/app/<path>`
   equals `base` (`absent` means the file must not exist). The DB head is `20260928_0051`.
2. **Build.** The build context is this folder plus the 35 files from the branch, at their
   `files.txt` paths with `backend/` stripped:
   `docker build -q -t offline.local/edu-ai/edu-ai-lead-agent-backend:release-bdb0963 .`
3. **Offline smoke.** `docker run --rm --network none -e PYTHONPATH=/app -v $PWD/smoke.py:/tmp/smoke.py:ro --entrypoint python <tag> /tmp/smoke.py`
   must print `smoke ok: release bdb0963 …`.
4. **Nothing running.** 0 rows in each of these:
   - `acquisition_jobs` running;
   - `content_slot_jobs` queued/running;
   - `copy_generation_jobs` running;
   - `news_infographic_jobs` queued/running;
   - `wecom_delivery_jobs` running.
5. **Backups.**
   - `pg_dump` of the database to `/var/backups/edu-ai/db-before-admin-console-<ts>.sql.gz`.
   - Copy `.env` / `.release.env` to `*.before-bdb0963-<ts>`.
   - Set `APP_IMAGE` in `.release.env` to the new image.
6. **Migrate.** `docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env run --rm --no-deps backend-migrate`
   runs `alembic upgrade head && python -m app.seed_sources`. After it, the head is
   `20261008_0054` and `sources` still holds the same 10 enabled seeds.
7. **Recreate** only the six app services, with `up -d --no-deps`:
   `acquisition-api acquisition-worker content-scheduler content-worker wecom-infographic-producer wecom-dispatcher`.
   Leave the cron images alone; they do not read the new columns.
8. **After about 40 s.**
   - All six run the new image, `acquisition-api` is healthy, and `docker logs --since 2m` shows
     no traceback.
   - Run `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/v1/admin/auth/me`.
     It must return `401`. This reads nothing.
9. **First owner account** (interactive, the password is typed by the owner):
   `docker compose … exec -it acquisition-api python -m app.admin_users_main create <user> --name <显示名> --role owner`.
10. **Tell the other sessions.**
    - Send them the new digest.
    - The exhibit connector must add it to its `IMAGES` pins before its next restart.
    - Fast-forward `mainline` to this branch and push to Codeup origin only.
    - Add a "Live since" entry to `.trellis/spec/guides/production-mainline.md`.
11. **Watch.**
    - The next slot run has `operator_keyword_version_id` null until the first keyword save.
    - Selection and delivery are as before.

Rollback: restore the env backups and recreate the same six services. The schema stays, and the
old image ignores the new columns and tables.

## How operators reach the console

The API listens on loopback only, and the other `/api/v1/*` routes have no login, so they must
never be exposed. Only `/api/v1/admin/*` and the built console may be exposed.

- **Now (no domain):** serve the console from the office machine, as with the exhibit. Run Vite or
  `vite preview` with the `/api/v1/admin` proxy to the production API through the existing SSH
  tunnel. Open it on the office LAN.
- **Public HTTPS on a subdomain of the company's ICP-filed domain** (owner, 2026-10-08: the
  company domain is filed), for example `admin.<company domain>`:
  1. **备案接入.** The filing must list Tencent Cloud as the access provider, because the server
     124.222.207.221 is Tencent Cloud in mainland China. Check in the Tencent Cloud 备案
     console. If the domain was filed through another provider, file a 新增接入 at Tencent
     first (about 1–2 weeks). Until then, Tencent blocks the subdomain on 80/443.
  2. **DNS.** Add an A record `admin` → `124.222.207.221` wherever the domain's DNS is managed.
  3. **Security group.** Open 443, plus 80 for the HTTPS redirect and an HTTP-01 certificate.
     Restricting both to the office IP is optional.
  4. **Certificate.** Use a free DV certificate: Tencent Cloud SSL (DNS validation, download
     the nginx format) or certbot. Install it as `/etc/nginx/ssl/<domain>.crt` / `.key`.
  5. **Site.**
     - On the server, `npm run build:admin` (or copy `frontend/dist-admin/` built from this
       branch) into `/var/www/edu-ai-admin/`.
     - Copy `deploy/admin-console/edu-admin-headers.conf` to `/etc/nginx/snippets/`.
     - Copy `edu-admin.conf.template` to `/etc/nginx/conf.d/edu-admin.conf`, replace
       `__DOMAIN__`, then `nginx -t && systemctl reload nginx`.
     - If nginx is missing, install it first.
     - If ports 80/443 are already used by another site on this server, add only the server
       blocks.
  6. **Secure cookie.** Production `.env` must have `APP_ENV=production` (or
     `ADMIN_SESSION_COOKIE_SECURE=true`).
  7. **Check from outside.**
     - `https://admin.<domain>/admin/` shows the login page.
     - `/api/v1/admin/auth/me` → 401.
     - `/api/v1/sources` → 404, so the internal API is not exposed.
     - `http://` redirects to `https://`.
