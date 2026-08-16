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

### Phase 2.2 correction default-off release attempt

- [x] Re-fetch and freeze Codeup `origin/main` at exact bbox-compatibility commit
  `c66aa6217d137033118c552f3db11b2a1121d082`; build and validate the retained 307-path offline
  source overlay, immutable image provenance, non-root runtime, exact 165-file image source set,
  unit/raw-pixel bbox contract, migration/OpenAPI drift, and transfer bundle checksums.
- [x] Run strict read-only production preflight against the current 2026-08-16 ordinary automation
  baseline, then quiesce writers and capture a fresh catalog/checksum-verified PostgreSQL/MinIO/
  brand/env/code/prior-image rollback set.
- [x] Transfer and checksum the protected candidate artifacts without changing active source,
  markers, environment, volumes, migration, or flags.
- [ ] Complete remote image validation, active retag/source overlay, one-shots, dependency-ordered
  restore, and default-off 30-second candidate stability. The remote offline import probe failed
  before overlay, so the release stopped and the prior candidate was restored.

The local release archive contains 307 regular files / 360 members, is 821,122 bytes, and has
SHA-256 `e516184eebdeb9b98c09cc3fecd98369012d75aba5763fdb16ed836b2d3390f9`.
The immutable candidate is
`sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2`
(132,064,594 bytes). Its 131,268,412-byte transfer bundle has SHA-256
`db1cab9cc975e08d46aa0d47e35f81100d02ea0eb5df90ce8677cc23378119c4`.
All local labels/source hashes/non-root/import/pip/unit-bbox/raw-pixel-bbox/OpenAPI/Alembic gates
passed.

Production preflight retained false diversity/OCR flags, exact prior release `331a494` and image
`sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`,
and stable ordinary baseline
`35:179:35:13:3:58:154:34:43:34:382:24:47:0:0`. Running and current-date actionable work were
zero, seven historical queued copy jobs retained aggregate attempt count zero, and WeCom was
`24:47:0:0:0:1` across jobs, attempts, nonterminal, unknown, duplicate request fingerprints, and
the unchanged historical duplicate content-fingerprint group.

The first quiesced backup attempt used a valid 9,726,989-byte database dump but omitted `-i` from
the container-local `pg_restore --list` validation. It therefore read EOF, failed closed before
MinIO/brand/image backup and before transfer, and restored all prior services with unchanged
counters. That incomplete rollback directory is retained as `20260816T021431Z` and is not used.
The fresh reviewed rollback ID is `20260816T021614Z`: PostgreSQL SHA-256
`1363341cac636e0dfa00900ab66df6cfcba6de1a48bca6a7b61821f82f2f3a29`, 685-object MinIO manifest
SHA-256 `1ea27f1ced8056ec39437665cf717a83dd3f59ff2323caeb67be15e56459a3bc`,
brand archive SHA-256 `5184e5ef669bd85261dde402c90ff0520d17cfd606c34a14185a1cd0aef710e7`,
code archive SHA-256 `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`,
unchanged env/release-env SHA-256 values, and nine prior-image tags with inventory SHA-256
`ad0d88b71a39a8f9afeaa6c0d0911f4e49d00e4bae71532051f301f8ff7886a7`.

After transfer and remote image load, the isolated no-network import probe failed because its
one-line probe rebound the FastAPI `app` name to the Python package before calling `openapi()`.
No active tag, source overlay, marker, one-shot, migration, environment, or data change followed.
The failure trap restored the prior tags; its relative Compose paths could not start services from
the protected stage directory, so recovery directly started only the existing prior containers in
dependency order, dispatcher last. The final 30-second recovery gate passed with all eight services
on the prior image at restart zero, exact prior source/markers/protected inputs, both flags false,
the stable ordinary vector and WeCom state above, zero actionable work, and bounded log/provider
counts `0:0:0:0`. Protected recovery evidence SHA-256 is
`bb5dbd36206b0da14b62381962eccdb31c46bf543557b06483d7ce04f9ccd208`.

This attempt made no Zhipu, Comfly, image-generation, or WeCom provider call and created no fixture,
acceptance database/bucket, enqueue, retry, resend, activation, frontend deploy, commit, or push.
Per the stop-on-failure boundary, no second release attempt is allowed in this run.

