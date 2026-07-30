# Daily Topic Selection and Locking

## Goal

Convert the governed event pool into at most one explainable daily topic or a durable `no_topic`
decision without using an LLM for the final numeric score.

## Parent and Dependency

- Parent: `07-30-content-production-mvp`.
- Input dependency: completed governance event/fact/evidence/source projections.
- Output dependency: brand retrieval and material generation may run only for a locked topic.

## Requirements

- Apply versioned hard vetoes before numeric scoring.
- Normalize and persist source trust/diversity, AI/science-education relevance, parent relevance,
  freshness, communication potential, repetition, controversy, and marketing-risk features.
- Implement a transparent, replaceable `scoring-v1-preview` for the functional MVP, show real
  rankings to the user, and defer larger labeled tuning/formal production activation to hardening.
- Enforce the materially same event seven-day veto and stable tie-breaks.
- Lock at most one event/version per `Asia/Shanghai` business date and scoring profile.
- Persist every feature, weight, penalty, threshold, veto, rank, cutoff, config, and explanation.
- Produce `no_topic` when no eligible score reaches the threshold and stop downstream work.
- Add durable scheduling/manual enqueue, jobs/leases/retries, status/query APIs, and safe operations.

## Acceptance Criteria

- [x] Controlled and real event sets have documented expected/actual rank and decision results.
- [x] The user can inspect all `scoring-v1-preview` values/results, and a later config version can
      replace it without rewriting score/selection code or historical rows.
- [x] Two concurrent runs cannot lock two topics for one date/profile.
- [x] Seven-day repeated events and hard-veto cases cannot be rescued by high scores.
- [x] Below-threshold/all-veto days persist `no_topic` and make no downstream provider call.
- [x] API exposes complete safe explanations and versions without re-fetching/re-summarizing.
- [x] Replay/restart is idempotent and existing acquisition/governance behavior remains unchanged.

## Out of Scope

- Brand retrieval, copy, audit, image, material UI, model-generated final scores, or manual weight
  editing UI. Large labeled tuning and production scoring calibration are deferred hardening.
