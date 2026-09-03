# Agent 检索增强真实 A/B 评测

## Goal

在本地开发环境中，用同一批真实业务问题、同一个智谱工具调用模型和同一份 PostgreSQL 业务数据，
配对比较“原始查询直接检索”与“受控 Query Rewrite + Weighted RRF + 智谱 Reranker”，回答检索增强
是否让 Agent 更稳定地找到、引用并组合正确证据，同时给出可复算、可解释且不夸大成熟度的面试证据。

## Background and confirmed facts

- 当前 Agent 已通过 `BoundedAgentRunner` 和 `TypedToolRegistry` 提供 `search_evidence`、
  `get_event`、`retrieve_brand_context`、`validate_copy` 四个严格 Schema 工具，单次运行最多四次
  模型决策和四次工具调用。
- PostgreSQL reader 已提供治理后新闻证据、事件详情、品牌 RAG 和文案校验上下文的只读投影；品牌检索
  使用已配置的阿里多模态 Embedding。
- `EnhancedAgentKnowledgeReader` 已实现智谱一次受控改写、原始/改写查询的 Weighted RRF、智谱
  Reranker 和确定性回退；基础 `PostgresAgentKnowledgeReader` 可作为不启用增强的对照组。
- 现有 42 例 Agent Workbench 报告是 provider-free 的确定性契约回归，不代表真实模型效果；现有品牌
  RAG 报告同样不是私有语料上的 live 模型质量结论。
- 用户已授权本任务进行一次本地真实 A/B，规模为 12 个问题 × 2 个实验臂 × 3 次重复，最多 72 次
  Agent run；Agent、Query Planner 和文本精排优先使用已配置的智谱能力，品牌向量继续使用已配置的
  阿里多模态 Embedding。

## Requirements

### R1 — Paired experiment isolation

- A 组使用 `PostgresAgentKnowledgeReader`：原始 query 直接进入现有全文/品牌混合检索。
- B 组仅将 reader 替换为 `EnhancedAgentKnowledgeReader`：保留原始 query，并增加一次智谱
  Query Rewrite、Weighted RRF 和一次智谱 Reranker；改写或精排失败时按现有契约回退。
- 两组必须冻结相同的 Agent 模型、温度、系统提示、工具 Schema/Registry hash、运行限制、数据库
  快照身份、品牌检索版本、Embedding 身份、问题集和评分器。实验臂不得改变 Agent 可见工具或向模型
  暴露 oracle。
- 每个 case/repetition 的 A/B 顺序使用固定随机种子交错，两个实验臂使用独立但同配置的进程内
  Embedding cache，分别经历一次冷启动和后续热缓存，防止跨臂缓存污染延迟结果。

### R2 — Real-data Seed dataset

- 从当前开发机 PostgreSQL 的可用治理数据中冻结 12 个真实业务问题：新闻证据、事件详情、品牌上下文、
  证据与品牌组合、文案校验、安全/越权拒答各 2 个。
- 新闻、事件、品牌和多工具共 8 个 case 是检索敏感实验样本；文案校验和安全拒答共 4 个 case 是
  非劣化负对照，不进入检索提升主指标。
- 每个 case 单独保存允许/必须工具、参数约束、相关证据或品牌 chunk、预期终态和安全断言。标签来源
  固定为 `codex_seed_v1`；它不是人工 Gold，不得报告人工一致率或生产业务提升。
- 因金丝雀要求目标 `Recall@3=1`，每个检索命名空间最多冻结 3 个 qrel；禁止用 4 个及以上目标构造
  数学上不可能通过的 Top-3 门禁。
- 模型输入只能获得问题及正常工具结果，不能获得标签。包含真实 UUID、原文、内部 URL 或私有品牌内容
  的冻结数据与原始 attempt 只写入 gitignored 的 `output/evals/agent-retrieval-ab/<run-id>/`；提交的代码、
  测试和文档只保留 Schema、哈希、计数及通过隐私扫描的聚合结果。
