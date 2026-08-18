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

## Authorized default-off retry — exit 1 with exact recovery

The exact reviewed driver was invoked once after a fresh zero-work baseline. It quiesced all eight
application services and completed protected rollback `20260816T044848Z-zhipu-ocr-default-off`.
Its protected manifest SHA-256 is
`179c004951e911e5c435df92aa299608f1f488199ef397bca3e9d7df52d9371f`; PostgreSQL dump SHA-256 is
`c14ea603766ca1467b5c1e9602d99baf63fef13699230f47b451848927f23d66`; the 708-file MinIO
manifest is `704a6937016a07c2fe843611afb3088efe85fa96d6b3bc5cabe391e385f2f4a8`; brand/code archive
SHA-256 values are `4fb13a0ca7698adbd946a444a0bea8c18390c6397d6b6a33cbb6168034efe4dc` /
`797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`; active-tag/rollback-image
inventory SHA-256 values are `aeb0397afd7771fc2d17e766b42a693910545be98f73072c9b47f566a765ed1a` /
`af320587843168bc565a6a3451aa3da9cde988dfb9b0866fc52183e64685bbc1`.

Before image loading, bundle validation found OCI Config path
`blobs/sha256/695d4b23d5cfa5a09ac156f9308b23d3e7615b342a00aad19c619bc62f30db0a`
instead of the assumed `<candidate-image-id>.json` and failed as `image bundle config digest
mismatch`. State was `backup_ready=1`, `tags_changed=0`, `overlay_changed=0`, so no candidate load,
active retag, source/marker overlay, one-shot or migration occurred. The reviewed recovery completed
and the driver exited 1.

Independent verification retained exact prior commit/image, prior source and markers, all eight
restart-zero services, healthy infrastructure, exact active/forbidden tag contract, inactive
candidate, false flags, safe logs, durable vector
`36:182:36:13:4:59:157:35:44:35:391:25:49:0:0`, WeCom `25:49:0:0:0:1`, historical queued
`7:0`, zero actionable/running/unknown work, and provider tuple `391:49:35:44`. No second run or
manual substitute occurred. The protected stage and fresh rollback remain retained;
`release-result.txt` is absent and `c66aa62` was not deployed.

## Offline OCI archive correction after recovered retry

Read-only inspection established that the protected image bundle is an OCI/containerd layout, not
the classic layout assumed by the failed validator. The candidate identity is the sole index image
manifest digest
`sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2`; its different
config digest is
`sha256:695d4b23d5cfa5a09ac156f9308b23d3e7615b342a00aad19c619bc62f30db0a`. The driver now
distinguishes OCI from supported classic archives by explicit metadata and fully validates the OCI
index/manifest/config/layer descriptor graph, exact RepoTag plus its containerd/OCI annotations,
the reviewed `linux/amd64` config and ordered diff IDs, exact `manifest.json` references, all
referenced blob hashes/sizes and an exact safe regular-member set before load. Conflicting markers,
extra images or blobs, dangling references, order/path/hash/size/media-type conflicts, traversal,
duplicates and non-regular members fail closed. Existing candidate checks after load are retained.

Initial offline artifacts before independent least-privilege review, both mode 0600:

- `research/default-off-release-driver.sh` — SHA-256
  `db4bc3b5d8ab9976392930f87f1ba6ac2b866f9c70fa8460e6d95a643fd28547`.
- `research/test-default-off-release-driver.sh` — SHA-256
  `ac7257f200d6ed231f693173052de6f19dc1b8bbc724e941b5e6d0d64b6601b9`.

Both passed `bash -n`. The full fake harness passed realistic OCI and supported-classic positives,
the candidate-digest-differs-from-config regression, descriptor/config/layer hash/size negatives,
config diff-ID, strict JSON/schema/media and index-annotation/RepoTag negatives,
tag/index/manifest conflicts, unsafe/duplicate/non-regular/dangling members, pre-load phase arming,
and the existing signal/recovery/mixed-tag cases. The exact local candidate bundle also passed the
validator-only contract with the isolated tag and candidate manifest digest; it was not loaded.
ShellCheck and gitleaks were unavailable in the offline environment; the targeted changed-shell
secret scan and `git diff --check` passed.

No production, SSH, Docker service, provider or WeCom access occurred during this correction. No
transfer, service stop, backup, load, retag, overlay, restart, build, enqueue, retry, resend or flag
enablement occurred. The prior queued noon job and its ordinary terminal progression remain in the
historical evidence, and the authorized retry remains a recovered exit before image load. These
offline hashes grant no deployment permission; any retry requires separate review/authorization
and a fresh state/rollback validity decision.

## Authorized OCI-corrected default-off retry — recovered exit 1

The final driver SHA-256
`db4bc3b5d8ab9976392930f87f1ba6ac2b866f9c70fa8460e6d95a643fd28547` replaced the old staged
driver as the only pre-driver mutation. The stage remained protected with exactly ten mode-0600
members, its source/image and 307/165-file manifests remained exact, and the exact production OCI
validator-only gate passed. Fresh samples retained durable/current-day/WeCom/historical vectors
`36:182:36:13:4:59:157:35:44:35:391:25:49:0:0` / `2:2:4` /
`25:49:0:0:0:1` / `7:0`, provider/delivery tuple `391:49:35:44`, and zero actionable/running/
unknown work. Exact prior services, protected inputs and false flags passed, with 10,242 seconds
remaining in the reviewed safe window.

The driver was invoked exactly once by its root/physical-cwd/absolute-stage/null-stdin contract. It
quiesced writers and completed fresh rollback
`20260816T055519Z-zhipu-ocr-default-off`. Evidence SHA-256 values are:

- protected manifest:
  `0e1619252f8f8d7a88f42ef8f5ed4780f8f05c3c130b15320b571545dde4a13b`;
- PostgreSQL dump / 526-line catalog:
  `20062d931713c6c6bfbf6d79919ba9944c78f1ed3058dff0b2ce590fb777cb86` /
  `a91f6b2c397218870fe87b92babc5c9636e684c7301d25019e9fb07bd34b9284`;
