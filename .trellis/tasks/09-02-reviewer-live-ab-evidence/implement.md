# Reviewer Live A/B 与简历证据：实施计划

## Phase 1 — provider-free harness

- [x] 确认前三个子任务已提交，冻结 paired experiment manifest 和脱敏输入 contract。
- [x] 实现 dry-run/preflight、逐样本 attempt、样本/重复/费用上限、零 whole-suite retry 和安全账本。
- [x] 实现盲化 human worksheet、adjudication import、metrics/CI/bad-case report 与完整性/privacy checks。

## Phase 2 — optional authorized live run

- [ ] 向用户报告预估调用数与最高费用，并获得 provider/model、样本数和费用的单独明确授权。
- [ ] 在授权边界内运行 paired A/B；保留失败、unknown usage、latency 与全部适用 case。
- [ ] 完成人工标注/adjudication 后生成可复算报告；不足样本不输出 uplift。

本轮只完成 provider-free harness。没有 live 授权、没有接入 provider executor、没有读取凭据，
`live_model_calls=0`；以上三项只有在用户另行明确授权后才能执行。

## Phase 3 — evidence handoff

- [ ] 用人工确认的 report SHA 形成 enforce calibration 候选，不自动修改生产 mode。
- [ ] 运行 focused eval/unit/privacy/Ruff/mypy/`git diff --check` 与 Trellis check，独立提交/归档。
- [ ] 仅将报告可支持的数字和适用范围写入作品集/简历。

Calibration candidate gate 和 resume-claim projection 已实现，但在没有有效 live report 与人工确认时
不会生成候选，也不会写入任何百分比。

## Pre-start gate

- [x] contract、observe、enforce 三个子任务已完成并提交。
- [x] live 调用授权与实现授权严格分离。
