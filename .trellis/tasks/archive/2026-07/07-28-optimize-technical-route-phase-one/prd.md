# Optimize the Technical Report and First Delivery Step

## Goal

Revise `main.tex` into a clearer, technically accurate, visually polished v0.3 report whose
implementation route starts with authoritative-source automated acquisition. Remove the P0/P1
milestone vocabulary and organize delivery by concrete capability steps instead.

## Background and Confirmed Facts

- `main.tex` is the editable XeLaTeX source for the current five-page v0.2 report.
- The existing roadmap starts with a disposable P0 generation demo and places acquisition in P1.
- The user explicitly rejected that order: authoritative-source automated acquisition is the
  first step, and P0/P1-style labels must not be used going forward.
- The current report already presents authoritative-source acquisition as the first box in the
  logical workflow, so the delivery route should align with that architecture.
- The repository has a working Python 3.11/FastAPI, PostgreSQL/pgvector, MinIO, and React/Vite
  development environment, but no product pipeline has been implemented.
- The original `技术报告.pdf` must be preserved as the v0.2 reference.

## Requirements

### R1 — Capability-based delivery route

- Remove all P0, P1, P2, P3, and P4 milestone labels and the disposable manual-input demo.
- Replace them with ordered, semantically named construction steps.
- Make “权威源自动采集与证据入库” the first delivery step.
- Describe each step through its objective, deliverables, boundary, and observable completion
  condition rather than an abstract maturity label.

### R2 — Authoritative source governance

- Define a source registry covering source identity, trust tier, organization type, allowed
  domains, acquisition method, cadence, enabled state, and ownership.
- Treat government/education authorities, schools/universities/research organizations,
  international organizations, and first-party company releases as eligible primary evidence.
- Treat reputable media as discovery/context unless linked back to an eligible primary source.
- Treat social platforms as lead-only sources that cannot directly support final factual claims.

### R3 — Safe automated acquisition contract

- Prefer RSS and documented public APIs; use allowlisted HTML extraction only as a fallback.
- Use a separate scheduler process to create durable acquisition runs instead of relying on API
  process memory.
- Specify timeouts, bounded retries, per-source rate limits, content-type and byte limits, redirect
  limits, robots/terms review, and outbound-network/SSRF protections.
- Support incremental acquisition using publication windows, stable source IDs, and HTTP cache
  metadata such as ETag/Last-Modified when available.

### R4 — Immutable provenance and idempotency

- Preserve the fetched source snapshot before normalization and record canonical URL, source ID,
  publication/fetch times, content hash, parser/normalization version, and acquisition run ID.
- Make repeated collection idempotent and retain duplicate provenance rather than silently
  discarding source history.
- Keep model-generated summaries and semantic classification outside the raw acquisition boundary.

### R5 — Clear first-step output and acceptance

- Define the output as a queryable, auditable evidence candidate pool ready for cleaning,
  deduplication, clustering, and later selection.
- Include per-source success/failure, freshness, new-document count, parse success, duplicate rate,
  latency, and retry metrics.
- Define representative official sources and failure cases for acceptance without claiming that
  live collectors already exist.

### R6 — Coherent downstream route

- Follow acquisition with data governance, topic eligibility/scoring, brand knowledge retrieval,
  evidence-bound generation and validation, then visual/material-package delivery.
- Preserve the hard boundary between evidence retrieval and brand-knowledge retrieval.
- Keep deterministic validation before LLM audit and image generation.
- Preserve manual copy/download and exclude automated social publishing.

### R7 — Technical accuracy

- Align the runtime baseline with Python 3.11, FastAPI/Pydantic v2, PostgreSQL/pgvector, MinIO,
  and React/TypeScript/Vite.
- Describe native PostgreSQL full-text ranking accurately; do not call it BM25 unless an explicit
  BM25 extension or service is selected.
- Describe API, scheduler, and workers as separate runtime responsibilities and durable database
  state as the source of truth.
- Strengthen structured generation with claim-to-evidence bindings rather than relying only on a
  prose `source_note`.

### R8 — Editorial and visual polish

- Update the document version to v0.3 and revise the executive summary to match the new order.
- Fix literal Markdown-style `**bold**` text and other wording/typography defects in the LaTeX.
- Improve the architecture figure, first-step callout, tables, spacing, and page balance while
  preserving a restrained, trustworthy blue/teal internal-technology aesthetic.
- Keep the report readable on A4, with no clipped tables, overlapping nodes, broken links, or
  avoidable mostly-empty final page.

### R9 — Deliverables

- Keep the editable report in `main.tex`.
- Compile and visually inspect a new v0.3 PDF without overwriting the original
  `技术报告.pdf` reference.
- Do not implement collectors, migrations, APIs, workers, or frontend product features in this
  documentation task.

## Acceptance Criteria

- [x] `main.tex` contains no P0/P1/P2/P3/P4 milestone labels.
- [x] The first construction step is authoritative-source automated acquisition and evidence
      ingestion, with explicit source, safety, provenance, idempotency, and acceptance contracts.
- [x] The downstream sequence is complete and does not reintroduce a generation-first demo.
- [x] Inaccurate BM25 wording, Python/runtime drift, weak source-note-only provenance, and literal
      Markdown emphasis are corrected.
- [x] The original `技术报告.pdf` remains unchanged.
- [x] XeLaTeX compiles the revised source without errors; warnings that affect layout are resolved.
- [x] The generated v0.3 PDF is visually inspected page by page and has no clipping, overlap, or
      major page-balance defect.
- [x] Report boundaries still exclude automatic social publishing and do not claim unimplemented
      product behavior already exists.

## Out of Scope

- Implementing or running real website collectors.
- Choosing production source credentials, legal approvals, or final source allowlists.
- Implementing the database schema, pipeline, model adapters, or material-package UI.
- Replacing the product's manual social publishing boundary.

## Blocking Open Questions

None. The user selected authoritative-source automated acquisition as the first step, rejected
P0/P1-style labels, and supplied the editable LaTeX source.
