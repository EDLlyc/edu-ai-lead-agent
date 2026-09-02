# 受治理的 Worker–Reviewer：技术设计

## 1. 架构结论

本任务不引入第二套 Agent runtime，也不把现有 auditor 改名后包装成“多 Agent”。最终文章管线由一个
业务状态机协调，复用 execution governance 作为权限、预算、因果 Trace 与 Artifact 账本：

```text
Article Writer (worker)
  -> deterministic validation
  -> legacy auditor: 事实 / 隐私 / 安全 / 发布硬门禁
  -> editorial Reviewer (reviewer): 品牌 / 结构 / 可读性 / 编辑质量
       accepted ---------> render / editor handoff
       manual/unavailable -> review_required
       repairable reject -> one Writer repair -> full validation + legacy audit + Reviewer
       second reject ----> review_required（无第三稿、无循环）
```

`OfficialAccountLocalExecutor` 仍是恢复与业务状态的唯一 owner；execution governance 只治理调用，不
接管官方账号 stage/lease/fencing。Reviewer 的结论不能覆盖 deterministic 或 legacy hard gate。

## 2. 职责与权限分离

| Actor | Role | 可用 Capability | 明确禁止 |
|---|---|---|---|
| root coordinator | orchestrator | 编排与业务持久化 | 直接伪造模型 verdict |
| initial/repair Writer | worker | `official.article.generate` | review、approve、handoff、publish |
| editorial Reviewer | reviewer | `official.article.review` | plan、business write、修改文章、publish |

模式非 `off` 时使用稳定 allocation identity：`official.writer.initial`、
`official.reviewer.r1`、可选 `official.writer.repair`、`official.reviewer.r2`。每个调用经既有
`CapabilityGateway` 预留并结算预算；角色限制由存储身份和 capability allowlist 强制，Prompt 不承担
授权职责。

Reviewer 只消费当前 run/task 下已注册、active 且 exact-SHA 匹配的 Article/source/brand Artifact。
execution-governance repository 增加最窄的 exact artifact lookup/ensure 能力；不新建 Artifact registry。

## 3. Verdict 与返工契约

`reviewer-contract-eval` 子任务冻结版本化的 `ReviewVerdict`、`ReviewIssue` 与 rubric：

- decision 闭集为 `accepted|manual_review|rejected|unavailable`；
- issue code、severity、section/block/claim/evidence reference 都是有界类型；
- `accepted` 不得带 blocking issue，非法组合、未知字段、断裂引用一律 fail closed；
- provider failure/timeout/ambiguous outcome 由应用层投影为 `unavailable` 或 `result_unknown`，模型不能
  自报成功；
- 模型输出不得包含自由文本 repair prompt 或 chain-of-thought。

返工可行性与动作由代码拥有的版本化 policy 从 `(issue_code, location)` 派生为 `RepairDirective`。
Writer 只收到闭集 directive、初稿和原有受控证据/品牌上下文；Reviewer 原始响应、隐藏推理和任意
工具指令都不会进入 Writer 输入。事实、隐私、安全与发布边界继续由 legacy auditor/deterministic
gate 决定，编辑 Reviewer 无权降低其严重度。

## 4. rollout 状态机

Reviewer mode、policy/rubric/prompt identity 与 enforce calibration report SHA 在 run 创建时冻结并进入
request fingerprint；环境变量后续变化不能重解释进行中或历史 run。

| Mode | 行为 |
|---|---|
| `off` | 完整保留现有调用数、provider payload、状态与持久化；不创建 Reviewer allocation/row。 |
| `observe` | hard gate 通过后运行受治理 Reviewer，真实持久化 verdict；不新增阻断、返工或 release。 |
| `enforce` | Reviewer 参与 gate；可修复 rejection 最多触发一次 Writer repair，其余非接受结果转人工。 |

`enforce` 除 mode 外还要求显式 acknowledgement 与一份经人工确认的 live/human calibration report
SHA；迁移、fixture 或实现完成均不能自动开启。历史 run 无新 record 时保持原语义，但不得标记为
“Reviewer passed”。

## 5. 持久化与内容修订

持久化采用 product intent + immutable result，而非把正文塞入 execution trace：

