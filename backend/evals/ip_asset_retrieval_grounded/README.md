# Grounded IP asset retrieval evaluation

这是一套后端离线评测，不是站内标注产品，也不提供 `/ip-assets/evaluation` 页面、API 或数据库表。

冻结资产包括 41 张 approved IP 图的安全快照、100 条脱敏中文查询（80 dev / 20 holdout），以及
Codex 逐图视觉检查形成的 4,100 个 0–3 相关性判断。标签来源固定为 `codex_seed`，不是人工
Gold；报告不声称人工一致性、线上用户效果或业务提升。

## 日常无网络检查

```bash
make ip-asset-grounded-eval-check
```

该命令检查 authoring artifact、strict schema、完整矩阵、hash 与 canonical seed report，不访问
数据库或模型服务，也不会改写 canonical 文件。

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
