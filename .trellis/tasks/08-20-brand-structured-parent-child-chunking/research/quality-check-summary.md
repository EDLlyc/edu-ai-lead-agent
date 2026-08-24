# Bounded quality context for structured brand chunking

Source of truth: `.trellis/spec/backend/quality-guidelines.md` (current working tree). This bounded
summary selects the checks relevant to this task; the reviewer may read the full source directly.

## Required gates

- Run Ruff format/lint and strict mypy for changed Python layers, then the focused parser/service/API
  tests and `make backend-check` before completion.
- API/Pydantic changes require deterministic production OpenAPI regeneration, generated frontend type
  regeneration, and drift checks. Do not hand-maintain a second wire type.
- SQLAlchemy/Alembic changes require the real PostgreSQL + pgvector integration path, not SQLite or
  `Base.metadata.create_all()` substitutes. Test clean upgrade, model/migration constraint parity,
  repository transactions, and the updated single Alembic head declarations.
- Run `git diff --check`, Compose/Doctor/release-contract checks affected by version/default/head changes,
  and a scoped secret/private-content scan. Quality checks must not create or source `.env`.
- Preserve unrelated dirty-worktree changes; inspect targeted diffs instead of resetting or rewriting
  user-owned files.

## Cross-layer review

- Brand knowledge and factual evidence stay separated in domain types, persistence and retrieval;
  every returned brand chunk remains `evidence_eligible=false`.
- Parser/chunk/input/retrieval versions are immutable and stored. Historical rows remain readable and
  null-safe; new semantic behavior receives new identities rather than reinterpreting old snapshots.
- Migrations and generated OpenAPI/frontend contracts move in the same change as their models/schemas.
- One typed projection owns section metadata for repository, application, HTTP, copy generation and
  Agent Workbench consumers.
- External calls remain outside database transactions; parent rows are flushed before child and
  embedding rows when no ORM relationship provides ordering.

## Privacy and negative cases

- Logs, errors, APIs and committed fixtures contain no private source body, filename/path, object key,
  embedding, prompt/provider body, credential or PII. Use IDs, hashes, counts and allowlisted metadata.
- Test malformed/encrypted/oversized files, empty pages, ambiguous Q&A, historical rows without a
  section, offset/FK mismatch, wrong provider/model and external-claim evidence rejection.
- Do not rely on mock-only persistence tests for constraints, migrations, pgvector ranking or
  transaction ordering.

## Final review questions

- Is the change in the correct domain/application/infrastructure/API layer?
- Do exact raw-text offsets, deterministic identities and parent/child provenance survive round-trip?
- Do retrieval filters and evidence separation remain unchanged?
- Are typed failures safe, bounded and terminal/retryable as intended?
- Are migration, API generation, tests and specs synchronized?
