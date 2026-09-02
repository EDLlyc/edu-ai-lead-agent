# Research: Existing IP asset recognition and safe metadata repair seams

- Query: Identify the existing AI-assisted upload metadata recognition path, asset storage/repository update seams, and a safe dry-run/apply/rollback design for the approved 41 local IP assets.
- Scope: internal
- Date: 2026-09-02

## Findings

### Executive conclusion

The existing upload recognition stack can classify the 41 images without adding another provider:
it is a Zhipu vision adapter using the configured `glm-4.1v-thinking-flash` model and the frozen
`ip-asset-recognition-v1` normalization/prompt policy. It performs exactly one provider attempt per
eligible image. A complete batch therefore has a hard maximum of 41 provider requests; the actual
count can be lower when an item fails manifest mapping, verified object read, raster validation, or
normalization before the provider boundary.

The missing capability is persistence, not recognition. Today recognition is intentionally
transient and advisory, and `IpAssetRepository` exposes creation/read/search/job operations but no
metadata update, compare-and-swap, metadata version, or metadata audit primitive. The safest MVP is
therefore a development-only CLI with two separate phases:

1. `plan` (live provider, database read-only): resolve exactly the approved 41 manifest assets to
   ready/shared database rows, read every original through the verified MinIO boundary, run the
   existing recognition service once per successfully prepared image, and write a new private,
   gitignored, exclusive dry-run plan.
2. `apply` (provider-free, explicit opt-in): load and strictly validate that plan, row-lock one asset
   at a time, recheck the content commitment and current repairable-metadata fingerprint, and either
   apply an atomic metadata/name/tag replacement, return `already_applied`, or fail closed on drift.

No Alembic migration is required if the dry-run plan plus apply/rollback result are accepted as the
local audit and snapshot required by the task. A durable in-database revision ledger would require a
new table and migration because no such table exists today; adding one is unnecessary for this
one-time local repair and expands rollback/downgrade scope.

### Existing recognition provider, model, and call boundary

- `backend/app/core/config.py:381-400` defines recognition as default-off and fixes bounded model,
  timeout, concurrency, serialized request, and streamed response settings. The default model is
  `glm-4.1v-thinking-flash`, timeout 90 seconds, concurrency 1, request maximum 16 MiB, and response
  maximum 1 MiB.
- `backend/app/core/config.py:719-732` permits recognition only when the hub is enabled,
  `ai_provider_mode == "zhipu"`, and a credential is configured.
- A read-only settings projection on 2026-09-02 found the local runtime in `development`, with the
  hub and recognition enabled, provider mode `zhipu`, model `glm-4.1v-thinking-flash`, concurrency
  1, timeout 90 seconds, and a configured credential. No endpoint, credential value, or request was
  inspected or emitted.
- `backend/app/infrastructure/ai/factory.py:51-76` is the authoritative factory. It returns no model
  unless configuration is complete and otherwise builds `ZhipuIpAssetRecognitionAdapter` with the
  same bounded settings. The batch should reuse this factory rather than construct another client
  or duplicate credentials.
- `backend/app/infrastructure/ai/ip_asset_recognition.py:68-133` validates an HTTPS base URL, secret,
  model identity, timeouts, concurrency, and byte limits. The adapter owns its semaphore, so batch
  code must not bypass that concurrency bound.
- `backend/app/infrastructure/ai/ip_asset_recognition.py:135-183` makes one JSON-only
  `/chat/completions` request. `_post_json_with_retries(..., max_attempts=1)` proves there is one
  provider attempt per item and no hidden retry multiplication. For 41 valid selected items the
  maximum and expected request count is 41.
- `backend/app/infrastructure/ai/ip_asset_recognition.py:185-215` requires the returned model to equal
  the requested model, validates controlled enums, normalizes bounded optional strings/tags, and
  maps invalid output to the existing closed `invalid_schema` failure.
- `backend/app/infrastructure/ai/ip_asset_recognition.py:218-231` freezes the prompt schema and embeds
  `ip-asset-recognition-v1`. Output is advisory and excludes department, contributor, rights,
  approval, confidence, prose, and reasoning.
