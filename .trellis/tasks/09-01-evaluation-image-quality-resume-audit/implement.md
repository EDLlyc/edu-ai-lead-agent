# 建议实施计划

本文件描述 P0/P1 MVP 的实施顺序。必须先完成 provider-free schema/harness，再复用同一契约接入最终 publication observation；两者存在显式依赖，不并行修改共享 schema。

## Phase 0：口径、schema 和种子数据

- 定义 `rubric.v1`、issue taxonomy 和 case/observation/report schema。
- 建立至少 40 个脱敏 fixture case 与冻结 observation，覆盖六个维度、critical/warning/borderline/hard-negative；不复制 `private/` 图片，不冒充多人标注。
- 给现有“图片校验通过”文案补充准确范围，区分 file-valid、OCR-audited、semantic-audited、publication-audited。
- 固化当前基线，不把当前 `topic_rerank` 漂移混入图片任务。

完成证据：数据字典、样本清单、标注指南、baseline report。

## Phase 1：provider-free 图片评测 harness

- 新建 `backend/evals/image_quality/`。
- 实现严格 schema、dataset hash、冻结 observation 聚合、分桶指标、Markdown/JSON canonical 报告。
- 加入 hard-gate 决策和 expected/actual 失败诊断。
- 覆盖 semantic、IP identity、OCR、artifact、crop/layout、diversity 六类 observation，输出 critical precision/recall/F1、false-pass 和 manual-review rate。
- 在 Makefile/CI 中增加 `image-quality-eval --check`。

完成证据：无网络可复现，测试覆盖 malformed/duplicate/drift/failure，canonical check 通过。

## Phase 2：最终发布字节 observation

- 新增 additive 持久化 `VisualEvalRecord`，绑定 generated visual 与 publication SHA-256。
- 在中心裁切/JPEG 编码后复用现有可选 auditor；`off` 不调用，`observe` 只记录 accepted/review/rejected/unavailable。
- 编辑器 handoff 只在 hash、rubric、judge、decision 均匹配时声明 audit accepted；旧记录保持可交付。
- 默认 `off`；本阶段不实现 gate、自动重生成或发布阻断。

完成证据：端到端测试证明裁切后错误能被发现，旧行为在 off 模式保持兼容。

## Deferred Phase 3：人工标定 live track

- 扩展到 100–200 张，2–3 名标注者，20% 重叠并裁决分歧。
- 接入 OCR、DINOv2/CLIP-I 和 criteria-based VLM judge；保存 provider/model/prompt/rubric 版本。
- 计算 judge-human agreement、critical defect recall/false-pass、置信区间、延迟和成本。
- 用 calibration split 选 threshold，用 holdout 只做最终报告。

完成证据：gold dataset card、agreement report、threshold rationale、live/offline paired report。

## Deferred Phase 4：移动端感知回归与业务指标

- 覆盖 320/375/430 screenshot regression、文字像素高度、对比度、主体 safe area。
- 建立每篇/每周场景多样性报告。
- 记录首轮人工通过率、误放率、平均审核时长和重生成次数。
- 对模型/提示词做 paired A/B，只有显著改进才 promote baseline。

完成证据：浏览器截图报告、A/B report、业务 proxy 趋势。

## 推荐 MVP 边界

本任务 MVP 只完成 Phase 0–2。Phase 3 的真实人工标定是形成 human-aligned 指标的必要后续，但不能在本阶段用 fixture 结果替代。

## Validation Commands

```bash
make image-quality-eval
cd backend && conda run --name edu-ai pytest \
  tests/unit/test_image_quality_eval.py \
  tests/unit/test_image_validation_ai.py \
  tests/unit/test_official_account_worker.py \
  tests/unit/test_official_account_editor_handoff_v2.py \
  tests/integration/test_image_quality_eval_migration.py \
  tests/integration/test_official_account_local.py -q --no-cov
make backend-format-check
make backend-lint
make backend-typecheck
```

最终再运行 `make backend-test` 或项目完整质量门；若只被既有 `topic_rerank/priority-barrier` 漂移阻断，保留失败证据，不修改无关 canonical。

## Implemented Evidence

- Provider-free baseline: 48/48 sanitized fixtures, six dimensions with eight cases each, critical
  precision/recall/F1 `1.0/1.0/1.0`, false-pass `0/18`, manual review `18/48`, and unavailable
  `6/48`. These are frozen policy-conformance results, not live-model or human-agreement metrics.
- Production observation: `IMAGE_QUALITY_EVAL_MODE=off|observe` defaults to `off`; `observe`
  evaluates the final 1536×1024 JPEG and persists five single-image dimensions. Batch diversity
  remains an offline/future batch-evaluator construct.
- Persistence: Alembic `20260901_0041` adds an immutable one-record-per-visual child with composite
  generated-visual/run/final-SHA foreign key and request/record fingerprints. Ready plus the
  optional child share one fenced transaction.
- Truthful handoff: only a current accepted record with recomputed decision, final SHA, versions,
  request fingerprint, and record fingerprint yields `durable_image_audit_accepted`; historical
  and degraded rows stay deliverable as `passed_local_visual_inspection`.
- Verification: the final focused rerun collected 75 tests across five unit and two real
  PostgreSQL integration suites; global Ruff lint passed; 11 changed production files passed
  mypy; 24 task Python paths passed Ruff format/check;
  migration upgrade, empty downgrade, and populated downgrade refusal passed; Compose resolves
  the default mode to `off`; the one-page resume PDF was rebuilt and visually checked.
- Pre-existing workspace gates remain outside scope: global format reports
  `test_title_relevance_ingestion.py` and user-modified `test_topic_selection_delivery.py`; global
  mypy reports two Literal errors in `local_exact_target_selection.py`; full backend pytest reports
  28 topic/copy/IP-environment failures and 1777 passes, with no image-quality focused failure.

## Risky Files and Rollback Points

- `backend/app/infrastructure/db/models.py` 与新增 Alembic migration：只做 additive schema；迁移必须可 downgrade。
- `backend/app/application/services/official_account_local.py`：默认 off 不得新增 provider 调用或改变 ready/release 行为。
- `backend/app/application/services/official_account_editor_handoff_v2.py`：只收紧 audit 状态的真实性，不阻止旧数据交付。
- `backend/evals/image_quality/canonical-report.*`：只能通过显式 `--write-canonical` 更新，禁止为隐藏失败直接改基线。

## 验收

- 每个图片维度有明确 construct、gold label 与可解释 evidence。
- 最终发布字节而非原始生成图被评测。
- CI 不依赖 live provider；live track 输出不会自动覆盖 canonical。
- 自动评测器报告与人工一致性、关键缺陷召回和误放率。
- 简历数字可从版本化 report 直接追溯，未完成结果不进入简历。
