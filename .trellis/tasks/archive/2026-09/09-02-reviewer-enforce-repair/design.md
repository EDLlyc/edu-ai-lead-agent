# Reviewer Enforce 单次返工：技术设计

## 1. Article revision lineage

保留 `official_account_article_versions.version` 的 schema family 语义，新增：

- `revision_no SMALLINT`，只允许 1 或 2；旧 row 回填 1；
- nullable `repair_of_article_version_id`；revision 1 必须无 parent，revision 2 必须绑定同 run/schema 的
  revision 1；
- unique `(run_id, version, revision_no)`，配合 FK/check 与加锁 repository validation 防止并发第三稿；
- 下游统一按 `run.active_article_version_id` 精确读取，不再按 run 任取首行。

修复稿先不可变持久化并通过 deterministic validation，随后才成为 active candidate；它自己的 legacy
audit 与 Reviewer record 决定是否可以 render/handoff。失败初稿与修复稿都保留以供审计，旧 approval
永不复制到新 SHA。

## 2. Enforce 状态机

```text
r1 hard gates pass -> reviewer r1
  accepted -> downstream
  manual/unavailable/result_unknown/nonrepairable -> review_required
  repairable rejected -> durable repair intent -> worker repair -> r2

r2 -> deterministic validation -> legacy hard audit -> reviewer r2
  accepted -> downstream with exact r2 lineage
  anything else -> review_required / stable failure; no further allocation
```

repairability 只来自 contract 子任务的代码 policy。repair Writer 使用独立 role/capability/budget，输入是
初稿 exact artifact、原有 source/brand context 与有界 `RepairDirective`；它没有 review/approve 权限。

## 3. Repair exactly-once

新增 product-owned durable repair request/intent，绑定 source Article ID/SHA、directive fingerprint、Writer
prompt/provider/model identity、allocation/reservation 与唯一 request fingerprint。`calling` 后无确定结果的
崩溃进入 `result_unknown` 并人工处理，不能再调用一次“碰碰运气”。compatible revision 2/repair record
存在时直接恢复后续 gate；冲突 replay、stale fencing 或 lost lease 不得修改 active pointer。

第二次 Reviewer allocation、任何第三稿 allocation、替换模型绕预算和 whole-stage 隐式 retry 都由代码
状态与数据库约束共同拒绝。

## 4. Enforce 晋级与下游

`enforce` 只有在显式 acknowledgement 和人工确认的 calibration report SHA 均被 run snapshot 冻结时
允许创建。fixture/canonical 不能满足该条件。

renderer、generated media、draft、Editor Handoff V2 与 release fingerprint 都绑定 exact active Article
revision/SHA 和最终 accepted Reviewer record。manual/unavailable/rejected/result_unknown 不生成机器批准，
且不改变人工审批和“不自动发布”边界。observe/off 继续保持前一阶段语义。

## 5. 验证矩阵

覆盖 r1 accepted/manual/unavailable/nonrepairable/repairable、repair provider failure/ambiguous、r2 全分支、
deterministic/legacy recheck、并发 repair、crash-after-each-boundary、lease reclaim/stale fencing、预算耗尽、
旧 verdict/approval tamper、active revision downstream、migration/backfill/downgrade 和 off/observe 回归。