#### Retry checklist after independent review — not executed

The import-only defect is reproduced and corrected locally with this exact non-network probe:

```bash
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --entrypoint python "$candidate" -c '
from app.api_main import app as api_app
import app.worker_main as acquisition_worker
import app.governance_worker_main as governance_worker
import app.content_worker_main as content_worker
import app.wecom_dispatcher_main as wecom_dispatcher
from app.infrastructure.ai.zhipu import ZhipuImageTextRecognizer, _ImageOcrResponse
assert api_app.openapi()["openapi"]
assert all(module.__name__.startswith("app.") for module in (
    acquisition_worker, governance_worker, content_worker, wecom_dispatcher
))
' </dev/null
```

Any future operator script must be independently reviewed, copied as the sole tenth top-level file
in the protected stage, checked against its locally reviewed SHA-256, and remain mode 0600. Invoke
the fixed absolute remote path without local-variable expansion, for example
`ssh ... 'sudo -n bash -- /tmp/edu-ai-zhipu-release-c66aa62-RELEASE_ID/retry-default-off.sh' </dev/null`;
do not use a double-quoted `$script` command or stream the script through `ssh ... bash -s`. Its
fixed prologue and Compose invocation are:

```bash
set -Eeuo pipefail
umask 077
readonly app=/opt/edu-ai-lead-agent
readonly stage=/tmp/edu-ai-zhipu-release-c66aa62-RELEASE_ID
readonly backup=/var/backups/edu-ai/releases/RELEASE_ID-zhipu-ocr-bbox
readonly old_id=sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f
readonly new_id=sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2
compose=(docker compose --project-name edu-ai-lead-agent --project-directory "$app" \
  --env-file "$app/.env" --env-file "$app/.release.env")
"${compose[@]}" config --quiet </dev/null
```

Run the following sequence and stop on the first failed equality:

1. Re-fetch Codeup and repeat the local archive/image/OpenAPI/Alembic gates. Before execution,
   require the stage to contain exactly the original nine verified regular files plus the one
   reviewed operator script, no symlink or subdirectory, mode 0700 on the stage and mode 0600 on
   every file. On production, use
   only the absolute `compose` array above for `config`, `ps`, `stop`, `up`, `wait`, `exec -T` and
   `logs`, and redirect every Compose invocation from `/dev/null`. Never change the global working
   directory to the stage; use `(cd "$stage" && sha256sum -c artifacts.sha256)`.
2. Re-run the full read-only production preflight and stable baseline sample. Verify prior active
   image/source/markers, all ten active/shared tags and eight running containers on `old_id`, the
   loaded candidate absent from running containers, false flags, `120.0`, zero running/current
   actionable/nonterminal/unknown/duplicate-request work, historical queued `7:0`, protected
   env/release-env/brand/volume hashes, backup timer, capacity and secret-safe logs. Block if any
   scheduler can cross a provider-capable due boundary during restoration or the final sample.
3. Acquire the production backup lock before the first stop and hold it through the completed final
   gate or recovery. Capture exact existing service container IDs and install phase-aware recovery before
   the first stop. It must cover `ERR`, nonzero `EXIT`, `HUP`, `INT`, and `TERM`, preserve the first
   failure code, disable recursive traps, and distinguish `backup_ready`, `tags_changed`,
   `overlay_changed`, and `completed`. An early failure before `backup_ready` must only restart the
   untouched prior IDs; it must not try to read a partial backup.
   Quiesce exact IDs by direct `docker stop ... </dev/null`, dispatcher first and API last. The
   post-backup recovery path must begin with `cd "$app"`, conditionally restore exact code and
   markers only after host overlay began, restore the old shared and nine service tags only after
   retagging began, and either directly start each still-existing prior ID or use the absolute
   Compose array with `--no-build --no-deps --force-recreate </dev/null`. Verify restored source,
   markers, tags, images, flags, container health and ordering; restore dispatcher last.
