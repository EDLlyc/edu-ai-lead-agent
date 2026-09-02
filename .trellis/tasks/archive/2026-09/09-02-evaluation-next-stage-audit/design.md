# Design: Evaluation next-stage roadmap

## 1. Evidence architecture

Keep four evidence tiers explicit and never merge their claims:

```text
Tier 1 contract regression  -> provider-free fixtures + canonical drift -> CI blocking
Tier 2 model/corpus quality -> opt-in live runs + frozen datasets        -> comparison evidence
Tier 3 human alignment      -> independent labels + adjudication         -> release recommendation
Tier 4 online effectiveness -> privacy-reviewed trends/experiments       -> product impact
```

The current repository is strongest at Tier 1. The grounded IP run is Tier 2 but uses
`codex_seed` labels. The user chose not to schedule human assessors, so the next implementation
strengthens Tier 2 through Codex-reviewed Seed V2 and fixes measured abstention weakness without
claiming Tier 3 or changing production search behavior.

## 2. Recommended P0 boundary

Create an additive `codex_seed_v2` path beside V1; never overwrite or silently promote the original
seed.

```text
existing 41-asset snapshot + V1 Seed
                     |
                     +-> Codex image reinspection
                     +-> 24 no-answer/near-miss queries -> full 24x41 grades
                     +-> blind audit of risky V1 slices -> reviewed change ledger
                     `-> immutable codex_seed_v2 (124x41)

live safe run -> safe ranking/evidence observations -> threshold sweep on dev
                                                    -> one-shot holdout report
                                                    -> paired V2/V3/candidate-policy comparison
```

There is no annotation webpage, new business API or production database migration. The evaluator
identity is Codex, maturity remains Seed, and no human or independent-reviewer agreement metric is
produced.

## 3. Query and label design

- Preserve the existing 100 queries and 4,100 Codex judgments as V1 Seed history.
- Add exactly 24 no-answer/near-miss queries so V2 has 124 queries, exactly 30 no-answer queries and
  5,084 judgments. Cover
  nonexistent character, wrong scene, contradictory constraints, unsupported exact text, unavailable
  department/style and close semantic distractors.
- Keep a dev/holdout split; assign 18 new queries to dev and 6 to holdout. Thresholds and feature
  choices use dev only.
- Codex completes all 41 judgments for every new query after re-viewing the corpus. No pooling is
  needed for a 41-image corpus.
- Blind-audit the existing no-answer, combined-constraint, grade-1/2 boundary and fixed space-station
  slices without opening rank/run files. A typed change ledger records old/new grade and bounded
  rubric reason.
- Store only Codex evaluator/version, rubric and review pass identity; do not manufacture reviewer
  accounts, adjudication or agreement statistics.

## 4. Selective-retrieval diagnostics

Extend safe live observations with bounded decision evidence, not raw vectors/provider bodies:

- top semantic similarity where present;
- top1/top2 similarity margin;
- metadata match score/count;
- number of ranking lanes supporting top results;
- mode/degraded reason and returned count.

The evaluator sweeps versioned candidate rules and reports:

- no-answer false-positive and correct-abstention;
- answerable false-abstention;
- coverage and risk/coverage curve;
- Recall@3/5, MRR@5 and nDCG@5 at each retained coverage;
- per-category/dev/holdout slices and paired bootstrap intervals.

The P0 deliverable recommends a threshold/policy but does not change the production selector. A
separate approved task may introduce `ip-asset-hybrid-v4-selective-rrf` after this Seed report is
reviewed; human calibration remains a deferred evidence gap.

## 5. Minimal durable run envelope

Do not build a general evaluation platform in P0. Define a small safe manifest only when preserving
live reports:

- `run_id`, git commit, evaluator/search/model/provider/input-policy identities;
- dataset, query, corpus, qrels and rubric hashes;
- aggregate/slice metrics, CI configuration, latency/token/cost aggregates;
- artifact relative refs and SHA-256;
- evidence tier/maturity and validity notes.

The manifest must not contain query text, raw output, image paths, vectors, prompts, provider bodies
or user identity. Storage can begin as ignored local artifacts plus a reviewed Markdown summary; a
database/service is deferred until multiple live tracks require shared querying.

## 6. Compatibility, risks and rollback

- Existing provider-free targets and Seed canonical remain byte-stable.
- Seed V2 artifacts are additive and fail closed on incomplete matrices, invalid evaluator identity
  or corpus drift.
- Evaluation-only runs continue through the no-telemetry service boundary.
- Multiple Codex passes can measure self-consistency only; they do not establish human alignment or
  independent agreement.
- Production threshold activation, online experiment tokens and evaluator database schema are
  separate approvals and rollback boundaries.

## 7. Deferred tracks

- A future human Gold campaign remains deferred by user decision.
- Official-account article live/human A/B stays with the existing governed Reviewer task.
- Image live calibration should follow after retrieval P0 and use atomic prompt constraints plus
  pairwise preference and IP-identity review.
- General Agent live trace/pass-k evaluation follows after governed Reviewer integration.
- Online randomized search experiments wait for traffic and privacy review.
