# Validation

## Automated gates

- Backend: 418 tests passed; Ruff format/lint and strict Mypy passed.
- Frontend: OpenAPI/type generation drift, Prettier, ESLint, strict TypeScript, 15 Vitest tests,
  and the production build passed.
- Infrastructure: Compose rendered, Alembic is at `20260804_0017`, and `make doctor` passed.
- Runtime: acquisition, governance, and content services were running with healthy PostgreSQL and
  MinIO containers.

## Scope boundary

- Ministry list/detail parsing is covered by deterministic fixtures and source-policy contracts.
- The optional live Ministry smoke was not made part of ordinary closure; a live parser or policy
  failure must remain a typed safe failure and must never broaden the crawl scope.
- No historical topic row was edited directly, and no social publishing path was added.
