# Strict visual production integration — independent implementation check

Date: 2026-09-07. Reviewer: `/root/strict_visual_check`.

## Scope and verdict

Review target: `/root/projects/edu-ai-lead-agent/.trellis/worktrees/visual-quality-preview`,
branch `release/visual-quality-preview-20260907`, base `218015e` (runtime matches live `6154c78`).
Root runtime/Reviewer WIP was not edited or built. The task's PRD, design, implementation,
check-context files and complete backend quality guidelines were read; Trellis check and
before-development instructions governed the review. Frontend quality/type-safety instructions
were also read for the regenerated API contract.

**IMPLEMENTATION_CHECK_PASS — change-relative, with the explicit existing-gate and test-environment
exceptions below.** No unresolved implementation regression was found after the fixes and final
full-scope checks. `SAFE_TO_DEPLOY` is not granted by this report. This is a prospective new-run implementation
check, not proof of new live model audits or permission to replay, overwrite or publish old drafts.

## Findings fixed

1. **Native V4 prompt could exceed the image port's 2,000-character limit before dispatch.**
   `backend/app/application/services/official_account_visual_generation.py` now builds a
   separately bounded V4 prompt rather than appending to the already long V3 prompt. The full
   bounded topic (300), section heading (120) and selected block context (480), native geometry,
   approved IP identity and negative constraints survive. No port limit was increased. A
   maximum-context regression and historical V3 prompt/plan hash tests pass; V1–V3 remain unchanged.

2. **The omitted-null snapshot serializer destroyed the typed public response schema.**
   `backend/app/domain/official_account_local.py` originally used a dictionary-returning wrap
   serializer, causing OpenAPI to expose `ArticleMediaSelectionSnapshot` as an arbitrary object.
   The locked Pydantic 2.13.4 field-level `exclude_if` now omits only null
   `reference_policy_version`, preserving legacy serialized bytes and the closed typed schema.
   Tests exercise both Pydantic serialization schema and actual FastAPI OpenAPI. OpenAPI and
   generated TypeScript were regenerated, never manually patched.

3. **Current-head migration consumers were not synchronized to additive head `20260907_0043`.**
   Updated current-head assertions in ten integration test modules, `scripts/doctor.sh`, and,
   with main's explicit approval, `deploy/release/migration-compatibility.json`. Explicit tests
   upgrading/downgrading to historical `20260901_0042` remain pinned there. The declaration keeps
   `previous_application_compatible=false` and now explicitly fences weekly v2/governance inputs
   even when zero Article rows exist. A release-contract regression protects that qualification.
   No sealed historical operator authorization was renewed.

4. **A mixed strict identity could enter the legacy executor before failing later.**
   Coordinated with the durable owner to add `OfficialAccountVersionIdentity.__post_init__`:
   either V4 member requires the strict marker; a non-null marker requires the exact strict policy,
   Zhipu and both V4 members. Legacy partial identities retain existing semantics. Updated one
   weekly test that previously constructed an intentionally incomplete new identity accidentally.

5. **Actual normal execution exposed a five-scene/reference-count mismatch.**
   The durable owner corrected strict Article construction to use five scenes, independent of
   the number of eligible distinct references. The normal regression uses three eligible genuine
   synthetic catalog records, repeats approved references deterministically, and produces five
   different generated scenes. This is not a repository fixture that manually converts an old
   Article into a strict Article.

6. **The durable audit decoder bypassed strict typing.**
   Coordinated replacement of dynamic `**kwargs` plus `type: ignore` with a closed, strict
   Pydantic dataclass JSON decoder. Unknown fields, malformed identities, booleans/floats in integer
   fields and invalid audit roles fail closed. There is no new type-ignore in this boundary.

7. **Cross-layer verification was initially incomplete.**
   Required and reviewed the new real PostgreSQL/MinIO normal material enqueue → executor →
   five generation intents/results → six audit intents/results → independent durable-ready gate →
   media resolver → prepared child → draft consumer regression. Synthetic adapters inspect
   committed pre-call rows. A second enqueue/export/worker pass reuses the same run/artifact and
   leaves call counts at 5 and 6. Added a separate strict weekly timeout regression: timeout is
   bounded/retryable, retry uses the frozen identity and existing run despite changed configuration,
   and `result_unknown` is terminal. No timeout or concurrency limits were raised.

## Cross-layer review conclusions

- Strict opt-in is absent/null for historical identities and exact for new strict identities;
  run identity and Article reference-policy snapshot are checked in both directions.
- Fixed Comfly `gpt-image-2` native `1536x1024` is enforced before requests and on decoded output.
  References are decoded and meet the 512-pixel short-edge floor. Five block-bound scenes are
  required; catalog assets are references, not substituted final illustrations.
