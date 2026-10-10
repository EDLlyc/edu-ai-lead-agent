# Backend quality contract excerpt

Source: `.trellis/spec/backend/quality-guidelines.md`, opening sections. Full specification remains authoritative; this excerpt avoids context injection truncation.

# Backend Quality Guidelines

## Contract status

These are the implemented quality gates for Python 3.11/FastAPI and the generated frontend API
contract. Local commands and tests live in the paths linked below. CI remains a required follow-up
when continuous integration is introduced.

## Required engineering patterns

- Use Pydantic v2 at HTTP, settings, and structured model-output boundaries.
- Type public functions and application/port interfaces; run a strict static type checker.
- Keep domain/application code independent of FastAPI, SQLAlchemy, and provider SDKs.
- Inject clocks, ID generators, repositories, and external adapters where deterministic tests need
  control; do not monkeypatch global time or clients by default.
- Version prompts, scoring configurations, parsers, embeddings, models, and policy rules.
- Make every stage input/output serializable and persist enough provenance to reproduce a verdict.
- Use UTC-aware instants and explicit business dates/timezones.
- Generate the OpenAPI schema deterministically for the frontend contract.

The implemented commands are owned by [`backend/pyproject.toml`](../../../backend/pyproject.toml)
and wrapped by the root [`Makefile`](../../../Makefile): `make backend-check` runs Ruff format
checking, Ruff lint, strict mypy across application and backend tooling scripts, and pytest with
coverage. Changing tools is acceptable only if the same gates remain and the task documents the
decision.


Task-specific checks: no real provider calls/publication; generated API parity; PostgreSQL migration/constraint tests; actual browser deep-route and mocked recovery checks.
