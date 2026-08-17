# Design: Broad Workspace Offline Production Release

## Four boundaries

1. **Git:** every meaningful safe artifact is reviewed, committed, and fast-forward pushed to
   authoritative Codeup `main`.
2. **Application payload:** Docker builds from the explicit committed backend context, so dormant
   Workbench modules are present. A separate exact runtime-source manifest controls active overlay,
   while the transport bundle independently excludes reports, Trellis, frontend, dev lock, and task
   tools.
3. **Production:** one immutable offline image/source bundle updates the existing local-tag runtime.
4. **Feature activation:** OCR/diversity is preserved, delivered-repeat moves `.6 -> .7`,
   `小赛洞察` applies naturally, and Workbench remains local-only.

This honors “push everything” without treating Git availability as a production endpoint or
force-adding ignored/private/compiler material.

## Repository curation

Changes are grouped into coherent commits: Workbench/shared refactors/contracts/tests/portfolio;
OCR evidence/tooling; report source/tool/deliverables; Trellis/spec/skill metadata; release
operator/task evidence. Two authenticated-URL test literals are rewritten before commit. LaTeX
`.fls`, `.fdb_latexmk`, and `.xdv` become ignored; all remaining status-listed paths are accounted
for and intentionally committed.

Push is non-force and fast-forward-only. A fresh fetch must make Codeup `origin/main` equal the
release commit before the clean build worktree is created.

## Candidate boundary

The candidate is built offline from the verified production dependency base plus the complete
committed backend application scope described by the explicit image-input manifest. It receives
full-SHA revision/source/base labels, an exact file/hash manifest, and an immutable local image
ID/bundle hash.

The base image's historical full-pyproject hash is not reused as a false equality gate. Instead,
the build proves that production dependencies and `runtime.lock` are unchanged from c66, records
the new final pyproject hash (whose only dependency addition is dev-only MCP), rejects MCP imports
from every supported production entrypoint, and runs non-root imports plus `pip check`.

Workbench absence from the supported production graph is structural: no `api_main` registration,
production OpenAPI path, Compose service, runtime MCP dependency, or deployed frontend. Dormant
modules and shared helpers exist in the image; only an unsupported manual command/environment
override could launch them. Full imports/real-PG regressions prove they do not break production,
and the production frontend build must contain no Workbench chunk/marker.

The task-local release operator/harness is committed for provenance but transferred separately and
never copied into active application source/image.

## State machine

| State | Runtime | Scoring | Writers | Recovery |
|---|---|---|---|---|
| S0 prior | f20 local tag/image + exact Git-proven hybrid source | `.6` or absent | running | no-op |
| S1 quiesced | f20 | explicit `.6` | stopped | restart captured prior IDs |
| S2 candidate | new image ID behind local tags | `.6` | stopped | restore source/tags/markers |
| S3 activated | candidate | `.7` | stopped | full f20 only if no durable `.7` |
| S4 accepted | candidate | `.7` | dependency-ordered running | retained rollback set |

Operator flags include `backup_ready`, `tags_changed`, `overlay_changed`, `env_activated`, and
`completed`. Signals/nonzero EXIT enter one recursion-disabled recovery path. Recovery never reads
a partial backup and the operator is never invoked twice.

## Build flow

1. Curate workspace; implement/review the task-local broad-release operator and fake recovery
   harness; freeze final tree.
2. Run full backend/frontend/Workbench/lock/release/Compose/Doctor/contract/secret gates.
3. Commit and fast-forward push all safe work; fetch authoritative Codeup again.
4. In a fresh detached worktree, build the offline candidate from the verified production base and
   validate OCI/classic structure, image labels/ID, non-root imports, all Compose entrypoints,
   source manifest, `pip check`, OpenAPI, Alembic, `.6`/`.7`, and Workbench production absence.
5. Export mode-0600 image/source/operator/manifests into a protected local artifact set.

## Production flow

### Preflight and stage

