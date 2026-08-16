# Zhipu image OCR provider rejection — result

## Status

Repository implementation Phases 0–2, the independent Phase 2.2 quality review, Phase 3 release
preparation, and the default-off Phase 4 production deployment are complete. The canonical short
release marker was reconciled and an independent read-only recheck passed. The first separately
authorized Phase 5 OCR fixture gate was attempted exactly once and failed closed with
`invalid_provider_output`; the isolated-news/Comfly acceptance and activation were not started.
The repository then returned to Phase 2.1 for an offline-only response-envelope correction. The
reviewed correction is now deployed from exact Codeup commit
`331a4942a84b36811cbbc4abff68bca2abc71f0c` on a new immutable candidate while both visual flags
remain false. A separately authorized corrected-candidate fixture then made exactly one provider
HTTP attempt and failed closed with parser code `image_ocr_layout_invalid`; no retry, isolated-news
acceptance, Comfly call, or activation followed.

The release implementer used key-auth SSH for the reviewed backup, offline image transfer, source
overlay, migration, and dependency-ordered restart. It did not call Zhipu, Comfly, or WeCom,
generate a fixture, create an acceptance database/bucket, enqueue, retry, resend, commit, or push.
External/provider call-count deltas caused by Phases 3–4 are all zero. Production now runs the
candidate release with both visual flags false. After the failed fixture was cleaned up, the
existing candidate WeCom dispatcher was restored without enqueue, retry, or resend and passed the
bounded fail-closed recovery gate.

The later Phase 2.2 default-off release attempt for `c66aa6217d137033118c552f3db11b2a1121d082`
stopped before source overlay, marker update, migration, or candidate service creation. Production
therefore still runs `331a4942a84b36811cbbc4abff68bca2abc71f0c` on the prior `aec802...` image
with both flags false; its separately recorded 30-second recovery gate passed.

## Implemented contract

- Added independent bounded image OCR settings: `IMAGE_OCR_MODEL=glm-ocr`, 10 MiB raw input,
  1 MiB response, and 120-second OCR timeout. Controlled diversity rejects any other OCR model.
- Added `ZhipuImageTextRecognizer` on `/layout_parsing`. It accepts only validated PNG/JPEG bytes,
  sends a private Base64 data URL with crop/layout visualization disabled, and uses the existing
  bounded Zhipu HTTP transport and typed provider failures.
- Enforced case-normalized model identity and the official exactly-one-page nested raw envelope.
  The latest offline compatibility layer accepts bounded unique nonnegative indices and either
  documented `[0,1]` boxes or page-bounded raw MaaS pixel boxes with deterministic normalization;
  it retains finite raw labels, bounded text, at most eight lines, geometric
  `(y1, x1, index)` ordering, and the existing exact ordered visual-text gate.
- Bounded `image` element content is ignored without projection, logging, or persistence;
  unsupported table/formula content and malformed envelope/page/layout structures fail closed with
  stable content-free parsing-stage issue codes.
- Routed only image OCR to the dedicated adapter. `AI_CHAT_MODEL=glm-5.2` remains the text model;
  embeddings, brand PDF OCR, image generation, and the disabled OpenAI-compatible image-quality
  auditor are unchanged.
- Synchronized `.env.example`, acquisition API/content-worker Compose values, Doctor, production
  evidence, README, production runbook, and backend Trellis specifications.
- Added Settings/factory/material and provider contract regressions, including input/response
  limits, PNG/JPEG/Base64, pre-HTTP PDF/WebP/empty/malformed/oversized rejection, model/page/layout
  failures, exact line outcomes, typed HTTP failures, body redaction, and proof that OCR failure
  precedes similarity and storage.

## Local validation

- Baseline focused suite before implementation: 55 passed.
- Final focused implementation/static checkpoint: 153 passed; Ruff and strict mypy passed.
- Additional OCR envelope/422/non-text-layout/material ordering checkpoint: 67 passed.
- Full backend gate: Ruff format/lint, strict mypy over 147 source files, and 808 tests passed with
  80% coverage.
- Full frontend/API gate: OpenAPI drift check, Prettier, ESLint, TypeScript, 39 tests in 9 files,
  and Vite production build passed.
- Release/operations: Python lock check passed; 52 release-tool tests passed; Compose rendered with
  identical API/worker OCR values; shell syntax and `git diff --check` passed.
- Doctor passed against the local test stack, including one application-image contract, API/worker
  OCR equality, migration compatibility, PostgreSQL/MinIO health, and Alembic head
  `20260815_0021`.
- Final drift/safety checks found no Alembic, OpenAPI, generated frontend contract, dependency,
  credential-pattern, or adapter-output logging change.

## Independent Phase 2.2 findings and fixes

- `backend/app/application/services/material_package.py`: provider-level exact-text failures were
  terminally handled as generic invalid provider output, so the required OCR repair/catalog
  fallback path could not run. The worker now routes only missing, unexpected, duplicate, and
  misordered visual-text issue codes through the existing one-repair quality path; malformed
  layout/schema and all other provider failures remain terminal before similarity/storage.
- `backend/app/core/config.py` and `backend/app/infrastructure/ai/zhipu.py`: the configured/direct
  image-OCR response limit could exceed the reviewed 1 MiB boundary. Settings and adapter
  construction now enforce the 1 MiB ceiling. The layout parser also rejects conflicting
  page-count fields rather than accepting the first alias.
- `backend/tests/unit/test_material_package.py`,
  `backend/tests/unit/test_acquisition_foundation.py`, and
  `backend/tests/contract/test_zhipu_image_ocr.py`: added regressions for provider-level exact-text
  repair routing, the fixed response envelope, direct adapter bounds, and ambiguous page counts.

No findings remain unfixed. Existing backend specifications already required both repaired
behaviors, so no additional specification edit was needed.

## Independent final validation

- Focused OCR/Settings/factory/material/release checkpoint: 97 passed; affected Ruff format/lint
  and strict mypy passed.
- Full backend: Ruff format/lint passed, strict mypy passed over 147 source files, and 812 tests
  passed with 80% coverage.
- Frontend/API: OpenAPI drift, Prettier, ESLint, TypeScript, 39 tests in 9 files, and Vite build
  passed.
- Release/operations: Python lock check and 52 release tests passed; full-profile Compose rendered;
  Doctor passed with API/worker image-OCR equality and Alembic `20260815_0021`; shell syntax and
  `git diff --check` passed.
- Safety/drift: no Alembic, OpenAPI, generated frontend, dependency, credential-pattern, or
  adapter-output logging drift was found. No live provider, SSH, production, deployment, commit,
  push, enqueue, retry, resend, or WeCom action occurred.

