# 智谱 OCR 请求拒绝诊断与修复 — Implementation Plan

## Phase 0 — Baseline and contract freeze

- [x] Reconfirm clean task scope, production commit/image/Alembic, flags false, service health and
  zero running content/image/delivery work with bounded read-only probes.
- [x] Record official `glm-5.2` text-only and `glm-ocr` image-layout contracts in task evidence;
  do not call a provider in this phase.
- [x] Run focused baseline tests for Settings, factory, image validation, material worker, Compose,
  Doctor and API drift.

## Phase 1 — Provider-specific OCR adapter

- [x] Add bounded `IMAGE_OCR_MODEL`, input/response byte limits and timeout Settings; validate exact
  reviewed model when controlled diversity is enabled.
- [x] Implement `ZhipuImageTextRecognizer` on `/layout_parsing`, PNG/JPEG Base64, safe typed errors,
  strict response/model/layout validation and deterministic ordered line projection.
- [x] Route image OCR to the new adapter without changing text generation, embeddings, brand PDF
  OCR or the disabled image-quality auditor.
- [x] Keep the provider-neutral port and material service API unchanged; no migration/OpenAPI drift.

## Phase 2 — Tests and operations wiring

- [x] Add request/response/error contract tests including malformed indices, bbox values, page
  count, labels, line count, model identity, bytes, media types and safe error redaction.
- [x] Add Settings/factory/material regressions for model separation, disabled compatibility,
  exact ordered OCR, typed failure and no similarity/storage before OCR success.
- [x] Wire `.env.example`, Compose API/content worker equality, Doctor and production evidence with
  safe model/version output only; update README/runbook and backend specs.
- [x] Run affected Ruff/strict mypy/tests, API contract, Compose render, Doctor, shell syntax,
  lock/release checks and `git diff --check`; then run full backend/frontend quality gates.

## Phase 2.1 — Official response-envelope correction after the first live gate

- [x] Record the second offline root cause from the official response contract: nested
  `layout_details`, typed `data_info.num_pages`/`pages`, and documented element `height`/`width`.
- [x] Replace the flat image-only decoder with a strict exactly-one-page nested decoder; preserve
  the legacy brand/PDF OCR response and all factory/material interfaces.
- [x] Ignore bounded `image` content without projection, reject table/formula and malformed or
  conflicting metadata before similarity/storage, and add content-free parsing-stage issue codes.
- [x] Mirror the official response in contract tests, including page and element dimensions,
  multi-page/conflict/malformed/non-text cases; focused OCR pytest, Ruff and file-level strict mypy
  pass.
- [x] Run project Ruff and strict mypy plus the broader provider/material focused tests; record the
  local-only outcome in `result.md` without any live/SSH/deployment/WeCom action.

## Phase 3 — Independent check and release preparation

- [x] Dispatch independent `trellis-check`; fix findings and repeat full-scope gates.
- [x] Verify no Alembic/OpenAPI/generated frontend drift and no secrets/private paths/provider bodies.
- [x] Main session prepares one coherent code/spec/task commit, pushes the approved Codeup main
  commit (GitHub remains backup only), and builds the immutable offline source-overlay image.
- [x] Validate image labels, source manifest, imports, non-root user, exact file set, dependency
  health and rollback image IDs before production quiesce.

## Phase 4 — Deploy with flags still false

- [x] Capture fresh production DB/MinIO/brand/env/code/image rollback artifacts and checksums.
- [x] Quiesce dispatcher, content, governance and acquisition writers in order; require infra-only
  state and zero running work.
- [x] Deploy the exact verified backend image through the existing offline source-overlay path;
  run migration (expected head remains 0021), seed/Doctor/runtime probes, then restore upstream,
  governance and content while both flags remain false. Keep dispatcher stopped for live gates.
- [x] Require protected inputs, durable business counters and historical queued work unchanged,
  aside from explicitly explained ordinary current-date scheduler reconciliation.

Post-deployment marker audit: the canonical short marker was resolved as a regular mode-0600
`ubuntu:ubuntu` file and read as the target value before reconciliation. The separately authorized
same-filesystem atomic replacement changed only that file and preserved its path, owner and mode.
A repeated 30-second flags/service/counter/protected/log gate passed without restart or durable
delta; the dispatcher remained stopped.

## Phase 5 — Bounded live OCR and isolated news

- [ ] Create one protected deterministic 1024×1024 PNG with the exact approved three lines; call
  the deployed `glm-ocr` adapter once and require exact ordered output. Never print image/Base64,
  provider body or credentials; delete the fixture after evidence.
