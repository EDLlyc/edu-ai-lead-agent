# Reviewer Enforce 单次返工：实施计划

## Phase 1 — revision persistence

- [x] 确认前两个子任务已提交，读取实施时真实 migration head 与最新高冲突文件。
- [x] 添加 revision/repair-of 约束、repair intent、repository exact active lookup 与旧 row backfill。
- [x] 更新 migration compatibility/doctor/head tests，证明并发只能创建一个 revision 2。

## Phase 2 — bounded repair orchestration

- [x] 实现 enforce calibration gate 和 frozen run identity。
- [x] 接入 code-owned directives、repair Worker capability/budget、durable intent 与 compatible recovery。
- [x] 对 revision 2 重跑 deterministic + legacy audit + Reviewer，并把所有第二次非接受结果封闭终止。

## Phase 3 — downstream lineage and verification

- [x] 将 renderer/media/draft/handoff/release fingerprint 改为 exact active revision/final review 绑定。
- [x] 覆盖 crash/restart/replay/lease/fencing/ambiguous/预算/越权/旧批准污染及 off/observe 回归。
- [x] 运行真实 PostgreSQL、migration、Ruff/format/mypy/privacy/full regression 与 Trellis check，独立提交。

## Pre-start gate

- [x] contract/eval 与 observe/governance 子任务已完成并提交。
- [x] enforce 仍默认关闭，未把 fixture 当作 calibration evidence。
