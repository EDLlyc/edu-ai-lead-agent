# Image quality provider-free policy baseline

> This provider-free baseline measures strict schema, metric aggregation, and decision-policy conformance on sanitized hand-authored fixtures. It does not measure live model quality, human agreement, production effectiveness, or calibrated image-quality thresholds.

- Dataset: `image-quality-eval-dataset-v1` (48 cases)
- Dataset SHA-256: `4e575477d467662afab1d8c00bf68d503e7e782884cdcea34d5558bcf18e7435`
- Rubric: `image-quality-rubric-v1` (`d05fe7db0babdbee1533bbed2179daaa25f4ff2bb10352d49b2339efc0ca328f`)
- Decision policy: `image-quality-decision-policy-v1`
- Contract cases passed: 48/48

## Fixture distribution

| Fixture kind | Cases |
| --- | ---: |
| `positive` | 12 |
| `warning` | 6 |
| `borderline` | 6 |
| `hard_negative` | 18 |
| `unavailable` | 6 |

## Critical-defect policy metrics

| Metric | Result |
| --- | ---: |
| Critical precision | 100.00% |
| Critical recall | 100.00% |
| Critical F1 | 100.00% |
| False-pass rate | 0.00% (0/18) |
| Manual-review rate | 37.50% (18/48) |
| Unavailable rate | 12.50% (6/48) |

No aggregate image-quality score is produced: an aesthetic signal cannot offset a critical semantic, identity, text, crop, or duplicate failure.

## Per-dimension coverage and defect metrics

| Dimension | Cases | Coverage | Defect P/R/F1 | False pass | Manual review |
| --- | ---: | ---: | --- | ---: | ---: |
| `semantic_faithfulness` | 8 | 87.50% | 100.00% / 100.00% / 100.00% | 0.00% | 37.50% |
| `ip_identity` | 8 | 87.50% | 100.00% / 100.00% / 100.00% | 0.00% | 37.50% |
| `ocr_text` | 8 | 87.50% | 100.00% / 100.00% / 100.00% | 0.00% | 37.50% |
| `aesthetics_artifacts` | 8 | 87.50% | 100.00% / 100.00% / 100.00% | 0.00% | 37.50% |
| `publication_layout` | 8 | 87.50% | 100.00% / 100.00% / 100.00% | 0.00% | 37.50% |
| `batch_diversity` | 8 | 87.50% | 100.00% / 100.00% / 100.00% | 0.00% | 37.50% |

## Case diagnostics

