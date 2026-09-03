# Agent 检索增强真实 A/B：实施结果

## 已完成

- 新增独立 `backend/evals/agent_retrieval_live_ab/`，复用生产 `BoundedAgentRunner`、
  `TypedToolRegistry`、plain/enhanced reader 与既有智谱/阿里 provider adapter。
- provider-free preflight 在 repeatable-read + read-only PostgreSQL 事务中冻结 12 个 Codex Seed case，
  验证 8 个检索样本、4 个负对照、oracle 存在性、Registry 一致性、快照和调用上限。
- 增加 fixed-seed AB/BA 调度、72/216/108/108/108 硬预算、独立 arm cache、不可覆盖 attempt journal、
  10,000 次 case-level paired bootstrap、aggregate-safe 报告和隐私扫描。
- 本地忽略输出：`output/evals/agent-retrieval-ab/agent-ab-20260902-v1/`。

## 真实运行结果

一次已授权 live run 在系统性失败后按 fail-closed 原则提前停止：留下 7 个终态 observation 和 1 个
`started` 中断 journal，没有重跑失败 cell。7 个终态均未达到 task success；其中 6 个是模型协议/可用性
失败，1 个是取消终态。已完成的调用计数为 Agent decision 19、planner 6、reranker 4、Alibaba embedding 0。

失败主要发生在 Agent 决策层：智谱模型多次重复调用证据工具、额外下钻事件，并在三次模型决策预算内未
生成符合严格 JSON 最终协议的回答；另有超时/不可用终态。因为 72-cell 矩阵不完整，报告明确禁止生成
retrieval uplift 或简历效果结论。

## 证据边界

- `paired-report.md` 明确标记 incomplete、Codex Seed、非 human Gold、local-only 和 unknown cost。
- private dataset/oracle/attempts 保持 gitignored；提交内容不含真实 UUID、语料、provider body 或凭据。
- 没有修改生产 Agent prompt、检索、MCP、数据库、公众号、部署或 canonical eval。

## 后续建议

如需第二次真实运行，应另建授权，而不是续跑或覆盖本次证据。先单独诊断智谱工具循环与严格最终 JSON
兼容性，并决定是恢复生产四轮上限、增加通用重复调用终止约束，还是使用更适合 strict tool-calling 的
Agent 模型；这些都属于新的实验变量，不能悄悄并入本次 A/B。

## v2 新授权修订与结果

用户已单独授权一个全新、最多 72 attempts 的 v2 矩阵；它不续跑或覆盖上述 v1。v2 将每个 attempt 恢复
为生产一致的四次模型决策/四次工具调用，Agent decision 总上限为 288，其他 provider 上限仍为 108。
前两个 cell 是同一 case/repetition 的 A/B 强制金丝雀：只有两臂完整通过终态、任务、工具、参数、Top-3
target 全召回、全引用及 provider/protocol/budget 门禁，才继续后 70 个；否则立即产出 incomplete/no-uplift
报告。金丝雀通过后仍有连续四次系统性失败熔断，且不自动重跑任何 cell。

全部 provider-free 门禁和 v2 preflight 通过后，唯一一次新授权 live run 执行了前两个金丝雀 cell，并按
设计立即停止：`completed_attempts=2/72`、`canary_passed=false`、`circuit_breaker_reason=canary_failed`。
raw 臂终态为 `agent_model_unavailable`，enhanced 臂终态为 `agent_model_invalid_output`；两臂 task success
均为 0。安全聚合计数为 Agent decisions 6、Planner 2、Reranker 1、Alibaba Embedding 0；无 executor、
预算或非终态 journal 失败。剩余 70 个 cell 未执行，且没有手工、静默或整套重跑。

v2 的 aggregate-safe 报告已离线复算，manifest/dataset/oracle/authorization/report/attempt 文件哈希均验证
一致。结论明确为不完整实验、不可声明 retrieval uplift；旧 v1 和新 v2 均保留在各自 gitignored 目录，
互不续跑或覆盖。

## v2 验证

- 新增/相关 provider-free tests 58/58 通过，其中本评测 package focused tests 14/14 通过。
- Ruff、targeted mypy、Agent canonical 42/42、Brand RAG canonical 36/36、Trellis task validate 与
  scoped `git diff --check` 通过。
- v2 provider-free preflight 冻结 12 cases、2 arms、3 repetitions，并确认 72 attempts、288 Agent
  decisions、Planner/Reranker/Embedding 各 108 的上限；preflight provider 调用为 0。

## 独立复核修正

- 不完整的 7/72 观察不再用 0 填充其余 case；所有 paired delta 与 95% CI 均明确为 `N/A/null`，
  只保留已完成 attempt 的描述性诊断。当前只有 1/8 个检索 case 形成完整的三次配对，不能做 A/B 结论。
- 失败分类修正为 6 次 Agent 模型失败、1 次取消终态和 1 个非终态 `started` journal；19/6/4/0
  capability 计数明确只是已落终态 observation 的已知下界。
- 复核同时收紧了本地 PostgreSQL、manifest/provider/source 漂移、授权/attempt 绑定、artifact 权限与
  symlink 边界，并按 evidence/brand 两个命名空间分别计算多工具 case 的 Top-3。

## 最终本地复核

- 本任务相关 provider-free 回归 43/43 通过，其中新评测 focused tests 14/14；Ruff 与 targeted strict
  mypy 通过。
