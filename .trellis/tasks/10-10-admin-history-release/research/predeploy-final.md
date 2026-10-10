cd backend &&  python -m evals.gate.runner
# Pre-deploy gate: PASS

- Commit: `0a68c7d+dirty`
- Started: 2026-10-10T05:32:49+00:00

| Step | Result | Seconds | Detail |
|---|---|---|---|
| `topic_golden` | passed | 0.8 | - |
| `same_topic_golden` | passed | 0.1 | - |
| `topic_rerank` | passed | 0.4 | - |
| `brand_retrieval` | passed | 0.1 | - |
| `agent_workbench` | passed | 2.0 | - |
| `image_quality` | passed | 0.1 | - |
| `ip_asset_retrieval` | passed | 0.2 | - |
| `visual_retrieval` | passed | 0.1 | - |
| `ip_asset_grounded_seed` | passed | 1.3 | - |
| `ip_asset_grounded_authoring` | skipped | 0.7 | needs the private visual asset manifest |
| `unit_and_contract_tests` | passed | 296.6 | 0 known failure(s), no new failure |

predeploy gate PASS @ 0a68c7d+dirty: 10 passed, 0 failed, 1 skipped (2026-10-10T05:32:49+00:00)