- Provider pricing/cost is not encoded in the repository, and no external pricing lookup was made.
  The implementation must report provider call counts, not invent a monetary amount. The operator
  must authorize the 41-call maximum before `plan`; normal startup, tests, `apply`, and
  `make eval-check` must remain provider-free.

### Image read and normalization boundaries

- `backend/app/application/services/ip_asset_recognition.py:20-37` already supplies the correct
  application boundary: validate the original with `validate_ip_asset_upload`, normalize it on a
  worker thread, and call the recognition model only after both steps pass. Stored database assets
  can use their already-safe filename/media type when invoking this service; the filename is not
  propagated to the provider request.
- `backend/app/domain/ip_assets.py:430-460` verifies the actual raster signature/container,
  declaration match, 25 MiB limit, 8192 edge, 32 million pixel bound, decoded dimensions, exact
  container length (no trailing payload), alpha presence, SHA-256, and perceptual hash.
- `backend/app/domain/ip_asset_recognition.py:83-126` EXIF-transposes and decodes the image, clears
  source metadata, preserves alpha with RGBA/PNG, otherwise uses RGB/JPEG, bounds the maximum edge
  to 1568, and progressively downsizes until the provider input is at most 8 MiB. The provider sees
  only the re-encoded pixels.
- `backend/app/infrastructure/storage/minio_ip_asset_store.py:72-140` is the correct source of bytes
  for database repair. `get_verified()` admits only the configured private bucket and the exact
  content-addressed key, streams at most 25 MiB, then verifies byte size and SHA-256. A repair batch
  should not read arbitrary paths or make a direct MinIO GET.
- `backend/app/application/services/ip_assets.py:354-367` demonstrates reconstructing a descriptor
  from an `IpAssetRecord` and using `store.get_verified()`. This helper also enforces accessibility;
  the batch needs a stricter exact-approved-set preflight rather than exposing a public endpoint.
- `backend/app/infrastructure/brand/visual_catalog.py:30-41,103-109` safely loads the private manifest
  and revalidates manifest-bound files. For this repair, use the manifest to define the approved set
  and the database checksum mapping, but send the verified immutable MinIO original to recognition:
  it is the exact object whose database metadata will be changed.
- `backend/evals/ip_asset_retrieval_grounded/assets.py:128-187` contains the existing one-to-one
  mapping proof for approved manifest entries to ready/shared database rows by checksum. It also
  requires semantic embeddings to be ready, which metadata repair does not need. Do not import an
  evaluation-only repository into production CLI code; reproduce/factor only the approved-41,
  one-to-one, ready/shared mapping contract and omit the semantic-ready requirement.

### Exact approved-set selection

The safe selection algorithm should be deterministic and fail closed before the first provider
request if corpus-level preflight fails:

1. Load `settings.image_asset_manifest` with `load_visual_catalog`.
2. Select `asset.approved is True`; require exactly 41 and unique full checksums.
3. Resolve each manifest item through `repository.get_by_sha256(asset.checksum)`.
4. Require a one-to-one mapping, `status == ready`, and `shared_at is not None`. Do not require
   `source_kind == seed_import`: exact-byte imports may legitimately have reused an earlier upload
   row.
5. Bind each item to public `asset_ref` and a domain-separated content commitment. Do not write the
   full database UUID, manifest path, original filename, object key, bucket, or raw content checksum
   into the plan.
6. Sort by `asset_ref` (or frozen catalog ref) so provider execution and output are reproducible.

The existing frozen evaluator has 41 safe catalog refs, but it is not the source of current database
state. The current private manifest plus database checksum mapping must be revalidated for this run.

### Recognition output and proposed metadata

`IpAssetRecognitionSuggestion` contains exactly the repairable AI fields
(`backend/app/domain/ip_asset_recognition.py:47-80`):

- `character`
- `asset_type`
- `emotion`
- `action`
- `scene`
- `intended_use`
- `style`
- free `tags`
- provider/model identities

Department and contributor are outside the provider schema and must always be copied from current
database state, never blanked or inferred. Orientation, media properties, visibility, status,
ownership, source kind, download/favorite aggregates, generation lineage, and embedding state are
also immutable with respect to this repair.

