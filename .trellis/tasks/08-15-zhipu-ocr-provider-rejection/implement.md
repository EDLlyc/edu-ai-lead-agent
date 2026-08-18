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

## Authorized default-off retry — failed closed before image load

- [x] After the ordinary noon delivery became terminal, a fresh 15-second gate passed at exact
  durable vector `36:182:36:13:4:59:157:35:44:35:391:25:49:0:0`, current-day `2:2:4`,
  actionable/running/unknown all zero, WeCom `25:49:0:0:0:1`, historical queued `7:0`, and
  provider/delivery tuple `391:49:35:44`. The exact reviewed driver was copied as the protected
  stage's sole tenth member and invoked once through its absolute-path/root/cwd/null-stdin contract.
- [x] The driver quiesced all eight application services and completed fresh rollback
  `20260816T044848Z-zhipu-ocr-default-off`. Protected manifest SHA-256 is
  `179c004951e911e5c435df92aa299608f1f488199ef397bca3e9d7df52d9371f`; PostgreSQL dump is
  10,041,130 bytes / `c14ea603766ca1467b5c1e9602d99baf63fef13699230f47b451848927f23d66`;
  the 708-file MinIO manifest is
  `704a6937016a07c2fe843611afb3088efe85fa96d6b3bc5cabe391e385f2f4a8`; brand/code archives are
  `4fb13a0ca7698adbd946a444a0bea8c18390c6397d6b6a33cbb6168034efe4dc` /
  `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`; active/rollback image
  inventories are `aeb0397afd7771fc2d17e766b42a693910545be98f73072c9b47f566a765ed1a` /
  `af320587843168bc565a6a3451aa3da9cde988dfb9b0866fc52183e64685bbc1`.
- [ ] The next gate failed before `docker image load`: the OCI-style archive records Config as
  `blobs/sha256/695d4b23d5cfa5a09ac156f9308b23d3e7615b342a00aad19c619bc62f30db0a`,
  while the driver required `<candidate-image-id>.json`, producing
  `image bundle config digest mismatch`. Recovery phase state was `backup_ready=1`,
  `tags_changed=0`, `overlay_changed=0`; no candidate tag, source, marker, one-shot or migration
  mutation began.
- [x] Driver recovery completed and independent verification found exact prior release
  `331a4942a84b36811cbbc4abff68bca2abc71f0c` /
  `sha256:aec802ded8ffbcfec0e4bb89a0a46565355684869b5b4e1ceb48b4d789ff916f`,
  all eight services running at restart zero, healthy infrastructure, prior markers/source, exact
  shared-plus-service tags, forbidden service-local tags absent, candidate running count zero,
  false flags, safe logs, and every fresh vector above unchanged. The mode-0600 safe driver log
  SHA-256 is `bf8e2f0368c32a6b21addec150c0e13a3097b1fe2443b5848e6f7aa23d7534cd`.

The single authorized invocation exited 1 and was not repeated. The protected ten-member stage and
fresh rollback remain retained; `release-result.txt` is absent because no release completed. No
OCR/Comfly/image-generation/WeCom provider call, fixture, enqueue/retry/resend, activation, commit
or push occurred. Independent review must reconcile the OCI/containerd bundle Config semantics
with the loaded candidate identity before any new execution authorization.

### Offline OCI/containerd archive-validator correction

The failed gate's identity semantics were reproduced without loading the image. The exact local
bundle is an OCI layout even though it also carries Docker-compatible `manifest.json`: its sole
`index.json` image-manifest descriptor and candidate ID are
`sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2`, while its config
descriptor/blob is independently
`sha256:695d4b23d5cfa5a09ac156f9308b23d3e7615b342a00aad19c619bc62f30db0a`. Treating the latter
as the candidate identity was the exact format-assumption defect.

The mode-0600 driver now exposes a load-before-mutation `validate_candidate_bundle` gate that
selects OCI only from the explicit paired `oci-layout`/`index.json` markers and otherwise validates
the supported classic form. OCI validation requires one exact index descriptor and RepoTag, binds
the descriptor digest to the candidate ID, checks descriptor media type/size and manifest blob
hash, binds both real containerd/OCI index annotations to that RepoTag, validates the config and
every ordered layer descriptor/blob by hash and size, requires the reviewed `linux/amd64` platform,
verifies ordered `rootfs.diff_ids` against the decompressed raw/gzip layers, and requires exact
agreement with `manifest.json` Config/Layers.
It rejects non-standard JSON, conflicting format markers, extra
images, extra/dangling blobs, duplicate descriptors or tar members, path traversal, unsafe names,
non-regular members, unexpected fields and member-count/size excess. The existing post-load image
identity, provenance labels, embedded-source, non-root, import/OpenAPI/pip/Alembic and default-off
gates remain unchanged; `tags_changed` is still armed before the actual load command.

The current driver SHA-256 is
`db4bc3b5d8ab9976392930f87f1ba6ac2b866f9c70fa8460e6d95a643fd28547`; the mode-0600 harness
SHA-256 is `ac7257f200d6ed231f693173052de6f19dc1b8bbc724e941b5e6d0d64b6601b9`. `bash -n` passed for
both. The full harness passed realistic two-layer OCI and supported-classic positives, the critical
candidate-manifest-vs-config regression, bundle phase arming, and descriptor/config/layer
hash/size/diff-ID, strict JSON/schema/media, exact index-annotation/RepoTag mapping,
index/manifest ordering, dangling/unsafe/duplicate/non-regular negatives along with all existing
signal, early/mid/late recovery and mixed-tag cases. The exact 126 MiB candidate
bundle passed the same validator-only function with its isolated tag and manifest digest; no
`docker load` occurred.
ShellCheck and gitleaks were not installed in the offline environment; the static
forbidden-action gates, full sandbox harness, targeted changed-shell secret scan and
`git diff --check` remained the available checks.

This was an offline-only correction: it did not access SSH, production, Docker services, providers
or WeCom, and did not transfer, quiesce, back up, retag, overlay, restart, enqueue, retry, resend,
build or enable either visual flag. The earlier ordinary attempt-zero noon delivery blocker and
its later terminal progression remain historical preflight evidence; the one authorized retry
still ended recovered before image load. Neither these new hashes nor the retained fresh rollback
set authorize another attempt. Reuse still requires exact durable-state equivalence, a fresh
independent review and explicit authorization; otherwise a new quiesced backup is mandatory.

## Authorized OCI-corrected default-off retry — recovered exit 1