- 708-object MinIO manifest:
  `704a6937016a07c2fe843611afb3088efe85fa96d6b3bc5cabe391e385f2f4a8`;
- brand manifest / brand archive / active-code archive:
  `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24` /
  `4fb13a0ca7698adbd946a444a0bea8c18390c6397d6b6a33cbb6168034efe4dc` /
  `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`;
- prior active-tag / unique rollback-image inventories:
  `aeb0397afd7771fc2d17e766b42a693910545be98f73072c9b47f566a765ed1a` /
  `a5f3c632ac065cb1c665b289799ee88b99abe8ede3c90f79b531675b2bd77ade`.

After bundle load armed `tags_changed=1`, the post-load candidate check failed as `candidate image
source manifest mismatch`. The exact defect is in driver collection scope: the runtime manifest had
163 lines, while the frozen artifact had 165 because the runtime command omitted top-level
`alembic.ini` and `pyproject.toml`. This was not an OCI identity or candidate-content failure.
State was `backup_ready=1`, `tags_changed=1`, `overlay_changed=0`; no host overlay, one-shot,
migration or candidate service restoration began.

Phase-aware recovery restored prior tags and services, logged `recovery completed`, and the single
invocation exited 1. Independent recovery samples retained every vector and provider/delivery
counter exactly. Production remained on
`331a4942a84b36811cbbc4abff68bca2abc71f0c` /
`sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`, with prior
source/markers/tags, all eight restart-zero services, false flags, protected inputs, healthy
infrastructure and clean logs. Candidate running count was zero; `release-result.txt` was absent.

The target was not deployed and there was no second run. Model invocations, image attempts and
WeCom attempts had zero delta; no Zhipu OCR, Comfly, image-generation or Enterprise WeChat provider
call, fixture, enqueue, retry, resend, activation, commit or push occurred. The separately owned
driver fix must include both missing manifest entries and requires a new explicit authorization
before production execution.

## Offline correction for the post-load 165-file manifest

Local read-only reproduction confirmed the failed runtime command produced 163 entries and differed
from the frozen 165-entry manifest only by root `alembic.ini` and `pyproject.toml`. The exact
candidate already contains both files with matching hashes. The fix therefore preserves the
reviewed count and image and makes the collection scope explicit: those two non-symlink root files
plus regular `*.py`/`*.html` files below non-symlink `app/` and `alembic/`, NUL-delimited and
C-locale sorted with empty-safe hashing. A pure validator now requires both manifests to have
exactly 165 safe, unique,
deterministically ordered entries and identical paths/hashes.

Final offline artifacts, both mode 0600:

- `research/default-off-release-driver.sh` — SHA-256
  `2430f8c1f54ad4db482e69b216b49eeb42df5bb630fe1603745d7358f485fefc`.
- `research/test-default-off-release-driver.sh` — SHA-256
  `233c4b68f73639d1973f2eafb29d6ac109f2ac17ebeeeb01acd2275cbcbfb8bc`.

Both passed `bash -n` and the full fake harness. The harness now executes the actual manifest
collection/validation boundary with fail-closed exact fake-Docker argument checks and proves old
163 fails through that boundary, exact 165 passes, temporary output is EXIT-cleaned, and missing
root, hash drift, extra/replaced, whitespace/traversal/absolute/backslash/newline/scope/suffix/
hash/order and duplicate cases fail. All prior archive/recovery/tag tests remain passing. The exact
local candidate then passed the manifest-only probe under network-none, read-only, cap-drop-all and
no-new-privileges constraints; its exact legacy command produced 163 entries and the validator
rejected them. No `docker load` occurred.

No SSH, production, provider or WeCom access occurred, and no transfer, quiesce, backup, load,
retag, overlay, restart, enqueue, retry, resend, build or flag enablement occurred. The retained
`20260816T055519Z-zhipu-ocr-default-off` backup/recovery evidence is unchanged. These offline
hashes grant no deployment permission; a future retry still requires independent review, current
state gates and explicit authorization.

## Authorized final default-off retry — recovered import-probe failure

The final mode-0600 driver/harness hashes were
`2430f8c1f54ad4db482e69b216b49eeb42df5bb630fe1603745d7358f485fefc` /
`233c4b68f73639d1973f2eafb29d6ac109f2ac17ebeeeb01acd2275cbcbfb8bc`. Local and production
critical smokes accepted the exact OCI archive and corrected 165-entry candidate manifest. Fresh
18-second samples retained durable/current-day/WeCom/historical vectors
`36:182:36:13:4:59:157:35:44:35:391:25:49:0:0` / `2:2:4` /
`25:49:0:0:0:1` / `7:0`, provider/delivery tuple `391:49:35:44`, and zero actionable/running/
unknown work. Exact prior services/source/markers/tags, false flags, protected inputs, logs and the
8,735-second safe window passed.

Only the staged driver was replaced; the protected stage remained exact ten. The driver was then
invoked once by its root/physical-cwd/absolute-stage/null-stdin contract. It quiesced writers and
completed fresh rollback `20260816T062022Z-zhipu-ocr-default-off`. Evidence SHA-256 values are:

- protected manifest:
  `6e301f7d3a0190e1192c744b520845b1956d0fd3034ea8099bf2fb34e3385c8f`;
- PostgreSQL dump / 526-line catalog:
  `dec08cf2b184785fbb84403d93f0a0878571a69d34d4fcf9f25463247e15a4b5` /
  `e22c1c6b6614836c046b60fec118eab37f2802d3c643e7ac845d5183593f8751`;
- 708-object MinIO manifest:
  `704a6937016a07c2fe843611afb3088efe85fa96d6b3bc5cabe391e385f2f4a8`;
- brand manifest / archive / active-code archive:
  `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24` /
  `4fb13a0ca7698adbd946a444a0bea8c18390c6397d6b6a33cbb6168034efe4dc` /
  `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`;
