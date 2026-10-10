# Deployment plan — 2026-10-10

User approval: “同意上线。” The existing rollout/README.md is the detailed operations runbook.

- [x] Independent review of manifest, migrations, and admin checks; run predeploy gate and frontend build.
- [x] Verify running base, prepared image content and smoke; check current jobs and permitted time.
- [x] Save and validate database/configuration backups.
- [x] Configure encryption keys and explicit compose mappings without displaying secrets.
- [x] Migrate 0054 to 0059, preserving enabled source counts.
- [x] Recreate exactly the six approved services; verify image, health, logs and consumer heartbeats.
- [x] Bind the existing WeChat account; read-only authenticated/API checks; verify no publish jobs.
- [x] Restore localhost frontend access via production tunnel and check login rendering.
- [x] Record actual evidence, limitations and rollback locations.
- [x] Reconcile mainline and push origin (release receipt a136a6d pushed successfully).

Rollback uses the saved configuration and previous immutable image, leaving additive schema in
place. Do not deploy during the three documented push windows or with active affected jobs.
