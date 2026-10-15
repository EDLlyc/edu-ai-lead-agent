# Public hosting runbook — xiaosaiai.com (EXECUTED 2026-10-15 ~12:10-13:25 CST, see "Execution record")

Hosts (owner confirmation pending for the mapping): `ops.xiaosaiai.com` = 运营后台,
`pgc.xiaosaiai.com` = 展台. Both A records -> 124.222.207.221 (resolved from public DNS and from the
server on 10-15 ~11:40). Note: an OCR copy of the DNS table said `xiaosiai`; the certificate and
resolution prove the real name is `xiaosaiai`.

Certificate (from the tech lead, never committed): wildcard `*.xiaosaiai.com` + apex, Certum DV,
valid 2026-09-22 .. 2027-04-09, key matches, chain of 3. Source folder is in the WeCom cache on the
owner's PC (key file is world-readable there: delete after upload). Install as
`/etc/nginx/ssl/xiaosaiai.com.{crt,key}`, key mode 600 root. Renew by 2027-04.

Server facts (read-only checks 10-15): Tencent Cloud CVM ap-shanghai `ins-fe0zqjvv`; nginx not
installed (apt candidate 1.24.0); nothing on 80/443; disk 89% used (8.4G free); production image
`a3a3e7f7…` contains NO visitor-display code; compose passes env per service, so
`ADMIN_SESSION_COOKIE_DOMAIN` must be added to `acquisition-api` in compose.yaml.

## Built artifacts (rebuild from clean exports; paths are in /tmp)
- Admin: mainline `d1e5b14`, `VITE_ADMIN_DATA_MODE=production VITE_API_BASE_URL=https://ops.xiaosaiai.com
  VITE_EXHIBIT_ENTRY_URL=https://pgc.xiaosaiai.com/ npm run build:admin` -> `dist-admin/` (serve at /admin/).
- Exhibit: branch `c195bf1`, `VITE_ADMIN_ENTRY_URL=https://ops.xiaosaiai.com/admin/ npm run
  build:visitor-display` -> `dist/visitor-display/`. Calls relative `/api/v1/visitor-display/*`.
- nginx: `nginx/render.sh <out>`; both files passed `nginx -t` and a stub-upstream auth test.
- API overlay: `overlay/` FROM `a3a3e7f7…` + `core/config.py` + `api/v1/routes/admin.py`
  (base hashes expected: config bdc046bb…, admin 68aa6ace…; new: 960fd930…, f6793f2d…); `overlay/smoke.py`.

## Order (outside 06:00–08:30, 11:00–13:30, 17:00–19:30)
1. nginx: apt install, put cert/key, render configs, snippets, static roots
   `/var/www/edu-ai-admin` (admin) and `/var/www/edu-ai-exhibit`; `nginx -t`; start. Check
   `https://ops.xiaosaiai.com/admin/` from outside (Tencent blocks unfiled domains).
2. API: build overlay + offline smoke; add `ADMIN_SESSION_COOKIE_DOMAIN: ${ADMIN_SESSION_COOKIE_DOMAIN:-}`
   to acquisition-api only; `.env` `ADMIN_SESSION_COOKIE_DOMAIN=xiaosaiai.com`; back up compose.yaml,
   `.env`, `.release.env`; recreate acquisition-api, content-scheduler, content-worker as for `.17`
   (active-jobs checks, auto rollback). Compare effective env before/after (names only).
3. Exhibit data service: NOT READY — see "Open".
4. Verify from outside: login on ops, cookie `Domain=xiaosaiai.com`, pgc redirects to ops login when
   signed out and shows live data when signed in; operator routes 404; session lasts 12 h.

## Open
- Exhibit adapter code lives only in the root tree (`connect_live.py` overlays WORKING-TREE files,
  which include uncommitted WIP). Decide: deploy the committed `c195bf1` version (clean) or finish and
  commit the WIP first. It needs an overlay image (FROM a3a3e7f7 + the visitor_display files), a new
  compose service on the compose network with `VISITOR_DISPLAY_ENABLED=true` and an asset secret, no
  operator PIN and no production API URL, bound to 127.0.0.1:18089, ideally a read-only DB role.
- Security group 80/443 and ICP filing status: unconfirmed (a local TCP test is meaningless behind the VPN).

