# Harden Freshness, Orchestration, and Compliant Crawling

## Goal

Make the daily content pipeline select only trustworthy recent articles, wait for factual
governance before creating a topic-selection cutoff, and recover safely when an earlier no-topic
decision was created before governance completed. Improve crawler resilience and observability
while preserving the approved-source, public-HTTPS, and no-anti-bot-bypass boundaries.

## Confirmed Facts

- The 2026-08-03 scheduled acquisition run processed all eight approved sources successfully,
  produced 26 new candidates, one unchanged result, and filtered 200 list items.
- The same run included articles published in April, June, July 2025, and August 2026. The current
  acquisition gate filters title relevance but does not enforce a ten-day publication window.
- The content scheduler created the 2026-08-03 topic run at 11:18 before governance completed.
  It persisted two old candidates and `all_vetoed` with an immutable cutoff.
- Governance later processed the acquisition run as 20 successful jobs and 7 review-required jobs,
  but the existing daily topic key returned the old run on manual enqueue.
- `SafeHttpFetcher` already enforces HTTPS allowlists, redirect-hop validation, public DNS/IP
  checks, response bounds, timeouts, ETag/Last-Modified, an identifying User-Agent, and typed
  transient retry handling. It does not rotate identities, bypass challenges, or use stealth
  browser automation.
- Source registry metadata stores robots/terms review and per-source rate limits, but runtime
  acquisition does not receive or enforce the robots status as a crawl policy.

## Requirements

### R1 - Ten-day freshness boundary

- Add a validated acquisition freshness setting with default `10` days and a separately versioned
  content scoring freshness setting with the same default.
- A candidate with a trustworthy publication time older than the acquisition cutoff must not be
  detail-fetched or admitted as a normal evidence candidate. Record a bounded filtered observation
  and reason instead.
- If publication time is unavailable at discovery, fetch the bounded detail page only to resolve
  publication metadata. If it remains unavailable, preserve the snapshot/observation but exclude
  the document from the normal downstream candidate pool as `freshness_unknown`.
- Existing immutable candidates, snapshots, events, and audit records remain unchanged. The new
  rule applies to new acquisition runs and the downstream ten-day topic window applies to existing
  event projections.

### R2 - Governance-ready topic scheduling

- The content scheduler must not enqueue a topic-selection run until the relevant terminal
  acquisition run has a terminal governance run with no queued/running/retry-scheduled jobs.
- `succeeded` and `partially_succeeded` governance runs are eligible inputs; review-required jobs
  remain excluded by existing governance/topic veto rules.
- The scheduler must poll/reconcile while waiting, so a missed initial ordering does not defer the
  topic run until the next business day.
- The topic cutoff must be captured after readiness is confirmed and remain immutable for that run.

### R3 - Safe same-day recomputation

- If an earlier run produced `no_topic` before a newer terminal governance result became available,
  the system may create a new immutable revision with a fresh cutoff.
- The previous run and decision remain queryable as superseded history; no SQL deletion or in-place
  mutation of scores, evidence, or old decisions is allowed.
- Only the current revision may feed copy-generation reconciliation. Repeated reconciliation must
  be idempotent and must not create duplicate topic jobs, drafts, images, or packages.
- A previously selected topic is not silently replaced. Automatic same-day recomputation is limited
  to provisional no-topic decisions caused by an early/incomplete governed pool.
- API responses must expose the revision/current relationship sufficiently for operators to explain
  why a prior `all_vetoed` result was superseded.

### R4 - Compliant crawler hardening

- Keep the eight approved source profiles and their host/path allowlists; do not add arbitrary web
  discovery or expand the crawl frontier automatically.
- Enforce the recorded robots/terms policy at runtime. A disallowed source is skipped with a typed
  policy outcome; a manual-review source remains explicitly bounded and visibly marked.
- Preserve the identifying User-Agent, conservative per-source pacing, source leases, bounded
  concurrency, conditional requests, and no-cookie/no-stealth behavior.
- Honor bounded `Retry-After` values for 429 responses, retain exponential backoff with jitter for
  transient failures, and never retry 401/403, CAPTCHA, login, paywall, or other permanent policy
  responses.
- Do not implement CAPTCHA bypass, login automation, browser fingerprint spoofing, proxy rotation,
  user-agent rotation, or any technique intended to evade a site's anti-bot controls.
- Emit safe counters for stale, unknown-date, robots/policy, 403/429, retry, and parser outcomes;
  never log response bodies, cookies, credentials, or raw provider/source payloads.

### R5 - Verification and operations

- Add deterministic unit/contract tests for ten-day boundaries, missing dates, filtered observations,
  robots/policy states, Retry-After handling, and no-stealth fetch behavior.
- Add PostgreSQL integration coverage for governance readiness, same-day revision/supersession,
  current-revision queries, and idempotent copy reconciliation.
- Run focused backend checks, migration/integration checks, Compose configuration validation, and a
  read-only production-data verification after deployment. Live source checks remain opt-in.

## Acceptance Criteria

- A fixture published exactly ten days ago is eligible at the configured boundary; an item older by
  one second is filtered before normal candidate persistence; an unknown-date item is preserved only
  as an auditable filtered observation.
- A source run containing old and current titles stores only current candidates under the new rule,
  while exposing filtered counts and reasons.
- Starting content services before governance no longer creates an early topic run; once governance
  reaches a terminal state, exactly one topic revision is enqueued with a fresh cutoff.
- A pre-existing no-topic run created before governance can be superseded by one new revision without
  changing the old row, and repeated reconciliation creates no duplicate revision or downstream job.
- A selected topic cannot be automatically superseded by this recovery path.
- A 429 with a bounded `Retry-After` delays the next attempt; a 403 or disallowed robots policy is
  terminal and does not trigger repeated requests.
- Existing source allowlists, SSRF protections, snapshots, provenance, no-publishing boundary, and
  all existing acquisition/governance behavior remain intact.

## Out of Scope

- Evading anti-bot systems, bypassing CAPTCHA/login/paywalls, stealth browsing, proxy or identity
  rotation, or accessing non-public content.
- Adding new sources, general search, arbitrary URL ingestion, or continuous real-time monitoring.
- Rewriting historical candidates or deleting the current day's old topic records.
- Automatic human-review approval, social publishing, or a new public-facing crawler UI.
- Recalibrating scoring weights beyond changing the explicit freshness window/version.

## Open Questions

None. Unknown publication time is conservatively excluded from the normal downstream feed, and
same-day recovery is limited to early no-topic decisions.
