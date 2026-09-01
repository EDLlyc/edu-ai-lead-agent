# Agent 系统检索、编排与治理升级

## Goal

通过三个可独立验收的子任务，让现有系统同时获得可量化的 IP 图片检索质量、可恢复的每周三篇公众号生产流程，以及可复用的 Agent 预算、权限和因果追踪契约。升级必须复用现有品牌 RAG、IP 资产、公众号 V2 周刊和 Agent Workbench 能力，不重复建设已经完成的模块。

## Background and confirmed facts

- IP 文本检索当前版本为 `ip-asset-hybrid-v2`，使用元数据分数和多模态相似度的固定比例直接相加；它已有显式过滤、退化模式和稳定排序，但没有独立的检索质量数据集，也没有搜索漏斗聚合指标。
- 品牌 RAG 已实现 PostgreSQL FTS、pgvector、weighted RRF、父子切片、父级多样化和离线 Recall/MRR/nDCG 评测；这些生产纯函数和评测做法应作为模式复用，而不是重新引入 Elasticsearch。
- 公众号 V2 已有确定性周调度、三角色选题、三份独立文章产物、校验和汇总 ZIP；当前缺口是持久化 DAG、节点级 checkpoint、租约/重试、断点续跑和统一状态查询。
- Agent Workbench 已有闭集只读工具、四次工具调用上限、超时、结果大小限制和线性 trace；当前缺口是跨运行时复用的角色权限、父子预算、因果事件与 Artifact 身份。
- 当前工作区存在大量并行且未提交的功能改动。三个子任务必须串行建立迁移头并局部暂存，不能覆盖或整包提交其他任务文件。

## Requirements

### R1 — 子任务边界

父任务仅负责依赖顺序、共享契约和最终集成验收，不直接拥有产品实现。三个子任务分别负责：

1. `08-31-ip-asset-retrieval-v3`：rank fusion、离线查询集和匿名日聚合漏斗。
2. `08-31-agent-budget-permission-trace`：项目自有 Agent 运行时的预算、角色权限、因果 trace 与 Artifact 元数据。
3. `08-31-official-account-weekly-three-article-dag`：在现有周刊生成器之上增加持久化静态 DAG，并消费统一治理契约。

### R2 — 实施顺序和兼容

- 先完成独立且用户可见的 IP 检索 V3；再完成 Agent 治理基础；最后让周刊 DAG 复用该基础。
- 每个子任务独立完成实现、检查、spec 更新和工作提交后再进入下一个；父任务最终只做跨子任务集成检查和归档。
- 现有 IP V2、公众号 V1/V2 产物、Agent Workbench API 和默认关闭/本地边界必须保留可回滚兼容。
- 数据库迁移按实际最终 Alembic head 串行创建，不在规划中预占 revision 编号。

### R3 — 共享安全和真实性边界

- 搜索指标只保存按业务日期、版本、模式和事件类型聚合的计数，不保存原始查询、asset/profile 标识、IP、UA、Cookie、会话或逐事件日志。
- 周刊 DAG 不调用微信接口、不自动发布、不自动置顶；现有本地 bundle 和 operator handoff 仍是最终边界。
- Agent trace 不保存 system/user/assistant 原文、模型思维过程、provider body、凭据、私有对象路径或完整工具结果。
- 所有质量数字必须标明数据集、版本和适用范围；离线 fixture 指标不能冒充线上用户效果。

## Acceptance Criteria

- [x] 三个子任务均有收敛后的 PRD、设计、实施计划、真实上下文清单和独立验收结果。
- [x] IP V3 能在同一离线查询集上与冻结 V2 比较，并输出 Recall@5、MRR@5、nDCG@5、零结果率及类别分解；日聚合漏斗无任何用户级或查询级持久化。
- [x] 统一 Agent 治理契约能表达 `run_id / task_id / agent_id / event_id / parent_event_id / artifact_id`，在执行层默认拒绝越权，并对父子预算做不可超分配的原子检查。
- [x] 每周三篇静态 DAG 能持久化节点状态、从 checkpoint 恢复、并行三个角色分支、失败后只重试受影响节点，最终复用现有字节稳定的汇总产物。
- [x] 跨子任务集成测试证明周刊 DAG 使用统一 trace/预算/权限契约，IP 指标不复用 Agent trace 保存用户行为，二者的数据边界清晰。
- [x] 后端/前端类型、迁移、OpenAPI、Ruff、mypy、pytest、Vitest/build、隐私扫描和 `git diff --check` 按各子任务范围通过；并行工作区改动没有被覆盖或误提交。

## Out of Scope

- 引入 Elasticsearch、替换当前 embedding/provider、在线训练 reranker 或声明线上检索提升。
- 用户鉴权、跨用户个性化、原始搜索日志、用户画像或行为级漏斗回放。
- 自由规划的 LLM DAG、无限递归 Agent、开放工具市场或修改 Codex/Trellis 自身调度协议。
- 微信公众号接口调用、自动发布、自动置顶、浏览器模拟发布或修改既有不可变周刊子产物。
- 将三个子任务并行修改同一个数据库 migration head 或高冲突生成文件。

## Risks and deferred items

- V3 离线指标只能证明受控数据集上的排序策略；真实用户收益需要匿名聚合运行一段时间后再判断。
- 公众号周刊当前实现尚未形成独立工作提交，实施 DAG 前必须先确认其工作区所有权和提交边界。
- 统一治理契约会触碰 Agent Workbench 和新周刊 DAG 的共享模型，必须通过兼容适配器避免改变既有 API 字节。