Independent Phase 2.2 passes.

## Phase 3 release preparation and read-only production preflight

- Codeup `origin/main` resolves exactly to
  `bd6aa9d77b94a65c326e91b9932e3f83e7be6974`; its direct runtime parent is
  `4af7e9c201836d07a7e4a396b25ed2a0156f8694`. The final documentation commit has zero runtime
  diff from that parent. The repository release scanner checked 823 committed files without a
  secret-shaped-content finding.
- The allowlisted archive contains 307 regular files / 360 members with no symlink, forbidden
  path, private material, frontend, report, task artifact, or secret-shaped filename. Its SHA-256
  is `7ea27a52dd3a0812b669c487b69c4472b6f09a84dc3e83f2ff90fd836a5e9301`.
- The reviewed offline source-overlay build produced the developer-local immutable candidate
  `sha256:21828f4745ebd6b9586aceddb82067c8e72fef61f577823b111430e61f25290e`
  (132,069,740 bytes). Its protected transfer bundle is 131,274,201 bytes with SHA-256
  `bd91567ad5beda61a33fef576ad852e6ed869c7d74d6c0c52d1e174ed5c71b35`.
- Candidate labels bind the exact release commit, archive checksum, dependency-base image
  `sha256:50fd2519fbc5aa204c45e76cb685d01aaea1656b998d3ed96c9ab6671b3b9374`,
  and byte-identical target/base `pyproject.toml` SHA-256
  `d32d7b8c8dd90b2e455dbfbadde65e56e01ab2d7981f79e39358da8b5943cd0f`.
- All 165 in-image source hashes and the exact file set passed. Runtime ownership is `app:app`,
  default/executing user is non-root `app`, stale build/egg-info/site-packages application copies
  are absent, and `pip check`, application entrypoint imports, OCR model/limits, and the dedicated
  `/layout_parsing` route pass. Alembic is `20260815_0021`; runtime OpenAPI equals the committed
  document, with no migration/API/generated-client drift from the active release.
- Production remains on release
  `7d8a9142d3195ce5d0df8e62252a74d99229a1bc` and image
  `sha256:3ce0e573da86726ffb3ba59da7fa16b3e16903649ad6a62213944c698a7b2c64`.
  `IMAGE_DIVERSITY_ENABLED=false` and `IMAGE_OCR_ENABLED=false`; the effective OCR contract is
  `glm-ocr`, 10 MiB input, 1 MiB response, and 120 seconds.
- PostgreSQL, MinIO, API, all schedulers/workers, and the WeCom dispatcher are healthy/running as
  intended with restart count zero; `minio-init` and migration exited zero. All nine application/
  migration containers use the active image. Alembic remains `20260815_0021`, running work is
  zero, current-date nonterminal copy run/job counts are zero, and nonterminal/unknown WeCom is
  zero.
- Safe preflight counters are 34 acquisition runs, 179 evidence candidates, 34 governance runs,
  13 daily selections, two slot runs, 55 copy runs, 31 image artifacts, 31 material packages, and
  21 WeCom jobs. Seven historical queued copy jobs retain aggregate attempt count zero. WeCom is
  20 delivered / one failed, with zero duplicate request-fingerprint groups and the unchanged one
  historical duplicate content-fingerprint group. Diversity plan/similarity rows remain zero.
- The production environment remains mode 0600 with SHA-256
  `4ad88db853075ad8668a1c45bd2e1f4498256c2ece0903ab2fbe3ea40521efdc`; 256 private brand files
  retain manifest SHA-256 `dbf0d94b6bf8abbae88bf769f0f319365ccdd40ba0f028be6aae8dc8ef2f4290`
  and a read-only content-worker mount. Named PostgreSQL/MinIO volumes are unchanged. The host has
  62,344,840 KiB free and 95% free inodes on the relevant filesystem.
- Backup timer/root checks passed. The prior `20260815T062634Z` PostgreSQL, 630-object MinIO, brand,
  and code rollback artifacts all passed their stored SHA-256 manifests; 19 rollback image tags
  and six release backup directories remain available. A fresh Phase 4 backup is still mandatory
  after approval and quiescence.

## Phase 4 default-off production deployment

- The maintenance window used rollback ID `20260815T134516Z`. The dispatcher, content,
  governance, acquisition workers/schedulers, and API were stopped in dependency order. Only
  healthy PostgreSQL and MinIO remained running; durable running work and nonterminal WeCom were
  both zero before backup and activation.
- The fresh PostgreSQL custom dump is 9,446,528 bytes with SHA-256
  `58b44c20070eb53f0e1efe2d94ce4d3fa4c7418bec273ce61fd53753b7e30968`;
  its catalog was validated with container-local `pg_restore`. The 658-object MinIO mirror passed
  every manifest entry and has manifest SHA-256
  `90c4a9231175749307a24f7cf59095ec3ad72f92184fa4bb702a88ee1194ae45`.
- The fresh brand archive is 210,227,952 bytes with SHA-256
  `5184e5ef669bd85261dde402c90ff0520d17cfd606c34a14185a1cd0aef710e7`;
  the environment backup retains SHA-256
  `4ad88db853075ad8668a1c45bd2e1f4498256c2ece0903ab2fbe3ea40521efdc`.
  The previous code archive is 815,656 bytes with SHA-256
  `c6a09ff369a5ce44046c53d78e4b2145d9f02ee354c81671b987fa9db5d2367d`.
- Nine immutable service-specific rollback tags preserve the prior full image ID
  `sha256:3ce0e573da86726ffb3ba59da7fa16b3e16903649ad6a62213944c698a7b2c64`;
  their inventory SHA-256 is
  `8c2af5735193fc24ac4b7cb39bb52aa059e496579a7a58a34457c73739dba610`.
- The mode-0600 image/source artifacts matched their local checksums after key-auth transfer. The
  image loaded as exact ID
  `sha256:21828f4745ebd6b9586aceddb82067c8e72fef61f577823b111430e61f25290e`;
  remote labels, all 165 image-source hashes, exact file set, non-root runtime, imports, dependency
  health, OCR constants, and Alembic head passed before active retagging. The shared application
  tag and all nine service tags resolve to the candidate.
- The active overlay matches all 307 allowlisted release files. No frontend, task, report, private,
  `.env`, cache, build, or secret-shaped artifact entered the release. The canonical regular
  mode-0600 marker files now contain exact full/short values
  `bd6aa9d77b94a65c326e91b9932e3f83e7be6974` / `bd6aa9d`, and the candidate image revision matches
  the full value. `.env`, `.release.env`, private brand material, and both named volumes were
  preserved.
