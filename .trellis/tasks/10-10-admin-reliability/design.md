# Technical design

## Boundaries and data flow

- Preserve existing auth/roles/write guard/audits and generated OpenAPI wire types. Specific admin
  specs and the operator-approved publishing task govern this existing console; the older generic
  draft-only specs describe other workspaces, not a prohibition on repairing these controls.
- Classify publishing uncertainty at the WeChat adapter and persist it at the job state owner.
  Store outcome_unknown and succeeded in the draft occupancy set and PostgreSQL partial unique index. Recheck uses
  a known publish_id, never submit; explicit owner-only resolution is an audited local state change with note, confirmation and an updated_at concurrency token. A confirmed publication does not unlock the draft.
  No raw provider body, credential, query-bearing URL or exception text is exposed.
- Publication confirmation displays account/all titles and explains no follower mass send.
- Statistics backfill derives a bounded date range from last success, retains recent overlap for
  eventual updates, and queries missing stored days as needed. Missing-data reporting covers absent/invalid whole daily measurements, not per-metric completeness; legitimate omitted optional counters retain the existing zero convention. API supplies explicit range_start,
  range_end and missing_dates; absent rows remain missing, not fabricated zero measurements.
  Query/network/persist phases keep network calls outside open database transactions.
- Run publication and statistics in separate lifecycle-owned tasks with cancellation on shutdown.
- Model overlay keeps attempted versions distinct from loaded versions and safe load_errors.
  Heartbeat persists loaded versions plus errors; only attempted-version changes drive restart,
  avoiding a bad-ciphertext restart storm. UI presents saved state separately from consumer state.
- Vite dev/preview maps admin document routes to /admin/index.html before SPA fallback while leaving
  API, assets and missing asset requests untouched; no public binding or proxy expansion.

## Migration and compatibility

- 0060 (publication owner): extend draft occupancy to outcome_unknown and succeeded; add nullable reconciliation actor/note fields. Preflight/refuse existing
  conflicting history safely rather than discard it. Keep ORM and migration predicates equal.
- 0061 (model owner): nullable JSONB load_errors on model_key_consumers, child of 0060. Legacy
  heartbeat rows stay interpretable as status not reported; legacy services are not upgraded here.
- Additive response fields; generate API schemas/types centrally after all edits. Do not hand-edit
  generated files or old migrations. No dependency changes expected.

## Ownership

- publish worker: admin_client.py, wechat_admin.py, publish-only routes/schemas, publish ORM block,
  migration 0060, WeChatPublishPage and tests, wechat/api.ts, testApi.ts method additions.
- stats worker: wechat_stats.py, api_main.py loops, stats-only routes/schemas, WeChatStatsPage/tests,
  dedicated backend stats regression tests, testApi.ts stats fixture only.
- model/preview worker: model overlay/models API/schemas/consumer ORM block, migration 0061,
  ModelsPage/tests, vite config/fallback and its test.
- Main: task/specs, generated contracts, combined validation, browser preview, release preparation.
  Shared files use disjoint class/function edits; no whole-file rewrites/formatting until coordinated.

## Release

Develop from mainline 97ece80. Keep a release manifest and migration validation before any
production rollout. Current production remains 24e96708/schema 0059. Local browser verification of
new mutation contracts uses isolated data and fake providers, not the production account.