- prior active-tag / unique rollback inventories:
  `aeb0397afd7771fc2d17e766b42a693910545be98f73072c9b47f566a765ed1a` /
  `3cd2d4a0d1f388e3156eed872506511be2201c92bf21bb0a5f47757b110419bf`.

The post-load, pre-overlay import gate then failed with `ModuleNotFoundError: No module named
'app.acquisition_scheduler_main'`. The repository and exact 165-entry candidate manifest contain
`app/scheduler_main.py`, not `app/acquisition_scheduler_main.py`; the driver probe imports the
wrong acquisition scheduler module. State was `backup_ready=1`, `tags_changed=1`,
`overlay_changed=0`, so no host overlay, one-shot, migration or candidate service restoration
began.

Phase-aware recovery restored prior tags and services and the single invocation exited 1.
Independent 17-second samples retained every baseline vector and provider/delivery counter.
Production remained on `331a4942a84b36811cbbc4abff68bca2abc71f0c` /
`sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`, with prior source,
markers, tags, eight restart-zero services, false flags, protected inputs, healthy infrastructure
and clean logs. Candidate running count was zero and `release-result.txt` was absent.

The target was not deployed and there was no second run. Model invocations, image attempts and
WeCom attempts had zero delta; no Zhipu OCR, Comfly, image-generation or Enterprise WeChat provider
call, fixture, enqueue, retry, resend, activation, commit or push occurred. A separately reviewed
import-probe fix and new explicit authorization are required before any future production attempt.

## Offline Compose-entrypoint import correction

The exact local candidate reproduced the stale import failure: `app.acquisition_scheduler_main`
does not exist, while Compose runs acquisition scheduling as `python -m app.scheduler_main`. The
driver now imports API `app.api_main` plus an ordered constant list of the seven actual
scheduler/worker/dispatcher modules. A static harness gate parses all eight current Compose
`*app-runtime` services and requires exact equality with `APP_SERVICES` and those entrypoint
constants. A fake-Docker case executes the entire `assert_candidate_image` branch rather than
replacing it with a no-op, and every fake argument assertion returns nonzero explicitly.

The exact full-gate smoke also exposed a stale hardcoded Alembic filename. Candidate revision
`20260815_0021` is declared by `20260815_0021_visual_controlled_diversity.py`, not the filename the
old driver named. Alembic validation now consumes the expected-head constant, requires one exact
revision declaration and requires the complete head output to contain exactly the one expected
line; an extra head is rejected. After both corrections, the exact local candidate passed
identity/labels, the 165-file
manifest, all entrypoint imports, non-root/default-off Settings, `pip check`, OCR route
construction, shadow exclusion, OpenAPI and Alembic with network disabled, read-only rootfs,
capabilities dropped and no-new-privileges. No image load occurred.

Final offline artifacts, both mode 0600:

- `research/default-off-release-driver.sh` — SHA-256
  `c3f716bee66dcd64d328fc655bac26e3dfcdc1f052cb335451f4a411d9e74ad4`.
- `research/test-default-off-release-driver.sh` — SHA-256
  `c01a63c5141bd49a9ebabfdcaa8cffd218a0dc0eded402fa1437758e21225aec`.

Both pass `bash -n` and the full harness, including Compose-entrypoint binding, strict fake full
candidate gate, and all existing archive/manifest/recovery/tag cases. No SSH, production,
provider or WeCom access occurred; there was no load, transfer, quiesce, backup, retag, overlay,
restart, enqueue, retry, resend, build or flag enablement. The retained
`20260816T062022Z-zhipu-ocr-default-off` backup/recovery evidence is unchanged. These hashes do
not authorize deployment or another retry.

## Authorized c3f716 default-off retry — recovered source-mode failure

The final driver/harness hashes were
`c3f716bee66dcd64d328fc655bac26e3dfcdc1f052cb335451f4a411d9e74ad4` /
`c01a63c5141bd49a9ebabfdcaa8cffd218a0dc0eded402fa1437758e21225aec`, both mode 0600 and
`bash -n` clean. Fresh 17-second samples retained durable/current-day/WeCom/historical vectors
`36:182:36:13:4:59:157:35:44:35:391:25:49:0:0` / `2:2:4` /
`25:49:0:0:0:1` / `7:0`, provider/delivery tuple `391:49:35:44`, and zero actionable/running/
unknown work. Exact prior services/source/markers/tags, false flags, protected inputs, logs and a
6,976-second safe window passed.

Only the stage driver was replaced; exact ten-member protection, source/image archives and
307/165-file manifests remained unchanged. The driver was invoked once by its root/physical-cwd/
absolute-stage/null-stdin contract, quiesced writers and completed fresh rollback
`20260816T064939Z-zhipu-ocr-default-off`. Evidence SHA-256 values are:

- protected manifest:
  `1c4af079eef19cd3bab42bc40d5f865be13ca7b1433e46423c860fa8ff5209cd`;
- PostgreSQL dump / 526-line catalog:
  `6ffcda7aacc5a4e5b9d4a372c8cc31faf44de4bf3eb776f009a631f00439476b` /
  `caacbcff7d186df52553c39e205c11ae442bd84c1bb195e67509e8d43e50027a`;
- 708-object MinIO manifest:
  `704a6937016a07c2fe843611afb3088efe85fa96d6b3bc5cabe391e385f2f4a8`;
- brand manifest / archive / active-code archive:
  `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24` /
  `4fb13a0ca7698adbd946a444a0bea8c18390c6397d6b6a33cbb6168034efe4dc` /
  `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`;
- prior active-tag / unique rollback inventories:
  `aeb0397afd7771fc2d17e766b42a693910545be98f73072c9b47f566a765ed1a` /
  `31ba23e359066a9440846704cfe92ecb9f4d181aedfb323da658ece75a85e655`.