- [x] Fresh 18-second production samples and the immediate invocation boundary retained durable
  vector `36:182:36:13:4:59:157:35:44:35:391:25:49:0:0`, current-day `2:2:4`, WeCom
  `25:49:0:0:0:1`, historical queued `7:0`, provider/delivery tuple `391:49:35:44`, and zero
  actionable/running/unknown work. Business date was `2026-08-16`; the reviewed
  `2026-08-16T08:45:00Z` safe-until gate retained 10,242 seconds. Exact prior image/source/
  markers/tags, eight restart-zero services, false flags, protected inputs, bounded logs and the
  fresh 708-object MinIO aggregate all passed.
- [x] Replaced only the old staged driver with the final mode-0600 artifact, SHA-256
  `db4bc3b5d8ab9976392930f87f1ba6ac2b866f9c70fa8460e6d95a643fd28547`. The protected stage
  remained mode 0700 with exactly ten mode-0600 regular members; source/image hashes and the
  307/165-file manifests remained exact. The exact OCI bundle passed the production explicit-path
  validator-only gate for isolated tag `edu-ai-lead-agent:offline-c66aa62` and candidate ID
  `sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2`. No harness was
  transferred.
- [x] Invoked the final driver exactly once as root from physical `/opt/edu-ai-lead-agent`, through
  its absolute protected-stage path with stdin `/dev/null`. It quiesced writers and completed new
  rollback `20260816T055519Z-zhipu-ocr-default-off` before advancing.
- [x] The fresh backup verified with protected-manifest SHA-256
  `0e1619252f8f8d7a88f42ef8f5ed4780f8f05c3c130b15320b571545dde4a13b`. PostgreSQL dump /
  526-line catalog SHA-256 values are
  `20062d931713c6c6bfbf6d79919ba9944c78f1ed3058dff0b2ce590fb777cb86` /
  `a91f6b2c397218870fe87b92babc5c9636e684c7301d25019e9fb07bd34b9284`; the catalog matched
  `pg_restore --list`. The 708-object MinIO manifest is
  `704a6937016a07c2fe843611afb3088efe85fa96d6b3bc5cabe391e385f2f4a8`. Brand manifest,
  brand archive and active-code archive hashes are
  `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24`,
  `4fb13a0ca7698adbd946a444a0bea8c18390c6397d6b6a33cbb6168034efe4dc`, and
  `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`; prior active-tag /
  unique rollback-image inventory hashes are
  `aeb0397afd7771fc2d17e766b42a693910545be98f73072c9b47f566a765ed1a` /
  `a5f3c632ac065cb1c665b289799ee88b99abe8ede3c90f79b531675b2bd77ade`.
- [ ] After bundle load armed `tags_changed=1`, the post-load image-source check failed as
  `candidate image source manifest mismatch`. Exact root cause: the driver's runtime collection
  produced 163 lines, while the frozen artifact contains 165; its collection omitted the exact
  top-level `alembic.ini` and `pyproject.toml` entries. This is a driver manifest-scope defect, not
  an OCI identity or candidate-content drift. Phase state was `backup_ready=1`,
  `tags_changed=1`, `overlay_changed=0`, so no host overlay, one-shot, migration or candidate
  service restoration occurred.
- [x] Phase-aware recovery restored prior tags/services, logged `recovery completed`, and the one
  invocation exited 1. Independent 16-second samples retained the exact baseline and provider/
  delivery tuple, with zero actionable/running/unknown work. Prior source/markers/tags, all eight
  restart-zero services, false flags, protected inputs, infrastructure and bounded logs passed;
  candidate running count was zero. The protected stage and fresh rollback remain retained and
  `release-result.txt` is absent. The driver was not run a second time.

The target was not deployed. Model-invocation, image-attempt and WeCom-attempt counts had zero
delta, so the retry caused no Zhipu OCR, Comfly, image-generation or Enterprise WeChat provider
call. No fixture, enqueue, retry, resend, feature enablement, commit or push occurred. Execution is
stopped pending the separately owned offline driver fix and a new explicit authorization.

### Offline post-load 165-file manifest correction

The post-load failure was reproduced locally without loading or modifying the image. The prior
runtime command returned 163 entries and the frozen manifest returned 165; the exact set difference
was only `alembic.ini` and `pyproject.toml`. Both root files already exist in candidate
`sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2` and match their
frozen hashes, so neither the candidate nor the reviewed expected count was changed.

The driver now uses `assert_candidate_source_manifest` for the network-none, read-only,
capability-dropped collection. It explicitly requires and emits the two non-symlink root files,
adds regular `*.py`/`*.html` files below non-symlink `app/` and `alembic/`, and sorts their
NUL-delimited names under an exported `LC_ALL=C` before empty-safe hashing. The extracted
`validate_candidate_source_manifest` function parses both observed and frozen manifests as the
exact safe scope, requiring 165 unique deterministically ordered entries, both roots and exact
path/hash equality. Missing roots, replaced/extra paths, duplicates, unsafe or whitespace paths,
hash drift and count drift fail before active retag or source overlay. The remaining post-load
identity, provenance, non-root, import, pip, OCR route/Settings, OpenAPI and Alembic gates are
unchanged.

The final mode-0600 driver SHA-256 is
`2430f8c1f54ad4db482e69b216b49eeb42df5bb630fe1603745d7358f485fefc`; the final mode-0600
harness SHA-256 is `233c4b68f73639d1973f2eafb29d6ac109f2ac17ebeeeb01acd2275cbcbfb8bc`.
Both passed `bash -n`. The complete fake harness now executes the real manifest collection branch
with fake Docker output and fail-closed exact runtime-argument checks: the legacy 163-entry form
fails through `assert_candidate_source_manifest`, exact 165 passes, the temporary observed
manifest is EXIT-cleaned, and missing-root, root-hash, extra/replaced-path, whitespace/traversal/
absolute/backslash/newline/scope/suffix/hash/order and duplicate cases fail. All existing OCI,
rootfs-diff-ID, strict-JSON, annotation/tag, bundle-arming, signal/recovery and mixed-tag cases also
pass. A local exact-candidate manifest-only positive passed with `--network none`, `--read-only`,
`--cap-drop ALL` and `no-new-privileges`; the exact old command independently produced 163 entries
and was rejected by the 165-entry validator. Neither probe performed a load.

This correction was offline/local only. It did not access SSH or production and caused no image
load, provider/WeCom call, transfer, service stop, backup, retag, overlay, restart, enqueue, retry,
resend, build or flag change. The protected `20260816T055519Z-zhipu-ocr-default-off` rollback and
its recovered production evidence remain recorded above, but these new hashes do not authorize a
retry or establish current durable-state equivalence. A future execution requires a fresh
independent review and explicit authorization.