- `minio-init` and `backend-migrate` exited zero on the reviewed image with `--no-build`.
  Alembic remains `20260815_0021`, ten sources remain active, and seeding introduced no durable
  counter change.
- API/acquisition, governance, and content services were recreated in dependency order on the
  candidate and are running with restart count zero. Scheduler-only gates proved zero governance,
  content-slot, or current-date copy work before the provider-capable workers were started. The
  dispatcher was recreated on the candidate without starting it and remains stopped/restart-zero.
- Every safe durable counter remained at the predeployment snapshot: 34 acquisition runs, 179
  evidence candidates, 34 governance runs, 13 daily selections, two slot runs, 55 copy runs, 142
  copy attempts, 31 image artifacts with aggregate attempt count 40, 31 packages, 376 model
  invocations, 21 WeCom jobs, and 41 delivery attempts. Seven historical queued copy jobs retain
  aggregate attempt count zero; plan reservations and similarity attempts remain zero. Running
  work, current-date actionable copy, nonterminal/unknown WeCom, and duplicate WeCom request
  fingerprints are all zero.
- API and content-worker runtime settings both report diversity/OCR false with `glm-ocr`, 10 MiB,
  1 MiB, and 120 seconds. A bounded log scan found zero traceback, critical, delivery-unknown,
  OCR/provider-request, Comfly/Toapis, or WeCom-send markers. A final 30-second service/counter/
  protected-input sample was stable; its protected evidence SHA-256 is
  `f774fbbedf33680d165c2bfebf225bb119865ae239afbe5642348f5316c3695c`.
- The protected target artifacts are retained with the rollback set. The temporary transfer stage
  remains at the generated production path, mode 0700, with ten top-level evidence files mode
  0600; it is intentionally not cleaned before the separately authorized live gate.
- Operator compatibility corrections were fail-closed: `pg_restore` validation moved from the
  absent host binary to the PostgreSQL container, effective false flags were verified from rendered
  Compose/runtime defaults rather than requiring explicit `.env` lines, full image IDs were checked
  with inspect rather than truncated image-list output, and the stopped dispatcher used supported
  `compose up --no-start --no-deps` semantics. None caused a provider call, writer restart, or
  durable-state delta before its gate passed.

## Independent Phase 4 marker-reconciliation recheck

- Direct reads of the canonical `RELEASE_COMMIT` and `.release-commit` regular mode-0600 files
  returned exact short/full release values. The candidate image label returned the same full
  revision.
- API, acquisition, governance, and content services remain running on the exact candidate with
  restart count zero; PostgreSQL, MinIO, and API remain healthy. Migration/MinIO initialization
  remain exited-zero, and the candidate dispatcher remains stopped in created state with restart
  count zero.
- API and content worker remain equal and default-off for diversity/OCR, with `glm-ocr`, 10 MiB,
  1 MiB, 120 seconds, and the separate `glm-5.2` chat model.
- Durable counts remain at the Phase 4 snapshot: Alembic `20260815_0021`, ten active sources,
  34 acquisition runs, 179 candidates, 34 governance runs, 13 daily selections, two slot runs,
  55 copy runs, 142 copy attempts, 31 images / 40 aggregate attempts, 31 packages, 376 model
  invocations, 21 WeCom jobs, and 41 delivery attempts. Running work, current-date actionable copy,
  nonterminal/unknown WeCom, diversity reservations, and similarity attempts are zero. Seven
  historical queued copy jobs retain aggregate attempt count zero. Provider/delivery counters were
  unchanged across a 15-second sample.
- The protected stage remains mode 0700 with ten mode-0600 top-level evidence files. The source and
  image-transfer hashes remain `7ea27a52dd3a0812b669c487b69c4472b6f09a84dc3e83f2ff90fd836a5e9301`
  and `bd91567ad5beda61a33fef576ad852e6ed869c7d74d6c0c52d1e174ed5c71b35`. Fresh read-only checks
  also reconfirmed the rollback PostgreSQL dump, brand archive, and 658-object MinIO manifest
  hashes recorded above.
- A 200-line-per-service bounded scan found zero severe, delivery-unknown, provider-request,
  Comfly/Toapis, or WeCom-send events. One `zhipu` occurrence is the allowlisted
  `governance_worker_started` configuration field, not a provider request; durable counters prove
  no corresponding invocation delta.

### Post-deployment short-marker reconciliation

- An independent audit reported the short marker as stale. A canonical read-only resolution before
  the authorized reconciliation found `/opt/edu-ai-lead-agent/RELEASE_COMMIT` already resolving to
  itself as a regular mode-0600 `ubuntu:ubuntu` file containing exactly `bd6aa9d\n` (8 bytes). The
  full marker simultaneously contained exactly
  `bd6aa9d77b94a65c326e91b9932e3f83e7be6974\n` (41 bytes).
- The authorized same-directory atomic replacement rewrote only the short marker with the reviewed
  value, retaining the canonical path, owner, group, and mode. Its resulting SHA-256 is
  `310ac235acbd17d8fbcb365cc74ab605ef93cf960c0d4580af3c2bb524e55808`.
  The full marker hash, `.env`, `.release.env`, brand manifest, services, images, data, counters,
  and temporary stage were unchanged.
- The stale condition was not reproducible at the canonical path, so no unsupported production-side
  race or mutation is asserted. The root cause of the earlier evidence claim was insufficient
  evidence attribution: it promoted equality assertions embedded in a composite deployment gate
  without separately recording the marker's resolved canonical path, file type, byte length, and
  checksum. That made the claim impossible to distinguish from an audit of a stale snapshot or
  reference. The reconciliation closes that evidence gap with direct before/after canonical reads.
- A fresh 30-second read-only sample retained all nine candidate application/migration containers
  at restart zero, the dispatcher stopped, flags false, Alembic `20260815_0021`, and counter snapshot
  `34:179:34:13:2:55:142:31:40:31:376:21:41:0:0`. Running work, current-date actionable copy,
  nonterminal WeCom, provider/delivery deltas, and bounded log findings remained zero; protected
  inputs and the temporary stage were unchanged.

## Phase 5 deterministic OCR fixture gate

- The immediate pre-call gate passed against canonical release `bd6aa9d` and candidate image
  `sha256:21828f4745ebd6b9586aceddb82067c8e72fef61f577823b111430e61f25290e`.
  API and content worker were running at restart zero; the dispatcher was created/stopped at
  restart zero. Both runtime services retained diversity/OCR false, `glm-ocr` remained separate
  from `glm-5.2`, and the OCR envelope remained 10 MiB input, 1 MiB response, and 120 seconds.