Post-load candidate gates reached and `pip check` passed. Active retag and host overlay then armed
`tags_changed=1` and `overlay_changed=1`; overlay failed as `source member mode is outside the
reviewed allowlist`. Exact local archive inspection found all 307 regular source members outside
the accepted `0600|0644|0700|0755` set: 295 are 0664 and 12 are 0775. Sorted member
`.env.example` is the first 0664 failure. Source paths and hashes remain exact, making this an
archive-mode/driver-policy mismatch. No marker, one-shot, migration or candidate service
restoration occurred.

Phase-aware recovery restored prior source/markers, active tags and services and the single
invocation exited 1. Independent 16-second samples retained every vector and provider/delivery
counter. Production remained on `331a4942a84b36811cbbc4abff68bca2abc71f0c` /
`sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`, with eight
restart-zero services, false flags, protected inputs, healthy infrastructure and clean logs.
Candidate running count was zero and `release-result.txt` was absent.

The target was not deployed and there was no second run. Model invocations, image attempts and
WeCom attempts had zero delta; no Zhipu OCR, Comfly, image-generation or Enterprise WeChat provider
call, fixture, enqueue, retry, resend, activation, commit or push occurred. A separately reviewed
source-mode correction and new explicit authorization are required before future production work.

## Offline canonical source-mode correction

The recovered source-mode mismatch is corrected offline. The exact local source archive has 307
regular files: 295 mode 0664 and 12 mode 0775. The old allowlist rejects the first sorted 0664
member, while the new preflight-only validator maps the complete exact set to 295 canonical 0644
and 12 canonical 0755 entries. Frozen paths and hashes did not drift.

The driver now produces and verifies sorted exact per-file mode evidence before any production
preflight, quiesce or backup. Only regular 0644/0664 -> 0644 and 0755/0775 -> 0755 mappings are
accepted. Other permissions, special or world-write bits, unsafe/duplicate/extra/missing paths,
non-regular members and destination executable-class drift fail closed. Overlay consumes only the
file evidence and uses explicit canonical `install -m 0644` or `install -m 0755`; group-write bits
and directories are never overlaid.

Both scripts pass `bash -n` and the full fake harness, including exact Compose/full-candidate,
OCI/classic archive, source manifest, mixed tag and early/mid/late recovery coverage. New mode
cases prove canonical and 0664/0775 positives, 0600/0700/0666/0777/setuid/setgid/sticky/unknown
negatives, extracted/destination class rejection and canonical install arguments. The exact archive
passes mode/preflight-only validation with 307 evidence lines and the expected 295/12 mapping.

Initial offline artifacts before independent review, both mode 0600:

- `research/default-off-release-driver.sh` — SHA-256
  `870eb45bef00bd927aa270aa737780b745c1db4300347fb295d72ef2af961d6e`.
- `research/test-default-off-release-driver.sh` — SHA-256
  `d6c2758de04a419f642d707a24a15bbcf2e20a6ebebb6a18c96db36a369a712b`.

Independent review then closed two further safety gaps without changing the frozen bundle. The
archive validator now checks directory and explicit-root modes before extraction, accepting only
0755/0775 and rejecting world-write, special and encoded type bits. Overlay source/destination
paths must resolve exactly beneath physical roots, so a nested ancestor symlink fails before
installation. Each file is installed into a generated root-only sibling and atomically replaces
the destination without dereferencing a final-component target; canonical mode and owner/group are
checked again after installation and before the final source hash. The fake harness now exercises
strict mode-evidence syntax/order/path-set,
directory modes, a real local `/usr/bin/install`, a successful no-op fake that fails post-install,
and a nested destination symlink whose target is not modified.

Final independently reviewed offline artifacts, both mode 0600:

- `research/default-off-release-driver.sh` — SHA-256
  `0074ca60fa46a64a16957f0ff684058ed62bb4f5d0466b85b7fb6d57339cba1c`.
- `research/test-default-off-release-driver.sh` — SHA-256
  `7563e97eeb6778f60d104dee8ee7f40a5027999f6bb20ce8bcc881962e1865da`.

No SSH, production, Docker load, provider or WeCom access occurred, and no transfer, quiesce,
backup, retag, overlay, restart, enqueue, retry, resend, build, activation, commit or push occurred.
The retained `20260816T064939Z-zhipu-ocr-default-off` rollback/recovery evidence remains unchanged.
Future builders should normalize source archive modes to 0644/0755. These offline changes and
hashes grant no deployment permission; independent review, current-state gates and explicit
authorization remain required.

## Authorized 0074ca retry — pre-backup recovered exit 1

The final driver/harness hashes were
`0074ca60fa46a64a16957f0ff684058ed62bb4f5d0466b85b7fb6d57339cba1c` /
`7563e97eeb6778f60d104dee8ee7f40a5027999f6bb20ce8bcc881962e1865da`, both mode 0600 and
`bash -n` clean. Fresh 18-second samples retained durable/current-day/WeCom/historical vectors
`36:182:36:13:4:59:157:35:44:35:391:25:49:0:0` / `2:2:4` /
`25:49:0:0:0:1` / `7:0`, provider/delivery tuple `391:49:35:44`, and zero actionable/running/
unknown work. Prior services/source/markers/tags, false flags, protected inputs, logs and the
4,874-second safe window passed.

Only the staged driver was replaced; exact ten-member protection and candidate archives/manifests
remained unchanged. The driver was invoked once by its root/physical-cwd/absolute-stage/null-stdin
contract. It failed during preflight `assert_previous_source` as `source mode class differs from
the canonical contract`. Phase state was `backup_ready=0`, `tags_changed=0`,
`overlay_changed=0`, so there was no lock/quiesce, fresh backup, image load, retag, overlay,
one-shot, migration or service restoration. Recovery completed and the invocation exited 1. No
fresh backup ID/evidence exists; retained rollback `20260816T064939Z-zhipu-ocr-default-off` was not
used and remains historical evidence only.

