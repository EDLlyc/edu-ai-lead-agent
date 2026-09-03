# Agent 检索增强真实 A/B 评测：技术设计

## 1. Boundary and components

新增独立的 `backend/evals/agent_retrieval_live_ab/` 评测包，不改变生产 Agent、MCP、新闻选择或发布代码。

```text
local PostgreSQL --read only--> dataset builder --> private frozen Seed dataset
                                                \-> oracle/hash/preflight

same query + same Zhipu Agent model
        |                              |
        v                              v
A: PostgresAgentKnowledgeReader    B: EnhancedAgentKnowledgeReader
   raw retrieval                      Zhipu rewrite -> raw + rewrite retrieval
                                                     -> weighted RRF -> Zhipu rerank
        |                              |
        +------ same TypedToolRegistry-+
                       |
                BoundedAgentRunner
                       |
        redacted attempt + metrics + citations
                       |
         paired scorer / CI / safe report
```

外层 Agent 通过现有 `OpenAICompatibleToolCallingModel` 调用智谱兼容接口；品牌原始/改写查询继续通过现有
阿里多模态 Embedding。A/B 的 registry schema hash 必须完全一致，否则 preflight 失败。

## 2. Dataset and oracle contract

实现严格 Pydantic JSONL schema，case 包含 `case_id/category/query/expected_tools/allowed_tools/`
`argument_constraints/relevance_qrels/expected_terminal/safety_assertions/label_source`。检索 qrel 使用等级
相关性而非单个 exact answer，允许 Recall/MRR/nDCG；新闻引用 ID 与品牌 chunk ID 分开评分，品牌 chunk
永远不能作为外部事实证据。

dataset builder 只读取已经治理的当前事件/证据、active 品牌 chunk 和可用 copy run。它生成临时候选后，
由固定规则和 Codex 审阅冻结 12 个 Seed case；oracle 保持 evaluator-side。数据库快照指纹只包含表级计数、
最大更新时间、检索/Embedding 版本和内容身份哈希，不保存向量或原文。任何原始 UUID/文本文件都留在
gitignored output。

执行前 resolver 重新确认 qrel 引用仍存在且满足治理/有效期条件，并写 snapshot commitment。不存在、失效或
库发生不可接受漂移时终止，防止用过期 oracle 给模型扣分。

## 3. Paired execution and cache fairness

manifest 固定 12 cases、3 repetitions、temperature 0、model identity、四次模型/工具上限、random seed 和
两组 reader 配置。调度单位是 `(case, repetition)`；用固定 seed 对每个 pair 选择 `AB` 或 `BA`，同一 pair
连续完成以减小 provider 时间漂移。

v2 调度把第一个 pair 的两个 cell 标记为强制金丝雀。Runner 先各执行一次 raw/enhanced，且只在两者都
达到预期终态、task success、完整工具/参数、Top-3 target 全召回与全引用，并且没有 provider、协议或预算
失败时继续后 70 个 cell。任何失败都保留两个 observation、写入 `canary_failed`，并生成不可声明 uplift 的
不完整报告。金丝雀之后对 provider/protocol/budget 失败维护连续计数，四次连续系统性失败触发熔断；不可
解释的 executor 边界失败可直接 fail closed。熔断只影响是否继续调度，不改变任一实验臂的 prompt、reader、
工具或模型行为。

为使 `Recall@3=1` 门禁可达，dataset builder 对 evidence 和 brand 两个检索命名空间分别限制最多 3 个
qrel；构造与 live preflight 都 fail closed，历史报告只允许离线读取，不能因此恢复 provider 执行。

两个 arm 各拥有独立 `CachedBrandEmbeddingModel` 和 HTTP client，配置、TTL、容量相同。每个 arm 第一次
相同 query 是 cold observation，随后重复可命中自身 cache；不得让 A 的 embedding 结果直接预热 B。
报告分别展示 all-run 和 warm-run latency，不把缓存命中当检索质量提升。

Runner 用 attempt journal 先写 `started`，结束后原子落地 terminal record。进程中断后保留 incomplete ledger，
默认不续跑；续跑必须显式引用同一 manifest 且只补缺失 cell，不能重跑已有失败以挑选最好结果。

## 4. Budget and provider observations

