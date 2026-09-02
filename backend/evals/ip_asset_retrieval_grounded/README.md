# Grounded IP asset retrieval evaluation

这是一套后端离线评测，不是站内标注产品，也不提供 `/ip-assets/evaluation` 页面、API 或数据库表。

冻结资产包括 41 张 approved IP 图的安全快照、100 条脱敏中文查询（80 dev / 20 holdout），以及
Codex 逐图视觉检查形成的 4,100 个 0–3 相关性判断。标签来源固定为 `codex_seed`，不是人工
Gold；报告不声称人工一致性、线上用户效果或业务提升。

## 日常无网络检查

```bash
make ip-asset-grounded-eval-check
```

该命令仅使用 Git 内冻结文件，依次检查 V1 的固定 hash、查询/判断的确定性 authoring bytes、
strict schema、完整矩阵和 canonical seed report，再检查 V2 authoring、strict schema 与
canonical report。它不需要被忽略的私有素材清单，不访问数据库或模型服务，也不会改写 canonical
文件。

需要根据私有素材清单完整重建并核对 V1 安全资产快照时，显式运行：

```bash
PYTHONPATH=backend conda run --name edu-ai \
  python -m evals.ip_asset_retrieval_grounded.authoring --check \
  --manifest private/brand-materials/visual-assets.manifest.json
```

该完整检查保留私有清单依赖，不属于干净 checkout 的 CI 门禁。

## 显式真实运行

```bash
make ip-asset-grounded-eval-preflight
make ip-asset-grounded-eval-live \
  SEARCH_VERSION=ip-asset-hybrid-v3-rrf \
  OUTPUT=/tmp/ip-grounded-v3.json
make ip-asset-grounded-eval-report \
  RUN=/tmp/ip-grounded-v3.json \
  OUTPUT_JSON=/tmp/ip-grounded-v3-report.json \
  OUTPUT_MARKDOWN=/tmp/ip-grounded-v3-report.md
```

Preflight 在任何查询 embedding 调用前验证安全快照未漂移、41:41 动态图库映射、ready/shared
状态和兼容向量完整性。Live runner 复用生产 filter extraction、metadata ranking、向量检索与
V2/V3 selector，但走内部 no-telemetry boundary，不增加业务搜索聚合。

V2/V3 成对比较：

```bash
make ip-asset-grounded-eval-compare \
  BASELINE=/tmp/ip-grounded-v2.json \
  CANDIDATE=/tmp/ip-grounded-v3.json \
  OUTPUT_JSON=/tmp/ip-grounded-comparison.json \
  OUTPUT_MARKDOWN=/tmp/ip-grounded-comparison.md
```

报告包含 Recall@3/5、MRR@5、nDCG@5、类别/split/mode、coverage/failure、无答案的正确拒答与
误报率，以及固定随机种子的 query-level paired bootstrap 95% CI。Run 文件只保存安全 catalog
ref 和版本身份，不保存向量、score、原图位置、provider body、动态 UUID 或用户标识。

## Codex Seed V2 与选择性检索

Seed V2 是与 V1 并存的增量数据集，不覆盖 V1 文件。它包含 41 张 approved 图片、124 条查询
（98 dev / 26 holdout）、30 条 no-answer 和完整的 5,084 个 `codex_seed_v2` 判断；其中新增
24 条 no-answer/near-miss 查询（18 dev / 6 holdout）。同一个 Codex 完成逐图复核，因此它仍然
只是 Seed，不是人工 Gold、独立复核或人类一致性证据。review ledger 明确冻结本轮盲复核的
V1 no-answer、组合约束、grade 1/2 边界与固定空间站查询范围，并完整记录实际改分。

日常无 provider 检查：

```bash
PYTHONPATH=backend conda run --name edu-ai \
  python -m evals.ip_asset_retrieval_grounded.authoring --check-v2
PYTHONPATH=backend conda run --name edu-ai \
  python -m evals.ip_asset_retrieval_grounded.runner validate-seed-v2
PYTHONPATH=backend conda run --name edu-ai \
  python -m evals.ip_asset_retrieval_grounded.runner check-v2-canonical
```

`run-live-v2` 是显式、可产生 provider 成本的操作，不属于日常检查。只有获得单独授权并完成
live preflight 后才运行。已有安全 run 可通过 `report-selective-v2` 在 dev 上确定候选拒答规则，
再一次性报告 holdout；曲线点和 category/challenge slice 都保留覆盖率、拒答与排序指标，该规则
只用于诊断，不会改变生产检索。`write-safe-manifest-v2` 保存 run 身份、数据/产物 hash、聚合指标
和成本/耗时计数；验证时会重建 envelope 并逐项绑定 run/report bytes，不保存查询原文、路径、
向量、prompt、provider body 或用户身份。

真实 Seed V2 的 V2/V3 对照使用两个独立 provider run，并明确保存在本地忽略目录：

```bash
make ip-asset-grounded-eval-live-v2 \
  SEARCH_VERSION=ip-asset-hybrid-v2 OUTPUT=output/evals/ip-v2-v3/v2-run.json
make ip-asset-grounded-eval-live-v2 \
  SEARCH_VERSION=ip-asset-hybrid-v3-rrf OUTPUT=output/evals/ip-v2-v3/v3-run.json
make ip-asset-grounded-eval-compare-v2 \
  BASELINE=output/evals/ip-v2-v3/v2-run.json \
  CANDIDATE=output/evals/ip-v2-v3/v3-run.json \
  OUTPUT_JSON=output/evals/ip-v2-v3/paired-report.json \
  OUTPUT_MARKDOWN=output/evals/ip-v2-v3/paired-report.md
make ip-asset-grounded-eval-report-selective-v2 \
  RUN=output/evals/ip-v2-v3/v2-run.json \
  OUTPUT_JSON=output/evals/ip-v2-v3/v2-selective.json \
  OUTPUT_MARKDOWN=output/evals/ip-v2-v3/v2-selective.md
make ip-asset-grounded-eval-safe-manifest-v2 \
  RUN=output/evals/ip-v2-v3/v2-run.json \
  REPORT_JSON=output/evals/ip-v2-v3/v2-selective.json \
  OUTPUT=output/evals/ip-v2-v3/v2-manifest.json
make ip-asset-grounded-eval-safe-manifest-v2-check \
  MANIFEST=output/evals/ip-v2-v3/v2-manifest.json \
  RUN=output/evals/ip-v2-v3/v2-run.json \
  REPORT_JSON=output/evals/ip-v2-v3/v2-selective.json
```

`compare-runs-v2` 只接受完整的 124-query Alibaba V2 baseline 与 V3 candidate。它要求全部
数据 hash 和 embedding identity 一致，分别报告 overall/dev/holdout、category/challenge、
execution/degraded/no-answer 诊断，并对四项 answerable 排名指标给出固定 10,000 次 bootstrap 的
V3-V2 95% CI。两次请求没有保存查询向量，因此报告会明确声明“模型身份相同，但不能证明两次
embedding bytes 完全一致”。live 产物不进入 canonical，也不接入 `make eval-check`。
