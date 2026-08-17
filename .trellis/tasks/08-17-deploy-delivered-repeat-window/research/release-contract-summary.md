# Offline Broad Release Contract Summary

## Authority and payload

- Review/commit/push all meaningful non-secret work, then fetch exact Codeup `origin/main`.
- Build only from a clean detached worktree at that full SHA. Bind image ID/labels, source/image
  bundles/manifests, operator hash, stage, and full/short production markers.
- Docker image inputs are the explicit committed backend context, including dormant Workbench
  modules. Active-source overlay uses a separate exact runtime manifest, and the transport bundle
  independently excludes reports/Trellis/frontend/dev lock/task tools/env/private/output/compiler
  intermediates.
- Workbench remains absent from the supported production routes/OpenAPI/Compose/runtime MCP/frontend
  graph; an unsupported manual command override is not release behavior.

## Release mechanism

No project registry credentials or genuine previous-digest baseline exist. Do not call
`make release-prod` and do not fabricate standard manifests. Use one reviewed checksum-bound
offline operator against the existing local-tag contract; standard digest activation is deferred.
This is a one-time exception to the committed digest-only release policy and requires explicit
Phase 1.4 user approval.

## Ordered execution

1. Full repository/operator/lock/contract/secret gates before commit and push.
2. Exact Codeup fetch; prove unchanged production dependencies/runtime lock despite the dev-only
   pyproject change; immutable offline image/source build and entrypoint/Alembic verification.
3. Read-only f20 preflight, two stable samples, zero actionable/nonterminal/unknown work, zero legacy
   prompt jobs, and a safe scheduler window. No complete pure read-only startup projection API
   exists; predictive create/claim mirroring is deferred rather than approximated with SQL.
4. Protected stage; load isolated candidate only; backup lock; dispatcher-first quiescence; fresh
   PG/catalog and rollback evidence.
5. Make `.env` sole scoring owner; normalize absent to explicit `.6` under old Compose.
6. Retag/overlay exact candidate under `.6`; skip MinIO init and the default migrate+seed command;
   run only the explicit Alembic upgrade command override and prove source counters unchanged, then
   offline `.6`/v3 + `.7`/v4 probe.
7. Atomically `.6 -> .7`; preserve OCR/diversity true/true.
8. Restore API/acquisition/governance/content sequentially with explicit `--no-deps`; dispatcher
   last. Immediately before each scheduler/dispatcher require sufficient safe time and the observed
   actionable/nonterminal plus legacy vectors at zero, then recheck them after its start.
9. Require exact image/restart-zero, `.7`/v4, true/true flags, healthy infra/API, unchanged Alembic,
   no Workbench endpoint, and immediate plus 30-second aggregate/log stability.

## Recovery contract

- Before durable `.7`: restore `.6`, f20 source/tags/markers/image/services; dispatcher last.
- After durable/nonterminal `.7`, or whenever zero durable/nonterminal `.7` cannot be proven: stop
  all eight application services—API, dispatcher, acquisition scheduler/worker, governance
  scheduler/worker, content scheduler/worker—retain candidate + `.7`, keep only PostgreSQL/MinIO,
  and request incident direction.
- No automatic DB restore/downgrade and no second operator invocation.

## No-side-effect contract

No manual enqueue/replay/retry/resend/fixture/provider/WeCom call. Evidence is aggregate-only and
contains no IDs, URLs, object keys, prompts, bodies, env bytes, or secrets.
