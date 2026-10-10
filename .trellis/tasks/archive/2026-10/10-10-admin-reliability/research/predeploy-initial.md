cd backend &&  python -m evals.gate.runner
# Pre-deploy gate: FAIL

- Commit: `97ece80+dirty`
- Started: 2026-10-10T02:52:17+00:00

| Step | Result | Seconds | Detail |
|---|---|---|---|
| `topic_golden` | passed | 1.3 | - |
| `same_topic_golden` | passed | 0.1 | - |
| `topic_rerank` | passed | 0.6 | - |
| `brand_retrieval` | passed | 0.2 | - |
| `agent_workbench` | passed | 6.6 | - |
| `image_quality` | passed | 0.3 | - |
| `ip_asset_retrieval` | passed | 0.3 | - |
| `visual_retrieval` | passed | 0.2 | - |
| `ip_asset_grounded_seed` | passed | 1.7 | - |
| `ip_asset_grounded_authoring` | skipped | 0.8 | needs the private visual asset manifest |
| `unit_and_contract_tests` | failed | 329.9 | 1 new failure(s): backend/tests/unit/test_brand_embedding_zhipu.py::test_api_lifespan_owns_and_closes_dedicated_zhipu_brand_client |

## New test failures

- `backend/tests/unit/test_brand_embedding_zhipu.py::test_api_lifespan_owns_and_closes_dedicated_zhipu_brand_client`

predeploy gate FAIL @ 97ece80+dirty: 9 passed, 1 failed, 1 skipped (2026-10-10T02:52:17+00:00)
make: *** [Makefile:197: predeploy-check] Error 1