## Execution record (2026-10-15, owner said "现在就部署吧" at 11:57, so the slot-window rule was waived)
- Exhibit data service: image `offline.local/edu-ai/edu-ai-lead-agent-backend:visitor-display-c195bf1`
  (id `b47c3539…`, tree sha `b4f55869…` = `f06694a` + `c195bf1` overlay files, 320 files), service
  `visitor-display` from `adapter/compose.visitor-display.yaml` (`profiles: [exhibit]`, host network,
  127.0.0.1:18089, read-only fs, no operator PIN). `adapter/activate-exhibit.sh` created a SELECT-only
  Postgres role `visitor_ro` (read-only default transaction), appended `VISITOR_DISPLAY_ASSET_SECRET`,
  `VISITOR_DISPLAY_DB_USER`, `VISITOR_DISPLAY_DB_PASSWORD` to `.env` (backup `.env.before-visitor-display-20261015T051514Z`).
  Snapshot on loopback: HTTP 200, 470 KB, live data; operator/admin routes 404 on that process.
  Gotcha: the tree hash must use `LC_ALL=C sort` (host locale en_US ordered files differently), and the
  local tree must not contain `__pycache__`.
- API: overlay `…:admin-cookie-domain-d1e5b14` (id `e2372099…`) FROM `a3a3e7f7…`; ONLY `acquisition-api`
  was recreated (it is the only service serving `/api/v1/admin`); `content-scheduler`/`content-worker`
  keep `a3a3e7f7…` and were not restarted. `compose.yaml` gained
  `ADMIN_SESSION_COOKIE_DOMAIN: ${ADMIN_SESSION_COOKIE_DOMAIN:-}` under acquisition-api; `.env` has
  `ADMIN_SESSION_COOKIE_DOMAIN=xiaosaiai.com`; `.release.env` `APP_IMAGE` now points to the overlay so a
  later recreate cannot revert it. Effective-env diff: exactly one added name. Backup dir
  `backups/admin-cookie-domain-20261015.u0MocK` (rollback = restore its three `*.before` files and
  recreate acquisition-api).
- nginx 1.24 installed (apt), cert/key in `/etc/nginx/ssl/` (key 600 root), configs in
  `/etc/nginx/conf.d/edu-{admin,exhibit}.conf`, static roots `/var/www/edu-ai-{admin,exhibit}`.
  Loopback checks with real TLS: http->https 301; `/admin/` 200; `/api/v1/admin/auth/me` 401 signed
  out; other API paths 404; pgc signed-out page 302 to ops login, snapshot 401; operator routes 404.
- Host firewall: `ufw` was active (default deny) with only 22 open, so 80/tcp and 443/tcp were
  added (v4+v6). The Tencent security group must also allow them.
- Compose now warns about the orphan container `visitor-display` when run without the override file;
  never pass `--remove-orphans`. To recreate it use
  `docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env -f compose.yaml -f compose.visitor-display.yaml --profile exhibit`
  with `VISITOR_DISPLAY_IMAGE` set.
- Not verified by the agent: access from the public internet (the agent's machine is behind a VPN that
  rewrites DNS to 198.18.x), and a signed-in pgc view (needs an admin password). Cert expires 2027-04-09.

## Follow-up tuning (2026-10-15 ~14:30, owner approved)
- nginx: HTTP/2 on both sites; `gzip_types` for css/js/svg (http level, `edu-common.conf`) and for JSON on the
  exhibit snapshot route only (470 KB -> ~100 KB; the admin API is not compressed on purpose, BREACH);
  exhibit `/assets/` cached 1 y (private, immutable) and fixed pictures 1 d (private); the page stays
  no-store. Default servers on 80/443 return 444 / reject the TLS handshake for any other hostname or the
  bare IP (before this the console login answered on any Host). Measured from outside: admin JS 316 KB -> 97 KB,
  CSS 25 KB -> 5.9 KB, `h2` negotiated, unknown host closed. Not testable without a session: gzip/cache
  headers on the authenticated exhibit routes (syntax-checked only).
- First attempt failed `nginx -t` (duplicate `gzip on`, Debian already enables it) and was restored
  automatically; backup of the previous conf at `backups/nginx-conf-20261015-opt/`.
- Host: `fail2ban` installed with an sshd jail (5 failures / 10 min -> 1 h ban; journald backend).
  SSH password login and `PermitRootLogin yes` are still on: switch to key-only only after confirming
  a working key.
- Disk is still 89%: Docker has 139 images (14 in use, ~60 old `backend:*` release tags). Nothing deleted.

