# Human review export

Turns the exhibit's operator reviews into labelled evaluation cases. These are the project's only
human labels: nothing here is scored by a model.

```bash
make human-review-report STORE=/root/projects/edu-ai-lead-agent/tmp/visitor-display/news-reviews.sqlite3
# or, to also write labels.jsonl, golden-candidates.jsonl and report.md:
cd backend && python -m evals.human_review.runner --store <file> --output-dir ../output/human-review
```

- The store is opened read-only. One label per news item: the operator's latest decision.
- Report: how often the AI's selection agrees with the operator, the share of AI picks the
  operator would also push, the share of wanted news the AI picked, and both disagreement lists
  with the AI's reasons and the operator's note. Under 30 reviews the report says the rates are
  indicative only.
- `golden-candidates.jsonl` holds topic-golden stubs for the disagreements. Review the category
  and summary, append the ones you accept to `evals/topic_golden/cases.v1.jsonl`, then run
  `python -m evals.topic_golden.runner --write-canonical`. Reviews recorded before the exhibit
  stored the snippet and source tier cannot become candidates and are counted as skipped.

Routine: review 10–20 items a day in the exhibit (both selected and rejected news), run the report
weekly, and turn repeated disagreement reasons into rules.