评测层用计数包装器包住 Agent model、planner、reranker 和 embedding port；在调用前原子消费 capability budget。
默认 hard caps 为 72 Agent attempts、288 Agent decisions、108 planner requests、108 rerank requests 和 108
embedding requests。单个 provider adapter 的重试仍固定为一次尝试。

v2 manifest、authorization、attempt 和 report 使用新的 schema/policy 身份及新输出目录。v1 的不完整证据
保持不可变，Runner 不支持将 v1 attempt 混入 v2、续跑旧目录或覆盖既有 cell。

Agent result 已提供模型 token/latency；planner、reranker 和 embedding 只记录安全的 capability、provider、
model、request count、latency、status 与可用 usage。若 provider 合同没有 usage，不解析或保存 raw body 来
猜测 token。价格表仅接受 manifest 中显式的 provider/model/date/unit price；缺失时成本字段为 unknown。

## 5. Scoring and inference

先对单次 attempt 评分，再按 case/arm 聚合三次重复：

- retrieval-sensitive：Hit@3、Recall@3、MRR@3、nDCG@3、target citation coverage；
- all cases：terminal/tool/argument/citation/refusal/unsupported-claim 与 composite task success；
- stability：三次成功率及 all-three-pass；
- operations：latency、tokens、request counts、fallback/failure taxonomy。

检索 uplift 只比较 8 个 retrieval-sensitive cases；4 个 copy/safety cases只做 non-regression。统计单元是 case，
不是 72 个互相独立的 attempts。固定 seed 做 10,000 次 case-level paired bootstrap，报告 delta 与 95% CI；
小样本、Seed label、provider 波动、缓存状态和本地语料范围写入 validity section。完整性失败或 CI 跨零时只
报告观察差异，不生成显著提升结论。

## 6. Artifact layout and privacy

```text
output/evals/agent-retrieval-ab/<run-id>/
  authorization.json
  dataset.private.jsonl
  oracle.private.jsonl
  manifest.json
  attempts/*.json
  failure-ledger.json
  metrics.json
  paired-report.md
  artifact-hashes.json
```

输出目录必须为新目录并保持 gitignored。privacy scanner 检查凭据形态、数据库 URL、真实 UUID、私有文档
路径、原始 provider body 和未脱敏语料。需要提交/展示时只能另行导出 aggregate-safe report，其中使用
case alias、hash、计数和聚合指标，且再次扫描。

## 7. Compatibility and rollback

- 新 runner 不加入默认 `make eval-check` 的 live 路径；provider-free unit/contract tests可进入 backend gate。
- 现有 `backend/evals/agent_workbench` 和 `backend/evals/brand_retrieval` canonical 文件不修改。
- 删除新 eval package/Make target 即可回滚；没有 Alembic、业务数据迁移、配置默认值或服务器状态变更。
- 若真实 run 失败，只删除或保留 ignored output 供诊断，不需要回滚业务数据库。

## 8. Zhipu structured-output compatibility

OpenAI-compatible Agent adapter 继续只接收标准 Chat Completions envelope 和标准 function tool calls，
但请求显式携带智谱文本模型支持的 `response_format={"type":"json_object"}`。JSON mode 只保证语法，
终答仍由现有 `AgentProposedAnswer` 严格校验；不接受 Markdown fence、额外字段、未知 claim kind、重复 JSON
key 或未经 observation 支持的 citation。

system message 提供固定的 final-answer JSON 形状，并根据已有 history 追加确定性 next-action guidance：

```text
no successful observation -> choose only a necessary typed tool
successful non-empty retrieval -> synthesize final JSON unless a different tool is required
successful empty retrieval -> refuse safely unless a different evidence source is required
```

guidance 只读取工具名、状态和结果是否非空，不复制私有结果文本，不修改工具 Schema，也不在 adapter 内
伪造终答。合法的 `search_evidence -> get_event` 或 evidence + brand 多工具链仍可由明确用户目标触发；
成功 `search_evidence` 后的同类同义重搜和纯证据问题的无条件事件下钻由 prompt contract 阻止。若模型仍
违反约束，现有四轮/四工具预算和失败终态继续 fail closed。

修复验证使用 MockTransport 覆盖请求 payload、标准 tool-call envelope、严格终答和历史提示，再创建全新
私有 run identity 做恰好两个 live cells。compatibility canary 无论通过与否都在第二格后硬停；它不是新的
72-cell 授权，不能形成 uplift 结论。