## Authorized final default-off retry — import probe recovered exit 1

- [x] Verified final local driver/harness SHA-256 values
  `2430f8c1f54ad4db482e69b216b49eeb42df5bb630fe1603745d7358f485fefc` /
  `233c4b68f73639d1973f2eafb29d6ac109f2ac17ebeeeb01acd2275cbcbfb8bc`, mode 0600 and
  `bash -n`. The exact local OCI bundle and loaded candidate passed the corrected 165-entry
  manifest smoke including `alembic.ini` and `pyproject.toml`.
- [x] Fresh production samples at `2026-08-16T06:17:13Z` and `06:17:31Z` retained durable vector
  `36:182:36:13:4:59:157:35:44:35:391:25:49:0:0`, current-day `2:2:4`, WeCom
  `25:49:0:0:0:1`, historical queued `7:0`, provider/delivery tuple `391:49:35:44`, and zero
  actionable/running/unknown work. Business date, exact prior services/source/markers/tags, false
  flags, protected inputs, clean logs and fresh 708-object MinIO state all passed. The final
  invocation sample retained 8,735 seconds before the `2026-08-16T08:45:00Z` safe-until boundary.
- [x] Replaced only the staged driver. The stage remained mode 0700 with exactly ten mode-0600
  files, exact source/image archives, 307/165-file manifests and artifact sidecars. The new remote
  explicit-path OCI validator and network-none/read-only exact 165-entry manifest-only probe both
  passed; candidate running count returned to zero before main invocation.
- [x] Invoked the final driver exactly once as root from physical `/opt/edu-ai-lead-agent`, through
  its absolute protected-stage path with stdin `/dev/null`. It quiesced writers and completed new
  rollback `20260816T062022Z-zhipu-ocr-default-off`.
- [x] The fresh backup verified with protected-manifest SHA-256
  `6e301f7d3a0190e1192c744b520845b1956d0fd3034ea8099bf2fb34e3385c8f`. PostgreSQL dump /
  526-line catalog hashes are
  `dec08cf2b184785fbb84403d93f0a0878571a69d34d4fcf9f25463247e15a4b5` /
  `e22c1c6b6614836c046b60fec118eab37f2802d3c643e7ac845d5183593f8751`; the catalog matched
  `pg_restore --list`. MinIO manifest remained
  `704a6937016a07c2fe843611afb3088efe85fa96d6b3bc5cabe391e385f2f4a8` for 708 objects. Brand
  manifest/archive and active-code archive remained
  `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24` /
  `4fb13a0ca7698adbd946a444a0bea8c18390c6397d6b6a33cbb6168034efe4dc` /
  `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`. Prior active-tag /
  unique rollback inventories are
  `aeb0397afd7771fc2d17e766b42a693910545be98f73072c9b47f566a765ed1a` /
  `3cd2d4a0d1f388e3156eed872506511be2201c92bf21bb0a5f47757b110419bf`.
- [ ] After bundle load armed `tags_changed=1`, the post-load, pre-overlay import gate failed with
  `ModuleNotFoundError: No module named 'app.acquisition_scheduler_main'`. The repository and exact
  candidate manifest expose acquisition scheduler entrypoint `app.scheduler_main`; no
  `app/acquisition_scheduler_main.py` exists. The driver probe therefore references a nonexistent
  module. Phase state was `backup_ready=1`, `tags_changed=1`, `overlay_changed=0`; no host overlay,
  one-shot, migration or candidate service restoration occurred.
- [x] Phase-aware recovery restored prior tags/services, logged `recovery completed`, and the one
  invocation exited 1. Independent samples at `06:22:32Z` and `06:22:49Z` retained every vector
  and provider/delivery counter exactly. Prior release/image/source/markers/tags, eight restart-zero
  services, false flags, protected inputs, infrastructure and bounded logs passed; candidate
  running count was zero. `release-result.txt` is absent and the driver was not rerun.

The target was not deployed. Model-invocation, image-attempt and WeCom-attempt counts had zero
delta, so no Zhipu OCR, Comfly, image-generation or Enterprise WeChat provider call occurred. No
fixture, enqueue, retry, resend, feature enablement, commit or push occurred. Execution is stopped
pending a separately reviewed import-probe correction and new explicit authorization.

### Offline Compose-bound import-probe correction

The recovered failure was reproduced on the exact local candidate: importing the driver's stale
`app.acquisition_scheduler_main` returned nonzero because no such module exists. Repository and
Compose inspection binds the eight long-lived entrypoints to API `app.api_main:app` and seven
modules `app.scheduler_main`, `app.worker_main`, `app.governance_scheduler_main`,
`app.governance_worker_main`, `app.content_scheduler_main`, `app.content_worker_main` and
`app.wecom_dispatcher_main`.

The driver now defines `API_ENTRYPOINT_MODULE` and ordered `LONG_LIVED_ENTRYPOINT_MODULES` once.
The candidate import probe receives those constants as arguments, uses `importlib`, and requires
the imported names to equal the complete unique list; it also calls `openapi()` on the `app` object
obtained from the exact API module. No service-name-derived alias remains. The harness derives all
eight Compose `*app-runtime` application services and fails unless they equal `APP_SERVICES` and
their API/seven module values equal the driver constants. It runs the complete
`assert_candidate_image` path through fake image-inspect/run arguments whose every assertion
returns nonzero explicitly, avoiding conditional/command-substitution `errexit` self-proof.

The exact local full-gate smoke then found one further stale handwritten path: the driver named
nonexistent migration `20260815_0021_add_image_ocr_delivery_fields.py`, while the candidate's valid
revision lives in `20260815_0021_visual_controlled_diversity.py`. The gate now passes
`EXPECTED_ALEMBIC_HEAD` into the candidate, requires exactly one matching declaration line and
requires the complete `alembic heads` output to equal its one expected line. Filename drift and an
additional head both fail.
The corrected full smoke passed exact image/tag identity and provenance labels, the 165-file
manifest, all eight entrypoints, non-root/default-off Settings, `pip check`, OCR route construction,
package-shadow exclusion, OpenAPI equality and Alembic under network-none/read-only/cap-drop/
no-new-privileges constraints. No image load occurred.

The final mode-0600 driver SHA-256 is
`c3f716bee66dcd64d328fc655bac26e3dfcdc1f052cb335451f4a411d9e74ad4`; the final mode-0600
harness SHA-256 is `c01a63c5141bd49a9ebabfdcaa8cffd218a0dc0eded402fa1437758e21225aec`.
Both pass `bash -n`; the full harness passes Compose-entrypoint binding, strict fake full-candidate
gate, manifest/archive/tag/recovery and all prior failure-injection cases.

