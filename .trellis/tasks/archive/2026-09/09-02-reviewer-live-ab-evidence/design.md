# Reviewer Live A/B 与简历证据：技术设计

## 1. 授权边界

实现 runner、dry-run、preflight、人工 worksheet 和报告生成器不授权任何模型调用。真正 live run 必须
再次获得用户对 provider/model、样本数/重复数和费用上限的明确同意；没有 key、额度、有效样本或授权
时生成安全失败账本，不生成 uplift 结论。

## 2. Paired 实验

每个脱敏 case 使用同一冻结 initial Article 作为配对起点：baseline 是 single Writer + 既有 hard gates，
treatment 在同一初稿上增加 governed Reviewer 和最多一次 repair。这样差异归因于 Reviewer policy，而
不是两次随机初稿。manifest 固定 dataset/oracle、initial artifact、prompt/rubric/policy/provider/model、
temperature/seed（provider 支持时）、时间窗、代码 SHA、样本/重复上限和预算。

调用逐条持久化 attempt/status/usage/latency，禁止 whole-suite 隐式重试。缺失 token usage 保持 unknown，
不估造成精确数字；成本只根据已知 usage 与冻结价格表计算并标注适用日期。

## 3. 人工 gold 与统计

盲化 worksheet 不暴露 baseline/treatment 标签。人工 gold/adjudication 是主真值；至少对校准子集进行
双人独立标注并记录一致率，分歧由第三步 adjudication 解决。LLM judge 只能输出单独辅助列，不能覆盖
人工标签。

报告包括 editorial/critical defect recall、false accept/reject、Pass@1/Pass@2、manual-review rate、
P50/P95 latency、input/output tokens、增量 cost、失败 taxonomy、bad cases，以及 bootstrap confidence
interval 或多次运行方差。样本不足时明确 `insufficient_evidence`。

## 4. 证据与晋级

输出包含不可变 run manifest/hash、raw bounded observation、human labels、metrics JSON、Markdown 报告与
privacy scan。live artifact 与 provider-free canonical 永不互相覆盖。只有通过完整性检查并被人工确认的
report SHA 可作为 enforce calibration identity；简历每个数字必须能回链到报告、样本范围和时间。