- 既有 Agent canonical 42/42、Brand RAG canonical 36/36 均通过且未改写。
- Trellis context、私有 artifact 权限/隐私扫描和全工作区 `git diff --check` 通过。
- 唯一未满足项仍是完整的 72-cell live matrix；任务保持未完成，不生成简历指标。

独立复核另发现原 v2 Seed 的 evidence 命名空间包含 5 个 qrel，却要求 `Recall@3=1`，导致该检索门禁在
数学上不可达。实现现已把每个命名空间的 qrel 上限固定为 3，并在新 preflight 前 fail closed。已产生的
两格 v2 观察仍如实证明 raw=`agent_model_unavailable`、enhanced=`agent_model_invalid_output`，其停止决定
不依赖该 qrel 缺陷；但该历史 run 继续保持 incomplete/不可声明 uplift，不能续跑来形成新矩阵。

## Phase 6 provider-free 兼容修复

- OpenAI-compatible Agent 请求现显式携带 `response_format={"type":"json_object"}`，system
  message 固定 completed/refused 四字段终答契约。最终答案仍经 `AgentProposedAnswer` 严格校验，
  并额外拒绝 Markdown fence、重复 JSON key、缺少/多余顶层字段；未放宽工具参数、unknown tool、
  call ID 或引用校验。
- 根据已有 history 只投影工具名、成功状态和结果是否为空，生成确定性 next-action guidance；
  成功检索后禁止同类同义重搜，纯证据问题不再无条件下钻 `get_event`，明确要求事件详情或品牌
  结果的合法多工具链仍保留。guidance 不复制私有工具正文，不持久化 provider body/prompt。
- 新增 v3 `compatibility_canary_only` manifest/authorization/attempt/report 身份。授权硬上限为
  2 个 Agent attempts、8 个 Agent decisions，planner/reranker/embedding 各 4 次；调度器只取首个 A/B
  pair，第二格后无论成败都停止，离线报告拒绝任何超过两格的 v3 artifact。v1/v2 不能被 v3
  续跑、转换或覆盖。
- provider-free 相关回归 83/83 通过；Ruff、targeted strict mypy 和 `git diff --check` 通过。
  Agent canonical 42/42、Brand RAG canonical 36/36 通过。本阶段未调用任何 live provider。

## Phase 6 live 执行边界

v3 private preflight 与唯一一次 2-cell live canary 已由主会话执行；使用全新目录和授权，未读取、续跑或
覆盖旧 v1/v2 结果。第二格后无条件停止，剩余 70 格不在本次授权范围内。

## Phase 6 独立检查修正

- 独立检查发现 CLI 调度器虽只执行两格，但公共报告构建函数仍可接受 72 个 v3 attempt 并生成带 uplift
  字段的 v3 报告。现已在报告构建和 `PairedReport` Schema 双层限制最多两格、仅允许首个 A/B canary，
  同时拒绝越权 capability 总数、总数与 terminal attempt ledger 不一致、以及 failure count 大于请求数。
- 报告现在分别展示“授权兼容性 attempts（最多 2）”和“完整配对矩阵覆盖（共 72）”，避免把成功完成
  两格授权误读为已完成检索 uplift 实验；无论两格通过或失败，paired delta/CI 仍为 `N/A/null`。
- `.trellis/spec/backend/agent-workbench.md` 已同步 v3 acknowledgement、两格无条件硬停、智谱 JSON mode、
  私有正文不进入 guidance，以及合法 event/brand 多工具路径约束。
- provider-free Agent/检索相关测试 117/117 通过；focused Phase 6 测试 32/32 通过，Ruff、targeted strict
  mypy、Agent canonical 42/42、Brand RAG canonical 36/36 和 `git diff --check` 均通过。检查未调用任何
  provider、preflight、live、服务器、部署或发布命令。

## v3 compatibility canary 实际结果

- 新建私有目录 `output/evals/agent-retrieval-ab/agent-ab-20260903-v3-compat-canary/`；preflight 冻结
  12 个 Seed case 与当前只读 PostgreSQL 快照，确认授权仅为 2 attempts / 8 Agent decisions，preflight
  provider 调用为 0。
- 唯一一次 live 执行严格停在第 2 格：`completed_attempts=2/2`、完整矩阵覆盖 `2/72`，剩余 70 格未执行，
  没有重跑、续跑或覆盖旧证据。
- 两臂 Agent 均在 2 次模型决策内完成，仅调用一次 `search_evidence`，终态、工具、参数、引用和 task
  success 均通过；provider failure、bounded/cancelled run 与 executor failure 均为 0。这证明本阶段修复的
  智谱 tool-call 到 strict JSON final-answer 兼容链路已经跑通。
- raw 臂 Top-3 的 Hit/Recall/MRR/nDCG 为 `1/1/1/1`；enhanced 臂为
  `1/0.3333/0.3333/0.1443`。enhanced 最终引用覆盖完整，但其 Top-3 只覆盖一个 Seed qrel，因此严格
  canary 为 `false`、circuit=`canary_failed`。
- 该结果只支持“协议兼容修复有效”，同时暴露当前单例中增强排序的 Top-3 退化；`2/72` 不是完整 A/B，
  所有 paired delta/CI 保持 `N/A/null`，不得形成 retrieval uplift 或简历效果结论。
- 离线 report 已复算并通过 v3 两格、capability ledger、artifact hash 与隐私边界校验；报告命令因
  `canary_passed=false` 按设计返回非零，不代表执行器或 provider 异常。
