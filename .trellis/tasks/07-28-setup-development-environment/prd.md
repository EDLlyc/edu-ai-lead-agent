# Configure Development Environment

## Goal

Provide a reproducible full-stack local development environment so a developer can clone the
private repository, install backend and frontend dependencies, start PostgreSQL/pgvector and
MinIO, and run quality checks without guessing versions, ports, commands, or secret handling.

## Background

- The repository is greenfield and currently contains architecture/spec documentation but no
  application source.
- The local machine is Ubuntu under WSL2 with Docker 29.1, Docker Compose 2.40, Node.js 20.20,
  npm 10.8, and a Conda environment named `edu-ai` running Python 3.11.15.
- `environment.yml` currently installs only Python 3.11 and pip.
- The architecture contract selects FastAPI/Pydantic, PostgreSQL with pgvector, React/TypeScript/
  Vite, and S3-compatible object storage. API, scheduler, and workers will be separate runtime
  processes, but their business behavior is not part of this task.
- The GitHub repository is `EDLlyc/edu-ai-lead-agent` and is private.

## Requirements

### R1 — Python and Conda

- Keep `edu-ai` as the documented Conda environment name and Python 3.11 as the interpreter.
- Keep Conda responsible for the interpreter and pip bootstrap; define application and development
  dependencies in `backend/pyproject.toml` so package metadata has one source of truth.
- Support an editable development install with a documented command.

### R2 — Backend toolchain

- Create a minimal installable backend package using FastAPI, Pydantic v2, SQLAlchemy 2 async,
  asyncpg, Alembic, pgvector, APScheduler, HTTP/ingestion libraries, retry/logging libraries, and
  typed settings required by the current architecture.
- Add development extras for Ruff, strict type checking, pytest, asyncio tests, and coverage.
- Add only a minimal runnable health shell needed to prove the environment works; do not implement
  ingestion, RAG, scoring, generation, or publishing behavior.

### R3 — Frontend toolchain

- Create a React + TypeScript strict + Vite application shell managed by npm and a committed
  `package-lock.json`.
- Include the initial server-state and API-contract tooling defined by the specs, plus lint,
  formatting, unit/component test, accessibility-test, and production-build commands.
- Do not implement the material-package product UI in this task.

### R4 — Local infrastructure

- Add Docker Compose services for PostgreSQL with pgvector and MinIO/S3-compatible storage.
- Persist data in named volumes, include health checks, and enable the `vector` extension through
  an idempotent initialization script.
- Use configurable host ports and do not require application containers for the first local setup.

### R5 — Configuration and secrets

- Add `.env.example` containing variable names and safe local placeholders only.
- Keep `.env` ignored. Do not commit provider API keys, database credentials used outside local
  development, tokens, signed URLs, or social-platform credentials.
- Use `Asia/Shanghai` as the documented business timezone while storing instants in UTC later.

### R6 — Developer workflow

- Add root documentation and commands for setup, infrastructure start/stop/status, backend checks,
  frontend checks, and an environment doctor/smoke check.
- Commands must be non-destructive by default; stopping infrastructure must not delete volumes.
- Document how to override ports when defaults conflict.

### R7 — Version control and privacy

- Keep GitHub visibility private.
- Ensure generated caches, local environments, `.env`, logs, coverage, frontend build output, and
  local object/database data are ignored.

## Acceptance Criteria

- [x] A fresh clone can create/activate `edu-ai` from `environment.yml` and install
      `backend[dev]` in editable mode using documented commands.
- [x] `npm ci --prefix frontend` succeeds from the committed lockfile.
- [x] `docker compose config` succeeds without exposing real secrets.
- [x] PostgreSQL/pgvector and MinIO start with healthy status, and the vector extension is present.
- [x] The minimal FastAPI health shell imports/starts and its automated test passes.
- [x] Backend formatting/lint, strict type check, and pytest commands pass.
- [x] Frontend formatting/lint, strict TypeScript check, unit test, and production build pass.
- [x] A single documented doctor/smoke command reports interpreter/tool versions and infrastructure
      readiness with actionable failures.
- [x] `.env` and generated artifacts remain untracked, and a repository scan finds no committed
      credentials or provider tokens.
- [x] No business pipeline, model call, automated publishing, or production deployment behavior is
      introduced.

## Out of Scope

- The ingestion, deduplication, scoring, RAG, audit, image-generation, and material-package flows.
- Production Docker images, cloud deployment, CI/CD, monitoring infrastructure, and backups.
- Production database schema/domain migrations beyond enabling pgvector and proving connectivity.
- Real company AI-platform credentials or API calls.
- Optimization or rewriting of `技术报告.pdf`; that will be handled by a later task.

## Blocking Open Questions

None. The user approved the full-stack local scope previously proposed: Conda/Python tooling,
backend and frontend toolchains, Docker Compose infrastructure, environment templates, developer
commands, and smoke validation.
