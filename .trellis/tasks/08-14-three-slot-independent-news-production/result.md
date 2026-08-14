# Implementation result

## Phase 0 baseline

- Loaded the complete task PRD/design/implementation plan, required backend/frontend specs,
  cross-layer and reuse guides, and every routed agent-pipeline section before editing code.
- Confirmed the only pre-task worktree changes are the explicitly excluded Trellis skill,
  `reports/`, the separate digest-release task, and this task directory.
- Confirmed Alembic has one head at `20260807_0019` and Compose exposes `content`, `governance`, and
  `wecom` profiles.
- OpenAPI baseline SHA-256: `1b033b273106d157370457575228acf61d9b14615a5d67278b3f7ca333c2387f`.
- Generated frontend schema baseline SHA-256:
  `a65bad7b7c840ae560dfcc76dbd162cecf2e312ae05a471e3506f19f8d8588a4`.
- Baseline OpenAPI export/check and generated-schema drift check passed.
- Baseline backend focused suites passed: 207 tests across acquisition, topic selection, copy,
  material package, WeCom, repositories, and topic APIs.
- Baseline frontend material mapper/hook/component suites passed: 12 tests.
- Baseline clean-head migration and isolated downgrade suites passed: 2 tests.

No provider or Enterprise WeChat call was made.

## Phase 1 — domain and persistence

- Added the exhaustive `morning`/`noon`/`evening` domain, bounded schedules, aware
  preparation/target/expiry calculations, deterministic `slot-ranking-v1`, and explicit unfilled
  reasons. The preparation calculation also covers a valid previous-day preparation time for a
  next-day target.
- Added Alembic `20260814_0020` and ORM persistence for slot runs, immutable scores, selections,
  typed acquisition identity, copy-origin XOR, delivery windows, and slot job projections.
- Preserved legacy null-slot uniqueness and date-wide formal-delivery protection. Downgrade refuses
  to discard live slot-origin data. PostgreSQL migration/constraint/upgrade/downgrade tests pass.

## Phase 2 — acquisition, readiness, and selection

- Added independent scheduled acquisition reconciliation for each enabled slot while keeping the
  legacy daily path unchanged when slot mode is off. Slot mode additionally requires the existing
  global content runtime gate.
- Selection requires the exact terminal acquisition/governance lineage and immutable governed
  cutoff. Transactional persistence uses a date-level advisory lock and same-day event exclusions
  so replay and concurrent slots converge without duplicates.
- Slot preference uses stored governed/editorial/product signals only after legacy eligibility and
  veto decisions. Tests cover all three preference profiles, bilingual inputs, global Ministry
  priority, no-rescue, stable ties, 0--3 results, and at most nine distinct selections per day.

## Phase 3 — independent production lineage

- Added discriminated legacy/slot topic origins and strict repository loading; missing or dual
  origins are rejected.
- Each selected item reconciles to its own copy run and carries slot, ordinal, target, and expiry
  through copy, image/material processing, package snapshots, API responses, and JSON downloads.
- The existing evidence-bound full-copy, brand RAG, IP asset, image validation/repair/fallback, and
  immutable-version contracts remain in use. Fake-provider acceptance covers legacy plus all three
  slot origins, while failure/replay tests preserve sibling isolation.
- The content worker now selects the matching legacy or slot reconciliation path instead of running
  legacy reconciliation unconditionally in slot mode.

## Phase 4 — delivery windows and durable throttling

- Added one typed lane per slot/recipient/provider/mode, one formal job per eligible package, typed
  target/expiry, and persistent `next_allowed_at` throttling.
- Claiming locks the ready delivery window before selecting the lowest ready ordinal. This ordering
  was tightened after the PostgreSQL concurrency test exposed that locking a higher-ordinal job
  first could otherwise acquire the lane and violate ordering.
- Clock-controlled and real PostgreSQL tests cover no early send, configured 60-second gap,
  concurrent dispatchers, expiry without provider calls, restart/replay, lower-sibling bypass, and
  legacy guard compatibility. Disabled slots cannot be auto-reconciled or directly enqueued.

## Phase 5 — API and frontend

- Added typed slot create/run/score/content-edition endpoints with stable conflicts and safe source
  projections. Source links share the HTTPS normalizer and reject userinfo, IP literals, malformed
  URLs, and HTTP.
- Regenerated `backend/openapi.json` and the frontend schema. The legacy daily topic response was
  not changed.
- Added the date-oriented three-column content edition board using generated types and existing
  material cards. Mapper/hook/component tests cover empty, preparing, partial, failed, expired,
  mixed sibling, delivered, polling, source-link, keyboard, and 0/1/3-item states.

## Phase 6 — configuration and operations

- Added matching environment and Compose settings for all services. Slot mode, every individual
  slot, WeCom, and auto delivery remain disabled by default; review remains required by default.