Independent 17-second samples retained every baseline vector and provider/delivery counter.
Production stayed on `331a4942a84b36811cbbc4abff68bca2abc71f0c` /
`sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`, with prior source,
markers, tags, eight restart-zero services, false flags, protected inputs, healthy infrastructure
and clean logs. Candidate running count was zero.

A follow-up, separately authorized single read-only diagnosis streamed the exact staged archive's
source-only canonical evidence directly across all 307 active destinations. Canonical counts were
295 mode 0644 and 12 mode 0755; current counts were 295 mode 0600 and 12 mode 0700. All 307 were
mismatches, all were `ubuntu:ubuntu` regular files, and all realpaths remained within physical
`/opt/edu-ai-lead-agent`. The first sorted mismatch was `.env.example`, current 0600 versus
canonical 0644. Output was bounded to 20 mismatch rows plus totals and contained no content, hashes
or environment data. The pipeline created no remote temporary file and made no production change.

The target was not deployed and there was no second run. Provider and delivery counters had zero
delta; no OCR, Comfly, image-generation or Enterprise WeChat provider call, fixture, enqueue,
retry, resend, activation, backup, commit or push occurred. A separately reviewed active-mode
compatibility policy and new explicit authorization are required before future production work.

## Offline restrictive destination-mode preservation correction

The destination-mode contract is corrected offline without revisiting production. Candidate
archive semantics remain 295 non-executable 0644 and 12 executable 0755 entries; the retained
read-only diagnosis established 295 current 0600 and 12 current 0700 destinations. The old predicate
required exact candidate/destination equality and therefore rejected all 307 even though every
executable class, owner/group, regular-file check and anchored realpath aligned.

Pre-quiesce evidence now binds candidate semantic mode, exact existing destination mode and path.
Only destination 0600/0644 for non-executable and 0700/0755 for executable files is allowed.
Group/world-write, special/unknown modes, ownership drift, class mismatch, unsafe paths and
preflight-to-overlay mode changes fail closed. Atomic overlay uses and verifies the preserved mode,
owner/group, realpath and exact content; it cannot broaden 0600/0700 or add a new destination path.

`bash -n` and the full fake harness pass. New regressions cover strict/canonical destinations,
mixed exact preservation, unsafe/tampered evidence and modes, TOCTOU drift, no-op install, nested
symlink, and a production-shaped 307-file matrix that remains exactly 295 mode 0600 plus 12 mode
0700 after candidate content installation. The exact local archive with a synthetic restrictive
destination also passes preflight-only and independently proves the former exact-mode comparison
had 307 mismatches. Full candidate, OCI/classic, tag and recovery gates remain intact.

Final offline artifacts, both mode 0600:

- `research/default-off-release-driver.sh` —
  `03e3fb11808d789cc9a6a6b8d5fcf48f4d42147f14fb78be62c5416c0771f013`.
- `research/test-default-off-release-driver.sh` —
  `aafbffeb15e8e7a2e7d0694f37500410df9925a457776067e5389f725a1448e6`.

Independent review then bound owner/group into every exact destination evidence row and moved
temporary installation outside the application-writable tree. The temporary parent must be
physical, root-owned, non-group/world-writable and on the destination filesystem; each generated
child is rechecked as root:root mode 0700 before install and immediately before atomic replacement.
New regressions cover ownership evidence/drift, escaped or non-root temporary directories, cleanup,
a final-component symlink race with an unchanged external target, and a true 295×0664/12×0775
candidate source. The exact frozen archive installed over a generated restrictive destination and
finished with all hashes exact, 295 mode 0600, 12 mode 0700 and no temporary residue.

Final independently reviewed offline artifacts, both mode 0600:

- `research/default-off-release-driver.sh` —
  `bcbe4dd7b3e580d7e025f3fb33cedab486d7d39f7164b653b9b0586c8d6fee1a`.
- `research/test-default-off-release-driver.sh` —
  `36038d89d0a1cc9918466c7b1692867f76487097618bacd5d59a32a09ae9df82`.

No SSH, production, Docker load, provider or WeCom access occurred; no transfer, quiesce, backup,
retag, overlay, restart, enqueue, retry, resend, build, activation, commit or push occurred. The
pre-backup failure/read-only diagnosis and historical 064939 recovery evidence remain unchanged.
These hashes grant no deployment permission.

## Authorized bcbe4d retry — recovered trusted-parent failure

The final driver/harness hashes were
`bcbe4dd7b3e580d7e025f3fb33cedab486d7d39f7164b653b9b0586c8d6fee1a` /
`36038d89d0a1cc9918466c7b1692867f76487097618bacd5d59a32a09ae9df82`, both mode 0600 and
`bash -n` clean. Fresh 18-second samples retained durable/current-day/WeCom/historical vectors
`36:182:36:13:4:59:157:35:44:35:391:25:49:0:0` / `2:2:4` /
`25:49:0:0:0:1` / `7:0`, provider/delivery tuple `391:49:35:44`, and zero actionable/running/
unknown work. Prior services/source/markers/tags, false flags, protected inputs, logs and the
2,002-second safe window passed.

Only the stage driver was replaced; exact ten-member protection and archives/manifests remained
unchanged. The driver was invoked once by its root/physical-cwd/absolute-stage/null-stdin contract,
quiesced writers and completed fresh rollback `20260816T081242Z-zhipu-ocr-default-off`. Evidence
SHA-256 values are:

- protected manifest:
  `d3eaf7fab7130ff92e404f34955f7e8e16b3baa48ac6a7a576cd5799a2f2dfa0`;
- PostgreSQL dump / 526-line catalog:
  `dfe5a8fbb841368a30cb3da67227e6370c44e76250df7932a7ae76443cb9746b` /
  `945ac4b019261c0e78317cd1b148c167eafc83b558b69edaf2be9b081bab4199`;
- 708-object MinIO manifest:
  `704a6937016a07c2fe843611afb3088efe85fa96d6b3bc5cabe391e385f2f4a8`;
