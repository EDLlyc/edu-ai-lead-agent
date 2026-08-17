# 本地 Agent 求职作品集工作台

## Goal

在现有教育科技内容系统上增加一个默认关闭、只允许本地开发环境启用的 Agent
Research Workbench。它用同一套强类型只读工具同时支持 bounded Function Calling 和 MCP，
提供可复现评测、无思维链泄露的执行轨迹 UI，以及面向 Agent 应用开发实习的作品集说明。

本任务的价值不是再增加一条业务自动化，而是把仓库已有的 RAG、LangGraph、证据治理、
确定性校验、OpenAPI 和可观测性能力，组织成招聘者可在本地理解、运行和验证的 Agent
工程闭环。

## Background and confirmed facts

- 仓库已经具备 PostgreSQL/pgvector、品牌 hybrid RAG、LangGraph 治理图、结构化模型适配、
  证据绑定、确定性校验、token/latency 记录、OpenAPI 生成和 React 审计页面。
- 当前没有共享 Agent tool registry、标准 Function Calling loop、MCP server、独立 Agent eval
  dataset/report 或端到端 Agent trace 页面；现有模型调用属于固定业务编排，不能把它们包装成
  已实现的通用 Agent 能力。
- `list_candidates` 只是按时间分页，不能冒充语义 `search_evidence`；真正的事实资格边界在
  `EligibleEvidence` 和 copy-generation 的 EventVersion -> validated Tier A/B binding 查询中。
- 现有 `get_event_detail`、通用 `retrieve_brand_context` 与纯
  `validate_material_draft` 可以成为三个工具的复用边界；Workbench trace 不适合塞进带强 FK
  的既有 model/copy attempt 表，因此 MVP 可不做 migration。
- 2026 年公开 Agent 应用/平台实习要求反复出现 RAG、Prompt、LangChain、Function Calling、
  MCP、工具/Skill、上下文管理、评测和可观测性。本任务优先补齐仓库最明显且可演示的后三类
  缺口，而不是重复已经很强的业务流水线。

## User and demo scenarios

1. 面试官在本地选择一个受控问题，例如“这条 AI 教育事件有哪些可靠证据，适合怎样向
   家长解释？”，观察 Agent 在最多四步内选择只读工具、引用证据并给出有界答案。
2. 开发者通过 MCP stdio client 枚举并调用与 Workbench Agent 完全相同的工具，确认没有
   第二套业务逻辑或第二套 JSON Schema。
3. 开发者运行离线评测命令，得到工具选择、参数合法性、引用正确性、拒答、安全边界、
   步数、延迟和 token 使用的 JSON/Markdown 报告。
4. 面试官在 Trace 页面查看 action/observation 时间线、引用与指标；页面不展示模型隐藏
   推理、完整 prompt、原始 provider body、密钥或私有对象位置。

## Requirements

### 1. Shared typed tool boundary

- 建立唯一的 typed tool registry；工具名、描述、Pydantic 参数、结构化结果、超时与输出
  上限均由该 registry 控制。
- MVP 暴露四个只读工具：
  - `search_evidence`：检索已治理的事实证据，返回稳定 evidence/event/source 标识和短引用；
  - `get_event`：读取一个事件的受控聚合详情与来源概览；
  - `retrieve_brand_context`：读取品牌表达上下文，结果始终标记
    `evidence_eligible=false`；
  - `validate_copy`：调用现有确定性文案/证据边界，返回 typed issue codes，不执行修复或写入。
- 工具不得抓取任意 URL、执行 shell/代码、访问任意文件、写数据库、生成图片、投递企微、
  enqueue/retry/resend，或接受未注册工具名。
- 现有 repository/service/domain 逻辑是业务规则的单一来源；Agent 与 MCP 只能通过适配层
  复用，不能复制检索、品牌边界或校验规则。

### 2. Bounded Function Calling Agent

- application service 驱动 provider-neutral tool-calling loop；模型适配器只能返回
  `final_answer` 或结构化 tool calls。
- loop 使用自定义 typed LangGraph `model -> execute one tool -> model | terminal`，不使用
  prebuilt autonomous agent。Graph recursion limit 只是最后防线；四步/四调用/总时限由业务状态
  显式控制。MVP 不接 checkpointer，不持久化会话记忆。
- 每次运行最多 4 个模型步骤、4 次工具调用；每个工具和整次运行均有硬超时、参数/结果
  大小上限与取消处理。达到预算后返回 typed `budget_exhausted`，不得继续调用。
