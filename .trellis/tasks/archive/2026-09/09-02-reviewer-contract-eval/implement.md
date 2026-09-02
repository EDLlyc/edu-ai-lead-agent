# Reviewer 契约与离线评测：实施计划

## Phase 1 — contract

- [x] 冻结 schema/rubric/policy version 和 editorial issue taxonomy。
- [x] 实现严格 `ReviewVerdict`/`ReviewIssue`、input identity/fingerprint 和非法组合校验。
- [x] 实现代码拥有的 repairability policy 与有界 `RepairDirective` 投影。

## Phase 2 — provider-free evaluator

- [x] 建立至少 48 个脱敏 case 与独立 oracle，覆盖 PRD 全部 good/base/bad 分支。
- [x] 实现严格 loader、deterministic policy runner、指标与 bad-case 归因。
- [x] 生成 canonical JSON/Markdown、README 和 drift/privacy tests，固定零 live call truth。

## Phase 3 — verification

- [x] 运行 focused Ruff/format/mypy/unit/eval/canonical/`git diff --check`。
- [x] Trellis check 契约、指标诚实性与后续生产可消费性；发现已修复并完成复验。

## Pre-start gate

- [x] 父任务最终规划已获用户批准。
- [x] 本任务 context manifests validate，且未启动外部 provider。
