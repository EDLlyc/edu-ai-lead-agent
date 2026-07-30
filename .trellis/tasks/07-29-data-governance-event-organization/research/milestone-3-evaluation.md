# Milestone 3 controlled event-organization evaluation

Date: 2026-07-29

## Scope

This evaluation covers the versioned deterministic policy implemented in Milestone 3. It uses
controlled fixtures rather than live-news labels. It verifies decision boundaries, persistence,
checkpoint recovery, source diversity, and concurrency safety; it does not establish production
clustering quality on an open-world news stream.

Policy versions:

- semantic duplicate: `semantic-v1`
- event assignment: `event-assignment-v1`
- embedding provider contract: `embedding-3`, 2048 dimensions

## Controlled labeled set

| Fixture | Expected | Observed |
| --- | --- | --- |
| Exact copy of an already organized article | attach existing event through deterministic reuse | attached |
| Same-event title paraphrase, compatible entity/category/time | attach existing event | attached |
| Same topic, event time separated by 30 days | create distinct event | created |
| High similarity but conflicting organization identity | review | review |
| High similarity with five-day date distance | review | review |
| Embedding similarity in the gray band | review | review |
| Transitive-neighbor risk where the event representative is not close | create distinct event | created |

The four non-ambiguous auto-decision samples contain two positive same-event pairs and two
distinct-event pairs:

- auto-attach precision: `2 / 2 = 1.00`
- auto-attach recall: `2 / 2 = 1.00`
- auto-attach F1: `1.00`
- review rate over all seven labeled policy samples: `3 / 7 = 42.86%`
- distinct-event false merges: `0`

These figures are regression baselines for this fixture set, not statistical estimates of live
precision or recall. The set is intentionally small and balanced around known boundaries.

## Persistence and recovery observations

- PostgreSQL checkpoint interruption after factual analysis resumed without a second factual-model
  invocation. Replaying under a new graph thread reused the stored analysis and both stored
  purpose-specific embeddings.
- Near-duplicate and event-assignment embeddings remained separate and each persisted at 2048
  dimensions.
- Reuse is scoped to the claimed prompt/schema/taxonomy/provider/model and embedding
  provider/model/dimension/input versions. Changing an analysis or embedding version creates a new
  immutable derivation instead of silently loading the latest artifact for that article.
- An acquisition candidate shared by two source observations produced two governed occurrences and
  an initial event projection with `source_diversity = 2`.
- Adding an exact-copy candidate created a second immutable event version; the first version retained
  its original member-set hash and source-diversity projection.
- Event versions persist a relational representative article ID and the complete version-bundle
  fingerprint. Candidate retrieval joins only that stable representative, not whichever member is
  nearest to the incoming article, preventing transitive-chain merges.
- Two concurrent workers processing same-event articles produced one event, two memberships, and
  serialized outcomes of one `created_new` plus one `assigned_existing`.
- Replaying the exact-copy job did not add another analysis, embedding, duplicate relation,
  membership, assignment decision, or event version.
- Artifact transactions lock and revalidate the active governance lease before commit, so a stale
  worker cannot publish normalized, model-derived, duplicate, or event records after losing its
  fencing token.

## Representative limitations and follow-up

- Entity normalization is currently exact case-folded canonical-name comparison; aliases and
  organization renames can increase review volume.
- Event time uses the accepted structured projection and falls back to publication time. Articles
  describing retrospective or scheduled events may need richer temporal features.
- The recent-event query is exact pgvector distance over a bounded PostgreSQL window. This is the
  intended current scale shape, but candidate-limit and index strategy must be reevaluated with
  production volume.
- No transitive-chain merge is allowed: each article is compared with stable event representatives.
  This protects precision but can split events whose representative becomes stale.
- Threshold tuning must create a new similarity or assignment policy version. Existing decisions and
  event versions remain immutable.

Before production threshold claims, build a larger labeled corpus from real stored articles with
independent human annotation and report confidence intervals, per-category metrics, review burden,
and representative false-merge/false-split cases.

## Post-review validation

The final review gate passed all six focused PostgreSQL tests covering graph recovery, stale-worker
fencing, version-specific derivations, exact-copy organization, stable-representative behavior,
concurrent assignment, and migration parity. The 149 non-integration backend tests, provider
contracts, Ruff formatting/lint, strict mypy, and `git diff --check` also passed.
