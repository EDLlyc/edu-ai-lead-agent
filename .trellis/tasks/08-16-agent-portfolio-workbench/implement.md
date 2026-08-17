# 本地 Agent 求职作品集工作台 — Implementation Plan

## Execution boundary

- 本任务仅在共享工作区和本地测试环境实施。
- 不连接生产服务器，不执行 SSH、部署、企微、业务 enqueue/retry/resend 或付费 provider 调用。
- 不 commit/push；只有用户后续明确授权才可改变此边界。
- 不修改现有生产 feature flags，不新增 Compose 长驻服务，不新增 Alembic migration。
- 保留工作树中其他任务和用户已有修改；不得还原或重写
  `.agents/skills/trellis-break-loop/SKILL.md`、`08-15-zhipu-ocr-provider-rejection/**` 或
  `reports/**`。

## Phase 0 — Contract and baseline

- [x] 0.1 记录当前 git status 与相关 backend/frontend/API/lock baseline；只读确认现有 Agent、
  evidence、event、brand RAG、copy validator 和 preview UI 复用点。
- [x] 0.2 按官方 MCP Python SDK v2 契约固定 `mcp==2.0.0` 与 stdio API；只放入本地/dev
  dependency 与 hash lock，不导入生产 API 入口。
- [x] 0.3 冻结四个 tool 名称、参数/结果、timeout/output cap、citation/brand boundary、四步预算
  和 trace allowlist；先写 failing contract tests。
- [x] 0.4 建立至少 40 个版本化脱敏 eval cases 的 schema、分类与 deterministic oracle；确认
  无私有品牌正文、完整文章、凭据或生产 ID。

## Phase 1 — Shared tool registry and read-only adapters

- [x] 1.1 新增 provider-independent Agent status、budget、citation、trace 和 tool result value
  objects；domain 层不导入 FastAPI、SQLAlchemy、MCP 或 provider SDK。
- [x] 1.2 新增 `AgentKnowledgeReader`/`ToolCallingModel` 等 application ports，并为本地演示实现
  deterministic fixture reader。
- [x] 1.3 从现有 copy-generation evidence query 提升共享的 governed-evidence read boundary；
  `search_evidence` 只返回 validated Tier A/B binding、短 quote、event/source IDs 和 HTTPS URL。
- [x] 1.4 `get_event` 复用 `governance_queries.get_event_detail` 及既有投影；工具输出按模型上下文
  需要裁剪，禁止直接序列化 ORM 或无限成员列表。
- [x] 1.5 `retrieve_brand_context` 复用通用 brand service/repository；所有结果保留
  `evidence_eligible=false`，provider/model 不匹配时 typed unavailable，不暗中混用向量。
- [x] 1.6 `validate_copy` 直接复用 `validate_material_draft`。如需让 production context 与本地
  validation context 共用，将输入收窄为结构化 Protocol，不复制规则、不伪造 durable state。
- [x] 1.7 建立 immutable `TypedToolRegistry`，统一导出模型 JSON Schema、MCP registration 与
  eval snapshot；拒绝 duplicate/unknown tools、invalid args、oversized results 和 handler timeout。
- [x] 1.8 focused unit/integration tests 覆盖四工具、只读 DB 行为、brand/evidence 隔离、session
  生命周期和 no-side-effect assertions。

## Phase 2 — Bounded LangGraph Function Calling loop

- [x] 2.1 实现 typed state graph：`model_decision -> tool_execution -> model_decision | terminal`；
  LangGraph recursion limit 之外再显式执行 `steps<=4`、`tool_calls<=4`、wall-clock/token/output
  guard。
- [x] 2.2 实现 recorded adapter 仅供 focused protocol tests；另实现一套固定 offline policy
  adapter 供 no-key demo/eval。两者都不能读取 eval expected tools/citations/outcome；报告不得把
  recorded replay 分数表述为模型质量。
- [x] 2.3 实现 OpenAI-compatible tools adapter；使用 MockTransport 验证 request schema、tool call
  ID/name/arguments、usage、finish reason、malformed/duplicate/oversized response 与安全错误投影。
- [x] 2.4 最终答案使用 bounded summary + `claims[{text,kind,citation_ids}]`；runner 从本次成功
  tool results 构建唯一安全 citation catalog，移除/拒绝 unattached、invented 或 kind mismatch
  条目；禁止 brand chunk 充当事实证据，不足时返回 refused/insufficient_evidence。
- [x] 2.5 构建 redacted trace：action/observation、工具、safe args summary、counts/citations、duration、
  usage；测试证明不存在 chain-of-thought、full prompts、provider bodies、secret/private paths。
- [x] 2.6 focused Ruff、strict mypy 与 graph/adapter/trace tests 全绿后冻结 core contract。

## Phase 3 — MCP and deterministic eval

- [x] 3.1 用官方 MCP Python SDK 当前稳定 API 新增 stdio-only entry point；由 shared registry
  动态注册四工具，不开 HTTP/SSE、不接入 `api_main`/Compose。
- [x] 3.2 官方 in-memory/stdio client contract tests 覆盖 discovery/list/call/lifecycle、canonical
  schema 规范化语义 parity、invalid args、unknown tool、timeout/error 和 stderr-only safe logging。
- [x] 3.3 实现 JSONL dataset loader、case validator 和 deterministic graders；不以 exact answer
  字符串或 LLM judge 作为唯一 oracle。
