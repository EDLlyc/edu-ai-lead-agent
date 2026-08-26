# Design: 本机真实数据 MCP

## Boundary

新增 `app.agent_mcp_real_data_main` 作为唯一的真实数据入口。它仍使用 MCP STDIO；进程由本机 Codex 启动，数据库也只解析当前开发机的 `Settings.database_url`。现有 `app.agent_mcp_main` 继续只构造 fixture reader，作为离线评测与公开作品集入口。

```text
Codex Agent Client
  └─ stdio ──> agent_mcp_real_data_main (development + explicit opt-in)
                   ├─ TypedToolRegistry (unchanged schemas/handlers)
                   ├─ PostgresAgentKnowledgeReader
                   │    ├─ PostgreSQL read-only projections
                   │    └─ retrieve_brand_context -> configured Embedding provider
                   └─ lifecycle: close HTTP client + dispose engine
```

## Composition

1. 真实入口读取专用 MCP runtime 设置，并在创建 server 前验证：development、显式 real-data mode、显式 enable、以及可用的非 fake Embedding provider。
2. 读取主 `Settings`，通过现有 `create_engine` / `create_session_factory` 建立连接池；使用由该入口拥有的 `httpx.AsyncClient` 与 `create_embedding_model` 创建 `GovernanceEmbeddingBrandAdapter`。
3. 将 reader 传给现有 `build_agent_tool_registry`，再传给现有 `AgentWorkbenchMCPServer`。MCP 仍从 registry 生成完全相同的工具 Schema 与安全错误。
4. 将 engine 和 HTTP client 的释放挂到 MCP lifespan；退出、异常或客户端断开后均关闭，不保留后台业务任务。

## Data and Privacy Flow

- `search_evidence` 与 `get_event` 仅查询已治理的数据库投影；公共 HTTPS URL、数量与文本长度仍由 registry 限制。
- `retrieve_brand_context` 先将调用方的检索 query 发送到已配置的 Embedding provider，再以 provider/model identity 匹配的向量查询本地品牌 chunks。仅返回限长 excerpt 和结构化元数据；品牌 chunks 永远不可作为事实证据。
- `validate_copy` 将调用方提交的限长 draft 与不可变 `copy_run_id`、`brand_chunk_ids` 对应的本地上下文交给确定性规则校验器；不会调用生成模型或写回数据库。
- 所有实际结果仅经 STDIO 返回给当前获得本机访问权的调用方；测试和文档只断言类型、数量、Schema、资源状态和错误码，不固化真实业务内容。

## Failure and Compatibility

- fixture 入口保持原命令、默认值与拒绝 live provider 的行为，不与 real-data mode 共享默认分支。
- 缺少 opt-in、production、disabled/fake provider、缺失 provider credentials 或无法构造 provider 时，真实入口 fail closed；禁止改用 fixture、禁用向量检索后继续返回数据，或连接生产库。
- provider/model identity 不匹配沿用 registry 的 `agent_tool_unavailable` 投影；不改写入库向量，也不隐式选取另一模型。
- PostgreSQL 查询已在 adapter 中完成 read-only/rollback；Embedding 一定发生在数据库 session 之前。连接与 HTTP client 由入口 lifespan 释放。

## Operational Use

实现和测试完成后，Codex 的 `edu-ai-agent-workbench` 本机配置会切换到新入口并携带专用 development/real-data 环境变量。该配置不使用 HTTP 端口、不会随系统开机常驻；需要时由 Codex 拉起，关闭本机进程或服务后不可调用。fixture 命令保留，可按需另注册为演示服务器。

## Rollback

将 Codex MCP 注册命令切回现有 `python -m app.agent_mcp_main` 即可恢复 fixture-only 行为；无需数据库迁移、数据回填或服务器操作。
