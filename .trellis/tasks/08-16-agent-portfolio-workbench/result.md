# 本地 Agent 求职作品集工作台 — Result

## Status

本地 repository implementation、独立 Phase 2.2 review、回归修复和最终质量门均已完成。该工作台
仍是默认关闭、仅回环可达、无持久化写入的开发者功能；production API、Dockerfile、Compose、
Alembic 与 production OpenAPI 均未接入它。未执行 SSH、部署、provider、企微、enqueue/retry/
resend、commit 或 push。

## Delivered contract

- 四个 typed tools（`search_evidence`、`get_event`、`retrieve_brand_context`、
  `validate_copy`）由单一 immutable registry 同时导出 model schema、MCP registration 和 eval
  snapshot；unknown/invalid/timeout/oversize 均为 typed safe failures。
- LangGraph loop 具有独立的四步、四次 tool call、wall-clock、token 与 output bounds；最终 claims
  只能引用本次成功 evidence tool result 构成的安全 citation catalog。品牌上下文始终
  `evidence_eligible=false`。
- PostgreSQL adapter 使用 transaction-level read-only、既有 governed evidence/copy/event/brand
  seams 和 bounded projections；fixture adapter 支持无 key 的离线 demo。
- MCP 使用 dev-only `mcp==2.0.0` 和 stdio transport；未加入 runtime lock、production API 或
  Compose。
- 独立回环/CORS HTTP app 和独立 OpenAPI/generated TypeScript schema 驱动 trace UI；正常
  production app 不注册 route。production Vite build 即使显式传入 workbench flag 也会 tree-shake
  工作台代码。
- 42 条、六类、脱敏 deterministic cases 生成稳定 JSON/Markdown 报告；当前为 42/42，registry
  schema SHA-256 为
  `6f583f43b11907889a3d3a7fa99636c15cbfb0de80335be1c0723f658ea4acca`。
- 招聘者入口、case study、Mermaid 架构图、示例 trace、面试提纲、简历 bullet 和 fixture-only
  截图位于 `README.md` 与 `docs/portfolio/`。

## Independent Phase 2.2 findings and fixes

- `backend/app/application/services/agent_tools.py`：`validate_copy` 曾用裁剪后的前 32 条 issue
  计算 `accepted`，会隐藏第 33 条及之后的 error。现在 acceptance 基于完整 issue 集合，返回投影
  仍保持 32 条上限；`backend/tests/unit/test_agent_tools.py` 覆盖 32 warnings 后出现 hard error。
- `backend/evals/agent_workbench/metrics.py`：argument-validity 曾从 tool-call step 读取 result code，
  invalid arguments 可能被误计为合法。现在按 `(call_id, tool_name)` 配对 tool result 后计分；
  `backend/tests/unit/test_agent_workbench_eval.py` 覆盖 invalid paired result。
- `backend/app/core/security.py`：citation URL 同步投影只拒绝少数本地域。现在额外拒绝所有已保留/
  明显非公网 suffix 和所有 IP literals；工具单测覆盖 `.test`、`.example`、`.invalid`、`.onion`、
  `.home.arpa` 等输入。
- `backend/app/infrastructure/db/governance_queries.py` 与
  `backend/app/infrastructure/db/copy_generation.py`：移除了错误加入共享 event/copy read 的 current
  membership-policy predicate。生产 `_create_event_projection_version` 的成员快照本来就是全部 active
  memberships；共享 event/copy 读取现在再次遵守该 invariant。
- `backend/app/infrastructure/db/agent_workbench.py`：重复 evidence 的处理仅在 workbench query 加
  SQL `DISTINCT`，bounded event overview 再按 candidate ID 局部去重；未改变共享 copy/event 的
  membership、occurrence 或 evidence 语义。
- `backend/tests/integration/test_event_organization.py` 精确断言 current
  `EventClusterVersion.member_set_hash == stable_key(all active article IDs)`；
  `backend/tests/integration/test_agent_workbench_db.py` 使用不同 membership policy 的 active row
  证明 shared event detail 保留两个 memberships、workbench 只返回一个 candidate、evidence IDs
  唯一、全局 sources 不超过 8、事务只读且 durable counts/session checkout 不变。既有 copy 和
  governance integration regressions 一并通过。

没有遗留的独立 review finding；本次通过 `trellis-update-spec` 新增 backend/frontend Agent
Workbench executable specs，并把共享 registry、本地-only API、有限展示不得改变安全结论、
generated-contract UI 与 production tree-shaking 等约束加入两层 spec index。

## Verification

- `make backend-check`：Ruff format/lint、strict mypy（162 source files）、943 tests 全绿，coverage
  81%。
- `make frontend-check`：production OpenAPI drift、Prettier、ESLint、TypeScript、102 tests 与 Vite
  build 全绿。
- `make agent-portfolio-check`：workbench OpenAPI/generated schema drift、42/42 canonical eval、59
  focused backend tests、66 frontend feature/App tests全绿；canonical report 与 registry hash未漂移。
- 真实 PostgreSQL focused integration：
  `test_agent_workbench_db.py`、`test_event_organization.py`、
  `test_copy_generation_repositories.py` 共 5 tests 全绿。
- 独立 affected static gate：Ruff format/lint 全绿；strict mypy 对 162 source files 无问题。
- `VITE_AGENT_WORKBENCH_ENABLED=true npm run build --prefix frontend` 全绿；`frontend/dist` 中
  `Agent 研究工作台`、`agent-workbench` 与 `/api/v1/agent-workbench` 均无匹配。
- Python lock、52 release-tool tests、full-profile Compose、shell syntax、Doctor、Alembic unique head、
  scoped secret scan 与 `git diff --check` 全绿。独立本地 Uvicorn/CORS/fixture POST E2E 通过且进程已
  停止。
- `backend/Dockerfile`、`compose.yaml`、`backend/app/api_main.py`、`backend/openapi.json` 与
  `backend/alembic/versions/` 无 workbench diff；`mcp` 只存在于 dev dependency/lock。

## Limitations

- 42/42 是离线 deterministic contract/grounding/safety baseline，不是 live model accuracy 或
  provider quality score。
- optional live/local model track 保持显式 opt-in，未在本任务执行；工作台不会发送、发布或改变
  production state。
- DB-backed demo 依赖本地已治理数据；默认五分钟演示使用脱敏 fixture，不需要 provider key。
