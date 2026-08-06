# Full Automated Pipeline Acceptance

## Goal

Run one new, normal, real end-to-end content-production execution in the local development
environment and report its observable result. The run must exercise the durable production-shaped
boundaries for authoritative acquisition, governance, daily topic selection, copy generation and
audit, branded image generation, material-package persistence, and API retrieval. Its output gives
the user a trustworthy answer to whether daily automation currently works.

## Confirmed Facts

- The local Compose deployment is healthy: API, acquisition/governance/content schedulers and
  workers, PostgreSQL, and MinIO are running. Enterprise WeChat delivery is configured disabled.
- `backend/app/preview_run.py` already orchestrates the public APIs and polls their durable states;
  it uses a future unused business date by default, so it does not overwrite the current locked
  daily result.
- The runner writes redacted output under `output/preview/<preview-run-id>/`, downloads an image
  only via the local API, and validates a PNG at exactly 1024x1024 before reporting image success.
- A prior real preview completed on 2026-08-05. This task is a new acceptance execution after the
  image-output reliability changes committed in `c4b9392`.

## Requirements

1. Execute one isolated run through the existing normal public API and worker boundaries, with
   live authoritative sources and configured real copy/image providers. Local development
   PostgreSQL and MinIO records are allowed.
2. Use a new unused preview business date and unique preview output directory. Do not change
   existing rows directly, replay a locked business date, reset local data, or fabricate a success
   state.
3. Observe and retain only safe evidence for each stage: durable IDs, terminal statuses, configured
   versions, safe error codes, and elapsed timing. Do not print or persist credentials, raw provider
   responses, signed CDN URLs, or private object paths.
4. Treat `no_topic`, `review_required`, and `failed` as valid typed terminal outcomes. Only call the
   automation fully successful if a selected topic leads to accepted copy, an image that passes
   local PNG/dimension validation, and a ready/manual-use material package.
5. Verify the persisted results through the local API, and inspect the generated local manifest and
   image when present. Keep the front-end preview as viewing-only and do not create a WeCom delivery
   job or send a message.
6. Run focused regression checks for the runner and image-output safety, plus service/API health
   checks.
7. Repair the preview-manifest audit projection discovered by this run: when an audit has no
   explicit status but persists `accepted=true` or `accepted=false`, project it as `accepted` or
   `rejected` rather than the caller default. Preserve explicit statuses unchanged and do not alter
   durable audit records, decision logic, or the generation pipeline.

## Acceptance Criteria

- [x] A new preview manifest exists under `output/preview/` and identifies a unique run ID and
      business date without leaking secrets, temporary URLs, or private MinIO paths.
- [x] Acquisition, governance, topic selection, copy generation, and material-package stages each
      have API-observed terminal statuses and traceable durable IDs, or the first typed terminal
      blocker is recorded accurately.
- [x] If selection is `selected`, copy is `accepted`, validation/audit results are visible, and the
      material package is `awaiting_manual_use`, `ready`, or `completed` with an image status of
      `succeeded`.
- [x] If an image succeeds, its exported local file is a valid 1024x1024 PNG and its package/image
      status can be read from the local API. A missing or invalid image is not represented as success.
- [x] If no eligible topic is found, the manifest reports the normal `no_topic` decision and does
      not claim a pipeline defect or generate downstream material.
- [x] No Enterprise WeChat delivery job/message is created by this execution.
- [x] `docker compose ps`, API health, focused runner/image tests, and `git diff --check` pass;
      the pre-existing user edit in `.agents/skills/trellis-break-loop/SKILL.md` remains untouched.
- [x] Preview manifest audit fields represent accepted/rejected boolean audit outcomes consistently
      at both the top level and `copy.audit`, with a regression test for both values.

## Out of Scope

- Database migrations, same-day topic recomputation, source-policy changes, and front-end feature
  work.
- Automated publishing to Moments or any social platform.
- Creating, enqueueing, or sending Enterprise WeChat sales deliveries.
- Weakening SSRF, Fake-IP, DNS, HTTPS, host allowlist, image signature, size, or private-storage
  controls to force a result.

## Open Questions

None. The normal success and safe terminal-outcome behavior are defined by the existing pipeline
contracts and the user's prior approval for a real local run.
