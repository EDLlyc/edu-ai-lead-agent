# 微信公众号严格图片链路：一次性提交计划

状态：**待用户确认；尚未暂存、提交或推送。** 日期：2026-09-07。

## 提交边界与依据

仅在隔离工作树 `/root/projects/edu-ai-lead-agent/.trellis/worktrees/visual-quality-preview` 操作。
分支：`release/visual-quality-preview-20260907`；准确基线：`218015e44cc07221bdefeb449da8a8371354712e`。
主工作区的未提交改动、私有图片/预览产物、临时日志和依赖目录均不进入本批提交。
下方清单覆盖隔离工作树本次全部改动；起草时暂存区为空，无不明候选改动。

本次已完成实现、独立复核、实际 gzh/Chromium 离线检查及规范更新。
独立结论是 `IMPLEMENTATION_CHECK_PASS`（相对基线），不是 `SAFE_TO_DEPLOY`：
81 项严格链路测试通过（含 16 项真实 PostgreSQL 测试）；全量后端 2,124 通过 /
34 失败（33 项历史失败及 1 项基线可复现的集成环境影响）。前端、发布测试的
历史例外详见 [完整复核](visual-production-check-20260907.md)。

审核后的运行时集合 SHA-256：
`6ad46cc5924318ba56a33240184b780b970196b6386b8030bbaeea48d2cc1441`。
收尾没有修改运行时；仅同步文档及更准确的回滚规范。
两项临时测试容器和测试依赖链接已清理，生产服务、现有三篇草稿和预览原件未改动。

## Proposed commits（按顺序）

### 1. `feat(wechat): enforce durable native visual reviews for new drafts`

60 个文件。包括已验收的独立预览工具与适配器、前瞻性正式链路、数据库迁移、
最终上传字节审图、原图来源、Xiaosai 排版、冻结重试身份、生成的 API 契约、
对应测试和规范。迁移声明只描述实现兼容性，不是发布授权。

精确文件列表（均相对上述隔离工作树）：

