# Admin reliability — first optimization batch

## Goal and authorization

Make the existing operations console trustworthy when publishing, syncing statistics, loading
model credentials, and reopening pages. The user approved the prioritized review with
“好的，请你处理” after the review and task-recording question. This task implements the five
first-batch items in that approved summary; no further product decision is blocking.

## Scope and requirements

- R1 (P1): correct publish/confirmation wording: public article publication, not mass send.
  Show the selected account and every article title in confirmation. Source: publish page:452,
  admin_client.py:266; original publishing PRD explicitly excludes mass send.
- R2 (P1): preserve uncertainty for submit transport interruption, unusable response and server
  failure. Unknown jobs continue occupying their draft. Add explicit status recheck and audited
  operator reconciliation; no automatic resubmission. Ongoing status failures must leave
  publishing after the existing 30-minute bound. Sources: admin_client.py:141,
  wechat_admin.py:422,492 and the existing partial unique index.
- R3 (P1): /admin/ and /admin/<section> must open and refresh in the current local Vite preview.
  Preserve real asset/API 404s and same-origin admin-only API proxy. Browser reproduced 404 for
  sources, wechat-publish and wechat-stats with current preview config at vite.config.ts:108.
- R4 (P1): backfill missed account/article statistics within the supported 30-day window after
  downtime; never claim coverage for absent records. Derive 7-day/30-day cards from explicit
  business-date bounds, distinguish missing values from measured zero, and explain daily-person
  sums are not period-deduplicated users. Sources: wechat_stats.py:104,181 and stats page:132.
  Keep statistics work independent of the publishing loop so slow sync does not delay due jobs.
- R5 (P1): only report successfully applied model-key versions. Expose a safe per-provider load
  error and distinguish saved versus loaded. Avoid repeatedly restarting on the same undecryptable
  version; a new version must still trigger normal graceful reload. Source: overlay.py:97,146.

## Acceptance

1. Submit disconnect/5xx/bad JSON/missing success identity produces outcome_unknown; known provider
   rejection stays failed. Repeated/parallel submissions of an occupied draft are refused.
2. Recheck is read-only at WeChat. Manual reconciliation is guarded, audited and available only
   for an unresolved job; a confirmed-not-published result unlocks retry without sending anything.
3. At 30 minutes, failed status polling produces actionable unknown state. Tests use injected
   provider transports and clocks, never a real publish call.
4. Browser hard navigation and refresh work for /admin/ and its known sections; missing assets
   and unrelated API paths remain 404/unproxied.
5. Ten-day sync interruption is covered within the bounded window; failed sync does not advance
   success watermark. Frontend date-boundary/gap/empty/true-zero tests pass.
6. Invalid ciphertext keeps env credentials, reports load failure and no false loaded version;
   watch does not loop-restart unchanged bad versions and reacts to a newer one.
7. Backend lint/types, targeted and integration regressions, frontend lint/types/admin tests,
   OpenAPI generated parity, builds, migration head and final review pass.

## Out of scope

The approved second batch (pagination, unsaved form guards, mobile cards and overview homepage),
mass-send capability, real publication, public domain setup, old draft-pipeline upgrade, and
production rollout are separate work. Prepare a concrete validated release for owner approval;
keep the currently deployed backend intact during development.