The provider suggestion must be reconstituted through `IpAssetMetadata` before it enters the plan or
repository. `IpAssetMetadata.__post_init__` normalizes every bounded field and sorted/deduplicated
tags (`backend/app/domain/ip_assets.py:268-293,321-338`), so this remains the one domain validator.

The output remains AI advisory data, not human Gold. Even when the user chooses an AI-only repair,
the artifact should state `review_status: ai_suggestion_unreviewed` (or an equivalent closed enum)
and should not claim manual approval.

### Critical tag projection trap

The current database stores both structured values and free tags in `ip_asset_tags`:

- `_tag_rows()` writes emotion/action/scene/intended-use/style rows plus free-tag rows
  (`backend/app/infrastructure/db/ip_assets.py:1429-1439`).
- `_tags_for()` reads only `(asset_id, value)` and drops the `dimension`, so the public
  `IpAssetRecord.tags` projection is a union of all tag dimensions, not the original free-tag tuple
  (`backend/app/infrastructure/db/ip_assets.py:1584-1604`).

Consequently, `IpAssetMetadata(..., tags=record.tags)` is not a lossless metadata snapshot: it would
turn emotion/action/scene/style values into free tags on apply. A repair implementation must add an
internal dimension-aware metadata-state read or query `IpAssetTagModel.dimension/value` inside the
repository transaction. Do not use the public `record.tags` projection to calculate before-state,
replace tags, or create rollback data.

Recommended internal state shape:

```text
IpAssetMetadataState
  asset_ref
  content_commitment
  character / asset_type
  emotion / action / scene / intended_use / style
  free_tags                 # only dimension == "free"
  metadata_fingerprint      # canonical repairable fields above
```

Department/contributor can be retained directly on the locked ORM row and need not appear in the
repair artifact.

### Naming implications

Canonical display naming is derived from character, asset type, emotion-or-action,
scene-or-intended-use, and orientation (`backend/app/domain/ip_assets.py:519-546`). Merely changing
the scalar metadata while leaving `naming_key`, `canonical_name`, and `canonical_slug` unchanged
would make search and download/display naming contradict the repaired classification.

The repository update should therefore regenerate naming in the same transaction:

- Build an `IpAssetMetadata` using proposed repairable fields plus current department/contributor.
- Call `canonical_name_base(metadata, current_orientation)`.
- If the derived naming key is unchanged, retain the current `name_version` and regenerate the same
  versioned display/slug.
- If it changes, take the existing naming-key advisory transaction lock, allocate
  `max(name_version) + 1` for the new key, and call `versioned_canonical_name` exactly as creation does
  (`backend/app/infrastructure/db/ip_assets.py:211-246`).
- Update scalar metadata, derived naming fields, dimensioned tags, and `updated_at` atomically.

Stable `asset_ref`, primary key, blob identity, and all foreign keys remain untouched. Existing image
embeddings are based on normalized image bytes and provider/input-policy identity, not metadata, so
this task must not rebuild, delete, or enqueue embeddings.

### Existing persistence primitives and migration implications

- `IpAssetRepository` has `get_by_sha256`, `get_by_ref`, `get_by_id`, and `create_asset`, but no
  metadata read with dimensioned tags and no metadata update/CAS method
  (`backend/app/application/ports/ip_assets.py:228-350`).
- `PostgresIpAssetRepository.create_asset` owns name allocation, scalar insertion, tag insertion,
  and embedding job creation (`backend/app/infrastructure/db/ip_assets.py:187-327`). It is not an
  update primitive; exact-byte replay deliberately returns the existing asset without applying new
  metadata.
- `IpAssetModel` has mutable scalar metadata and `updated_at`, but no metadata revision/fingerprint
  column (`backend/app/infrastructure/db/models.py:5527-5571`).
- `IpAssetTagModel` is replaceable child state with uniqueness on
  `(asset_id, dimension, value)` (`backend/app/infrastructure/db/models.py:5621-5643`).
- There is no IP asset metadata audit/version/snapshot table in models or Alembic migrations.

