# Topic rerank offline evaluation

This provider-free evaluation exercises the shared daily and morning/noon/evening rerank boundary
with synthetic governed candidates. It checks bounded complete permutations, priority barriers,
hard-veto and same-day exclusions, selection boundaries, and deterministic fallback. The fixed fake
uses only allowlisted candidate projections and does not read expected answers from the JSONL cases.

Run it from the repository root:

```bash
cd backend && python -m evals.topic_rerank.runner --check
```

Use `--write-canonical` only after an intentional dataset, policy, or evaluator change has been
reviewed. Canonical artifacts exclude wall-clock latency, tokens, timestamps, and random IDs.

The report is **fixture contract conformance only**. It does not claim live-provider behavior,
editorial ranking accuracy, production readiness, or business impact.
