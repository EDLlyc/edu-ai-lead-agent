# Journal - LiYuchen (Part 1)

> AI development session journal
> Started: 2026-07-28

---


## Session 1: Initialize Trellis project guidelines

**Date**: 2026-07-28
**Task**: Initialize Trellis project guidelines
**Branch**: `main`

### Summary

Initialized Conda and Trellis, enabled Codex hooks, converted the technical report into backend/frontend engineering specs, validated the bootstrap task, and archived it.

### Git Commits

| Hash | Message |
|------|---------|
| `0b17dea` | (see git log) |

### Status

[OK] **Completed**


## Session 2: Configure full-stack development environment

**Date**: 2026-07-28
**Task**: Configure full-stack development environment
**Branch**: `main`

### Summary

Configured the reproducible Conda, FastAPI, React/Vite, PostgreSQL/pgvector, and MinIO development environment; added OpenAPI client generation and full quality checks; synchronized Trellis backend/frontend specifications and completed all acceptance criteria.

### Git Commits

| Hash | Message |
|------|---------|
| `9cac128` | (see git log) |
| `c1aa929` | (see git log) |
| `e386c8c` | (see git log) |

### Status

[OK] **Completed**


## Session 3: Revise technical report with evidence-first roadmap

**Date**: 2026-07-28
**Task**: Revise technical report with evidence-first roadmap
**Branch**: `main`

### Summary

Reworked the editable XeLaTeX technical report into a polished v0.3 architecture document, removed P-level milestones, made authoritative-source acquisition and evidence ingestion the first construction step, added safe acquisition and provenance contracts, generated and visually verified an eight-page PDF, and synchronized Trellis architecture references.

### Git Commits

| Hash | Message |
|------|---------|
| `1790cd4` | (see git log) |
| `1e3d247` | (see git log) |
| `4d008f6` | (see git log) |

### Status

[OK] **Completed**


## Session 4: Complete authoritative-source ingestion

**Date**: 2026-07-29
**Task**: Complete authoritative-source ingestion
**Branch**: `main`

### Summary

Completed the production-shaped first capability: governed daily acquisition from eight authoritative sources, deterministic AI-title filtering, safe fetching, immutable snapshots, provenance APIs, PostgreSQL/MinIO durability, deployment configuration, full verification, a live 8-of-8 acceptance run, and the phase-one LaTeX/PDF delivery report.

### Git Commits

| Hash | Message |
|------|---------|
| `da28c14` | (see git log) |
| `cda45d3` | (see git log) |
| `602f21a` | (see git log) |

### Status

[OK] **Completed**


## Session 5: Complete factual governance and event organization

**Date**: 2026-07-30
**Task**: Complete factual governance and event organization
**Branch**: `main`

### Summary

Completed the production-shaped second capability: versioned normalization and evidence-bound factual analysis, dual-purpose embeddings, exact/semantic deduplication, durable LangGraph execution, auditable event organization, internal APIs, independent deployment processes, a successful bounded live Zhipu workflow, explicit bounded gzip transport handling, executable backend specs, and final 201-test production verification.

### Git Commits

| Hash | Message |
|------|---------|
| `8ca954a` | (see git log) |

### Status

[OK] **Completed**


## Session 6: Daily topic selection MVP

**Date**: 2026-07-30
**Task**: Daily topic selection MVP
**Branch**: `main`

### Summary

Planned the remaining content-production MVP nodes and completed deterministic daily Top 1/no_topic selection with immutable preview scoring, seven-day and stale-event vetoes, PostgreSQL locking and leases, scheduler/worker/API delivery, Alembic 0005/0006, generated OpenAPI types, full backend/frontend verification, and updated operational/spec contracts.

### Git Commits

| Hash | Message |
|------|---------|
| `60574ef` | (see git log) |
| `b0d08fc` | (see git log) |

### Status

[OK] **Completed**


## Session 7: Brand knowledge RAG MVP

**Date**: 2026-07-30
**Task**: Brand knowledge RAG MVP
**Branch**: `main`

### Summary

Completed the private Sai Xiansheng brand-knowledge MVP: safe PDF/DOCX/TXT/Markdown ingestion, immutable MinIO originals, versioned chunks and 2048-dimensional embeddings, PostgreSQL full-text plus pgvector retrieval, internal upload/activation/diagnostic UI, strict separation from factual evidence, real ingestion of two supplied slide decks, and a private 26-asset visual manifest with sidecar and path-safety guards. Full backend, frontend, migration, deployment, and private-data isolation gates passed.

### Git Commits

