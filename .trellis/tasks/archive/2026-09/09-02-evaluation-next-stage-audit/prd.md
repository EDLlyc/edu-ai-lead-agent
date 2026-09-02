# 评测体系下一阶段审查与改进

## Goal

审查项目现有检索、图片、内容生成与 Agent 评测的真实性、覆盖面、统计可靠性和上线闭环，并在用户批准后交付第一项改进：由 Codex 将 IP 检索数据升级为复核过的 Seed V2，扩充无答案/近似干扰样本并建立拒答阈值评测。目标是解决“离线门禁是绿的，但检索在没有合适图片时仍大量误报”的问题。

## Background and confirmed facts

- 工作区已有统一 `make eval-check` 与云效质量门禁，覆盖 Agent Workbench、品牌文本检索、数字 IP、图片质量、IP 资产检索、选题重排、品牌视觉检索，以及 provider-free 的 grounded seed contract。
- 已完成基于 41 张真实批准图片的 100-query / 4,100-grade `codex_seed` 数据集，包含 80/20 dev/holdout、graded relevance、no-answer 与固定 bootstrap 置信区间；它明确不是人工 Gold。
- 2026-09-02 的真实 V2/V3 paired run 中，V3 的 MRR@5 显著提升 `+0.0307`，但 Recall@5 基本不变；六条 no-answer 查询的误报率均为 `0.8333`，是当前最明确的检索质量缺口。
- 当前多数 CI 评测验证冻结 schema、policy 与 canonical drift，擅长防回归，但不能替代真实模型、真实图片、人工专家或线上行为效果。
- 图片质量评测目前以 frozen observation 验证 rubric/decision contract；默认不把它宣称为 human-aligned 图片质量。
- 项目已有匿名搜索后预览、收藏、下载和无结果聚合能力，但尚需核验这些行为是否已经形成按检索版本、查询类别和时间窗可决策的离线/线上联合报告。
- 当前已有独立的 P0 任务处理七套 provider-free 门禁、选题 fixture 假阳性和“小赛和赛先生在空间站”回归；本任务不重复这些工作。
- 用户明确决定本阶段不安排真人标注，由 Codex 完成扩充和复核。因此任何新数据仍属于 `codex_seed` / `ai_reviewed_seed`，不得称为人工 Gold、人工参考集或人类一致性证据。

## Requirements

### R1. 评测资产与证据盘点

- 逐套记录被测对象、数据来源、case 数、指标、是否调用真实 provider、是否有人类标签、是否进入 CI、能支持和不能支持的结论。
- 区分 contract regression、model quality、human alignment、online effectiveness 四类证据，禁止用前一类替代后一类。

### R2. 缺口与风险排序

- 从检索拒答、人工 Gold、线上行为、长文/品牌 RAG、图片生成质量、Agent trace/工具使用、数据污染与评测器偏差等维度识别缺口。
- 每项建议给出优先级、预期决策价值、最小样本/实现范围、验收指标和不做的风险。

### R3. 对照外部成熟实践

- 只采用能解决本项目明确缺口的成熟方法，例如分层人工标注与裁决、paired/bootstrap 统计、LLM judge 的人工校准、claim-level RAG 评测、Agent trajectory/最终状态评测和线上 guardrail。
- 不因工具流行而引入新的评测平台；优先复用现有 JSONL、runner、canonical、PostgreSQL 聚合和 run identity。

### R4. 输出可执行路线图

- 形成 P0/P1/P2 路线图，并明确下一项最值得实施的窄范围工作。
- 不在审查阶段修改生产检索权重、模型、前端、数据库 schema 或线上发布策略。

### R5. Codex Seed V2

- 保留现有 100 条查询与 4,100 个 `codex_seed` 判断，禁止就地覆盖 V1 身份。
- 新增 exactly 24 条无答案或近似干扰查询，使查询总数为 124、无答案总数为 30，并形成完整 124×41=`5,084` 判断矩阵。
- 新查询覆盖不存在角色、错误场景、矛盾约束、不支持的可见文字、图库不存在的动作/用途，以及与已有图片语义接近但关键条件冲突的 hard negative。
- Codex 重新检查全部 41 张图片，并对新增查询完成全矩阵标记；对现有 100 条中的无答案、组合约束、grade 1/2 边界和固定演示查询做第二轮盲复核。
- 复核时不能读取 V2/V3 排名、cosine、RRF 分数或线上行为；报告只允许声明 Codex 内部一致性检查，不能声明独立评审者一致性。