- Generation and audit each require a committed newly-claimed durable intent and a current lease.
  Strict HTTP dispatch has one physical POST, no redirect/retry multiplication, bounded polling
  and result download, and exact direct GLM-5V-Turbo audit routing. Same-attempt concurrent claim,
  expired/stale leases, crash/unknown outcomes, heartbeat failure, storage/response persistence
  failures and sibling retention have offline regressions. Unknown work is never automatically
  reissued or repaired.
- Every successful generated parent is stored ready before any image audit. Five body uploads and
  the cover upload are normalized before their six audits; audit subjects bind exact final-byte
  SHA, decoded geometry, role, Article/render, parent generation, genuine reference, criteria,
  provider/model and policy. Boolean success with wrong identity or nonempty issues cannot pass.
- Repository ready gating independently requires the exact six accepted proofs, five distinct
  generated parents, ordered body slots and closed cover-0 lineage. Nullable SQL checks explicitly
  reject null native intent fields and null accepted record fingerprints. Populated downgrade is
  fenced. MinIO access is outside held database transactions.
- The cover is a recorded derivative of generated scene 0, final JPEG `1175x500` and below 64 KiB;
  generated body JPEGs are below 1 MiB. Resolver reconstruction and prepared validation recheck
  lineage and exact bytes. The draft consumer preserves audited upload bytes rather than running
  a second normalization. Article-visible alt text is deliberately Article-authoritative; the
  generated descriptor's contextual caption can differ without changing the Article.
- Original news images remain separate context-only media with source bytes, rights, attribution,
  placement and derivative provenance preserved; zero or two originals are covered. They are not
  counted among five generated scenes or six generated-image audits.
- New weekly input v2 freezes every Article identity field. Legacy retries use a proven prior
  material-linked identity or fail closed after strict activation, never derive a paid replacement
  from new global settings. Three prepared children must have one policy; no DAG version bump or
  old-weekly replay was added.
- Strict prepared child v2 reuses the frozen pure V2 Xiaosai renderer, then a lossless inline-CSS
  projection. Exact reconstructed manifest/files, symlinks, nested manifests, unknown fields,
  tampered final bytes and source lineage are validated before upload. Up to 256 escaped URL
  characters per inline image are reserved before upload and enforced on each returned URL.
  HTML remains at most 19,999 characters; no content is truncated and no platform cap is raised.
- The accepted preview service, preview CLI, image generation port, image provider implementation,
  audit adapter and factory SHA identities remain byte-identical to the accepted preview review
  where they were already finalized. The production V4 prompt change does not change preview V3.
  Accepted preview output directories were not written or removed.

## Verification and reproducibility

Product commands ran from the candidate with `PYTHONPATH=backend`, `conda run --name edu-ai`.
Local integration endpoints were PostgreSQL loopback 44640 and MinIO loopback 44642, using task-only
credentials. Integration fixtures create unique databases/buckets; the strict module has its own
database so its intentional downgrade fence cannot poison legacy migration tests. Main owns the
test containers and their final cleanup. No external model, SSH, production database/service,
image generation, deployment, commit, push, draft creation or publication call was made here.

Final frozen-tree `make -k backend-check` completed: **2,124 passed, 34 failed, zero setup errors,
80% coverage**. JUnit comparison against the independently baselined preview run contains exactly
the same **33 baseline failures** plus the integration-credential/default-unit-test interaction
described below. All **81 strict policy/worker/prepared/PG tests pass** in the full suite.
All integration tests ran: **134 passed, the same 2 baseline failures**. No new implementation
failure remains. Full lint passes; full format has only the two unchanged baseline files; full
mypy has only the two unchanged Literal errors. Full make correctly exits nonzero; it is not
presented as a green general release gate.

Artifacts: `/tmp/edu-ai-strict-visual-final-Gsgz7K/final-backend.xml` and
`final-backend-check.log`. The reviewed runtime digest below was rechecked after the final run.

Exact final full-gate invocation (local test credentials only):

```sh
env -u OFFICIAL_ACCOUNT_LOCAL_VISUAL_PIPELINE_VERSION \
  -u CONTENT_LLM_RERANK_ENABLED -u IMAGE_PROVIDER_MODE \
  PYTHONPATH=backend \
  DATABASE_URL=postgresql+asyncpg://strict_visual_test:strict_visual_local_only@127.0.0.1:44640/strict_visual_test \
  MINIO_ENDPOINT=http://127.0.0.1:44642 \
  MINIO_ACCESS_KEY=strict_visual_test MINIO_SECRET_KEY=strict_visual_local_only \
  AI_PROVIDER_MODE=disabled VISUAL_EMBEDDING_PROVIDER_MODE=disabled \
  PYTEST_ADDOPTS=--junitxml=/tmp/edu-ai-strict-visual-final-Gsgz7K/final-backend.xml \
  make -k backend-check
```

