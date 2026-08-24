# Implementation Plan

1. [x] Add visual embedding/ranking domain contracts, canonical query v1 and selector v2 while freezing
       selector v1 snapshots and all hard eligibility barriers.
2. [x] Add dedicated application ports/services for image indexing, text/image query embedding, compatible
       complete-catalog retrieval and typed v1 fallback.
3. [x] Add the bounded Alibaba `qwen3-vl-embedding` adapter with exact 2048-dimensional validation,
       SecretStr settings, provider-free defaults and contract fakes.
4. [x] Add migration `20260821_0024`, SQLAlchemy models and repositories for lease-safe jobs, immutable asset
       vectors, complete-index proof and cosine retrieval; update migration compatibility declarations.
5. [x] Add the explicit local index CLI and safe aggregate diagnostics. Do not read provider-export CSV from
       application code or start indexing automatically.
6. [x] Wire semantic retrieval before material-package selection; persist safe ranking/fallback metadata and
       preserve exact v1 behavior when disabled or unavailable.
7. [x] Add the bounded internal visual-search schema/route and regenerate production OpenAPI/frontend types;
       do not add arbitrary URL input or expose files/vectors/provider fields.
8. [x] Add deterministic visual-retrieval eval fixtures/reports plus domain, adapter, application, API, CLI,
       real-PostgreSQL, migration/downgrade and privacy tests.
9. [x] Update `.env.example`, Compose, Doctor and backend brand/visual/database/error/logging/quality specs.
10. [x] Run Ruff, strict mypy, focused/full backend tests, eval drift, Alembic/API/Compose/Doctor/release,
        `git diff --check` and scoped secret/private-path scans.
11. [x] Run an independent Trellis check and fix verified findings without touching unrelated dirty changes.
12. [x] After code/check gates are green, perform the separately approved protected local 41-asset indexing
        run with one attempt per asset, no raw retention, and aggregate-only retrieval acceptance; do not
        deploy, replay business, send, commit or push unless separately requested.
13. [x] Add immutable image-input policy v2, deterministic bounded PNG normalization, truthful source/input hashes,
        migration `20260821_0025`, v1/v2 isolation and regression/eval/spec coverage.
14. [x] Run focused normalization/provider/repository/material/API tests, real PostgreSQL migration/retrieval tests,
        independent Trellis review and one final full gate after the last production edit.
15. [x] Perform the newly authorized complete 41-asset v2 index with one request per derivation, aggregate-only
        diagnostics and no automatic retry; enable local semantic selection only after exact 41/41 coverage and
        a bounded text-query acceptance check.

The main session created a protected PostgreSQL backup, applied the already-tested additive `0023` and `0024`
migrations while no application process was running, and reran Doctor successfully at the single `0024` head.
The one authorized live indexing execution then attempted all 41 approved assets exactly once: 36 produced
ready vectors and 5 ended with the typed `provider_unavailable` code. The incomplete catalog therefore failed
the complete-index proof and remains on deterministic selector-v1 fallback. A separately authorized retry skipped
the 36 ready rows and retried only the same five derivations; all five remained provider-unavailable. Aggregate
diagnosis binds the failures to Base64 request bodies above 10 MiB. A future normalized input-policy version and
complete fresh-catalog reindex were subsequently authorized and are tracked in steps 13--15.

Steps 13--14 passed implementation and independent review. The main session then captured a second protected
database backup, applied `0025`, required a green Doctor, proved all 41 private assets normalize below the fixed
v2 bound, and performed exactly one v2 catalog run. All 41 v2 derivations succeeded on their first attempt. One
bounded synthetic text query returned a complete 41-item score map before the local private `.env` was atomically
switched to semantic enabled / Alibaba / input-policy v2. Historical v1 rows remain isolated and unused.

## Risky seams and rollback points

- `domain/visual_assets.py`: keep v1 literal and make all eligibility gates precede semantic ranking.
- `application/services/material_package.py`: provider work must remain outside transactions and fallback
  must not alter existing prompt/reference snapshots beyond new versioned safe fields.
- New pgvector rows must never mix with `brand_chunk_embeddings`; all queries require exact derivation scope.
- The live catalog contains private images. Only the final explicitly approved bounded operator may send the
  41 approved PNGs, and it must not retain provider bodies, request IDs or raw vectors outside PostgreSQL.
- Rollback is feature flag off + selector v1; no existing data migration or destructive restore is needed.

## Planned validation commands

```bash
conda run --name edu-ai ruff format --check backend/app backend/tests
conda run --name edu-ai ruff check backend/app backend/tests
make backend-typecheck
conda run --name edu-ai pytest -q backend/tests/unit/test_visual_assets.py \
  backend/tests/unit/test_material_package.py backend/tests/contract/test_brand_visual_embedding.py --no-cov
conda run --name edu-ai pytest -q backend/tests/integration/test_brand_visual_retrieval.py \
  backend/tests/integration/test_migrations.py backend/tests/integration/test_governance_migration_downgrade.py --no-cov
make backend-check
make api-contract-check
docker compose config --quiet
make doctor
```