- `.env.example`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/official-account-strict-visual-pipeline.md`
- `.trellis/spec/backend/official-account-visual-preview.md`
- `backend/alembic/versions/20260907_0043_strict_visual_pipeline.py`
- `backend/app/api/v1/routes/official_account_local.py`
- `backend/app/application/ports/image_generation.py`
- `backend/app/application/ports/official_account_local.py`
- `backend/app/application/ports/official_account_strict_visual.py`
- `backend/app/application/ports/official_account_weekly_production.py`
- `backend/app/application/services/official_account_local.py`
- `backend/app/application/services/official_account_strict_prepared.py`
- `backend/app/application/services/official_account_strict_visual.py`
- `backend/app/application/services/official_account_visual_generation.py`
- `backend/app/application/services/official_account_visual_preview.py`
- `backend/app/application/services/official_account_weekly_production.py`
- `backend/app/application/services/wechat_official_account_draft.py`
- `backend/app/core/config.py`
- `backend/app/domain/official_account_local.py`
- `backend/app/domain/official_account_strict_layout.py`
- `backend/app/domain/official_account_upload_media.py`
- `backend/app/domain/official_account_visual_pipeline.py`
- `backend/app/infrastructure/ai/factory.py`
- `backend/app/infrastructure/ai/image_generation.py`
- `backend/app/infrastructure/ai/image_validation.py`
- `backend/app/infrastructure/ai/official_account_visual_strict.py`
- `backend/app/infrastructure/db/models.py`
- `backend/app/infrastructure/db/official_account_local.py`
- `backend/app/infrastructure/db/official_account_strict_visual.py`
- `backend/app/infrastructure/db/official_account_weekly_production.py`
- `backend/app/infrastructure/official_account_media.py`
- `backend/app/infrastructure/official_account_runtime.py`
- `backend/app/infrastructure/wechat_official_account/prepared_artifacts.py`
- `backend/app/official_account_visual_preview_main.py`
- `backend/app/official_account_weekly_scheduler_main.py`
- `backend/app/official_account_worker_main.py`
- `backend/openapi.json`
- `backend/tests/integration/test_execution_governance_migration.py`
- `backend/tests/integration/test_governance_migration_downgrade.py`
- `backend/tests/integration/test_governance_migrations.py`
- `backend/tests/integration/test_ip_asset_personal_migration.py`
- `backend/tests/integration/test_ip_asset_prompt_migration.py`
- `backend/tests/integration/test_ip_asset_search_aggregates.py`
- `backend/tests/integration/test_migrations.py`
- `backend/tests/integration/test_official_account_local.py`
- `backend/tests/integration/test_official_account_strict_visual.py`
- `backend/tests/integration/test_official_account_weekly_dag_migration.py`
- `backend/tests/integration/test_visual_input_migration.py`
- `backend/tests/unit/test_content_worker_validation_wiring.py`
- `backend/tests/unit/test_image_validation_ai.py`
- `backend/tests/unit/test_official_account_preview_image_geometry.py`
- `backend/tests/unit/test_official_account_strict_prepared.py`
- `backend/tests/unit/test_official_account_strict_visual_policy.py`
- `backend/tests/unit/test_official_account_strict_visual_worker.py`
- `backend/tests/unit/test_official_account_visual_preview.py`
- `backend/tests/unit/test_official_account_weekly_production.py`
- `deploy/release/migration-compatibility.json`
- `deploy/release/tests/test_pipeline_contract.py`
- `frontend/src/lib/api/generated/schema.d.ts`
- `scripts/doctor.sh`

此批文件内容指纹：`27501af65d10929362612a12ba2f8154f33fdd2932faba6145100fa1cbec3bfe`。

### 2. `docs(wechat): record accepted preview and strict integration checks`

18 个文件。保存需求、设计、实现上下文、已接受预览、独立检查和收尾证据；
不是父任务归档或部署完成记录。候选 jsonl 有意去掉本分支不存在的两个旧阶段引用，
不从主工作区导入未上线的 substantive-topic 改动；根工作区保留其原有完整上下文。

精确文件列表：

- `.trellis/tasks/09-05-production-recovery-qwen-embedding/check.jsonl`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/design.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/implement.jsonl`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/implement.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/prd.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/capture-visual-preview-source.py`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/check-visual-preview-mobile.cjs`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-baseline-audit.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-commit-plan-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-integration-bug-analysis.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-preview-check.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-preview-live-evidence-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-preview-route.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-check-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-evidence-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-export-route.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-implementation-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-integration-route.md`

除本计划自身外的此批文件内容指纹：`de02d107410cfa5eec59a8129b13c625798be9dc956420eb725efb435d5243d6`。
本计划不参与自身哈希，避免自引用；确认后仍须检查计划内容未被另行修改。

内容指纹算法：按文件路径的字典序，对每个文件计算 SHA-256，拼接
`<sha256>  <relative-path>\n`，再对拼接后的 UTF-8 字节计算 SHA-256。
提交前重查路径集合、基线、暂存区和两批内容指纹；若出现未知改动先停止，不静默扩展。

## 主工作区排除项

### 本次记录的镜像副本（不在任何提交中）

以下路径属于 `/root/projects/edu-ai-lead-agent`，不是候选工作树。对应视觉任务记录通过上面的
候选副本提交；不得从根工作区重复暂存或整库构建。
本计划创建后根工作区也有同名镜像，亦排除。

- `.trellis/spec/backend/official-account-strict-visual-pipeline.md`
- `.trellis/spec/backend/official-account-visual-preview.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/check.jsonl`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/design.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/implement.jsonl`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/implement.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/prd.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/capture-visual-preview-source.py`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/check-visual-preview-mobile.cjs`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-baseline-audit.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-integration-bug-analysis.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-preview-check.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-preview-live-evidence-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-preview-route.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-check-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-evidence-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-export-route.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-implementation-20260907.md`
- `.trellis/tasks/09-05-production-recovery-qwen-embedding/research/visual-production-integration-route.md`

### Unrecognized dirty files（不在任何提交中，保持原样）

以下为主工作区完整的其余未提交文件清单。包含其他任务、Reviewer/评分、
配置/Compose、报告和已有删除项；可能与候选中的相对路径重名，但内容不相同，
不得据此从主工作区暂存、覆盖或回退。全部默认排除，用户可在确认时指出边界问题。

- `.env.example`
- `.trellis/spec/backend/agent-pipeline.md`
- `.trellis/spec/backend/content-slot-production.md`
- `.trellis/spec/backend/index.md`
- `.trellis/spec/backend/official-account-weekly-dag.md`
- `.trellis/spec/backend/topic-selection.md`
- `.trellis/tasks/08-20-brand-structured-parent-child-chunking/task.json`
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/check.jsonl`
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/design.md`
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/implement.jsonl`
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/implement.md`
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/prd.md`
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/research/implementation-contract-summary.md`
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/result.md`
- `.trellis/tasks/08-20-llm-multidimensional-news-scoring/task.json`
- `.trellis/tasks/09-02-reviewer-image-live-evidence/check.jsonl`
- `.trellis/tasks/09-02-reviewer-image-live-evidence/design.md`
- `.trellis/tasks/09-02-reviewer-image-live-evidence/implement.jsonl`
- `.trellis/tasks/09-02-reviewer-image-live-evidence/implement.md`
- `.trellis/tasks/09-02-reviewer-image-live-evidence/prd.md`
- `.trellis/tasks/09-02-reviewer-image-live-evidence/research/implementation-readiness-review.md`
- `.trellis/tasks/09-02-reviewer-image-live-evidence/research/model-panel-selection.md`
- `.trellis/tasks/09-02-reviewer-image-live-evidence/research/pricing-source-2026-09-03.json`
- `.trellis/tasks/09-02-reviewer-image-live-evidence/research/quality-gates.md`
- `.trellis/tasks/09-02-reviewer-image-live-evidence/task.json`
- `.trellis/tasks/09-02-reviewer-live-ab-execution/check.jsonl`
- `.trellis/tasks/09-02-reviewer-live-ab-execution/design.md`
- `.trellis/tasks/09-02-reviewer-live-ab-execution/implement.jsonl`
- `.trellis/tasks/09-02-reviewer-live-ab-execution/implement.md`
- `.trellis/tasks/09-02-reviewer-live-ab-execution/prd.md`
- `.trellis/tasks/09-02-reviewer-live-ab-execution/task.json`
- `backend/app/api/v1/routes/content_slots.py`
- `backend/app/api/v1/routes/topic_selection_views.py`
- `backend/app/application/services/topic_reranking.py`
- `backend/app/core/config.py`
- `backend/app/domain/content_slots.py`
- `backend/app/domain/topic_rerank.py`
- `backend/app/domain/topic_selection.py`
- `backend/app/infrastructure/ai/official_account_reviewer_live_ab.py`
- `backend/app/infrastructure/ai/topic_rerank.py`
- `backend/app/infrastructure/db/content_slots.py`
- `backend/app/infrastructure/db/topic_selection.py`
- `backend/app/official_account_reviewer_live_ab_main.py`
- `backend/app/schemas/content_slots.py`
- `backend/app/schemas/topic_rerank.py`
- `backend/app/schemas/topic_selection.py`
- `backend/evals/official_account_reviewer_live_ab/README.md`
- `backend/evals/official_account_reviewer_live_ab/article_ledger.py`
- `backend/evals/official_account_reviewer_live_ab/cases.v2.jsonl`
- `backend/evals/official_account_reviewer_live_ab/cases.v2.manifest.json`
- `backend/evals/official_account_reviewer_live_ab/harness.py`
- `backend/evals/official_account_reviewer_live_ab/metrics.py`
- `backend/evals/official_account_reviewer_live_ab/model_panel_proxy.py`
- `backend/evals/official_account_reviewer_live_ab/models.py`
- `backend/evals/official_account_reviewer_live_ab/production_dataset.py`
- `backend/evals/topic_rerank/README.md`
- `backend/evals/topic_rerank/canonical-report.json`
- `backend/evals/topic_rerank/canonical-report.md`
- `backend/evals/topic_rerank/cases.v1.jsonl`
- `backend/evals/topic_rerank/runner.py`
- `backend/tests/contract/test_topic_rerank_provider.py`
- `backend/tests/integration/test_topic_selection_repositories.py`
- `backend/tests/unit/test_content_slots.py`
- `backend/tests/unit/test_official_account_reviewer_live_ab.py`
- `backend/tests/unit/test_official_account_reviewer_live_ab_app.py`
- `backend/tests/unit/test_official_account_reviewer_live_ab_model_panel.py`
- `backend/tests/unit/test_topic_rerank.py`
- `backend/tests/unit/test_topic_selection_delivery.py`
- `compose.yaml`
- `deploy/release/tests/test_pipeline_contract.py`
- `reports/ip-digital-asset-hub-demo-guide-2026-09-02.pdf`
- `reports/ip-digital-asset-hub-demo-guide-2026-09-02.tex`
- `reports/ip-digital-asset-hub-live-demo-script-2026-09-02.pdf`
- `reports/ip-digital-asset-hub-live-demo-script-2026-09-02.tex`
- `reports/wechat-digital-employee-briefing-2026-08-18.pdf`
- `reports/wechat-digital-employee-briefing-2026-08-18.tex`
- `scripts/doctor.sh`
- `技术报告-v0.3.pdf`
- `技术报告.pdf`
- `文案驱动公司IP生图技术方案.md`
- `朋友圈内容自动生成与企业微信分发技术方案.md`

## 一次性确认及后续边界

回复“行”或“ok”表示按以上两批准确文件清单执行本地提交。
执行时仅显式 `git add <files>`，然后依次新建上述两个提交；不 amend、不 push。
不启动 CI/发布事务，不迁移生产数据库，不启用新配置，不重跑旧周刊，不替换草稿，
不群发、不额外调用付费模型。拒绝分组则停止，由用户手动提交。

本次确认不构成线上发布许可。后续另行准备不可变源码/镜像、备份、当前安全窗口、
基线门禁例外处置、兼容回滚和真实三篇文章整体时限验证，再报告可执行的发布方案。
