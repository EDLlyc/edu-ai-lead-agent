# Official-account Reviewer provider-free contract report

> This provider-free, hand-authored fixture track measures closed-schema, input-binding, hard-gate, repair-policy, and metric-pipeline conformance. It does not measure live Reviewer accuracy, human agreement, production uplift, model quality, or online safety effectiveness.

## Evidence identity

- Provider-free: `true`
- Live model calls: `0`
- Dataset: `official-account-review-eval-dataset-v1` / `ad3f8b8c6937d5d70f57d36e3809e9e6cb5ed33749cf83e328b34e534113a0c8`
- Oracle SHA-256: `b8b0aca86944d2bff52cbfdc15b1ec84a9a252ebbb4fc713dbd97c6a213dba5a`
- Rubric: `official-account-editorial-rubric-v1` / `255b4beb44a0a13c531c5f5a981acdc9ca5291ca021326614b764e0664d834ed`
- Fixture policy: `official-account-review-fixture-policy-v1` / `78d6a41861cd2df892ea494fe936c51d88cab360d7ac849b81e198db574b69d0`
- Evaluator bundle SHA-256: `41f5c9718eeb42b7b4f2dcbc176674e3b6c43a9be435850a517bb134efc9ab9e`

## Aggregate contract metrics

- Passing cases: `48/48`
- Hard-gate critical contract precision / recall / F1: `100.00%` / `100.00%` / `100.00%`
- False accept count / rate: `0` / `0.00%`
- False reject count / rate: `0` / `0.00%`
- Manual review rate: `14.58%`
- Unavailable rate: `25.00%`
- Repairability accuracy: `100.00%`
- Exact issue-location accuracy: `100.00%`
- Hard-gate override violations: `0`

## Dimension coverage

| Dimension | Cases | Defect-case P/R/F1 | Failed cases |
| --- | ---: | ---: | --- |
| `factual_grounding` | 8 | 100.00% / 100.00% / 100.00% | — |
| `brand_tone` | 8 | 100.00% / 100.00% / 100.00% | — |
| `structure_readability` | 8 | 100.00% / 100.00% / 100.00% | — |
| `privacy_safety` | 8 | 100.00% / 100.00% / 100.00% | — |
| `instruction_boundary` | 8 | 100.00% / 100.00% / 100.00% | — |
| `marketing_integrity` | 8 | 100.00% / 100.00% / 100.00% | — |

## Failure cases

| Case | Expected / actual | Failure codes |
| --- | --- | --- |
| — | All fixture contracts matched | — |

Case inputs and evaluator oracle labels are stored in separate files. The frozen policy receives only case-side typed observations and never receives expected labels.
