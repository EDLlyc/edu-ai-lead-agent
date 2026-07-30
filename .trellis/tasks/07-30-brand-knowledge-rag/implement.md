# Implementation Plan: Functional Brand Knowledge RAG

- [x] Inspect supplied brand files and define minimal kinds/audience/validity/tags.
- [x] Pin simple bounded PDF/DOCX/TXT/Markdown parsers and critical safety limits.
- [x] Add document/version/chunk/embedding/job models and one Alembic migration.
- [x] Add private MinIO original storage, deterministic parse/chunk, and `embedding-3` vectors.
- [x] Add active `parents` target-audience filtering and simple full-text/vector rank fusion.
- [x] Add upload/status/list/activate/retrieval APIs and a minimal upload/status UI with an internal
      generation-context debug entry, not a parent-facing search experience.
- [x] Add focused parser/security/repository/retrieval tests and ingest real supplied documents.
- [x] Demonstrate one brand-context retrieval for a selected topic as copy-generation input; record
      quality limitations.
- [ ] Update specs, check, commit, and archive the child.

Deferred: OCR/large archives, exhaustive parser corpus, sophisticated reranking, ANN/index tuning,
advanced admin/version rollback UI, and production performance evaluation.
