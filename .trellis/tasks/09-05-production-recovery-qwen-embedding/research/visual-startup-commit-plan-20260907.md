# 最小启动修复：一次性本地提交计划

状态：实现及独立检查完成，等待用户确认本批提交；尚未执行 git add/commit。

## 唯一提交

`fix(wechat): isolate visual execution and verify weekly queue retries`

- 仅在候选 `/root/projects/edu-ai-lead-agent/.trellis/worktrees/visual-quality-preview` 操作。
- 分支：`release/visual-quality-preview-20260907`；基线：`4c353b2d924403efda91a5ad1967a6f8c50eaa79`。
- 总计 20 个已知本轮文件（含本计划）；不 amend，不 push，不构建、不部署。
- 范围：策略/执行配置隔离、旧身份兼容、启动与三个队列用例、相应规范和检查证据。
- 用户回复“行 / 好的 / ok”确认本批后，主会话复核 HEAD、路径和内容，再执行一次提交。
- 新增代码或候选字节变化须重新核验，不自动纳入；本计划不是生产发布授权。

### 代码、配置与测试（8 个）

- `.env.example`
- `backend/app/core/config.py`
- `backend/app/infrastructure/official_account_runtime.py`
- `backend/app/official_account_worker_main.py`
- `backend/tests/unit/test_official_account_strict_visual_policy.py`
- `compose.yaml`
- `backend/tests/unit/test_official_account_strict_compose.py`
- `backend/tests/unit/test_official_account_weekly_queue_timing.py`

### 规范、任务与证据（12 个）

