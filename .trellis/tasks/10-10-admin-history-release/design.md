# Design

## UI and API
Use existing injected clients and styling/guards. Audit needs an explicit request generation/context shared by initial/refetch and load-more, plus separate append error/retry; no router/store migration.
Publication GET /api/v1/admin/wechat/publish-jobs keeps items compatible and adds total/offset/limit metadata. Support bounded offset/limit, a closed status filter, date_from/date_to creation dates (inclusive days; UTC predicates from business timezone). Retain old jobs(accountId) array adapter for draft/published loading if needed; add typed jobsPage for record pages. Default API limit may remain50 for compatibility, UI sends20. API types remain generated. Job record pagination must not restrict server-side draft occupancy or couple filtered jobs to draft actions. Use deterministic created_at desc,id desc and count matching filters. Invalid range rejects with controlled422. Backend filters/date handling are source of truth.

## Ownership
- audit implementer: frontend/src/features/admin/AuditLogPage.tsx and tests; helper file only if useful. H1/H2. No backend or shared CSS edits without root coordination.
- publication implementer: backend admin_wechat route/schema, wechat_admin list service, appropriate integration tests; backend/openapi.json + generated frontend schema; frontend wechat/api,testApi, usePublicationPage, WeChatPublishPage and relevant tests; minimal Admin.module.css additions only coordinate if needed. H3/H4. No rollout/spec writes.
- root: task/specs, mock/browser fixtures, combined verification, release manifests/scripts, authorized deployment and final commit/archive/journal.
- independent checker: review/self-fix after implementers finish with coordination; owns review report. No production operations.

## Release
Work in existing admin worktree, new fix/admin-history-release-20261010 branch descended from verified admin batch. Preserve unrelated root checkout and node_modules symlink. Until backend cutover succeeds, do not overwrite frontend/dist-admin or restart production-connected5180. New builds go in task-specific /tmp paths. Use the previous reliability rollout as base, regenerate candidate hashes after H3 changes. Gate final application source commit before remote cutover; documentation-only receipts can be committed after deployment. Preserve all non-target service IDs, user config, publishing history and production secrets. No automatic real publish/sync/probe smoke.
