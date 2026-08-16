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

## Phase 2.2 — Raw MaaS representation compatibility after the second live gate

- [x] Review pinned official BigModel raw schema and `zai-org/GLM-OCR` converter/tests; record the
  Bayesian limit of the broad `image_ocr_layout_invalid` observation without inferring a private
  response body or making another provider call.
- [x] Keep one explicit raw MaaS decoder and strict nested single-page/model/data-info boundary;
  accept bounded unique nonnegative zero-/one-origin indices without a continuity assumption.
- [x] Accept documented unit bboxes and page-bounded raw pixel bboxes only when positive page axes
  permit deterministic normalization. Never infer an unbound `0–1000` or other coordinate scale.
- [x] Treat element dimensions as independently optional bounded vendor metadata, prefer page
  dimensions for pixels, and use element axes only as an unambiguous fallback. Ignore optional
  image content/bbox and bounded transport extensions without logging, projection, or persistence.
- [x] Split parser failures into content-free schema/page/dimension/index/label/bbox/content/
  unsupported-structure subcodes while retaining the exact three-line gate and terminal material
  routing for every parser code or mixed parser/text tuple.
- [x] Add mocked raw contract and material tests for both official bbox forms, index variants,
  optional/extensions, missing/wrong scale/dimensions, unknown labels, malformed structures and
  privacy; retain legacy PDF OCR behavior.
- [x] Independent review: select bbox scale once per raw page so a tiny pixel bbox at/below one
  cannot be mixed with ordinary pixel boxes; pin the official 2040x2640 full-page fixture.
- [x] Independent review: keep only outer/data/page extensions ignorable, reject unknown element
  keys and raw/normalized/error envelope conflicts with granular content-free codes, and require a
  present compatibility `page_count` alias to agree with typed `num_pages`.
- [x] Run focused provider/material/legacy OCR tests plus full-project Ruff format/lint and strict
  mypy; record the offline-only result and remaining design drift before any release decision.

Checkpoint after independent review: all 237 focused tests, 247-file Ruff format-check/lint,
affected strict mypy, and 141-source backend application strict mypy pass. The explicit-config,
no-incremental 147-source repository strict-mypy gate is still blocked only by the pre-existing
untouched `scripts/annotate_brand_visual_assets.py:153` `no-any-return` finding outside this
iteration's ownership. `make backend-typecheck` reports green because its repository-root command
does not discover `backend/pyproject.toml`; the explicit config invocation is the authoritative
strict result. No full backend suite or live/external action was run.

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

### Phase 2.1 correction redeployment

- [x] Freeze Codeup `origin/main` at exact correction commit
  `331a4942a84b36811cbbc4abff68bca2abc71f0c`; rebuild and revalidate the retained 307-path offline
  source overlay, immutable image provenance, non-root runtime, exact 165-file image source set,
  OCR/parser contract, migration/OpenAPI drift, and transfer bundle checksums.
- [x] Repeat strict read-only production preflight, dependency-ordered quiesce, and a fresh
  checksum/catalog-verified PostgreSQL/MinIO/brand/env/code/prior-image rollback set before any
  active tag, source, marker, one-shot, or service mutation.
- [x] Transfer and remotely verify the exact source/image artifacts; load/retag only the backend
  and nine application/migration tags, overlay only allowlisted source, preserve protected inputs
  and volumes, update exact full/short markers, and run minio-init/migration without building.
- [x] Restore API/acquisition, governance, content, then the dispatcher last with diversity/OCR
  false. Require exact candidate/restart-zero service state and stable durable/provider/WeCom,
  historical queue, protected-input, marker, migration, flags, and secret-safe log evidence across
  a final 30-second sample.

The correction redeployment used release/rollback ID `20260815T153208Z`, candidate
`sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`,
source archive SHA-256
`ea13c86df5bea0cf9f860007708d66f115cc7afb401966d4b79741772bf51f1e`, and image-bundle SHA-256
`7cb547773f9bb445fe635934d4447e6afcf7d5fd6cd2a2f296f390baecc58f63`.
All eight long-running services are on the candidate at restart zero; infrastructure is healthy,
both visual flags remain false, the durable vector remains
`34:179:34:13:2:55:142:31:40:31:376:21:41:0:0`, and nonterminal/unknown WeCom remains zero. The
protected final evidence SHA-256 is
`e28defaba3de84946fa2bd0d96a52edefbf864cf22cf88f38ed2ff91a4da5211`.
No provider call, fixture, enqueue, retry, resend, activation, frontend deploy, production build,
commit, or push occurred. The next paid OCR fixture remains unchecked and separately gated.

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

The separately authorized corrected-candidate fixture gate was then executed against release
`331a4942a84b36811cbbc4abff68bca2abc71f0c` and image
`sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`.
The current business-day durable vector had advanced through ordinary terminal scheduler work to
`35:179:35:13:3:58:154:34:43:34:382:24:47:0:0`; its delta was attributed to one acquisition run,
one governance run, one slot run, and three completed copy/image/package/delivery paths before the
gate, then remained stable with running/actionable/nonterminal/unknown counts zero. Three
schedulers and the dispatcher were stopped before the paid boundary.

Two preparation defects failed before HTTP and consumed zero provider attempts: `timeout` was
initially applied to a shell function, and the immutable application image had no font files for
in-container rendering. The first cleanup used Compose start and idempotently reran the declared
MinIO-init/migration dependencies; both remained exited-zero with no schema or durable delta.
The corrected path used the trusted local Noto Sans CJK font, transferred only a deterministic
mode-0600 1024-by-1024 RGB PNG with the exact three approved lines, proved byte/hash identity and
deployed-user readability, and used direct exact-container stop/start for final isolation and
recovery.

The deployed `ZhipuImageTextRecognizer` then made exactly one HTTP attempt with
`AI_MAX_ATTEMPTS=1` and an explicit zero-retry HTTP transport. It failed closed as
`invalid_provider_output`, with `exact_ordered=false`, zero accepted lines, parser code
`image_ocr_layout_invalid`, and no quality issue code. No retry or second OCR call occurred, so the
fixture checkbox remains incomplete and isolated-news/Comfly acceptance and activation remain
prohibited. Both local/remote fixture copies and the exact child container were deleted and proved
absent. Direct restoration started only the three previously running schedulers and then the
dispatcher last. The final 30-second gate retained flags false, the current durable vector,
restart-zero candidate services, zero queue/unknown/log findings, and no acceptance database,
bucket, enqueue, resend, image generation, Comfly, or WeCom action.

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