Exact focused pytest selection, with the same local integration endpoints and fake/off provider
configuration (`CONTENT_LLM_RERANK_ENABLED=false`, `IMAGE_PROVIDER_MODE=fake` for this focused run):

```sh
conda run --name edu-ai pytest \
  backend/tests/integration/test_official_account_strict_visual.py \
  backend/tests/unit/test_official_account_strict_visual_policy.py \
  backend/tests/unit/test_official_account_strict_visual_worker.py \
  backend/tests/unit/test_official_account_strict_prepared.py \
  backend/tests/unit/test_official_account_weekly_production.py \
  backend/tests/unit/test_official_account_preview_image_geometry.py \
  backend/tests/unit/test_official_account_visual_preview.py \
  backend/tests/unit/test_image_generation.py \
  backend/tests/unit/test_image_validation_ai.py \
  backend/tests/unit/test_content_worker_validation_wiring.py \
  backend/tests/unit/test_official_account_worker.py \
  backend/tests/unit/test_official_account_visual_generation.py \
  backend/tests/unit/test_wechat_official_account_draft.py \
  backend/tests/unit/test_wechat_official_account_draft_worker.py \
  -q --no-cov --junitxml=/tmp/edu-ai-strict-visual-final-Gsgz7K/focused.xml
```

Already completed checks:

- Changed Python scope: Ruff lint and formatting pass for 52 files; strict mypy passes for all
  31 changed/new runtime modules. `bash -n scripts/doctor.sh` and `git diff --check` pass.
- Final focused cross-layer command includes the strict PG module, strict policy/worker/prepared,
  weekly production, preview geometry/runner, image generation/validation, worker wiring, legacy
  worker/planner, and real draft HTTP/worker tests: **375 passed, 6 failed, zero setup errors**.
  All **16 strict PostgreSQL tests pass**, including the real normal enqueue-to-consumer test.
  All six failures are the already-baselined missing private PNG cases in the legacy draft test.
  Machine artifact: `/tmp/edu-ai-strict-visual-final-Gsgz7K/focused.xml`.
- Default-settings regressions without integration environment overrides: **4 passed**, including
  the production-placeholder credential test, two rerank default tests and repaired weekly fixture.
- `pytest deploy/release/tests -q --no-cov`: **67 passed, 1 failed**. The remaining unchanged
  compose inbox-path assertion independently fails on clean base `218015e`; the new-head
  compatibility/doctor contract passes. Artifact: same directory `release.xml` and
  `release-check.log`. These are mock release tests, not release operations.
- Full `make -k frontend-check`: API and agent API drift checks, formatting, ESLint, TypeScript and
  production build pass. **243 component/unit tests pass**, but one existing Playwright file is
  wrongly collected by Vitest and its top-level `test.skip` fails suite collection. Exact base
  archive independently reproduces **243 passed / the same one failed suite**. Separately,
  `npm run test --prefix frontend -- --run src` passes **34 files / 243 tests**.
- Frontend package.json and lockfile byte-match the installed dependency tree's root manifests.
  Test-only candidate and temporary-base `node_modules` symlinks were removed by exact-path unlink;
  the temporary archive's `frontend` source tree was then removed with a checked exact-directory,
  non-forced recursive removal while retaining its diagnostic log. This was a disposable archive
  of tracked base code, recoverable with `git archive 218015e frontend`, not a registered worktree
  or user source directory. Root dependency packages were not removed, installed or source-edited;
  standard tool caches under the shared dependency directory (including configured
  `node_modules/.tmp/*.tsbuildinfo`) may be refreshed by these checks. The preexisting clean
  `weekly-source-preflight` worktree remains clean. Candidate production build output is ordinary
  ignored `frontend/dist`, not any accepted article output. Frontend logs:
  `/tmp/edu-ai-strict-frontend-check-TjfRMV/`; base reproduction:
  `/tmp/edu-ai-strict-base-frontend-xadLPB/frontend-test.log`.

### Baseline generated-contract drift, not a runtime feature removal

Before this change, clean base `218015e` already fails `export_openapi.py --check`. Independent
base schema comparison finds only obsolete generated `LlmDimensionScoresResponse` and
`llm_dimension_scores`/`llm_total` properties in `ContentSlotScoreResponse` and `TopicScoreResponse`.
These do not exist in the base runtime. Regeneration removes those stale generated declarations
and adds the strict reference-policy property; it does not import dirty-root Reviewer work or
remove a runtime feature. Frontend has no consumers of those obsolete declarations.

