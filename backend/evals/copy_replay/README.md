# Copy replay (Moments A/B)

Re-generates first drafts for the real accepted slot topics of one business date under two or more
generator prompt versions, then validates and audits them without repair or database writes.
Use it before switching a copy prompt / brand-retrieval version.

- Spends real model calls (about two per topic per version) and reads production; run it in a
  one-off `content-worker` container with `evals/` mounted.
- Brand-rotation versions see the brand statements of accepted copy in the 3 days before the date,
  plus the drafts this replay already produced (sequential production).
- Metrics: rule-validation pass, first-draft audit acceptance, drafts reusing an 8-character run of
  a recent brand statement, the most repeated brand wording, and each draft's brand sentence.
- A validation failure is for the whole first draft (often a news-fact sentence); production
  repairs once before review.

```bash
sudo docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env run --rm --no-deps -T \
  -v /tmp/evals:/app/evals:ro -e PYTHONPATH=/app --entrypoint python content-worker \
  -m evals.copy_replay.runner --date 2026-09-28 \
  --prompt-version moments-generator-v24-standalone-heading \
  --prompt-version moments-generator-v25-brand-rotation
```

Dated results are kept in `reports/`.
