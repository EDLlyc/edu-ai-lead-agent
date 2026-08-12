# Deployment checklist

1. Confirm local commit and that local automation containers are not running.
2. SSH to the established host and read-only check runtime path, Git state,
   Compose state, disk, protected paths, and service health.
3. Record the prior release/image state and create a server-local rollback
   reference before updating code.
4. Pull the committed release through Git, verify `dbd2c42` is in `HEAD`, and
   render the Compose configuration without exposing `.env` values.
5. Restrict automatic copy reconciliation and claiming to the current Shanghai
   business date; add regression coverage without deleting historical rows.
6. Rebuild/recreate only API, content scheduler, and content worker.
7. Verify the effective compact-copy versions, health, restart counts, current
   date boundary, and bounded logs. Confirm no migration or delivery action
   occurred.
8. Write redacted deployment evidence, run the focused deployment check, then
   commit/archive only the Trellis task records.
