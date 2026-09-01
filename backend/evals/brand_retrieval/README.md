# Brand text retrieval offline evaluation

This provider-free benchmark compares the frozen `brand-hybrid-rrf-v2-diverse` selector with the
current `brand-hybrid-rrf-v3-parent-diverse` selector on the same 36 sanitized, independently graded
candidate observations. It covers all nine brand content types and reports Recall@5, MRR@5,
nDCG@5, parent diversity, external-claim verification coverage, and brand-as-fact violations.

The fixture contains no private corpus text, paths, object keys, vectors, provider responses, or
credentials. The report measures deterministic RRF and selection-policy regression only. It must
not be described as live embedding recall, private-corpus quality, generation quality, or production
effectiveness.

Layout parsing is intentionally not folded into these ranking metrics: hand-authored FTS/vector
ranks would be a tautological proxy for parser quality. Sanitized parser/chunker contract tests
instead construct typed multi-page layout input and assert page IDs, card/table boundaries, and
exact source slices.

```bash
cd backend && python -m evals.brand_retrieval.runner --check
```

Canonical artifacts may be regenerated only after every gate passes:

```bash
cd backend && python -m evals.brand_retrieval.runner --write-canonical
```
