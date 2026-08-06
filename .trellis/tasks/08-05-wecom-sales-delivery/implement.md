# Implementation Plan: Enterprise WeChat Sales Delivery

## Ordered checklist

1. Add validated WeCom settings and safe environment examples; keep all switches disabled by default.
2. Add application ports and typed provider errors/results for token, image upload and text/image send.
3. Add the official HTTP adapter with host allowlist, token cache, multipart image upload, duplicate-check payloads, bounded body parsing and error classification.
4. Add `wecom_delivery_jobs` and `wecom_delivery_attempts` ORM models plus an additive Alembic migration.
5. Add the application delivery service: package prerequisite validation, stable enqueue idempotency, lease claim/heartbeat, text composition, MinIO image read, partial completion, retry and unknown-outcome handling.
6. Add API schemas/routes and register them in `api_main.py`; expose only the configured internal `default` recipient.
7. Add `wecom_dispatcher_main.py` and the `wecom` Compose profile; wire API and dispatcher environment variables without placing secrets in source.
8. Add unit and contract tests for config, text composition, idempotency/state rules, token caching/refresh, multipart upload, message payloads, provider error mapping and unknown timeout behavior.
9. Run migration validation, ruff, mypy, focused tests and the full backend test suite; inspect `git diff` for secrets and unrelated changes.
10. Run a no-credential Compose config/build check. A real send remains opt-in and is reported as not run unless the deployment provides valid WeCom credentials and a configured internal userid.

## Validation commands

```bash
cd backend
python -m ruff check app tests
python -m mypy app
pytest -q tests/unit tests/contract
alembic -c alembic.ini check
```

From the repository root:

```bash
docker compose config --quiet
docker compose --profile wecom build wecom-dispatcher
```

## Risk points and review gates

- Provider adapter must never leak token, secret, userid, media id or response body.
- A send timeout is not equivalent to a failed send; verify `delivery_unknown` is terminal until operator action.
- Persist text success before attempting image and never resend a delivered child on lease recovery.
- API handler must only enqueue and must reject unapproved packages.
- Migration must be additive and point its `down_revision` to the current head `20260804_0017`.
- Compose service must remain opt-in and disabled by default.

## Rollback point

Before enabling the `wecom` profile, stop the dispatcher. If the migration must be reverted in local development, downgrade the additive migration after confirming no delivery rows are needed. Do not attempt to undo provider-side messages by replaying or mutating material packages.