1. `official_account_article_review_requests` 在外部调用前持久化精确 Article ID/SHA、上下文指纹、
   prompt/rubric/policy/provider/model identity、allocation/reservation 和 request fingerprint；状态为
   `pending|calling|succeeded|unavailable|result_unknown`。
2. `official_account_article_review_records` 一对一保存不可变终态、严格 issue snapshot、usage/latency、
   record fingerprint 与 execution artifact/event binding。核心 lineage 使用关系列；有界、已验证的 issue
   snapshot 才可使用 JSONB。
3. `official_account_article_versions.version` 继续表示 schema family。enforce 子任务新增 `revision_no`
   （仅 1 或 2）和同 run 的 `repair_of_article_version_id`；唯一性变为 schema version + revision。
4. `run.active_article_version_id` 是 renderer、media、draft 和 handoff 的唯一文章选择；禁止再按 run 任取
   第一行。初稿与修复稿都不可变，旧 verdict/approval 不能投影到新 SHA。

所有 execution trace 只保存闭集名称、计数、耗时、opaque ID、hash 与状态，不保存文章、Prompt、
provider body、repair text、凭据或私有路径。

## 6. 恢复与 exactly-once 边界

业务 lease/fencing 继续保护 stage 提交；每个新 provider boundary 在调用前必须存在 durable intent。
重启按 request fingerprint 恢复 compatible allocation/request/record/artifact：

| 持久状态 | 恢复动作 |
|---|---|
| terminal record + exact artifact | 复用结果，零 provider 调用 |
| pending，尚未进入调用 | 使用同一 identity/reservation 执行 |
| calling 且无可证明终态 | 标记 `result_unknown` 并转人工，不盲目重调 |
| compatible revision 2 已存在 | 复用并继续后续 gate，不生成 revision 3 |
| fingerprint、SHA、scope 或 fencing 冲突 | fail closed，不覆盖成功数据 |

预算的成功、超时、取消、异常路径只结算一次。第二次 Reviewer 非接受、repair provider ambiguous、预算
耗尽或 lease 丢失都终止自动返工。

## 7. 评测与晋级证据

评测分两条永不混写的轨道：

- provider-free：至少 48 个脱敏 fixture，验证 schema、策略、hard-gate precedence、Artifact binding、
  权限、预算、一次返工、恢复及 canonical drift；这些指标不能表述为 live 模型准确率。
- opt-in live：在同一版本化数据集上做 paired single-Writer vs Worker–Reviewer，人工 gold/adjudication
  为主真值，LLM judge 仅辅助。报告 critical/editorial defect recall、false accept/reject、Pass@1/2、
  manual-review rate、P50/P95 latency、tokens、估算 cost、置信区间/方差与 bad cases。

Live runner 默认 dry-run，必须有用户对 provider、样本数和费用上限的单独授权。只有可复算报告与
manifest/hash 存在时，才允许把真实数字写入作品集或简历。

## 8. 子任务与依赖顺序

1. `09-02-reviewer-contract-eval`：纯 domain/eval 契约，无 provider/DB。
2. `09-02-reviewer-observe-governance`：off/observe、持久化 intent/result、exact artifact 与治理接入。
3. `09-02-reviewer-enforce-repair`：revision lineage、一次 repair、下游 active binding 与恢复矩阵。
4. `09-02-reviewer-live-ab-evidence`：opt-in live A/B、人工 gold、晋级/简历证据。

子任务串行提交。迁移 head、`models.py`、config/worker wiring 和 handoff 属于高冲突文件，不并行编辑。
每个子任务从实施时真实 Alembic head 生成 additive migration，并独立通过 focused checks。

## 9. 明确不采用的方案

- 不增加 LangGraph/checkpointer、通用工作流平台、swarm、递归 Reviewer 或无限 reflection。
- 不让两个通用 auditor 重复拥有事实/安全 taxonomy，也不让模型自由文本成为工具指令。
- 不把内容返工写成 Article schema v7，不覆盖初稿，不盲目重放 ambiguous provider call。
- 不创建第二套权限、预算、Trace 或 Artifact 账本，不改变人工审批和“不自动发布”边界。
