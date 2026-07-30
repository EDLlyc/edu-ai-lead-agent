# Milestone 1 Runtime and Persistence Contract

Date: 2026-07-29 (Asia/Shanghai)

## Dependency compatibility

Package-index and wheel-metadata inspection selected these exact production pins for Python 3.11:

- `langgraph==1.2.10` (`Requires-Python >=3.10`)
- `langgraph-checkpoint-postgres==3.1.0` (`Requires-Python >=3.10`)
- `psycopg[binary]==3.3.4`
- `psycopg-pool==3.3.1`

`langgraph==1.2.10` requires `langgraph-checkpoint>=4.1.0,<5.0.0`.
`langgraph-checkpoint-postgres==3.1.0` requires the same checkpoint range plus
`psycopg>=3.2.0`, `psycopg-pool>=3.2.0`, and `orjson>=3.11.5`. These constraints are compatible
with Python 3.11 and the project's Pydantic v2 runtime. The normal application database path
continues to use SQLAlchemy async with `asyncpg`; the official LangGraph async saver deliberately
uses a second, explicit psycopg connection path.

## Checkpointer connection and DDL ownership

- SQLAlchemy URL: `postgresql+asyncpg://...`
- LangGraph checkpoint URL: `postgresql://...` or `postgres://...`
- Reusing the asyncpg URL for the saver is rejected by validated settings and the adapter.
- Alembic owns checkpoint schema creation. Runtime code never calls
  `AsyncPostgresSaver.setup()`.
- Migration `20260729_0004` creates the official 3.1.0 checkpoint schema shape:
  `checkpoint_migrations`, `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, the three
  thread indexes, nullable checkpoint blobs, and `task_path`. It records migration versions
  `0..9`, matching the inspected package migration list.
- Checkpoint state is restricted by workflow design to IDs, hashes, versions, statuses, and small
  typed outputs. Full source text, prompts, provider payloads, credentials, and Zhipu
  `reasoning_content` are not checkpoint inputs.

## Zhipu model and fixed-vector contract

The bounded compatibility probe is recorded separately in `zhipu-model-probe.md`. Its selected
quality-first defaults are:

- structured factual analysis: `glm-5.2`
- embeddings: `embedding-3`
- fixed vector dimension: `2048`

The 2048 dimension is encoded in validated settings, the SQLAlchemy `Vector(2048)` mapping, an
explicit database check constraint, and migration column `vector(2048)`. A provider response with
another dimension must be rejected before persistence in the provider milestone. Near-duplicate
and event-assignment vectors remain separate rows by purpose.

## Safe runtime defaults and budgets

- Governance, its scheduler, and its worker default to disabled.
- The acquisition API, scheduler, worker, tables, source scope, and `ai-title-v1` are unchanged.
- Provider mode defaults to `disabled`; Zhipu mode requires a non-blank base URL and `SecretStr`
  API key.
- Settings include bounded concurrency, connect/read/total timeouts, attempts, input/output
  limits, and per-run plus per-day token/cost-unit budgets.
- `.env` remains the only local credential location and is Git-ignored. Research, migrations,
  logs, checkpoints, and tests contain no key.

## Initial vector/index decision

No HNSW or IVFFlat index is created. The initial corpus is small, and the approved design starts
with exact distance over bounded recent windows. An ANN index requires representative volume and
query measurements in a later migration.