- 所有 tool arguments 在执行前按 registry schema 严格校验；未知、重复失控、越界或格式
  错误均 fail closed。
- 提供完全离线的 recorded adapter 供 protocol tests 使用，并提供不读取 oracle 的固定
  deterministic policy adapter 供 CI/no-key demo/eval 使用；另提供经过 MockTransport 契约
  测试的 OpenAI-compatible tools adapter，但 live 模式只能由开发者在本地显式启用，默认
  命令和 CI 不调用任何外部模型。
- 最终输出不是无法评分的自由文本：模型必须返回 bounded summary、逐条
  `claims[{text, kind, citation_ids}]`，以及由 runner 构建的安全
  `citations[{id,kind,source_name,title,url,evidence_eligible}]` catalog。每条 external-fact claim
  的引用只能解析到本次 trace 中成功返回的 evidence IDs；catalog 不得包含未被 claim 使用的
  条目，品牌上下文不得变成事实证据。没有足够证据时必须拒答或说明不足。

### 3. MCP adapter

- 使用官方 MCP Python SDK 当前稳定大版本，提供独立 stdio entry point；不增加生产
  Compose service，不开放 SSE/Streamable HTTP 端口。
- MCP 的工具列表、JSON Schema、调用实现和结果投影必须直接来自 shared registry。
- in-memory/stdio contract test 必须证明工具发现、成功调用、非法参数、未知工具和安全错误
  投影；不得依赖 provider、生产数据库或网络。

### 4. Eval and observability

- 提供至少 40 个版本化、脱敏、可离线运行的 cases，覆盖：证据搜索、事件下钻、品牌/事实
  隔离、文案校验、多工具组合、证据不足拒答，以及恶意/越界请求。
- deterministic evaluator 至少输出：task success、tool selection、argument validity、citation
  precision/coverage、unsupported-claim rate、refusal accuracy、step count、latency，以及模型
  可提供时的 input/output tokens；不得用单一 LLM judge 作为权威分数。
- recorded adapter 只用于 runner/tool 协议测试，不得读取 eval oracle 或产生“模型质量”分数。
  CI-authoritative offline track 使用一个固定、只读取 query/trace/registry 的 deterministic
  policy baseline 来验证 evaluator 与系统不变量；报告必须明确它不是 LLM intelligence 分数。
  可选 live/local model track 才报告真实模型的 tool selection/task quality，并单独输出非阻断
  结果；默认测试禁止密钥或付费调用。
- Trace 是 API 响应中的临时、typed、redacted 投影，不新增数据库表或迁移。记录工具名、
  受控参数摘要、状态、耗时、结果计数/引用和安全错误；不记录隐藏思维链、完整 prompt、
  provider body、原文全文、私有 brand 正文、数据库 URL 或凭据。

### 5. Local-only API and UI

- Workbench 使用独立 local-only ASGI entry point；现有 `api_main`、Dockerfile/Compose 和生产
  OpenAPI 不注册该 route。官方启动命令固定 loopback，且 request runtime gate 只信任 socket
  peer 为 `127.0.0.1`/`::1`；任何 `Forwarded`/`X-Forwarded-*` header、production、
  `0.0.0.0`、非回环 peer 或 flag=false 均拒绝。默认值为关闭。
- API 使用 application service 和 dependency injection，返回 generated-OpenAPI-compatible
  wire types；独立 workbench OpenAPI/schema 生成物也必须 drift-free。不得把 ORM、provider
  类型或 MCP 类型直接暴露到 HTTP。
- React 页面提供受控问题/预设、运行状态、final answer、引用列表、步骤时间线和指标面板；
  source/model 内容按文本渲染，状态不能只靠颜色，键盘与可访问性测试必须覆盖。
- 前端不得出现发布、发送、重试生产任务或写入业务数据的控制。

### 6. Portfolio packaging

- README 增加招聘者入口；`docs/portfolio/` 提供架构图、边界/取舍、评测方法、示例结果、
  本地运行步骤和面试讲解要点。
- 提供一条离线命令完成 tool/MCP/eval portfolio check，并生成稳定 JSON 与 Markdown 报告；
  提供本地 UI 演示说明和一张不含私有数据的截图。
- 任何简历数字都必须由仓库命令或报告复现；不得声称未执行的 live 模型效果、生产 MCP
  服务或自动发布能力。

## Acceptance Criteria

