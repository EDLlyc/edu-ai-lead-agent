# Implementation Plan: 本地真实 IP 检索 V2/V3 成对评测

## Ordered checklist

- [x] 1. 加载 Trellis backend/quality/IP asset 规范，记录相关文件与当前 dirty 边界。
- [x] 2. 为 `GroundedRetrievalRunV2` 增加严格的 V2/V3 paired scorer、聚合与 bootstrap 报告。
- [x] 3. 增加 paired JSON/Markdown renderer、runner 命令和清晰的本地 Make 入口，保持 V1 兼容。
- [x] 4. 增加版本/身份/覆盖/no-answer/bootstrap/隐私/报告的 focused tests。
- [x] 5. 更新 Grounded README 与 backend spec，声明真实 provider、Seed 和本地证据边界。
- [x] 6. 运行 task-scoped tests、Ruff、Mypy、Grounded gate、`make eval-check` 和 diff 检查。
- [ ] 7. 提交 comparator 代码；不包含工作区其他任务改动，不推送。
- [ ] 8. 再次运行只读 preflight并记录业务 search aggregate 快照。
- [ ] 9. 在忽略目录中顺序完成 Alibaba Seed V2 的 hybrid-v2 与 hybrid-v3-rrf 各 124-query run。
- [ ] 10. 生成两个 selective report、paired JSON/Markdown、两个 safe manifest，并完成 identity/privacy 校验。
- [ ] 11. 确认业务 search aggregate 未变化，记录指标、置信区间、失败/降级、耗时与请求数。
- [ ] 12. Trellis 收尾、归档和本地提交；不推送、不部署。

## Validation commands

```bash
make ip-asset-grounded-eval-check

conda run --name edu-ai pytest \
  backend/tests/unit/test_ip_asset_retrieval_grounded_eval.py -q --no-cov

conda run --name edu-ai ruff check \
  backend/evals/ip_asset_retrieval_grounded \
  backend/tests/unit/test_ip_asset_retrieval_grounded_eval.py

conda run --name edu-ai ruff format --check \
  backend/evals/ip_asset_retrieval_grounded \
  backend/tests/unit/test_ip_asset_retrieval_grounded_eval.py

conda run --name edu-ai mypy backend/evals/ip_asset_retrieval_grounded
make eval-check
git diff --check
```

计划中的真实运行命令将在实现后的 README/Make 入口中冻结；所有输出目标均位于
`output/evals/ip-asset-v2-v3-<timestamp>/`。

## Risky files and rollback points

- `backend/evals/ip_asset_retrieval_grounded/metrics.py` / 新 V2 comparator：不得改变现有 V1 指标语义。
- `backend/evals/ip_asset_retrieval_grounded/runner.py`：新增命令必须保持 frozen/legacy 命令兼容。
- `backend/evals/ip_asset_retrieval_grounded/reporting.py`：禁止把 query、grade、score 或路径写入报告。
- `Makefile`：live 命令不能成为 `eval-check` prerequisite。
- 工作区其他 dirty 文件属于并行任务；不格式化、不暂存、不回退。

## Follow-up checks before implementation start

- 用户批准本 PRD/设计/实施范围，并明确接受真实 Alibaba Embedding 预计 248 次外部请求。
- 运行 `task.py start ip-asset-live-paired-evaluation`。
- 运行 `trellis-before-dev` 获取 backend/quality/IP asset 开发上下文。
- 重新检查相关路径 diff，确保 comparator 变更可与其他工作区修改隔离提交。