- 执行前验证每个正例 oracle 仍能在当前数据库快照中找到；数据漂移、空语料或标注不完整时 fail closed，
  不启动付费 A/B。

### R3 — Bounded live execution

- 默认命令只做 dataset/config/database/provider preflight；真实执行必须同时提供显式 live flag、固定
  authorization manifest 和新建的输出目录。
- 单次授权最多 72 个 Agent attempts；每个 attempt 使用与生产一致的四次模型决策、四次工具调用和 30 秒
  总时限。Query Planner 与 Reranker 每次调用最多一次尝试，禁止 whole-suite 隐式重试。
- 新授权使用独立的 v2 manifest/policy/authorization 身份和全新输出目录；旧的 v1 失败证据不可续跑、覆盖
  或作为新矩阵的一部分。
- 固定调度的前两个 cell 是同一个 case/repetition 的 A/B 金丝雀。仅当两臂都通过终态、任务、工具选择、
  参数、Top-3 target 全召回、引用完整性及 provider/protocol/budget 门禁时，才执行剩余 70 个 cell；任一
  不通过立即输出 incomplete/no-uplift 证据。
- runner 同时执行全局计数器：最多 288 次 Agent 模型决策、108 次 Query Planner、108 次 Reranker、
  108 次阿里 Embedding 请求。任何上限先到即停止后续调用，保留已完成/失败 attempts 并将 run 标为
  `incomplete_budget_exhausted`，不得用部分结果声称 uplift。
- 金丝雀通过后，如连续四个 cell 出现 provider/protocol/budget 系统性失败，则确定性熔断；单个 executor
  边界失败可更早 fail closed，且均不自动补跑或重跑失败 cell。
- 仅允许 `APP_ENV=development`、本地 PostgreSQL、智谱 Agent/Planner/Reranker 和阿里品牌 Embedding；
  不启动服务器、不部署、不发布公众号、不抓取新网页、不写业务表，也不修改业务筛选和发布链路。

### R4 — Metrics and statistical reporting

- 检索主指标在 8 个检索敏感 case 上计算：target Hit@3、Recall@3、MRR@3、nDCG@3，以及相关证据
  最终被 Agent 引用的 citation coverage。
- Agent 指标在全部 12 个 case 上计算：task success、终态准确率、工具选择 precision/recall、参数有效率、
  citation precision/coverage、unsupported-claim rate、拒答准确率和每个 case 三次全部通过的稳定性。
- 运维指标包括成功/失败/回退次数、failure taxonomy、P50/P95 端到端与模型/工具延迟、Agent 已报告的
  input/output/reasoning tokens、各 provider capability 请求数。provider 未返回的 usage 或未配置的价格
  必须记为 `unknown`，不得推算成伪精确成本。
- A/B 差异先对三次重复按 case 聚合，再做固定 seed 的 paired bootstrap 95% CI；样本仅 8/12 个，报告
  必须同时给出逐 case bad cases 和“小样本探索性结果”限制。CI 跨 0 或完整性门禁未通过时，不得写
  “显著提升”。

### R5 — Reproducibility and evidence honesty

- run manifest 记录代码 SHA、dataset/oracle hash、数据库快照指纹、registry hash、模型/provider/版本、
  retrieval policy、温度、随机种子、缓存策略、上限、开始/结束时间及 artifact hashes。
- 原始 attempt 必须包含实验臂、case、repetition、终态、脱敏 trace、指标、provider 请求计数和失败码；
  失败、空返回、格式错与降级结果都保留，不能只挑成功截图。
- live 报告与现有 provider-free canonical report 永久分开，绝不自动覆盖。报告只能描述本次本地数据和
  Seed 标签上的结果；任何简历数字需能回链到安全聚合报告并保留适用范围。

### R6 — Zhipu Agent protocol compatibility repair