- [ ] shared registry 的四个工具拥有严格 schema、只读实现、超时/大小限制与正反例；
  registry 生成唯一 canonical schema/hash，Agent、MCP 和 eval 的协议包装经规范化后语义等价，
  不要求不同协议 envelope 字节相等。
- [ ] bounded runner 在 success、refusal、invalid arguments、unknown tool、tool timeout、provider
  failure、cancellation 和 budget exhaustion 下均返回稳定 typed result，且永不超过 4 步/4 调用。
- [ ] OpenAI-compatible tool-call adapter 通过无网络 MockTransport 契约测试；默认 fake 模式和
  全部 CI 命令的外部 provider call 数为 0。
- [ ] 官方 MCP stdio server 可被测试 client 枚举和调用；没有 HTTP MCP listener、生产
  Compose service 或第二套工具实现。
- [ ] 至少 40 个脱敏 eval cases 可重复运行；recorded test 不读取 case oracle，offline policy
  baseline 只读取 query/trace/registry；schema、安全、预算、claim-level 引用与拒答不变量
  100% 通过，报告同时给出分类指标和失败 case IDs，并明确不代表 live LLM accuracy。
- [ ] 独立 local ASGI 的 `POST /api/v1/agent-workbench/runs` 在 loopback flag 开启时返回
  summary、claims、仅含已使用安全来源的 citation catalog、steps 和 metrics；正常
  `api_main`/Docker/Compose 无此 route，非回环 socket peer 与 forwarding-header spoof 均拒绝；
  无 Alembic migration。
- [ ] Trace/UI 不含 hidden reasoning、raw prompt/provider body、secret、私有对象位置或全文；
  frontend 使用独立生成类型渲染 claim 与安全 citation catalog，并通过交互、错误态、
  可访问性和无发布控制测试。
- [ ] Workbench 导航只在 Vite development + explicit local flag 下出现；production Vite build
  无活动入口，backend feature 只能 loopback opt-in。
- [ ] `make agent-portfolio-check`（最终名称可在实现中按现有 Make 规范微调）离线完成 registry、
  MCP contract、eval 和 report drift 检查；backend/frontend/OpenAPI/lock/full gates 全绿。
- [ ] README、作品集 case study、Mermaid 架构图、脱敏截图与示例评测报告可让招聘者在 5 分钟
  内理解问题、Agent 决策边界、评测结论和工程取舍。
- [ ] 整个任务不连接生产服务器、不部署、不推送业务消息、不调用付费 provider，也不
  commit/push；除非用户之后对这些动作另行明确授权。

## Out of Scope

- 多 Agent 协作、自主浏览、任意网页抓取、代码解释器、shell/file-system tools。
- 长期 trace 持久化、数据库 migration、用户账号/OAuth、网关、限流平台、Kubernetes。
- MCP HTTP/SSE/公网部署、生产 Compose 或云效/ACR/服务器变更。
- 新闻采集、图片生成/OCR、企微发送、业务调度和生产开关调整。
- 模型微调、SFT/RL、以 LLM judge 取代确定性评分。

## Key Decisions

- 选择“一套 registry，三个消费者（Agent/MCP/eval）”，避免展示三个互相漂移的 demo。
- 选择单 Agent、最多四步的自定义 LangGraph 闭环，不把复杂度包装成多 Agent；Graph 无持久
  checkpoint，业务预算不依赖 recursion exception。
- Trace 展示 action/observation 与指标，不展示或推断 chain-of-thought。
- MCP 仅用 stdio；官方 SDK 的 HTTP transport、鉴权与公网部署不属于本地求职 MVP。
- 默认 fixture/fake、可选本地 database/live adapter；CI 和作品集基线必须离线可复现。
- 不新增数据库表；先证明协议、评测、边界和可观察性，再决定是否做持久化 AgentOps。

## Risks and deferred work

- MCP Python SDK 当前稳定大版本在 2026 年发生过迁移；实现必须固定兼容大版本并以官方
  文档/SDK contract tests 为准，不依赖过时的 FastMCP import 示例。
- 真实模型的 tool choice 质量不能由 deterministic fake baseline 代表；作品集必须明确区分
  contract score 与 optional live-model score。
- 现有事实检索与品牌检索必须保持独立；若复用接口不足，新增 read-only query port，而不是
  让 Agent 直接访问 ORM 或拼接两类语料。
- 身份认证、持久 trace、Streamable HTTP MCP、模型路由和 rate limiting 可作为后续偏平台岗
  的第二阶段，不进入本 MVP。
