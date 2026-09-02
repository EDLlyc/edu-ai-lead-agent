# Implementation Plan: 本地真实 IP 检索 V2/V3 成对评测

## Ordered checklist

- [x] 1. 加载 Trellis backend/quality/IP asset 规范，记录相关文件与当前 dirty 边界。
- [x] 2. 为 `GroundedRetrievalRunV2` 增加严格的 V2/V3 paired scorer、聚合与 bootstrap 报告。
- [x] 3. 增加 paired JSON/Markdown renderer、runner 命令和清晰的本地 Make 入口，保持 V1 兼容。
- [x] 4. 增加版本/身份/覆盖/no-answer/bootstrap/隐私/报告的 focused tests。
- [x] 5. 更新 Grounded README 与 backend spec，声明真实 provider、Seed 和本地证据边界。
- [x] 6. 运行 task-scoped tests、Ruff、Mypy、Grounded gate、`make eval-check` 和 diff 检查。
- [x] 7. 提交 comparator 代码；不包含工作区其他任务改动，不推送。
- [x] 8. 再次运行只读 preflight并记录业务 search aggregate 快照。
- [x] 9. 在忽略目录中顺序完成 Alibaba Seed V2 的 hybrid-v2 与 hybrid-v3-rrf 各 124-query run。
- [x] 10. 生成两个 selective report、paired JSON/Markdown、两个 safe manifest，并完成 identity/privacy 校验。
- [x] 11. 确认业务 search aggregate 未变化，记录指标、置信区间、失败/降级、耗时与请求数。
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

## Local live evidence (2026-09-02)

- Code commit: `82b488a`; output directory:
  `output/evals/ip-asset-v2-v3-20260902-82b488a/` (Git ignored).
- Preflight: 41/41 approved assets mapped to ready/shared rows with the configured compatible
  `qwen3-vl-embedding` vectors.
- Baseline: `igr_8e8ae94128f793661fb3`, 124 Alibaba requests, 124 observations, 0 failures,
  23,789 ms. Candidate: `igr_4be2fad59b443fd5f6d3`, 124 Alibaba requests, 124 observations,
  0 failures, 29,840 ms.
- Overall answerable deltas (V3 minus V2): Recall@3 `+0.0057`
  (95% CI `[-0.0083, +0.0201]`), Recall@5 `+0.0027`
  (`[-0.0181, +0.0247]`), MRR@5 `+0.0254` (`[-0.0009, +0.0560]`), nDCG@5
  `+0.0093` (`[-0.0120, +0.0318]`). These intervals do not establish a decisive overall win.
- Holdout Recall@5 changed by `-0.0231` (`[-0.0556, 0.0000]`) and holdout nDCG@5 by
  `-0.0223` (`[-0.0605, +0.0063]`), so V3 must not be promoted from this run.
- Raw no-answer false-positive rate was `0.9667` for both strategies. The diagnostic selective
  policy reduced it to zero but retained only `0.1429` dev / `0.1923` holdout decision coverage;
  it is too conservative and remains inactive.
- Both runs had the same 118 semantic / 6 `degraded_metadata` observations. Read-only diagnosis
  proved all six were zero-candidate hard-filter combinations, not missing vectors or provider
  failures: the 41-asset metadata has no `portrait_avatar`, `meme_sticker`, or
  `transparent_cutout` rows. The current `partial_index` reason therefore also conflates an empty
  filtered corpus with incomplete vector coverage; fixing filter semantics/reason taxonomy is a
  separate production-retrieval task.
- Business aggregate remained byte-identical before and after:
  `3|9|a574d12f8af9f04af09453bd0cad8951`. Both safe manifests validated. A recursive scan of all
  seven JSON artifacts found no prohibited exact keys; all output files had zero exact query-text
  matches and zero dynamic UUID matches.
- Paired report SHA-256:
  `88a905e3c07cd09bfd30a10fb204ff045e946cce6061a56a15763e044aa5b7e3` (JSON) and
  `ea33b1ddae198e76bfffd19fff27c7fb55b13ad41640c5518420eac65e7c4af8` (Markdown).

## Follow-up checks before implementation start

- 用户批准本 PRD/设计/实施范围，并明确接受真实 Alibaba Embedding 预计 248 次外部请求。
- 运行 `task.py start ip-asset-live-paired-evaluation`。
- 运行 `trellis-before-dev` 获取 backend/quality/IP asset 开发上下文。
- 重新检查相关路径 diff，确保 comparator 变更可与其他工作区修改隔离提交。
