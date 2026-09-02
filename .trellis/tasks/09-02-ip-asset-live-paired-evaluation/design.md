# Design: 本地真实 IP 检索 V2/V3 成对评测

## 1. Architecture and boundaries

```text
frozen Seed V2 + safe 41-asset snapshot
                  │
         manifest/DB/vector preflight
                  │
       ┌──────────┴──────────┐
       │                     │
 real run: hybrid-v2   real run: hybrid-v3-rrf
       │                     │
       └──────────┬──────────┘
                  │ strict identity binding
          Seed V2 paired scorer
                  │
      JSON + Markdown + safe manifests
                  │
       local ignored output directory
```

运行复用生产 `IpAssetService.search_text_for_evaluation(...)`，它禁用业务搜索聚合写入，但保留
生产 filter extraction、metadata ranking、向量检索和 V2/V3 selector。实现不增加 HTTP/UI
入口，不修改数据库 schema、生产默认版本或 Embedding 数据。

## 2. Seed V2 paired comparison

在 Grounded evaluator 中增加独立 V2 comparator，而不是放宽现有 V1 model：

- 严格加载两个 `GroundedRetrievalRunV2`；
- 校验 baseline/candidate 方向、真实 provider mode、全部数据哈希、embedding identity 与查询顺序；
- 对 answerable query 计算 Recall@3/5、MRR@5、graded nDCG@5；
- no-answer 只进入明确的返回/拒答诊断，不进入 ranking macro；
- 汇总 overall、split、category、challenge kind、mode、failure/degraded；
- 对四项 answerable 指标按 query ref 配对执行固定种子的 10,000 次 bootstrap；
- 输出安全 bad-case ref 和 V3 相对 V2 的 win/tie/loss，不输出查询、score 或向量。

V2 comparator 使用新 schema/version 和新 JSON/Markdown renderer。V1 `compare-runs` 的输入、输出和
命令保持不变。

## 3. Local run orchestration

实现明确的 Make/CLI 入口，实际产物放在 `output/evals/`。建议执行顺序：

1. provider-free Seed V1/V2 gate；
2. live preflight；
3. 记录评测前业务搜索聚合快照；
4. Seed V2 hybrid-v2 live run；
5. Seed V2 hybrid-v3-rrf live run；
6. 为两个 run 分别生成 selective report；
7. 生成 V2/V3 paired report；
8. 为两个 run/report 生成并验证 safe manifest；
9. 隐私扫描并确认业务搜索聚合无变化。

外部调用只发生在步骤 4/5。失败产物保留诊断但不能标记为成功证据，也不能把 fake 或 metadata
degraded 结果包装为 real embedding。

## 4. Evidence identity and privacy

paired report 绑定两个 run 的：

- run ref 和创建时间；
- search version；
- provider/model/dimensions/input-policy/execution mode；
- asset/query/seed/robustness/review hashes；
- duration 和 provider request count。

产物继承现有 prohibited-key 深度扫描，并增加 paired report 测试。只保存 catalog ref，禁止动态
资产 ID、路径、原图、query text、grade matrix、向量、provider 响应和任何用户/会话字段。

## 5. Compatibility and rollback

- 所有新增命令为 additive；现有 V1/V2 frozen gate 与 V1 live comparator 不变。
- `make eval-check` 只调用 provider-free 检查，不引用 live 产物。
- 若 comparator 实现有问题，可回滚代码提交；本地 `output/evals/` 产物是 Git 忽略文件，可保留供
  诊断或由用户之后自行删除。
- 若真实 provider 运行失败，不修改数据库或重建 embedding，只记录失败并停在本地。

## 6. Validation strategy

- 单元测试：V2 identity、版本方向、覆盖、no-answer、bootstrap、报告与隐私字段。
- 静态检查：task-scoped Ruff、format、Mypy、`git diff --check`。
- 离线回归：Grounded V1/V2 canonical 和顶层 `make eval-check`。
- 本地 live：preflight、两个 124-query Alibaba run、selective/paired reports、safe manifests。
- 副作用：比较运行前后匿名业务 search aggregate 快照，必须完全一致。