- Running, current-date actionable, and nonterminal/unknown WeCom queues were all zero. Seven
  historical queued copy jobs retained aggregate attempt count zero. The durable counter snapshot
  was exactly `34:179:34:13:2:55:142:31:40:31:376:21:41:0:0`, with zero duplicate WeCom request
  fingerprint groups.
- A generated mode-0700 local directory held one deterministic mode-0600 1024×1024 PNG rendered
  with the installed Noto Sans CJK SC font and exactly the three approved lines. The fixture was
  36,064 bytes with SHA-256
  `247e0d6da2efc2e451a5287e9ed671fc68c5fa906dbe632fcf57cd1ee7b5dff6`. Its PNG signature,
  dimensions, line count, local mode and byte identity were checked before and after transfer into
  one generated mode-0700 child of the protected production stage.
- Main review authorized the paid boundary with provider attempts still zero. The deployed
  `ZhipuImageTextRecognizer` then used `layout_parsing`, provider `zhipu`, model `glm-ocr`,
  `image_ocr_enabled=True`, and `AI_MAX_ATTEMPTS=1`. Exactly one HTTP provider attempt occurred.
  It returned the typed terminal result `invalid_provider_output`; recognized line count was not
  accepted and exact ordered validation was false. No finer allowlisted issue-code tuple or safe
  stage classification was captured, so that detail is unavailable and was not reconstructed.
  No response body, unexpected recognized text, request payload, Base64, credential, prompt,
  private path, or row/object identifier was printed or persisted.
- No retry or second OCR call occurred. No Comfly/image-generation, database or MinIO write,
  acceptance database/bucket, scheduler/service restart, environment edit, enqueue, resend,
  WeCom action, real-news acceptance, or activation occurred.
- The exact local and protected-stage fixture files and their generated child directories were
  deleted and confirmed absent. The protected stage returned to its ten original top-level files.
  The post-call gate retained all candidate services at restart zero, the dispatcher stopped,
  both flags false, queues `0:0:0`, the exact durable counter snapshot above, WeCom state
  `0 nonterminal / 20 delivered / 1 failed / 41 attempts / 0 unknown`, and zero delivery request
  fingerprint duplicates.

The deterministic OCR fixture gate fails. Per the stop-on-first-failure contract, later Phase 5
acceptance and Phase 6 activation remain prohibited in this run.

### Fail-closed service recovery

- Before recovery, both visual flags were false; all candidate application services were at
  restart zero; running/actionable work and nonterminal/unknown WeCom were zero. The exact
  post-fixture durable snapshot was
  `34:179:34:13:2:55:142:31:40:31:376:21:41:0:0`; WeCom remained 20 delivered / one failed across
  21 jobs and 41 attempts, with zero duplicate request fingerprints and the unchanged one
  historical duplicate content fingerprint.
- The already-created candidate dispatcher was started directly without Compose recreation,
  environment/data edits, enqueue, retry, resend, or any provider call. After more than two
  two-second poll intervals and a further 30-second sample, it was running on the exact candidate
  with restart count zero. WeCom job, attempt, status, duplicate, and provider-send deltas were
  all zero; model invocation, copy-attempt, and image-attempt totals also remained unchanged.
- All eight long-running application services were running on the candidate with restart count
  zero; migration remained exited-zero on the candidate, and PostgreSQL/MinIO were healthy at
  restart zero. Both flags remained false, the full/short markers remained exact, all actionable
  families remained zero, and bounded severe/secret/unknown log findings were zero. The final
  service snapshot SHA-256 is
  `4de9cddbdf5efdf9fbca7311b0be0913adf87601f5ef059e7080b3d7ec6b5273`.
- The verified rollback set and protected transfer stage were retained for diagnosis. No new
  fixture, acceptance database/bucket, Zhipu/Comfly call, service recreation, image/data change,
  or cleanup beyond the already-confirmed fixture removal occurred during recovery.

## Phase 2.1 official response-envelope correction

- Official contract review established four deterministic mismatches in the deployed image parser:
  it expected flat `layout_details` instead of pages-to-elements `object[][]`, treated the official
  `data_info.pages` array as an integer page-count alias, rejected documented element
  `height`/`width`, and rejected populated non-text `image` elements.
- The repository parser now validates typed `data_info.num_pages == 1`, an optional but
  exactly-one-page positive-dimension `pages` array, exactly one nested layout page, bounded paired
  element dimensions consistent with page metadata, unique indices, labels, boxes and content.
  It flattens only the sole page, projects only `text`, ignores bounded `image` content, and rejects
  unsupported `table`/`formula` before similarity or storage.
- Content-free issue codes now distinguish response-envelope, page-metadata, layout, and
  unsupported-layout failures while the external error remains `invalid_provider_output`. No raw
  body, provider content/URL, Base64, credentials, prompts, object keys, paths, hashes, or bytes are
  logged or persisted.
- Contract fixtures now use the official nested layout shape with page and element dimensions and
  cover flat/multi-page responses, conflicting metadata, malformed dimensions/elements, ignored
  image content, rejected table/formula, exact text ordering, and safe error output. The legacy
  brand/PDF OCR implementation is unchanged.
- Final local-only Phase 2.1 gate: 99 provider/factory/material/image-validation tests passed,
  including 56 image-OCR contract cases and the unchanged legacy brand/PDF OCR suite. Project Ruff
  format/lint passed across 247 files and strict mypy passed across 147 source files.
- This local implementation checkpoint made no live provider call and did not use SSH, production,
  deployment, MinIO, Comfly, enqueue/retry/resend, or WeCom. Production flags and services were
  not read or changed during that checkpoint; the later reviewed redeployment is recorded below.

## Phase 2.1 release preparation and default-off redeployment

- Codeup `origin/main` resolved exactly to
  `331a4942a84b36811cbbc4abff68bca2abc71f0c`. The 823-file committed-source secret scan passed.
  The retained 307-path source allowlist produced 307 regular files / 360 archive members without
  a symlink, forbidden/private/frontend/task/report path, or secret-shaped filename. Its 818,067
  byte archive SHA-256 is
  `ea13c86df5bea0cf9f860007708d66f115cc7afb401966d4b79741772bf51f1e`;
  only the reviewed two runtime and two test files changed from the prior release archive.