- brand manifest / archive / active-code archive:
  `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24` /
  `4fb13a0ca7698adbd946a444a0bea8c18390c6397d6b6a33cbb6168034efe4dc` /
  `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`;
- prior active-tag / unique rollback inventories:
  `aeb0397afd7771fc2d17e766b42a693910545be98f73072c9b47f566a765ed1a` /
  `5ce7d88b0755db41a61340bd30f4cac561e59b77ceaf5217020b968bdbc74926`.

Post-load candidate checks reached and `pip check` passed. Atomic source overlay then failed as
`trusted install parent ownership or mode is unsafe`; phase state was `backup_ready=1`,
`tags_changed=1`, `overlay_changed=1`. No one-shot, migration or candidate service restoration
began. Recovery restored prior overlay/tags/services and the one invocation exited 1. Independent
16-second samples retained every vector/provider counter and exact prior production, with eight
restart-zero services, false flags, protected inputs and clean logs. Candidate running count was
zero and `release-result.txt` absent.

Read-only diagnosis established that driver destination root `/opt/edu-ai-lead-agent` produces
trusted temp parent `/opt`. `/opt` is a physical non-symlink directory on device 64770 but mode
0750, uid/gid 1000:1001, owner `ubuntu:ubuntu`; the driver requires root:root. The application
directory is mode 0700 with the same owner/device. Same-device root-owned non-group/world-writable
mechanical candidates were `/var/backups/edu-ai/releases` 0700, `/var/backups/edu-ai` 0700 and
`/var/backups` 0755. `/var/tmp` and `/tmp` were root:root 1777 and rejected. The bounded queries
listed no contents and made no changes; candidate selection remains unreviewed.

The target was not deployed and there was no second run. Provider/delivery counters had zero
delta; no OCR, Comfly, image-generation or Enterprise WeChat call, fixture, enqueue, retry, resend,
activation, commit or push occurred. A reviewed trusted-parent correction and new explicit
authorization are required before future production work.

## Offline fixed trusted backup-root correction

The driver now stages atomic payloads only in fixed `/var/backups/edu-ai/releases`, validated
before any stop as physical non-symlink root:root 0700, same-device and stale-prefix-free. Every
reserved-prefix object and scan error now blocks preflight without printing its name. Every
generated child has the exact six-alphanumeric direct-child shape and is revalidated; EXIT cleanup
also requires the unchanged physical root, so backup IDs, unrelated entries and symlink-root targets
remain untouched.

`bash -n` and the full harness pass production-shaped non-root-0750 app ancestry, real preserved
mode-0600 atomic install/cleanup; unsafe roots, reserved file/symlink/long-prefix residue, scan
errors and cleanup-scope attacks fail while retaining 307-file, candidate/OCI/tag/recovery gates.
Final mode-0600 hashes: driver
`189f2dc1370544b3a57bd5fdbfd471e9e2066045a94ba336d06bd4aeb28b2072`; harness
`212fa5b535ddd7c6f64826a1b6828d0e1fd9260daeee92442c3ad8b92d876fef`. No production/provider
access or deployment occurred; 081242 recovery/topology evidence remains unchanged.

## User-authorized fast-path production release — succeeded

Ordinary evening automation was monitored read-only from the 17:00 CST boundary. Acquisition
finished all ten jobs, governance finished 19 succeeded and 2 review-required jobs, and the slot
finished with zero selections, three unfilled positions and no delivery window. This was a typed
terminal no-delivery outcome. A subsequent 15-second baseline retained durable/provider/WeCom
vectors `37:184:37:13:5:59:157:35:44:35:394:25:49:0:0` / `394:49:35:44` /
`25:49:0:0:0:1`, with actionable/running/unknown all zero.

The user then explicitly authorized one simplified path instead of the complex atomic driver.
Preflight retained exact stage/source/candidate/prior-service identities and false flags. The eight
application services were quiesced in order and fresh backup
`20260816T091212Z-zhipu-ocr-fast-default-off` completed before overlay. Its evidence hashes are:

- protected manifest:
  `2721c71d08842f301ca8e0de86cf1273ec6c1c79cc20137cfd736ff0efcb3e74`;
- PostgreSQL custom dump / validated catalog:
  `a0b5bee39db44af9df59d99d40d9065b42ebc5ab07aba0053c5af288eaae353b` /
  `48a575e6ed936e4fcd9e357da6120a08a3c9df7a8d733dc83e68f905c19fa121`;
- 307-file prior-source archive:
  `3cbaf789b53fcbe6b2ec4b8671286f01f009cb83563e837f7c7a24e79e8987f4`;
- successful fast-release result:
  `930d3cf793eff8dc5b95383da326e7f47266239926f7c0af309a5a451215cba0`.

The validated source archive
`e516184eebdeb9b98c09cc3fecd98369012d75aba5763fdb16ed836b2d3390f9` was overlaid at the
physical application root with root `umask 077` and restrictive tar extraction; all 307 hashes
passed. Full/short markers now identify
`c66aa6217d137033118c552f3db11b2a1121d082` / `c66aa62`, and the shared plus nine service
tags resolve to exact candidate
`sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2`.
Migration exited zero at Alembic `20260815_0021`. API/acquisition/governance/content were restored
in dependency order and the dispatcher last; all eight services use the candidate with restart
count zero, API is healthy, flags remain `false:false`, and the old image has zero running
containers.

The 15-second stability gate and an independent read-only postcheck retained the exact baseline;
there was zero release-caused provider/image/WeCom delta. No OCR, Comfly, fixture, enqueue, retry,
resend, manual delivery, MinIO/brand object operation, frontend deployment, commit or push
occurred. Production mutation is stopped; the retained full backups, new fast backup and unique
rollback tags remain retained. The simplified independent conclusion follows.

## Simplified independent postdeploy check — pass

