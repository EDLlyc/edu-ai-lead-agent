# Curated implementation contracts

This is a task-local routing summary for context injection. The authoritative full sources remain
`.trellis/spec/backend/ip-asset-hub.md` (especially **Scenario: Grounded 41-asset retrieval
evaluation**, line 630 onward) and `.trellis/spec/backend/quality-guidelines.md` (especially
**Scenario: Unified provider-free evaluation gate**, line 383 onward). Re-open those complete files
before editing their domains; do not treat this summary as a replacement spec.

## Grounded retrieval invariants

- The existing 41-asset snapshot, 100-query Seed V1 and 4,100 `codex_seed` grades are immutable
  history. Query/asset/rubric/dataset hashes and truthful Seed maturity are part of the contract.
- Query and label authoring must not consume live ranks, cosine, metadata score or RRF output.
- Evaluation runs reuse production filter extraction, metadata/vector retrieval and rank selection
  through the no-telemetry boundary. Ordinary search retains its anonymous aggregate write.
- Run observations/results may contain only safe query/catalog refs and bounded version/decision
  evidence. Never persist vectors, provider body/request ID, dynamic database UUID, original image
  path/key/checksum, profile/user/session/IP/UA/cookie or raw business query.
- No-answer cases are separate from answerable ranking macros. Reports include correct abstention
  and false-positive rates rather than granting artificial perfect Recall/MRR.
- Paired comparisons require the same corpus/query/label/embedding identity, fixed query order and
  fixed-seed query-level bootstrap.
- Provider-free authoring/schema/hash/canonical checks stay in `make eval-check`; live model/database
  execution remains an explicit local command.
- No frontend page, annotation API, human-workflow database or production search behavior is added.

## Current task additions

- The user explicitly chose Codex-only review. Create additive Seed V2 with exactly 124 queries,
  exactly 30 no-answer queries and exactly 5,084 grades; never call it human Gold or agreement.
- Add exactly 24 no-answer/near-miss queries, with 18 dev and 6 holdout. Re-view all 41 images before
  authoring and blind-audit the risky V1 slices without opening rank/run artifacts.
- Add evaluation-only bounded decision evidence and dev threshold sweeps. Report answerable
  false-abstention together with no-answer false-positive and risk/coverage. Holdout is reporting
  only. Do not activate a production V4 selector.
- Add only a minimal safe live-run manifest; no general eval platform, API, UI or migration.

## Quality-gate invariants

- Checked runners never silently rewrite canonical artifacts. Intentional data/report changes need
  explicit authoring/write commands plus reviewed diffs.
- `make eval-check` remains provider-free, propagates any child failure and requires no key/network/
  worker/business write. Keep every existing target compatible.
- Fixture/Seed metrics are regression evidence, not live-model accuracy, human alignment or business
  uplift. Every report states the harness, evidence tier and validity limits.
- Required validation includes focused tests, canonical/hash checks, Ruff format/lint, strict mypy,
  privacy/scope scan and `git diff --check`.
- The shared worktree has overlapping P0/Reviewer changes. Preserve them, inspect the latest diff,
  avoid bulk formatting and stage only task-owned paths/hunks.

