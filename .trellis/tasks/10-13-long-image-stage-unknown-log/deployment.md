# Long-image stage-unknown logging — deployment record (2026-10-13)

Why: ~22% of long-image jobs in 7 days ended `result_unknown / production_stage_unknown`
with no recorded cause (`execute_next` swallowed every exception).

Change (commit a026004, `backend/app/application/services/wecom_news_infographic.py`):
emit `news_infographic_stage_unknown` with `job_id`, `error_type`, `error_code` (closed
`AppError.code` only), `http_status`, `response_kind`, `cause_type`. Exception messages are never logged.

Deployed 2026-10-13 ~10:38 CST to `wecom-infographic-producer` only:
- base image  sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7 (rollback target)
- overlay     sha256:e0513020fda591c8522bd525a74e1dc953e91133f94509c9f8d9da61459fff9e
  (tag `infographic-stage-log-a026004`), file sha256 f4c86c58…3a98
- No env file edited. `APP_IMAGE` and `CONTENT_SCORING_VERSION` overridden for that one
  `compose up` so the producer kept its running env; env name/hash diff before/after = 0.
- Backup/stage dir: /opt/edu-ai-lead-agent/backups/infographic-stage-log-20261013.wnxqGp
- First activation attempt rolled itself back (script bug: `grep -c` exit 1 under inherited ERR trap);
  fixed with `|| true`, second run succeeded.

Rollback: `APP_IMAGE=offline.local/edu-ai/edu-ai-lead-agent-backend@sha256:da05208… 
CONTENT_SCORING_VERSION=<running value> docker compose -p edu-ai-lead-agent --env-file .env
--env-file .release.env --profile infographic up -d --no-deps --no-build --pull never --force-recreate wecom-infographic-producer`

Read the cause after the next failure:
`docker logs edu-ai-lead-agent-wecom-infographic-producer-1 2>&1 | grep news_infographic_stage_unknown`
