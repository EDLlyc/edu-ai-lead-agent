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

## Codeup and candidate

- Codeup application release: `572636aa6cca973676abfe99ee7e7e0b4d997c59`.
- Candidate image: `sha256:d0bc989463989c0d040f7b17d5d583f1369a59e105622db7911eac380ab7a992`.
- Candidate image bundle SHA-256: `4f9247a4b95faaeed85e56aa04ce6aad350c013d41b97c3b809fd2dc409c87cd`.
- Eight-file source delta archive SHA-256: `0457bf612770c5dae9fad8e18588356c52825451387a6ff2124c132627229e56`.
- Final operator SHA-256: `9639c455d12d9bc1b05c37a1ba7f8a273ac3d8dead06156efcd6636036e82ebd`.

The candidate was built from a clean detached Codeup worktree on the exact active production image
without network access. Linux/amd64, non-root user, RootFS-base prefix, labels, installed packages,
all eight imports, absent runtime MCP dependency, OpenAPI, unique Alembic head, exact 179-file image
manifest, literal `.7`/0.62 and current `.8`/0.59 contracts all passed.

## Production activation — succeeded

The read-only preflight proved all eight prior services on exact image
`sha256:886e6e212bfe2a6a21c3a2bd5826b7283f5d5fb76c2949201861d15892fa8f99`,
running/restart0, with `.env` as the single `.7` owner and no `.release.env` override. Seven old
queued copy runs were historical; the current business date was `0 queued / 0 running / 1 accepted`,
so they were not claimable by the current-date worker.

The first invocation created backup `20260818T014831Z-threshold-059` and then stopped before the
first service stop because Git archive parent-directory entries were stricter than the file-only
path-set assertion. Phase state was pre-mutation: active tags, source, environment, markers and all
services remained prior. The retained root-owned mode-0700 backup checksum-manifest SHA-256 is
`4e27a0d8d4ec7a5486bface5db95e5a977132e89c3ea9c0bf1dc4546b009a152`.

The corrected operator ignored signed directory entries while still requiring the exact eight
regular files. It created the fresh successful rollback set
`20260818T014933Z-threshold-059`; checksum-manifest SHA-256
`a9b2d719fe2d640adb3b7d67f9e55eeb3ad9068ee9b95b24f6e5be59efd88a89`.
It then stopped the eight services in writer-safe order, retagged the verified candidate, installed
the exact source delta, atomically changed `.env` from `.7` to `.8`, preserved Alembic head
`20260815_0021`, and restored API first / dispatcher last.

Final independent evidence:

- all eight services run candidate `d0bc989…`, status `running`, restart count 0;
- API health is `healthy`;
- full marker is exact `572636aa6cca973676abfe99ee7e7e0b4d997c59`;
- `.env` contains exactly one `.8`; `.release.env` contains zero scoring-version keys;
- acquisition API, content scheduler and content worker each resolve
  `.8|0.59|topic-veto-v4-delivered-content`;
- pre/post durable vector stayed
  `41:322:41:624:9:12:65:41:51:41:439:26:51` and all seven current actionable counters stayed 0;
- severe log scan across all eight services returned 0;
- no provider call, enqueue, historical replay, retry, resend or WeCom send was performed by the release.
