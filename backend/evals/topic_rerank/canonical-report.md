# Topic rerank fixture contract conformance

> Provider-free synthetic fixtures verify safety and structure contracts only; this is not evidence of live-model editorial quality or production accuracy.

- Policy: `topic-rerank-v3-layered-auto-finalize`
- Dataset SHA-256: `9905ac5ba1ef4fa6c7da790a67317a3458a7b2f1fcda616fb8844bbd30752288`
- Result: 8/8 passing
- Volatile latency and token counts are intentionally excluded.

| Case | Context | Scenario | Outcome | Candidates | Pass |
| --- | --- | --- | --- | ---: | --- |
| `daily-reorder` | `daily` | `reorder` | `applied` | 2 | yes |
| `evening-reorder` | `evening` | `reorder` | `applied` | 2 | yes |
| `hard-veto-excluded` | `daily` | `hard_veto` | `applied` | 2 | yes |
| `morning-reorder` | `morning` | `reorder` | `applied` | 2 | yes |
| `noon-reorder` | `noon` | `reorder` | `applied` | 2 | yes |
| `priority-barrier` | `daily` | `priority` | `applied` | 2 | yes |
| `provider-fallback` | `daily` | `fallback` | `fallback` | 2 | yes |
| `same-day-excluded` | `noon` | `same_day` | `applied` | 2 | yes |

These checked fixtures demonstrate bounded permutations, hard-rule exclusion, priority barriers, daily/slot sharing, and deterministic fallback only.
