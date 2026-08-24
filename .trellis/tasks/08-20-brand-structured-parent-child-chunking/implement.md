# Implementation Plan

1. [x] Add versioned section/content/claim enums and immutable parsed-section/chunk contracts, including
       exact offsets, external-claim implication and one shared canonical embedding-input builder.
2. [x] Refactor the bounded parser to preserve PDF pages, generate page-scoped children, traverse DOCX
       paragraphs/tables in document order, recognize interview Q&A, and keep generic/OCR fallbacks.
3. [x] Add the next Alembic revision plus SQLAlchemy models for `brand_sections` and structured chunk
       columns, with historical backfill and explicit FK/check/unique/index contracts.
4. [x] Extend ports, ingestion executor and repository persistence to embed `embedding_text`, bind its
       hash, persist sections before chunks before embeddings, and retain short transaction boundaries.
5. [x] Upgrade hybrid retrieval to use embedding/search text and parent-aware diversity while preserving
       all active/audience/validity/kind/provider/model filters and historical null-safe rows.
6. [x] Extend the shared `BrandRetrievalHit`, copy-generation context, Agent Workbench registry/fixtures,
       HTTP schemas/mappers and generated OpenAPI/frontend types with safe section metadata.
7. [x] Bump Settings, `.env.example`, Compose and Doctor to parser v3/chunk v3/input v2/retrieval v3;
       update brand/database/directory/error/logging/quality specs and migration head declarations.
8. [x] Add sanitized unit/contract fixtures and real-PostgreSQL/pgvector integration tests for PDF pages,
       DOCX Q&A/order, classifications, exact provenance, migration, ingestion, retrieval and compatibility.
9. [x] Run the bounded private-material offline validator and retain aggregate-only evidence; run Ruff,
       strict mypy, focused/full pytest, Alembic/API/Compose/Doctor/release gates, diff and privacy scans.
10. [x] Perform an independent Trellis quality review, fix verified findings, synchronize specs/result,
        and stop before any production, provider, re-ingestion, activation, deployment, commit or push.
11. [x] Add v3-only, per-parent budget-aware coalescing for pathological generic OCR Markdown blocks;
        preserve exact offsets, stable keys, maximum child size, the global 600 hard cap and frozen v2.
12. [x] Add sanitized >600-block, coverage/separator, stable replay, no-cross-parent, max-size and genuine
        hard-cap rejection regressions; run focused Ruff, strict mypy and brand/OCR/parser tests, then
        synchronize specs/result for independent review without making another provider call.
13. [x] After the independent review passed, execute the separately authorized post-fix OCR validation
        with exactly one HTTP attempt and no retry; retain aggregate-only page/parent/child, hard-cap,
        exact-slice, coverage, replay and protected-cleanup evidence without any persistence or downstream
        action.
14. [x] Extract the existing weighted RRF formula into one typed pure production helper without changing
        database filters, score semantics, tie-breaking, v2/v3 selection or HTTP projections.
15. [x] Add strict brand-retrieval eval models/loader/metrics/reporting plus 36 sanitized, category-balanced,
        independently graded cases covering all nine content types and parent-diversity boundaries.
16. [x] Run the same fused candidates through frozen retrieval v2 and current retrieval v3; gate Recall@5,
        MRR@5, nDCG@5, strict parent-diversity improvement, verification coverage and zero evidence leaks.
17. [x] Add metric math, malformed dataset, oracle-isolation, historical compatibility and canonical drift
        regressions; expose provider-free `make brand-retrieval-eval` and `--check` commands.
18. [x] Update the brand/quality/directory specs and task result, then run focused eval/unit tests, Ruff,
        strict mypy, `git diff --check` and privacy scans; use the final full backend gate only after focused
        review is green. Do not call a provider, private corpus, production or delivery path.

## Handoff status

- Items 1-8 are implemented, including the final compatibility review fixes: exact frozen v2/v3
  parser/chunker/input bundles, v2/v3 retrieval dispatch, mixed-bundle startup/upload rejection,
  version-scoped stale-lease recovery, conservative external-claim classification, and parent-first
  diversity.
