# GLM-5V-Turbo live image-evaluation evidence — 2026-09-03

## Evidence identity

- Model: direct Zhipu `glm-5v-turbo`; no other model or gateway participated.
- Adapter: `image-panel-zhipu-glm-5v-turbo-one-shot-v3`.
- Dataset: 48 deterministic pairs from six independent source families; 36 objective recipe
  cases and 12 subjective unlabeled cases. These are not 48 independent real images.
- Plan: 48 AB/BA pairs plus 12 fixed AB/BA repeats, exactly 120 one-shot attempts.
- Human labels: 0. External labels: 0. Single-model only: true.
- Frozen report SHA-256: `cfff38107ecc84317efec4ec0e28d79ff8a560747c2df84eb50185611643473d`.
- Safe report file SHA-256: `2dddb2a4fb5c42c358e5197fa988dc5097f0b1c0e4a8383097777829cf4d459c`.
- Frozen non-activating artifact SHA-256:
  `68942fd5312c7c48eeb93d8c4d1e7aa2a5679478cacff3d930a34ee7dad01b1b`.
- Non-activating artifact file SHA-256:
  `1aff51befa07b606286da42d247c259c690c168bfeae72386b60a002e5d18667`.

The immutable evidence chain independently revalidated with these bindings:

| Artifact | File SHA-256 | Embedded logical SHA-256 |
|---|---|---|
| Manifest | `27715eeeacde91544effd40f79e10384ac1ca78308f1bc8669180779c7410309` | `c2b6b8e5750beb20ba7c41d5c3d47748533afc69f5c732b60d82351c28a9484b` |
| Authorization | `ad3381344d135872671a959c9145696a68bde0ba85c8bcd6ff4fd372e73a8f65` | `5c432c04af70f2d284c4e3eea2377b143b90743f1ba0f7a5e52620cbe1031384` |
| Pricing snapshot | `2a940b617430ea3afa7ba05e457b9d87dc776f42b2e0bd9096dc9dc1b4cbb0e0` | `d4e0e3b0e74f1c90b510a1f502d24036864dd4b95febb560e6d575f9a777f507` |
| Frozen requests | `326a776cce9895b4c415d2c333b81f02d1b8470b323023a556cab79efde1839c` | n/a |
| Attempt journal | `b8fd20472342fc71f55e09920335df2c5aca7cdc474b5249a278d9fde7747f6e` | hash-chained records |
| Terminal attempts | `49ef5c63551802ed588dd654f89d1b4f213339bf8b6c9abd4bf9399027b71ee7` | n/a |

The pricing-source record itself has SHA-256
`8846f0df83ecf424862a026150cc216f7e9469c988ca7672d196c0268312578e`.

## Execution

- 120 attempts observed: 119 completed and one terminal `failed/provider_rejected`; no retry or
  replacement.
- The failed attempt remains in every execution denominator and has unknown usage/cost.
- Known usage: 404,154 input tokens and 9,848 output tokens over 119 attempts.
- Known native cost: CNY 3.08512600; one failed attempt remains unknown rather than zero.
- Latency: P50 5,392.5 ms; P95 21,204.85 ms.
- Journal: 240 ordered records, one STARTED and one terminal per attempt.
- The CLI correctly returned incomplete/non-activating because 119/120, even though all planned
  provider boundaries were attempted.

## Objective recipe-gold results

All rates retain the full case/arm denominator; unresolved AB/BA pairs are not silently dropped.

- Overall pair accuracy: 29/36 = 80.56%; eligible order-consistent cases: 31/36.
- Arm decision macro-F1: 89.54%.
- Critical false-accept rate: 2/36 = 5.56%.
- Acceptable false-reject rate: 0/36 = 0%.
- Critical-flag false-negative rate: 7/36 = 19.44%; false-positive rate: 0/36.
- Holdout pair accuracy: 15/18 = 83.33%; arm macro-F1: 91.40%; critical FAR: 11.11%.

Per-dimension pair accuracy:

| Dimension | Accuracy | Important failure signal |
|---|---:|---|
| Semantic faithfulness | 100% | No observed objective miss |
| IP identity | 100% | No observed objective miss |
| OCR / visible text | 0% | 33.33% critical FAR; 100% critical-flag FN |
| Aesthetics / artifacts | 100% | No observed objective miss |
| Publication layout | 83.33% | One unresolved objective case |
| Batch diversity | 100% | Four-image capability and objective cases passed |

The high-value conclusion is not a single aggregate score: GLM-5V-Turbo was strong on five tested
dimensions but unsafe as a sole OCR/text-integrity gate on this six-family derived benchmark.

## Subjective unlabeled stability

These metrics are self-consistency only, not accuracy, proxy gold, model consensus, or human
agreement.

- AB/BA position stability: 12/12 = 100%; abstention rate: 0%.
- Fixed-repeat consistency: 11/12 = 91.67%.
- Holdout repeat consistency: 5/6 = 83.33%.

## Claim boundary

- `non_activating=true`, `selection_recommendation=false`, `enforce_eligible=false`.
- Production mode and model selection were not activated by this experiment.
- With only six independent source families, the report does not claim narrow confidence intervals
  or broad population generalization.
- A defensible engineering conclusion is to retain deterministic OCR and other hard validation
  alongside VLM auditing instead of using GLM-5V-Turbo as a standalone publication gate.
