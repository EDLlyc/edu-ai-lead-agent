# Rollout: 运营后台 polish (accounts, own password, source articles, audit filters)

**Superseded (2026-10-09):** never deployed. Its files ship in the combined release
`../../10-09-admin-release-2/rollout/` (9eaaaf3, migrations 0055–0059). Do not use this bundle.

Overlay of 10 backend files from `feat/admin-console-20261008` @ 0854380 on the running image
`5a5fb24c`. There is no migration and the DB stays at `20261008_0054`. Gate: `predeploy gate PASS @ a8d0af6+dirty`
(the tree committed as b554f6d). The offline smoke passed on the branch.

The steps are the ones in `../10-08-admin-console/rollout/README.md` without step 6 (migrate):
1. base hashes;
2. build (`release-0854380`);
3. offline smoke;
4. no running jobs;
5. env backup and `APP_IMAGE`;
6. recreate the six services;
7. check `/api/v1/admin/accounts` → 401 without a cookie.

Avoid slot hours. Rollback: restore the env pair and recreate the six services.
