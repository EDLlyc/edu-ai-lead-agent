# Implementation Plan — 微信公众号本地草稿 MVP

## Pre-start checks

- [ ] Obtain explicit approval of the final planning summary before `task.py start`.
- [ ] Re-run `git status --short` and inspect diffs for every high-collision file; preserve all unrelated/user changes.
- [ ] Re-run `python3 ./.trellis/scripts/get_context.py --mode packages` and load curated manifests.
- [ ] Confirm the current Alembic head before choosing the new revision ID.

## Phase 1 — Domain and deterministic contracts

- [ ] Add strict source union, Article Package v1, blocks, claims, audit verdict, media/draft values and status enums.
- [ ] Implement canonical JSON and source/generation/content/render/media/draft request fingerprints.
- [ ] Implement material-package eligibility projection and bounded fixture source.
- [ ] Add historical v1/current v2 Article Package dispatch plus a versioned deterministic media planner for 1--5
      distinct body slots, target 3--5, stable section placement and explicit safe degradation.
- [ ] Implement deterministic article validation: structure/length, known IDs, evidence-vs-brand separation, block claim
      coverage, provider/model/version identity and safe issue codes.
- [ ] Implement the versioned HTML renderer with escaped text, fixed tags/styles, verified source links and exact media
      placeholders.
- [ ] Add unit tests before persistence/HTTP wiring.

## Phase 2 — Database and repository

- [ ] Add SQLAlchemy models for runs, article versions, attempts, render versions, local media and local drafts.
- [ ] Add an additive Alembic migration with FK/check/unique/index contracts and update migration-head assertions.
- [ ] Relax body ordinal constraints only to 0--4, retain cover ordinal 0, add/backfill typed draft-to-body-media
      associations, and preserve legacy ordinal-0 FKs and historical rows.
- [ ] Implement repository enqueue/list/detail/claim/heartbeat/stage-persist/retry operations using short transactions,
      lease tokens and `FOR UPDATE SKIP LOCKED`.
- [ ] Add real PostgreSQL tests for clean upgrade, metadata parity, source XOR, status/role constraints, concurrent
      idempotency, expired lease reclaim and unknown-result non-retry.

## Phase 3 — Article model adapters and worker

- [ ] Add generator/auditor application ports and deterministic fake implementations.
- [ ] Add the Zhipu structured article adapter using existing low-level retry/JSON/error utilities, strict schema,
      bounded prompt data, safe provider identity and usage metadata.
- [ ] Build stable generation/audit prompts with explicit untrusted-data boundaries and no HTML/URL output.
- [ ] Implement the stage executor: generate -> validate -> audit -> render, persisting each successful immutable
      artifact before the next step.
- [ ] Add independent `official_account_worker_main.py`, heartbeat, graceful shutdown and disabled-mode behavior.
- [ ] Add provider MockTransport tests and worker failure/restart tests; prove no network client is created for fixture.

## Phase 4 — Local media and draft simulation

- [ ] Implement an approved fixture image catalog with immutable descriptor/tag/checksum/dimension validation and
      real-material safe degradation when only the primary image artifact is available.
- [ ] Persist separate per-ordinal body/cover role records and stable local IDs; reject duplicate body bytes.
- [ ] Implement local draft adapter, exact all-slot replacement, ordered body associations, stable local draft ID and `simulation=true`.
- [ ] Complete worker stages for every missing body ordinal -> cover -> draft, including deterministic retry and injected
      `result_unknown` behavior.
- [ ] Add checksum/signature, role isolation, replay, partial-stage resume and no-blind-retry tests.

## Phase 5 — API, OpenAPI and preview

- [ ] Add capability, list, create, detail, retry, media and preview schemas/routes under
      `/api/v1/official-account-local`.
