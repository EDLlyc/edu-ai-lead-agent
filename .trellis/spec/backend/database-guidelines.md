# Database Guidelines

## Persistence contract

Use PostgreSQL with pgvector, SQLAlchemy 2 async mappings, `asyncpg`, and Alembic. The implemented
acquisition, factual-governance, material-package, and Enterprise WeChat delivery schema is defined in
[`models.py`](../../../backend/app/infrastructure/db/models.py), accessed through
the acquisition and governance repositories under
[`infrastructure/db`](../../../backend/app/infrastructure/db), and migrated by
[`backend/alembic/versions`](../../../backend/alembic/versions). The current unique head is
`20260805_0018`. PostgreSQL/pgvector/MinIO integration tests, not SQLite or `create_all()`, are the
executable persistence contract.

The database is the durable source of truth for pipeline runs, jobs, source snapshots, evidence,
brand knowledge, generation artifacts, and material packages. Never rely on scheduler memory for
whether a daily job ran.

## Data-domain separation

Use distinct models, repositories, and foreign-key paths for:

- **Evidence data:** sources, immutable source snapshots, evidence candidates and occurrences,
  normalized articles/passages, factual analyses, purpose-specific embeddings, duplicate
  relations, event clusters/versions/memberships, assignment decisions, and relational evidence
  bindings.
- **Brand data:** versioned brand documents/chunks, audience and validity metadata, safety rules,
  approved examples, and visual guidance.

Both domains may have vector columns, but a brand chunk cannot satisfy a factual claim's evidence
foreign key. Prefer database constraints over convention alone where possible.

Implemented evidence, topic-selection, brand-knowledge, material-package, and delivery tables follow
the exact model/migration names. The detailed governance table, uniqueness,
checkpoint, vector, and event-version contracts are in
[`governance-event-organization.md`](./governance-event-organization.md). The
config/run/job/score/daily-lock schema, immutable same-day revisions, and event/version composite
constraints are in
[`topic-selection.md`](./topic-selection.md). Brand document/version/job/chunk/vector constraints
are in [`brand-knowledge-rag.md`](./brand-knowledge-rag.md).

## SQLAlchemy 2 async pattern

Use typed declarative mappings (`Mapped[...]`, `mapped_column`) and `select()` statements. Inject
`AsyncSession` or a repository into the use case. Do not use legacy `Query`, implicit global
sessions, or lazy-loading that performs hidden async I/O.

```python
class PipelineRunModel(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    schedule_date: Mapped[date]
    timezone: Mapped[str]
    pipeline_version: Mapped[str]
    status: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "schedule_date", "timezone", "pipeline_version",
            name="uq_pipeline_runs_schedule_business_key",
        ),
    )
```

Load relationships explicitly with `selectinload` when needed. Select only required columns for
list endpoints. Avoid per-row queries and bound batch sizes for embeddings and bulk inserts.

## Transactions and external calls

- The application service owns transaction boundaries.
- Keep transactions short and never hold one open across web scraping, LLM, embedding, reranking,
  image generation, or object-storage network calls.
- Use a short transaction to claim a job, perform the external call outside it, and use another
  transaction to persist the fingerprint/result and transition state.
- For competing workers, use `SELECT ... FOR UPDATE SKIP LOCKED`, a lease/heartbeat, or an
  equivalent tested claim mechanism.
- Use a unique idempotency key and upsert/conflict handling for scheduled runs and stage artifacts;
  do not implement check-then-insert races in Python.

Acquisition source leases also own a durable `next_request_at` pacing watermark. Every list or
detail request reserves a slot in a short transaction before sleeping, and releasing the lease
expires ownership without deleting that watermark. This keeps the configured inter-request limit
effective across retries, worker restarts, and separate jobs for the same source.

Retries must not duplicate external side effects. Persist the request fingerprint, provider
request ID when available, prompt/model version, attempt number, and artifact status.

## Time, identifiers, and naming

- Use UUIDs for externally exposed and distributed entity identifiers unless a measured reason
  justifies another choice.
- Use `snake_case`, plural table names, and singular Python model names.
- Store instants as timezone-aware `TIMESTAMPTZ` values in UTC.
- Store the business schedule date and IANA timezone separately; the product default is
  `Asia/Shanghai`, not a hard-coded UTC offset.
- Name constraints and indexes explicitly: `pk_<table>`, `fk_<table>_<column>`,
  `uq_<table>_<purpose>`, and `ix_<table>_<purpose>`.
- Use database enums only when migration cost is accepted. Otherwise use validated text plus a
  check constraint and a domain enum.

## Snapshots, provenance, and auditability

Preserve the raw or canonical source snapshot before normalization, subject to lawful storage
and retention. Record source URL, canonical URL, publication/fetch times, content SHA-256, parser
version, normalization version, source tier, and extraction metadata. A duplicate record points
to the retained article/event; deduplication must not erase provenance.

Every score stores feature values, weights, penalties, total, threshold, rule/model version,
eligibility, and veto reasons. Every generated artifact stores prompt version, model/provider,
input artifact references, and validation/audit verdicts.

Claims and evidence are relational records, not just a prose `source_note`. A binding records the
claim ID, evidence passage/snapshot ID, exact quote or offsets, URL, source tier, and retrieval
time. Enforce that accepted core claims have at least one eligible binding in application logic
and test it at the database/service boundary.

## Vector and full-text search

- Keep embedding provider, model, dimension, and normalization version with each vectorized row.
- Configure vector dimensions in one place and encode changes through migrations/re-index jobs.
- Add HNSW or IVFFlat indexes only after representative data and query measurements exist.
- Apply metadata filters (audience, validity, source eligibility) before or alongside retrieval.
- PostgreSQL `tsvector`/`ts_rank` is full-text ranking, not BM25. Do not label it BM25.
- If exact BM25 is required, document and migrate a PostgreSQL extension such as `pg_search`, or
  select a search service through an explicit architecture decision.