This correction was offline/local only. It did not access SSH, production, providers or WeCom and
performed no load, transfer, quiesce, backup, retag, overlay, restart, enqueue, retry, resend, build
or feature change. The retained `20260816T062022Z-zhipu-ocr-default-off` backup/recovery evidence
above remains unchanged. These hashes authorize no retry; current state gates, independent review
and explicit authorization remain mandatory.

## Authorized c3f716 default-off retry — source-mode recovered exit 1

- [x] Verified final mode-0600 driver/harness SHA-256 values
  `c3f716bee66dcd64d328fc655bac26e3dfcdc1f052cb335451f4a411d9e74ad4` /
  `c01a63c5141bd49a9ebabfdcaa8cffd218a0dc0eded402fa1437758e21225aec` and `bash -n` without
  repeating the already reviewed full harness/candidate gate.
- [x] Fresh samples at `2026-08-16T06:46:43Z` and `06:47:00Z` retained durable vector
  `36:182:36:13:4:59:157:35:44:35:391:25:49:0:0`, current-day `2:2:4`, WeCom
  `25:49:0:0:0:1`, historical queued `7:0`, provider/delivery tuple `391:49:35:44`, and zero
  actionable/running/unknown work. Exact prior services/source/markers/tags, false flags,
  protected inputs, clean logs and fresh 708-object MinIO state passed. The immediate invocation
  boundary retained 6,976 seconds before `2026-08-16T08:45:00Z`.
- [x] Replaced only the staged driver. The stage remained mode 0700 with exactly ten mode-0600
  members, source/image archives and 307/165-file manifests unchanged; remote driver hash and
  `bash -n` passed. Invoked it exactly once as root from physical `/opt/edu-ai-lead-agent`, by its
  absolute protected-stage path with stdin `/dev/null`.
- [x] The driver quiesced writers and completed fresh rollback
  `20260816T064939Z-zhipu-ocr-default-off`. Protected-manifest SHA-256 is
  `1c4af079eef19cd3bab42bc40d5f865be13ca7b1433e46423c860fa8ff5209cd`. PostgreSQL dump /
  526-line catalog hashes are
  `6ffcda7aacc5a4e5b9d4a372c8cc31faf44de4bf3eb776f009a631f00439476b` /
  `caacbcff7d186df52553c39e205c11ae442bd84c1bb195e67509e8d43e50027a`; the catalog matched
  `pg_restore --list`. MinIO manifest remained
  `704a6937016a07c2fe843611afb3088efe85fa96d6b3bc5cabe391e385f2f4a8` for 708 objects. Brand
  manifest/archive and active-code archive remained
  `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24` /
  `4fb13a0ca7698adbd946a444a0bea8c18390c6397d6b6a33cbb6168034efe4dc` /
  `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`. Prior active-tag /
  unique rollback inventories are
  `aeb0397afd7771fc2d17e766b42a693910545be98f73072c9b47f566a765ed1a` /
  `31ba23e359066a9440846704cfe92ecb9f4d181aedfb323da658ece75a85e655`.
- [ ] Candidate post-load gates reached and `pip check` passed. After active retag armed
  `tags_changed=1`, host overlay armed `overlay_changed=1` and failed as `source member mode is
  outside the reviewed allowlist`. The frozen source archive encodes all 307 regular files outside
  the driver's `0600|0644|0700|0755` allowlist: 295 are mode 0664 and 12 are mode 0775. The sorted
  manifest's first member, `.env.example`, is already 0664, so overlay fails on the first member.
  Content/path hashes are unchanged; this is an archive-mode/driver-policy mismatch. No marker,
  one-shot, migration or candidate service restoration occurred.
- [x] Recovery restored the backed-up prior overlay, active tags and services, logged `recovery
  completed`, and the single invocation exited 1. Independent samples at `06:51:53Z` and
  `06:52:09Z` retained every vector/provider counter. Exact prior source/markers/tags, eight
  restart-zero services, false flags, protected inputs, infrastructure and logs passed; candidate
  running count was zero, `release-result.txt` was absent, and no second run occurred.

The target was not deployed. Model-invocation, image-attempt and WeCom-attempt counts had zero
delta, so no Zhipu OCR, Comfly, image-generation or Enterprise WeChat provider call occurred. No
fixture, enqueue, retry, resend, activation, commit or push occurred. Execution is stopped pending
a separately reviewed source-mode policy/normalization correction and new explicit authorization.

### Offline canonical source-mode correction

Exact local archive inspection reproduced the recovered failure without production access: all
307 regular source members are noncanonical only because of group-write inheritance—295 are 0664
and 12 are 0775—and the legacy allowlist rejects the first sorted member, `.env.example`. Paths and
content hashes are unchanged.

The driver now validates the archive's complete regular-file mode set during local extraction,
before production preflight, quiesce or backup. It accepts only 0644/0664 as canonical 0644 and
0755/0775 as canonical 0755, writes sorted exact 307-path mode evidence, and verifies the extracted
tree and the current destination are regular non-symlink files in the expected executable class.
Unsupported modes, special bits, world-write, duplicates, unsafe paths, path-set drift and
non-regular members fail closed. Overlay iterates only this file evidence and calls `install` with
the canonical 0644/0755 mode; no group-write bit or directory is preserved.

The full fake harness covers canonical and group-writable positives; 0600, 0700, 0666, 0777,
setuid, setgid, sticky and unknown-mode negatives; extracted-mode and destination executable-class
drift; and strict fake `install -m 0644/0755` calls. It retains the complete candidate,
OCI/classic archive, tag and early/mid/late recovery gates. The exact frozen archive passes the new
preflight-only validator with `canonical_0644=295`, `canonical_0755=12` and 307 evidence lines;
the former allowlist rejects it as expected.

Initial implementation mode-0600 SHA-256 values before independent review were
`870eb45bef00bd927aa270aa737780b745c1db4300347fb295d72ef2af961d6e` for the driver and
`d6c2758de04a419f642d707a24a15bbcf2e20a6ebebb6a18c96db36a369a712b` for the harness.

