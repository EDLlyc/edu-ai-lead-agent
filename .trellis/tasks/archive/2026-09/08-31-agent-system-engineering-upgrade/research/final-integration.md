# Final integration evidence

## Child delivery

- IP retrieval V3 shipped in `fd8d611` and was archived in `60d50f3`.
- Shared execution governance shipped in `19fe3ec` and was archived in `38e6a3d`.
- Official-account V2 weekly automation and the default-disabled draft adapter shipped in `f79d846`.
- The durable weekly DAG shipped in `f41a032` and was archived in `5e1e465`.

## Contract and privacy result

- Retrieval telemetry persists only anonymous daily aggregates; raw queries, profile/asset identities,
  session data, IP addresses, user agents, and per-event behavior are outside the schema.
- The weekly DAG consumes the shared governed run, capability, budget reservation/allocation, causal
  trace, and artifact contracts. Node attempts retain exact lineage without article bodies, prompts,
  provider responses, credentials, or private object paths.
- The static graph keeps three article-role branches independent, resumes from durable checkpoints,
  fences stale workers, retries only eligible affected nodes, and reuses the immutable weekly
  aggregate boundary.
- WeChat draft staging remains a separate, default-disabled development adapter. The DAG does not
  construct it and performs no publish, mass-send, pin, login, or browser-automation action.

## Verification result

- Alembic remains single-headed at `20260831_0040`; upgrade/downgrade and migration compatibility
  checks passed on the task-owned migration matrix.
- Weekly DAG unit/integration/migration tests passed 14/14; weekly V1/V2/live, draft-adapter, and
  execution-governance coverage passed 90/90, for 104/104 affected tests.
- The complete backend run passed 1755 tests. The remaining 27 failures are confined to unrelated
  in-progress topic-rerank/Zhipu configuration work and were not staged in these commits.
- Full Ruff lint passed. Focused formatting, typing, Compose, Docker worker, CLI, Doctor contract,
  release contract, OpenAPI/frontend, privacy, and `git diff --check` gates passed for the owned
  changes. Existing unrelated worktree edits were preserved and left unstaged.
