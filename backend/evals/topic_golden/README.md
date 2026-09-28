# Topic golden set

Operator-labelled "should / should not select" news for the topic-selection rules. It answers a
different question from `topic_rerank` (which only checks the rerank contract): **would the rules
pick the news the operator actually asked for, and reject what they do not want?**

- `cases.v1.jsonl`: one case per line. `label_source` records who decided and when;
  `synthetic=false` marks real headlines the operator explicitly asked for, `synthetic=true` marks
  representative examples of an operator rule (e.g. "no admissions marketing").
- Each case is projected like the governed loader would (fresh, verified, listed A/B sources), so a
  rejection comes from the editorial/selection rules, not from a veto.
- The report compares the pre-change production baseline `.11` with the current default `.13`,
  and records how acquisition would order each headline for a detail fetch.

```bash
make topic-golden-eval                                   # fails if the report drifted
cd backend && python -m evals.topic_golden.runner --write-canonical   # after reviewing a change
```

Adding a case: whenever the operator says "this should have been picked" or "this should not be
pushed", append the real headline and summary with the date in `label_source`, run the runner and
commit the reviewed canonical report. Known open gaps stay visible in `canonical-report.md` until a
rule change fixes them.