Independent review found and fixed two additional pre-extraction/overlay gaps. Directory members,
including an explicit root member, now accept only 0755/0775 and reject world-write, special and
encoded type bits before `tar --same-permissions`. Source and destination files are anchored to
their physical absolute roots, preventing a nested ancestor symlink from escaping the reviewed
tree; after `install`, exact canonical mode and owner/group are rechecked before the final manifest
hash. Installation targets a generated root-only sibling and atomically replaces the destination,
so a final-component symlink race cannot redirect `install`. The harness adds real directory-mode
headers, unsafe mode-evidence syntax/order/path-set
cases, a real local `/usr/bin/install` result, a successful no-op fake that must fail, and a nested
destination symlink whose target remains unchanged. The exact 307-file archive still passes with
`canonical_0644=295` and `canonical_0755=12`.

Final independently reviewed mode-0600 SHA-256 values are
`0074ca60fa46a64a16957f0ff684058ed62bb4f5d0466b85b7fb6d57339cba1c` for the driver and
`7563e97eeb6778f60d104dee8ee7f40a5027999f6bb20ce8bcc881962e1865da` for the harness.

This was offline/local only: no SSH, production, Docker load, transfer, quiesce, backup, retag,
overlay, restart, provider/WeCom access, enqueue, retry, resend, build or flag change occurred. The
retained `20260816T064939Z-zhipu-ocr-default-off` backup/recovery evidence above is unchanged. The
artifact builder should normalize future source archives to 0644/0755; this compatibility gate does
not authorize a retry or deployment.

## Authorized 0074ca retry — pre-backup active-mode mismatch

- [x] Verified final local driver/harness SHA-256 values
  `0074ca60fa46a64a16957f0ff684058ed62bb4f5d0466b85b7fb6d57339cba1c` /
  `7563e97eeb6778f60d104dee8ee7f40a5027999f6bb20ce8bcc881962e1865da`, mode 0600 and
  `bash -n`, without repeating the independently reviewed harness/full candidate tests.
- [x] Fresh samples at `2026-08-16T07:21:42Z` and `07:22:00Z` retained durable vector
  `36:182:36:13:4:59:157:35:44:35:391:25:49:0:0`, current-day `2:2:4`, WeCom
  `25:49:0:0:0:1`, historical queued `7:0`, provider/delivery tuple `391:49:35:44`, and zero
  actionable/running/unknown work. Exact prior services/source/markers/tags, false flags,
  protected inputs, clean logs and fresh 708-object MinIO state passed. The immediate invocation
  boundary retained 4,874 seconds before `2026-08-16T08:45:00Z`.
- [x] Replaced only the staged driver. The stage remained mode 0700 with exactly ten mode-0600
  members, source/image archives and 307/165-file manifests unchanged; remote hash and `bash -n`
  passed. Invoked it exactly once as root from physical `/opt/edu-ai-lead-agent`, by its absolute
  protected-stage path with stdin `/dev/null`.
- [ ] Driver preflight mapped the exact archive to 295 canonical 0644 and 12 canonical 0755 files,
  then `assert_previous_source` failed as `source mode class differs from the canonical contract`.
  State was `backup_ready=0`, `tags_changed=0`, `overlay_changed=0`: the lock/quiesce/fresh-backup,
  image load, retag, overlay, one-shot, migration and service-restoration phases did not begin.
  Recovery completed and the invocation exited 1; it was not run again. No fresh backup ID or
  checksum exists for this attempt, and `20260816T064939Z-zhipu-ocr-default-off` remains history
  only.
- [x] Independent samples at `07:24:58Z` and `07:25:15Z` retained every vector and provider/
  delivery counter exactly. Prior release/image/source/markers/tags, eight restart-zero services,
  false flags, protected inputs, infrastructure and logs passed; candidate running count was zero.
- [x] A separately authorized one-shot read-only diagnosis streamed exact canonical evidence from
  the stage driver's source-only pure validators into the 307 active destinations. Results were
  295 current 0600 versus canonical 0644 plus 12 current 0700 versus canonical 0755: zero matches,
  307 mismatches. Every destination was an `ubuntu:ubuntu` regular file whose realpath remained
  inside physical `/opt/edu-ai-lead-agent`; the first sorted mismatch was `.env.example` at
  0600/0644. Only 20 bounded mismatch rows were emitted, with no content/hash/env output and no
  remote temporary file or mutation.

The target was not deployed. Model-invocation, image-attempt and WeCom-attempt counts had zero
delta, so no Zhipu OCR, Comfly, image-generation or Enterprise WeChat provider call occurred. No
fixture, enqueue, retry, resend, activation, backup, commit or push occurred. Production access is
stopped pending an independently reviewed active restrictive-mode compatibility decision and new
explicit authorization.

### Offline restrictive destination-mode preservation correction

The pre-backup failure and its separately authorized read-only diagnosis remain the evidence
boundary: candidate semantic evidence is 295 mode 0644 plus 12 mode 0755, while all 307 current
destinations are stricter—295 mode 0600 plus 12 mode 0700—with regular `ubuntu:ubuntu` paths anchored
inside the application root. No production mutation or fresh backup occurred in that attempt.

The driver now separates candidate semantics from destination access policy. Archive/extracted
files still accept only 0644/0664 -> semantic 0644 and 0755/0775 -> semantic 0755. Existing
destinations accept only 0600/0644 for non-executable or 0700/0755 for executable content; group/
world-write, special, unknown and class-mismatched modes fail. Before quiesce, exact sorted evidence
binds each candidate semantic/path to its exact destination mode after owner/group and physical
realpath checks. Overlay validates that binding again, rejects mode or ownership TOCTOU drift,
installs into a root-only sibling using the preserved destination mode, atomically replaces the
existing path, and then verifies realpath, exact mode, owner/group and byte equality. It never adds
a path and never broadens 0600/0700 to 0644/0755.

The full fake harness passes strict and canonical destinations, mixed per-file preservation,
destination evidence tampering, group/world-write, special/unknown/class mismatch, post-preflight
mode drift, no-op install and nested symlink negatives. Its production-shaped 307-file case proves
the old exact comparison mismatches all 307 candidate/destination modes, while the corrected
semantic binding installs exact candidate bytes and retains 295 mode 0600 plus 12 mode 0700. All
existing full-candidate, OCI/classic, tag and early/mid/late/signal recovery gates remain green.
The exact local archive plus a synthetic restrictive destination passes preflight-only with the
same 295/12 mapping and 307 historical exact-mode mismatches.

Initial implementation mode-0600 SHA-256 values before independent least-privilege review were
`03e3fb11808d789cc9a6a6b8d5fcf48f4d42147f14fb78be62c5416c0771f013` for the driver and
`aafbffeb15e8e7a2e7d0694f37500410df9925a457776067e5389f725a1448e6` for the harness.