- [ ] Gate routes with local settings; live create fails closed without a configured provider while fixture stays usable.
- [ ] Return 202/Location for enqueue/retry and safe typed error envelopes for state conflicts.
- [ ] Add preview CSP/no-store/nosniff/no-referrer headers and fixed document wrapper.
- [ ] Add API/contract tests for safe projections, preview/media behavior and absence of publishing/credential fields.
- [ ] Regenerate `backend/openapi.json` and frontend API types through project commands; never edit generated types.

## Phase 6 — Local draft workbench UI

- [ ] Add the development-only `features/official-account-local` API mapper, query keys/hooks and terminal polling.
- [ ] Add eligible material selector, explicit live button, fixture action, run/status list and typed error states.
- [ ] Add article metadata/sections, sources/claim bindings, quality/version/usage, ordered body gallery/selection
      explanation, cover and simulation detail while preserving the primary-body compatibility field.
- [ ] Add sandboxed mobile preview iframe using `preview_url`; do not use `dangerouslySetInnerHTML`.
- [ ] Lazy-load behind `VITE_OFFICIAL_ACCOUNT_LOCAL_ENABLED`; add no publish/send/login/account/secret UI.
- [ ] Add mapper/hook/component/App tests covering accessibility, polling stop, explicit live action and boundary labels.

## Phase 7 — Local runtime and documentation

- [ ] Add official-account local settings to `.env.example`/Compose with safe disabled defaults.
- [ ] Add opt-in Compose worker profile and Make/script commands for full fixture demo and one explicit live smoke.
- [ ] Ensure the fixture command is idempotent, starts only loopback services, performs zero external calls and reports
      the browser URL without secrets/private paths.
- [ ] Document setup, fixture flow, live provider prerequisites, safe smoke usage and the no-WeChat boundary in README.
- [ ] Document why fixture reaches 3--5 images while live may safely degrade when its material package exposes only
      one approved image; never imply that the local slice searches the web or calls image generation at runtime.
- [ ] Verify Compose config/build without AI or WeChat credentials.

## Phase 8 — Final verification

- [ ] Run focused backend unit/contract/integration tests for all new modules.
- [ ] Run migration upgrade-to-head and metadata parity against real PostgreSQL.
- [ ] Run API/OpenAPI generation and drift checks.
- [ ] Run focused frontend tests, strict typecheck, lint and production build.
- [ ] Run the provider-free fixture demo and capture safe evidence of article/media/draft/preview readiness.
- [ ] Export twice, assert every planned body file and placeholder, distinct checksums, ZIP exactness and a JS-disabled
      file-only 430px screenshot with no external request.
- [ ] If configured credentials are available, run exactly one opt-in live article smoke from an eligible material
      package and inspect only the persisted/safe projection; never call WeChat.
- [ ] Run full `make backend-check`, `make frontend-check`, `docker compose config --quiet`, `git diff --check`,
      sensitive-field scans and review all changed files against PRD/design.
- [ ] Use `trellis-check`, resolve findings, update executable specs if the implementation establishes a reusable
      contract, then use `trellis-finish-work`.

## Expected validation commands

```bash
python3 ./.trellis/scripts/task.py current
python3 ./.trellis/scripts/task.py validate \
  .trellis/tasks/08-21-wechat-official-account-local-draft-mvp
make backend-format-check
make backend-lint
make backend-typecheck
conda run --name edu-ai pytest backend/tests/unit/test_official_account_article.py \
  backend/tests/unit/test_official_account_html.py \
  backend/tests/contract/test_official_account_article_provider.py -q
conda run --name edu-ai pytest backend/tests/integration/test_official_account_local.py \
  backend/tests/integration/test_migrations.py -q
make api-generate
make api-contract-check
npm run test --prefix frontend -- --run src/features/official-account-local src/app/App.test.tsx
make frontend-typecheck
make frontend-build
docker compose --profile official-account-local config --quiet
make official-account-local-demo
make backend-check
make frontend-check
git diff --check
```

The live command is opt-in and must require an explicit `MATERIAL_PACKAGE_ID`; its exact target name is added with
the runtime implementation and is never part of default CI.

