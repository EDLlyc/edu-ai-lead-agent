-- Read-only count; never emit account credentials or change history.
SELECT count(*) AS conflicting_occupied_drafts
FROM (
  SELECT 1 FROM wechat_publish_jobs
  WHERE status IN ('scheduled','submitting','publishing','outcome_unknown','succeeded')
  GROUP BY account_id, media_id HAVING count(*) > 1
) conflicts;
SELECT version_num FROM alembic_version;