Independent review made destination evidence self-contained by binding owner/group on every
semantic-mode/exact-mode/path row. It moved install temporaries out of the application-writable
tree into the physical root-owned non-writable parent, requires root:root mode 0700 and the same
destination filesystem before install and replacement, and retains cleanup on every trapped
failure. The harness now uses real 0664/0775 modes in its 307-file candidate, rejects ownership
drift and evidence ownership tampering, rejects escaped/non-root temporaries, proves zero temporary
residue, and injects a final-component symlink immediately before `mv -T` to prove the external
target is unchanged. The exact frozen archive installed over a generated restrictive destination
and passed all 307 hashes with 295 mode 0600 and 12 mode 0700.

Final independently reviewed mode-0600 SHA-256 values are
`bcbe4dd7b3e580d7e025f3fb33cedab486d7d39f7164b653b9b0586c8d6fee1a` for the driver and
`36038d89d0a1cc9918466c7b1692867f76487097618bacd5d59a32a09ae9df82` for the harness.
This correction authorizes no retry or deployment.

## Authorized bcbe4d retry — trusted-parent recovered exit 1

- [x] Verified final local driver/harness SHA-256 values
  `bcbe4dd7b3e580d7e025f3fb33cedab486d7d39f7164b653b9b0586c8d6fee1a` /
  `36038d89d0a1cc9918466c7b1692867f76487097618bacd5d59a32a09ae9df82`, mode 0600 and
  `bash -n`, without repeating independently reviewed offline tests.
- [x] Fresh samples at `2026-08-16T08:09:43Z` and `08:10:01Z` retained durable vector
  `36:182:36:13:4:59:157:35:44:35:391:25:49:0:0`, current-day `2:2:4`, WeCom
  `25:49:0:0:0:1`, historical queued `7:0`, provider/delivery tuple `391:49:35:44`, and zero
  actionable/running/unknown work. Exact prior services/source/markers/tags, false flags,
  protected inputs, clean logs and fresh 708-object MinIO state passed. The immediate invocation
  boundary retained 2,002 seconds before `2026-08-16T08:45:00Z`.
- [x] Replaced only the staged driver. Exact ten-member protection, source/image archives and
  307/165-file manifests remained unchanged; remote hash and `bash -n` passed. Invoked it exactly
  once as root from physical `/opt/edu-ai-lead-agent`, by its absolute protected-stage path with
  stdin `/dev/null`.
- [x] The driver quiesced writers and completed fresh rollback
  `20260816T081242Z-zhipu-ocr-default-off`. Protected-manifest SHA-256 is
  `d3eaf7fab7130ff92e404f34955f7e8e16b3baa48ac6a7a576cd5799a2f2dfa0`. PostgreSQL dump /
  526-line catalog hashes are
  `dfe5a8fbb841368a30cb3da67227e6370c44e76250df7932a7ae76443cb9746b` /
  `945ac4b019261c0e78317cd1b148c167eafc83b558b69edaf2be9b081bab4199`; the catalog matched
  `pg_restore --list`. MinIO manifest remained
  `704a6937016a07c2fe843611afb3088efe85fa96d6b3bc5cabe391e385f2f4a8` for 708 objects. Brand
  manifest/archive and active-code archive remained
  `7ddb17cf32426ddd1a5e586e63d8dd6b4641cf29dd9a9519313a088117528e24` /
  `4fb13a0ca7698adbd946a444a0bea8c18390c6397d6b6a33cbb6168034efe4dc` /
  `797d347837410b45bdb74c57bf3311ee69c301e7ba40da3d2fd167fc9549a057`. Prior active-tag /
  unique rollback inventories are
  `aeb0397afd7771fc2d17e766b42a693910545be98f73072c9b47f566a765ed1a` /
  `5ce7d88b0755db41a61340bd30f4cac561e59b77ceaf5217020b968bdbc74926`.
- [ ] Candidate gates reached and `pip check` passed. Atomic overlay then failed as `trusted install
  parent ownership or mode is unsafe`, with `backup_ready=1`, `tags_changed=1`,
  `overlay_changed=1`. No one-shot, migration or candidate service restoration began. Recovery
  restored prior overlay/tags/services, logged `recovery completed`, and the one invocation exited
  1; it was not rerun.
- [x] Independent samples at `08:14:56Z` and `08:15:12Z` retained every vector/provider counter.
  Exact prior source/markers/tags, eight restart-zero services, false flags, protected inputs,
  infrastructure and logs passed; candidate running count was zero and `release-result.txt` absent.
- [x] Read-only stat diagnosis proved the driver derives temp parent `/opt` from destination root
  `/opt/edu-ai-lead-agent`. `/opt` is physical non-symlink directory mode 0750 owned
  `ubuntu:ubuntu` (uid/gid 1000:1001), while the driver requires uid/gid 0:0; both paths are on
  device 64770. A second bounded query found mechanical same-filesystem trust candidates
  `/var/backups/edu-ai/releases` root:root 0700, `/var/backups/edu-ai` root:root 0700 and
  `/var/backups` root:root 0755. `/var/tmp` and `/tmp` are root:root 1777 and fail. No contents were
  listed and neither query created a temporary file or mutation.

The target was not deployed. Provider/delivery counters had zero delta; no OCR, Comfly,
image-generation or Enterprise WeChat call, fixture, enqueue, retry, resend, activation, commit or
push occurred. Production access is stopped pending an independently reviewed trusted-parent design
and new explicit authorization.

### Offline fixed trusted backup-root correction

Atomic install now uses fixed `SOURCE_INSTALL_TMP_ROOT=${BACKUP_ROOT}` rather than `/opt`. A
pre-stop gate requires the exact physical non-symlink root to be root:root 0700, same-device and
free of any reserved-prefix object; scan errors fail closed without exposing entry names. Each
generated name has an exact six-alphanumeric suffix, is revalidated before `mv -T`, and is removed
on success or only through physical-direct-child trap cleanup; rollback names cannot collide.

The full harness passes a production-shaped non-root-0750 application ancestry with separate
root-owned backup root and real mode-0600 atomic install. Old-derived, missing, symlink, non-root,
0750, 1777, mocked cross-device, reserved file/symlink/long-prefix residue and scan failures fail;
cleanup preserves backup/unrelated paths and refuses a symlink root. Existing
307/full-candidate/OCI/recovery gates remain green. Final mode-0600 hashes: driver
`189f2dc1370544b3a57bd5fdbfd471e9e2066045a94ba336d06bd4aeb28b2072`; harness
`212fa5b535ddd7c6f64826a1b6828d0e1fd9260daeee92442c3ad8b92d876fef`. The 081242 evidence is
unchanged and these hashes authorize no retry.

## User-authorized final fast-path production release

