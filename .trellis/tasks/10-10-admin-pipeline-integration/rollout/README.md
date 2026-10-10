# Bounded legacy pipeline candidate

These build helpers do not contact production. The coordinator owns admission, backups, remote
build/tag verification, cutover, live heartbeats, frontend ordering and recovery. Do not run a
worker `--once`/`--drain` as a smoke test against real configuration.

## Source and image boundary

The candidate derives from actual legacy image
`sha256:83a41e414fee1636c8d4897ae175ee5549afd9a7d4b37df0897b838c9b714851`.
Only the twelve `FILES` in `build_context.py` enter `/app/app`. `core/config.py` is derived from
the captured legacy source with SHA-256
`1155959c69c07bb99fbae68b61731743ca7ada0c4fc2e91f34542dc6dce77314`: add the optional
`model_secret_key` field and replace the cached getter's plain return with the model overlay.
The helper checks both anchors and restores the original bytes to verify that every other
legacy default/validator remains identical. It never reads the current checkout's config as
candidate payload. Current `db/models.py`, migrations and dependencies are not copied.

Root supplied `research/legacy-all-hashes.json` from the actual image: 359 source, asset,
migration and metadata files. The candidate has 364 total files in that scope (312 under app),
including five additions. The baked smoke checks exact sets and every hash, not just the overlay.
Verification metadata under `/opt/admin-pipeline-release` is outside application import paths.

## Generate after the final application source commit

Call the helper with explicit coordinator-provided local paths and full Git/image identities:

```sh
python build_context.py \
  --repo-root REPO_ROOT \
  --legacy-root EXTRACTED_LEGACY_ROOT \
  --legacy-hashes LEGACY_ALL_HASHES_JSON \
  --legacy-image sha256:83a41e414fee1636c8d4897ae175ee5549afd9a7d4b37df0897b838c9b714851 \
  --source-commit FULL_COMMITTED_GIT_SHA \
  --output NEW_CONTEXT_DIRECTORY
```

The output must not already exist. No credentials or real environment values are arguments.
All eleven copied checkout files must exactly match their bytes at `--source-commit`; the
helper rejects later uncommitted application edits. The twelfth is the approved legacy config port.
The helper, smoke script and Dockerfile must also match that commit; their SHA-256 identities are
recorded in `build_helpers_sha256`, and the baked smoke verifies their included copies.
`--legacy-hashes` is optional for source-only development contexts; a production smoke refuses
such a partial manifest. Final production context must include the full actual-image manifest.

The output contains `overlay/app/` (12 files), `Dockerfile`, `.dockerignore`, and
`verification/{manifest.json,legacy-config.py,smoke.py,build_context.py,Dockerfile}`. Manifest keys:

- `legacy_image`, `source_commit`, `full_legacy_manifest` identify the reviewed inputs.
- `legacy_files` contains all original files and hashes, including assets/migrations/metadata.
- `overlay_files` and `overlay_sha256` identify the twelve candidate files.
- `expected_file_sha256` is the full candidate scope; `expected_app_sha256` is its app subset.
- `legacy_config_sha256` / `derived_config_sha256` identify the narrow Settings port.

The coordinator must check a local Docker base tag resolves to `legacy_image`, then build with
`--pull=false --network=none --build-arg LEGACY_IMAGE=VERIFIED_LOCAL_BASE_TAG`. The Dockerfile has
only `FROM`/`COPY` and no package installation. It inherits the legacy entrypoint/runtime.

Run the baked smoke as a separate ephemeral container using the exact candidate image, with
`--network none --entrypoint python` and `/opt/admin-pipeline-release/smoke.py`. Do not pass
production `--env-file`, environment variables, volumes or bind mounts. The script explicitly
loads `/app`, clears environment before fixture construction, blocks sockets/psycopg connections,
process signals and thread starts, imports four entrypoints without running them, and creates
temporary synthetic journals only. Fixtures prove:

- Legacy Settings defaults/validator results are preserved, and the cached getter applies keys.
- Real installed AES-GCM opens valid data; unreadable keys/master keys keep environment values
  with honest versions/errors; environment restore and attempted-version restart logic work.
- New selected colour is applied, retry pinning survives a later choice, an old default-colour
  add ACK reconciles after expiry without provider writes, and malformed pins fail closed.

The final stdout is one safe JSON PASS receipt. No key/ciphertext/provider content is printed.
Root records candidate image and source identities beside this receipt; host-interpreter fixture
success is supplementary and does not replace the actual candidate-image run.

## Compose and runtime scope

The source Compose adds `ADMIN_PIPELINE_IMAGE` only to local article, weekly DAG, governance and
draft consumers; it falls back to `APP_IMAGE`, then the normal development image. A production
upgrade leaves the existing `APP_IMAGE` pin and the six current admin/core containers unchanged.
`MODEL_SECRET_KEY` is explicit only for the six registered model consumers. The draft worker
receives neither the model encryption key nor the admin encryption key.

Lifecycle tests cover actual persistent entrypoints, including weekly single routing; once,
drain and status commands do not start the watcher. Signal tests hold a fake job in flight,
invoke its registered SIGTERM callback, prove no cancellation or subsequent claim, then verify
cleanup after completion. They never signal the test process or call a provider.

Focused verification (from repository root):

```sh
PYTHONPATH=backend python -m pytest --no-cov -q \
  backend/tests/unit/test_admin_model_worker_lifecycle.py \
  backend/tests/unit/test_admin_pipeline_compose.py \
  backend/tests/unit/test_official_account_strict_compose.py \
  backend/tests/unit/test_model_api_keys.py
```

Ordinary Docker stop can force-kill a process after its grace timeout. This release's cutover
helper uses `stop --timeout -1`; its bounded local CLI wait does not authorize SIGKILL. Admission
must still prove no runnable or in-flight target work and recheck after stopping; graceful
watcher self-SIGTERM does not justify stopping busy production workers. Rollback must preserve new layout journals: old draft code
cannot safely reconstruct a nondefault pinned edition. Keep compatible code or stop that
consumer for forward repair; never delete/rewrite durable pins or restore an old DB snapshot.