| Hash | Message |
|------|---------|
| `e495a1c` | (see git log) |

### Status

[OK] **Completed**


## Session 8: Image generation and material package UI

**Date**: 2026-07-31
**Task**: Image generation and material package UI
**Branch**: `main`

### Summary

Completed the final content-production MVP child task: one-image generation through the ToAPIs gpt-image-2 contract, private MinIO storage, versioned material packages, accessible internal review/copy/download UI, migration 0009, and spec updates.

### Main Changes

- Added ToAPIs gpt-image-2 image adapter with deterministic fake provider, request-fingerprint idempotency, bounded polling/download, and typed error states
- Added private MinIO image store with content-addressed keys and checksum
- Added material package service, schemas, run/package/review APIs, and controlled image-download route
- Added migration 20260731_0009 and synced migration test head-revision assertions
- Added MaterialPackagePanel UI with generated OpenAPI types, TanStack Query polling, and accessible states
- Updated agent-pipeline.md with the image generation code-spec and database-guidelines.md with the head-revision sync rule

### Git Commits

| Hash | Message |
|------|---------|
| `4f31610` | (see git log) |
| `7f3a9eb` | (see git log) |
| `c4835d1` | (see git log) |
| `b0a4aab` | (see git log) |
| `ea08db8` | (see git log) |

### Testing

- [OK] Backend: ruff format/lint, mypy, 184 unit + 39 integration tests pass
- [OK] Frontend: prettier, eslint, tsc, vitest, vite build pass
- [OK] API contract check passes; end-to-end smoke returns 200/404 as expected

### Status

[OK] **Completed**

### Next Steps

- Run parent task 07-30-content-production-mvp integration gate and archive it


## Session 9: Full project runtime verification

**Date**: 2026-08-03
**Task**: Full project runtime verification
**Branch**: `main`

### Summary

Verified the full local MVP stack: backend and frontend quality gates, PostgreSQL/pgvector and MinIO migrations, 39 integration tests, Compose API startup, acquisition worker execution, and /healthz. Found one stale scripts/doctor.sh migration-head assertion expecting 20260730_0007 while current head is 20260731_0009; no product code was changed.

### Git Commits

| Hash | Message |
|------|---------|
| `7a04fc0` | (see git log) |

### Status

[OK] **Completed**


## Session 10: Complete content pipeline hardening and image API diagnosis

**Date**: 2026-08-04
**Task**: Complete content pipeline hardening and image API diagnosis
**Branch**: `main`

### Summary

Completed and verified OCR brand ingestion, freshness and pacing controls, parent-facing copy/audit updates, idempotent material-package delivery, and image quota error handling. Rebuilt content-worker successfully. ToAPIs image generation was tested in the real worker and returned quota_not_enough (HTTP 403), so no image was fabricated or persisted as success. GitHub push remains pending due to a local TLS handshake failure.

### Git Commits

| Hash | Message |
|------|---------|
| `34f932b` | (see git log) |

### Status

[OK] **Completed**


## Session 11: Switch image generation to Comfly

**Date**: 2026-08-04
**Task**: Switch image generation to Comfly
**Branch**: `main`

### Summary

Added the Comfly OpenAI-compatible image provider at https://ai.comfly.org with validated config, bounded URL/base64/task handling, safe retries and redaction, API/worker lifecycle wiring, smoke tooling, tests, Compose parity, and backend spec updates. Backend 344 tests, Ruff, mypy, frontend checks, doctor, Compose, and credential scans passed. /v1/models returned HTTP 200 with gpt-image-2. Live image smoke failed closed because the provider CDN hostname is not yet explicitly configured in COMFLY_OUTPUT_HOSTS; no fake or persisted image was created. Pushed main at 6c27d4c.

### Git Commits

| Hash | Message |
|------|---------|
| `6c27d4c` | (see git log) |

### Status

[OK] **Completed**


## Session 12: Complete controlled Comfly output download policy

**Date**: 2026-08-04
**Task**: Complete controlled Comfly output download policy
**Branch**: `main`

### Summary

Added opt-in Comfly public CDN output downloads with HTTPS, DNS-publicity, SSRF, size, media, signature, and dimension checks. Updated Compose, settings, factory, tests, and backend quality guidance. Rebuilt all services; health, backend 350 tests, frontend 15 tests, Compose, doctor, Ruff, and mypy passed. Real Comfly generation remained external-provider/DNS blocked: slow upstream response and local Fake-IP resolution; no unvalidated image was stored.

### Git Commits

| Hash | Message |
|------|---------|
| `4963b9a` | (see git log) |

### Status

[OK] **Completed**