| Case | Dimension | Fixture | Expected | Actual | Pass | Diagnostic |
| --- | --- | --- | --- | --- | --- | --- |
| `aesthetics-artifacts-borderline-01` | `aesthetics_artifacts` | `borderline` | `manual_review` | `manual_review` | yes | — |
| `aesthetics-artifacts-hard-negative-01` | `aesthetics_artifacts` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `aesthetics-artifacts-hard-negative-02` | `aesthetics_artifacts` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `aesthetics-artifacts-hard-negative-03` | `aesthetics_artifacts` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `aesthetics-artifacts-positive-01` | `aesthetics_artifacts` | `positive` | `accepted` | `accepted` | yes | — |
| `aesthetics-artifacts-positive-02` | `aesthetics_artifacts` | `positive` | `accepted` | `accepted` | yes | — |
| `aesthetics-artifacts-unavailable-01` | `aesthetics_artifacts` | `unavailable` | `unavailable` | `unavailable` | yes | — |
| `aesthetics-artifacts-warning-01` | `aesthetics_artifacts` | `warning` | `manual_review` | `manual_review` | yes | — |
| `batch-diversity-borderline-01` | `batch_diversity` | `borderline` | `manual_review` | `manual_review` | yes | — |
| `batch-diversity-hard-negative-01` | `batch_diversity` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `batch-diversity-hard-negative-02` | `batch_diversity` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `batch-diversity-hard-negative-03` | `batch_diversity` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `batch-diversity-positive-01` | `batch_diversity` | `positive` | `accepted` | `accepted` | yes | — |
| `batch-diversity-positive-02` | `batch_diversity` | `positive` | `accepted` | `accepted` | yes | — |
| `batch-diversity-unavailable-01` | `batch_diversity` | `unavailable` | `unavailable` | `unavailable` | yes | — |
| `batch-diversity-warning-01` | `batch_diversity` | `warning` | `manual_review` | `manual_review` | yes | — |
| `ip-identity-borderline-01` | `ip_identity` | `borderline` | `manual_review` | `manual_review` | yes | — |
| `ip-identity-hard-negative-01` | `ip_identity` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `ip-identity-hard-negative-02` | `ip_identity` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `ip-identity-hard-negative-03` | `ip_identity` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `ip-identity-positive-01` | `ip_identity` | `positive` | `accepted` | `accepted` | yes | — |
| `ip-identity-positive-02` | `ip_identity` | `positive` | `accepted` | `accepted` | yes | — |
| `ip-identity-unavailable-01` | `ip_identity` | `unavailable` | `unavailable` | `unavailable` | yes | — |
| `ip-identity-warning-01` | `ip_identity` | `warning` | `manual_review` | `manual_review` | yes | — |
| `ocr-text-borderline-01` | `ocr_text` | `borderline` | `manual_review` | `manual_review` | yes | — |
| `ocr-text-hard-negative-01` | `ocr_text` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `ocr-text-hard-negative-02` | `ocr_text` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `ocr-text-hard-negative-03` | `ocr_text` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `ocr-text-positive-01` | `ocr_text` | `positive` | `accepted` | `accepted` | yes | — |
| `ocr-text-positive-02` | `ocr_text` | `positive` | `accepted` | `accepted` | yes | — |
| `ocr-text-unavailable-01` | `ocr_text` | `unavailable` | `unavailable` | `unavailable` | yes | — |
| `ocr-text-warning-01` | `ocr_text` | `warning` | `manual_review` | `manual_review` | yes | — |
| `publication-layout-borderline-01` | `publication_layout` | `borderline` | `manual_review` | `manual_review` | yes | — |
| `publication-layout-hard-negative-01` | `publication_layout` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `publication-layout-hard-negative-02` | `publication_layout` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `publication-layout-hard-negative-03` | `publication_layout` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `publication-layout-positive-01` | `publication_layout` | `positive` | `accepted` | `accepted` | yes | — |
| `publication-layout-positive-02` | `publication_layout` | `positive` | `accepted` | `accepted` | yes | — |
| `publication-layout-unavailable-01` | `publication_layout` | `unavailable` | `unavailable` | `unavailable` | yes | — |
| `publication-layout-warning-01` | `publication_layout` | `warning` | `manual_review` | `manual_review` | yes | — |
| `semantic-faithfulness-borderline-01` | `semantic_faithfulness` | `borderline` | `manual_review` | `manual_review` | yes | — |
| `semantic-faithfulness-hard-negative-01` | `semantic_faithfulness` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `semantic-faithfulness-hard-negative-02` | `semantic_faithfulness` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `semantic-faithfulness-hard-negative-03` | `semantic_faithfulness` | `hard_negative` | `rejected` | `rejected` | yes | — |
| `semantic-faithfulness-positive-01` | `semantic_faithfulness` | `positive` | `accepted` | `accepted` | yes | — |
| `semantic-faithfulness-positive-02` | `semantic_faithfulness` | `positive` | `accepted` | `accepted` | yes | — |
| `semantic-faithfulness-unavailable-01` | `semantic_faithfulness` | `unavailable` | `unavailable` | `unavailable` | yes | — |
| `semantic-faithfulness-warning-01` | `semantic_faithfulness` | `warning` | `manual_review` | `manual_review` | yes | — |

The frozen observations are hand-authored regression inputs. Their perfect agreement with fixture labels proves only that the typed aggregation and decision policy replay deterministically; it is not judge-human agreement or a live-model benchmark.
