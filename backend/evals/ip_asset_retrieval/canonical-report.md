# IP asset retrieval deterministic baseline

> This provider-free report measures frozen, sanitized rank observations. It is not a live embedding, private-library, user-conversion, or production-effectiveness claim.

- Dataset: `ip-asset-retrieval-eval-case-v1:7d06b5d41ba98e54` (40 cases)
- Top K: 5

## Retrieval-policy comparison

| Metric | V2 direct blend | V3 weighted RRF |
| --- | ---: | ---: |
| Recall@5 | 84.00% | 92.00% |
| MRR@5 | 100.00% | 100.00% |
| nDCG@5 | 95.48% | 97.02% |
| Zero-result rate | 20.00% | 20.00% |

## Category breakdown

| Category | Cases | V2 R/M/N | V3 R/M/N |
| --- | ---: | --- | --- |
| `action` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `asset_type` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `character` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `combined_filters` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `emotion` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `intended_use` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `scene` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `transparent_background` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |

Graded relevance is used only after the production rank selector returns an order; it is never supplied to ranking.
