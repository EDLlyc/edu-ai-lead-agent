# IP 检索真实图库 Seed Eval V1

## Goal

为 IP 数字资产中心建立第一版基于真实 41 张批准图片的离线 grounded retrieval 评测集：由 Codex 实际检查图片，策划 100 条脱敏业务查询并完成 100×41 共 4,100 个 0–3 相关性初始标签；使用真实检索链路生成可复现、可比较且统计口径诚实的 Markdown/JSON 报告。

本版本不新增任何站内页面、前端路由、标注 API、数据库表或人工标注工作流。Codex 标签固定声明为 `codex_seed`，不冒充人工 Gold。

## User Value

- 团队可以用真实 41 图回答“当前检索到底准不准”，而不只知道合成排序代码没有回归。
- V2、V3 或后续策略可以在同一 query/label snapshot 上比较 Recall、MRR、nDCG、无答案错误及置信区间。
- 现有 41-case provider-free synthetic suite 继续提供快速 CI 回归；新的 grounded suite补充真实图库证据，二者互不替代。
- Seed dataset、run observation 和报告都有版本/hash，可审查、可重跑且不泄漏私有图片位置或线上个人行为。

## Confirmed Facts

- 当前 `backend/evals/ip_asset_retrieval/` 有 41 个脱敏合成 case，保存冻结的 metadata/semantic ranks，不读取真实图片或调用真实检索链路。
- 当前批准 manifest 稳定包含且仅包含 41 张 `approved=true` 图片，已有稳定安全 catalog ref、受控视觉元数据和完整性证明。
- 现有动态 IP 资产库已经导入 41 图，并提供 metadata + multimodal vector + weighted RRF 的 V3 真实检索；V2 direct blend 保留为 rollback。
- 普通搜索会写匿名结果/无结果聚合；离线评测不得污染这些业务指标。
- 用户明确要求不新增 `/ip-assets/evaluation` 或其他站内标注页面，并授权 Codex 完成第一轮标记。

## Requirements

### R1 — Versioned 100-query set

- 建立 exactly 100 条唯一、脱敏、人工策划的中文查询。
- 覆盖角色、图片类型、情绪、动作、场景、用途、透明底、组合约束、自然口语/同义表达、简称/轻微噪声、无答案/hard negative。
- 固定包含“小赛和赛先生在空间站”。
- 显式、分层固定为 80 条 dev 与 20 条 holdout；普通调参报告不输出 holdout 逐条标签。
- 不复制线上原始 query；未来从业务反馈补样本时必须先重新表述和脱敏。

### R2 — Complete Codex seed labels

- Codex 先实际查看完整 41 图，再对每条 query 的全部 41 项打 0–3 grade：
  - `0` 不相关或关键约束冲突；
  - `1` 弱相关，只满足边缘/局部意图；
  - `2` 可用，满足主要意图但不完整；
  - `3` 高度相关，应优先推荐。
- 结果必须 exactly 4,100 个唯一 query × catalog-ref 判断，绑定 rubric、evaluator 和 asset-set 版本。
- 标签来源只能写为 `codex_seed`；没有真实人工复核时，不报告 human agreement、不使用 `gold` maturity。
- 标签不能由当前 V2/V3 搜索结果、cosine、metadata score 或排名自动反推；先固定查询和 rubric，再基于图片内容独立标记。

### R3 — Safe frozen dataset

- 查询与 labels 使用 strict JSONL schema、dataset SHA-256、query-set/version、asset-set fingerprint 和 rubric/evaluator version。
- committed dataset 只允许 safe query ref/text、category/split、稳定 catalog ref、grade 和版本字段。
- 禁止写入原图 bytes、私有路径、文件名、对象 key、checksum、动态数据库 UUID、向量、provider body/request ID、profile/user/session/IP/UA/cookie。
- 真实 41 图发生缺失、重复、非 approved、映射失败或 fingerprint drift 时 fail closed，不以部分图库产生完整报告。

### R4 — Grounded retrieval runner

- 新 runner 使用真实 41-asset projection 和生产 filter extraction、metadata candidate、embedding/vector search 及 rank selector；labels 只能在排名完成后参与计分。
- 支持 active search version 的单次 run，以及两个安全 run observation 的 paired V2/V3 比较。
- evaluation mode 必须关闭普通 search aggregate side effect；评测前后业务搜索计数保持不变。
- 缺少数据库、41 图、兼容 embeddings 或 provider 时给出 typed preflight failure，不伪装成成功或无结果。
- live/provider run 是显式本地命令，不加入每个 PR 的无网络 `eval-check`。

