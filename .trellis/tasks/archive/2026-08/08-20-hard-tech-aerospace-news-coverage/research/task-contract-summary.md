# Bounded implementation/check contract

This task-local summary exists because the owning pipeline and quality specs exceed the context-injection file-size limit. The linked specs remain authoritative; this file extracts only the clauses needed by this task.

## Acquisition contract

Source: `.trellis/spec/backend/agent-pipeline.md:75-164`.

- The active frontier is exactly ten controlled government, education, research, company and media profiles. It does not authorize arbitrary URLs or general web search.
- Xinhua Tech and Xinhua Education are already active; CAST and EdSurge remain pending and must not be activated here.
- Default acquisition is daily at 06:30 Asia/Shanghai. Discovery and detail limits remain separate and bounded.
- Current v2 behavior requires a topic plus substantive progress and excludes financing/ordinary releases; this task intentionally replaces that behavior only for a new immutable version.
- Candidate evaluation is deterministic, NFKC-normalized and bounded to 6000 body characters.
- Title ordering currently uses education, frontier, then neutral; detail re-evaluates title plus body and freshness.
- Persist rule version, cohort/scores/reasons, title/body topic/progress/exclusion terms, product directions, bounds, URLs, times, source/version IDs, snapshot and observations.
- Historical relevance-rule strings remain executable. Downstream uses stored text/snapshots and must not re-crawl.
- Connector tests must preserve exact path/host restrictions, duplicate-anchor handling, parser drift and all ten active/two pending fixtures.
- Integration uses real PostgreSQL/MinIO fakes/fixtures and verifies bounded detail fetch, zero-match/cursor behavior, immutable snapshots and no refetch.

## Topic-selection contract

Sources: `.trellis/spec/backend/agent-pipeline.md:238-258` and `.trellis/spec/backend/topic-selection.md:7-90,142-226`.

- Current `.8` threshold is 0.59 with weights 0.30 editorial, 0.25 product fit, 0.15 source trust and 0.10 each diversity/freshness/communication. This task does not change those numbers.
- Scoring config is immutable by `(profile, version)` with canonical snapshot/fingerprint; historical responses read run snapshots, not process settings.
- `.6`, `.7`, `.8` must remain replayable with exact v2 editorial identity. A new default version owns broad-hard-tech semantics.
- Genuine vetoes are independent of the numeric score. This task retains unresolved governance, ineligible evidence, Tier-C-only, unverified, privacy/legal/safety, prohibited deception, delivered-repeat and stale-event barriers. It intentionally stops treating a verified hard-tech failure itself as an unsuitable-negative veto under the new policy.
- The new policy may admit a governed Tier-A/B hard-tech candidate below 0.59 only when remaining vetoes are empty; persist `passes_threshold=false`, `eligible=true` and an explicit policy/bypass reason.
- Plans, failures, financing, events and product releases are content classes/ranking inputs, not completed-breakthrough claims.
- Rerank runs only after deterministic eligibility, is capped at eight, cannot cross priority/veto barriers, and uses deterministic fallback on provider/output failure.
- Selection persists every considered score/rank/explanation and at most one locked daily topic or `no_topic`.
- `.7`/`.8` delivery-backed repeat history and slot same-day constraints remain unchanged; the new version inherits delivery-backed provenance.

## Database/versioning contract

Source: `.trellis/spec/backend/database-guidelines.md:188-220`.

- `source_versions.relevance_rule_version` and candidate rule identity are durable provenance.
- New source seeding creates immutable fingerprinted versions and retains history; no old candidates, snapshots, versions or scoring configs are rewritten.
- This semantic rollout requires no migration unless storage shape changes; JSON audit fields may extend compatibly.
- Retry attempts do not accumulate terminal filtered counts; run counts remain sums of terminal jobs.

## Quality/security contract

Sources: `.trellis/spec/backend/quality-guidelines.md:9-25,300-380`.

- Type public functions, keep domain pure, version policies/configs, persist reproducible provenance and use fixed clocks/fixtures.
- Required full gate: Ruff format/lint, strict mypy, pytest+coverage through `make backend-check`; also API drift if schema changes, Compose render for defaults, and `git diff --check`.
- Unit tests cover normalization, scoring, threshold and veto precedence. Integration uses real PostgreSQL, not SQLite.
- Rerank sees only eligible candidates, remains bounded, and cannot override hard vetoes or invent evidence.
- Source/model text is untrusted; no prompt, key, raw provider body, private path or full article enters logs/model diagnostics.
- This task performs no provider call, production mutation, deployment, replay or delivery.
