# Implementation Plan: IP 检索真实图库 Seed Eval V1

## Ordered checklist

- [x] 1. 用户批准本次删除页面后的最终方案；运行 `task.py start`，加载 `trellis-before-dev` 和 curated manifests，记录 task-scoped dirty diff。
- [x] 2. 更新 backend IP asset/quality specs，写明 grounded seed、真实检索 no-telemetry、live/provider 与 synthetic CI 双轨契约。
- [x] 3. 新建 strict grounded models/loaders/tests，定义 query、seed matrix、safe asset snapshot、run observation、report 和禁止字段。
- [x] 4. 编写 exactly 100 条脱敏 queries，固定 80/20 split、类别配额、no-answer 和 space-station query；先通过 query-only validation。
- [x] 5. 逐张检查 41 张真实图片，完成 exactly 4,100 个 `codex_seed` grades；运行完整矩阵、分布、no-answer consistency、敏感字段和 hash 检查。
- [x] 6. 实现 safe 41-asset snapshot/fingerprint 与 live dynamic mapping preflight；缺失、重复、非 ready/shared 或 embedding identity drift 时 fail closed。
- [x] 7. 为 `IpAssetService` 增加内部 evaluation no-telemetry boundary，复用完整生产检索/排序路径，确保普通 HTTP search 语义完全不变。
- [x] 8. 实现 live run observation、V2/V3 离线 paired compare、Recall@3/5、MRR@5、nDCG@5、no-answer 轨道和固定 seed bootstrap 95% CI。
- [x] 9. 实现 canonical seed report、JSON/Markdown live report、可选 offline review template、Make targets 和 README；live provider 不进入普通 PR gate。
- [x] 10. 增加 service/eval/privacy/canonical tests；focused tests、全局 lint、scoped format/typecheck、`make eval-check` 和 `git diff --check` 通过。完整 backend gate 已执行，剩余失败均来自 task 外并行改动，记录于 live evidence/handoff。
- [x] 11. 在已授权的本地环境运行真实 41 图 preflight 与 grounded evaluation，记录 active search identity、coverage/failure 和 seed metrics；不输出凭据/路径/向量/provider body。
- [x] 12. 确认任务 diff 中没有任何 frontend、API route、Alembic/ORM 或站内 evaluation 页面变更，完成最终检查和提交。

## Validation commands

```bash
cd backend && conda run --name edu-ai python -m evals.ip_asset_retrieval_grounded.runner validate-seed
cd backend && conda run --name edu-ai python -m evals.ip_asset_retrieval_grounded.runner check-canonical
cd backend && conda run --name edu-ai python -m evals.ip_asset_retrieval.runner --check

conda run --name edu-ai pytest \
  backend/tests/unit/test_ip_asset_retrieval_grounded_eval.py \
  backend/tests/unit/test_ip_asset_service.py \
  -q --no-cov

conda run --name edu-ai ruff format --check \
  backend/evals/ip_asset_retrieval_grounded \
  backend/tests/unit/test_ip_asset_retrieval_grounded_eval.py

conda run --name edu-ai ruff check \
  backend/evals/ip_asset_retrieval_grounded \
  backend/tests/unit/test_ip_asset_retrieval_grounded_eval.py

conda run --name edu-ai mypy \
  backend/evals/ip_asset_retrieval_grounded

make eval-check
git diff --check
```

显式 live 检查：

```bash
make ip-asset-grounded-eval-preflight
make ip-asset-grounded-eval
```

## Review gates

### Dataset

- exactly 100 queries、80 dev / 20 holdout、类别覆盖、固定 space-station query。
- exactly 41 safe catalog refs、100×41=4,100 unique grades、0..3、source=`codex_seed`。
- no-answer 与 grade consistency；无敏感字段或私有图片衍生物。

### Retrieval

- labels/rubric 不进入 production rank input。
- runner 复用生产 search selector，不维护第二份 V2/V3 算法。
- live preflight 在 provider call 前验证完整 41 图和 embedding identity。
- evaluation 前后普通 search aggregate snapshot 不变；HTTP search 测试仍证明正常增量。

### Metrics/report

- grade>=2 只定义 usable relevance，nDCG 保留 graded gain。
- no-answer 不进入普通 Recall/MRR 宏平均；failure/coverage 单列。
- bootstrap 固定 seed 可重现，paired sample count 和 CI direction 明确。
- holdout 普通报告只出 aggregate；所有报告明确 `seed` 及局限。

### Scope

- 无 `/ip-assets/evaluation`、无 frontend 文件、无新 API route、无 migration/ORM/annotation DB。
- 原 provider-free 41-case suite、IP 网站和业务搜索聚合行为不回归。

## Risky files and rollback points

- `backend/app/application/services/ip_assets.py`：只增加内部 no-telemetry evaluation boundary；默认普通 search path 不变，可独立回滚。
- `backend/evals/ip_asset_retrieval_grounded/`：query、seed、canonical 和 hashes 必须成组 review/rollback。
- `Makefile`：新增独立 targets，不重命名旧 `ip-asset-retrieval-eval`，live target 不加入 provider-free PR gate。
- `.trellis/spec/backend/ip-asset-hub.md` / `quality-guidelines.md`：只记录已实现契约，不提前声称 human Gold。
- 工作树有并行任务；禁止批量格式化或修复无关 canonical。

## Follow-up checks before `task.py start`

- 用户明确批准本次 backend-only 最终规划。
- 运行 `trellis-before-dev`，加载 `implement.jsonl` 中 backend specs/research。
- 用 `git status --short` 记录相关文件已有修改；有重叠时先保留并适配，不重置。
- 确认私有 41 图可读且仅用于本地视觉检查，任何 contact sheet/临时描述不进入提交。
