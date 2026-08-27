# 公众号本地自动化与视觉优化 V2：实施计划

## Phase 0 — protection and baselines

- [x] Read task artifacts and backend/frontend/gzh specs; inspect `git status` and focused diffs before every
      high-collision edit.
- [x] Freeze V1 constants, golden hashes and current focused-test baseline; record that default external calls are 0.
- [x] Inventory existing media quality projections and choose the smallest fail-closed V2 gate without schema/migration.

## Phase 1 — V2 domain

- [x] Add explicit V2 identity/models for release, recipe, semantic emphasis, context block placement, content/artifact
      fingerprints and mobile binding. Leave V1 definitions/dispatch unchanged.
- [x] Implement deterministic semantic span selection and exact text round-trip tests.
- [x] Implement context-to-block scoring/fallback/collision spacing and tests for body+context interleaving.
- [x] Implement Xiaosai recipe selection, title/TOC length bands and callout variants using only allowlisted inline CSS.
- [x] Extend V2 preflight for release truth, placement validity, image separation, emphasis bounds and mobile binding.

## Phase 2 — application and artifact

- [x] Add injected release policy with `manual_only` compatibility and `quality_auto` machine release; manual rejection
      wins. Reuse durable validation/audit/media states and construct no provider clients.
- [x] Build V2 body/release/placement/theme/preflight/manifest and deterministic ZIP around content/artifact identity.
- [x] Support canonical runtime `not_run` and exact passed-report local export without fingerprint circularity.
- [x] Add offline application tests for gate matrix, determinism, tamper failure, ZIP safety and zero external clients.

## Phase 3 — API/OpenAPI/workbench

- [x] Inspect overlapping diffs, then minimally extend settings, schema, route and capabilities.
- [x] Regenerate OpenAPI/types; map only generated wire types into release/recipe/placement/mobile view models.
- [x] Update handoff UI and clipboard fallback/status copy; keep sandbox, accessibility and no-publish boundary.
- [x] Add API/mapper/component tests for automatic release, manual rejection, context placement and mobile identity.

## Phase 4 — news fixture, browser acceptance and export

- [x] Add deterministic local news fixture with >=3 body, >=1 context and 1 cover; preserve source/credit/rights warning.
- [x] Update Playwright to verify exact content/body/media hashes, order, image loading, 320/430 overflow and 0 external
      requests.
- [x] Produce a new non-overwriting local V2 export whose ZIP contains the passed fingerprint-bound report.
- [x] Run the installed gzh validator on final clean HTML to 0 ERROR/0 WARNING.

## Phase 5 — documentation and checks

- [x] Update English backend/frontend specs and operator docs for release policy, placement, recipes, report identity and
      permanent local/no-publish behavior.
- [x] Run focused Ruff format/lint, mypy, pytest, historical official-account regressions, API generation/drift,
      frontend format/lint/typecheck/Vitest/build, Playwright, Compose config where touched, and `git diff --check`.
- [x] Dispatch Trellis check agent, repair verified findings and rerun affected focused gates.
- [x] Report exact files/results/output path/external call count. Do not commit unless the user separately asks.

## Validation commands

```bash
conda run --name edu-ai python -m ruff format --check <affected-python-files>
conda run --name edu-ai python -m ruff check <affected-python-files>
conda run --name edu-ai python -m mypy <affected-domain-and-application-files>
conda run --name edu-ai pytest backend/tests/unit/test_official_account_editor_handoff.py \
  backend/tests/unit/test_official_account_local_api.py -q
make api-generate
make api-contract-check
npm run test --prefix frontend -- --run src/features/official-account-local
npm run lint --prefix frontend
npm run typecheck --prefix frontend
npm run build --prefix frontend
npm run test:e2e --prefix frontend -- --grep "editor handoff"
python /root/.codex/skills/gzh-design/scripts/validate_gzh_html.py <clean-v2-body.html>
git diff --check
```

## Risky files and rollback points

- High collision: `.env.example`, `compose.yaml`, backend config/route/schema, `backend/openapi.json`, generated TypeScript,
  official-account Panel/api/hooks, README and Trellis specs. Inspect scoped diff first and never rewrite whole files.
- Prefer new V2 modules/tests and narrow wiring. No migration/repository/worker changes are expected.
- Rollback is release policy `manual_only`/V2 flag off; V1 remains intact.

## Pre-start gate

- [x] PRD/design/implement agree on additive V2, machine release truth and zero-WeChat boundary.
- [x] `implement.jsonl` and `check.jsonl` contain real spec/research entries.
- [x] `task.py validate` passes.
- [x] User approves the final planning summary after these artifacts are presented.