## Docker image cleanup (2026-10-15 ~14:50, owner asked "没用的镜像删除")
- Removed 286 unused tags of `offline.local/edu-ai/edu-ai-lead-agent-backend`, `edu-ai-backend:*` and the
  2-month-old compose-built `edu-ai-lead-agent-*:latest`. Kept: every image any container uses (running or
  stopped), the images named in `.release.env` and the 4 newest `.release.env.before-*`, and anything created
  in the last 7 days. Result: disk 89% -> 81% (8.4 G -> 15 G free); Docker images 139 -> 30; all 17 containers up,
  API healthy, public site 200.
- Rollback note: releases older than 7 days (except the ones listed in recent `.release.env.before-*`) can no
  longer be recreated from a local tag; the offline overlay builds are reproducible from the task folders.
- Still large: `/var/log/journal` 1.4 G (could be capped with `SystemMaxUse=300M`), Docker volumes 8.4 G (data).

## Site polish (2026-10-15 ~16:00, owner approved items 1-3)
- Login page: removed the "返回展厅" link (the exhibit requires this same login, so it looped) and reworded the
  hint to "请联系管理员开通账号。" (`AdminLoginPage.tsx`, test updated). Console rebuilt (`index-DNXin1rR.js`,
  identical to the build) and swapped in `/var/www/edu-ai-admin`; backup `backups/site-polish-20261015/`.
- nginx (both sites): `robots.txt` Disallow all, `X-Robots-Tag: noindex, nofollow` (header snippets), SVG favicon
  injected with `sub_filter` (no frontend rebuild needed for the exhibit), `/favicon.ico` -> 204, Chinese 404
  page for unmatched routes. Static files live in `/var/www/edu-ai-static/` (`nginx/static/`).
- Liveness check: `monitor/healthcheck.sh` + systemd timer `edu-ai-healthcheck.timer` (every 5 min). Checks the
  console and exhibit entry through nginx/TLS, the API (401 on `/auth/me`), the exhibit adapter (200), the 16
  production containers (list in the script, override with `EXPECTED_CONTAINERS`), disk < 92 %, certificate > 14
  days, nginx. Alerts only on change (+ every 6 h while failing) to the journal
  (`journalctl -t edu-ai-healthcheck`) and, once `ALERT_WEBHOOK_URL` is set in `/etc/edu-ai-healthcheck.env`, to a
  WeCom bot. Use an ops-only group, not the formal news group. It runs on the host, so it cannot see a security
  group or network outage (use an external uptime probe for that). A simulated failure raised and cleared an alert.

## Owner-chosen account passwords (2026-10-15 17:41, commit 6204b86)
- Policy (owner decision "block_common"): new passwords are 8-128 chars; the server refuses only the most common
  passwords (`12345678`, `password`, ...), one repeated character and a password equal to the username. Everything else
  is allowed; the console only shows a strength hint (弱/中/强) and never blocks. Owners can type the password when
  creating an account or resetting one (blank = generated, shown once); a chosen password is never echoed back.
- API overlay `…:account-password-6204b86` (id `e008f5f8…`) FROM `e2372099…` with 5 backend files; only
  `acquisition-api` recreated, effective env unchanged, `.release.env` `APP_IMAGE` moved to it. Console build
  `index-D0SiKVTa.js`. `overlay-password/activate.sh` waits out the content slot windows instead of refusing.
  Backup `backups/account-password-20261015.a3e54G` (compose/.env/.release.env `*.before`, `www.before`).
- Only owners can create accounts or reset others' passwords; editors can only change their own.

## 新闻审核 in the console (2026-10-15 18:25, commit 1b926bb)
- Overlay `…:news-review-1b926bb` (id `0ab05e2e…`) FROM `e008f5f8…` with 14 files (visitor-display news pool services/db,
  `news_reviews` store, `admin_news_reviews` route, patched `api_main.py` and `models.py`, migration 0062). Only
  `acquisition-api` recreated, effective env unchanged. `alembic upgrade` 0061 -> 0062 adds table `news_reviews`
  (empty). Console `index-BOZyDchv.js`.
- Backup `backups/news-review-20261015.5Dh3KA/`: `db-before.dump` (pg_dump -Fc), compose/.env/.release.env `*.before`,
  `www.before`. Rollback = `alembic downgrade 20261010_0061` in the new container (drops the table), restore the three
  files and recreate acquisition-api on `e008f5f8…`, restore `www.before`; `activate.sh` does it on any failure.
- Phase 3 (人工加推 from the console) is not built. Exhibit article tests are not on mainline (model drift).
- 18:40 新闻审核 page changed to a table (one row per story, AI verdict beside it, one-click 适合推/不适合推, optional
  note); console `index-d1fqClPY.js`, front-end only, backup `backups/news-review-list-20261015/www.before`.
