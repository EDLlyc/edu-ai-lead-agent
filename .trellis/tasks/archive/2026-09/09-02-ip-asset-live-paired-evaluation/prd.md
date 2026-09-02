# 本地真实 IP 检索 V2/V3 成对评测

## Goal

在本地真实的 41 张 approved IP 图片与兼容向量上，使用已经配置的阿里云
`qwen3-vl-embedding` 对 Grounded Seed V2 的同一组 124 条查询分别执行
`ip-asset-hybrid-v2` 和 `ip-asset-hybrid-v3-rrf`，生成可核验的成对比较报告。

用户价值是把“冻结 fixture 的策略回归”提升为“真实模型、真实语料、生产检索路径”的本地证据，
能够诚实回答 V3 是否比 V2 更好、差异是否稳定以及失败集中在哪些查询切片，同时不把本地实验上传、
部署或误表述为线上业务效果。

## Background and confirmed facts

- 现有 `backend/evals/ip_asset_retrieval_grounded` 已提供安全资产快照、Seed V2、真实运行、选择性
  报告与安全 manifest；Seed V2 包含 124 条查询、30 条 no-answer、5,084 个 Codex 判断。
- 私有视觉清单存在；2026-09-02 的只读 preflight 已通过，41 张目标图片全部映射为
  ready/shared 且具有兼容的 `alibaba-model-studio/qwen3-vl-embedding/2048/
  brand-visual-embedding-input-v2` 向量。
- 本地 PostgreSQL/MinIO 服务健康；数据库共有 46 张 ready 图片和 46 份当前兼容向量。
- `.env` 已配置真实视觉 Embedding provider、endpoint 与 API key。真实 V2/V3 各跑 124 条查询，
  预计共发起 248 次外部 Embedding 请求；输出仍只保存在本地。
- 现有 V1 `compare-runs` 只接受 100-query 的 `GroundedRetrievalRun`，不能比较 Seed V2 的
  `GroundedRetrievalRunV2`，因此需要补齐 Seed V2 成对比较器，而不是把 V2 产物降级成 V1。
- Codex Seed V2 不是人工 Gold。即使真实运行通过，也只能声称 model/corpus quality evidence，
  不能声称人类一致性、线上转化提升或已校准生产阈值。

## Requirements

### R1. Seed V2 成对比较契约

- 新增只接受两个 `GroundedRetrievalRunV2` 的显式比较入口；baseline 必须是
  `ip-asset-hybrid-v2`，candidate 必须是 `ip-asset-hybrid-v3-rrf`。
- 两个 run 必须具有相同的 asset/query/seed/robustness/review 哈希，以及相同 provider、model、
  dimensions、input-policy 与真实 `alibaba` execution mode；身份不一致时 fail closed。
- 比较必须基于相同 124 条 query ref，并分别报告 dev/holdout、category、challenge kind、
  execution/degraded 状态和 answerable 排名指标。
- 对 Recall@3、Recall@5、MRR@5、nDCG@5 使用固定随机种子的 10,000 次 query-level paired
  bootstrap，输出 V3-V2 delta 与 95% CI；no-answer 不得被伪造为满分排名样本。
- 输出只允许安全 catalog ref、聚合指标、闭集失败原因和版本身份，不保存查询原文、动态 UUID、
  文件/对象路径、向量、原始 score、provider body、请求标识或用户信息。

### R2. 本地真实 V2/V3 运行

- 在任何付费请求前再次运行 preflight；失败时不调用 provider。
- 使用同一 Git 代码版本、同一 Seed V2 与同一 41 图语料，顺序运行 V2 baseline 和 V3 candidate。
- 每个 run 必须覆盖 124 条查询并记录 `embedding_execution_mode=alibaba`；禁止用 fake/degraded
  结果冒充真实对照。
- 普通业务搜索聚合计数在评测前后保持不变；运行不得写入生产业务状态或修改现有向量。
- 运行、单跑选择性报告、成对比较报告和安全 manifest 写入 Git 忽略的
  `output/evals/ip-asset-v2-v3-<timestamp>/`，不提交为 canonical truth。

### R3. 可复现入口与验证

- 为 Seed V2 live run、单跑报告、安全 manifest 和 V2/V3 paired comparison 提供清晰的 CLI 或
  Make 入口；保留现有 V1 入口兼容性。
- 增加身份错配、版本反转、查询覆盖漂移、no-answer 处理、bootstrap 可复现、隐私字段拒绝和
  Markdown/JSON 报告的单元测试。
- provider-free `make eval-check` 继续不包含 live 命令，不依赖凭据，也不因本任务变成付费门禁。
- README/spec 说明外部 provider 调用与本地输出的区别，并保留 Seed/非 Gold/非线上效果边界。

## Acceptance Criteria

- [x] 只读 preflight 在真实运行前通过并确认 41/41 目标资产与兼容向量。
- [x] V2/V3 两个真实 run 均为 `alibaba` 模式、各覆盖 124 条查询，数据和模型身份完全一致，
      baseline/candidate 版本方向正确。
- [x] 成对报告包含总体及 dev/holdout/category/challenge 切片、失败/降级统计、四项排名指标和
      固定 10,000 次 bootstrap 的 V3-V2 95% CI。
- [x] 报告明确披露 30 条 no-answer、Codex Seed 非人工 Gold、两次独立 provider 查询的限制，
      不声称线上效果或生产阈值。
- [x] 两个 run、两个单跑选择性报告、paired JSON/Markdown 和安全 manifest 全部保存在本地忽略目录，
      artifact hash/identity validation 通过且隐私扫描无禁止字段。
- [x] 评测前后业务搜索聚合计数相同，无数据库业务写入、向量重建、服务发布、远端推送或生产部署。
- [x] focused tests、Ruff、Mypy、`make ip-asset-grounded-eval-check`、`make eval-check` 和
      `git diff --check` 通过；其他并行工作区改动不进入本任务提交。

## Key Decisions

- 使用最新 Seed V2 的 124 条查询，而不是退回只支持现有 comparator 的 V1 100 条查询。
- 补齐 V2 run comparator；不修改 V2/V3 生产排序权重，也不在本任务激活选择性拒答阈值。
- 真实运行允许访问已配置的阿里云 Embedding API，预计 248 次请求；数据库、图片、报告和代码操作
  均保持本地，绝不推送或部署。
- live 产物属于一次性本地证据，不写入 checked canonical；CI 只验证 comparator 和冻结契约。

## Out of Scope

- 人工 Gold、多人标注一致性或新的 Codex/模型标注。
- 扩充查询集、调整检索权重、上线拒答策略或 A/B 实验。
- 新增网页评测/标注路由、API、数据库表或统计看板。
- 重新生成 41 张图片的 Embedding、修改图片元数据或业务搜索计数。
- 上传服务器、推送 Git 远端、部署或调用微信公众号。

## Risks and deferred items

- V2/V3 分别调用 provider，虽然模型身份和数据一致，但无法证明两次返回的浮点向量逐字节相同；
  报告必须披露这一限制，后续若需要严格同向量对照再设计单次 embedding 双策略回放。
- 单次真实运行会产生外部模型费用并受 provider 限流影响；并发保持现有配置，失败不静默降级为成功。
- 工作区有大量其他任务的未提交修改；实现和提交只触碰 Grounded evaluator、测试、文档和本任务文件。