## Phase 9 — Approved editorial refinement

- [ ] Add new exact version dispatch for semantic media-plan, current Article Package, renderer/style/template,
      fixture generator/rules, local adapter and export bundle; freeze every v1--v5 golden first.
- [ ] Implement balanced current placement and bounded deterministic one-to-one section/candidate semantic scoring;
      assert the fixture maps observation/experiment/review to sections 1/3/4 and historical plan v1 is unchanged.
- [ ] Replace generic alt/captions with approved semantic reader copy and remove engineering/governance phrases from
      the fixture article while preserving safe source/review metadata.
- [ ] Create metadata-stripped publication derivatives without overwriting PNG masters; pin type/extension/size/hash/
      dimensions, enforce byte bounds, and update current fixture media serving/export only.
- [ ] Add the next-head manual-review migration/model/repository/service/API with immutable idempotent approve/reject,
      bounded reviewer label/note, ready-only gate and conflicting-decision 409.
- [ ] Add ordered safe manual-review projection, generated OpenAPI/types and a development-only accessible editorial
      review rail. Do not add publish/send/account/credential actions or allow automatic approval.
- [ ] Add review versus copy-ready export modes. Pending/rejected retains warning; approved creates a separate exact
      tree/ZIP whose reader HTML omits warning chrome and whose fingerprint binds the review event.
- [ ] Add domain/export/API/repository/PostgreSQL/frontend/runtime tests for semantic assignment, 1/3/4 placement,
      derivatives, captions, natural fixture copy, review idempotency/conflict, copy-ready gating and historical goldens.
- [ ] Run focused backend/frontend/migration/OpenAPI/Compose/task/diff checks, create a fresh pending fixture bundle,
      and test approval/copy-ready only through controlled local acceptance without claiming AI approval.

## Phase 10 — Approved multimodal catalog matching

- [ ] Freeze all v1--v6 prompt/article/render/media/export goldens, then add the exact Article v4,
      media-plan/query/selector v3, renderer v7, adapter v5 and review-bundle v4 family; reject every mixed tuple.
- [ ] Reuse the existing Qwen3-VL embedding port/adapter/result identity and current 41-item approved brand catalog.
      Add a complete-index preflight so incomplete/mixed coverage makes zero paid query calls.
- [ ] Add a body-publication candidate projection that preserves approved catalog/checksum/role/kind lineage while
      keeping filenames/paths private. Keep the validated material-package primary image as the distinct cover.
- [ ] Implement bounded section query serialization and a deterministic maximum-weight one-to-one assignment over
      up to five placements and 41 candidates. Similarity is primary; tag score and stable candidate order break ties.
- [ ] Implement whole-plan fallback for disabled/single/incomplete/provider/result/catalog-race cases. Never mix
      partial semantic scores with fallback and never retry one query invisibly.
- [ ] Persist the bounded Article v4 media-selection snapshot before render and recover from it without any additional
      embedding call. Add migration `20260823_0029` from the actual head with v4 downgrade refusal.
- [ ] Extend the local adapter with deterministic metadata-stripped catalog publication derivatives and strict
      manifest/path/checksum/type/size validation. Never overwrite masters or persist/expose private paths.
- [ ] Add independent disabled-by-default settings/worker wiring, safe API/OpenAPI/generated-type projections and
      development-only UI labels for multimodal match versus deterministic fallback.
- [ ] Bind review-bundle v4 identity to the persisted selection snapshot while preserving pending/human-review and
      approved-only copy-ready semantics.
- [ ] Add focused domain/provider/application/recovery/PostgreSQL/API/frontend/export/runtime tests, including a
      fake complete 41-item index, zero-call preflight failures, semantic order change, full fallback and historical
      goldens. Default fixture/tests/export remain zero external.
- [ ] Run Trellis independent check, focused quality gates, fresh pending fixture/export twice and 430/320 screenshots.
      Do not call a real embedding provider, Zhipu, WeChat, WeCom, web search or image generation during acceptance.

