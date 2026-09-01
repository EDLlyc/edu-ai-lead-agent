# 公众号每周三篇确定性 DAG

## Goal

在现有每周三角色选题、三份独立 V2 文章和不可变汇总 bundle 之上，增加一个数据库持久化、可租约执行、可断点续跑的静态 DAG，使失败只影响对应节点，并让操作者能准确看到每篇文章处在哪个阶段。

## Background and confirmed facts

- 现有 `official_account_weekly_edition` 已实现 `Asia/Shanghai` 周边界、三个固定角色、候选选择、三份独立最终产物、完整性校验和确定性汇总 ZIP。
- 现有 fixture/live CLI 以一次进程调用完成全流程；它没有 durable run/node、checkpoint、lease、retry 或统一状态 API。
- 现有 V2 文章产物、content/artifact fingerprint、mobile passed、`quality_auto` 和 local-only/unpublished truth 是可复用的完成门禁，不能由 DAG 重新解释。
- 项目已有独立 worker、租约、幂等 job 和 checkpoint 模式，可复用其并发/恢复做法。

## Requirements

### R1 — 代码拥有的静态 DAG

- 新增版本化固定图，不接受 LLM 生成节点或边：`schedule -> select_roles -> three role branches -> aggregate -> finalize`。
- 每个角色分支至少包含 `build_article -> plan_media -> render_handoff -> validate_child`，三个分支可在选题完成后并行，aggregate 必须等待三个 `validate_child` 成功。
- 节点输入只引用持久化 run、选题和 artifact 身份；大正文、图片、模型消息或完整子产物不得写入 checkpoint。
- 图定义、节点种类、依赖和允许处理器是闭集并纳入版本/指纹。

### R2 — Durable run、节点状态和恢复

- 持久化 weekly run 与 node attempt，至少包含 run/task/node/role、输入指纹、状态、尝试次数、租约、safe artifact ref、错误码和时间戳。
- 同一 `week_start + schedule_version + selection_version + dag_version` 幂等；重复触发返回同一 run，不覆盖已完成节点或既有汇总目录。
- worker 只领取依赖已成功的 ready 节点；租约过期可重领，完成采用 fencing token，陈旧 worker 不能写回。
- 重启后从成功 checkpoint 继续；失败重试只影响该节点及其下游，三个角色中已验证的其他分支不得重建。

### R3 — 产物门禁和聚合

- 每个 `validate_child` 必须验证独立 event/run/Article/content/artifact/ZIP 身份、mobile passed、允许的 release、local-only/unpublished、图片完整性和 V2 manifest。
- aggregate 复用现有 `build_weekly_edition_artifact`/writer，三份 child tree 和 ZIP 必须逐字节保持；DAG 不复制另一套 bundle 规则。
- 任一分支不足、重复、篡改或终态失败时 aggregate 不运行；最终状态明确区分 partial、retryable failed、terminal failed 和 ready。

### R4 — 调度、状态和统一治理

- 周调度仍由现有纯函数判断 due，不把 morning/noon/evening daily slot 改造成周刊槽位。
- 提供 development-only enqueue/status/retry 接口或等价 CLI；不新增发布按钮和社交平台客户端。
- 每个 run/node 事件使用统一 Agent 治理子任务定义的因果 trace 与预算投影；确定性非模型节点仍记录零 token、处理时长和 artifact ref。
- 运行时默认限制同时活跃的角色分支为 3；模型、工具和产物预算超限时 fail closed，并保留稳定错误码。

## Acceptance Criteria

- [x] 代码拥有的 DAG 拓扑无环、节点/边稳定，三个角色分支只有在 `select_roles` 成功后可并行，aggregate 只在三个 validation 成功后可运行。
- [x] 真实 PostgreSQL 集成测试证明幂等 enqueue、并发 claim、lease expiry、fencing、checkpoint resume、单分支 retry 和成功节点不重跑。
- [x] 进程在任意节点后终止并重启时能恢复；最终 batch fingerprint、三份 child bytes 和无中断执行完全一致。
- [x] duplicate/tampered/partial child、budget exhaustion、permission denial 和 terminal provider failure 均产生稳定安全状态，且不生成 aggregate。
- [x] 状态投影按固定角色顺序展示每篇文章当前节点、尝试次数、安全错误码和 artifact 状态，不泄露正文、prompt、provider body 或路径。
- [x] fixture、MockTransport 和可选本地 live 路径证明默认零微信/企微调用；任何结果仍需人工进入公众号流程。
- [x] migration/ORM、worker lifecycle、API/OpenAPI、focused weekly/V1/V2 regressions、Ruff、mypy、pytest、Compose/Doctor 和 `git diff --check` 通过。

## Out of Scope

- LLM 自由生成或动态修改 DAG、任意递归 Agent、跨周自动补齐无限历史任务。
- 重写现有选题算法、文章 V2 renderer、图片选择/生成、周刊 aggregate 格式或 operator pin state。
- 微信接口、浏览器自动发布、自动置顶、企微推送或面向生产的无人工发布。
- 把周刊强行映射为现有每日三时段 content slots。

## Risks and deferred items

- 当前周刊代码属于尚未提交的并行任务；实施前必须先完成或明确接管其提交，否则不能安全建立持久化层。
- 第一个版本只保证单数据库/多 worker 的租约一致性，不建设跨区域调度或分布式消息总线。
