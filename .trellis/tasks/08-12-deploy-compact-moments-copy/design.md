# Compact copy release deployment design

The running server remains the authority for configuration and durable state.
The local repository supplies the already validated, tracked source release.
Use the existing Git checkout at `/opt/edu-ai-lead-agent` to update to the
known commit lineage, after preflight and a server-local rollback reference.

The image build embeds application source, so a Git pull alone cannot apply the
patch. Compose will rebuild only `acquisition-api`, `content-scheduler`, and
`content-worker`; PostgreSQL and MinIO stay running. The deployment does not
invoke `backend-migrate`, because the release has no schema migration.

`.env`, private brand materials, named data volumes, previous image IDs, and
the active Enterprise WeChat profile are preserved. No worker job is manually
enqueued, so an upgrade cannot intentionally create a content package or send a
message. Health and bounded logs are checked before reporting success.

The server rollout exposed a historical replay defect. Automatic reconciliation
now receives the current Shanghai business date and filters daily selections on
that date. The worker passes the same date when claiming work, and the query
joins the durable run before filtering, so old queued or stale jobs remain
preserved but unclaimable by automatic processing. `execute_next` accepts an
optional time only for deterministic tests; the production default remains the
current UTC time converted through the configured business timezone.
