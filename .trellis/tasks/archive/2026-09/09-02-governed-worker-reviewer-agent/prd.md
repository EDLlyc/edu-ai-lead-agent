# 受治理的 Worker Reviewer 内容 Agent

## Goal

将公众号最终文章现有的线性 `generator -> deterministic validation -> auditor` 能力升级为可证明的
Worker–Reviewer Agent：Writer 与 Reviewer 拥有独立身份、权限、预算和因果事件，Reviewer 只读取
不可变文章 Artifact 并输出证据化结构 verdict，拒绝时最多触发一次定向返工。最终以真实或冻结的
A/B 评测同时报告质量收益、额外 token/cost/latency 和失败模式，使简历亮点来自可复现证据而不是
“Multi-Agent” 标签。

## Background and confirmed facts

- `CopyGenerationExecutor` 已有独立 generator/auditor port、确定性前置校验、持久化 audit 和最多一次
  repair；确定性规则是最终权威，LLM audit 不能覆盖 hard issue。
- `OfficialAccountLocalExecutor` 已在文章生成和确定性校验后调用 fixture/live article auditor，并将
  verdict 持久化；未通过的文章不会进入 render，但当前没有 Reviewer 驱动的定向返工。
- execution governance 已实现 `run/task/agent/event/artifact` 身份、`worker/reviewer` 角色、默认拒绝
  Capability Gateway、父子多维预算原子预留/结算和安全因果 Trace；Reviewer 已被禁止 plan 与
  business write，但当前文章 auditor 尚未使用这套治理契约。
- 周刊 DAG 已实现 PostgreSQL checkpoint、lease/fencing、三分支并行、受影响节点重试和 Artifact
  lineage，可以作为 Reviewer 持久化与恢复的工程模式。
- 现有 Agent Workbench 42/42 是 deterministic contract baseline；真实模型 Agent 质量尚无有效
  live 指标。本任务不得把 fixture 或 fake 结果表述成真实模型收益。
- 当前 Article 的 `version` 表示 schema/bundle family（v1-v6），不是内容修订轮次；返工必须引入独立
  revision/repair lineage，不能伪装成 schema v7。
- 现有 official-account auditor 继续拥有事实、隐私、安全与不当发布指令硬门禁；新 Reviewer 只拥有
  品牌、结构、可读性与编辑质量维度，避免两次通用模型审同一问题。

## Requirements

### R1 — 独立且最小权限的 Reviewer

- Writer 与 Reviewer 使用不同的 `agent_id`、角色 allocation、Prompt/version 和预算；Reviewer 必须
  通过现有 Capability Gateway 读取当前文章、来源证据和品牌上下文，不能生成、覆盖或发布文章。
- Reviewer 输入只能引用当前 run/task 下的 immutable article Artifact；跨 run、跨 task、错误 SHA、
  已失效版本或未注册 Artifact 必须在调用模型前 fail closed。
- Reviewer 输出为严格结构化 `ReviewVerdict`，至少包含 overall decision、闭集 issue code、severity、
  article/evidence reference 和 reviewer/provider/model/rubric identity。模型不得输出可执行自由文本指令；
  应用层依据闭集 issue/location 与版本化策略派生有界 `RepairDirective`。
- Reviewer 不能暴露 raw prompt、provider body、chain-of-thought、凭据、私有路径或完整文章正文到安全
  execution trace；持久化内容与安全元数据分层保存。

### R2 — 一次且仅一次的定向返工

- Reviewer `accepted` 时继续既有 render/handoff；`manual_review` 时保留文章并进入人工交接状态；
  `rejected` 只有在存在闭集、可修复 issue 时才可派生一个 Writer repair allocation。
- 每篇文章最多一次 Reviewer 驱动的 Writer 返工。修复稿必须产生新 Artifact、新 SHA 和新的 review
  request fingerprint；不得覆盖初稿或复用旧批准。
- Reviewer 不得直接修改文章。Writer 只能消费代码拥有的闭集 `RepairDirective` 和原有证据/品牌
  上下文，不能读取 Reviewer 的隐藏推理、自由文本建议或任意自然语言工具指令。
- 修复后重新运行全部 deterministic validation 和 Reviewer；第二次 rejection、不可修复 hard issue、
  provider unavailable 或预算耗尽都进入稳定人工复核/失败状态，不允许循环或偷偷换模型绕过。

### R3 — 真实性、幂等与恢复

- 每次 review 绑定 article Artifact ID/SHA、生成版本、Reviewer Prompt/rubric/policy、来源/品牌快照、
  request fingerprint 和 record fingerprint；任何内容或版本变化都使旧 verdict 失效。
- review/repair 的身份、预算、事件和 Artifact 关系通过现有 execution governance 持久化；预算在调用前
  预留、所有成功/超时/取消/异常路径只结算一次，重试不能获得新预算。
