# Implementation Plan

## Ordered Checklist

1. Preserve and inventory the existing dirty worktree; do not touch unrelated report files or the
   user-owned Trellis skill edit.
2. Implement the WeCom automatic-reconciliation candidate filtering and bounded conflict-skip
   logging without changing the schema, provider payloads, direct quality gates, or explicit retry
   API. Add focused unit/contract coverage for historical invalid packages, existing jobs,
   eligible direct packages, state races, and idempotent reconciliation.
3. Add the server migration runbook and production environment checklist. Keep all secret values
   blank/placeholders and document the group-webhook outbound-only requirement, profile startup,
   TLS/reverse proxy, backup/restore, monitoring, and rollback.
4. Run focused backend tests and static checks after the production-code edit. Regenerate/check API
   types only if a public contract changes; no public API change is expected.
5. Build/restart the full local Compose profile set, verify migration head and API health, and
   inspect safe scheduler/worker configuration and recent durable counters.
6. Run one isolated real preview with live sources and configured real copy/image providers. Export
   the generated copy/image under a unique `output/preview/<run-id>/` directory and retain a
   redacted manifest.
7. Enqueue exactly one visible `mode=test` group-webhook delivery for the resulting eligible
   package, poll its durable job, verify text-before-image attempts and delivery status, and check
   duplicate enqueue/reconciliation behavior. If the preview ends in a typed terminal outcome,
   record it and do not fabricate a delivery.
8. Run the final backend/frontend/Compose/migration/doctor/diff gates, inspect outputs for secret or
   private-path leakage, and record evidence in the task research directory.
9. Update the relevant backend delivery/operational spec if the reconciliation rule introduces a
   reusable convention, then finish the Trellis task with a concise status report and commit only
   task-related changes.

## Validation Commands

Focused loop:

```bash
conda run --name edu-ai pytest backend/tests/unit/test_wecom_delivery.py \
  backend/tests/contract/test_wecom_group_webhook.py -q
conda run --name edu-ai ruff format --check backend
conda run --name edu-ai ruff check backend
conda run --name edu-ai mypy backend/app
docker compose config --quiet
git diff --check
```

Operational checks:

```bash
docker compose --profile governance --profile content --profile wecom ps --all
curl -fsS http://127.0.0.1:8000/healthz
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'SELECT version_num FROM alembic_version;'
python backend/app/preview_run.py --api-base http://127.0.0.1:8000 \
  --output-root output/preview
```

Final gate:

```bash
make backend-check
make frontend-check
make doctor
docker compose config --quiet
git diff --check
```

## Review Gates and Rollback Points

- Before changing code: task status must be `in_progress`; planning artifacts must be reviewed.
- Before real model/provider calls: all services healthy, migration head confirmed, output directory
  unique, and no locked business date selected.
- Before the real webhook call: package is eligible, request uses `mode=test`, provider is the
  configured group webhook, and the job fingerprint has not already been delivered.
- If reconciliation behavior regresses: stop the dispatcher or set automatic delivery false; no
  migration rollback is needed.
- If the real provider returns a timeout: preserve `delivery_unknown` and do not resend automatically.
- If a final gate fails after a production edit, fix it and rerun the affected check plus one final
  full gate; do not claim the prior green result.

## Evidence to Retain

- Service/migration/health summary with secret values omitted.
- Safe stage IDs/statuses and the redacted preview manifest.
- Local generated copy and image path under `output/preview/`.
- WeCom job/attempt safe states and response codes only.
- Test and quality-gate output summaries.
- Server runbook and production checklist paths.