- `.trellis/spec/backend/official-account-strict-visual-pipeline.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/check.jsonl`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/design.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/implement.jsonl`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/implement.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/prd.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-integration-bug-analysis.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-release-plan-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-release-preflight-20260907.json`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-release-readiness-review-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-startup-check-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-startup-commit-plan-20260907.md`

## 本轮验证

- 独立联合测试 151 passed；6 个 Python 文件 Ruff/format 通过；3 个运行模块 strict mypy 通过。
- 实际 Compose→Settings 覆盖 15 个 Python 角色及关闭/严格/旧版三种配置；4 个完整身份一致。
- 三篇受控时钟排队：第三篇720秒超时后复用原任务，866秒观察全部成功；根累计1732秒。
- 根预算拒绝、独立 Article 后续完成、unknown 不重生成均有回归；不冒充实际模型性能。
- 线上实际 image window=300 被显式用于测试；既有900默认矛盾和历史全量门禁失败未扩展修改。
- 无付费调用、SSH、容器启动、生产写入、旧草稿替换或远端推送。
- 详见 `visual-startup-check-20260907.md`；父级恢复/Qwen任务保持开启。

## 候选内容 SHA-256（不含本计划自身，避免自引用）

- `.env.example` — `0097306df4ab35f66b5a5b516d73f075992fe9dfde61f89213cad0e02685392c`
- `.trellis/spec/backend/official-account-strict-visual-pipeline.md` — `e1864097956f0eba5cd63ef2b1cf51300aef7ec30abf60524a8f8467b8225b90`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/check.jsonl` — `d13afc75431e8a1d995a7a520d0238d4b7b676654b892ab434127c5075f30e8f`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/design.md` — `25fb588a2b321c9f92d17ca2f53b809efbc4359457111d0dd445d2d25a121667`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/implement.jsonl` — `c277ae528ec5ec95be1cbcd667d492a1ed5d880c4f1c10deaf8b31b7465dcb7a`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/implement.md` — `8c9fcd0a98a7e469c96023e89faf5ea004a788959531db84ce5e0c5bf95a56e5`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/prd.md` — `c415f3214ba3f5aed3a76b286b67370e25eb747ffd5ccd02a2b7a36d8c353ce3`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-integration-bug-analysis.md` — `5dd4451b9246a84555376ffb879e14e8124f93c071defbd7e160472fb9ac681d`
- `backend/app/core/config.py` — `3141f82cf3547fea2ff03b0f240571a013881c4017d260ffd5f64bca26d8a058`
- `backend/app/infrastructure/official_account_runtime.py` — `88a265b2a80c3a9e55ed1eca625075f20fae2b18bd296d0814f0d0b8b92560f8`
- `backend/app/official_account_worker_main.py` — `0bfd9ac9399bab37727dec793f7b976d59e4c4530e02fc0b353240c5b4ee0f6c`
- `backend/tests/unit/test_official_account_strict_visual_policy.py` — `b067a66c04c999a33aec5f211faa9b1b950cfdc205c15ed1e49bb9b87e2f9f2c`
- `compose.yaml` — `6d83b7587fb3a626cc390405faafe982884536811b781ab642dc3808375c1386`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-release-plan-20260907.md` — `2ba8115cf9bf5c77c99e264a16f77d114ce40316d081afe8a8f7a78e415eb573`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-release-preflight-20260907.json` — `1ec151ab85960dfac5e0fdcd85273d6a608ac2496cd71f49a8efb43c964f2fee`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-release-readiness-review-20260907.md` — `a8a16c5914865c4d9ee79b8a45f1b39f3766a67661f08a517588328eb494fb6c`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-startup-check-20260907.md` — `fbf776eb483a7d7da4a42f628e878ba31ed92d0cf79514dc5a2daf826c5e291b`
- `backend/tests/unit/test_official_account_strict_compose.py` — `55cb2dccadeefee46218b82c05a8f7e0d3af54e69908778f10a4d4b86927ae1e`
- `backend/tests/unit/test_official_account_weekly_queue_timing.py` — `92c91c9ae2930eedca0471c63efb978b318c5ef7cf4af4c081e18ab37070a0fd`

## 排除的主工作区

主工作区 HEAD `1f3b6a4da39faf77c78998b3697cf0dce79f7573`。以下全部不是本提交的 git add 目标；
其中本任务文档有主会话同步副本，也只提交候选中的明确文件。
原51个非Trellis脏文件/删除状态与此前哈希快照一致；Reviewer、评分、简历等 WIP 全部保留。
候选中没有无法归属的额外脏文件；如果用户要另纳入以下 WIP，需另定范围，不能顺带提交。

- `.env.example`（` M`）
- `.trellis/spec/backend/agent-pipeline.md`（` M`）
- `.trellis/spec/backend/content-slot-production.md`（` M`）
- `.trellis/spec/backend/index.md`（` M`）
- `.trellis/spec/backend/official-account-weekly-dag.md`（` M`）
- `.trellis/spec/backend/topic-selection.md`（` M`）
- `.trellis/tasks/08-20-brand-structured-parent-child-chunking/task.json`（` M`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/check.jsonl`（` M`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/design.md`（` M`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/implement.jsonl`（` M`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/implement.md`（` M`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/prd.md`（` M`）
- `backend/app/api/v1/routes/content_slots.py`（` M`）
- `backend/app/api/v1/routes/topic_selection_views.py`（` M`）
- `backend/app/application/services/topic_reranking.py`（` M`）
- `backend/app/core/config.py`（` M`）
- `backend/app/domain/content_slots.py`（` M`）
- `backend/app/domain/topic_rerank.py`（` M`）
- `backend/app/domain/topic_selection.py`（` M`）
- `backend/app/infrastructure/ai/topic_rerank.py`（` M`）
- `backend/app/infrastructure/db/content_slots.py`（` M`）
- `backend/app/infrastructure/db/topic_selection.py`（` M`）
- `backend/app/schemas/content_slots.py`（` M`）
- `backend/app/schemas/topic_rerank.py`（` M`）
- `backend/app/schemas/topic_selection.py`（` M`）
- `backend/evals/official_account_reviewer_live_ab/README.md`（` M`）
- `backend/evals/official_account_reviewer_live_ab/harness.py`（` M`）
- `backend/evals/official_account_reviewer_live_ab/metrics.py`（` M`）
- `backend/evals/official_account_reviewer_live_ab/models.py`（` M`）
- `backend/evals/topic_rerank/README.md`（` M`）
- `backend/evals/topic_rerank/canonical-report.json`（` M`）
- `backend/evals/topic_rerank/canonical-report.md`（` M`）
- `backend/evals/topic_rerank/cases.v1.jsonl`（` M`）
- `backend/evals/topic_rerank/runner.py`（` M`）
- `backend/tests/contract/test_topic_rerank_provider.py`（` M`）
- `backend/tests/integration/test_topic_selection_repositories.py`（` M`）
- `backend/tests/unit/test_content_slots.py`（` M`）
- `backend/tests/unit/test_official_account_reviewer_live_ab.py`（` M`）
- `backend/tests/unit/test_topic_rerank.py`（` M`）
- `backend/tests/unit/test_topic_selection_delivery.py`（` M`）
- `compose.yaml`（` M`）
- `deploy/release/tests/test_pipeline_contract.py`（` M`）
- `reports/wechat-digital-employee-briefing-2026-08-18.pdf`（` M`）
- `reports/wechat-digital-employee-briefing-2026-08-18.tex`（` M`）
- `scripts/doctor.sh`（` M`）
- `技术报告-v0.3.pdf`（` D`）
- `技术报告.pdf`（` D`）
- `文案驱动公司IP生图技术方案.md`（` D`）
- `朋友圈内容自动生成与企业微信分发技术方案.md`（` D`）
- `.trellis/spec/backend/official-account-strict-visual-pipeline.md`（`??`）
- `.trellis/spec/backend/official-account-visual-preview.md`（`??`）
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/check.jsonl`（`??`）
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/design.md`（`??`）
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/implement.jsonl`（`??`）
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/implement.md`（`??`）
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/prd.md`（`??`）
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/research/implementation-contract-summary.md`（`??`）
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/result.md`（`??`）
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/task.json`（`??`）
- `.trellis/tasks/09-02-reviewer-image-live-evidence/check.jsonl`（`??`）
- `.trellis/tasks/09-02-reviewer-image-live-evidence/design.md`（`??`）
- `.trellis/tasks/09-02-reviewer-image-live-evidence/implement.jsonl`（`??`）
- `.trellis/tasks/09-02-reviewer-image-live-evidence/implement.md`（`??`）
- `.trellis/tasks/09-02-reviewer-image-live-evidence/prd.md`（`??`）
- `.trellis/tasks/09-02-reviewer-image-live-evidence/research/implementation-readiness-review.md`（`??`）
- `.trellis/tasks/09-02-reviewer-image-live-evidence/research/model-panel-selection.md`（`??`）
- `.trellis/tasks/09-02-reviewer-image-live-evidence/research/pricing-source-2026-09-03.json`（`??`）
- `.trellis/tasks/09-02-reviewer-image-live-evidence/research/quality-gates.md`（`??`）
- `.trellis/tasks/09-02-reviewer-image-live-evidence/task.json`（`??`）
- `.trellis/tasks/09-02-reviewer-live-ab-execution/check.jsonl`（`??`）
- `.trellis/tasks/09-02-reviewer-live-ab-execution/design.md`（`??`）
- `.trellis/tasks/09-02-reviewer-live-ab-execution/implement.jsonl`（`??`）
- `.trellis/tasks/09-02-reviewer-live-ab-execution/implement.md`（`??`）
- `.trellis/tasks/09-02-reviewer-live-ab-execution/prd.md`（`??`）
- `.trellis/tasks/09-02-reviewer-live-ab-execution/task.json`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/capture-visual-preview-source.py`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/check-visual-preview-mobile.cjs`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-baseline-audit.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-commit-plan-20260907.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-integration-bug-analysis.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-preview-check.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-preview-live-evidence-20260907.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-preview-route.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-check-20260907.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-evidence-20260907.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-export-route.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-implementation-20260907.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-integration-route.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-release-plan-20260907.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-release-preflight-20260907.json`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-release-readiness-review-20260907.md`（`??`）
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-startup-check-20260907.md`（`??`）
- `backend/app/infrastructure/ai/official_account_reviewer_live_ab.py`（`??`）
- `backend/app/official_account_reviewer_live_ab_main.py`（`??`）
- `backend/evals/official_account_reviewer_live_ab/article_ledger.py`（`??`）
- `backend/evals/official_account_reviewer_live_ab/cases.v2.jsonl`（`??`）
- `backend/evals/official_account_reviewer_live_ab/cases.v2.manifest.json`（`??`）
- `backend/evals/official_account_reviewer_live_ab/model_panel_proxy.py`（`??`）
- `backend/evals/official_account_reviewer_live_ab/production_dataset.py`（`??`）
- `backend/tests/unit/test_official_account_reviewer_live_ab_app.py`（`??`）
- `backend/tests/unit/test_official_account_reviewer_live_ab_model_panel.py`（`??`）
- `reports/ip-digital-asset-hub-demo-guide-2026-09-02.pdf`（`??`）
- `reports/ip-digital-asset-hub-demo-guide-2026-09-02.tex`（`??`）
- `reports/ip-digital-asset-hub-live-demo-script-2026-09-02.pdf`（`??`）
- `reports/ip-digital-asset-hub-live-demo-script-2026-09-02.tex`（`??`）