4. Allocate a new release/backup ID and prove its release, PostgreSQL, MinIO, brand and nine rollback
   tag targets do not exist. Take a new manual backup under the already-held backup lock; do not call
   the registry-only standard wrapper or reuse `20260816T021614Z`.
   Dump PostgreSQL with `docker exec "$pg" pg_dump ... </dev/null >"$dump"`, validate the nonempty
   dump with the required stdin attachment
   `docker exec -i "$pg" pg_restore --list <"$dump" >/dev/null`, mirror and checksum MinIO, archive
   brand/env/release-env/markers/exact active code, and create nine unique prior-image tags. Mark
   `backup_ready=1` only after every catalog, content, manifest, mode, ownership, image-ID and
   protected checksum gate passes; retain but never consume a partial generation.
5. Recheck the protected transfer manifest and loaded image ID. Run the corrected candidate probe
   above before any active tag change. Verify labels, 165 exact image-source hashes, non-root user,
   imports, `pip check`, OCR route/Settings, OpenAPI and Alembic. Re-prove all active/shared tags are
   still `old_id`; only then set `tags_changed=1` and retag the shared and nine service tags, checking
   every tag resolves to `new_id`. The stage check remains in a subshell so recovery never inherits
   its directory.
6. Extract the 307-file source archive into a generated mode-0700 child, reject symlinks/extras,
   verify every source hash/path, then overlay only those files. Atomically write the full/short
   markers in `$app`; set `overlay_changed=1` before the first host write and prove exact source,
   marker modes/ownership, env/release-env/brand/volumes afterward. On any failure, the already
   armed phase-aware recovery restores and re-verifies prior code, markers, tags and services.
7. Run MinIO init and migration as isolated one-shots with `--no-build --no-deps`,
   `--abort-on-container-exit`, and `</dev/null`; require exited-zero, exact candidate migration
   image, Alembic `20260815_0021`, ten active sources and no durable delta.
8. Recreate API, then acquisition, governance and content services, and dispatcher last. Every
   `compose up` uses the absolute array,
   `--no-build --no-deps --force-recreate`, and `</dev/null`. Gate zero actionable queues and stable
   provider/delivery counters before and after each provider-capable worker or scheduler and before
   the dispatcher. Do not enter this step unless the maintenance timing gate proves no scheduler is
   due during the bounded restoration/final-sample window.
9. Require API/content Settings equality at
   `false:false:glm-ocr:10485760:1048576:120.0`, exact candidate/restart-zero services, protected
   inputs and historical queues, then run the final 30-second durable/provider/WeCom/log sample.
   Do not generate a fixture, enqueue, retry, resend, call any provider or enable either flag. Set
   `completed=1`, disarm recovery, and release the backup lock only after this gate passes.

Audit disposition: the corrected local probe passed. A production read-only audit confirmed the
candidate is loaded but inactive, the prior release is active and healthy, the stage manifest and
fresh rollback/protected/recovery hashes verify, and durable/WeCom/actionable vectors remain exact.
The original nine-file protected stage is reusable only after revalidation and after the reviewed
operator script becomes its sole tenth file. The `20260816T021614Z` rollback set remains valid
recovery evidence for the failed attempt, but writers resumed afterward: a new quiesced backup is
mandatory for a retry. The retry remains blocked until the exact generated script and every trap
branch are independently reviewed against this contract. After that review and separate release
authorization, one default-off retry may proceed; this audit authorizes neither execution nor a
provider call. No command in this checklist was executed against production.

### Offline-only exact retry driver

The independently requested hardening is implemented as the mode-0600 operator artifact
`research/default-off-release-driver.sh` (SHA-256
`29ee24ae9f7a8ccb9a845c7bd473d1b175a70180c6dc5f4e2652065346641a9b`). Its only production
entrypoint is `/usr/bin/bash "$stage/default-off-release-driver.sh" ... </dev/null` from the exact
`/opt/edu-ai-lead-agent` working directory. The driver rejects any other stage basename,
non-`/dev/null` stdin, extra/missing stage member, non-0600 member, non-0700 stage, self/archive/
manifest/image mismatch, relative Compose context, or rendered non-local application image. Every
Compose call supplies the fixed project name, project directory, compose file and both absolute env
files, and redirects stdin from `/dev/null`; every ordinary `docker exec` does likewise. The sole
stdin-attached exception is the required catalog proof
`docker exec -i "$postgres_id" ... pg_restore --list <"$dump"`.

