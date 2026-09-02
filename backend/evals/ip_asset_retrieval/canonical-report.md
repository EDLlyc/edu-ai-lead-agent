# IP asset retrieval deterministic baseline

> This provider-free report measures frozen, sanitized rank observations. It is not a live embedding, private-library, user-conversion, or production-effectiveness claim.

- Dataset: `ip-asset-retrieval-eval-case-v1:e9f43c05ebb1314e` (41 cases)
- Top K: 5

## Retrieval-policy comparison

| Metric | V2 direct blend | V3 weighted RRF |
| --- | ---: | ---: |
| Recall@5 | 83.90% | 92.20% |
| MRR@5 | 100.00% | 100.00% |
| nDCG@5 | 95.50% | 97.09% |
| Zero-result rate | 19.51% | 19.51% |

## Category breakdown

| Category | Cases | V2 R/M/N | V3 R/M/N |
| --- | ---: | --- | --- |
| `action` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `asset_type` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `character` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `combined_filters` | 6 | 0.833/1.000/0.956 | 0.933/1.000/0.975 |
| `emotion` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `intended_use` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `scene` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |
| `transparent_background` | 5 | 0.840/1.000/0.955 | 0.920/1.000/0.970 |

Graded relevance is used only after the production rank selector returns an order; it is never supplied to ranking.
