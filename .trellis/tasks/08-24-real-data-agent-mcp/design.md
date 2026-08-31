# Design: 本机真实数据 MCP

## Boundary

新增 `app.agent_mcp_real_data_main` 作为唯一的真实数据入口。它仍使用 MCP STDIO；进程由本机 Codex 启动，数据库也只解析当前开发机的 `Settings.database_url`。现有 `app.agent_mcp_main` 继续只构造 fixture reader，作为离线评测与公开作品集入口。

```text
Codex Agent Client
  └─ stdio ──> agent_mcp_real_data_main (development + explicit opt-in)
                   ├─ TypedToolRegistry (unchanged schemas/handlers)
                   ├─ EnhancedAgentKnowledgeReader
                   │    ├─ controlled QueryPlanner -> Zhipu GLM JSON
                   │    ├─ original/rewrite retrieval -> weighted RRF
                   │    ├─ bounded rerank -> Zhipu rerank
                   │    └─ PostgresAgentKnowledgeReader
                   │         ├─ PostgreSQL read-only projections
                   │         └─ brand vector retrieval -> Alibaba qwen3-vl-embedding
                   └─ lifecycle: close HTTP client + dispose engine
```

## Composition

1. 真实入口读取专用 MCP runtime 设置，并在创建 server 前验证：development、显式 real-data mode、显式 enable、以及可用的非 fake Embedding provider。
2. 读取主 `Settings`，通过现有 `create_engine` / `create_session_factory` 建立连接池；使用入口拥有的 `httpx.AsyncClient` 与品牌专用 factory 创建 `AlibabaMultimodalBrandEmbeddingAdapter`。同一 client 仍可服务智谱 planner/rerank，但 provider identity 独立。
3. 仅在真实数据 composition 中，用 `EnhancedAgentKnowledgeReader` 装饰 PostgreSQL reader；再将其传给现有 `build_agent_tool_registry` 和 `AgentWorkbenchMCPServer`。MCP 仍从 registry 生成完全相同的工具 Schema 与安全错误。
4. 将 engine 和 HTTP client 的释放挂到 MCP lifespan；退出、异常或客户端断开后均关闭，不保留后台业务任务。

## Retrieval Enhancement

`QueryPlanner` 是受控的应用服务，不是第二个 Agent。它先做 NFKC、空白与标点规范化，再最多请求一次智谱 GLM 结构化输出。产物只包含原查询、最多一个改写、受限 intent 和版本指纹。严格 Pydantic 验证、重合度检查或内部截止时间任一失败即只使用原查询。

两路候选仍各自调用既有 reader，因此所有受众、文档类型、有效期、Tier A/B、当前事件版本与 provider/model identity 约束保持在权威查询层内。服务层只按稳定 identity 去重，使用 `k=60`、原查询权重 `1.0`、改写权重 `0.8` 的 weighted RRF，然后把最多 10 个候选交给智谱 `rerank`。精排输出仅允许已有 candidate index；超时、重复 index、非有限分数或缺失项全部回退 RRF。

## Cache Boundaries

- `RunToolResultCache`：由 `BoundedAgentRunner` 每次 `run()` 初始化，key 是 registry Schema hash、工具名和经 Pydantic 验证后的 canonical JSON。只缓存成功结果，重复调用仍产生正常 observation 并消耗工具次数预算。
- `EmbeddingCache`：进程内、TTL + LRU 有界、single-flight。key 包含缓存版本、provider/model/input-version namespace、artifact/chunk ID、input hash 和实际文本 hash；只保存经 Schema 校验的结果，进程退出即清空。因为品牌结果 fingerprint 绑定 artifact，禁止跨 chunk 复用完整结果。
- 不缓存失败、不使用 Redis、不持久化用户查询。trace/log 只记录 hit/miss、scope、版本与查询 hash，不记录原文。

品牌 RAG 的 cache namespace 固定绑定 `alibaba-model-studio/qwen3-vl-embedding` 和品牌 embedding-input version；治理事件/article 的智谱 `embedding-3` 不进入该缓存。

## Data and Privacy Flow

- `search_evidence` 与 `get_event` 仅查询已治理的数据库投影；公共 HTTPS URL、数量与文本长度仍由 registry 限制。
- `retrieve_brand_context` 先将调用方的检索 query 发送到已配置的 Embedding provider，再以 provider/model identity 匹配的向量查询本地品牌 chunks。仅返回限长 excerpt 和结构化元数据；品牌 chunks 永远不可作为事实证据。
- `validate_copy` 将调用方提交的限长 draft 与不可变 `copy_run_id`、`brand_chunk_ids` 对应的本地上下文交给确定性规则校验器；不会调用生成模型或写回数据库。
- 所有实际结果仅经 STDIO 返回给当前获得本机访问权的调用方；测试和文档只断言类型、数量、Schema、资源状态和错误码，不固化真实业务内容。

## Failure and Compatibility

- fixture 入口保持原命令、默认值与拒绝 live provider 的行为，不与 real-data mode 共享默认分支。
- 缺少 opt-in、production、非阿里品牌 provider、缺失阿里或智谱 credentials、或无法构造 provider 时，真实入口 fail closed；禁止改用 fixture、禁用向量检索后继续返回数据，或连接生产库。
- provider/model identity 不匹配沿用 registry 的 `agent_tool_unavailable` 投影；不改写入库向量，也不隐式选取另一模型。
- PostgreSQL 查询已在 adapter 中完成 read-only/rollback；Embedding 一定发生在数据库 session 之前。连接与 HTTP client 由入口 lifespan 释放。
- QueryPlanner 和 rerank 是可选增强而非数据可用性前置条件；它们在工具 5 秒总界内使用独立更短截止时间，失败时 fail soft。Embedding 和 PostgreSQL 失败仍沿用 typed unavailable，不伪造结果。

## Brand Vector-Space Migration

`python -m app.brand_embedding_reindex_main plan` 只读取 aggregate 状态。`migrate --execute` 为每个 active-ready 文档复用 immutable original 和 metadata，创建当前 v3 parser/chunk/input bundle 下的阿里派生版本，交给同一 ingestion executor 重建 2048 维向量，并只激活 ready 目标。旧版本在单文档切换成功前持续 active；失败版本不覆盖原 active identity，可再次派生重试。

## Operational Use

实现和测试完成后，Codex 的 `edu-ai-agent-workbench` 本机配置会切换到新入口并携带专用 development/real-data 环境变量。该配置不使用 HTTP 端口、不会随系统开机常驻；需要时由 Codex 拉起，关闭本机进程或服务后不可调用。fixture 命令保留，可按需另注册为演示服务器。

## Rollback

将 Codex MCP 注册命令切回现有 `python -m app.agent_mcp_main` 即可恢复 fixture-only 行为；无需数据库迁移、数据回填或服务器操作。