For the local MVP, add repository methods and keep audit artifacts under gitignored `output/`; no
schema change is necessary. Row locking plus canonical before/after fingerprints gives safe
compare-and-swap without adding a version column. If a future requirement says repair history must
survive deletion of local output or support multi-operator production audit, then add a dedicated
immutable `ip_asset_metadata_revisions` table in a separate migration, with explicit downgrade
policy. Do not overload `ip_asset_search_aggregates`, embedding jobs, or generation records.

### Dry-run artifact contract

Use a new strict Pydantic schema (`extra="forbid"`, frozen) and canonical JSON. Suggested top-level
fields:

```text
schema_version: ip-asset-metadata-repair-plan-v1
policy_version: ip-asset-recognition-v1
provider: zhipu
model: <configured exact model>
asset_set_fingerprint: <domain-separated commitment to ordered refs/content commitments>
created_at: UTC timestamp
selected_count / scanned_count / suggested_count / unchanged_count / failed_count
provider_call_count
items: exactly 41 closed item records when corpus preflight succeeds
plan_fingerprint: canonical hash excluding this field
```

Suggested item fields:

```text
asset_ref
content_commitment
before_metadata
proposed_metadata | null
before_metadata_fingerprint
proposed_metadata_fingerprint | null
changed_fields
status: changed | unchanged | read_failed | invalid_raster | provider_failed | invalid_suggestion
error_code | null
provider_call_status: completed | failed | not_called
```

`content_commitment` should be a domain-separated hash of the verified body checksum, for example
`SHA256("ip-asset-metadata-repair-content-v1\0" || SHA256(body))`, rather than publishing the raw
content-addressed checksum. It still binds apply to exact bytes while avoiding a direct object-store
identifier. `metadata_fingerprint` should hash only the exact repairable fields, including
dimension-`free` tags in canonical order. It must not use public `record.tags`.

Privacy constraints should recursively reject keys/values for filename, path, object key, bucket,
database UUID, profile/user/session/token, provider body/response/request ID, prompt, Base64/data
URL, raw image bytes, credentials, and raw content SHA fields. Only safe `asset_ref`, controlled
metadata suggestions, provider/model/policy identity, commitments, counts, status, and closed error
codes belong in the plan.

The plan directory should be new mode `0700`; artifacts should be exclusive mode `0600`, bounded,
symlink-safe, fsynced, and atomically published without overwriting an existing plan. The closest
repository pattern is `backend/evals/official_account_reviewer_live_ab/harness.py:506-522,720-778`.
Copy or extract the generic pattern; do not import product code from an unrelated evaluator.
`output/` is already ignored by `.gitignore:36`.

Dry-run is database read-only but not provider-free. Emit aggregate progress/counts only; do not
print per-image metadata, paths, filenames, response bodies, or exception prose to the console.

### Apply semantics, idempotency, and drift

Apply must be a separate command with both a supplied plan path and explicit destructive opt-in
(for example `apply --plan ... --execute` plus a fixed acknowledgement). It must never be triggered
by API startup, worker startup, tests, imports, `make eval-check`, or the upload UI.

Per item, inside one short transaction:

1. Load the row by exact safe `asset_ref` with `FOR UPDATE`; require ready/shared and still part of
   the approved 41 mapping.
2. Reconstruct the descriptor, call `MinioIpAssetStore.get_verified`, and recompute the
   domain-separated content commitment. This is provider-free and catches object/DB drift.
3. Read tag rows with their dimensions and compute the current repairable metadata fingerprint.
4. If content differs, return `content_drift` with zero write.
5. If current metadata fingerprint equals the plan's proposed fingerprint, return
   `already_applied` with zero write. This is what makes a second apply succeed idempotently.
6. If current metadata fingerprint does not equal the plan's before fingerprint, return
   `metadata_drift` with zero write.
7. Otherwise replace scalar repairable metadata, derived naming state, and all dimensioned tag rows
   atomically; set `updated_at`; reread and assert the proposed fingerprint before commit.

One item failure should not invalidate successfully applied independent items, matching the PRD's
per-item failure requirement. The command must produce a separate immutable result manifest with
`changed`, `unchanged`, `already_applied`, `skipped`, `drifted`, and `failed` aggregates. A nonzero
drift/failed count should yield a nonzero process exit even if some rows changed, so partial success
is visible.