- The post-fix focused unit/contract suite (166 tests), real PostgreSQL/pgvector suite (5 tests),
  Ruff, and strict mypy are green. The parent-owned final backend gate passed all 1176 tests, and the
  production/Agent API, release, Compose, task-context, diff and privacy/Qwen boundaries are closed.
- The controlled private-material check is complete with aggregate-only evidence: the two PDFs retained
  48/50 page counts, the DOCX exposed all 9 Q&A parents, and all locally produced children satisfied exact
  offsets. One sparse PDF correctly requires the existing OCR path.
- On 2026-08-21 an explicitly authorized OCR-only preflight resolved exactly one sparse 50-page input,
  confirmed Zhipu/`glm-ocr`, 100-page, 40 MiB request, 10 MiB response and 180-second limits, and found
  zero competing OCR processes. The configured three-attempt transport was overridden to one attempt.
- The controlled run made exactly one provider HTTP request and no retry. The existing adapter accepted
  the provider/model response, then v3 parent-local chunk validation failed closed with
  `brand_chunk_limit` because OCR Markdown yielded more than the configured 600 children. Raw temporary
  OCR output was held under mode-0700/0600 permissions, overwritten and deleted. Exact returned-page
  coverage and child-slice aggregates were not retained before the local rejection, so they are not
  asserted and no second provider call is authorized by this record.
- The local root cause is now fixed without a provider call. v3 preserves ordinary page/Q&A/card
  boundaries, but when a generic OCR parent would exceed the remaining hard-cap budget it coalesces
  adjacent tiny blocks within that parent, then uses continuous parent-local bounded splitting only if
  still needed. Frozen v2 is untouched. The focused brand/OCR suite, Ruff and strict mypy are green;
  independent review added continuous-fallback, scope-guard and worker-handoff regressions and left the
  code ready for the separately authorized one-call OCR validation.
- The post-fix validation then made exactly one additional authorized HTTP attempt and no retry.
  Zhipu/`glm-ocr` returned all 50 pages; the fixed v3 path produced one generic parent and 38 children,
  maximum 900 characters, under the unchanged 600 hard cap. Exact parent/child slices, parent-local
  binding, full non-whitespace coverage and same-text deterministic replay passed. The prior
  `brand_chunk_limit` is resolved, and the protected raw temporary artifact was overwritten and removed.
- The provider-free brand-text retrieval evaluation is complete: 36/36 balanced sanitized cases pass,
  the repository and evaluator share one public domain RRF/selector implementation, v3 improves
  Recall@5/nDCG@5/parent diversity without verification or evidence leaks, and the canonical report
  explicitly disclaims live embedding/private-corpus accuracy. Focused tests, Ruff, strict mypy and
  canonical drift checks are green. The final post-eval backend gate also passed Ruff, strict mypy
  over 177 source files, and all 1,225 backend tests at 82% coverage.

## Risky seams and rollback points

- `backend/app/infrastructure/brand/parser.py`: canonical text and offset changes can invalidate every
  downstream hash; freeze tests before persistence work.
- `backend/app/infrastructure/db/models.py` and the new Alembic revision: nullable historical section
  bindings and generated FTS replacement must match exactly in metadata and migration SQL.
- `backend/app/application/services/brand_knowledge.py`: external calls stay outside transactions and
  must use embedding input/hash rather than raw text/hash.
- `backend/app/infrastructure/db/brand_knowledge.py`: insert order, active-version/provider filters and
  parent-aware diversity must not weaken evidence separation or historical retrieval。
- `BrandRetrievalHit` is shared by HTTP, copy generation and Agent Workbench; all mappings and generated
  contracts move together.
- Rollback defaults to v2 and leaves immutable v3 data inactive/readable; no document/original deletion.

## Explicit boundaries

- No Qwen3-VL/multimodal integration, dimension migration or image/page-vector indexing. The only newly
  executed provider actions were the two separately authorized OCR gates recorded above: one pre-fix and
  one post-fix HTTP attempt, with zero retries in either gate. Neither gate performed embedding,
  persistence, activation or downstream work.
- No private source text or path in fixtures, task artifacts, logs, errors or public outputs.
- No local/production re-ingestion or activation of the three originals, business replay, SSH, deploy,
  Enterprise WeChat action, commit or push.
- Preserve all unrelated dirty-worktree changes, especially the current news-scoring task and reports.