### Initial full-gate and test-environment attribution

An intentionally interrupted first attempt is not acceptance evidence. The next complete run
recorded **2120 passed / 37 failed / zero setup errors / 80% coverage** in `backend.xml`.
JUnit set comparison contains all original 33 preview-baseline failures and exactly four extras:
the subsequently repaired mixed-identity test fixture, two tests affected by the review command's
unnecessary `CONTENT_LLM_RERANK_ENABLED=false`, and a default-placeholder assertion affected by
supplying valid integration credentials. All four pass when exercised with the appropriate
default environment. The credential assertion also independently fails on clean base under
the identical integration environment (`base-default-credentials.log`); this is explicitly a
test-environment interaction, not a newly attributed product defect. The final full rerun removes
the unnecessary rerank/image overrides and runs the repaired fixture, leaving precisely that
one environment-only exception in addition to the 33 unchanged baseline failures.

## Unresolved release conditions and nonclaims

1. **General repository gates are not green.** The known 33 backend failures, two existing format
   files, two existing `local_exact_target_selection.py:158–159` Literal errors, frontend E2E
   collection issue and release mock inbox assertion are recorded rather than suppressed or
   opportunistically changed. Main must apply the project's release policy to these known
   exceptions; a change-relative implementation pass is not a clean global release gate.
2. **Prospective activation and live acceptance remain separate.** No new strict production run
   has been observed by this reviewer. Synthetic accepted audit proofs are test data, not actual
   six GLM-5V-Turbo audit outcomes. Main's actual gzh/Chromium diagnostic of the accepted full
   Article with explicitly synthetic strict proofs is useful layout evidence only: 18,441 HTML
   characters, 19,866 with URL reserve, 63,621-byte cover, zero layout diagnostics and no overflow
   at 320/430. It does not retroactively authorize old Article/draft replacement or publication.
3. **Latency is bounded, not guaranteed to fit the weekly execution window.** Current observed
   production settings are one Article worker, 300-second lease with 60-second heartbeat,
   720-second weekly Article wait and unchanged 900-second node / 3,600-second root budgets.
   Main's one historical accepted-preview sample totals 242.121 seconds generation plus 46.128
   seconds audit (288.249 seconds for one Article); this is not a p95 or SLA. Sequential configured
   worst case can approach 43 minutes per Article (up to 48 at the policy's 360-second generation
   ceiling), before text/storage. Frozen-identity retry and bounded terminal failures prevent
   duplicate paid replacement; they do not guarantee three Articles finish on time. Main must
   observe a prospective run's whole-queue timing and bounded outcome without blind timeout or
   concurrency increases. Already running Article work can outlive a failed weekly wait; inspect
   and reuse its durable identity instead of enqueueing a replacement.
4. **Rollback is not image-only and not just an Alembic downgrade.** New weekly v2 checkpoints or
   governance inputs can exist before any strict Article/generation/audit rows. Old consumers
   reject that version. Either prove all new state absent before rollback, or retain compatible
   consumers/use a forward fix. The SQL migration's populated-row fence alone is insufficient.
   Previous application compatibility remains false, and old sealed operators remain expired.

## Reviewed runtime identities

Deterministic digest of sorted changed/new backend runtime and migration file SHA lines:
`6ad46cc5924318ba56a33240184b780b970196b6386b8030bbaeea48d2cc1441`.
Command: `git ls-files -m -o --exclude-standard backend/app backend/alembic | rg '\.py$' | sort -u | xargs sha256sum | sha256sum`.

Selected final file SHA-256:

| File | SHA-256 |
|---|---|
| migration `20260907_0043_strict_visual_pipeline.py` | `f87dd5bd8fd7af2c31c77138a338912324d1ed2dbe668945735d1fde0b12a75b` |
| service `official_account_strict_visual.py` | `230819ede4cfbd96b8e38b02ae71b30f0a95aaad20bf6e64e9b0a9a93d039cec` |
| repository `official_account_strict_visual.py` | `5330dd3479618ef0d1ef3c19ae66304feb677387121589d293df46386559849d` |
| service `official_account_strict_prepared.py` | `f605a82844e076089059abb550ff26645559b71d1ca1655154c3d01a52ac518d` |
| `backend/openapi.json` | `5835efaa7340e9b9d271fc9b3a3d3330f1d83bda8d04685de4ba306284d5b6a5` |
| generated frontend `schema.d.ts` | `238647abe4a40fa61abc4d8cac9be4127197d4922c11bfd3181c0898918de610` |
