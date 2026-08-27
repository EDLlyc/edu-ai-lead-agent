# Implementation Plan: IP 资产演示加固

1. Add deterministic thumbnail types/encoder, repository/store derivative persistence, service access checks, route, response field and backend unit/integration tests.
2. Regenerate backend OpenAPI and frontend generated schema, then update frontend mappers/fixtures to consume `thumbnail_url` without changing original/private media behavior.
3. Reduce gallery/personal page size to 16 and search result size to 8; remove numeric similarity presentation and add honest semantic-lineage wording plus example search prompts.
4. Improve gallery selection text feedback and mobile gallery-first ordering.
5. Move flipbook controls into the preview stage and extend component/CSS regression tests for placement, keyboard and reduced-motion behavior.
6. Add one-click demo profile bootstrap and creation example brief with focused accessibility and no-auto-submit tests.
7. Add the read-only demo preflight command, Make target and local runbook instructions; test failure/success parsing without live provider calls.
8. Run focused backend/frontend tests, OpenAPI drift, lint, strict types, format, build, `git diff --check`, then real Chromium desktop/mobile smoke with request-size and mutation checks.

## Validation Commands

```bash
conda run --name edu-ai pytest \
  backend/tests/unit/test_ip_assets.py \
  backend/tests/integration/test_ip_assets.py --no-cov -q
make api-generate
make api-contract-check
npm run test --prefix frontend -- --run src/features/ip-assets
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm run format:check --prefix frontend
npm run build --prefix frontend
make ip-asset-demo-preflight
git diff --check
```

## Risky files and rollback points

- `backend/app/infrastructure/storage/minio_ip_asset_store.py`: original and derivative key validation must remain exact and content verified.
- `backend/app/infrastructure/db/ip_assets.py`: concurrent derivative creation must not leave an object row mismatch.
- `backend/app/api/v1/routes/ip_assets.py` and generated OpenAPI: card contract changes must propagate atomically.
- `frontend/src/features/ip-assets/IpAssetHub.tsx`: search, selection and thumbnail projection share card rendering and require broad focused tests.
- `frontend/src/features/ip-assets/IpAssetFlipbookRenderer.*`: overlay controls must not intercept drag gestures over the book.
- `scripts/ip_asset_demo_preflight.py`: checks must remain read-only and safe when services are absent.
