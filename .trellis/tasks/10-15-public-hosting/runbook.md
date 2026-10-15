# Public hosting runbook — xiaosaiai.com (prepared 2026-10-15, NOT executed)

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
