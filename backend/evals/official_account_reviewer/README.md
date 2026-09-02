# Official-account Reviewer provider-free evaluation

This track verifies the governed Reviewer's closed contract, input-reference binding, hard-gate
precedence, code-owned repair policy, metrics, and canonical-report pipeline. It uses 48 sanitized,
hand-authored fixtures and makes **zero provider or model calls**.

Run from `backend/`:

```bash
python -m evals.official_account_reviewer.runner --check
```

Intentional contract changes require review before regenerating artifacts:

```bash
python -m evals.official_account_reviewer.runner --write-canonical
```

## Truth boundary

- `cases.v1.jsonl` contains only typed evaluator-facing observations, declared article references,
  deterministic hard-gate results, and provider availability state.
- `oracle.v1.jsonl` is physically separate and contains expected decisions, issues, locations, and
  repairability labels. `run_fixture_policy(case)` cannot receive an oracle object.
- `rubric.v1.json` must exactly match the shared domain taxonomy. Unknown keys, issue codes,
  severity drift, repairability drift, broken references, duplicate IDs, sparse dimensions, unsafe
  fields, and canonical drift fail closed.
- The canonical evaluator-bundle SHA binds the domain contract, loader, typed fixture models,
  frozen policy, metrics, reporting, and runner; changing metric code cannot retain stale evidence.
- Severity, repairability, and repair operations are code-owned. Neither the dataset nor a future
  model output can provide free-text instructions to the Writer.

The canonical precision/recall/F1 and accuracy values measure deterministic fixture-contract
conformance only. They are **not** live Reviewer accuracy, human agreement, production uplift,
model quality, or online safety effectiveness. A separate explicitly authorized live A/B track is
required before making any such claim.