- [x] Entered strict read-only monitoring because the pre-17:00 maintenance window was below the
  900-second boundary. At `17:00:01` CST ordinary automation created the evening acquisition run;
  acquisition completed 10/10, governance completed 19 succeeded plus 2 review-required jobs, and
  the slot completed with `selected=0`, `unfilled=3`, and zero delivery windows. This typed
  no-delivery result was terminal without manual enqueue/retry/send. Ordinary governance changed
  the provider tuple from `391:49:35:44` to `394:49:35:44` before release authorization was used.
- [x] Independent samples at `2026-08-16T09:05:38Z` and `09:05:53Z` retained durable/provider/WeCom
  vectors `37:184:37:13:5:59:157:35:44:35:394:25:49:0:0` / `394:49:35:44` /
  `25:49:0:0:0:1`, with actionable/running/unknown all zero and the same `1:0:3` evening-slot /
  zero-window result.
- [x] The user explicitly replaced the complex-driver execution with one fast path. Fresh
  preflight confirmed exact protected stage membership (10 files, all mode 0600), source archive
  `e516184eebdeb9b98c09cc3fecd98369012d75aba5763fdb16ed836b2d3390f9`, 307-entry source
  manifest `a6a7271fd08a9176d98fa317a46535e7921c7936974bd67d188e6cd1518d3657`, inactive candidate
  `sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2` with exact c66
  revision, prior aec802 services restart-zero, false flags, healthy API/infrastructure, Alembic
  `20260815_0021`, and ten active sources. The fast path did not repeat OCI/full-candidate/307-
  topology gates and did not invoke the complex driver.
- [x] Acquired the backup lock, stopped the eight application services in dispatcher-to-API order,
  and retained exact zero vectors. Fresh unique backup
  `20260816T091212Z-zhipu-ocr-fast-default-off` contains a PostgreSQL custom dump and validated
  `pg_restore --list` catalog, the current 307-file source archive/manifest, protected env/release/
  markers, the ten prior active-tag identities, and ten unique rollback tags. SHA-256 values are:
  protected manifest `2721c71d08842f301ca8e0de86cf1273ec6c1c79cc20137cfd736ff0efcb3e74`,
  PostgreSQL dump `a0b5bee39db44af9df59d99d40d9065b42ebc5ab07aba0053c5af288eaae353b`, catalog
  `48a575e6ed936e4fcd9e357da6120a08a3c9df7a8d733dc83e68f905c19fa121`, and prior-source
  archive `3cbaf789b53fcbe6b2ec4b8671286f01f009cb83563e837f7c7a24e79e8987f4`. Per authorization,
  no fresh MinIO/brand mirror was made; the retained full rollback evidence remains available.
- [x] With root `umask 077`, overlaid the validated archive at physical
  `/opt/edu-ai-lead-agent` using `tar --no-same-owner --no-same-permissions`, verified all 307
  hashes, wrote full/short c66 markers, and retagged the exact candidate to the shared active tag
  plus nine service `:latest` tags. `backend-migrate` ran no-build/no-deps/force-recreate, exited
  zero, and retained Alembic `20260815_0021`; MinIO init was unnecessary and was not run.
- [x] Restored API, acquisition, governance and content services in dependency order and the
  dispatcher last. All eight services use the exact candidate image with restart count zero; API
  is healthy, flags are `false:false`, the prior image has zero running containers, and the
  15-second simple stability gate retained the exact baseline. Independent read-only postcheck
  passed with release-result SHA-256
  `930d3cf793eff8dc5b95383da326e7f47266239926f7c0af309a5a451215cba0`.

The fast release caused zero provider, image-attempt or WeCom delta: provider remained
`394:49:35:44`, WeCom remained `25:49:0:0:0:1`, and durable state remained
`37:184:37:13:5:59:157:35:44:35:394:25:49:0:0`. No OCR, Comfly, fixture, enqueue, retry, resend,
manual delivery, MinIO object mutation, frontend deployment, commit or push occurred. Production
mutation remains stopped; the simplified independent conclusion follows.

### User-authorized one-shot OCR activation gate — failed closed

- [x] Read-only preflight retained exact c66/candidate runtime, healthy API, restart-zero API and
  content worker, and runtime contract
  `false:false:glm-ocr:10485760:1048576:120.0:glm-5.2:1:false:zhipu`. No content/image work or
  nonterminal WeCom delivery was running. The pre-call durable/provider/WeCom aggregates were
  `37:184:37:13:5:59:157:35:44:35:394:25:49:0:0` / `394:49:35:44` / `25:49:0:0`.
- [x] Generated a deterministic RGB 1024x1024 three-line fixture using the trusted Noto Sans CJK
  font. The protected mode-0600 PNG was 42,981 bytes with SHA-256
  `9337541f14f4d887a11a1c1f970fcd1d88b7acc66fd51a6e863084894720618e`; its ordered lines matched
  the approved brand, controlled category title and short subtitle allowlist.
- [x] The first remote preparation stopped before Docker on a local wrapper assertion: the minimal
  protected environment contained 13 lines rather than the asserted 12. It made zero HTTP
  requests, removed its stage/container, retained `false:false`, and did not consume the authorized
  provider attempt.
- [x] The corrected sole authorized Docker invocation used the exact active image and an isolated
  direct recognizer with one-attempt configuration. The outer SSH/remote command exited 1 and the
  only captured safe marker was `fixture_cleanup=armed`; none of `typed_result`, `exact_ordered`,
  `accepted_line_count`, `issue_codes`, `http_attempts`, provider or model was emitted. The wrapper
  had captured Docker status internally but did not print it, so exact Docker exit status is
  **unknown**. Its protected stderr was removed by cleanup, so the paid HTTP-attempt count is also
  **unknown**; no claim of zero or one is made and no retry was attempted.
- [x] Failed closed without editing `.env`, backing it up, recreating services or enabling either
  feature. The remote fixture stage and unique container are absent. Two samples 15 seconds apart
  retained exact candidate/restart-zero API and worker state, healthy API and flags `false:false`.
  The final read-only aggregate was
  `37:184:37:13:5:59:157:35:44:35:394:25:49:0:0` / `394:49:35:44` / `25:49:0:0` with
  running `0:0:0:0`; durable, provider-durable and WeCom deltas were all zero.

No database, MinIO, Comfly, news or WeCom workflow was invoked; no enqueue, image generation,
retry, resend or manual delivery occurred. Durable provider counters cannot prove whether the
direct HTTP request crossed the external provider boundary, so that single boundary remains
unknown. Production remains default-off and no further call or mutation is authorized by this run.