## Risky files and rollback points

- High collision: `backend/app/core/config.py`, `backend/app/infrastructure/db/models.py`, migration tests,
  `backend/app/api_main.py`, `backend/openapi.json`, generated frontend schema, `frontend/src/app/App.tsx`,
  `compose.yaml`, `.env.example`, `Makefile`, `README.md`.
- Avoid modifying `content_worker_main.py` unless a proven shared helper is required; the new executor owns a separate
  worker entry point.
- Keep short-copy schemas/prompts/fingerprints byte-compatible. New article code must not widen `MaterialDraft`.
- Rollback behavior: disable local settings/profile and UI flag; additive rows remain audit data. Do not delete or
  rewrite existing material/copy/image/WeCom data.
- If a migration conflict appears because another active task moved head, stop and rebase the new additive revision
  on the actual head rather than editing or reverting the other task's migration.

## Follow-up checks before start

- No blocking product questions remain.
- `prd.md`, `design.md`, `implement.md`, `implement.jsonl`, `check.jsonl` must all be present and converged.
- Implementation approval must be a new user response after the final planning summary.

## Phase 11 — Follow-up structured-output reliability

- [x] Freeze v1--v7 initial provider payloads and introduce a v8 generator-v5/auditor-v2 identity.
- [x] Put canonical schema (and audit conditional invariant) in the v8 initial system instruction; include all
      outbound text in the input bound and retain one correction only.
- [x] Add migration `20260823_0030` for numeric Article v5, downgrade refusal, templates/default output 16,384 and
      focused historical/provider/config/migration/export tests.
- [x] Independently review v8 behavior, migration head and zero-egress default fixture; run at most one opt-in live
      smoke without WeChat or WeCom.

## Phase 12 — Explicit live-local review export

- [x] Keep fixture export as the default and add the affirmative CLI-only `--allow-live-local-export` review-mode
      path for ready simulated live runs; do not add an HTTP export endpoint.
- [x] Extract shared fail-closed persisted-media resolution for API/CLI; preserve catalog/source integrity checks and
      read bytes outside DB transactions.
- [x] Export the real ready v8 run to relative HTML/assets, offline preview, review metadata and deterministic ZIP;
      preserve pending review, prohibit copy-ready/published labels and verify repeat reuse without provider/WeChat/
      WeCom calls.

## Phase 13 — Manual IP-reference visual review supplement

- [x] Select only manifest-approved 小赛／赛先生 catalog files as local visual reference; keep private masters,
      paths, raw IDs, vectors, prompts and provider bodies out of the new local review bundle.
- [x] Generate and visually inspect five original 3:2 illustrations mapped to the five current article sections;
      reject any candidate with readable text, chest labels, logos, QR codes, watermarks or an advertising layout.
- [x] Export a fresh local preview/map/README/ZIP with safe public catalog references and image checksums; validate
      local-only HTML, JSON parseability and ZIP integrity. Do not modify the durable Article/worker/API/export
      pipeline or default zero-egress test behavior.

## Phase 14 — Automatic approved-IP body visuals

- [x] Add current-family generated-visual plan/prompt identities, immutable intent/result ports and an additive
      `20260824_0032` migration on the actual `0031` head. Keep the source-artifact/fixture/generated-media XOR
      and ready-only generated body-media relationship fail-closed.
- [x] Reuse the persisted v8 multimodal/deterministic selection snapshot, revalidate its approved public catalog
      reference, derive a transient section prompt and call the existing image-generation port only for a newly
      created durable intent. Do not persist prompt/raw IDs/paths/vectors/provider bodies and do not retry an
      uncertain provider call.
- [x] Wire a disabled-by-default local-worker setting, lazy provider construction, private content-addressed output
      store and safe API/OpenAPI detail projection. Default fixture/tests remain zero egress; no WeChat/WeCom/publish
      path or image-human-review action is introduced.