The driver acquires `/var/lock/edu-ai-backup.lock` before the first exact-container stop and holds
the descriptor through success or recovery. It generates a collision-free backup directory and
nine rollback tags, completes/catalogs/checksums a fresh PostgreSQL/MinIO/brand/env/release-env/
marker/code/image rollback set, then sets `backup_ready=1`. It sets `tags_changed` and
`overlay_changed` before their first writes and `completed` only after the final stability gate.
`ERR`, every nonzero `EXIT`, `HUP`, `INT`, and `TERM` share a non-recursive recovery path. A failure
after the first stop but before `backup_ready` reads no partial backup and restarts only captured
prior containers; mid/late failures restore tags and then code/markers only when their phase flags
require it. API, scheduler and worker restoration is dependency ordered, with actionable/running/
unknown/durable/provider/WeCom gates between provider-capable boundaries and the dispatcher last.

Candidate validation occurs before active retag and includes exact labels/embedded source hash,
165-file image manifest, non-root runtime, `pip check`, the corrected `api_app` import probe,
default-off OCR Settings and `/layout_parsing` route, OpenAPI equality and Alembic head. Protected
env/release-env/brand/volume/source/marker/tag checks, the pinned 2026-08-16 ordinary baseline,
operator-supplied reviewed scheduler-safe window, active-source count, historical queued invariant,
secret-safe bounded logs and final 30-second stability are mandatory. The script contains no build,
SSH, fixture, provider, enqueue, retry, resend, or feature-enablement path.

The mode-0600 local harness `research/test-default-off-release-driver.sh` (SHA-256
`54620cfba8207f1968b9328ac2d96414ca03a820d45def939a81cb5b2ffb6283`) passed `bash -n`, static
forbidden-action/absolute-context gates, injected early/mid/late nonzero exits, TERM recovery, and
incomplete-recovery fail-closed behavior. The observed recovery orders were respectively
`services`, `tags -> services`, and `overlay -> tags -> services`; TERM preserved exit 143 and a
failed restore converted the process to terminal exit 125. ShellCheck is not installed in the local
environment. This work was entirely offline: it did not access SSH, production Docker, production
files, services, providers, or durable state and does not authorize running the driver.

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

## Authorized Phase 2.2 default-off retry preflight — stopped before transfer

- [x] Revalidated the untouched protected stage as mode 0700 with exactly nine pre-driver regular
  mode-0600 members: the eight targets declared by `artifacts.sha256` plus the manifest itself.
  The eight-target check, source/image sidecar checks, 307-file source manifest, 165-file image
  manifest, 821,122-byte source archive SHA-256
  `e516184eebdeb9b98c09cc3fecd98369012d75aba5763fdb16ed836b2d3390f9`, and 131,268,412-byte
  image bundle SHA-256 `db1cab9cc975e08d46aa0d47e35f81100d02ea0eb5df90ce8677cc23378119c4`
  all passed. The reviewed driver remained local and was not copied.
- [x] Revalidated the inactive candidate
  `sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2`
  under isolated tag `edu-ai-lead-agent:offline-c66aa62`, with exact revision
  `c66aa6217d137033118c552f3db11b2a1121d082`, dependency base
  `sha256:50fd2519fbc5aa204c45e76cb685d01aaea1656b998d3ed96c9ab6671b3b9374`,
  and pyproject SHA-256 `d32d7b8c8dd90b2e455dbfbadde65e56e01ab2d7981f79e39358da8b5943cd0f`.
  No running container used the candidate.
- [x] Re-read production as exact prior release
  `331a4942a84b36811cbbc4abff68bca2abc71f0c` / short `331a494` / image
  `sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`.
  All eight long-running services were running that image at restart zero, both flags remained
  false, API/content Settings remained `glm-ocr`, 10 MiB/1 MiB/120.0 seconds with text model
  `glm-5.2`, infrastructure was running, Alembic remained `20260815_0021`, and ten sources were
  active. The active 307-file source manifest is
  `/tmp/edu-ai-zhipu-release-331a494-20260815T153208Z/source-files.sha256`, SHA-256
  `c0953ba579690f99b55050c816130b7d16137283d9bb169f483d000029ab8a38`.
