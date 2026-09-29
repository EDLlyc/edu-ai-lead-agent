# Selection replay

Replays the **real** candidate pool of every scheduled content-slot run in a date range under
one or more selection-rule variants and compares them with what production actually picked.
It answers "how would rule X have picked last week?" on production data, which the topic golden
set (hand-labelled single headlines) cannot.

- Read-only: one `SET TRANSACTION READ ONLY` session; no model calls (the LLM rerank is skipped,
  so a replay is the deterministic order).
- Repeat history inside the range comes from each variant's own picks (treated as delivered);
  history before the range comes from production.
- Metrics: gov.cn 要闻 priority (and how many are not science/education), 教育风向, negative
  incidents, specialised research, below-threshold picks, same-day same-topic pairs, 14-day
  repeats split by which same-topic clause matched (`same_event` / `similar_article` embedding /
  `title_phrase` headline), mean score, and per-slot changes between the last two variants.

It needs the production database, so run it in a one-off container of the running image with this
directory mounted:

```bash
sudo docker compose -p edu-ai-lead-agent --env-file .env --env-file .release.env run --rm --no-deps -T \
  -v /tmp/evals:/app/evals:ro -e PYTHONPATH=/app --entrypoint python acquisition-api \
  -m evals.selection_replay.runner --start 2026-09-19 --end 2026-09-28 \
  --variant v14=scoring-v1-preview.14-negative-incident-industrial-tech+slot-ranking-v2-same-topic-dedup \
  --variant v15=scoring-v1-preview.15-gov-yaowen-topic-gate+slot-ranking-v2-same-topic-dedup
```

Dated results are kept in `reports/`.
