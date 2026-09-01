# 图片评测平台设计草案

## 目标

为公众号图片链路增加第一版可复现、可解释、可追溯的图片质量评测能力。MVP 先交付 provider-free policy harness 和最终 publication observation record，不宣称已经完成人工标定；评测对象必须是裁切/压缩后的最终 publication bytes。

## 核心设计决策

1. 不设计单一“图片总分”。硬错误、候选排序和批次多样性使用不同门禁。
2. deterministic offline 与 live provider 分轨；CI 不依赖实时第三方模型。
3. 每个 case 使用 per-sample atomic criteria；generic judge prompt 只作为补充。
4. MVP 只允许 `off|observe`，不以未完成人工校准的自动分数阻断发布；未来 gate 阈值以 critical false-pass budget 为目标。
5. 每条结果绑定输入 hash、生成版本、judge 版本、rubric 和 dataset 版本。
6. 角色一致性与场景多样性分开报告，避免目标冲突。

## 数据模型

实现以下不可变 schema：

- `ImageEvalCase`
  - `case_id`
  - `publication_sha256`
  - `article_id` / `block_ref`
  - `required_assertions`
  - `critical_assertion_ids`
  - `forbidden_assertions`
  - `allowed_exact_text`
  - `reference_asset_ids`
  - `viewport_variants`
  - `gold_labels`
- `ImageEvalObservation`
  - `evaluator_kind`
  - `provider` / `model` / `prompt_fingerprint`
  - `rubric_version`
  - `dimension_scores`
  - `assertion_results`
  - `issue_codes`
  - `evidence_regions`
  - `confidence`
  - `latency_ms` / `cost`
- `ImageEvalDecision`
  - `decision`: `accepted|manual_review|rejected|unavailable`
  - `hard_gate_passed`
  - `manual_review_required`
  - `ranking_score`
  - `decision_policy_version`
- `ImageEvalReport`
  - dataset hash、case/label 分布、分桶指标、confidence interval、judge-human agreement、成本和失败率

所有 schema 应 `extra="forbid"`，浮点值边界明确，issue code 使用稳定枚举。

生产记录使用独立子表 `official_account_generated_visual_evals`，而不是给历史 visual 行
增加可空 `eval_record_id`。父表 `(id, run_id, sha256)` 与子表
`(generated_visual_id, run_id, publication_sha256)` 组成复合外键，确保审校永远绑定最终
publication hash；每图只允许一条 immutable record。`record_fingerprint` 覆盖规范化
observations、decision、版本和身份字段。ORM 不建立 relationship，handoff 按 run 批量读取。

## 执行流

```text
raw generated image
    ↓ deterministic decode/shape
publication crop + JPEG encoding
    ↓ bind publication_sha256
L0 deterministic hard gates
    ↓
L1 atomic semantic judge ── L2 IP identity ── L3 OCR/text
    ↓                         ↓                ↓
L4 aesthetics/artifacts ── L5 crop/layout ── L6 batch diversity
    ↓
versioned decision policy
    ├── accepted observation
    ├── rejected/manual-review observation
    └── unavailable observation
```

MVP 的 observation 不改变现有发布流；自动 regenerate 和 gate 属于后续阶段。

## 指标和门禁

### Hard gate

- invalid bytes/media/dimensions
- critical atomic assertion failed
- forbidden logo/text/QR/watermark detected
- exact required text mismatch
- IP identity below human-calibrated threshold
- final crop loses required subject/text safe area

### Review/ranking signals

- aesthetics/artifact score
- non-critical assertion coverage
- pairwise preference
- batch diversity
- borderline OCR/identity confidence

### 报告指标

- critical defect precision/recall/F1 和 false-pass rate
- per-dimension macro/micro F1
- Spearman/Kendall rank correlation
- Cohen's kappa / Krippendorff's alpha
- bootstrap 95% CI 与 paired effect size
- p50/p95 latency、provider failure、retry 和 cost/image

## Offline / live 双轨

### Offline

- 数据中保存合法、脱敏的冻结 evaluator observations。
- runner 只执行 schema、聚合、决策 policy 和 canonical drift。
- 每个 PR 可运行，不需要 API key 或网络。

### Observe provider

- 显式配置开关；复用现有可选 `ImageQualityAuditor`，固定 model version 和 rubric。
- 对最终 publication bytes 产生 observation，不自动覆盖 canonical，也不影响发布。
- provider unavailable 或返回非法结果时持久化 unavailable/typed issue，不伪装成 accepted。
- 真正的 gold/holdout、paired diff 和 baseline promotion延后到人工标定阶段。

## 与现有模块的映射

- 扩展 `backend/app/application/ports/image_validation.py`：保留兼容的 accepted/issues provider
  结果，增加 bounded criteria、prompt/rubric version；application service 再按五个单图维度
  规范化 observations 并聚合 decision。
- 在 `backend/app/application/services/official_account_visual_generation.py` 产出最终 publication bytes 后调用 evaluator。
- 新增独立的 `StoredOfficialAccountGeneratedVisualEval` 与 repository 批量查询；ready 和可选
  eval child 在同一个 fenced transaction 提交，旧 ready 行天然保持无 child 兼容。
- 修正 `official_account_editor_handoff_v2.py` 的 durable status 语义：只有存在与 publication hash 匹配的接受记录才称为 audit accepted。
- 新建 `backend/evals/image_quality/`，承载 dataset、frozen observations、runner 和 canonical report。
- 320/375/430 screenshot、safe-area 和可读性证据保留为 Deferred Phase 4，不属于本 MVP。

## 兼容与上线

- 首版 `IMAGE_QUALITY_EVAL_MODE=off|observe`，默认 `off` 并沿用当前放行行为。
- `observe` 只写 observation 和报告，不阻止发布；收集足够 gold 后再设计并启用 `gate`。
- decision policy version 必须写入交付产物，支持回滚到旧策略。
- provider unavailable 时明确记录 `semantic_unavailable`，按配置转人工或 fallback，不伪装成已审校。

## 风险

- judge 会受视觉风格和文本暗示影响：加入 counterfactual/hard-negative meta-eval。
- 参考图可能泄漏私有 IP：离线资产只保留许可可再分发样本；其他只保存 hash/冻结 observation。
- 数据集过小导致阈值不稳定：报告 CI，保持 holdout，优先扩大失败样本而非成功样本。
- 多指标维护成本高：优先完成 semantic/IP/OCR/publication crop 四个高风险维度，其余分阶段启用。