The checker made bounded read-only SSH observations only. Its initial `backup_shape` result used
the obsolete complex-driver backup suffix. The corrected check reached the exact physical
`20260816T091212Z-zhipu-ocr-fast-default-off` directory, verified root:root mode 0700 and matched
the recorded protected-manifest, PostgreSQL-dump and catalog hashes. Its subsequent
`code.tar.gz_shape` result was likewise a checker filename assumption. Neither was a production
mismatch; under the user-simplified gate, code/result sidecar filenames are no longer required and
no further SSH connection was made.

Before the filename stop, the checker independently passed exact c66 full/short markers, eight
candidate-`03a988...` long-lived services running at restart zero, healthy API/PostgreSQL/MinIO,
migration exit zero with Alembic `20260815_0021`, and `false:false` API/content flags. Combined
with the implement agent's recorded independent 15-second exact durable/provider/WeCom and
zero-running/unknown stability check, bounded safe logs, old-image-running-zero and fast-release
result checksum, the simplified production postdeploy conclusion is PASS with no blocker. No
provider, fixture, WeCom send, restart or production mutation occurred during checker access.

## User-authorized paid OCR fixture — failed closed; activation not performed

The subsequent activation authorization was conditional on one exact ordered three-line
`glm-ocr` PASS. Preflight passed on the c66 candidate with healthy API, restart-zero API/worker,
flags `false:false`, separate OCR/chat models, one-attempt configuration and no running content,
image or WeCom delivery work. A deterministic protected 1024x1024 fixture was generated with
SHA-256 `9337541f14f4d887a11a1c1f970fcd1d88b7acc66fd51a6e863084894720618e`.

One preparatory wrapper run stopped before Docker because a safe environment line-count assertion
was wrong; it made no HTTP request and cleaned up. On the corrected sole authorized Docker run, the
outer SSH/remote command returned exit 1 and emitted only `fixture_cleanup=armed`. No typed OCR
result or HTTP-attempt count was emitted. The exact Docker exit code was not printed, and protected
stderr was removed on exit, so both that Docker status and the actual paid provider-attempt state
are **unknown**. This is not a PASS and cannot be represented as a zero- or one-attempt result. No
retry was made.

The run therefore failed closed. The exact remote fixture stage and unique container are absent;
two samples 15 seconds apart retained the exact candidate at restart zero, healthy API and
`false:false` API/worker flags. Post-failure durable/provider/WeCom/running aggregates were
`37:184:37:13:5:59:157:35:44:35:394:25:49:0:0` / `394:49:35:44` / `25:49:0:0` /
`0:0:0:0`, all zero delta from the pre-call durable baseline. No env edit, feature activation,
service recreation, database/MinIO/Comfly/news/WeCom workflow, enqueue, retry, resend or manual
delivery occurred. Production remains on c66 default-off; any future provider attempt requires new
explicit authorization and a runner that always preserves typed attempt and Docker-exit evidence.

## User-authorized minimal activation — succeeded

After the fail-closed fixture result, the user explicitly lowered the gate and authorized activation
without another paid call. A fresh official-contract comparison found the c66 endpoint, `glm-ocr`
model, private data-URI, 10 MiB input ceiling and raw `layout_details` two-dimensional page shape
consistent with the provider documentation. The prior unknown therefore remains a test-wrapper
evidence gap; it was not recategorized as provider success or failure.

At `2026-08-16T09:51:46Z`, the c66 candidate, healthy API, restart-zero API/worker and default
`false:false:glm-ocr:10485760:1048576:120.0:1:false` contract passed preflight. The two target keys
were absent from both env files, provider/WeCom were `394:49:35:44` / `25:49:0:0`, and all running
and current-day actionable counts were zero. The authorized missing-key path created protected
rollback `20260816T095342Z-zhipu-ocr-activation-env`; its exact mode-0600 env SHA-256 is
`4ad88db853075ad8668a1c45bd2e1f4498256c2ece0903ab2fbe3ea40521efdc`.

The original env already ended with a newline. Its bytes, mode and owner were preserved, and only
the two explicit `true` assignments were appended once each. The activated env SHA-256 is
`df0213dbd192632307d4cba54f678f13e593da61e39a08b79474f2f6d2b5f717`; the release env remained
untouched and absolute Compose render passed. Only acquisition API and content worker were
force-recreated with no-build/no-deps. Both now report
`true:true:glm-ocr:10485760:1048576:120.0:1:false`, use exact candidate
`sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2` at restart zero, and
API is healthy. The dispatcher identity did not change.

After 15 seconds, provider and WeCom remained `394:49:35:44` / `25:49:0:0`, all eight running
categories remained zero, and safe activation-log severe/secret/provider-request counts were
`0:0:0`. No paid fixture, OCR/Comfly request, enqueue, retry, resend, dependency start, dispatcher
mutation or manual delivery occurred. Activation completed at `2026-08-16T09:54:08Z` without
rollback; the original env backup remains the explicit recovery artifact.

## Offline OCR container harness argv correction — passed

The local container harness initially exited 1 with no outer output although both scripts were
syntactically valid and the Python runner test passed. The container wrapper had split
`docker_call create` over source lines without continuations, so Bash passed only `create` to the
fake and executed every following option as a separate command. This is recorded as **E — implicit
assumption** plus **D — test coverage/diagnostic gap**.

The wrapper now constructs one exact `create_args` array. Its fake checks exact argc and positional
order for create/start/wait/inspect/logs/remove, explicitly returns failure on mismatches, and tests
missing/reordered argv. Its EXIT path emits only case/status/action names and stdout/stderr byte
counts plus SHA-256 before deleting private temporary evidence; a probe proves the private stderr
sentinel is not exposed.

Both scripts passed `bash -n`. The focused local-only harness exited 0 with
`exact-argc-order`, `redacted-failure-diagnostics`, `named-no-rm`, `network-none`, `pass-evidence`,
`typed-fail-evidence`, `stderr-hash-only`, `cleanup-after-evidence`, `malformed-retained`, and
`preflight-no-docker`. Final script SHA-256 values are
`38ab022e990db436ccd6a0283e412bba1331c5464e0feb05845822fb2b5cfc93` and
`51631d0b28769cc6e2e064dc94a98ea67ad5ffc975ab59f5c27ae6601a560b76` respectively. No SSH,
Docker daemon, provider, network, production, commit or push action occurred. No matching
`src/templates/markdown/spec/` directory exists, so no template was created.

