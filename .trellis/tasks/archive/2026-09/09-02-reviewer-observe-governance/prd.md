# Reviewer Observe 治理接入

## Goal

将最终文章审校接入独立 Reviewer 身份、Capability、预算、Artifact 与安全持久化，默认关闭并支持 observe。

## Requirements

- Dependency: 必须基于已完成并提交的 `09-02-reviewer-contract-eval`，不得复制其 schema/rubric。
- `off` 完全保留现有 auditor 行为和调用数；`observe` 将一次 Reviewer 调用绑定当前不可变文章
  Artifact，并记录独立 `ExecutionRole.REVIEWER` allocation、预算、Capability 与因果事件。
- Observe verdict 不新增阻断、不触发返工、不改变人工审批/发布；原有 deterministic/audit gate 仍是
  现行放行语义，历史 row 无 Reviewer record 仍可读但不能声称通过新 Reviewer。
- Reviewer 只能读当前 run/task 的文章、来源和品牌 Artifact；跨 scope/SHA/version 在 provider 前拒绝。
- 新 review record 绑定 article ID/SHA、prompt/rubric/policy/provider/model、request/record fingerprint、
  安全 issue snapshot 和 usage；trace 不保存正文、Prompt、provider body、凭据或私有路径。
- 配置、Compose、worker wiring 和 additive migration 使用实施时真实 head；有数据 downgrade 拒绝。

## Acceptance Criteria

- [x] off 零新增 Reviewer provider 调用、零新增 Reviewer row、既有字节/API/状态不漂移。
- [x] observe 的 accepted/manual/rejected/unavailable 均被安全持久化且不新增 release/repair 行为。
- [x] Reviewer 角色无法 plan/business-write；预算在超时、取消、异常和成功路径只结算一次。
- [x] PostgreSQL 测试覆盖 replay、并发、跨 run/task/artifact、hash/version tamper 和 populated downgrade。
- [x] 旧数据与现有官方账号、Workbench、execution-governance 契约保持兼容。

## Out of Scope

- 不生成修复稿、不启用 enforce、不运行 live A/B、不修改简历质量数字。
