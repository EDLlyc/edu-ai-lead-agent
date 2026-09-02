# Evaluation repository audit — 2026-09-02

## Executive finding

The project has a strong deterministic regression layer but only one real-provider paired retrieval
run, no human Gold retrieval labels, no calibrated selective-retrieval policy, and no durable
cross-suite live-run ledger. The next investment should increase evidence maturity rather than add
another synthetic fixture suite.

## Current evaluation matrix

| Track | Size | Data / execution | Current evidence | Missing evidence |
| --- | ---: | --- | --- | --- |
| Agent Workbench | 42 | synthetic, deterministic policy, provider-free | tool/citation/refusal/budget contract | live-model repeated trials, final-state and trace quality |
| Brand text retrieval | 36 | sanitized frozen FTS/vector ranks | RRF and parent-diversity regression | private-corpus human qrels and live embedding quality |
| Digital IP | 5 | deterministic projections | closed profile/projection contract | user usefulness or retrieval quality |
| Image quality | 48 | hand-authored frozen observations | rubric, hard-gate and persistence contract | real generated images, judge-human agreement, threshold calibration |
| IP retrieval synthetic | 41 | sanitized frozen ranks | V2/V3 selector regression | real provider/corpus behavior |
| IP retrieval grounded | 100 queries / 4,100 grades | real 41-image corpus, Codex seed; explicit live provider | real V2/V3 paired run with bootstrap | human Gold, robust no-answer set, calibrated abstention |
| Topic rerank | 10 | synthetic governed candidates | priority/veto/fallback structure | live editorial preference and business value |
| Visual retrieval | 6 | synthetic metadata/semantic inputs | selector/provider-failure contract | real prompt/image relevance and human preference |
| Official-account Reviewer (in progress) | 48 | provider-free contract fixtures | verdict/rubric/repair-policy contract | planned human-calibrated live A/B, not yet stable/committed |

The checked worktree currently runs the first eight tracks through `make eval-check`
(`Makefile:182-237`) and Yunxiao invokes that target after `backend-check`
(`deploy/yunxiao/pipeline.yaml:115-119`). The check passed on 2026-09-02.

## Strengths worth preserving

1. Canonical reports are byte-stable, schema/version/hash bound, and do not silently rewrite.
2. Evaluation oracles are kept out of production ranking/policy inputs.
3. Provider-free CI and opt-in live tracks are separated, so third-party availability cannot make
   ordinary pull requests flaky.
4. The grounded IP suite binds 41 approved images, 100 queries, 4,100 graded judgments, query/asset
   hashes, explicit model identity and no-telemetry execution.
5. Paired query-level bootstrap is already implemented for live V2/V3 comparisons.
6. Reports consistently state what the score cannot prove; fixture success is not called model
   accuracy or business uplift.

## High-priority gaps

### G1 — IP retrieval cannot reliably abstain

The only real live comparison shows no-answer false-positive rate `0.8333` for both V2 and V3, while
the six no-answer queries are too few for stable threshold selection
(`.../live-run-2026-09-02.md:23-29`). Ranking improved first-relevant placement, not recall. The
production selector generally returns candidates when compatible vectors exist, so ranking metrics
alone cannot solve “the library has no suitable image.”

Required next evidence:

- expand no-answer and near-miss cases to at least 30, with dev/holdout separation;
- measure answerable false-abstention together with no-answer false-positive;
- emit risk/coverage and threshold-sweep reports from safe top-score, score-margin, metadata-match
  and evidence-lane observations;
- select thresholds on dev only and evaluate holdout once;
- do not activate a production threshold in the evaluation task.

### G2 — `codex_seed` is not human Gold

The grounded canonical explicitly records `Maturity: seed` and `codex_seed`
(`backend/evals/ip_asset_retrieval_grounded/canonical-seed-report.md:3-11`). A credible Gold
promotion needs two independent human judgments on an overlap set, explicit adjudication,
label-source/version provenance and ordinal agreement. Codex labels must remain as a separate
baseline rather than being overwritten.

