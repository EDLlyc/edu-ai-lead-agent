# R14 narrow Moments-copy offline release

This is a fixed-base, one-attempt release operator for the owner's approved R13
heading and advisory-review behavior. It is **not** a general deployer. It
accepts only production host marker `3e62b33fcc62582240cb73ede9b12756eda029c5`,
OCI digest `sha256:2b3a9a7c5e35a3a7173a129a3bd7e0d5322caaeef2c125b9a4d63146e77c9d1a`,
base archive SHA-256 `651dbc6c08efc38ba405f133b630f4af077c45101de71f3777eab3a22827a80e`,
the one already-live draft-Worker notice fix `a9db34f8937effda32a2a58358d2b849268700a5`,
and schema `20260916_0048`. Recheck all of them on the host immediately before
use. No migration, provider call, social send, business replay, PDF activation,
environment-policy change, or host-script replacement is included.

The source commit must descend from that exact base. The entire application
overlay must be exactly these six modified files:

- `backend/app/application/services/copy_generation.py`
- `backend/app/application/services/wechat_official_account_draft.py`
- `backend/app/core/config.py`
- `backend/app/domain/copy_generation.py`
- `backend/app/domain/official_account_editor_handoff.py`
- `backend/app/schemas/copy_generation.py`

Only `backend/tests/` and this release directory may contain other changes.
The builder reads Git blobs, not the worktree. Its own committed bytes must match
the running operator. Build only after the production-base port and this
operator are integrated into one reviewed commit. The base image's documented
OCR runtime/Git discrepancy is retained and checked against the last effective
base-layer bytes; this release cannot overwrite the OCR file. The two WeChat
files must byte-match the original `a9db34f` Git commit. The other four files
are the reviewed R13 copy port. This is one uniform combined candidate, not a
replacement of the notice Worker with older base behavior.

## Authoritative source gate

Before building or activating a candidate, push the isolated reviewed release
branch to the configured internal Codeup `origin`. Independently read back the
exact remote branch tip with `GIT_TERMINAL_PROMPT=0 git ls-remote origin
refs/heads/release/moments-heading-advisory-prod-20260925` and require its full
40-character commit ID to equal both the reviewed local `HEAD` and the
candidate manifest's `revision`. Do not use a GitHub mirror, an unfetched local
branch, a mutable tag, or a detached/uncommitted working tree as release
authority. After any review fix, commit, push, read back, rebuild, and re-run
offline smoke; an older candidate manifest is no longer eligible. This remote
identity check is an external operator gate: the fixed-base builder itself
remains network-independent and validates only committed Git objects and its
own hash-bound bytes.

## Local immutable candidate

From a clean, reviewed production-base worktree, using the complete locally
verified base archive:

```bash
python3 -B .trellis/tasks/09-23-moments-brand-rag-diversity/research/r14-release/moments_release.py build \
  --repo ABSOLUTE_REVIEWED_WORKTREE \
  --revision FULL_REVIEWED_COMMIT \
  --base-archive /root/projects/edu-ai-lead-agent/output/wechat-forward-3e62b33/backend-image.oci.tar.gz \
  --output ABSOLUTE_NEW_PRIVATE_OUTPUT_DIRECTORY
```

Record the emitted manifest SHA-256 privately. The output directory must not
exist beforehand. Validate the complete OCI archive and manifest bytes, load
its unique tag, then run `smoke` with `--manifest` and `--manifest-sha256`. Smoke
uses network-disabled, read-only containers and checks the full application
tree, 12 imports, Settings, OpenAPI, `pip check`, schema head, and candidate copy
version defaults. Review the exact base-to-candidate app diff and run focused
production-base tests before any host transfer.

## Host gate and one application

Use the authenticated operator channel and a private root-owned staging path;
do not display the captured receipt, environment, private brand IDs, source
text, container inspect JSON or DB contents. The same committed operator and
hash-bound bundle run all phases:

1. `capture --manifest ... --manifest-sha256 ... --output PRIVATE_BASELINE_JSON`
2. `plan --manifest ... --manifest-sha256 ... --baseline ... --baseline-sha256 ...`
3. `apply --apply --manifest ... --manifest-sha256 ... --baseline ... --baseline-sha256 ...`

`capture` is read-only except for its named private receipt. `plan` is
read-only. Before any application mutation, both bind the live image/revision,
schema, all 12 app services, effective copy defaults, Zhipu `embedding-3`/2048,
active brand-pointer digest, protected host files, complete relevant DB-table
fingerprints, business volumes, journal, brand files, idle queues, backup timer,
and the next Monday/Wednesday/Friday 09:00 preparation window. Exactly eleven
application services must run the pinned base digest/ref; only
`wechat-official-account-draft-worker` may run the pinned `notice-a9db34f` tag
and image ID, while Compose still renders the base ref. Capture verifies that
notice image's revision label, exact two-layer extension of the base, unchanged
non-label image configuration, complete running application tree against the
known `a9db34f` Git tree plus the pinned OCR exception, and immutable runtime
tree. Any unknown image, misplaced notice image, extra application-file change,
or baseline drift fails closed. The baseline
expires after two hours. The plan refuses an existing attempt directory or a
window less than 20 minutes away, a future-dated receipt, insufficient backup
space, any installed standard-release marker, or a mount that shadows verified
application code. Space is checked again after the candidate image is loaded,
before stopping services. Existing historical queued preview jobs and
old unknowns are accepted only under the prior independently pinned cohort;
new pending, leased, stale or unknown work blocks release.

The live brand corpus contains one July test document whose active version uses
the `fake` embedding provider. Zhipu retrieval excludes it by provider/model.
The release does not modify that document: capture requires its pinned
document/version identity and source fingerprint, exactly one such exception, and all
other active versions to be ready Zhipu `embedding-3`/2048. The full active
pointer digest is then bound across plan, stop, activation and acceptance.

`apply` takes deploy and backup locks; loads and probes the candidate; repeats
the baseline; stops exactly the 12 application services; verifies PostgreSQL
custom dump/list, three non-Postgres volume archives, brand files, and host
runtime/config backup; fences the stopped state; then switches **only**
`.release.env` `APP_IMAGE` and the two revision markers. It starts the same 12
services once. PostgreSQL/MinIO containers and volumes remain intact.

Acceptance requires the same exact combined candidate image in every app
container, zero abnormal
restarts, health, schema `0048`, unchanged Compose/env flags and mounts,
unchanged provider and active brand pointers, unchanged protected DB/business
fingerprints, v24/v19/v12/preview-v12 effective copy defaults, backup timer, and
the same next business window. It does not claim a future model output is good.

An attempt directory is never deleted or renamed to retry. Before activation
intent, original services may restart only after the entire stopped baseline is
proved unchanged. From activation intent onward, **no automatic old-image
rollback** is allowed: a new v24/v12 run may have been persisted, and old
version-bundle compatibility is unproven. On failure or uncertain SSH outcome,
stop all 12 writers, inspect the private intent/backup/receipt and actual host
state, then plan a separately reviewed forward recovery. Do not infer success
or failure from an interrupted transport connection. Even an uncertain write
of the activation-intent file enters this forward-only state.

## Offline checks

```bash
pytest -q --no-cov .trellis/tasks/09-23-moments-brand-rag-diversity/research/r14-release
ruff check .trellis/tasks/09-23-moments-brand-rag-diversity/research/r14-release
ruff format --check .trellis/tasks/09-23-moments-brand-rag-diversity/research/r14-release
mypy --strict .trellis/tasks/09-23-moments-brand-rag-diversity/research/r14-release/moments_release.py
```
