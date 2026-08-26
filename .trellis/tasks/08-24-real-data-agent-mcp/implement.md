# Implementation Plan: 本机真实数据 MCP

1. 扩展隔离的 Agent Workbench 配置，定义真实 MCP 的显式 development-only opt-in 与合法 provider 前置条件；保留 fixture 默认和生产拒绝。
2. 在 runtime/composition 层新增真实 PostgreSQL registry builder，复用数据库 session factory、`PostgresAgentKnowledgeReader`、现有 Embedding adapter 与 retrieval version，不复制工具 handler。
3. 为真实 MCP 增加独立 STDIO 入口和资源生命周期；让其安全地关闭 engine 与 HTTP client，且不改变 fixture `agent_mcp_main` 默认行为。
4. 添加单元/合约测试：环境 fail-closed、composition 注入、相同 registry schema、lifecycle cleanup 和安全错误投影；复用现有 PostgreSQL integration test 证明只读、记录数稳定和连接归还。
5. 更新 Agent Workbench spec/运行说明，明确 fixture 与开发机真实 MCP 的入口、数据/隐私边界和回退方式；不把真实查询输出写入公开文档。
6. 运行 scoped pytest、MCP contract、workbench portfolio gate 与相关 backend quality checks；随后对本机开发库做一次不落盘的四工具 STDIO smoke。
7. 仅在验证成功后更新本机 Codex MCP 注册到真实入口；记录回退到 fixture 的单条命令，不部署服务器。

## Validation

```bash
cd backend && pytest -q --no-cov \
  tests/unit/test_agent_workbench_db.py \
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