- Fuse keyword and vector results with a documented, testable algorithm such as reciprocal rank
  fusion, then rerank a bounded candidate set.

Evidence and brand retrieval use separate queries and return separately typed results.

## Alembic migrations

- Every schema change is an Alembic revision reviewed with its generated SQL.
- Never call `Base.metadata.create_all()` in production startup.
- Keep migrations deterministic; do not call application services or external APIs from them.
- Split large backfills from blocking schema changes and make deployment order explicit.
- Test upgrade from a clean database to `head`; for risky changes, test the previous release to
  `head` and document downgrade limitations.
- Enable PostgreSQL extensions, including `vector`, through a migration or documented provisioning
  step with a corresponding integration check.

## Scenario: Versioned acquisition relevance migration

### 1. Scope / Trigger

Use this contract whenever source parsing, relevance policy, candidate provenance, or run/job
counters change. Historical source versions, candidates, observations, and MinIO snapshots are
audit records and must not be rewritten in place.

### 2. Signatures

- Upgrade: `alembic -c backend/alembic.ini upgrade head`.
- Acquisition relevance revision: `20260729_0003` in
  [`20260729_0003_title_relevance_handoff.py`](../../../backend/alembic/versions/20260729_0003_title_relevance_handoff.py).
- Factual-governance foundation revision: `20260729_0004`; the current repository head is
  `20260805_0018` (adds reviewed material-package delivery jobs and attempts after source-scoped
  HTTP fallback and topic-priority metadata, immutable
  ordered visual-reference rows and image visual-brief metadata, brand-document OCR metadata,
  source request pacing, freshness policy metadata, and immutable
  same-day topic revisions).
  Acquisition-specific downgrade tests still isolate the `0003 -> 0002` contract described here.
- Source contract: `source_versions.relevance_rule_version VARCHAR(40) NULL`.
- Candidate contract: `evidence_candidates.relevance_rule_version VARCHAR(40) NULL`.
- Counters: `acquisition_runs.filtered_count` and `acquisition_jobs.filtered_count`, non-null and
  defaulting to zero.

### 3. Contracts

- Legacy rows keep `relevance_rule_version=NULL`; seeding creates a new immutable active version
  with `ai-title-v1` for each of the eight existing sources and `moe-science-v1` for the Ministry
  source.
- Retry-scheduled attempts do not persist or accumulate a filtered count. The terminal scan value
  becomes the job count; the run count is the sum of terminal job counts.
- A downgrade from `0003` first repoints every active relevance-enabled source to its highest
  legacy NULL-rule version. If none exists, `sources.active_version_id` becomes NULL before the
  relevance columns are dropped.
- Downgrade never deletes source versions, candidates, observations, or snapshot objects.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Existing legacy database upgrades to `0003` | Existing rows remain queryable; counters are zero; rule fields are NULL |
| Source seed runs after upgrade | Exactly one fingerprinted active rule version per source; history retained |
| Attempt schedules a retry after scanning | `filtered_count` is not added to job/run totals |
| Terminal retry succeeds | Final scan count is stored once and aggregated once |
| Downgrade has a legacy source version | Activate the newest legacy version before dropping columns |
| Downgrade has no legacy source version | Set active version NULL; never point an old worker at an unfiltered new version |

### 5. Good / Base / Bad Cases

- Good: upgrade, seed, run, downgrade, and re-upgrade preserve all audit rows and valid active-version
  ownership.
- Base: a source with no relevant item stores zero candidates and a positive filtered count.
- Bad: mutate the old source version, sum filtered counts with `+=` across retries, or drop the rule
  column while a rule-enabled version remains active.

### 6. Tests Required

- [`test_migrations.py`](../../../backend/tests/integration/test_migrations.py) runs clean upgrade
  and an independent temporary-database `0003 -> 0002` downgrade assertion.
- [`test_title_relevance_ingestion.py`](../../../backend/tests/integration/test_title_relevance_ingestion.py)
  asserts mixed-list filtering, zero-match cursor advancement, retry count behavior, source-version
  preservation, and stored candidate handoff against real PostgreSQL/MinIO.
- Assert no negative counters, no active-version/source ownership mismatch, and no terminal row
  without `completed_at` in operational verification.
- **Head-revision assertion sync**: every new Alembic revision bumps the repository head, so the
  hard-coded `revision == "<head>"` assertions in
  [`test_migrations.py`](../../../backend/tests/integration/test_migrations.py),
  [`test_governance_migrations.py`](../../../backend/tests/integration/test_governance_migrations.py),
  and
  [`test_governance_migration_downgrade.py`](../../../backend/tests/integration/test_governance_migration_downgrade.py)
  must be updated to the new head in the same commit. The downgrade test asserts the revision
  *after* a refused downgrade equals the current head, not a stale governance-only revision.

### 7. Wrong vs Correct

#### Wrong

```python
job.filtered_count += attempt_filtered_count
```

#### Correct

```python
# Retry attempts remain non-terminal and do not publish scan totals.
job.filtered_count = terminal_filtered_count
```

Publish one terminal value and derive the run aggregate from terminal jobs.

## Avoid

- Storing evidence and brand chunks in an unlabeled shared collection.
- Treating JSONB as a substitute for core foreign keys, state, and claim bindings.
- Deleting source history when a page changes.
- Comparing naive and aware datetimes.
- Writing raw SQL in routes or pipeline prompts.
- Unit tests with SQLite for PostgreSQL/pgvector behavior; use a real ephemeral PostgreSQL service.