- The offline source-overlay build reused the unchanged dependency base
  `sha256:50fd2519fbc5aa204c45e76cb685d01aaea1656b998d3ed96c9ab6671b3b9374`
  and produced exact candidate
  `sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`.
  Its 131,266,546 byte transfer bundle SHA-256 is
  `7cb547773f9bb445fe635934d4447e6afcf7d5fd6cd2a2f296f390baecc58f63`.
  Revision/source/base/pyproject labels, non-root `app:app` runtime, all 165 in-image source hashes,
  exact file set, imports, `pip check`, OCR constants/route/parser behavior, Alembic `0021`, and the
  byte-identical committed/runtime OpenAPI SHA-256
  `003936b19e998f4e96865845531108535664947272e2b04d2fb83d95b9cab950` passed.
- Strict production preflight found the previous candidate healthy on all eight long-running
  services at restart zero, both visual flags false, Alembic `20260815_0021`, ten active sources,
  zero running/actionable/provider/delivery work, and the exact durable vector
  `34:179:34:13:2:55:142:31:40:31:376:21:41:0:0`. Seven historical queued copy jobs retained
  aggregate attempt count zero; WeCom remained 20 delivered / one failed across 21 jobs and 41
  attempts, with zero nonterminal/unknown or duplicate request fingerprints.
- The first quiesced invocation of the standard backup wrapper rejected the deliberately local
  offline `APP_IMAGE` tag because it accepts only a registry digest. Its fail-closed restoration
  returned every old service to the exact prior image/restart-zero state with all counters stable.
  The reviewed manual offline backup path was then used after a fresh dependency-ordered quiesce.
- Fresh rollback ID `20260815T153208Z` contains a 9,446,535 byte PostgreSQL custom dump with
  SHA-256 `30113ffc19c1a14c6998e8896b32fbc72de769684b9b27a0fd7a1cdaa03d3c72`
  and a container-local `pg_restore --list` pass; a verified 658-object MinIO manifest with
  SHA-256 `90c4a9231175749307a24f7cf59095ec3ad72f92184fa4bb702a88ee1194ae45`;
  brand archive SHA-256
  `5184e5ef669bd85261dde402c90ff0520d17cfd606c34a14185a1cd0aef710e7`;
  environment SHA-256
  `4ad88db853075ad8668a1c45bd2e1f4498256c2ece0903ab2fbe3ea40521efdc`;
  code archive SHA-256
  `9bab86056d3e446670f8bdbe0efbfde4d2d288c7ac9209ef5a3b9ed1f1daeeab`;
  and nine immutable prior-image rollback tags whose inventory SHA-256 is
  `73c6f8aa39371e84baee1c13d7be3af4b8349df9b5a69d9fe926aabdab6485da`.
- The mode-0600 image/source artifacts matched their local hashes after transfer. Remote load,
  label/runtime/source verification passed before the shared and all nine service tags were
  moved to the exact candidate. The active overlay matched all 307 allowlisted files; `.env`,
  `.release.env`, private brand inputs, named PostgreSQL/MinIO volumes, frontend, and unrelated
  workspace artifacts were preserved. Canonical mode-0600 marker files now contain exact full/
  short values `331a4942a84b36811cbbc4abff68bca2abc71f0c` / `331a494`.
- `minio-init` and `backend-migrate` exited zero without a build; Alembic remained
  `20260815_0021` and seeding changed no durable counter. API/acquisition, governance, and content
  were restored in dependency order with both flags false. The dispatcher was recreated last on
  the exact candidate only after nonterminal/unknown WeCom and all running work remained zero.
- Two operator-only probe corrections failed closed without production drift. A composite remote
  script was delivered on standard input and its `compose up` subprocess consumed the remaining
  probe text after successfully recreating the dispatcher; the missing evidence was not promoted
  to a pass. A later string assertion expected timeout `120` while runtime Settings represented the
  same numeric value as `120.0`; its trap stopped the dispatcher. After direct bounded diagnosis,
  the corrected numeric gate was rerun in full. Starting the already verified dispatcher through
  Compose also idempotently reran its declared `minio-init`/migration dependencies; both exited
  zero again with no schema, source, durable, provider, or delivery delta.
- The final 35-second sample retained all eight long-running services on the exact candidate at
  restart zero; API, PostgreSQL, and MinIO were healthy, and both one-shots were exited-zero.
  API/content Settings were equal at `false:false:glm-ocr:10485760:1048576:120.0`; markers,
  Alembic, ten sources, the exact durable vector, historical queued `7:0`, WeCom status, and all
  running/actionable counts remained unchanged. The 256-file protected brand aggregate retained
  SHA-256 `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24`.
  Bounded severe/unknown/secret/provider-send log counts were `0:0:0:0`. Protected final evidence
  and service-matrix SHA-256 values are
  `e28defaba3de84946fa2bd0d96a52edefbf864cf22cf88f38ed2ff91a4da5211` and
  `0e4abf38032d7e43c37ada23d4d7fc64ee1ef1be3e5a140e026eb0bf12b1d654`;
  the mode-0700 transfer stage and rollback artifacts remain retained.
- No Zhipu, Comfly, image-generation, or WeCom provider call occurred during this redeployment. No
  fixture, acceptance database/bucket, enqueue, retry, resend, activation, frontend deployment,
  production build, commit, or push occurred.

## Corrected Phase 5 deterministic OCR fixture gate

- The immediate gate reconfirmed canonical full/short release markers, the exact immutable
  candidate, all eight restart-zero application services, API/content runtime equality, false
  diversity/OCR flags, `glm-ocr`, the 10 MiB/1 MiB/120-second envelope, separate `glm-5.2` text
  routing, disabled quality audit, Alembic `20260815_0021`, and ten active sources.
- Ordinary 2026-08-16 scheduling had advanced the durable vector from the deployment snapshot to
  `35:179:35:13:3:58:154:34:43:34:382:24:47:0:0`. The delta was fully attributed to one terminal
  acquisition run, one terminal governance run, one succeeded content-slot run, and three accepted
  copy / succeeded image / package / delivered WeCom paths. The vector was stable before isolation;
  running/current-date actionable, nonterminal/unknown WeCom, unknown attempts, duplicate request
  fingerprints, and diversity rows were zero, while the seven historical queued copy jobs retained
  aggregate attempt count zero.
- Three schedulers and the dispatcher were stopped before the paid boundary. A first wrapper
  correction failed before child creation because `timeout` cannot directly execute a shell
  function. A network-disabled candidate probe then established that the immutable application
  image contains no font files, so in-container rendering also failed before adapter construction.
  Both paths had provider-attempt count zero, removed their exact child resources, and passed
  unchanged flag/vector/queue/log recovery gates. The first recovery used Compose start and
  idempotently reran its declared MinIO-init/migration dependencies; both remained exited-zero with
  no schema, source, durable, provider, or delivery delta. Final isolation/recovery used direct
  exact-container stop/start instead.