- 在不放宽 `AgentProposedAnswer`、工具参数或引用校验的前提下，使 OpenAI-compatible Agent adapter 使用
  智谱官方支持的 JSON mode，并在 system message 中给出完整、确定的终答对象契约。
- 成功且非空的检索 observation 返回后，下一轮提示必须明确要求：只有用户目标仍缺少另一类必要信息时
  才调用不同工具；不得通过改写同义 query 重复调用已成功的同类检索，也不得为纯证据检索无条件下钻
  `get_event`。原有精确调用 run-cache 保留，Schema、未知工具、重复 call ID 和 citation 门禁不得放宽。
- provider-free 契约测试必须证明 JSON mode 请求、完整终答形状、历史驱动的 next-action guidance、合法
  多工具路径和恶意/错误输出拒绝行为；测试不得保存原始 provider body 或引入 live 调用。
- 修复后仅允许新建一个独立授权、独立输出目录的 2-cell A/B canary。无论通过或失败都在第二格后停止，
  不执行剩余 70 格；旧 v1/v2 输出不可续跑、覆盖或混入新结果。

## Acceptance Criteria

- [x] provider-free 测试证明 A/B 唯一变量是 reader 增强层，oracle 不进入模型输入，A/B 顺序与聚合可复算。
- [x] dataset builder 从本地只读 PostgreSQL 生成 12 个完整 case，并在缺少相关记录、标签或稳定快照时
      preflight 失败；冻结数据和 raw attempts 不进入 Git。
- [x] dry-run/preflight 在不调用 provider 时输出模型身份、数据库/registry/dataset hashes、72-run 与
      provider 子调用上限；缺少显式授权、凭据或开发环境时 live 调用数为 0。
- [x] 一次新的 v2 显式授权真实运行先执行 2-cell A/B 金丝雀；两臂通过时最多继续至 72 个 attempts，
      任一门禁失败则停止。超时、格式错、额度不足和上限耗尽均形成安全失败账本且无隐式整套重跑。
- [x] 报告按检索敏感样本与负对照分别给出规定的检索、Agent、安全、稳定性、延迟、usage 和 failure
      指标，提供 paired CI 与逐 case bad cases，并将未知 token/cost 明确标为 unknown。
- [x] 隐私/秘密扫描证明提交内容和安全聚合报告不含 API key、数据库 URL、真实 UUID、私有语料、原始
      prompt/response/provider body；现有确定性 Agent 和品牌 RAG canonical artifacts 未被改写。
- [x] focused tests、Ruff、strict mypy、相关 eval check 和 `git diff --check` 通过；任何无法归因于本任务的
      既有失败须单独记录，不通过删测试或放宽契约解决。
- [x] 智谱 Agent adapter 以官方 JSON mode 请求终答，并通过严格 Schema 将兼容响应投影为
      `FinalAnswerDecision`；成功检索后的提示可阻止无意义同类重搜和不必要事件下钻。
- [x] 新的 provider-free 兼容性测试及相关既有 Agent/eval 回归通过；只执行一次新的 2-cell canary，
      第二格后强制停止并如实记录 pass/fail，不启动完整 72-cell 矩阵。

## Out of Scope

- 人工 Gold、双人标注/仲裁、线上用户随机分流和业务转化率 A/B。
- 调整生产 Query Rewrite、RRF 权重、Reranker、阈值、工具 Schema 或引用协议；本次仅允许收紧
  OpenAI-compatible Agent 的结构化输出请求和有历史依据的 next-action guidance。
- 将实验结果自动写入简历/作品集，或在没有支持性证据时宣称模型效果、统计显著性和生产 uplift。
- 服务器部署、公众号发布、业务数据库写入、新一轮新闻抓取和购买/充值模型额度。
- 运行新的完整 72-cell 矩阵；兼容性修复阶段最多消费一个新的 2-cell canary。
