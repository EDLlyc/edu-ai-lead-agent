# Direct delivery implementation plan

1. Update `backend/app/application/services/wecom_delivery.py` with a shared package eligibility
   helper and use it in enqueue and automatic reconciliation. Add direct-mode quality checks while
   preserving strict-mode approval behavior and all existing delivery safeguards.
2. Extend `backend/tests/unit/test_wecom_delivery.py` with direct-mode acceptance for
   `awaiting_manual_use + pending`, strict-mode rejection, quality veto cases, and the shared
   reconciliation query behavior using test doubles. Keep the existing image and text contract
   tests green.
3. Update `.env` locally (ignored secret-bearing file) to enable automatic direct delivery. Do not
   put credentials or enabled production behavior into `.env.example`.
4. Update the backend WeCom delivery specification and relevant comments/docstrings so the
   implementation contract no longer claims that approval is always required.
5. Run focused WeCom tests, the backend quality gate, Compose validation, and a database-backed
   smoke check. Rebuild and restart `acquisition-api` and `wecom-dispatcher` together with the
   active local configuration.
6. Observe the existing package and delivery job through the API/dispatcher. Report the exact
   package contents and the truthful delivery state; do not conceal provider failures or unknown
   outcomes.

## Validation commands

```bash
conda run --name edu-ai pytest -q backend/tests/unit/test_wecom_delivery.py
make backend-check
docker compose config --quiet
docker compose up -d --build acquisition-api wecom-dispatcher
curl -fsS http://127.0.0.1:8000/healthz
```

## Rollback point

Before the first external send, set `WECOM_AUTO_DELIVERY_ENABLED=false` and
`WECOM_REQUIRE_REVIEW_BEFORE_SEND=true`, then restart `wecom-dispatcher`. Do not delete durable
jobs or change package rows manually.
