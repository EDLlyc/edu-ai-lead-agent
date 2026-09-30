# 评测门禁、埋雷测试、人工标注导出与文案模板评测

## Source request (2026-09-29, owner)

“然后你看一下，我们的评测还要怎么优化” → review found eight gaps; the owner chose to build all four
high-priority items: 上线门禁、埋雷测试、人工审核导出脚本、新文案模板评测.

## Findings that motivate the work (production, last 30 days, read-only)

- No evaluation is a deploy gate; mainline CI does not run `eval-check`; ~14 overlay deploys on
  09-28/29 relied on a manual smoke test. On mainline `1632ce2` two provider-free checks were
  already red and nobody saw it: `topic_rerank` (`priority-barrier`) and four selection unit tests
  failed because their fixtures paired the default scoring version with an obsolete priority rule,
  which silently disables priority. The production barrier itself works (verified with the
  production config: a crossing rerank falls back with `priority_barrier_violation`).
- The copy auditor's most frequent findings are `hashtag_quality` (116) and `length_warning` (59);
  it has never been measured on known factual defects with a live model.
- No evaluation covers the headline-hook template (generator v26 / auditor v20 / rules v13).
- Zero human labels feed any evaluation; the exhibit's `news_reviews` store has 0 rows.

## Requirements

1. **Pre-deploy gate** — one command runs every provider-free evaluation and the unit + contract
   tests against a known-failure baseline; any new failure fails the gate. The production-mainline
   guide requires it before an overlay build. Stale fixtures found on the way are fixed.
2. **Seeded-defect test** (`evals/copy_quality defects`) — generate headline-hook drafts for real
   accepted topics, inject one known defect per mutant (hook and long-image claims), run the
   production validator and the live auditor exactly as production does, and report per defect
   type: blocked by validator / blocked by auditor / warned only / missed, plus false alarms on the
   unmodified drafts.
3. **Hook-quality evaluation** (`evals/copy_quality hooks`) — a fixed replay set of real topics, a
   four-criterion rubric scored by a judge model, and a sheet for human spot checks with
   judge-vs-human agreement once labels exist.
4. **Human review export** (`evals/human_review`) — read the exhibit's local review store and emit
   labelled cases, AI-vs-human agreement, and topic-golden candidates. The exhibit store records
   enough of the candidate (URL, snippet, tier, score, reasons) for the export to stand alone.

## Constraints

- No `app/` behaviour change, no migration, no deploy. Paid model runs happen only in one-off
  containers outside slot hours, with the planned call count printed first and a hard call cap.
- Evidence boundaries: AI-judged scores are never called human labels; every metric reports its
  denominator; single-trial results say so.
- Frozen production inputs that contain brand text stay out of the repository.

## Acceptance

- [ ] `make predeploy-check` is green on the branch and fails on an injected regression.
- [ ] Defect and hook reports exist for a first real run, with call counts and token usage.
- [ ] Exporter has unit tests and a documented labelling routine; works on an empty store.
- [ ] Unit tests for mutation, classification, rubric parsing and export logic; ruff/mypy clean.