### Simplified independent postdeploy conclusion

- [x] The checker used bounded read-only SSH only. Its first `backup_shape` stop used the obsolete
  complex-driver suffix instead of the documented fast-backup suffix. The corrected continuation
  reached physical `20260816T091212Z-zhipu-ocr-fast-default-off`, verified root:root mode 0700 and
  matched the fixed protected-manifest, PostgreSQL-dump and catalog hashes. The later
  `code.tar.gz_shape` stop was another checker filename assumption, not a production mismatch.
  Under the simplified gate, code/result sidecar names are no longer required; no further SSH was
  opened.
- [x] Runtime observations passed before that filename stop: exact c66 full/short markers, all
  eight long-lived services on candidate `03a988...` running at restart zero, healthy API/
  PostgreSQL/MinIO, migration exit zero at Alembic `20260815_0021`, and API/content flags
  `false:false`. Together with the implement agent's independent 15-second exact-baseline
  postcheck, safe logs, old-image-running-zero and release-result evidence above, the simplified
  postdeploy gate is PASS with no production blocker.

### User-authorized minimal production activation — succeeded

- [x] The official-contract recheck confirmed c66 uses the documented `/layout_parsing`,
  `glm-ocr`, private data-URI, 10 MiB input and `object[][]` raw layout contract. It classified the
  earlier unknown as missing wrapper evidence, not a provider failure; no new fixture or provider
  request was permitted.
- [x] At `2026-08-16T09:51:46Z`, fresh preflight retained c66 and candidate
  `sha256:03a988512f5f0792ec221be15c83db2ee64972f0fb5c4456eccc0562a8f184a2`, healthy API,
  restart-zero API/worker and runtime
  `false:false:glm-ocr:10485760:1048576:120.0:1:false`. Both target keys were absent from both
  `.env` and `.release.env`; their false values therefore came from reviewed Compose defaults.
  Durable/provider/WeCom aggregates were
  `37:184:37:13:5:59:157:35:44:35:394:25:49:0:0` / `394:49:35:44` / `25:49:0:0`, with
  all running and current-day actionable counts zero.
- [x] Created protected rollback `20260816T095342Z-zhipu-ocr-activation-env`. Its mode-0600 exact
  pre-activation env has SHA-256
  `4ad88db853075ad8668a1c45bd2e1f4498256c2ece0903ab2fbe3ea40521efdc`. The source already ended
  in a newline; the atomic replacement retained the complete original prefix, owner and mode and
  appended only one `IMAGE_DIVERSITY_ENABLED=true` and one `IMAGE_OCR_ENABLED=true` assignment.
  The resulting env SHA-256 is
  `df0213dbd192632307d4cba54f678f13e593da61e39a08b79474f2f6d2b5f717`; neither key was added to
  `.release.env`, and absolute Compose render passed.
- [x] Recreated only `acquisition-api` and `content-worker` using no-build/no-deps. Their runtime
  contract is now `true:true:glm-ocr:10485760:1048576:120.0:1:false`; both use the exact candidate
  with restart count zero and API is healthy. The dispatcher container identity was unchanged.
- [x] The 15-second gate retained provider `394:49:35:44`, WeCom `25:49:0:0` and running
  `0:0:0:0:0:0:0:0`. Bounded activation logs had zero severe, secret or provider-request markers.

No fixture, OCR/Comfly call, enqueue, retry, resend, service dependency start, dispatcher mutation
or manual delivery occurred. The earlier paid-attempt state remains historically unknown and was
not reinterpreted. Activation completed without failure or rollback; the protected env rollback is
retained and no commit or push was made.

## Phase 8 — OCR-independent controlled diversity (2026-08-18, local only)

- [x] Preserve the strict Zhipu OCR parser and all OCR-on request/envelope/element/exact-text
  behavior; do not implement the proposed unknown-element-extension tolerance.
- [x] Remove only the Settings dependency that required OCR to be enabled whenever controlled
  diversity was enabled. Retain reviewed `glm-ocr` identity enforcement when OCR is enabled.
- [x] Add focused Settings coverage for `diversity=true` / `ocr=false`, including proof that the
  disabled model value is not an activation dependency.
- [x] Add a controlled material-worker regression proving valid raster generation proceeds with
  zero recognizer calls, reaches the perceptual-similarity gate, stores once, and persists a passed
  non-OCR validation snapshot without `image_ocr_not_configured`.
- [x] Record the explicit tradeoff in PRD/design/spec/result/root-cause artifacts: requested visual
  text is not machine-verified while OCR is off; raster, storage, identity, enabled audit, and
  similarity gates remain in force.
- [x] Run focused Ruff format/lint, strict mypy, affected pytest, and `git diff --check`; record the
  exact local-only outcome. Do not access production or any external provider.

Local gates: Ruff format-check/lint passed for the three changed Python files; explicit-config,
no-incremental strict mypy passed for `config.py` and `material_package.py`; 221 affected Settings,
image generation, material, worker wiring, and strict Zhipu OCR contract tests passed. The initial
`uv run` command could not start because `uv` is not installed, so all recorded gates used the
repository's `/root/anaconda3/envs/edu-ai` interpreter. `git diff --check` passed after the final
task/spec edits. No production, SSH, Docker, network/provider, WeCom, enqueue, retry, replay,
resend, commit, push, or deployment action occurred.

Independent local review fixed the remaining cross-layer drift: Doctor now enforces the reviewed
`glm-ocr` identity only when diversity and OCR are both enabled, while continuing to require API/
worker equality for every OCR setting. `.env.example`, README, and both production operation guides
now describe OCR-off text as unverified instead of rejecting the configuration. The worker test
also carries a real perceptual-similarity result into persistence and proves the enabled audit and
byte/hash-consistent storage paths remain active; factory coverage proves the disabled recognizer
is not created under otherwise provider-usable settings.

Final reviewer gates: 237 focused tests passed across Settings/image generation, material worker,
content-worker validation wiring, strict Zhipu image/PDF OCR contracts, and release/Doctor
contracts. Ruff format-check/lint passed for all five changed Python files; explicit-config,
no-incremental strict mypy passed for config, material orchestration, adapter factory, and content
worker. OCR-off Compose rendering with an intentionally unused OCR model, `bash -n` for Doctor,
the unchanged-parser diff assertion, and `git diff --check` passed. No external action occurred.

After those review fixes, the final repository-level `make backend-check` also passed: Ruff
format/lint, strict mypy over 162 source files, and 969 backend tests at 81% coverage. Task context
validation and `git diff --check` passed; no external action was introduced by the final gate.