The result must not claim that every item was applied merely because its provider suggestion was
valid. Persist only actual post-transaction outcomes.

### Rollback

The plan already contains validated before-state, but a useful rollback needs the actual apply
outcomes and post-state identity. After apply, write an immutable result manifest containing each
changed asset's before and applied metadata fingerprints and safe metadata snapshots. A
`restore --result ... --execute` command can use the same repository CAS method in reverse:

- require current content commitment to match;
- require current metadata fingerprint to equal the recorded applied fingerprint;
- apply the recorded before metadata;
- fail closed if any later edit occurred;
- report restored/already-restored/drifted/failed counts.

Derived canonical naming can be regenerated from the restored semantic fields. This may allocate a
new version number rather than resurrect the exact prior `(naming_key, name_version)` if another row
has occupied it; the stable asset identity and semantic name are restored. If byte-exact historical
name-version restoration is required, that is a stronger durable-version-ledger requirement and
should use a migration, not a one-off local CLI.

Do not rely only on `updated_at` for rollback or CAS: it is not an immutable version token and has no
database constraint preventing coincident values.

### Recommended affected files

Minimal product changes:

- `backend/app/domain/ip_asset_metadata_repair.py` (new): strict plan/result/item schemas, closed
  status/error enums, canonical metadata/content/asset-set/plan fingerprints, privacy validation.
- `backend/app/application/ports/ip_assets.py`: add an internal dimension-aware metadata state and
  a CAS-style `repair_metadata` repository contract. Keep the public API projection unchanged.
- `backend/app/application/services/ip_asset_metadata_repair.py` (new): approved-41 preflight,
  verified reads, recognition orchestration, per-item failure isolation, plan/apply/restore
  orchestration, and aggregate counts.
- `backend/app/infrastructure/db/ip_assets.py`: implement dimension-aware state loading and the
  row-locked atomic scalar/name/tag CAS update. Reuse current naming and tag helpers.
- `backend/app/ip_asset_metadata_repair_main.py` (new): development-only explicit CLI, owned
  engine/client lifetime, provider factory reuse for `plan`, provider-free `apply`/`restore`, safe
  exclusive artifact output.
- `Makefile`: add explicit plan/apply/check targets, keeping the live plan target out of
  `eval-check`. Apply must require caller-supplied plan/output/ack variables rather than a permissive
  default.

Tests:

- `backend/tests/unit/test_ip_asset_metadata_repair.py` (new): strict schema, canonical
  fingerprints, free-tag dimension fidelity, privacy rejection, exact 41 selection, per-item
  failure isolation, max 41/success-count provider calls, dry-run zero repository writes, plan
  tamper/drift rejection, apply call graph provider-free, and aggregate/result truthfulness.
- `backend/tests/integration/test_ip_assets.py` or a focused new integration file: PostgreSQL/MinIO
  CAS update, scalar and dimensioned-tag replacement, naming regeneration/collision allocation,
  changed-row atomicity, second-apply `already_applied`, metadata/content drift refusal, reverse
  restore, and proof that blob bytes, embedding rows/jobs, favorites, memberships, download counts,
  generation rows, source/status/visibility remain unchanged.
- `backend/tests/unit/test_ip_asset_recognition.py`: retain all existing normalization/provider/API
  regression tests; add only a focused assertion if exposing policy identity through an internal
  batch projection changes shared code.
- `backend/tests/unit/test_ip_asset_retrieval_grounded_eval.py` and V2: rerun provider-free snapshot
  and preflight-related tests because repaired metadata changes dynamic rankings but must not mutate
  the committed human relevance data.

No frontend production file should be required for this batch repair. The existing upload flow
already calls recognition only after a click (`frontend/src/features/ip-assets/IpAssetHub.tsx:
1213-1261`) and keeps suggestions editable. Preserve its regression at
`frontend/src/features/ip-assets/IpAssetHub.test.tsx:428-518`. No batch repair endpoint or UI route
should be added.

