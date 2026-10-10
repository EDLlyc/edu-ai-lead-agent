# Release design — admin release 2

## Approved scope

The owner approved deployment in this conversation on 2026-10-10. Resume the existing
42-file release 9eaaaf3 rather than create a new task. The authoritative manifest and
operations are in rollout/files.txt and rollout/README.md. Application code is unchanged.

## Boundaries and compatibility

Deploy the prepared image onto exactly acquisition-api, acquisition-worker, content-scheduler,
content-worker, wecom-infographic-producer, and wecom-dispatcher. The seven older services and
cron images keep their existing images. Database migrations 0055–0059 are additive. New
ADMIN_SECRET_KEY and MODEL_SECRET_KEY values stay on the production host and are passed only
to the three named consumers. Do not log secret values or replace existing model credentials.

The account import binds the already configured production WeChat account with an editable
display name. It does not submit drafts for publication. Template selections are stored but do
not affect the older draft worker; model-key status must report legacy consumers as unconnected.
Public domain/HTTPS setup and the older WeChat pipeline upgrade are separate work.

## Release and recovery

Verify all manifest base hashes in the running image and new hashes in the prepared image.
Run the offline smoke and independent local quality checks. Check time window and in-flight jobs,
back up the complete database plus .env, .release.env and compose.yaml, then migrate and recreate
only the six services. Verify health, unauthenticated route guards, schema, source counts, model
consumer heartbeats, account import, and absence of new publication jobs. Build the admin frontend
and restore a localhost preview through an SSH tunnel as the current access route.

On failure restore the backed-up configuration and recreate the same six services on the old
image. Keep the additive schema. Never restore the entire database over new production writes.
