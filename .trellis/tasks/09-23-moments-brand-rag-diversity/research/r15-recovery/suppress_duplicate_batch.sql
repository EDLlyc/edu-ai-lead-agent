\set ON_ERROR_STOP on
-- Invoke with psql -X -v apply=0 (dry-run) or -v apply=1 after a verified backup.
-- No identifiers, draft text, or provider data are printed.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
LOCK TABLE copy_generation_runs, copy_generation_jobs,
  copy_generation_checkpoints, copy_draft_versions,
  copy_generation_attempts, image_artifacts, material_packages
  IN SHARE ROW EXCLUSIVE MODE;

CREATE TEMP TABLE r15_batch ON COMMIT DROP AS
SELECT r.id AS run_id, r.content_slot_selection_id AS selection_id,
       r.status AS run_status, r.active_draft_version_id AS draft_id,
       j.id AS job_id, j.status AS job_status, j.attempt_count,
       j.lease_owner, j.lease_token, j.lease_expires_at,
       c.stage AS checkpoint_stage
FROM copy_generation_runs AS r
JOIN copy_generation_jobs AS j ON j.run_id = r.id
JOIN copy_generation_checkpoints AS c ON c.run_id = r.id
WHERE r.business_date = DATE '2026-09-25'
  AND r.timezone = 'Asia/Shanghai'
  AND r.scoring_profile = 'preview'
  AND r.content_slot_selection_id IS NOT NULL
  AND r.created_at >= TIMESTAMPTZ '2026-09-25 10:50:00+00'
  AND r.created_at < TIMESTAMPTZ '2026-09-25 11:05:00+00'
  AND r.version_fingerprint =
    'd9c80c4ce74939400dd56c02c7331d1d537d7a93c2e577a6cb7259c2a646e021';

DO $$
BEGIN
  IF (SELECT count(*) FROM r15_batch) <> 9
    OR (SELECT count(*) FROM r15_batch
        WHERE run_status = 'queued' AND job_status = 'queued'
          AND draft_id IS NULL AND attempt_count = 0
          AND checkpoint_stage = 'queued') <> 8
    OR (SELECT count(*) FROM r15_batch
        WHERE run_status = 'accepted' AND job_status = 'succeeded'
          AND draft_id IS NOT NULL) <> 1
    OR (SELECT count(DISTINCT selection_id) FROM r15_batch) <> 9
    OR (SELECT count(*) FROM r15_batch
        WHERE lease_owner IS NOT NULL OR lease_token IS NOT NULL
          OR lease_expires_at IS NOT NULL) <> 0
    OR (SELECT count(*) FROM copy_generation_runs AS old
        JOIN r15_batch AS fresh
          ON fresh.selection_id = old.content_slot_selection_id
        WHERE old.id <> fresh.run_id
          AND old.created_at < TIMESTAMPTZ '2026-09-25 10:50:00+00') <> 9
    OR (SELECT count(*) FROM copy_generation_runs AS old
        JOIN r15_batch AS fresh
          ON fresh.selection_id = old.content_slot_selection_id
        WHERE old.id <> fresh.run_id AND old.status = 'accepted'
          AND old.created_at < TIMESTAMPTZ '2026-09-25 10:50:00+00') <> 8
    OR (SELECT count(*) FROM copy_generation_runs AS old
        JOIN r15_batch AS fresh
          ON fresh.selection_id = old.content_slot_selection_id
        WHERE old.id <> fresh.run_id AND old.status = 'failed'
          AND old.created_at < TIMESTAMPTZ '2026-09-25 10:50:00+00') <> 1
    OR (SELECT count(*) FROM copy_generation_attempts AS a
        JOIN r15_batch AS b ON b.job_id = a.job_id
        WHERE b.run_status = 'queued') <> 0
    OR (SELECT count(*) FROM copy_draft_versions AS d
        JOIN r15_batch AS b ON b.run_id = d.run_id
        WHERE b.run_status = 'queued') <> 0
    OR (SELECT count(*) FROM copy_draft_versions AS d
        JOIN r15_batch AS b ON b.run_id = d.run_id
        WHERE b.run_status = 'accepted') <> 1
    OR (SELECT count(*) FROM material_packages AS p
        JOIN r15_batch AS b ON b.run_id = p.run_id) <> 0
    OR (SELECT count(*) FROM image_artifacts AS i
        JOIN r15_batch AS b ON b.run_id = i.run_id) <> 0
  THEN
    RAISE EXCEPTION 'r15_duplicate_cohort_drift';
  END IF;
END $$;

UPDATE copy_generation_jobs AS j
SET status = 'cancelled', error_code = 'release_duplicate_suppressed',
    completed_at = now()
FROM r15_batch AS b
WHERE j.id = b.job_id AND b.run_status = 'queued';

UPDATE copy_generation_runs AS r
SET status = CASE WHEN b.run_status = 'queued' THEN 'failed'
                  ELSE 'review_required' END,
    error_code = 'release_duplicate_suppressed',
    completed_at = COALESCE(r.completed_at, now())
FROM r15_batch AS b
WHERE r.id = b.run_id;

UPDATE copy_generation_checkpoints AS c
SET stage = CASE WHEN b.run_status = 'queued' THEN 'failed'
                 ELSE 'review_required' END,
    issue_codes = '["release_duplicate_suppressed"]'::jsonb,
    updated_at = now()
FROM r15_batch AS b
WHERE c.run_id = b.run_id;

DO $$
BEGIN
  IF (SELECT count(*) FROM copy_generation_jobs AS j
      JOIN r15_batch AS b ON b.job_id = j.id
      WHERE b.run_status = 'queued' AND j.status = 'cancelled'
        AND j.error_code = 'release_duplicate_suppressed') <> 8
    OR (SELECT count(*) FROM copy_generation_runs AS r
        JOIN r15_batch AS b ON b.run_id = r.id
        WHERE b.run_status = 'queued' AND r.status = 'failed'
          AND r.error_code = 'release_duplicate_suppressed') <> 8
    OR (SELECT count(*) FROM copy_generation_runs AS r
        JOIN r15_batch AS b ON b.run_id = r.id
        WHERE b.run_status = 'accepted' AND r.status = 'review_required'
          AND r.active_draft_version_id = b.draft_id
          AND r.error_code = 'release_duplicate_suppressed') <> 1
    OR (SELECT count(*) FROM copy_generation_checkpoints AS c
        JOIN r15_batch AS b ON b.run_id = c.run_id
        WHERE c.issue_codes = '["release_duplicate_suppressed"]'::jsonb) <> 9
  THEN
    RAISE EXCEPTION 'r15_suppression_readback_failed';
  END IF;
END $$;

\if :apply
COMMIT;
\else
ROLLBACK;
\endif