- 重放相同 request fingerprint 返回同一 compatible record；冲突 payload fail closed。进程在 review、
  repair 或 re-review 后退出时，可从持久化状态继续且不重复 provider 调用或覆盖成功 Artifact。
- 不改变现有人工审批、最终 handoff、图片门禁或自动发布边界；Reviewer 永远不能自行发布。

### R4 — 可量化的 Worker–Reviewer Eval

- 建立独立、版本化的 Reviewer dataset/rubric：编辑维度覆盖品牌语气、结构可读性、信息层级、营销
  夸大、正确文章与边界样本；端到端管线样本另覆盖事实无依据、prompt injection echo、隐私、不可
  修复 hard issue 和 provider unavailable，以证明 Reviewer 不能覆盖现有硬门禁。
- provider-free track 验证 schema、策略、Artifact/版本绑定、一次返工上限、权限/预算/恢复和报告漂移；
  不得宣称 live 模型质量。
- opt-in live track 在同一脱敏集上比较 single Writer 与 Worker–Reviewer，记录缺陷召回、误拒率、
  Pass@1/Pass@2、人工复核率、P50/P95 latency、input/output tokens、估算成本和失败 taxonomy。
- 报告必须同时展示 bad cases 与质量/成本 trade-off；LLM judge 不能是唯一真值。没有真实调用数据时，
  简历只描述评测框架和工程契约，不填写模型质量提升百分比。

### R5 — 兼容、开关和隐私

- 新能力使用显式版本化 `off|observe|enforce` rollout mode，默认 `off`：`off` 不调用 Reviewer；
  `observe` 只在 deterministic validation 与现有 hard auditor 已通过后调用并持久化 verdict，但不新增
  阻断、不返工；`enforce` 才允许按 R2 阻断并最多触发一次返工。
- 旧文章、旧 audit 和无 governance Reviewer record 的历史 run 保持可读和可交付，但不能声称通过
  新 Reviewer；从 `observe` 升为 `enforce` 必须依赖单独 live/human 校准证据，不由 fixture 自动开启。
- 现有 copy auditor、official-account auditor、deterministic validation 和 execution governance 应
  复用或适配，不复制 issue taxonomy、provider parser、Capability Gateway 或预算账本。
- migration 只做 additive schema；有数据时 downgrade 必须拒绝破坏性删除。API/日志/trace/portfolio
  artifact 继续通过敏感信息扫描。

## Acceptance Criteria

- [x] Reviewer 以独立 `ExecutionRole.REVIEWER` allocation 运行，执行层证明无 plan/business-write 权限。
- [x] Review record 与当前 immutable article Artifact SHA、全部版本和双重 fingerprint 绑定，篡改或
      跨 run/task/artifact 请求在 provider 调用前被拒绝。
- [x] `accepted/manual_review/rejected/unavailable` 全部分支稳定；只有闭集可修复 rejection 最多派生一次
      Writer repair，第二次不再循环。
- [x] Writer repair 产生新 Artifact 并重新经过 deterministic validation 与 Reviewer；旧 verdict 不会
      投影到新文章，人工审批/发布边界保持不变。
- [x] budget/capability/event/artifact 持久化覆盖正常、超时、取消、异常、lease lost、replay 和 restart；
      真实 PostgreSQL 并发测试证明不重复调用、不超卖预算、不出现断裂因果。
- [x] provider-free Reviewer eval 与 canonical drift check 可在无 key/无网络 CI 中复现，并明确不等同
      live 模型质量。
- [x] opt-in live report 能在授权后比较 single Writer 与 Worker–Reviewer 的质量、延迟、token/cost 和
      bad cases；没有授权或有效结果时不会生成虚假简历数字。
- [x] 任务范围 Ruff、mypy、unit/contract/real PostgreSQL integration、migration、privacy、eval 和
      `git diff --check` 通过；既有官方账号 handoff、Agent Workbench 与 execution governance 契约不漂移。

## Out of Scope

- 不做开放式多 Agent swarm、动态角色协商、无限 Reflection、长期对话 Memory 或 A2A 网络协议。
- 不让 Reviewer 自动发布、发送企微、修改数据库业务对象或绕过人工审批。
- 不引入第二套 Agent runtime、第二套 Tool registry、第二套预算/权限系统或独立通用工作流平台。
- 不以“同一模型重复调用”直接宣称质量提升；不在未完成 live A/B 和人工校准前填写提升百分比。
- 不在本任务中训练、微调或使用 Reviewer 模型替代确定性安全/事实门禁。

## Key product decisions

- Reviewer 插入公众号最终文章生成后、人工交接前。
- 每篇文章最多一次 Reviewer 驱动的 Writer 返工。
- rollout 为 `off|observe|enforce`，默认 `off`，先通过 `observe` 收集证据再人工决定是否启用
  `enforce`。
- `enforce` 配置必须同时绑定人工确认的 live/human calibration report SHA；实现完成不等于自动启用。
