# Implementation and check contracts

This file curates only the quality contracts relevant to the Layout-aware brand ingestion task. The broad
backend quality specification remains authoritative for unrelated features.

## Layer and version contracts

- Domain/application types remain independent of FastAPI, SQLAlchemy and provider SDK objects.
- Decode the raw Zhipu envelope once at the infrastructure boundary; application/parser code receives only
  typed provider-neutral page/block values.
- Parser, chunk and embedding-input identities are executable bundles. Add one complete v4 bundle, freeze
  v2/v3 outputs, and reject unknown or mixed identities before a durable upload/job is created.
- Keep brand data distinct from factual evidence and visual-asset vectors. Every returned brand hit remains
  `evidence_eligible=false`.
- Do not add an Alembic revision, JSONB metadata or public API field for ephemeral bbox/block hints. If an
  implementation discovers a durable consumer that makes schema change necessary, stop and revise the PRD.

## Provider and transaction contracts

- Preserve request/response/page/element/character/time/concurrency/retry bounds and exact provider/model
  checks. Raw response dictionaries, SDK models and exception strings do not cross the adapter.
- Provider authentication/rate-limit/timeout/unavailable/rejected/invalid-output failures use the existing
  typed hierarchy. Contract/layout violations are terminal and expose only allowlisted issue codes.
- OCR and embedding network calls occur outside database transactions. Claim/heartbeat, result persistence
  and activation use short transactions and existing lease ownership.
- The controlled private-corpus rebuild occurs only after deterministic/provider-contract/real-database checks
  pass. Failed v4 work must not modify the old active version.

## Required test matrix

### Unit and contract

- PDF page-quality positive/negative boundaries, including the exact sparse/slide ratio edges.
- Multi-page layout envelope; unit and pixel bbox; optional page/element dimensions; empty/image-only pages;
  text/table/formula/image labels; duplicate/invalid index; unknown label; malformed/mixed/out-of-range bbox;
  page-count/source conflicts; element/document limits.
- Image element content, response sentinel, Markdown/body, Base64 and credential never appear in result,
  exception `str`/`repr`, captured log, durable safe metadata or API fixture.
- Canonical page/block/child exact slices, repeated-run IDs/hashes/ordinals, page-local overlap and hard cap.
- Spatial card grouping positive and ambiguous/unaligned negative.
- Frozen v2/v3 PDF/OCR behavior and unchanged DOCX Q&A/table order.

### Application and real PostgreSQL/pgvector

- v4 OCR handoff yields page sections; provider identity mismatch and invalid layout fail safely.
- v3/v4 immutable versions coexist; failed/processing versions cannot activate; ready activation is atomic;
  old ready version can be restored.
- Existing audience/validity/kind/provider/model filters, parent diversity and brand/evidence separation remain.
- `Base.metadata`, Alembic unique head and migration tests show no schema drift even though no revision is added.

### Evaluation and private local acceptance

- `make brand-retrieval-eval` remains canonical and provider-free. Layout-sensitive fixtures use the shared
  production RRF/selector, independent relevance oracle and existing Recall@5/nDCG@5/safety gates.
- Real private material validation records only aggregate counts, IDs/hashes and states. It must not write
  source text, paths, object keys, layout contents/bbox, queries, hits, provider responses or vectors to task
  files, tests, logs or Git.
- Two scoped PDFs may be rebuilt locally only; no server, news/business worker, delivery or publishing action.

## Validation order

1. Run the smallest affected unit and provider-contract tests during editing.
2. Run focused Ruff and strict mypy on changed backend modules.
3. Run affected application and real PostgreSQL/pgvector integration tests.
4. Run `make brand-retrieval-eval` and privacy/sentinel scans.
5. Complete an independent Trellis check and resolve findings.
6. Only then run the controlled local provider/re-index acceptance.
7. After the last production edit and local acceptance, run `make backend-check` once, followed by
   `git diff --check` and an owned-path/credential/private-data review.

Do not repeatedly run the full suite during each edit. Do not use SQLite/mock-only evidence for database
activation, pgvector filtering or version coexistence.

## Completion and commit boundary

- Update the brand spec with the real v4 identities, routing thresholds, layout projection and failure matrix.
- Keep task evidence aggregate-only and distinguish provider-free fixture metrics from private-corpus smoke.
- Inspect live diffs of every shared file before staging. A local commit may contain only task-owned hunks;
  if unrelated dirty hunks cannot be separated safely, report the blocker instead of committing them.
- Do not push, SSH, deploy, publish or run normal business workflows.
