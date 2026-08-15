# Zhipu image OCR provider rejection — result

## Status

Repository implementation Phases 0–2, the independent Phase 2.2 quality review, Phase 3 release
preparation, and the default-off Phase 4 production deployment are complete. The canonical short
release marker was reconciled and an independent read-only recheck passed. The first separately
authorized Phase 5 OCR fixture gate was attempted exactly once and failed closed with
`invalid_provider_output`; the isolated-news/Comfly acceptance and activation were not started.
The repository has now returned to Phase 2.1 for an offline-only response-envelope correction;
that correction has not been deployed or exercised against a live provider.

The release implementer used key-auth SSH for the reviewed backup, offline image transfer, source
overlay, migration, and dependency-ordered restart. It did not call Zhipu, Comfly, or WeCom,
generate a fixture, create an acceptance database/bucket, enqueue, retry, resend, commit, or push.
External/provider call-count deltas caused by Phases 3–4 are all zero. Production now runs the
candidate release with both visual flags false. After the failed fixture was cleaned up, the
existing candidate WeCom dispatcher was restored without enqueue, retry, or resend and passed the
bounded fail-closed recovery gate.

## Implemented contract

- Added independent bounded image OCR settings: `IMAGE_OCR_MODEL=glm-ocr`, 10 MiB raw input,
  1 MiB response, and 120-second OCR timeout. Controlled diversity rejects any other OCR model.
- Added `ZhipuImageTextRecognizer` on `/layout_parsing`. It accepts only validated PNG/JPEG bytes,
  sends a private Base64 data URL with crop/layout visualization disabled, and uses the existing
  bounded Zhipu HTTP transport and typed provider failures.
- Enforced case-normalized model identity, the official exactly-one-page nested layout envelope,
  typed and consistent page metadata/dimensions, bounded unique positive layout indices,
  allowlisted labels, finite ordered `[0,1]` boxes, bounded content, at most eight lines,
  deterministic `(y1, x1, index)` ordering, and the existing exact ordered visual-text gate.
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
- This correction made no live provider call and did not use SSH, production, deployment, MinIO,
  Comfly, enqueue/retry/resend, or WeCom. Production flags and services were not read or changed.

## Remaining work

- Complete the local Phase 2.1 quality gates and independent review before preparing a new immutable
  release; this run permits no retry, second OCR call, real-news/Comfly acceptance, or activation.
- Production flags remain false and the dispatcher is running only as the final dependency-ordered
  failure-recovery step. The isolated-news and activation gates remain blocked until a future
  separately authorized plan passes; the protected stage and rollback artifacts remain retained.
