# Backend Quality Guidelines

## Contract status

These are initial quality gates for Python 3.11/FastAPI. The first implementation task must add
the actual commands to `backend/pyproject.toml` and CI, then update this guide with those paths and
trusted test examples.

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

The initial tool defaults are Ruff for formatting/linting, mypy or Pyright in strict mode for
type checking, and pytest with pytest-asyncio. Changing tools is acceptable only if the same gates
remain and the task documents the decision.

## Test pyramid and required scenarios

### Unit tests

Cover pure normalization, source-tier eligibility, exact/semantic duplicate decisions, feature
normalization, weighted scoring, threshold behavior, veto precedence, claim coverage, validation
codes, retry classification, state transitions, and redaction. Use fixed clocks and deterministic
fixtures.

### Integration tests

Run against real PostgreSQL with pgvector, not SQLite. Test migrations, repository transactions,
job claiming under contention, idempotent inserts, vector/full-text filtering, evidence/brand
separation, and object/provider adapters through local fakes or recorded contract fixtures that do
not contain secrets.

### API and contract tests

Test status codes, stable error envelopes, `202` enqueue semantics, material-package responses,
and OpenAPI generation. CI regenerates frontend API types and fails on drift.

### Pipeline acceptance tests

At minimum, prove:

- a Tier C lead cannot become final factual evidence;
- duplicate content retains provenance and a seven-day event repeat is vetoed;
- a below-threshold day ends as `no_topic` without model/image generation;
- every accepted core claim has an eligible evidence binding;
- deterministic validation runs before LLM audit;
- an LLM auditor cannot invent evidence or override a hard veto;
- retryable failures back off and resume without duplicate side effects;
- retry exhaustion produces a visible terminal state;
- package output supports manual use and exposes no publishing endpoint.

### Front-to-back flow

Maintain one end-to-end test for the first vertical slice: enqueue or provide a candidate, create a
typed draft with evidence bindings, validate/audit using controlled adapters, create an image
artifact, expose the package, and exercise the frontend copy/download/source-link flow.

## Security review

- Treat source content and model output as untrusted; delimit it as data and never promote embedded
  instructions to system/developer prompts.
- Apply network timeouts, response-size limits, content-type checks, and an outbound-source policy
  to ingestion to reduce SSRF and resource-exhaustion risk.
- Sanitize rendered content and object keys/filenames.
- Keep secrets in deployment configuration, never source, prompts, logs, or API responses.
- Avoid collecting personal data about minors; if encountered, quarantine/redact it according to
  policy before any model call.
- Do not add social-platform publishing credentials, endpoints, or background actions.

## Review checklist

- Is the change in the correct API/application/domain/infrastructure layer?
- Are evidence and brand knowledge still separated in types, storage, and retrieval?
- Are scoring weights, thresholds, vetoes, prompts, and model versions persisted?
- Are all core claims bound to eligible evidence passages?
- Are external side effects idempotent and transactions short?
- Are failures typed as expected, retryable, or terminal rather than swallowed?
- Are logs structured, correlated, and free of secrets/content/PII?
- Are migration and OpenAPI drift checks included where contracts changed?
- Do tests cover the negative/policy path, not only the happy path?
- Does the product still require a human to publish?

## Forbidden patterns

- Blocking I/O inside async handlers or workers without an explicit thread/process boundary.
- `time.sleep()` in async code, unbounded retries, or unbounded model/source concurrency.
- `except Exception: pass`, boolean-only audit verdicts, or untyped provider dictionaries crossing
  adapter boundaries.
- LLM-generated scoring with no stored feature values/rules version.
- Using a second LLM pass as the only fact check.
- Mock-only tests for PostgreSQL locking, pgvector, migrations, or idempotency.
- Merging the first vertical slice without updating these greenfield specs with real examples.
