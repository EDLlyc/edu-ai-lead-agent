# Current-State Audit for Authoritative-Source Ingestion

## Repository evidence

- `backend/app/api_main.py` contains only `/healthz`; no business routes or runtime entry points
  exist.
- `backend/app/core/config.py` validates application, database, MinIO, and AI platform settings but
  has no acquisition policy, scheduler, worker, or source configuration.
- `backend/pyproject.toml` already owns the main ingestion and persistence dependencies:
  SQLAlchemy async, asyncpg, Alembic, APScheduler, httpx, feedparser, trafilatura,
  BeautifulSoup, Tenacity, and structlog.
- No S3/MinIO client library is present. The design must either add one with an explicit async
  boundary or select another tested adapter; raw snapshots cannot be claimed as implemented by
  storing only URLs in PostgreSQL.
- `compose.yaml` provides healthy loopback-only PostgreSQL/pgvector and MinIO services plus an
  idempotent development bucket.
- There is no Alembic config/revision, ORM base/session, repository, scheduler, worker, source
  registry, run/job model, snapshot adapter, or ingestion test fixture.

## Controlling contracts

- `main.tex` and `技术报告-v0.3.pdf` make authoritative-source acquisition and evidence ingestion
  the first construction step.
- `.trellis/spec/backend/agent-pipeline.md` defines source tiers, untrusted-content handling,
  snapshots, provenance, typed stages, job idempotency, and the manual-publishing boundary.
- `.trellis/spec/backend/database-guidelines.md` requires real PostgreSQL integration tests,
  SQLAlchemy 2 async, Alembic, short transactions, named constraints, and object-storage snapshot
  references.
- `.trellis/spec/backend/error-handling.md` separates input/policy/validation/transient/terminal
  failures and permits retry only for explicitly transient faults.
- `.trellis/spec/backend/logging-guidelines.md` requires structured correlation and forbids full
  source bodies, credentials, signed URLs, and personal data in logs.

## Planning implications

- This is a complex cross-layer backend capability, not a single scraper function.
- A production-shaped first slice should exercise source registry, durable execution, safe
  connector policy, MinIO snapshot persistence, PostgreSQL provenance, API contracts, and real
  integration tests together.
- The full first capability may merit parent/child Trellis tasks after the initial source scope is
  selected, because persistence/runtime foundation, connectors/snapshot handling, and API plus
  acceptance verification are independently testable deliverables.
- The initial source allowlist is a product decision: broader source diversity validates adapter
  abstractions but increases connector and maintenance work; government-only sources reduce the
  first delivery risk but do not validate the full report coverage.