### R5 — Metrics and reporting

- `grade >= 2` 作为 Recall/MRR 的可用相关阈值；nDCG 使用完整 0–3 graded gain。
- 报告 Recall@3、Recall@5、MRR@5、nDCG@5、category/split、mode、failure 和 zero-result/false-positive。
- 全部 grade `<2` 的 no-answer query 单列 correct abstention / false-positive，不以默认 1.0 混入普通相关查询宏平均。
- paired comparison 以 query 为 bootstrap 单位，固定 RNG seed，默认 10,000 次，报告 metric delta 的 95% CI。
- JSON/Markdown 报告明确 maturity=`seed`、模型/embedding/search identity、query/asset/rubric/dataset hashes、运行时间和真实性边界。

### R6 — Offline review and tests

- 提供 dataset validate、live preflight、run、paired report 和显式 write/review 命令；普通 check 不能静默改写 canonical 或 baseline。
- 可额外导出空白 CSV/JSONL review template，供未来人工复核，但本版本不实现页面、多人协作、DB 持久化、裁决或 Gold promotion。
- 覆盖 strict schema、重复身份、非法 grade、完整矩阵、类别/split、敏感字段、asset drift、label/ranking 隔离、no-answer、bootstrap determinism、report drift 和 search metrics 无污染。

## Acceptance Criteria

- [ ] exactly 100 条唯一查询、80/20 split、预定类别齐全且包含固定 space-station query。
- [ ] 真实 41 张 approved 图片被逐张检查，产生 exactly 4,100 个唯一 0–3 `codex_seed` labels。
- [ ] query、seed 和 snapshot 有稳定 version/hash；敏感字段扫描通过，不复制私有图片或位置。
- [ ] 41 图映射不完整、非 approved 或 fingerprint drift 时 runner fail closed。
- [ ] grounded runner 使用生产检索/排序边界，labels 不进入 retrieval input，evaluation 不改变业务 search aggregates。
- [ ] 报告包含 Recall@3/5、MRR@5、nDCG@5、no-answer 指标、类别/split 和固定 seed bootstrap 95% CI。
- [ ] 现有 provider-free 41-case runner 继续通过；grounded live run 有独立显式入口且不阻塞普通 CI。
- [ ] 文档和报告始终称 `codex_seed`，不伪造人工 Gold、一致性、业务提升或跨图库泛化。
- [ ] focused tests、format/lint/typecheck、canonical/hash drift 和 `git diff --check` 通过；无任何前端、标注 API 或 evaluation DB migration 变更。

## Key Decisions

- 删除站内 `/ip-assets/evaluation` 页面及其所有前端/API/数据库设计。
- V1 只交付 Codex 完整 seed、离线 schema/runner/report 和未来人工复核模板。
- 不拆子任务：查询、41 图标记、runner 和报告共享同一 dataset/asset fingerprint，必须成组审查。
- 保留 synthetic CI 与 grounded live 双轨；不让第三方 provider 稳定性阻塞普通 PR。

## Out of Scope

- 任何新的前端页面、路由、按钮或 IP 图库入口。
- 标注 CRUD API、PostgreSQL annotation tables、多人进度、盲标 UI、分歧裁决和账号权限。
- 将 Codex seed 宣称为人工 Gold，或制造 human-human/model-human agreement 数字。
- 采集线上原始查询、逐用户行为或身份。
- 在本任务中更改 V3 权重、生成图片质量、公众号 RAG 或 Agent trace 评测。

## Risks and Rollback

- 4,100 个判断容易出现疲劳或规则漂移：先固定 rubric，按 query 批次标记，并运行完整矩阵、分布和 hard-negative 抽查。
- 41 图相关项可能稀疏：no-answer 必须单列，不能用 1.0 默认分美化宏平均。
- Seed 来自单一 AI evaluator：报告必须标明来源与局限，后续真正 Gold 需要独立人工复核任务。
- 真实 provider 结果可能变化：run observation 绑定 provider/model/input policy/time，canonical 只冻结 dataset/metrics contract，不把一次 live ranking 当永久真值。
- 当前工作树有大量并行修改；实施只触及任务列出的 backend eval/service/spec/test/Make/docs 文件，不重置或格式化无关区域。
