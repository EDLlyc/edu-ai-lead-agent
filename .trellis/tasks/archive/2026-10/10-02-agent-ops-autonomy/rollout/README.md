# Rollout: watchdog diagnosis agent (release 92c80df)

Watchdog-only image `sha256:d996df96668d60e981a69180936cf3f58dcc6a34ebea355de35b85ea3a55b174`
(tag `edu-ai-lead-agent-backend:watchdog-92c80df`) = running app image 32c89fe6 + 3 files
(`files.txt`); the base of `delivery_watchdog_main.py` matched the running image; `smoke.py`
passed offline. The six app services are not touched.

Verified on the host with real read-only data (`--dry-run`, output in a temp dir): 4 past failing
slots diagnosed, see `backend/evals/ops_diagnosis/reports/2026-10-02-diagnosis.md`.

Deploy (owner confirmation required): back up `/usr/local/sbin/edu-ai-delivery-watchdog` as
`*.before-92c80df-<ts>`, set its `IMAGE=` to the digest above. The cron file is unchanged
(07:42 / 12:42 / 18:42). The content-worker service env already carries the copy-model settings,
so the diagnosis runs on glm-5.2; without them it is skipped. Model calls happen only when a slot
has a problem (about 5 calls, ~10k input tokens each).

Rollback: restore the wrapper backup (or pass `--no-diagnose` in it).
