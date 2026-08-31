# Implementation Plan: 本机真实数据 MCP

1. 扩展隔离的 Agent Workbench 配置，定义真实 MCP 的显式 development-only opt-in 与合法 provider 前置条件；保留 fixture 默认和生产拒绝。
2. 增加纯领域 QueryPlan 和 weighted RRF，以及 QueryPlanner / TextReranker 应用端口；将改写数量、候选数和版本固定在可测试合约中。
3. 实现智谱 GLM 结构化 QueryPlanner 和智谱 `rerank` adapter；用短内部超时、严格输出 Schema 和确定性回退保持 5 秒工具边界。品牌 Embedding 独立使用阿里多模态 provider。
4. 实现真实 reader 的增强装饰层：原查询/改写检索、去重 RRF、有界精排；`get_event` 和文案校验原样委托。
5. 增加 single-flight TTL/LRU Embedding 缓存，并在 `BoundedAgentRunner` 内增加单次 run 的成功工具结果精确去重与脱敏 trace metadata。
6. 在 runtime/composition 层新增真实 PostgreSQL registry builder，复用数据库 session factory、`PostgresAgentKnowledgeReader`、品牌专用阿里 Embedding factory 与 retrieval version，不复制工具 handler；API 上传、content worker 与 MCP 使用同一品牌 identity。
7. 为真实 MCP 增加独立 STDIO 入口和资源生命周期；让其安全地关闭 engine 与共享智谱 HTTP client，且不改变 fixture `agent_mcp_main` 默认行为。
8. 添加单元/合约测试：环境 fail-closed、QueryPlan/RRF、provider payload/response、降级、缓存、composition 注入、相同 registry schema、lifecycle cleanup 和安全错误投影。
9. 更新 Agent Workbench spec/运行说明，明确 fixture 与开发机真实 MCP 的入口、检索增强、数据/隐私边界和回退方式。
10. 运行 scoped pytest、MCP contract、workbench portfolio gate 与相关 backend quality checks；随后对本机开发库做一次不落盘的四工具 STDIO smoke。
11. 仅在验证成功后更新本机 Codex MCP 注册到真实入口；记录回退到 fixture 的单条命令，不部署服务器。
12. 增加 development-only 品牌重建入口，默认 dry-run；显式执行时从 immutable original 派生当前 v3 阿里版本、走现有 worker，并只激活 ready 版本。

## Validation

```bash
cd backend && pytest -q --no-cov \
  tests/unit/test_agent_workbench_db.py \
  tests/unit/test_agent_retrieval.py \
  tests/unit/test_agent_retrieval_ai.py \
  tests/unit/test_agent_workbench.py \
  tests/integration/test_agent_workbench_db.py \
  tests/contract/test_agent_mcp.py
make agent-portfolio-check
make backend-check
```

再通过官方 MCP STDIO client 调用四个工具，断言成功/安全 typed failure、Schema 一致、无连接泄漏；控制台只显示工具名与状态，不打印真实内容或凭据。

## Risky Files and Rollback

- `backend/app/agent_mcp_main.py`：只允许为了共享 server lifecycle 能力做兼容扩展；fixture 默认构建与 guard 不得改变。
- `backend/app/core/agent_workbench_config.py`：真实数据开关须 fail closed，且不能影响 `api_main` 或生产 Compose。
- 新真实入口与 runtime composition：若出现 provider/数据库问题，撤销 Codex MCP 注册至 fixture command；没有 schema migration 或数据 mutation。