- The corrected fixture was rendered locally with the trusted root-owned, non-writable Noto Sans
  CJK font and exactly `赛先生科学`, `人工智能`, and `理解智能如何学习与反馈`. It was deterministic,
  mode 0600, 1024×1024 RGB PNG, 39,931 bytes, and had SHA-256
  `05c2f259d6f14731f8b1cf2026efb3b490a599890409828e2199beaf195ce512`; the font SHA-256 was
  `b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a`. PNG signature/chunks,
  absence of text metadata, bounds, deterministic byte identity, remote byte identity, protected
  modes, and deployed non-root user readability passed before HTTP.
- The deployed factory returned `ZhipuImageTextRecognizer` using `layout_parsing`, provider
  `zhipu`, model `glm-ocr`, one-off OCR true, `AI_MAX_ATTEMPTS=1`, and an explicit HTTP transport
  with SDK retries zero. Exactly one provider HTTP attempt occurred. The safe terminal projection
  was `invalid_provider_output`, `exact_ordered=false`, accepted line count zero, parser issue
  `image_ocr_layout_invalid`, and no quality issue codes. No response body, Base64, credential,
  unexpected recognized text, provider URL/content, private path, image content, prompt, object
  key, or provider request identifier was printed or persisted.
- No second OCR call or retry occurred. No Comfly/image-generation, real-news pipeline, database or
  MinIO acceptance, enqueue/retry/resend, WeCom action, environment edit, acceptance DB/bucket, or
  activation occurred. The exact local/remote fixture copies and child container were deleted and
  proved absent.
- Only the three previously running schedulers were started directly, followed by the dispatcher
  last. The final 30-second gate retained all eight services on the candidate at restart zero,
  flags `false:false`, the current durable vector, queue/unknown gate `0:0:0:0`, and zero bounded
  severe/provider-send log findings.

## Phase 2.2 raw MaaS compatibility correction — offline only

- Pinned official-source review found that the second live code `image_ocr_layout_invalid` could
  not discriminate zero-based index, raw pixel bbox, optional fields, label drift, or malformed
  content. No private response was available, so the correction does not assert which hypothesis
  occurred. The Bayesian record assigns high confidence to accepting both zero-/one-origin index
  values and official raw pixel normalization, while leaving the actual live cause undetermined.
- The direct adapter remains a raw MaaS decoder only: exact model identity, `layout_details`,
  `data_info.num_pages == 1`, and one nested page stay mandatory. It does not add an SDK
  `json_result` fallback or infer envelope type from coordinate magnitude.
- Unique bounded indices now accept zero and gaps without relying on base. Text bboxes accept the
  documented unit form or raw pixels only with positive deterministic page axes and x/y range
  checks. Scale is selected once per text page, so a tiny pixel bbox whose coordinates happen to
  be at most one cannot be mixed with ordinary pixel boxes and change geometric ordering. When
  all text coordinates are at most one, unit/pixel interpretations preserve the same order under
  positive axis scaling. `data_info.pages` is authoritative; independently optional bounded
  element page axes are used only as an unambiguous fallback. An unexplained scale remains
  terminal.
- The raw semantic allowlist stays `text/image/table/formula`: only text is projected, image
  content/bbox is optional and ignored, table/formula have distinct terminal codes, and unknown
  labels fail closed. Bounded outer/data/page extensions are discarded at the private response
  boundary, but raw elements accept only the six official keys so an alternate semantic field
  cannot be silently hidden. Raw success mixed with `json_result`/`error`, a non-raw-only
  envelope, an unknown element key, and a conflicting compatibility `page_count` alias all fail
  with content-free codes. Extension values are never logged, projected, or persisted; the
  response remains capped at 1 MiB.
- Safe terminal subcodes now distinguish response/source/schema, page count,
  dimensions/conflict, index/duplicate, label, bbox shape/scale/range, content type/limit, element
  extra, line limit, table, and formula.
  Material tests prove every parser class, including a mixed parser/text tuple, bypasses quality
  repair and stops before similarity and storage. The application routing code required no change
  because its exact-text allowlist already implements that invariant.
- Offline mocked tests cover the official docs unit shape, the pinned official 2040x2640 full-page
  MaaS pixel fixture, page-level small-pixel scale selection, zero-/one-origin and non-contiguous
  indices, independently optional dimensions, extension-field privacy, source/page-count
  conflicts, page-authoritative and element-fallback dimensions, missing/conflicting scale,
  unknown labels, malformed indices/bboxes/content, unsupported structures, and the unchanged
  exact-text gate. The focused image OCR, legacy PDF OCR, factory/config, image-generation, and
  material suite passed all 237 collected tests. Affected strict mypy passed.
- Full-project Ruff format-check passed for 247 files and lint passed. Explicit-config,
  no-incremental strict mypy passed for all 141 backend application sources, but the requested
  147-source repository gate remains red on one pre-existing, untouched ownership-external issue:
  `scripts/annotate_brand_visual_assets.py:153` returns `Any` from `str | None`. The ordinary
  `make backend-typecheck` command reports green because its repository-root invocation does not
  discover `backend/pyproject.toml`; the explicit `--config-file backend/pyproject.toml` run exposes
  the baseline finding. This iteration did not edit that unrelated script or the Makefile. Per
  scope, no full backend pytest was run.
- Design drift from the research recommendation was deliberate and recorded: no SDK-normalized
  decoder was added for this fixed raw endpoint; text still requires usable geometry instead of an
  index-only ordering fallback; bounded outer transport extensions are ignored, while unknown raw
  element keys and normalized/error source conflicts are rejected because they can change or
  obscure exact-text semantics. No Alembic, OpenAPI, public API, Settings, factory, legacy PDF OCR,
  or durable schema change was required.
- This checkpoint performed no live/provider call, SSH, production read/write, deployment, image
  generation, MinIO, database, enqueue/retry/resend, or WeCom action. It does not authorize a new
  fixture or activation; production state was not accessed.

## Phase 2.2 default-off release attempt — failed closed before overlay

- Codeup `origin/main` was re-fetched and resolved exactly to
  `c66aa6217d137033118c552f3db11b2a1121d082`. The committed-source scan covered 824 files without
  a secret-shaped finding. The retained allowlist produced 307 regular files / 360 archive members,
  with only `backend/app/infrastructure/ai/zhipu.py` and its two reviewed test files changing from
  the prior runtime archive. The 821,122-byte source archive SHA-256 is
  `e516184eebdeb9b98c09cc3fecd98369012d75aba5763fdb16ed836b2d3390f9`.
