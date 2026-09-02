# Reviewer Live AB 与简历证据

## Goal

构建 opt-in live A/B runner、人工抽样与质量成本报告，只有有效结果才能进入作品集和简历。

## Requirements

- Dependency: 前三个 Reviewer 子任务必须完成并提交；live 调用还需要用户对 provider、样本数和费用的
  单独明确授权，规划/实现 harness 不构成调用授权。
- 使用同一脱敏、版本化 dataset 比较 single Writer 与 Worker–Reviewer；运行次数、模型、温度、
  prompt/rubric/policy、registry SHA 和执行时间窗全部冻结并记录。
- 指标至少包含 critical defect recall、false accept/reject、Pass@1/Pass@2、人工复核率、P50/P95
  latency、input/output tokens、估算 cost 和 failure taxonomy；同时报告增量质量与增量成本。
- 人工 gold/adjudication 是主真值；LLM judge 只能作为辅助且必须校准。失败尝试、缺失 usage 和 bad
  cases 必须保留，不能只挑成功截图。
- Live artifact 与 deterministic canonical 分开，永不自动覆盖；无有效 live 结果时简历不填百分比。

## Acceptance Criteria

- [x] Runner 有 dry-run/preflight、单次费用上限、样本/重复上限、无 whole-suite 隐式重试和隐私扫描。
- [x] A/B report 能按版本复算，展示置信区间或重复运行方差、bad cases 和质量/成本 trade-off。
- [x] 作品集可追溯到 run manifest/hash；简历数字逐项能映射到报告且标明数据集适用范围。
- [x] 未授权、provider 失败或样本不足时生成安全失败账本，不生成质量提升结论。

## Out of Scope

- 不自动购买额度、不上传生产文章、不用 LLM judge 替代人工 gold、不承诺未测的线上业务提升。
