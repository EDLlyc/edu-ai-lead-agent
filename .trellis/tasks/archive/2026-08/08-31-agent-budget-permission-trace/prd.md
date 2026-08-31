# Agent 预算权限追踪统一化

## Goal

把 Agent Workbench 已有的调用上限、只读工具和线性 trace 抽成项目自有运行时可复用的治理契约，让 Agent、工具和确定性 DAG 节点都使用统一身份、默认拒绝权限、父子预算和因果事件，并能在不保存敏感消息的前提下定位失败环节。

## Background and confirmed facts

- `AgentRunLimits` 已限制模型轮次、工具调用、超时、输入/结果/trace 字节和 graph recursion limit。
- Workbench 工具注册表当前要求 closed-world、read-only，并在调用前完成 schema 验证、超时和安全错误投影。
- `AgentTrace` 当前绑定 run UUID、连续 ordinal、usage 和 citation，但没有通用 task/agent/event/parent-event/artifact 身份，也不能被周刊 DAG 直接复用。
- 当前项目没有需要开放任意递归 Agent 的产品需求；递归必须默认关闭。

## Requirements

### R1 — 统一运行与因果身份

- 定义版本化强类型身份：`run_id`、`task_id`、`agent_id`、`event_id`、可空 `parent_event_id` 和可空 `artifact_id`。
- 每个 agent 内 `seq_no` 从 0 连续递增；跨 agent/节点只通过 parent event 和 DAG 依赖表达因果，不按完成时间拼接消息。
- 事件闭集至少包括 run/node start/finish/fail、model request/result、tool request/result、artifact produced 和 budget/permission denial。
- Artifact 只保存 opaque ref、kind、media type、byte size、SHA-256 和安全生命周期状态，不保存正文、图片字节、provider body 或私有路径。

### R2 — 父子预算

- 统一预算至少包含 elapsed time、model turns、input/output tokens、tool calls、tool result bytes、artifact bytes 和 child count/depth。
- 根预算在 run 创建时冻结；父节点给子任务分配额度时必须原子扣减或预留，全部 child allocation 之和不能超过父级剩余预算。
- 任意递归默认禁用；只有闭集节点显式允许派生，默认最大深度 1，系统硬上限 2。预算达到 70% 时禁止继续派生，耗尽时产生稳定 `budget_exhausted`，不得通过重试获得新额度。
- provider 不返回 token usage 时记录 `unknown` 与本地可验证的调用/字节预算，不能伪造精确 token。

### R3 — 角色和工具权限

- 定义最小角色：orchestrator/planner、worker、reviewer；每个运行时通过闭集 capability allowlist 挂载工具，默认 deny。
- Planner/orchestrator 只能生成或推进结构化计划，不直接写业务产物；Reviewer 默认只读并能运行检查，不能修改后再自审；Worker 只获得当前节点需要的工具和 artifact 范围。
- 权限在执行 gateway 检查 role、task scope、tool capability、read/write class 和 artifact scope，不能只依赖 system prompt。
- 现有 Workbench 四个只读工具和 API 输出必须通过兼容 adapter 保持既有行为与安全错误。

### R4 — 安全 trace 和查询

- trace 只保存枚举、opaque identity、计数、时长、大小、模型/工具安全标识、结果状态和稳定错误码。
- 禁止保存消息正文、CoT、prompt、provider body、凭据、数据库 URL、原始工具参数/结果、私有对象 key、IP/UA 或用户 profile token。
- 提供 bounded timeline 和聚合 usage 投影；未知/重复 event、断裂 parent、非连续 seq、跨 run artifact 或越权写入 fail closed。
- 周刊 DAG 使用同一事件/预算/权限核心；IP 搜索匿名漏斗明确不进入 Agent trace。

## Acceptance Criteria

- [x] 领域测试覆盖所有身份、连续 seq、合法 parent、artifact hash/size、重复/跨 run/断裂因果拒绝和稳定序列化。
- [x] 并发父子预算分配在真实 PostgreSQL 中不可超卖；超时、token/tool/byte/artifact/depth/child exhaustion 均产生稳定 denial 且不会执行底层 handler。
- [x] Tool gateway 默认拒绝未知工具、角色不允许工具、越权 write、跨 task/artifact scope；Reviewer 修改尝试被执行层拒绝。
- [x] 现有 Agent Workbench/MCP 四工具、四调用上限、loopback、引用绑定和 API golden/contract 保持兼容。
- [x] 周刊 DAG 能记录确定性节点的零 token usage、角色分支 parent_event 和 artifact lineage，并在预算/权限失败时安全停止下游。
- [x] timeline/API/日志/数据库定向扫描证明不存在禁止内容；响应和单次查询有明确事件数/字节上限。
- [x] migration/ORM、Ruff、mypy、unit/contract/real PostgreSQL tests、Agent eval/portfolio gates、API drift 和 `git diff --check` 通过。

## Out of Scope

- 修改 Codex/Trellis 调度、开放第三方任意工具、公开多租户 Agent 平台或生产级 RBAC 管理后台。
- 保存完整聊天记录、模型思维过程、工具原始结果或把 trace 当业务事实来源。
- 无限递归、动态扩大预算、自动用另一个模型绕过 budget denial 或在 Reviewer 中隐式修复产物。
- 本轮统一模型供应商、切换 Qwen/vLLM 或实现成本计费系统。

## Risks and deferred items

- 统一契约若直接替换 Workbench 类型会造成高回归风险；首版应新增核心类型并用 adapter 投影旧 API。
- token usage 在不同 provider 上不完整，首版以调用、时长和字节硬门禁为确定事实，token 只在供应商明确返回时累计。