- The network-disabled source-overlay build reused exact dependency base
  `sha256:50fd2519fbc5aa204c45e76cb685d01aaea1656b998d3ed96c9ab6671b3b9374`
  and produced candidate
  `sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2`
  (132,064,594 bytes). Revision/source/base/pyproject labels, non-root `app:app` runtime, all 165
  source hashes and exact file set, absence of stale application copies, imports, `pip check`, the
  dedicated OCR route, unit and 2040-by-2640 pixel bbox projection, zero/gapped indices, OpenAPI
  SHA-256 `003936b19e998f4e96865845531108535664947272e2b04d2fb83d95b9cab950`,
  and Alembic `20260815_0021` all passed offline. The 131,268,412-byte image bundle SHA-256 is
  `db1cab9cc975e08d46aa0d47e35f81100d02ea0eb5df90ce8677cc23378119c4`.
- Strict read-only preflight found all eight prior-candidate services running at restart zero,
  PostgreSQL/MinIO healthy, both visual flags false, `glm-ocr` isolated from `glm-5.2`, timeout
  rendered as `120.0`, and exact prior release/image
  `331a4942a84b36811cbbc4abff68bca2abc71f0c` /
  `sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`.
  The current 2026-08-16 ordinary automation baseline was stable for 15 seconds at
  `35:179:35:13:3:58:154:34:43:34:382:24:47:0:0`; current-day acquisition/slot/copy run counts
  were `1:1:3`. Running/current-date actionable work, nonterminal/unknown WeCom, duplicate request
  fingerprints, diversity reservations and similarity attempts were zero. Seven historical queued
  copy jobs retained aggregate attempt count zero; WeCom remained 23 delivered / one failed across
  24 jobs and 47 attempts, with the unchanged one historical duplicate content fingerprint.
- Production env/release-env SHA-256 values remained
  `4ad88db853075ad8668a1c45bd2e1f4498256c2ece0903ab2fbe3ea40521efdc` /
  `5b58077644a21764cc3521c6689d562c645c62f0fff117c07264f7285398e0c2`.
  The 256-file brand aggregate remained
  `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24`;
  named volumes, backup timer, 61,419,168 KiB free space, 95% free inodes, and prior rollback
  checksums passed. Bounded preflight log/provider counts were `0:0:0:0`.
- A first quiesced backup attempt created a valid 9,726,989-byte PostgreSQL dump but invoked the
  container-local catalog checker without interactive stdin. `pg_restore` therefore read EOF and
  the attempt failed closed before MinIO/brand/image backup or transfer. Direct prior-container
  restoration passed with unchanged durable/WeCom state. The incomplete `20260816T021431Z`
  directory remains retained and is not an approved rollback set.
- Fresh rollback ID `20260816T021614Z` passed catalog and checksum verification: PostgreSQL SHA-256
  `1363341cac636e0dfa00900ab66df6cfcba6de1a48bca6a7b61821f82f2f3a29`, 685-object MinIO manifest
  SHA-256 `1ea27f1ced8056ec39437665cf717a83dd3f59ff2323caeb67be15e56459a3bc`,
  brand archive SHA-256
  `5184e5ef669bd85261dde402c90ff0520d17cfd606c34a14185a1cd0aef710e7`,
  active-code archive SHA-256
  `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`,
  and nine prior-image tags with inventory SHA-256
  `ad0d88b71a39a8f9afeaa6c0d0911f4e49d00e4bae71532051f301f8ff7886a7`.
- The protected nine-file transfer stage matched the local image/source checksums. Remote image
  load and provenance checks began while only infrastructure was running, but the no-network import
  assertion rebound the imported FastAPI `app` name to the Python package before calling
  `openapi()`. It failed locally inside the candidate without contacting any provider and before
  active retag, source overlay, marker, one-shot, migration, environment, or data mutation.
- The trap restored every prior service tag. Its service-start branch used relative Compose paths
  after changing into the protected stage and therefore could not start the stopped containers.
  Recovery then directly started only the existing prior containers in dependency order, with the
  dispatcher last. A final 30-second gate retained all eight services on exact prior image at
  restart zero, prior source/markers/env/release-env, flags false, the durable/WeCom baselines above,
  zero actionable work, and bounded severe/unknown/secret/provider-send counts `0:0:0:0`. The
  protected recovery evidence SHA-256 is
  `bb5dbd36206b0da14b62381962eccdb31c46bf543557b06483d7ce04f9ccd208`.
- No Zhipu, Comfly, image-generation, or WeCom provider call occurred. No fixture, acceptance
  database/bucket, enqueue, retry, resend, activation, frontend deploy, production source/marker/
  migration change, commit, or push occurred. The candidate image, transfer stage, valid rollback
  set, incomplete first backup and safe failure evidence remain retained.
- The corrected offline import probe avoids rebinding the FastAPI object:
  `from app.api_main import app as api_app`, followed by named `app.*` module imports and
  `api_app.openapi()`. It passed locally against the exact candidate with network disabled, a
  read-only root filesystem, all capabilities dropped and `no-new-privileges`; the image ID remained
  exact.
- A subsequent production read-only audit did not run the candidate. It confirmed the candidate is
  merely loaded, every active/shared service tag and all eight running restart-zero containers still
  resolve to `aec802...`, the transfer source/image hashes remain
  `e516184eebdeb9b98c09cc3fecd98369012d75aba5763fdb16ed836b2d3390f9` /
  `db1cab9cc975e08d46aa0d47e35f81100d02ea0eb5df90ce8677cc23378119c4`,
  and the valid rollback/protected/recovery hashes still verify. Durable vector, WeCom vector and
  actionable work remained exactly
  `35:179:35:13:3:58:154:34:43:34:382:24:47:0:0`, `24:47:0:0:0:1`, and `0:0:0:0:0:0`.
- The protected candidate stage may be reused only after its full artifact manifest and loaded
  image identity are rechecked. The `20260816T021614Z` rollback set is valid for the exact state at
  the read-only audit, but it is not a fresh rollback point after writers resumed. A future retry
  must repeat the strict preflight and take a new backup after quiescence; `20260816T021614Z` cannot
  be substituted by an equality-only reuse approval.

## Offline-only operator-driver hardening

