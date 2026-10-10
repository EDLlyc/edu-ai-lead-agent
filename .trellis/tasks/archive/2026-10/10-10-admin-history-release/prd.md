# Admin history correctness and approved combined release

## Authorization / outcome
The user approved the preceding review with “好的，请你处理”: fix audit records, add publication-job pagination/status/date filters, then deploy these changes with the already-complete reliability and usability batches. This also answers the preceding request to create a task; no repeated planning or deployment consent is needed. Preserve current production workflows and operator data.

## Requirements / acceptance
- H1: Audit load-more results/errors never overwrite a new filter, refresh, retry, or mounted context. Retain already-loaded entries on a retryable page failure; prevent duplicate concurrent page requests. Verify delayed success and rejection races.
- H2: Translate publish_rechecked and publish_reconciled into clear Chinese actions and correct descriptions, including result, note, and ignored-newer-state where relevant. Recheck success must never say “能抓到文章”. Unknown future action remains safe/readable.
- H3: Publication records expose all records beyond 50, with total/range, 20 per page, previous/next, empty/error/retry, status and inclusive creation-date filters in the business timezone. Validate invalid dates/ranges/limits/status. Stable created_at/id ordering and bounded DB queries. No database migration for pagination.
- H4: Switching account/tab/filter/page resets pagination and isolates late responses, including A→B→A. Existing confirmation, draft locks, manual reconciliation guard/token and nonoverlapping polling remain intact. Non-job tabs must not inherit filtered occupancy data.
- H5: Full frontend gate, OpenAPI parity, backend lint/types and relevant real PostgreSQL admin integration tests; independent review and real browser mobile/filter/race checks pass. Final source commit passes make predeploy-check with existing baseline; no new failures or waivers.
- H6: Revalidate the live base image/hashes/schema; prepare exact minimal backend overlay including prior migrations0060/0061; offline candidate smoke; quiet-time idle check, verified database/config/frontend backup, six-service cutover and frontend replacement. Verify schema, health/logs, read-only authenticated contracts and preserved counts. Record digest/assets/rollback, update actual production preview5180 and isolated demo5181. No real publication or model probes.

## Deferred
Template-worker upgrade/application, overview dashboard, poster styles, public domain/TLS, other legacy services and cron upgrades are outside this approved batch. Never reset/read/reveal account passwords or rotate existing secrets.