## OCR-independent controlled diversity — local implementation passed

The 2026-08-18 product decision supersedes the prior OCR activation dependency. Settings now
accept `IMAGE_DIVERSITY_ENABLED=true` with `IMAGE_OCR_ENABLED=false`; the configured OCR model is
irrelevant while OCR is off, while controlled diversity still requires exact reviewed `glm-ocr`
identity whenever OCR is enabled. The Zhipu adapter/parser was not relaxed or otherwise changed,
including its terminal handling of unknown element fields and exact ordered visual text.

The material worker already had the required independent branch, so no service logic change was
needed. A new controlled regression proves OCR-off execution generates one media-valid image,
makes zero recognizer calls even when a recognizer object is supplied, reaches the perceptual-
similarity gate, writes immutable storage once, and persists a passed validation without
`image_ocr_not_configured`. Existing OCR-on behavior remains covered by the unchanged strict
provider/material tests.

The accepted tradeoff is explicit: the controlled prompt/brief still requests the three finite
brand/category lines, but the actual rendered text and order are not machine-verified while OCR is
disabled. PNG/JPEG signature and byte bounds, 1024×1024 raster validation, provider identity,
enabled visual audit, similarity decisions, and storage integrity remain required.

Local gates passed: focused Ruff format-check and lint for all three changed Python files;
explicit-config, no-incremental strict mypy for the two affected application modules; and 221
affected Settings/image-generation/material/worker-wiring/strict-Zhipu-OCR tests. The initial
`uv run` probe did not execute because `uv` is unavailable; the repository's existing
`/root/anaconda3/envs/edu-ai` interpreter ran every recorded gate. Final `git diff --check` passed.
No production/SSH/Docker/provider/network, WeCom, enqueue/retry/replay/resend, commit/push, or
deployment action occurred.

### Independent OCR-optional review

The final local review found and fixed two remaining contract drifts. Doctor had still required
`IMAGE_OCR_MODEL=glm-ocr` unconditionally; it now mirrors Settings by enforcing that identity only
when diversity and OCR are both enabled, while retaining API/content-worker equality for all OCR
settings. `.env.example`, README, the migration runbook, and the production checklist had also
retained the superseded mandatory-OCR rollout wording and now state the accepted unverified-text
tradeoff.

The material regression was made non-tautological at the downstream boundaries: it supplies an
otherwise callable recognizer and proves zero requests, runs an enabled audit, carries a real
perceptual-similarity result into persistence, retains validated PNG/1024×1024 metadata, and checks
that the stored descriptor byte count and SHA-256 match the generated body. A provider-shaped
factory test separately proves OCR-off controlled diversity constructs no recognizer. The strict
Zhipu adapter/parser implementation remained byte-for-byte outside the diff.

Final gates passed: 237 focused pytest cases; Ruff format-check/lint for all five changed Python
files; strict explicit-config, no-incremental mypy for Settings, material orchestration, adapter
factory, and content worker; OCR-off Compose render/equality with a deliberately unused model;
Doctor shell syntax; unchanged-parser assertion; and `git diff --check`. No production, SSH,
provider, WeCom, enqueue/retry/replay/resend, deployment, commit, or push action occurred.

The final full repository gate passed after those review edits: `make backend-check` reported Ruff
format/lint clean, strict mypy clean across 162 source files, and 969 backend tests passed in 56.73
seconds with 81% coverage. Task context validation and `git diff --check` also passed. This remains
a local code/config capability change only; production still has OCR enabled until a separately
authorized release and environment update set `IMAGE_OCR_ENABLED=false`.

## Production OCR-off release and authorized resend — succeeded

The reviewed source revision `5d0a4caca97cc61edd201e26bf99f038500f107a` was committed and
pushed to Codeup. A network-disabled overlay was built from the exact active production base and
validated before transfer. Its immutable candidate image is
`sha256:886e6e212bfe2a6a21c3a2bd5826b7283f5d5fb76c2949201861d15892fa8f99`; the compressed image
bundle SHA-256 is `e4583bb4e8b59f8f2be9f08dd0b17886a74562c6fec8ef8558080a7af635aba6`.
The task-local operator SHA-256 is
`e53527f8b1c1d9f42536e7df0af99c58c95e71911336bb7f4b38ede13bef3c9f`.

The checksum-bound activation completed once with fresh rollback backup
`20260818T010715Z-ocr-off`. All eight application services now run the candidate image with restart
count zero, the API is healthy, the full marker equals the target revision, and the effective
runtime flags are `IMAGE_OCR_ENABLED=false` and `IMAGE_DIVERSITY_ENABLED=true`. The strict OCR
implementation remains present but is not invoked while disabled; raster, visual audit,
similarity, storage and delivery validation remain active.

The already-selected morning package was recovered without creating new editorial content. Its
single authorized image retry advanced the artifact from failed attempt 1 to succeeded attempt 2,
producing an `image/png` raster at 1024x1024. A read-only check after a wrapper syntax error proved
that no hidden first retry occurred, so there was no duplicate provider call.

Because the original morning delivery window was already expired, one deterministic authorized
late formal direct-lane delivery was created for the existing copy and image. Delivery
`3d08d7fe-0926-47e2-a246-bc574bae26d9` reached terminal `delivered`: text `delivered`, image
`delivered`, one job attempt and two child delivery attempts. Exactly one delivery exists for the
package; no retry or second job was created.

The independent final check retained all eight services on the candidate at restart zero, healthy
API, flags `false:true`, successful image attempt 2, terminal delivery and bounded severe-log count
zero. Final safe counters were `439:51:51` for model invocations, aggregate image attempts and
WeCom child attempts. The rollback backup is retained. Production deployment and the requested
single resend are complete.
