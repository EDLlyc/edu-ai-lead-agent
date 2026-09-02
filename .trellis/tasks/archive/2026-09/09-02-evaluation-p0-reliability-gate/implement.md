# Implementation Plan: 评测 P0 可靠性门禁

## Ordered checklist

- [x] 1. 修复 `topic_rerank` evaluator 的优先级规则身份，增加 priority fixture 组分离断言。
- [x] 2. 更新/补充选题评测单元测试，确认两个 group 和 `[1, 2]` 顺序，并重建 canonical 报告。
- [x] 3. 按现有 IP retrieval schema 添加“小赛和赛先生在空间站”脱敏 case。
- [x] 4. 增加精确查询存在性测试，显式重建并审查 IP canonical JSON/Markdown。
- [x] 5. 在 Makefile 增加 checked Agent、数字 IP、统一 `eval-check` 及完整 `.PHONY`。
- [x] 6. 将 `eval-check` 接入云效 quality stage，并增加 pipeline contract 断言。
- [x] 7. 在 README 记录统一 provider-free 评测入口和真实性边界。
- [x] 8. 运行 focused checks、七套 canonical gate、静态检查和 diff 检查；记录任何非任务失败。
- [x] 9. 将 Grounded Seed V2 的 authoring、strict validation、canonical drift 三项检查接入
      `ip-asset-grounded-eval-check`，并通过顶层 `make eval-check` 验证失败传播。
- [x] 10. 修复干净 CI 缺少私有视觉清单时 V1 authoring 检查失败的问题，增加显式
      frozen-artifact 模式，并在 Git index 快照内重跑完整 `make eval-check`。

## Validation record (2026-09-02)

- 当前 V5 工作树的 `make eval-check`: 7/7 runners passed, 188 provider-free cases total.
- 为本次评测提交单独导出的纯 Git-index/V4 快照：7/7 runners、186 cases 全部通过；
  其中 topic rerank 为 V4 8/8，未包含并行 V5 的 tie/malformed 两个 case。
- Focused evaluator/pipeline tests: 22 passed; the broader planned focused set: 58 passed.
- Task-scoped Ruff format/lint, mypy, canonical drift, Make dry-run, and `git diff --check`: passed.
- Full backend Ruff lint: passed.
- Full `make backend-check` remains red because of unrelated in-progress workspace changes:
  two pre-existing format drifts, two Literal mypy errors in
  `backend/app/local_exact_target_selection.py`, and 27 tests in the separate V5/config work
  (1848 other backend tests passed). No unrelated files were reformatted or repaired by this task.
- Grounded Seed reviewer gate passed all six ordered checks: Seed V1 has 100 queries and 4,100
  judgments; Seed V2 has 124 queries and 5,084 judgments; both canonical reports match.
- The strengthened pipeline contract locks the exact seven offline runner prerequisites plus the
  Grounded Seed target. `make PY_RUN=false eval-check` exits nonzero at the first child target,
  confirming failure propagation.
- The full pipeline contract has 13 passing tests and one unrelated failure: the parallel
  `20260902_0044` migration is newer than the reviewed `20260901_0042` compatibility declaration.
  The migration work was not modified by this task.
- The current full backend typecheck has five unrelated errors in
  `backend/app/local_exact_target_selection.py` and
  `backend/app/infrastructure/official_account_reviewer_governance.py`; the scoped integration
  test body passes strict mypy when the repository's untyped PyYAML import is excluded (tests are
  outside the configured backend typecheck scope).
- 纯 Git-index 快照不含私有视觉清单；Grounded frozen V1、Seed V2 与完整 `make eval-check`
  均通过。依赖私有清单的原 `authoring --check` 仍显式失败，未被静默弱化。

## Validation commands

```bash
make eval-check

conda run --name edu-ai pytest \
  backend/tests/unit/test_topic_rerank.py \
  backend/tests/unit/test_ip_asset_retrieval_eval.py \
  deploy/release/tests/test_pipeline_contract.py \
  -q --no-cov

conda run --name edu-ai ruff check \
  backend/evals/topic_rerank \
  backend/evals/ip_asset_retrieval \
  backend/tests/unit/test_topic_rerank.py \
  backend/tests/unit/test_ip_asset_retrieval_eval.py \
  deploy/release/tests/test_pipeline_contract.py

conda run --name edu-ai ruff format --check \
  backend/evals/topic_rerank \
  backend/evals/ip_asset_retrieval \
  backend/tests/unit/test_topic_rerank.py \
  backend/tests/unit/test_ip_asset_retrieval_eval.py \
  deploy/release/tests/test_pipeline_contract.py

conda run --name edu-ai mypy \
  backend/evals/topic_rerank \
  backend/evals/ip_asset_retrieval

git diff --check
```

## Risky files and rollback points

- `backend/evals/topic_rerank/runner.py` 与 canonical 报告：工作区已有用户 V5 修改；只调整 evaluator 配置与断言，禁止回退生产代码。
- `backend/evals/ip_asset_retrieval/cases.v1.jsonl` 与 canonical 报告：数据集 hash/指标变化必须成组提交或成组回滚。
- `Makefile`：保留现有目标语义，新增 gate 不重命名单项入口。
- `deploy/yunxiao/pipeline.yaml`：只增加 provider-free gate；不能改变发布、部署或凭据开关。

## Follow-up checks before implementation start

- 确认用户批准本 PRD、设计和实施范围。
- 运行 `trellis-before-dev` 加载 backend/spec/CI 约束。
- 记录当前相关文件的 dirty diff，后续只叠加任务改动，不覆盖用户已有修改。
- 通过独立 `trellis-implement` 与 `trellis-check` 子代理完成 Seed V2 门禁接线和交叉审查；
  `implement.jsonl` / `check.jsonl` 只注入质量门与 IP Grounded 评测规范。
