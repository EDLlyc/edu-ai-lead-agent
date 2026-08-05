# Implementation Plan: Functional-First Content Production MVP

## Delivery Mode

Complete a runnable business vertical slice in 4--5 working days. Keep stable ports, schemas,
migrations, versions, feature flags, and repository/provider boundaries, but postpone exhaustive
hardening and tuning until the user has reviewed the functioning product.

Non-deferrable basics: no secret leakage, stored-evidence factual bindings, brand/evidence
separation, bounded uploads/provider calls, one daily topic/no-topic business key, one repair, one
idempotent image/package, and no automatic publishing.

## Day 1 — Topic Selection Preview

- [ ] Add transparent `scoring-v1-preview` vetoes, normalized factors, weights, threshold, rank, and
      seven-day repetition rule over current governed events.
- [ ] Persist a minimal versioned daily run, score rows, and one selected event/no-topic result.
- [ ] Add manual/daily trigger plus score/result API.
- [ ] Run focused domain/repository/API tests and one real event-pool demonstration.

The preview config is visible and replaceable. Large labeled tuning and formal default approval
remain the first hardening item after the user sees actual rankings.

## Day 2 — Brand Upload and RAG

- [ ] Add private brand upload for bounded PDF/DOCX/TXT/Markdown, document versions, chunks, and
      `embedding-3` vectors.
- [ ] Add active parent-audience filtering and simple PostgreSQL full-text + pgvector rank fusion.
- [ ] Add upload/status/retrieval APIs and a minimal internal upload/status view.
- [ ] Ingest supplied brand files and demonstrate one relevant retrieval result.

Advanced parser/OCR archives, sophisticated reranking, and performance tuning are deferred.

## Day 3 — Draft, Audit, and One Repair

- [ ] Add typed draft/claim/audit schemas and generator/auditor ports with fakes/live adapters.
- [ ] Bind external facts to governance evidence and brand statements to brand chunks.
- [ ] Add critical deterministic validation, brand/risk audit, and exactly one repair.
- [ ] Persist minimal run/draft/claim/binding/audit lineage and expose status/detail API.
- [ ] Demonstrate one real selected topic through accepted draft or visible reviewable failure.

Exhaustive prompt/chaos/provider matrices are deferred; evidence IDs, secrets, unsafe output, and
no-publish boundaries are not.

## Day 4 — Image, Package, and Internal Page

- [ ] Add image port/fake/live adapter after a short compatibility probe.
- [ ] Generate/store one image in MinIO with a request fingerprint and safe metadata.
- [ ] Assemble one versioned material package with topic, score, copy, image, sources, and audit.
- [ ] Build the internal daily/package page with review, copy, source links, and image download.
- [ ] Cover ready, no-topic, and failed states; prove no publish action exists.

Multiple images, editing, advanced approval, and production access control are deferred.

## Day 5 — Connect and Demonstrate

- [ ] Run acquisition/governance output through selection -> brand RAG -> draft/audit/repair ->
      image -> package -> UI.
- [ ] Fix integration defects only; avoid unrelated tuning or deployment expansion.
- [ ] Run focused critical tests plus the existing backend/frontend/Doctor/Compose/diff gates once.
- [ ] Record the demo inputs/results, known limitations, upgrade/hardening backlog, and operator
      commands.
- [ ] Commit/archive children and parent in Trellis order.

## Required External Inputs

- Brand documents by Day 2.
- Approved examples/length rules by Day 3 if absent from the corpus.
- Visual/logo rules and compatible image permission by Day 4.

## Follow-up Hardening Backlog

- Tune/approve the production scoring config on a larger labeled real set.
- Expand parser robustness, retrieval evaluation/reranking, indexes, and scale measurements.
- Add exhaustive crash/restart/concurrency/lease/idempotency matrices across all new stages.
- Add production authentication, monitoring, backup/retention, secret manager, cost dashboards, and
  deployment automation.
- Add richer editing/approval/multi-variant features only after user feedback.
