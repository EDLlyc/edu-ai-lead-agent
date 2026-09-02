# Reviewer Observe 治理接入：实施计划

## Phase 1 — prerequisites and schema

- [x] 确认 contract/eval 子任务已提交，读取最新 migration head 与 dirty high-collision files。
- [x] 增加 frozen mode/version/budget 配置与 durable review request/record migration/models/repository。
- [x] 补充 execution artifact exact lookup/compatible ensure 的最窄共享接口与回归测试。

## Phase 2 — governed adapters

- [x] 注册 initial Writer 和 editorial Reviewer capabilities、limits、roles 与 deterministic identities。
- [x] 接入独立 Reviewer port/provider/strict parser，保持 legacy auditor 不变。
- [x] 在 official-account executor 实现 off/observe 分支、pre-call intent、record/artifact 和 safe recovery。

## Phase 3 — verification

- [x] 覆盖 off zero-drift、observe non-blocking、四类 verdict、result_unknown、权限/预算/Artifact tamper。
- [x] 运行真实 PostgreSQL 并发/replay/migration/downgrade、worker/config/compose/handoff/Workbench 回归。
- [x] 完成 Ruff/format/mypy/privacy/`git diff --check` 与 Trellis check 后独立提交/归档。

## Pre-start gate

- [x] `09-02-reviewer-contract-eval` 已完成并提交（`ae525f1`）。
- [x] 实施时 head 为 `20260901_0042`，context manifests 已验证，并已重读高冲突配置 diff。
