# Implementation Plan

## Ordered Checklist

1. Update provider-neutral WeCom ports/constants with group limits and the byte-oriented image send
   contract while retaining the self-built-app media-id methods.
2. Extend `Settings`, `.env.example`, and both Compose service environments with provider selection,
   secret group key, and group-specific limits. Add provider-aware validation without weakening the
   current self-built-app checks.
3. Extract or reuse bounded WeCom response/error helpers as needed, then implement the group webhook
   adapter with fixed-host URL construction, Markdown/image payloads, Base64/MD5, no redirects,
   bounded parsing, retry classification, and secret-safe representations.
4. Add deterministic bounded image preparation for the group two-megabyte limit. Keep source
   artifact verification in the delivery service and avoid writing a derived object to MinIO.
5. Update the existing self-built-app client to satisfy the byte-oriented delivery port by wrapping
   its existing upload/send sequence. Keep its public/tested media-id operations intact.
6. Select the provider in `wecom_dispatcher_main.py` and update the delivery service to use the
   effective provider text/image limits and safe logical group recipient.
7. Add contract tests for the group adapter and settings; extend delivery tests for group eligibility,
   image preparation, ordering, idempotency, partial failure, and unknown timeout behavior.
8. Run focused tests, formatter/linter/type checks, Compose rendering, migration-head/doctor checks,
   and the final backend/full repository quality gates after the last production edit.
9. Review the diff for secret exposure and unrelated worktree changes. Update the backend WeCom
   specification with the final group-webhook contract, then commit only task-related files.

## Validation Commands

During implementation:

```bash
conda run --name edu-ai pytest backend/tests/contract/test_wecom_client.py \
  backend/tests/contract/test_wecom_group_webhook.py \
  backend/tests/unit/test_wecom_delivery.py -q
make backend-format-check backend-lint backend-typecheck
docker compose config --quiet
git diff --check
```

Final gate:

```bash
make backend-check
make frontend-check
make doctor
docker compose config --quiet
git diff --check
```

No real webhook send belongs in the default test suite. A live smoke send is an explicit operator
action after a real group-webhook key is supplied and must use a visible test-mode marker.

## Review Gates and Rollback Points

- Before implementation: confirm the provider is group webhook, scope is group-only, and no
  self-built-app removal or Moments publishing is being introduced.
- After configuration changes: verify blank placeholders render and default settings do not enable
  side effects.
- After adapter changes: inspect `repr`, logs, exceptions, and request construction for key/query
  leakage; verify timeout is classified as unknown.
- After service changes: verify the original image checksum is still checked and text success is
  persisted before image delivery.
- If provider behavior is wrong in deployment: disable WeCom or switch the provider setting back to
  self-built-app; no migration rollback is required.
