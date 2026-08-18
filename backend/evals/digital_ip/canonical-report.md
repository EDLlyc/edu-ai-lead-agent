# Digital IP fixture contract conformance

> This deterministic fixture report measures versioned projection contracts only; it is not a live embedding, retrieval, model-accuracy, or production-quality score.

- Dataset: `digital-ip-eval-case-v1:a30cf9dd04213df7`
- Cases passed: 5/5
- Expected document-type coverage: 100.00%
- Expected tag/character coverage: 100.00%
- Prohibited-rule hit rate: 100.00%
- Brand-as-fact violations: 0

| Case | Category | Pass | Type coverage | Tag coverage | Prohibited | Fact violations |
| --- | --- | --- | ---: | ---: | --- | ---: |
| `positioning-active-binding` | `positioning` | yes | 1/1 | 0/0 | n/a | 0 |
| `prohibited-language-hit` | `prohibited_language` | yes | 1/1 | 1/1 | hit | 0 |
| `safety-parent-boundary` | `safety` | yes | 1/1 | 2/2 | n/a | 0 |
| `tone-controlled-tags` | `tone` | yes | 1/1 | 3/3 | n/a | 0 |
| `visual-character-guidance` | `visual` | yes | 1/1 | 4/4 | n/a | 0 |

This checked artifact is a provider-free fixture baseline. It makes no claim about real embedding recall, live model consistency, or production effectiveness.
