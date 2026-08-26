# 真实数据 Agent MCP

## Goal

让本机 Agent 客户端通过 MCP 使用当前开发机 PostgreSQL 中已治理的真实新闻、品牌与文案数据，同时保留作品集使用的确定性 fixture MCP，且不降低既有的安全、只读与 Schema 约束。

## Confirmed Facts

- `app.agent_mcp_main` 是当前作品集 MCP 入口：STDIO 传输、fixture reader、`APP_ENV=production` 与非 fake provider 均会在启动前拒绝。
- `PostgresAgentKnowledgeReader` 已实现相同四个工具的只读业务投影：`search_evidence`、`get_event`、`retrieve_brand_context`、`validate_copy`。每次数据库会话均执行 `SET TRANSACTION READ ONLY` 与 4.5 秒 statement timeout，随后回滚释放连接。
- 品牌检索在访问数据库前使用 `BrandEmbeddingModel` 对查询做向量化；现有应用通过 `GovernanceEmbeddingBrandAdapter(create_embedding_model(...))` 使用既有配置的 Embedding provider，并会校验查询向量与已入库品牌向量的 provider/model identity 一致。
- 四个工具已经共享一份 `TypedToolRegistry`，含严格 Pydantic 入参/结果 Schema、5 秒单工具超时、参数与结果大小限制、只读与 closed-world 注解。`validate_copy` 复用确定性校验器且不会写入、修复或入队。
- 已有 PostgreSQL 集成测试覆盖治理证据、事件投影、只读写入拒绝、持久化记录数不变与连接池归还；MCP 合约测试覆盖官方 in-memory 与 STDIO 客户端。

## User Decisions

- 数据源仅为当前开发机的本地 PostgreSQL；不连接生产数据库。
- 首版完整接入全部四个工具，包含真实品牌资料检索与真实文案校验。
- 服务仅作为本机 STDIO MCP 进程运行；不新增 HTTP 端点、公网暴露、生产部署或鉴权方案。
- 品牌检索可使用当前已配置的 Embedding 服务。其查询文本会发送给该服务；返回给调用 MCP 的 Agent 客户端的是既有 Schema 限制后的品牌片段和校验结果。

## Requirements

1. 新增一个明确命名的真实数据 MCP 启动入口；不得把现有 fixture 入口默认切换为真实数据。
2. 复用 `TypedToolRegistry`、`PostgresAgentKnowledgeReader` 和既有 Embedding factory；不得复制工具业务逻辑或放宽 Schema。
3. 真实入口只能在 development 启动，且必须由专用显式开关选择本地 PostgreSQL 数据模式；production、缺失开关、disabled/fake Embedding provider、无效配置均须在执行工具前安全失败。
4. 保持所有查询及文案校验无副作用：禁止 SQL、写入、发布、入队、任意 URL 抓取、文件/对象路径和密钥输出。
5. 在 MCP server 生命周期内拥有并释放 database engine 与 HTTP Embedding client；不得在数据库事务打开时等待远端 Embedding。
6. 真实入口、fixture MCP、共享 registry 的工具 Schema 与错误投影必须可独立测试；测试日志和任务材料不得存储真实正文、数据库 URL 或凭据。
7. 实现验证通过后，将本机 Codex MCP 注册从 fixture 命令更新为新的真实数据入口，并保留 fixture 入口用于离线作品集演示。

## Acceptance Criteria

- [ ] 明确 opt-in 的真实 MCP 入口可由官方 STDIO 客户端列出与 fixture 完全相同的四个 canonical tool schemas，并针对本机开发库返回 Schema 限定的真实投影。
- [ ] 四个工具保持既有语义：Tier A/B 治理证据、当前事件版本、品牌片段 `evidence_eligible=false`、不可变 copy-run 上的确定性校验；无新增业务副作用。
- [ ] 真实入口在 production、无显式 real-data opt-in、或不具备可用 Embedding provider 时拒绝启动/返回安全的 typed unavailable，而非使用 fixture 或不受控降级。
- [ ] PostgreSQL 会话继续以只读事务和超时运行，写入被 PostgreSQL 拒绝，查询后无持久化记录变化、连接池连接归还。
- [ ] fixture MCP 入口及其 in-memory/STDIO 合约测试保持不变；真实入口的构建、环境校验、资源清理和错误边界新增有针对性的测试。
- [ ] 真实 smoke 验证不在仓库、测试快照或公开作品集中写入真实业务文本、UUID、数据库地址或凭据。

## Out of Scope

- 生产数据库、服务器部署、远程 Streamable HTTP MCP、Web/API 路由、身份认证与多用户授权。
- 写数据库、生成/修复/发布文案、任务调度、素材读取、任意 URL 请求、原始品牌文件或 provider 原始响应的暴露。
- 更换或重建品牌 Embedding、修改新闻治理/选题/发布业务规则，或把实时数据混入离线评测和公开作品集。
