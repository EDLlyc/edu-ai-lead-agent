# Same-topic golden pairs

Real headline pairs from production picks, labelled "same topic" or not, to measure the headline
clause of the same-topic rule used by `slot-ranking-v2-same-topic-dedup` (one story per topic per
day) and by the quality report / selection replay.

- `pairs.v1.jsonl`: only clear-cut pairs; ambiguous "same theme, different story" pairs are left
  out. `label_source` says who labelled them and from which picks.
- `current` is the production headline clause; `candidate` strips numbers and boilerplate
  (issuing bodies, 开幕式/致辞/出席/会见, 高质量发展, column prefixes, a source's own institution
  name) before matching.
- The pairs were drawn from matches the rule produced, so precision is the meaningful number;
  recall is only indicative. The embedding clause is not evaluated here.

```bash
make same-topic-eval                                               # fails on drift
cd backend && python -m evals.same_topic_golden.runner --write-canonical   # after review
```
