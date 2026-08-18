# Result

## Implementation status

The repository implementation is complete and frozen pending source-control publication and production rollout.

### Behavior

- Current default: `scoring-v1-preview.8-threshold-059`, threshold `0.59`.
- Historical `.7`: threshold `0.62`, delivered-history v4.
- Historical `.6`: threshold `0.62`, selection-history v3.
- `.8` and `.7` share weights, tiered editorial/product rules, Ministry priority/bypass, penalties, tie-break and seven-day formal-delivery repeat semantics.
- No repository query, database schema, OpenAPI, dependency, provider or delivery behavior changed.
- No historical run is replayed or resent.

### Production planning evidence

Read-only verification before implementation found the three relevant production services on `.7`; `.env` owns exactly one `.7` value and `.release.env` owns zero occurrences. Activation can therefore use a cardinality-checked atomic `.7 → .8` replacement after backup.

## Verification

- Focused topic-selection unit tests: PASS.
- Real PostgreSQL topic-selection/API/delivered-lineage tests: 12 PASS.
- Focused Ruff: PASS.
- Focused strict mypy: PASS.
- `make backend-check`: Ruff format 279 files, Ruff lint PASS, strict mypy 162 source files, backend pytest **974 passed**, coverage 81%.
- `make api-contract-check`: PASS; no production OpenAPI/client drift.
- `docker compose config --quiet`: PASS.
- Trellis task context validation: PASS.
- `git diff --check`: PASS.

## Pending release evidence

- Exact Codeup full SHA and clean candidate image ID.
- Fresh production rollback-set identity and hashes.
- Runtime `.8`/`0.59`, all-eight service health/restart0 and stable counter evidence.