### R6. 拒答与选择性检索评测

- 在 evaluation-only live observation 中增加有界决策证据，例如 top similarity、top1/top2 margin、metadata match 和 evidence-lane 数量；禁止保存向量、原图路径、provider body、动态 UUID 或用户信息。
- 在 dev split 上扫描候选拒答规则，报告 no-answer false-positive、correct abstention、answerable false-abstention、coverage/risk、Recall@3/5、MRR@5、nDCG@5 和分层 bad cases。
- holdout 只用于最终一次报告，不参与阈值选择；paired comparison 保留固定 seed bootstrap 95% CI。
- 本任务只形成候选阈值和证据，不启用新的生产搜索版本，不改变普通搜索结果或业务遥测。

### R7. Live 评测证据留存

- 新增最小安全 run manifest，记录 run ID、Git SHA、模型/检索/数据版本、hash、聚合指标、置信区间配置、耗时/成本聚合和产物 hash。
- manifest 不存 query 原文、图片路径、向量、prompt、provider body 或用户身份；不建设通用评测 SaaS、站内看板或新的业务数据库。

## Acceptance Criteria

- [x] 现有评测矩阵覆盖所有 `backend/evals/*` 及相关线上聚合/CI 门禁，并记录真实性边界。
- [x] 高优先级缺口有仓库证据、可观察指标和一手外部方法依据。
- [x] Seed V1 文件和 hash 保持可验证；Seed V2 exactly 124 条查询、30 条 no-answer、5,084 个 0–3 判断，敏感字段扫描通过。
- [x] 新增 24 条查询由 Codex 基于实际 41 图完成全矩阵标记；高风险旧切片完成盲复核并输出变化原因，但不生成任何人工 Gold/一致性声明。
- [x] dev-only 阈值扫描同时报告 no-answer false-positive 和 answerable false-abstention，并生成 coverage/risk、排名指标、slice、bad-case 和 bootstrap 结果。
- [x] holdout 未参与候选阈值选择；报告清楚区分 Seed、live provider、线上效果和人工证据。
- [x] live run manifest 可验证身份/hash 且不包含查询、路径、向量、provider body 或用户信息。
- [x] 现有 provider-free `make eval-check`、focused tests、Ruff、mypy、privacy scan 与 `git diff --check` 通过。
- [x] 无 frontend、站内 evaluation 页面、新 API route、业务数据库 migration 或生产阈值启用。

## Out of Scope

- 重复实现正在进行的 P0 provider-free 统一门禁。
- 在本轮审查中直接调整 RRF 权重、Embedding 模型、内容提示词或发布门禁。
- 把 Codex seed、LLM judge 或 frozen observation 改称人工 Gold。
- 新增站内 `/ip-assets/evaluation` 标注页面。
- 安排真人标注、计算 human-human agreement，或把 Codex 多轮复核描述为多人独立评审。
- 在本任务中启用生产搜索 V4、线上 A/B 分流或新的拒答门禁。

## Key Decisions

- 用户选择不安排真人，由 Codex 完成新增标记和高风险复核；数据成熟度保持 Seed。
- 下一项实施聚焦 IP 检索拒答，不新建全链路评测平台，也不重复正在进行的公众号 Reviewer 任务。
- 新增 exactly 24 条无答案/near-miss 查询；V1 不覆盖，V2 使用新的版本/hash。
- 先评测阈值、后单独审批生产行为；当前任务不改变搜索结果。

## Risks and Deferred Items

- 同一 AI 负责初始与复核仍可能有系统性偏差；通过盲复核、固定 rubric、变化记录和真实性声明降低但不能消除该风险。
- 30 条 no-answer 比 6 条稳定，但仍是小样本；报告必须给出分母、置信区间和 bad cases。
- 真正的人工一致性、线上因果 A/B、图片 live-human calibration 和 Agent repeated-trial 评测继续延期。