- [x] Re-read protected inputs without printing secrets: env/release-env SHA-256 values stayed
  `4ad88db853075ad8668a1c45bd2e1f4498256c2ece0903ab2fbe3ea40521efdc` /
  `5b58077644a21764cc3521c6689d562c645c62f0fff117c07264f7285398e0c2`, the 256-file brand
  aggregate stayed `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24`,
  and PostgreSQL/MinIO retained the expected named volumes. The backup timer was enabled/active,
  more than 58 GiB was free, and the bounded secret/provider/send log gate was clean.
- [ ] Do not transfer or invoke the exact reviewed driver. Fresh data was stable for 15 seconds at
  durable vector `36:182:36:13:4:59:157:35:44:35:391:25:47:0:0`, current-day vector `2:2:4`,
  provider/delivery tuple `391:47:35:44`, historical queued `7:0`, and zero running/unknown work,
  but actionable work was `0:0:0:0:0:1` and WeCom was `25:47:1:0:0:1`. The sole nonterminal row
  was an ordinary formal delivery queued with attempt zero for 12:30 China time and therefore
  violated the driver's hard zero-actionable gate.
- [ ] A second independent incompatibility also blocks the immutable driver: production retains
  the nine per-service tags as `edu-ai-lead-agent-<service>:latest`, while reviewed driver SHA-256
  `2190df29f7bbe59c903cd33237eae4068af633fd33c5010e2d2e890b3b0ecbfd` asserts, backs up,
  retags, and restores `edu-ai-lead-agent-<service>:local`. Those nine `:local` tags are absent;
  only shared Compose tag `edu-ai-lead-agent-backend:local` exists. Creating substitute tags by
  hand or editing the reviewed artifact would cross the authorized boundary.

The live slot schedules are 07:30, 12:30, and 18:30 China time with a 90-minute preparation lead,
so the next acquisition/content cron boundary after the noon run is 17:00. If ordinary automation
later makes the noon delivery terminal, any future attempt still requires a new stable baseline,
current MinIO aggregate, independently reviewed driver revision matching the actual retained tag
names, new exact SHA-256 authorization, and a safe-until timestamp before that boundary. This
preflight made no stage write, driver invocation, lock acquisition, service stop, backup, retag,
overlay, one-shot, provider call, enqueue/retry/resend, feature enablement, or delivery action.

### Offline tag-contract correction after blocked preflight

The driver was corrected offline to preserve the exact mixed production tag scheme: the shared
Compose image is `edu-ai-lead-agent-backend:local`, all nine backend/migration service tags are
`edu-ai-lead-agent-<service>:latest`, and every corresponding service `:local` tag must remain
absent. `SHARED_ACTIVE_TAG`, the service suffix constants, `TAG_SERVICES`, and dedicated active,
forbidden-local, and rollback tag functions now drive every preflight validation, protected prior
tag inventory, candidate retag, recovery retag, and final equality check. The fresh backup records
ten exact prior active tag identities separately from its nine generated rollback tags. Candidate
bundle validation still requires its sole isolated RepoTag and arms `tags_changed=1` before
`docker image load`, so a load failure cannot bypass tag recovery. The isolated candidate tag is
also rejected if it aliases the shared active tag, any service `:latest` tag, or any forbidden
service `:local` tag.

The revised mode-0600 driver SHA-256 is
`29ee24ae9f7a8ccb9a845c7bd473d1b175a70180c6dc5f4e2652065346641a9b`; the revised mode-0600
harness SHA-256 is `54620cfba8207f1968b9328ac2d96414ca03a820d45def939a81cb5b2ffb6283`.
The full fake harness proves mixed shared/local plus service/latest validation, absence of all nine
service/local tags, ten-entry prior inventory, bundle phase arming, candidate retag, and exact old
image restoration before services in both mid and late recovery. This correction resolves only the
script/tag mismatch. The observed attempt-zero 12:30 China-time delivery remains actionable, so
the hard zero-work preflight still blocks release. No checksum grants permission to transfer or
deploy; a fresh stable baseline, independent review, new authorization and safe window remain
mandatory. This correction used no SSH, production access, provider call, service action, or
durable mutation.