- Extended doctor and production evidence with safe configuration and queue/window counters without
  content, credentials, private object paths, or private URLs.
- Updated README, production migration runbook, backend database/topic/agent/WeCom specs, and
  frontend component/index specs with versioned slot and rollout/rollback contracts.
- Added the indexed seven-section `content-slot-production.md` executable contract so future work
  has one cross-layer source for signatures, error behavior, examples, and required tests.

## Phase 7 — final verification

- Final focused gate: Ruff format/check passed, strict mypy passed for 139 application source files,
  and 146 slot/copy/delivery/API/PostgreSQL tests passed.
- Final `make backend-check`: Ruff format checked 232 files; Ruff and strict mypy checked 142 source
  files; all 717 backend tests passed with 79% aggregate coverage.
- Final `make frontend-check`: OpenAPI and generated-type drift checks, Prettier, ESLint, TypeScript,
  38 Vitest tests in 9 files, and the Vite production build all passed.
- `make doctor`, the full governance/content/WeCom Compose render, unique Alembic head
  `20260814_0020`, three PostgreSQL migration/upgrade/downgrade tests, shell syntax checks, API
  contract drift check, and `git diff --check` passed.
- The controlled offline acceptance path composes deterministic 0--3/all-three-slot selection,
  cross-slot max-nine deduplication, fake copy generation for all origin variants, existing
  image/material quality suites, independent API projections, and PostgreSQL delivery
  ordering/gap/expiry/replay tests. It made no real model, image, or Enterprise WeChat call.
- Changed/untracked-file audit found only this task's planned files plus the explicitly excluded
  pre-existing Trellis skill, `reports/`, and separate digest-release task. Added-line scans found
  zero secret-shaped assignments and zero authenticated URLs. OpenAPI/migration drift checks are
  clean.

## Independent Trellis check — 2026-08-14

The independent review loaded the native `check.jsonl` context, all PRD/design/implementation/result
artifacts, the routed oversized agent-pipeline sections, every changed/untracked task file, and the
complete diff. It repaired the following material findings before freezing the implementation:

- Slot candidate history originally projected only legacy daily selections. Prior
  `content_slot_selections` from the configured seven-day window now participate in
  `days_since_last_selection`, theme-repetition projection and the existing repeat veto, while the
  legacy daily loader remains daily-only for exact `.4`/`.5`/`.6` replay compatibility.
- A completed delivery window with no job/package could remain `preparing`. Edition and item
  projection now emit explicit `expired` after the immutable run window, without hiding explicit
  delivered, failed or unknown outcomes.
- Doctor did not compare the six per-slot target hour/minute settings across every relevant
  service. They now participate in the same cross-service identity check as the feature/window/gap
  settings.
- Persisted slot ordering keys used a different eligibility/exclusion grouping from the actual
  deterministic sorter. The stored explanation now exactly matches the live ordering groups.
- Migration/ORM constraints did not fully bind duplicated lineage fields. Composite acquisition,
  governance, run/score/selection, copy-origin, ordinal and delivery-window foreign keys and their
  target uniques now reject cross-wired date/timezone/slot/event/version/window data in PostgreSQL;
  downgrade drops them in dependency-safe order.
- A slot delivery left `running` after its durable lease expired could be reclaimed automatically,
  risking resend after an unknown provider outcome. Slot jobs now persist the current child and job
  as `delivery_unknown`, record a safe durable attempt, never auto-reclaim it, and allow the next
  lowest ready ordinal to continue. Legacy stale-running recovery remains unchanged.
- Decision persistence now rejects score/selection lineage drift and enforces the same-day maximum
  of nine under the date advisory lock, in addition to the database cross-slot event uniqueness.
- The final backend format gate found and corrected one missing module-level separator in the copy
  response schema; this was formatting-only.

Focused verification after the fixes passed 48 content-slot/API/WeCom unit tests and 10 real
PostgreSQL slot/API/migration tests, including clean upgrade, metadata parity, safe downgrade,
cross-wire FK rejection, concurrent ordering/gap, stale-lease unknown handling and legacy history
isolation. Final `make backend-check` passed Ruff format/lint, strict mypy for 142 source files and
724 backend tests at 79% aggregate coverage. Final `make frontend-check` passed OpenAPI export and
generated-type drift, Prettier, ESLint, TypeScript, 38 Vitest tests in 9 files and the Vite build.
Full-profile Compose render, shell syntax, unique Alembic head `20260814_0020`, `make doctor`,
secret/authenticated-URL scan and `git diff --check` also passed.

No assertion was weakened, no real provider/Enterprise WeChat call was made, and no commit,
deployment or production mutation was performed. The excluded pre-existing Trellis skill,
`reports/`, and digest-release task were not modified by this review. The production
implementation is frozen with the independent check complete.