- Added the exact mode-0600 release driver
  `research/default-off-release-driver.sh`, SHA-256
  `29ee24ae9f7a8ccb9a845c7bd473d1b175a70180c6dc5f4e2652065346641a9b`. It requires absolute
  `/opt/edu-ai-lead-agent` Compose/project/env context, exact absolute stage invocation with
  `/dev/null` stdin, a ten-member mode-protected stage and self/archive/image/source hashes. It
  rejects drift before quiescence.
- The fresh backup lock is acquired before the first stop and held to completion/recovery. Fresh
  generated backup/tag collisions fail closed. PostgreSQL uses a noninteractive dump and the one
  intentional `docker exec -i ... pg_restore --list <dump` catalog stream; MinIO, brand, protected
  env, release env, exact prior source/markers, nine rollback tags and their manifests must all pass
  before `backup_ready=1`.
- `backup_ready`, `tags_changed`, `overlay_changed`, and `completed` are explicit phase flags set
  before their associated risk boundary. `ERR`, nonzero `EXIT`, `HUP`, `INT`, and `TERM` use one
  recursion-disabled recovery path. Pre-backup failure consumes no partial backup; mid/late recovery
  restores only changed layers and then starts captured prior services API-first, schedulers/workers
  behind zero-work gates, and WeCom dispatcher last.
- The candidate gate runs before retag with exact revision/base/pyproject/embedded-source labels,
  source manifest/count, non-root/read-only/no-network probes, `pip check`, corrected
  `from app.api_main import app as api_app` imports, `/layout_parsing`, OpenAPI, and Alembic checks.
  Runtime gates require exact default-off `false:false:glm-ocr:10485760:1048576:120.0` equality,
  the pinned 2026-08-16 durable/WeCom/historical baseline, zero current actionable/running/unknown/
  duplicate work, an operator-reviewed scheduler-safe window, exact protected inputs/tags/markers,
  secret-safe logs, dependency ordering, dispatcher last and final 30-second stability. There is no
  build, fixture, provider call, flag enablement, enqueue, retry, or resend path.
- The mode-0600 harness `research/test-default-off-release-driver.sh`, SHA-256
  `54620cfba8207f1968b9328ac2d96414ca03a820d45def939a81cb5b2ffb6283`, passed `bash -n`, static
  gates, injected early/mid/late failures, TERM and incomplete recovery. Orders were `services`,
  `tags -> services`, and `overlay -> tags -> services`; TERM returned 143 and an incomplete restore
  returned fail-closed 125. ShellCheck was unavailable. No SSH, production, Docker service,
  provider, or durable-state access occurred during this offline hardening, and no retry is
  authorized by these artifacts alone.

## Remaining work

- Use the corrected import alias and the absolute-path/no-stdin command contract recorded in
  `implement.md`. A retry is blocked until the exact generated operator script and its phase-aware
  `ERR`/`EXIT`/signal recovery branches pass independent review and a new quiesced backup is planned.
  This run is stopped and does not permit another transfer/load/overlay attempt.
- Production remains on `331a494` / `aec802...`, both visual flags remain false, and the dispatcher
  is running as the final dependency-ordered fail-closed restoration step. Paid OCR, isolated-news/
  Comfly acceptance and activation remain prohibited without separate authorization.

## Authorized default-off retry preflight — fail-closed before transfer

The newly authorized single retry did not reach the transfer or driver boundary. A fresh read-only
audit confirmed the exact candidate source/image archives, inactive candidate ID and provenance,
prior active source/markers/image, eight restart-zero services, false flags, protected inputs,
named volumes, migration/source state, timer/capacity and bounded safe logs. The protected stage
remained its original nine pre-driver members; reviewed driver SHA-256
`2190df29f7bbe59c903cd33237eae4068af633fd33c5010e2d2e890b3b0ecbfd` was not copied or invoked.

The 15-second stable business baseline had advanced through ordinary automation to
`36:182:36:13:4:59:157:35:44:35:391:25:47:0:0`, current-day `2:2:4`, provider/delivery tuple
`391:47:35:44`, and historical queued `7:0`. Running and unknown work were zero, but actionable
work was `0:0:0:0:0:1` and WeCom was `25:47:1:0:0:1`: one formal attempt-zero delivery was queued
for 12:30 China time. This alone fails the driver's non-weakenable zero-actionable precondition.

The read-only tag audit also found that production's nine retained per-service tags use `:latest`,
whereas the exact reviewed driver requires and mutates nine `:local` service tags. Those `:local`
tags do not exist; only the shared Compose tag `edu-ai-lead-agent-backend:local` does. Because the
authorized driver checksum is immutable and hand-created compatibility tags are outside the
reviewed procedure, execution stopped without improvisation. No fresh backup or release evidence
hash exists for this non-attempt, and the earlier `20260816T021614Z` rollback remains evidence only.

There was no Zhipu, Comfly, image-generation, OCR-fixture, or WeCom call caused by this preflight,
and no driver transfer, service stop, backup lock, backup, tag/source/marker/environment/data edit,
one-shot, enqueue, retry, resend, activation, or feature enablement. Production remains on exact
`331a4942a84b36811cbbc4abff68bca2abc71f0c` /
`sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`
with both visual flags false.

## Offline correction for the exact mixed tag contract

The retained driver was corrected locally after the blocked preflight. Its tag model now preserves
the one shared `edu-ai-lead-agent-backend:local` tag and the nine exact
`edu-ai-lead-agent-<service>:latest` tags, while requiring every service-specific `:local` tag to be
absent. The same explicit arrays/functions are used by active-tag validation, the new protected
ten-entry prior-tag inventory, nine fresh rollback tags, candidate retagging, rollback retagging,
mid/late recovery and final identity checks. The isolated bundle RepoTag validation and pre-load
`tags_changed=1` arming remain intact. The candidate-tag input gate also rejects the shared active
tag, every service `:latest` tag, and every forbidden service `:local` tag before image loading.

The revised mode-0600 driver is SHA-256
`29ee24ae9f7a8ccb9a845c7bd473d1b175a70180c6dc5f4e2652065346641a9b`; the revised mode-0600
fake harness is SHA-256 `54620cfba8207f1968b9328ac2d96414ca03a820d45def939a81cb5b2ffb6283`.
The harness passed static, signal/EXIT, lock-lifetime, bundle-arming, unsafe-manifest, mixed-tag,
candidate-retag and exact mid/late old-ID recovery cases. This does not clear the separate live
preflight blocker: the ordinary formal noon delivery was still queued/actionable in the last
read-only evidence. No new authorization is inferred, and this correction performed no SSH,
production, Docker-service, provider, transfer, quiesce, backup, retag, overlay, enqueue, retry,
resend, delivery, or feature-enable action.