- [x] 3.4 输出 canonical stable JSON/Markdown report，包含总分、分类指标、失败 case IDs 和
  registry schema hash；稳定报告排除 timestamp/random run ID/wall-clock/token 等动态字段，后者
  只进入 ignored runtime diagnostics；添加 deterministic drift test。
- [x] 3.5 提供 `make agent-eval` 与 `make agent-portfolio-check`（或符合 Makefile 规范的等价名称）；
  默认路径断言 provider/network call=0。
- [x] 3.6 optional live/local track 必须显式 opt-in，输出到 ignored 目录并标注
  non-authoritative；本任务不运行该 track。

## Phase 4 — Local-only HTTP vertical slice

- [x] 4.1 新增 Settings：workbench 默认 false，production+true fail at startup，provider/data
  mode/limits 只能从 allowlist 选择；同步 `.env.example` 与配置测试，但不改生产 `.env`。
- [x] 4.2 新增独立 `agent_workbench_api_main.py`、HTTP schemas 与 dependency wiring；正常
  `api_main`/Dockerfile/Compose 不注册 route。Make launcher硬编码127.0.0.1，request gate基于真实
  socket peer拒绝非回环，并拒绝任何Forwarded/X-Forwarded-* headers。
- [x] 4.3 `POST /api/v1/agent-workbench/runs` 只调用 application service，返回 ephemeral typed
  result与安全citation catalog，不持久化 run/steps。
- [x] 4.4 API tests 覆盖 normal app route absent、disabled、local fake success/refusal/budget/tool
  error、production rejection、non-loopback/forwarding spoof、request/output limits、cancel 和 safe
  error envelope。
- [x] 4.5 独立生成并检查 workbench OpenAPI/frontend schema；不得手写重复 response types，现有
  production OpenAPI保持不变。
- [x] 4.6 运行 focused API/integration gates，证明无 Alembic head/schema drift、无业务表写入。

## Phase 5 — Trace UI and recruiter experience

- [x] 5.1 新建 `features/agent-workbench` API mapper/hook/components；接入现有 App 导航/布局，不
  把 fetch、mapping 和 rendering 堆进单一组件。
- [x] 5.2 UI 支持预设和 bounded query、idle/running/completed/refused/budget/failed states、答案、
  citations、trace timeline、tool/latency/token metrics。
- [x] 5.3 所有 source/model 内容按 text 渲染；外链仅 validated HTTPS；键盘、focus、aria-live、
  heading/status non-color coverage 全部通过；页面无 send/publish/production controls。
- [x] 5.4 mapper/component tests 覆盖 historical/optional usage、safe unknown codes、stale response、
  cancellation、malicious text 和 accessibility。
- [x] 5.5 生成一张只含 fixture 数据的本地截图，检查无 secret/private identifiers 后放入
  `docs/portfolio/assets/`。

## Phase 6 — Portfolio documentation

- [x] 6.1 README 增加招聘者入口，说明 5 分钟运行路径和不需要 provider key 的默认 demo。
- [x] 6.2 新增 case study：问题、架构、共享 registry、LangGraph bounded loop、MCP、eval、Trace、
  安全边界、量化结果、取舍与 deferred work。
- [x] 6.3 提供 Mermaid 架构图、示例 trace、deterministic eval report 和面试讲解提纲；所有
  数字可由命令复现。
- [x] 6.4 起草 2–3 条简历 bullet，但只引用最终实测数据；明确 deterministic contract score
  不是 live model accuracy。

## Phase 7 — Quality gates and independent review

- [x] 7.1 Focused: registry/tools/graph/adapter/MCP/eval/API/frontend feature tests、Ruff、strict
  mypy、TypeScript、ESLint、Prettier、a11y 与 report drift 全绿。
- [x] 7.2 Full once after code freeze: `make python-lock-check`, `make backend-check`,
  `make frontend-check`, `make release-tool-check`, full-profile Compose config、Doctor compatibility、
  shell syntax、`git diff --check` 和 scoped secret scan。
- [x] 7.3 Drift proof: OpenAPI/generated frontend/Alembic unique head/dependency locks exact；Compose
  production services、delivery/image/news entry points unchanged。
- [x] 7.4 Dispatch independent `trellis-check` review using curated `check.jsonl`; resolve concrete
  findings, rerun affected focused gates, then repeat final full gates only if production code changed。
- [x] 7.5 Final result lists changed files, commands/results, eval metrics, screenshots/docs, limitations
  and explicit proof of no server/deploy/provider/WeCom/commit/push actions.

## Suggested implementation ownership after approval

1. Backend core worker owns domain/ports/registry/read adapters/LangGraph/model adapter and backend tests.
2. MCP/eval worker starts only after the registry contract freezes and owns MCP entrypoint, eval dataset,
   reports, Make targets and related tests.
3. Frontend worker starts after HTTP/OpenAPI schema freezes and owns the feature UI/tests/screenshot.
4. Main agent owns dependency locks, cross-layer integration, portfolio docs and final orchestration.
5. Independent checker owns spec compliance, security/privacy, schema parity, full gates and self-fixes.

Workers are not alone in the codebase: each must preserve concurrent changes, avoid reverting another
owner's edits and coordinate shared files (`pyproject.toml`, lock files, `Makefile`, `api_main.py`,
`App.tsx`, generated OpenAPI) through the main agent.
