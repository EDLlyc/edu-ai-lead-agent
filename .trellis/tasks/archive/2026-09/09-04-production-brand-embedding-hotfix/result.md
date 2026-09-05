# Production result

Completed on 2026-09-05 (Asia/Shanghai).

## Delivered

- Main hotfix authority: `e43ccc368638a35f51dd0b28e734b868336bca5b`.
- Final main release tooling: `d92ff12314fc27eeb34086012977ac616ddbfa6a`.
- Activated release commit: `5c560da71bcbb61b765d3fe82c742cf2d5e676e1`.
- Activated image: `edu-ai-lead-agent-backend@sha256:35e4405a5dfa06e70a45c360d8838021e00c05938ac7f7e818378c6454d48454`.
- Codeup and GitHub `main` plus `release/brand-embedding-hotfix-20260904` were pushed without force.
- Production backup completed as `20260905T100525Z` before migration and activation.

## Acceptance evidence

- Release marker, legacy marker, OCI revision, and immutable RepoDigest agree with the activated
  release.
- PostgreSQL, MinIO, API, and all 12 application services converged; all 14 services were running
  with restart count zero.
- Alembic remained at the reviewed head `20260901_0042`.
- Production brand-delivery Compose validation passed with resolved identity
  `zhipu/embedding-3/2048`.
- `brand_chunk_embeddings.vector` is `vector(2048)`; the read-only aggregate observed 120 rows,
  including 113 rows with `zhipu/embedding-3/2048` identity.
- One fixed non-private, in-memory provider smoke returned
  `{"success":true,"provider":"zhipu","model":"embedding-3","dimensions":2048}`.
- Before/after/post-smoke captures proved protected `.env` bytes and identity, the seven-job frozen
  cohort (`657797a7d4b8d51c8355c07c62343610529fc85753ecb7b489dcd2ef3c5dc74c`), service identity,
  and every protected database/WeCom effect counter were unchanged.
- No historical job was replayed, updated, deleted, or sent. At activation, current-day, future,
  claimable, and running copy gates were all zero; the historical provider-unavailable terminal
  count remained 30.
- Task-local release harness passed 219 tests; `deploy/release` passed 70 tests; Ruff, formatting,
  Mypy, shell syntax, Trellis validation, and scoped diff checks passed.

## Operational notes

- Two failed candidates stopped before quiescence or activation. Their failures exposed Compose
  build-metadata and source-mode preflight gaps; both classes now fail before one-shot consumption,
  with executable regressions and a recorded break-loop analysis.
- The full host development `doctor.sh` stops immediately because the production host intentionally
  has no Node command. Production-specific Compose validation, database vector checks, service
  health capture, and the live embedding smoke passed instead; no package was installed on the host.
- This release restores future naturally scheduled brand retrieval/copy work. It deliberately does
  not claim that a news item was sent during deployment.