- Confirm the exact 307-path hybrid source manifest plus f20 image/markers, local-tag `.release.env`, OCR/diversity true/true, scoring
  ownership, service health/restarts, volumes/capacity/timer, and safe logs.
- Take two stable aggregate samples at least 15 seconds apart. Require zero running/actionable/
  nonterminal/unknown and legacy-prompt work plus a safe scheduler window. A complete pure
  read-only startup projection API does not exist, so predictive create/claim mirroring is deferred.
- Explicitly reject actionable copy/package/delivery rows using the pre-`小赛洞察` prompt identity.
- Preserve inert historical rows: copy queued/retry rows count only when due for the current
  Asia/Shanghai business date (running rows always count), legacy packages count only for today,
  and all nonterminal WeCom jobs continue to count globally.
- Transfer exact artifacts to a unique mode-0700 stage, verify mode-0600 members, load the isolated
  candidate tag, and prove candidate running count remains zero.

### Quiescence and evidence

- Hold `/var/lock/edu-ai-backup.lock` before first stop. Stop dispatcher, content, governance,
  acquisition, then API.
- Create/catalog-validate a fresh PostgreSQL dump and capture env/source/full+short markers,
  previous container IDs, shared/service tags, prior image ID, MinIO/brand manifests, and volume
  identity before `backup_ready=1`.
- If scoring is absent, atomically add explicit `.6` under old Compose. Reject duplicate/unexpected
  scoring or `.release.env` ownership. Preserve OCR/diversity and every unrelated byte.

### Activation and restore

- Retag immutable rollback tags, then shared local and nine service tags to the exact candidate ID.
  Atomically overlay the complete exact runtime-source/Compose manifest while preserving restrictive destination
  modes/owners and excluding env/private/brand/task/report/frontend paths.
- Write full `.release-commit` and short `RELEASE_COMMIT` markers bound to the authoritative SHA;
  preserve `.release.env` selecting the shared local tag.
- Do not run `minio-init`; it performs bucket/policy writes and there is no object-store change.
  The default `backend-migrate` command is also forbidden because it chains `app.seed_sources`.
  Run an explicit no-build/no-deps command override for only
  `alembic -c alembic.ini upgrade head`; head remains `20260815_0021` and source metadata/counters
  remain unchanged. Offline-probe candidate `.6`/v3 and `.7`/v4, then atomically change only `.env`
  `.6 -> .7`.
- Recreate/start API, acquisition, governance, and content with explicit `--no-deps`; dispatcher
  last. Immediately before every scheduler/dispatcher, recheck the safe window and observed
  actionable/nonterminal plus legacy-prompt zero vectors, then recheck those vectors after its
  sequential start. Require exact
  image/restart-zero, health, `.7`/v4, true/true OCR/diversity, no Workbench endpoint, unchanged
  protected inputs/source counters, and immediate plus 30-second aggregate/log stability.

## Rollback

Before durable `.7`, restore `.6` first, then f20 source/tags/markers/image and captured services,
dispatcher last. No DB restore/downgrade occurs.

After durable/nonterminal `.7`, or if zero durable/nonterminal `.7` cannot be proven, stop all eight
app services (API, dispatcher, acquisition scheduler/worker, governance scheduler/worker, content
scheduler/worker), retain candidate + `.7`, keep only PostgreSQL/MinIO, and request incident
direction.

## Deferred standard digest path

The repository's standard deployer remains unchanged. It is not invoked because there is no exact
project registry/push/pull capability or genuine previous-digest baseline. Completing task 08-14's
external activation blockers is a later operation; this release neither fabricates standard
manifests nor claims future `make release-prod` readiness.

The offline local-tag route therefore requires one explicit Phase 1.4 user exception to the
committed digest-only release policy before task activation.

## Security and evidence

Release logs contain only hashes, counts, versions, image IDs, status groups, and health/restart
state. They do not emit env bytes, record IDs, URLs, prompts, object keys, provider bodies, or
secrets. No provider, fixture, manual business action, or WeCom call is part of acceptance.