The 41-image corpus is small enough for complete judgments. If reviewer time is constrained, a
pooled assessment may be used, but the report must disclose pooling depth and unjudged-document
handling. No web annotation page is required: versioned offline worksheets/import validation are
sufficient.

### G3 — Holdout governance is organizational, not blind

The 20 holdout queries and all labels are committed alongside dev data. This prevents accidental
per-split metric mixing, but it cannot prevent tuning against visible labels. A later release gate
needs a sealed or rotating test set whose labels are unavailable to day-to-day tuning and whose
aggregate result is revealed only by the evaluator.

### G4 — Online aggregates are safe but not causal

The current table/API is intentionally grouped only by `business_date`, `search_version`, `mode`
and event kind (`backend/app/infrastructure/db/models.py:5521-5552`; schemas at
`backend/app/schemas/ip_assets.py:189-212`). This is good privacy engineering, but it means:

- there is no unique search denominator, so multiple previews can make an action ratio exceed 1;
- there is no query category or experiment assignment;
- the globally configured search version does not create simultaneous randomized V2/V3 traffic;
- low internal traffic may make classical A/B statistically uninformative.

Keep these metrics as operational trends. Do not call them conversion probabilities or causal
uplift. Add an experiment/session token only after traffic and privacy review justify it.

### G5 — Live run evidence is ephemeral

Grounded live observations were intentionally written to `/tmp` and not committed
(`.../live-run-2026-09-02.md:47-49`). That protects canonical truth from provider drift, but prevents
longitudinal comparison unless an operator manually preserves every report. A small durable eval
manifest should record run ID, git SHA, model/provider/input policy, dataset/rubric hashes, aggregate
metrics, latency/cost and artifact hashes without storing queries, vectors or provider bodies.

### G6 — Open-ended product quality still lacks human-calibrated live evidence

- Image quality currently proves only frozen policy conformance; real IP identity, prompt fidelity,
  OCR, aesthetics and crop thresholds remain uncalibrated.
- Agent Workbench proves a deterministic policy, not live model reliability across repeated trials.
- The in-progress official-account Reviewer task already owns the next article-quality rubric,
  provider-free contract and planned live/human A/B. Do not create a second article judge.
- Brand text/visual retrieval still uses synthetic observations, so private-corpus live quality is
  unknown.

## Medium-priority infrastructure gaps

1. Each eval implements its own dataset/metrics/reporting/runner stack; there is no cross-suite run
   manifest or artifact registry. Avoid a broad framework rewrite, but standardize a minimal result
   envelope when adding the durable live ledger.
2. Most deterministic tracks correctly omit confidence intervals, but future live/model tracks need
   paired uncertainty, failure taxonomies and bad-case samples, not only averages.
3. LLM graders need a meta-eval: blinded order swaps, human-audited calibration cases, judge version
   pinning and disagreement reports. A judge must never be its own unmeasured truth source.
4. Retrieval robustness should add paired paraphrase/noise invariance, filter monotonicity and
   near-miss hard negatives. These are more diagnostic than another batch of independent easy cases.
5. Every report should include a validity section covering harness identity, contamination,
   broken/ambiguous cases, reward-hacking shortcuts and sample review.

## Priority recommendation

1. **P0: IP retrieval Human Reference + selective-abstention evaluation.** It addresses the only
   measured live failure and upgrades the highest-value Seed evidence.
2. **P1: durable eval run manifest/history.** Preserve live evidence before running more paid tests.
3. **P1: finish the existing official-account Reviewer human-calibrated live A/B.** Reuse that task;
   do not duplicate a long-form judge.
4. **P1: live image-quality calibration in observe mode.** Pair prompt-constraint checks with human
   preference/identity review.
5. **P2: Agent repeated-trial trajectory evaluation and online search experiment design.** Proceed
   only when traffic, provider budget and human-review capacity exist.

## User decision after the audit

The user chose not to schedule human assessors and asked Codex to perform the next labeling pass.
The immediate implementation therefore becomes **Codex-reviewed Seed V2 + selective-abstention
evaluation**. This does not close the human-alignment gap: all new reports must retain Seed maturity
and must not report human Gold or human agreement.