No Alembic/model change is recommended for the local MVP. If implementation adds a durable revision
table anyway, it must also update `backend/app/infrastructure/db/models.py`, add the next Alembic
revision after the repository's then-current head, extend clean-upgrade/model-parity/downgrade
integration tests, and define whether downgrade refuses or intentionally loses revision history.

### Validation matrix

Provider-free checks that should run on every change:

- Domain/unit tests for plan schema, fingerprints, privacy, drift, idempotency, and fake recognizer.
- Repository integration against real PostgreSQL and MinIO for CAS/tag/name/restore semantics.
- Existing `backend/tests/unit/test_ip_asset_recognition.py`.
- Existing IP asset unit/integration/search tests.
- `make ip-asset-grounded-eval-check` and `make ip-asset-retrieval-eval`.
- Ruff, formatting, strict Mypy for affected Python modules, and `git diff --check`.
- A command-level test proving normal startup and `make eval-check` make zero recognition calls.

One explicitly authorized local live pass:

- Preflight the exact approved set before calls.
- Run `plan` once, maximum 41 requests, and record actual
  selected/scanned/called/suggested/unchanged/failed counts.
- Validate the generated plan's schema, canonical fingerprint, privacy scan, file permissions, and
  absence from git tracking.
- Inspect aggregate distributions only before apply; do not describe AI output as human Gold.
- Run explicit provider-free apply, then a second apply to prove zero changes.
- Verify the approved 41 distribution, search regression, and unchanged non-metadata tables.
- Keep the later 248-call Seed V2 V2/V3 retrieval rerun out of this task.

## Files found

- `backend/app/domain/ip_asset_recognition.py` — transient normalized input and advisory suggestion
  types plus pixel-only normalization.
- `backend/app/application/services/ip_asset_recognition.py` — single-image validation,
  normalization, and provider orchestration.
- `backend/app/infrastructure/ai/ip_asset_recognition.py` — bounded one-attempt Zhipu vision adapter
  and strict JSON taxonomy projection.
- `backend/app/infrastructure/ai/factory.py` — validated recognition adapter construction.
- `backend/app/core/config.py` — feature flag, model, provider, timeout/concurrency/byte settings.
- `backend/app/domain/ip_assets.py` — taxonomy, metadata validation, upload validation, alpha and
  orientation observations, and canonical naming.
- `backend/app/application/ports/ip_assets.py` — current record/store/model/repository interfaces;
  no update or metadata-audit primitive.
- `backend/app/application/services/ip_assets.py` — verified original read and current asset service
  composition.
- `backend/app/infrastructure/storage/minio_ip_asset_store.py` — private content-addressed verified
  object read.
- `backend/app/infrastructure/db/ip_assets.py` — creation, tags, reads, vector search, and the update
  seam; no metadata CAS today.
- `backend/app/infrastructure/db/models.py` — mutable IP scalar fields/tags and absence of metadata
  revisions.
- `backend/alembic/versions/20260824_0031_ip_asset_hub.py` — original IP asset/tag schema.
- `backend/app/ip_asset_import_main.py` — existing approved-manifest import loop and metadata mapping;
  it is not a repair tool and its current dry-run does not read images or call recognition.
- `backend/app/infrastructure/brand/visual_catalog.py` — safe private manifest and asset reading.
- `backend/evals/ip_asset_retrieval_grounded/assets.py` — exact approved-41 database mapping and live
  preflight pattern, with an unnecessary-for-repair semantic-ready dependency.
- `backend/tests/unit/test_ip_asset_recognition.py` — existing normalization, privacy, adapter,
  endpoint, explicit invocation, and config regressions.
- `backend/tests/integration/test_ip_assets.py` — real PostgreSQL/MinIO dynamic asset tests and best
  location/pattern for persistence assertions.
- `frontend/src/features/ip-assets/IpAssetHub.tsx` — click-only recognition and editable suggestion
  UI that should remain unchanged.
- `frontend/src/features/ip-assets/IpAssetHub.test.tsx` — explicit-click and stale-response/failure
  regressions.
- `backend/evals/official_account_reviewer_live_ab/harness.py` — reusable design reference for
  privacy scanning and exclusive, 0600, symlink-safe, atomic local evidence files.
