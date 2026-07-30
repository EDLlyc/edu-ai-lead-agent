# Implementation Plan: Functional Brand Knowledge RAG

- [ ] Inspect supplied brand files and define minimal kinds/audience/validity/tags.
- [ ] Pin simple bounded PDF/DOCX/TXT/Markdown parsers and critical safety limits.
- [ ] Add document/version/chunk/embedding/job models and one Alembic migration.
- [ ] Add private MinIO original storage, deterministic parse/chunk, and `embedding-3` vectors.
- [ ] Add active parent-audience filtering and simple full-text/vector rank fusion.
- [ ] Add upload/status/list/activate/retrieval APIs and a minimal upload/status UI.
- [ ] Add focused parser/security/repository/retrieval tests and ingest real supplied documents.
- [ ] Demonstrate one brand retrieval for a selected topic; record quality limitations.
- [ ] Update specs, check, commit, and archive the child.

Deferred: OCR/large archives, exhaustive parser corpus, sophisticated reranking, ANN/index tuning,
advanced admin/version rollback UI, and production performance evaluation.
