# Brand text retrieval deterministic baseline

> This provider-free report measures deterministic RRF and diversity-policy behavior on sanitized fixture observations. It is not a live embedding recall, private-corpus quality, generation-quality, or production-effectiveness claim.

- Dataset: `brand-retrieval-eval-case-v1:04779a5ffbebe1f5` (36 cases)
- Top K: 5
- Passed: 36/36

## Retrieval-policy comparison

| Metric | Legacy v2 | Structured v3 |
| --- | ---: | ---: |
| Recall@5 | 80.00% | 95.00% |
| MRR@5 | 100.00% | 100.00% |
| nDCG@5 | 84.37% | 92.86% |
| Parent diversity@5 | 85.00% | 100.00% |
| External-claim verification | 100.00% | 100.00% |
| Brand-as-fact violations | 0 | 0 |

Parent-diversity delta: `+0.150000`.

## Case results

| Case | Category | Pass | v2 R/M/N/D | v3 R/M/N/D | Failures |
| --- | --- | --- | --- | --- | --- |
| `audience-insight-01` | `audience_insight` | yes | 0.800/1.000/0.887/0.800 | 1.000/1.000/1.000/1.000 | — |
| `audience-insight-02` | `audience_insight` | yes | 0.800/1.000/0.868/0.800 | 1.000/1.000/0.964/1.000 | — |
| `audience-insight-03` | `audience_insight` | yes | 0.800/1.000/0.731/0.800 | 1.000/1.000/0.863/1.000 | — |
| `audience-insight-04` | `audience_insight` | yes | 0.800/1.000/0.887/1.000 | 0.800/1.000/0.887/1.000 | — |
| `digital-ip-values-01` | `digital_ip_values` | yes | 0.800/1.000/0.887/0.800 | 1.000/1.000/1.000/1.000 | — |
| `digital-ip-values-02` | `digital_ip_values` | yes | 0.800/1.000/0.868/0.800 | 1.000/1.000/0.964/1.000 | — |
| `digital-ip-values-03` | `digital_ip_values` | yes | 0.800/1.000/0.731/0.800 | 1.000/1.000/0.863/1.000 | — |
| `digital-ip-values-04` | `digital_ip_values` | yes | 0.800/1.000/0.887/1.000 | 0.800/1.000/0.887/1.000 | — |
| `external-claim-01` | `external_claim` | yes | 0.800/1.000/0.887/0.800 | 1.000/1.000/1.000/1.000 | — |
| `external-claim-02` | `external_claim` | yes | 0.800/1.000/0.868/0.800 | 1.000/1.000/0.964/1.000 | — |
| `external-claim-03` | `external_claim` | yes | 0.800/1.000/0.731/0.800 | 1.000/1.000/0.863/1.000 | — |
| `external-claim-04` | `external_claim` | yes | 0.800/1.000/0.887/1.000 | 0.800/1.000/0.887/1.000 | — |
| `other-01` | `other` | yes | 0.800/1.000/0.887/0.800 | 1.000/1.000/1.000/1.000 | — |
| `other-02` | `other` | yes | 0.800/1.000/0.868/0.800 | 1.000/1.000/0.964/1.000 | — |
| `other-03` | `other` | yes | 0.800/1.000/0.731/0.800 | 1.000/1.000/0.863/1.000 | — |
| `other-04` | `other` | yes | 0.800/1.000/0.887/1.000 | 0.800/1.000/0.887/1.000 | — |
| `positioning-01` | `positioning` | yes | 0.800/1.000/0.887/0.800 | 1.000/1.000/1.000/1.000 | — |
| `positioning-02` | `positioning` | yes | 0.800/1.000/0.868/0.800 | 1.000/1.000/0.964/1.000 | — |
| `positioning-03` | `positioning` | yes | 0.800/1.000/0.731/0.800 | 1.000/1.000/0.863/1.000 | — |
| `positioning-04` | `positioning` | yes | 0.800/1.000/0.887/1.000 | 0.800/1.000/0.887/1.000 | — |
| `product-profile-01` | `product_profile` | yes | 0.800/1.000/0.887/0.800 | 1.000/1.000/1.000/1.000 | — |
| `product-profile-02` | `product_profile` | yes | 0.800/1.000/0.868/0.800 | 1.000/1.000/0.964/1.000 | — |
| `product-profile-03` | `product_profile` | yes | 0.800/1.000/0.731/0.800 | 1.000/1.000/0.863/1.000 | — |
| `product-profile-04` | `product_profile` | yes | 0.800/1.000/0.887/1.000 | 0.800/1.000/0.887/1.000 | — |
| `safety-capability-01` | `safety_capability` | yes | 0.800/1.000/0.887/0.800 | 1.000/1.000/1.000/1.000 | — |
| `safety-capability-02` | `safety_capability` | yes | 0.800/1.000/0.868/0.800 | 1.000/1.000/0.964/1.000 | — |
| `safety-capability-03` | `safety_capability` | yes | 0.800/1.000/0.731/0.800 | 1.000/1.000/0.863/1.000 | — |
| `safety-capability-04` | `safety_capability` | yes | 0.800/1.000/0.887/1.000 | 0.800/1.000/0.887/1.000 | — |
| `tone-example-01` | `tone_example` | yes | 0.800/1.000/0.887/0.800 | 1.000/1.000/1.000/1.000 | — |
| `tone-example-02` | `tone_example` | yes | 0.800/1.000/0.868/0.800 | 1.000/1.000/0.964/1.000 | — |
| `tone-example-03` | `tone_example` | yes | 0.800/1.000/0.731/0.800 | 1.000/1.000/0.863/1.000 | — |
| `tone-example-04` | `tone_example` | yes | 0.800/1.000/0.887/1.000 | 0.800/1.000/0.887/1.000 | — |
| `visual-guidance-01` | `visual_guidance` | yes | 0.800/1.000/0.887/0.800 | 1.000/1.000/1.000/1.000 | — |
| `visual-guidance-02` | `visual_guidance` | yes | 0.800/1.000/0.868/0.800 | 1.000/1.000/0.964/1.000 | — |
| `visual-guidance-03` | `visual_guidance` | yes | 0.800/1.000/0.731/0.800 | 1.000/1.000/0.863/1.000 | — |
| `visual-guidance-04` | `visual_guidance` | yes | 0.800/1.000/0.887/1.000 | 0.800/1.000/0.887/1.000 | — |

The evaluator ranks only from fixture FTS/vector observations. Graded relevance is held by the scorer and never supplied to RRF fusion or the production selector.
