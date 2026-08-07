# Validate Full Automation and Prepare Server Migration

## Goal

Prove the current daily content pipeline works through its real durable boundaries, remove the
observed automatic WeCom reconciliation failure loop, and leave a repeatable production migration
runbook. The target operating mode is direct delivery of a validated material package to the
configured Enterprise WeChat group webhook; the system must never publish to Moments or another
social platform.

## Confirmed Background

- Compose currently contains PostgreSQL/pgvector, MinIO, migration, API, acquisition scheduler and
  worker, governance scheduler and worker, content scheduler and worker, and the WeCom dispatcher.
- The local deployment is running on migration head `20260805_0018`; API, PostgreSQL, and MinIO are
  healthy. Profiled services require the `governance`, `content`, and `wecom` profiles when started
  from a clean host.
- The current deployment uses the official group-webhook provider with automatic delivery enabled
  and review bypassed only at the package-review layer. Copy/image validation and audit gates still
  apply before direct delivery.
- Database inspection on 2026-08-07 found 10 material packages, 7 delivered WeCom jobs, and 6 old
  terminal provider-rejected jobs. The 7 recent delivered jobs each persisted successful text and
  image attempts with provider response code `0`.
- One 2026-08-04 package remains `awaiting_manual_use` but has no image validation/audit snapshots.
  The dispatcher repeatedly logs `wecom_auto_delivery_skipped error_code=conflict` for that package
  because the current direct-delivery quality gate correctly rejects it.
- The existing `backend/app/preview_run.py` can drive an isolated real acquisition-to-package run
  through public API boundaries and writes a redacted local manifest. It does not by itself create a
  WeCom delivery job.
- The repository already treats provider secrets, raw webhook keys, signed URLs, private MinIO
  locations, and raw provider bodies as non-loggable and non-persistable.

## Requirements

### R1. Operational verification

- Inspect every Compose service and record running/healthy/exit state, migration head, API health,
  scheduler/worker liveness, and safe stage counters.
- Verify acquisition, governance, topic selection, brand retrieval, copy validation/audit, image
  generation/validation, material-package assembly, and WeCom delivery separately. Distinguish a
  valid domain result such as `no_topic` or `review_required` from an infrastructure failure.
- Do not alter the existing locked daily result, reset volumes, or edit database rows directly.

### R2. Automatic WeCom reconciliation

- Stop repeatedly evaluating historical material packages that already have a delivery job or fail
  the direct quality prerequisites. Keep those packages and their safe failure evidence queryable.
- Preserve the final enqueue-time quality check for races and incomplete state. A deterministic
  ineligible package must not cause an unbounded two-second error log loop.
- Preserve idempotency, text-before-image ordering, leases, unknown-timeout handling, bounded retry,
  secret redaction, and explicit operator retry semantics.
- Add regression coverage for the historical incomplete-image case and for eligible direct delivery.

### R3. Isolated real end-to-end run

- Execute one new run using an unused business date and unique output directory through the normal
  API, schedulers/workers, live authoritative sources, configured real model providers, brand
  references, image generation, package assembly, and the group webhook delivery path.
- Use a visible WeCom test marker and one idempotent delivery request. Persisting local development
  rows and incurring configured provider cost is allowed; credentials and raw provider responses
  must not appear in output.
- Save a redacted manifest and local copy/image evidence so the generated text and image can be
  inspected. If the upstream result is a valid `no_topic`, `review_required`, or typed failure,
  report that exact outcome and do not manufacture downstream success.

### R4. Quality and compatibility checks

- Run focused regression tests for the changed delivery behavior, backend formatting/lint/type
  checks, backend tests, frontend/API contract checks, Compose rendering, migration checks, health
  checks, and `git diff --check`.
- Preserve the pre-existing user-owned edit in `.agents/skills/trellis-break-loop/SKILL.md` and all
  unrelated report files.

### R5. Server migration readiness

- Add a production-oriented runbook covering prerequisites, non-placeholder environment variables,
  secret placement, Compose profile startup order, migration and seed execution, frontend build and
  reverse proxy/TLS, firewall exposure, backup/restore, monitoring/alerts, log retention, upgrade,
  rollback, and first-day verification.
- Document that only API/frontend HTTP(S) should be exposed publicly; PostgreSQL and MinIO remain
  private. The group-webhook route needs outbound HTTPS only and does not need a trusted callback
  URL, trusted domain, or Enterprise WeChat self-built-app IP configuration.
- Keep `.env.example` safe for local development and provide a clearly labeled production checklist
  without committing real credentials.

## Acceptance Criteria

- [ ] All intended Compose services are running with the profiled services explicitly enabled; API
      health and migration head checks pass.
- [ ] The historical incomplete package no longer generates an unbounded repeated reconciliation
      conflict log, while its package and image evidence remain unchanged and inspectable.
- [ ] A newly created eligible package is automatically enqueued once, delivered as Markdown/text
      followed by image through the configured group webhook, and remains idempotent on reconciliation.
- [ ] The isolated run records safe terminal evidence for acquisition, governance, selection, copy,
      image, package, and delivery. A selected-topic path has accepted copy, a succeeded image, a
      usable material package, and a delivered test-mode WeCom job; a typed upstream terminal result
      is reported without false success.
- [ ] The local output contains a readable generated copy and a valid generated image without
      secrets, raw provider payloads, signed URLs, or private object paths.
- [ ] Focused tests, backend/frontend quality gates, API contract generation check, Compose config,
      migration/doctor checks, and diff validation pass.
- [ ] A server migration runbook and production environment checklist exist, explain the full
      profile startup sequence, and include backup/restore and rollback procedures.

## Out of Scope

- Same-day topic recomputation or changing the existing daily idempotency lock.
- Direct database repair of the historical package, destructive volume reset, or migration solely
  to hide old invalid data.
- Weakening SSRF/Fake-IP/public-IP checks, image signature/checksum validation, copy/audit gates,
  or webhook host validation.
- Adding inbound Enterprise WeChat callbacks, trusted-domain configuration, member lookup, or
  replacing the group webhook with a self-built application route.
- Automatic publishing to Moments, social platforms, or external public channels.

## Open Questions

None. The group-webhook direct-delivery policy and the local-server preparation scope were already
approved in the preceding delivery work; this task validates and operationalizes those decisions.