- `.trellis/spec/backend/ip-asset-hub.md` — authoritative hub/recognition/storage/search contract.
- `.trellis/spec/frontend/ip-asset-hub.md` — authoritative explicit-click/editable-suggestion UI
  contract.
- `.trellis/spec/backend/database-guidelines.md` — short transactions, external calls outside
  transactions, typed async SQLAlchemy, migration, vector identity, and audit principles.
- `.trellis/spec/backend/logging-guidelines.md` — provider/image privacy and aggregate-only logging.

## Code patterns

- Reuse the provider-neutral recognition port and service, not the HTTP route:
  `backend/app/application/ports/ip_assets.py:224-225` and
  `backend/app/application/services/ip_asset_recognition.py:20-37`.
- Keep live provider calls outside database transactions:
  `.trellis/spec/backend/database-guidelines.md` under “Transactions and external calls”.
- Use `MinioIpAssetStore.get_verified()` for bytes immediately before normalization/provider use:
  `backend/app/infrastructure/storage/minio_ip_asset_store.py:72-140`.
- Map approved manifest bytes to dynamic rows by checksum and prove one-to-one membership before
  work: `backend/evals/ip_asset_retrieval_grounded/assets.py:128-169`.
- Reuse the existing advisory lock and version allocation for canonical names:
  `backend/app/infrastructure/db/ip_assets.py:211-246`.
- Replace dimensioned tag rows from `IpAssetMetadata`; never round-trip public union tags:
  `backend/app/infrastructure/db/ip_assets.py:1429-1439,1584-1604`.
- Copy/extract the exclusive atomic artifact pattern rather than ordinary `Path.write_text`:
  `backend/evals/official_account_reviewer_live_ab/harness.py:729-778`.
- Preserve click-only upload recognition:
  `frontend/src/features/ip-assets/IpAssetHub.tsx:1213-1261`.

## External references

No external documentation or current pricing was used. The installed repository's typed settings,
adapter implementation, and tests are the authoritative version for this implementation. Provider
pricing/model availability is temporally variable and must be checked separately if a monetary cost
estimate or provider-lifecycle guarantee is required.

## Related specs

- `.trellis/spec/backend/ip-asset-hub.md` — identity, immutable original storage, dynamic search,
  advisory recognition, disabled defaults, and privacy/error matrix.
- `.trellis/spec/frontend/ip-asset-hub.md` — explicit user click, editable fields, stale-response
  handling, and no automatic upload.
- `.trellis/spec/backend/database-guidelines.md` — external call/transaction separation,
  idempotency, typed SQLAlchemy, vector identity, migrations, and provenance.
- `.trellis/spec/backend/logging-guidelines.md` — no image/prompt/provider body/path/secret logging;
  aggregate bounded provider metadata only.
- `.trellis/spec/backend/quality-guidelines.md` — IP grounded evaluation gates and provider-free
  routine quality checks.

## Caveats / Not Found

- No IP asset metadata update, compare-and-swap, revision, audit, or rollback primitive exists.
- `IpAssetRecord.tags` is not a lossless free-tag view because tag dimensions are discarded during
  projection. This is the highest-risk implementation trap.
- Current recognition outputs have provider/model but no durable request fingerprint, usage, cost,
  or provider request ID. The batch can honestly record call status/count and policy/model identity,
  not exact provider billing or request lineage.
- `has_alpha` proves an alpha-capable raster representation, not necessarily that visible pixels
  contain transparent regions. Do not deterministically force every `has_alpha` asset to
  `transparent_cutout`; let the bounded vision suggestion plus taxonomy validation decide.
- AI suggestions are not human Gold and have no calibrated confidence. Explicit local apply is the
  authorization boundary when no human per-image review is planned.
- A domain-separated content commitment hides the raw content-addressed checksum but is still a
  stable cross-artifact correlator. Keep artifacts private, mode 0600, gitignored, and local.
- Provider/model availability and monetary pricing were not verified externally. Maximum request
  count is code-proven (41), but exact cost is unknown.
- The current task has no `design.md` or `implement.md` at research time; findings are based on the
  PRD, Trellis specs, product code, and tests. Per role isolation, `implement.jsonl` and
  `check.jsonl` were not loaded.
