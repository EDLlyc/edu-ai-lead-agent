# Zhipu image OCR provider rejection — result

## Status

Repository implementation Phases 0–2 and the independent Phase 2.2 quality review are complete.
The release-preparation remainder of Phase 3 and Phases 4–7 remain for the main session and require
the separately authorized release, production, bounded live-gate, activation, and cleanup workflow.

The implementer did not access production, SSH, Zhipu/Comfly provider APIs, remote MinIO, or WeCom.
No paid or live call, deployment, enqueue, retry, resend, commit, or push was performed. External
call counts for image generation, OCR, and WeCom are all zero. The first Phase 0 production
baseline checkbox remains open because production access was explicitly outside this implementation
scope; the previously recorded task evidence was used without repeating a remote probe.

## Implemented contract

- Added independent bounded image OCR settings: `IMAGE_OCR_MODEL=glm-ocr`, 10 MiB raw input,
  1 MiB response, and 120-second OCR timeout. Controlled diversity rejects any other OCR model.
- Added `ZhipuImageTextRecognizer` on `/layout_parsing`. It accepts only validated PNG/JPEG bytes,
  sends a private Base64 data URL with crop/layout visualization disabled, and uses the existing
  bounded Zhipu HTTP transport and typed provider failures.
- Enforced case-normalized model identity, exactly one page, bounded unique positive layout
  indices, allowlisted labels, finite ordered `[0,1]` boxes, bounded content, at most eight lines,
  deterministic `(y1, x1, index)` ordering, and the existing exact ordered visual-text gate.
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

## Remaining work

- Phase 3 release preparation, commit/push, and immutable offline image build.
- Phases 4–7 production backup/quiesce/deploy, one bounded deterministic live OCR gate, one isolated
  news acceptance, fail-closed activation or rollback, cleanup, and final evidence recording.
- Production flags were not read or changed by this implementer; their final state must be verified
  by the authorized main-session workflow before and after any deployment.