- [ ] If the OCR fixture passes, clone production DB into a generated temp DB and create a distinct
  private empty MinIO bucket; prove exactly one target and zero other actionable queues.
- [ ] Run one isolated content worker with diversity/OCR true, audit/schedulers/WeCom false and
  `IMAGE_MAX_ATTEMPTS=2`; allow at most two image generations and one OCR logical call per image.
- [ ] Require stored 1024×1024 image, two distinct plans, exact ordered OCR, accepted similarity,
  no copy/WeCom delta, then download to a protected path for manual inspection of brand identity,
  topic fit, title hierarchy, occlusion, pseudo/extra text, watermark and QR.
- [ ] On any failure, stop immediately: no second news, manual retry, enqueue or resend; keep
  production flags false and follow failure cleanup/recovery.

The first Phase 5 gate was attempted exactly once and failed closed with the typed
`invalid_provider_output` code. The deployed adapter used the reviewed `layout_parsing` capability
and `glm-ocr` model with `AI_MAX_ATTEMPTS=1`; the observed provider-attempt count was exactly one,
but no exact ordered three-line result was accepted. No retry or second OCR call was made, so this
checkbox remains incomplete and the isolated-news/Comfly and activation steps were not started.
The generated local and protected-stage fixture child directories were removed and confirmed
absent. Production flags remained false, the dispatcher remained stopped immediately after
fixture cleanup, and all durable provider, image, package and delivery counters remained at their
pre-call values. The subsequent authorized fail-closed recovery started only the already-created
candidate dispatcher. After more than two
poll intervals and a final 30-second gate, all eight application services were running the exact
candidate at restart zero, infrastructure was healthy, both flags and exact release markers were
unchanged, and WeCom job/attempt/status/duplicate/provider-send deltas and safe log findings were
zero. No provider call, enqueue, retry, resend, environment/data edit, fixture, acceptance
database, or bucket was created during recovery; the verified stage and rollback artifacts remain
retained for diagnosis.

## Phase 6 — Activation or fail-closed recovery

- [ ] On full pass only, atomically set `IMAGE_DIVERSITY_ENABLED=true` and
  `IMAGE_OCR_ENABLED=true`; validate Compose/Settings equality and recreate API/content worker on
  the same verified image.
- [ ] Restore schedulers, prove runtime health/restart0 and expected configuration, then restore
  WeCom dispatcher last without enqueue/retry/resend.
- [ ] Run 30-second stability, durable counter/status checks and bounded secret-safe log scans.
- [ ] On any mismatch, restore env/image/services from verified rollback artifacts and keep flags
  false; unknown provider/delivery state is terminal failure.

## Phase 7 — Cleanup and record

- [ ] Remove only exact generated DB/bucket/fixture/container/dump/state after evidence capture;
  retain the protected env/backup according to rollback policy.
- [ ] Update `result.md` with code/deploy/live outcomes, bounded call counts, final flags, visual
  inspection and zero-delivery proof.
- [ ] Complete final Trellis review, spec-sync judgment, task commit/archive and session record;
  do not include unrelated `reports/**` or skill edits.

## Rollback points

- Before provider call: remove local fixture/temp resources; no external side effect occurred.
- Before production env edit: restore all stopped services on the newly deployed default-off image.
- After env edit: atomically restore env backup, recreate affected services, verify flags false,
  and restore dispatcher last.
- After any ambiguous OCR/image/WeCom result: do not retry or send; preserve safe typed evidence.

## Independent Phase 2.2 review

The independent reviewer found and fixed two contract defects before freezing production code:

- Provider-side exact OCR failures used `InvalidProviderOutputError`, so missing, unexpected,
  duplicate, or misordered text bypassed the existing one-repair image-quality path. The material
  worker now recognizes only those four allowlisted issue codes as recoverable OCR quality
  findings. Malformed schema/layout, identity, HTTP, and input errors remain terminal before
  similarity or storage.
- Settings and direct adapter construction permitted an image-OCR response ceiling above the
  reviewed 1 MiB envelope. Both now cap the response at 1 MiB, and conflicting page-count fields
  are rejected as an invalid single-page response.

Focused review gates passed with 97 tests plus affected Ruff format/lint and strict mypy. The final
local-only pass completed after production-code freeze: full backend Ruff/mypy and 812 tests at 80%
coverage; frontend OpenAPI/format/lint/type/test/build with 39 tests; 52 release tests; Python lock,
full-profile Compose, Doctor, shell syntax, diff, secret/log and migration/API/dependency/generated
drift checks. No live provider, SSH, production, deployment, commit, push, enqueue, retry, resend,
or WeCom action occurred.
