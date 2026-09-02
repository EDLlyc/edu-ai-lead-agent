# Reviewer 契约与离线评测

## Goal

建立受治理 Reviewer 的闭集 verdict、rubric、provider-free dataset 与 canonical 指标。

## Requirements

- Dependency: 无；这是父任务的第一个实施子任务，后续三个子任务只能消费其已提交版本。
- 定义 `accepted/manual_review/rejected/unavailable`、critical/warning、repairable/non-repairable、
  article/evidence reference、review request/record fingerprint 和版本化 rubric/policy。
- Critical 事实、隐私、安全、注入和不当发布指令不能被平均分或审美信号抵消；Reviewer 不生成
  chain-of-thought，也不拥有文章写权限。
- 建立至少 48 条脱敏 fixture，覆盖事实、品牌语气、结构可读性、安全隐私、注入/发布边界、正例/
  边界/provider unavailable；oracle 不进入被测策略。
- 报告关键缺陷 precision/recall/F1、false accept、false reject、manual-review、repairability accuracy、
  分维覆盖和失败 case；canonical 必须版本化且可检查漂移。

## Acceptance Criteria

- [x] 严格 schema 拒绝未知 issue、错误 severity、断裂 evidence reference、重复维度和非法 accepted。
- [x] Hard gate、manual review、unavailable 和 repairable policy 有明确单元测试且不产生总分掩盖。
- [x] Provider-free dataset/canonical 可无 key、无网络重复运行，损坏 dataset/rubric/report 会明确失败。
- [x] README 和报告明确 fixture 指标不等于 live Reviewer accuracy 或人类一致率。

## Out of Scope

- 不接生产 provider、数据库或官方账号状态机；不修改简历，不运行付费模型。
