# IP asset grounded retrieval Codex seed

> This report validates a Codex-authored 0-3 relevance seed over the real approved 41-image corpus. It is not human Gold, human agreement, a live-provider result, online user effectiveness, or business impact evidence.

- Maturity: `seed`
- Assets: 41
- Queries: 100 (80 dev / 20 holdout)
- Judgments: 4100
- Asset-set fingerprint: `9a40b9ea1afe28cfe98633a2fbcbfe696c34802ca37911a09d5e2da4eb0c2bb2`
- Query dataset SHA-256: `637a4f155beeae969353d6fb7fafb7a555e2bb695eebf91ef1c9cec6644e7e98`
- Seed dataset SHA-256: `8bf85e957b21658dbb2de28d6c735927605571170a1a05cccf61339a61715165`

## Query distribution

| Category | Queries | Mean usable assets (grade >= 2) |
| --- | ---: | ---: |
| `action` | 12 | 7.083 |
| `asset_type` | 8 | 19.250 |
| `character` | 10 | 14.900 |
| `combined_constraints` | 16 | 3.750 |
| `emotion` | 8 | 11.500 |
| `intended_use` | 10 | 12.600 |
| `no_answer` | 6 | 0.000 |
| `noisy_alias` | 4 | 20.500 |
| `paraphrase` | 6 | 11.000 |
| `scene` | 12 | 8.667 |
| `transparent_background` | 8 | 17.250 |

## Grade distribution

| Grade | Meaning | Judgments |
| ---: | --- | ---: |
| 0 | irrelevant or conflicting | 2881 |
| 1 | weak/local relevance | 163 |
| 2 | usable but incomplete | 407 |
| 3 | highly relevant / preferred | 649 |

The fixed query set includes `小赛和赛先生在空间站`. No-answer cases are retained for abstention/false-positive measurement and do not receive artificial perfect Recall/MRR values.