- [x] Add focused prompt/plan/result/configuration tests; regenerate OpenAPI and frontend generated API types; run
      focused lint, format, typecheck and official-account unit tests.

## Phase 15 — Block-anchored 3:2 visual profile

- [x] Add deterministic versioned provider-reference normalization: preserve valid PNG bytes and convert approved
      catalog JPEG input to bounded metadata-free PNG for exact ToApis/Comfly request builders.
- [x] Add current v2 plan/prompt/output identities, exact in-section semantic block selection and safe persisted
      anchor/reference-input metadata; retain a literal historical v1 planning/prompt/fingerprint path.
- [x] Add additive `20260824_0033` from the verified unique `0032` head and update model/repository parity without
      rewriting historical rows.
- [x] Persist the deterministic metadata-free 1536×1024 JPEG derivative as the real ready generated artifact used by
      staged media, HTML preview and export; add bounded semantic alt text.
- [x] Treat an ambiguous provider timeout after durable intent as immediate `result_unknown` with no automatic retry;
      preserve known validation/rejection as `failed`.
- [x] Show `generating_body_visuals` plus ready/total in the existing workbench timeline, preserve exact 3:2 gallery
      composition and add accessible semantic alt text without redesigning the application.
- [x] Regenerate OpenAPI/types and add focused no-network backend/frontend tests for v1 compatibility, JPEG
      normalization, timeout recovery, block fingerprints, output profile, timeline/progress and alt text.
- [x] Complete PostgreSQL migration/repository and final focused contract/Compose/diff gates; record exact results
      without making any external provider or WeChat/WeCom request.

## Phase 16 — Explicit one-call live image acceptance

- [x] Run one explicitly authorized Comfly paid generation with `IMAGE_MAX_ATTEMPTS=1`, the current v2
      block-anchor/request/output identities and one manifest-approved catalog JPEG reference. Make no article,
      embedding, WeChat, WeCom or publish request and never retry the paid call.
- [x] Save the safe local result under `output/official-account-live-image-acceptance-20260824`: the validated
      artifact is a metadata-free 1536×1024 JPEG, with request/provenance/checksum summary, offline preview and
      visual-inspection note that excludes secrets, provider URLs/bodies, prompt text and private paths.
- [x] Add a reusable one-shot local acceptance harness plus no-network unit coverage; run focused Ruff, mypy and
      image/official-account tests.
- [ ] P0 operator action: rotate the configured Comfly API key after an accidental local tool-output disclosure;
      never record the exposed value in task artifacts.
- [ ] Follow-up quality work: automated multimodal output inspection must reject or flag an image that is
      semantically relevant but does not visibly preserve the intended 小赛／赛先生 character identity.

## Phase 17 — News-backed visible-IP ToApis full-flow demo

- [x] Freeze literal v1/v2 visual identities and add v3 plan/prompt/request identities with mandatory visible company
      IP protagonist semantics; add `20260824_0034` from the verified unique `0033` head without rewriting `0033`.
- [x] Add bounded parsing and evidence/claim binding for the two approved Ministry of Education sources, keeping
      family guidance explicitly interpretive and making zero article/embedding provider calls.
- [x] Add the isolated operator-only ToApis runner: three manifest-approved single references, exclusive durable
      intent before each call, one attempt per image, timeout-to-unknown and no fourth call/substitution.
- [x] Create `output/official-account-news-ip-20260824-v1` with three metadata-free 1536×1024 JPEGs, safe HTML,
      evidence/visual/run projections, manifest, visual inspection and deterministic ZIP; keep all old outputs.
- [x] Run local visual inspection: all three images contain a clear 小赛／赛先生 protagonist and no readable text,
      Logo, QR code or watermark. Record 3 attempted / 3 succeeded / 0 retry and zero Comfly/WeChat/WeCom/publish.
- [x] Run focused Ruff, compile, mypy, 113 backend unit/worker/integration tests, migration upgrade/current/head and
      clean-upgrade test, output redaction/HTML/ZIP integrity checks and `git diff --check`.
