# Agent 实习项目提升评审

> 2026-09-03 refresh：以下“当前结论”基于已推送的 GitHub `main`
> (`c472c6e8defc1b0f78f13acd95bf114c26c03b7f`)、当前代码、重新执行的 provider-free 质量门、
> GLM-5V-Turbo 已冻结 live evidence，以及当前官方岗位页面。文末保留
> 2026-08-18 的历史审计，用于说明项目演进；冲突时以本节为准。

## 当前结论

从当前可复验的工程证据看，这个项目已经具备投递 Agent 应用实习的技术深度。它最适合主投：

1. **Agent 应用开发 / LLM 应用工程**；
2. **AI 平台 / Agent Runtime 后端**；
3. **Agent Evaluation / AI 质量工程**；
4. RAG / Knowledge Engineering 与 AI 全栈作为补充方向。

真正的竞争力不是“用了 LangGraph、MCP、RAG”这些名词，而是把概率模型放进了可治理的工程边界：
调用前鉴权和预算预留、强类型工具、证据级引用、评测 one-shot 失败不补跑、因果 Trace、不可变工件、
离线与 live 评测隔离，以及根据 bad case 拒绝自动上线。

当前不适合把自己包装成 Agentic RL、模型训练或通用 Multi-Agent 算法候选人。百度当前的 Agent
算法岗位明确要求 RL/MARL、进化优化或 Generate--Evaluate--Refine 等算法证据；本项目的优势是系统
与评测工程，而非训练算法。

## 当前项目状态

| 方向 | 当前水平 | 可验证证据 | 不能夸大的边界 |
|---|---|---|---|
| Agent Runtime | 很强 | LangGraph 有界 loop，4-turn/4-tool-call，超时/字节/引用校验，42/42 deterministic contract cases | 42/42 不是 live LLM accuracy |
| Tool / MCP | 很强 | 同一 Typed Tool Registry 同源导出 Function Calling、MCP v2 stdio 与 Eval schema | 是本地只读 MCP，不是公网 MCP 平台 |
| 执行治理 | 很强 | role/task/artifact scope、调用前原子预算预留、exactly-once 对账、causal trace、immutable artifact | 尚无生产 SLO/告警或跨运行 OTel dashboard |
| Worker--Reviewer | 强（架构） | Writer/R1/Repair Writer/R2 分权，observe/enforce，最多一次修复，48/48 provider-free policy suite | 尚无完整 live A/B、人工 Gold 或质量 uplift |
| RAG / Grounding | 强（架构） | 外部事实与品牌上下文隔离；sanitized selector Recall@5 95%、nDCG@5 92.86% | 不是线上 embedding 或真实用户效果 |
| Agent Evaluation | 很强（方法） | deterministic regression 与 live evidence 分轨；holdout、AB/BA、repeat、成本、失败分母、bad cases | live tool-using Agent benchmark 尚未成功完成 |
| 多模态评测 | 很强 | GLM-5V-Turbo 120 次 one-shot，119 完成，holdout 83.33%，OCR 0/6 | 仅 6 个 source families、0 human/external labels |
| 公开作品集 | 中强 | GitHub 已有 Workbench、截图、manifest、case study、公开简历和复验命令 | 无 Actions、License、Pages；README 首屏过长 |

本轮在当前工作区重新执行 `make agent-portfolio-check` 和 `make eval-check` 均通过：Workbench 42/42、
品牌检索 36/36、图片规则 48/48、数字 IP 5/5、IP Asset 41 cases、Grounded Seed V1/V2 完整性以及
视觉检索回归均通过。这些数字必须继续标注为 fixture/contract/Seed，而不是线上模型质量。当前
`eval-check` 还覆盖了未提交的选题重排 WIP（10/10）；公开 GitHub `main` 只有已提交的 8/8 基线，
因此 10/10 不能进入公开简历或远端 HEAD 的证据清单。

## 最亮眼的五项技术能力

### 1. Agent Capability Gateway 与持久化多维预算

这是项目最有含金量、当前简历却最容易被低估的一项。

- 模型或工具调用前，先校验 role、task、artifact scope、access class、参数大小和预算；
- 对 elapsed、model turns、input/output tokens、tool calls、result bytes、artifact bytes、child/depth
  等维度进行 durable reservation；
- 成功、超时、取消、异常、usage unknown 和超额结果都经过 exactly-once reconciliation；
- 事件、工件和 parent event 形成可复算的 causal lineage，原始 prompt/provider body 不进安全 Trace；
- 并发 child/capability reservation 不允许 oversell，失败不会通过重试获得新预算。

这直接对应 AI 平台岗位的调用治理、权限、成本、可靠性与可观测性，比“会写 ReAct”稀缺。

### 2. Function Calling、MCP 与 Eval 共用一个 Typed Tool Registry

四个只读工具的 Pydantic input/output、timeout、byte limit、safe summary、read-only annotation 和 schema
hash 只有一个所有者；Agent 调用、MCP v2 stdio 和评测从同一 registry 派生，避免三套 schema/handler
漂移。官方 MCP client contract tests 覆盖 list/call、unknown tool、timeout 和 subprocess stdio。

简历应突出“统一契约和运行时验证”，不要把“接入 MCP”当成全部价值。

### 3. Claim-level grounding 是运行时不变量

外部事实 claim 只能绑定本次运行成功返回的 Tier A/B evidence；品牌 RAG 永远
`evidence_eligible=false`，不能冒充新闻事实。不存在、冲突或类型错误的 citation 会在 finalize 阶段
fail closed。Trace 只保留安全字段，而不是泄露 chain-of-thought。

这比泛写“RAG 降低幻觉”更可验证，也更容易回答面试官关于 grounding、引用可信度与上下文污染的问题。

### 4. 固定、受治理的 Writer--Reviewer 协议

项目不是开放式 Agent swarm，而是更可信的固定多角色协议：Writer 生成，Reviewer R1 只读审校；只有
闭集、可修复 issue 才能映射为 code-owned repair directive；最多执行一次 Repair Writer，再由 Reviewer
R2 终审。`off` 是默认，`enforce` 还需要显式 acknowledgement 与 calibration report SHA。在
`enforce` 下，unknown/unavailable/budget denial 都进入稳定人工复核，不产生无限 reflection；
`observe` 下这些结果只记录证据，不阻断原业务流程。

这可以称为“bounded multi-agent review protocol”，不能声称动态协商、群体智能或已经提高线上质量。

### 5. 可证伪、能产生工程决策的 GLM-5V 图片评测

唯一识图模型为直连智谱 `glm-5v-turbo`。以 6 个独立 source families 派生 48 对样本，按 family 拆分
calibration/holdout，执行 AB/BA 与固定 repeat 共 120 次 one-shot 调用；119 次完成、1 次
provider rejection，不补跑，失败和 unknown cost 保留在分母。

- Objective pair accuracy：29/36（80.56%）；
- Holdout：15/18（83.33%）；
- Arm macro-F1：89.54%；
- P50/P95：5.39s / 21.20s；
- 已知成本：CNY 3.085126；
- OCR/visible text：0/6，OCR 维度 critical false-accept rate 33.33%。

最有价值的结论不是 80.56%，而是实验发现 VLM 对 OCR 不安全，因此生产继续保留确定性 OCR/hard
validation，评测输出保持 `non_activating=true`。这能体现实验设计、负样本归因和工程判断。

## 当前分级提升路线

以下成本是基于现有实现的工程时间估算，不包含等待授权或招聘页面变化。P0 完成后就应开始投递，
不需要等待 P1/P2。

### P0：直接影响投递与面试转化

| 事项 | 招聘价值 | 最小交付物 | 预计成本 | 暂不做的代价 |
|---|---|---|---:|---|
| 成功的 live tool-using Agent benchmark | 把 42/42 固定策略契约补成真实模型的工具选择、参数生成和拒答证据 | 冻结 24--40 个 sanitized objective tasks，覆盖正确工具、坏参数、未知工具、无证据拒答、超时和预算耗尽；同一智谱模型重复 2--3 次，报告 Pass@1、task success、tool selection、argument validity、citation/refusal、failure taxonomy、P50/P95、token 与 CNY cost；LLM judge 仅作开放文本次级 grader，无人工标签时明确 `human_labels=0` | 1--2 天工程 + 经 preflight 封顶的模型费用 | 面试中仍只能证明 runtime/contract，无法证明 live Agent intelligence |
| 招聘者可在 90 秒内看懂并复验 | 把 Capability Gateway、Trace 和 GLM bad case 从长文档提升为首屏证据 | README 前 60--90 行改为求职 landing page；加入 Agent Trace、四项证据表和一条无 Key 命令；生成 60--90 秒静态 replay/录屏；简历直链仓库与 case study，并采用下文三条 bullet | 0.5--1 天 | 招聘者可能只看到内容运营系统，最强 Agent 工程证据无法转化为面试 |
| 公开仓库信任信号 | 让第三方相信远端 HEAD 可复验且权利边界清楚 | 设置 description/topics/homepage；增加只读、无 secret、provider-free GitHub Actions；先确认代码与公司品牌资产授权，再决定 License，并用 NOTICE 区分代码、商标、品牌素材和第三方内容 | 0.5--1 天 + 权利确认等待 | 没有远端绿灯和授权说明，会降低复现可信度并产生知识产权疑问 |

Workbench 已有一次智谱 live 尝试，但它在 typed evidence verification 前失败且未重试；增强检索 A/B
也在 canary 后停止。因此当前不能声称真实模型 task success、检索 uplift 或 Reviewer 质量提升。

### P1：完成 P0 后拉开工程差距

| 事项 | 招聘价值 | 最小交付物 | 预计成本 | 暂不做的代价 |
|---|---|---|---:|---|
| 安全 AgentOps / OpenTelemetry 导出 | 补齐平台岗关注的跨运行观测、版本退化和成本回归 | 将现有 safe trace 映射为固定版本的 Agent/model/tool spans，只导出 allowlisted attributes；按模型/版本汇总 success、failure、latency、token、cost，并做一个离线 dashboard | 1--2 天 | 只能展示单次因果 Trace，无法证明持续运行质量或退化检测 |
| MCP 客户端互操作演示 | 把“同 registry 的 stdio MCP”变成招聘者可见的协议证据 | 用官方客户端测试之外的一个常见 MCP 客户端或可复验脚本完成 discover + call 录屏/日志；保留本地只读、无网络和无 secret 边界 | 0.5 天 | MCP 仍主要是代码与 contract-test 亮点，非技术招聘者不易验证 |
| 反馈到回归集的闭环 | 对齐 Agent Evaluation 岗的 failure mining 与持续改进要求 | 将一次真实坏例或明确人工反馈匿名化，经过确认后写入 versioned regression set；保留标签来源、裁决过程和修复前后结果 | 1--2 天（获得可公开案例后） | 评测仍以 fixture、AI-authored Seed 和零人工标签为主，难证明线上学习闭环 |

### P2：明确延期，不为关键词扩张

| 延期项 | 现在不做的理由 | 若现在做的成本 | 延期的实际代价 |
|---|---|---:|---|
| 通用 Multi-Agent debate、A2A、swarm | 尚无单 Agent live failure/消融证明需要动态协商，只会增加延迟、权限和评测面 | 2--5 天起 + 新 live eval | 很低；固定 Writer--Reviewer 已足够证明受治理的角色分工 |
| 长期 Memory、无限 Reflection/Replan | 当前业务无明确跨会话需求，且无限循环破坏硬预算和可复算性 | 2--5 天起 | 很低；面试时说明这是基于需求与风险的有意取舍 |
| SFT/DPO/GRPO/RL | 属于模型训练/算法研究轨道，需要独立数据、算力、基线和消融 | 1--3 周起 + 算力/数据 | 对应用/平台/评测岗很低；代价只是不能凭本项目主投训练算法岗 |
| 更换 Agent/RAG 框架或继续增加工具 | 不解决 live 证据、可见性和公开信任问题 | 1--3 天 | 接近零；四个工具已覆盖检索、事件、品牌上下文和确定性验证 |

## 可直接用于简历的三条 bullet

1. **Agent Runtime / MCP**：基于 LangGraph 实现 4-turn/4-tool-call 有界 Agent loop，以同一 Typed Tool
   Registry 统一 Function Calling、MCP v2 stdio 与 Eval schema；在调用边界校验参数/结果、timeout、
   byte budget、重复调用和 claim-level citation，42/42 条确定性工具与 grounding 契约通过。
2. **执行治理 / Reviewer**：设计 Agent Capability Gateway 与固定 Writer--Reviewer 协议，对 role、task、
   Artifact 和读写权限做调用前校验，原子预留并 exactly-once 对账多维预算；支持 observe/enforce、最多
   一次 code-directed repair、`result_unknown` 恢复及不可变因果 Trace，48/48 条离线 Reviewer policy
   cases 通过。
3. **多模态 Eval**：在 6 个独立素材族上构造覆盖六维的 48 组 GLM-5V-Turbo AB/BA + repeat 样本并
   执行 120 次 hash-bound one-shot 调用；holdout objective pair accuracy 83.33%，定位 OCR 0/6、OCR
   维度 critical FAR 33.33% 的失效，据此保留确定性 OCR 门禁且不自动激活生产策略。

面试时必须主动补充：42/42 和 Reviewer 48/48 是 provider-free contract/policy；GLM 数据只有 6 个独立
来源族、0 人工/外部标签和 1 次 provider rejection。

## 三分钟面试讲法

> 我做的不是一个靠 Prompt 串起来的 Demo，而是一套有真实业务输入的可评测 Agent 平台。Function
> Calling、MCP 和 Eval 共用同一个 typed registry；Capability Gateway 在 provider/tool 调用前校验角色、
> 任务、工件范围并预留多维预算，所有终态进入脱敏 causal trace。Writer--Reviewer 只有一次受控修复，
> 不允许无限自我反思。为了验证多模态审校，我对 GLM-5V-Turbo 做了 120 次 AB/BA + holdout 实验，结果
> 发现 OCR 维度 0/6，所以没有拿总体分数强行上线，而是保留确定性 OCR 门禁。

## 不要继续堆的内容

上表 P2 已给出逐项理由和成本。核心原则是：在成功的 live Agent benchmark、公开证据入口和远端
质量门补齐前，不增加通用 Multi-Agent、A2A、swarm、长期 Memory、无限 Reflection、训练框架、
Agent/RAG 框架或更多工具。

## 当前岗位映射

- [百度 Agent 工程师实习岗位](https://talent.baidu.com/jobs/detail/INTERN/3ddcb5a1-63d7-4596-b7cf-d636dad39f60)
  强调真实模型 Agent、上下文工程、RAG、Memory、Skill、MCP 与性能评估；
  项目强匹配 Runtime/Tool/MCP/RAG/Eval，Memory 可解释为无业务需求而有意不做。
- [百度 Agent 评估实习岗位](https://talent.baidu.com/jobs/detail/INTERN/a0bbc449-854f-421c-bfaf-1a5be906f86e)
  强调自动化评测、消融、行为日志、负样本归因、LLM-as-a-judge/环境反馈和
  Benchmark；图片实验、失败 taxonomy 与非激活结论高度匹配，live Agent benchmark 是主要缺口。
- [百度 AI 开放平台研发实习岗位](https://talent.baidu.com/jobs/detail/INTERN/ef30e579-2d3d-4539-ad90-884521b815c9)
  强调 Agent/API/CLI/Skill 服务化、Tool/MCP/Function Calling、鉴权配额、模型路由、限流缓存与日志监控；
  项目的 Typed Registry 和 Capability Gateway 强匹配，但该岗位主栈还包括 Java/Spring/MySQL/Redis。
- [Grab Agents Platform 实习岗位](https://jobs.smartrecruiters.com/Grab/744000126568308-intern-ai-engineer)
  强调 eval pipeline、golden dataset、failure mode、model comparison、trace rendering 和
  LangSmith/OpenTelemetry；项目的评测方法匹配，但人工 Gold 和跨运行观测仍是缺口。
- [百度 Agent 算法实习岗位](https://talent.baidu.com/jobs/detail/INTERN/cd423c1c-7a35-4672-b0a7-2857308efe43)
  强调 RL/MARL、进化算法或自进化决策；当前项目不应靠添加框架标签去匹配。

岗位状态会变化，以上状态与要求以 2026-09-03 的官方页面或当天官方索引为准，投递前需要重新核验。

## 相关证据

- [当前 Agent 能力审计](./current-agent-capability-audit-2026-09-03.md)
- [当前公开作品集审计](./current-portfolio-readiness-2026-09-03.md)
- [当前 Agent 实习岗位研究](./current-agent-internship-market-2026-09-03.md)
- [Workbench 规范](../../../../.trellis/spec/backend/agent-workbench.md)
- [执行治理规范](../../../../.trellis/spec/backend/execution-governance.md)
- [Writer--Reviewer 规范](../../../../.trellis/spec/backend/official-account-reviewer.md)
- [图片质量评测规范](../../../../.trellis/spec/backend/image-quality-evaluation.md)
- [GLM-5V-Turbo live evidence](../../archive/2026-09/09-02-image-vlm-human-calibration/research/glm-5v-turbo-live-evidence-2026-09-03.md)
- [Agent Workbench case study](../../../../docs/portfolio/agent-workbench.md)
- [公开简历 TeX](../../../../docs/portfolio/resume/resume-public.tex)
- [公开 GitHub 仓库](https://github.com/EDLlyc/edu-ai-lead-agent)

---

## 历史审计（2026-08-18，保留用于演进对照）

### 结论

这个项目已经超过普通实习作品的“功能及格线”。继续增加 Agent 数量、Memory、A2A 或更多工具，
对求职帮助很有限。当前最大问题是：核心能力留在本地仓库和长文档里，招聘者无法在几分钟内验证；
同时现有评测主要证明契约正确，尚未证明真实模型在工具选择、参数生成、多轮执行和失败恢复上的质量。

建议主投 **Agent 应用开发 / AI 平台后端**，副投 **Agent Evaluation / AI 全栈**。不建议把当前项目
包装成 Agentic RL 或大模型训练项目。

### 现有亮点与岗位映射

| 岗位要求 | 当前项目证据 | 判断 |
| --- | --- | --- |
| Python、FastAPI、PostgreSQL、工程落地 | 多进程业务流水线、真实 PostgreSQL、迁移、强类型 API、完整测试 | 强 |
| RAG / 知识库 / 数据治理 | 品牌 hybrid RAG、受治理 evidence/event、引用边界、数字 IP active-ready 投影 | 强 |
| Function Calling / Tool Use | 四个强类型只读工具、参数和结果双向校验、typed failure | 强 |
| MCP / Skill 接入 | 同一 registry 导出 MCP v2 stdio，不复制 handler/schema | 强，但展示弱 |
| Agent 编排 | bounded model-tool loop、次数/时间/token/output 预算、拒绝和 fallback | 强 |
| Agent 评测 | 42 条 Workbench、8 条 rerank、5 条数字 IP deterministic cases | 中强，缺 live 质量 |
| Trace / 安全 | claim-level citation、脱敏 Trace、只读事务、无任意 URL/SQL/shell | 强 |
| 可观测性 / AgentOps | 有单次 Trace、usage、latency、安全错误分类 | 中，缺跨运行统计 |
| 真实模型适配 | 智谱 JSON contract、严格 parser、单次兼容性验证 | 中，缺版本化对比实验 |
| 招聘者可访问性 | README、case study、截图、本地命令 | 弱，公开仓库仍看不到最终能力 |
| 开源协作证据 | 代码质量门和文档较强 | 弱，缺公开 CI、License、可复现 Release |

当前岗位也印证了这一排序：AI 平台岗直接要求 Agent Tool、Skill、MCP、Function Calling、模型调用
治理和可观测性；Agent 工程岗强调 RAG、Memory、Skill、MCP、性能评估；Agent 评测岗强调 golden
dataset、失败归因、Trace、对照实验和评测报告。项目已经覆盖前半部分，缺口集中在“公开证据、
真实评测、跨运行观测”，而不是基础 Agent 框架。

### P0：投简历前优先完成

#### 1. 完成公开求职作品集

- **为什么最重要**：目前招聘者无法从公开 GitHub 看到 Workbench；再好的本地实现也无法转化为面试。
- **已有基础**：case study、架构图、截图、42/42 报告、README 入口均已存在；
  `08-17-agent-workbench-public-portfolio` 已完成需求规划。
- **最小交付物**：公开可审计代码树、README 首屏、静态 replay 页面、60--90 秒演示、一条无密钥
  fixture-only 命令、只读 CI、清晰 License/NOTICE。
- **成本**：约 1--2 天；不需要改生产 Agent。
- **验收重点**：30 秒看懂价值，3 分钟看到一次真实多工具 Trace 和一个安全拒绝，命令可复现。

#### 2. 增加 opt-in 真实模型评测轨道

- **为什么重要**：42/42 是固定策略 contract baseline，面试官会追问“换成真实模型后成功率如何”。
- **已有基础**：OpenAI-compatible adapter、严格 Tool schema、完整 trace、eval case schema 和安全指标。
- **最小交付物**：同一脱敏数据集跑 2--3 次真实模型；记录工具选择正确率、参数合法率、任务成功率、
  引用覆盖、拒绝准确率、P50/P95 latency、token/cost、失败类型；canonical deterministic 报告保持独立。
- **成本**：约 1 天代码 + 少量受控模型费用。
- **验收重点**：展示 bad case 和修复前后对比，不只展示平均分；禁止 LLM judge 成为唯一真值。

#### 3. 收敛简历叙事和三分钟 Demo

- **为什么重要**：当前 README 很完整，但信息密度高，容易让核心 Agent 能力淹没在业务/发布细节里。
- **最小交付物**：一个项目标题、三条简历 bullet、一个架构图、一个成功 Trace、一个失败恢复案例、
  一张指标表；面试讲解按“问题—设计—边界—指标—取舍”展开。
- **成本**：半天。
- **建议标题**：`面向内容研究的可评测 Agent 工作台（LangGraph + MCP + RAG + Eval）`。

### P1：P0 完成后增强

#### 4. 增加轻量 AgentOps 运行对比

- 不急着建设完整持久化平台。先把脱敏 run artifact 导出为 JSONL，生成模型/版本维度的成功率、
  工具错误、fallback、token、latency 和失败 taxonomy 汇总。
- 可选接入 OpenTelemetry，仅记录受控 span attribute；不要存 raw prompt、provider body 或业务正文。
- 这能直接回答“如何发现 Agent 退化”和“如何做模型版本回归”。
- **成本**：1--2 天。

#### 5. 做一个真正的 MCP 客户端演示

- MCP server 已经存在，没必要新增工具。补一段受控的客户端连接示例或录屏，证明 Cursor、Claude
  Desktop 或其他 MCP client 能发现 schema、调用两个工具并收到 typed result。
- 演示必须使用 fixture/read-only 数据；不要把 MCP 暴露成公网服务。
- **成本**：半天。

#### 6. 把数字 IP 库变成可量化案例

- 当前 5/5 只证明 contract conformance。增加 20--30 条脱敏 query 的小型 gold set，衡量 Recall@K、
  MRR、标签覆盖、禁用规则命中和 brand-as-fact 违规率。
- 将本地 feedback ledger 导出成脱敏分析报告，展示“哪些品牌资料被采用/拒绝以及原因”；暂不写回生产。
- **成本**：1--2 天。

#### 7. 补一份系统设计取舍文档

- 用一页说明为什么 Tool registry 单一来源、为什么 MCP 只走 stdio、为什么品牌不能当事实、为什么
  loop 有硬预算、为什么 Workbench 不进生产。
- 这比再加一个框架更能体现工程判断和安全意识。
- **成本**：半天；现有文档可直接提炼。

### P2：明确延期

- **长期 Memory**：只有出现跨会话用户任务时再做；当前 fixture 研究任务不需要。
- **Multi-Agent / A2A**：现有任务不需要角色协商，加入后只会增加 latency、失败面和评测成本。
- **Reflection / 自我修正循环**：先用真实模型 bad case 证明单 loop 的具体瓶颈，再决定是否增加。
- **模型微调、SFT、DPO、GRPO**：这是算法岗的另一条作品线，需要数据、训练和消融证据，不应贴标签。
- **公网 Agent 服务**：当前 loopback-only 是合理安全边界；公开展示应使用静态 replay，不是直接暴露 API。
- **更多工具**：现有四个工具已足够展示检索、事件查看、品牌 RAG 和验证；工具数量不是竞争力。

### 推荐执行顺序

1. 公开作品集与一键 Demo。
2. 真实模型 eval + bad-case 报告。
3. 简历/面试材料收敛。
4. AgentOps 汇总和 MCP 客户端演示。
5. 数字 IP 真实检索评测。

前 3 项完成后就应开始投递，不需要等待 P1/P2。对于 Agent 应用工程岗，项目已经有足够深度；后续
工作的目标是提高可信度和可见性，而不是继续扩大代码量。

### 当时招聘证据摘要

- 百度 AI 开放平台研发实习岗把 Agent Tool、Skill、MCP、Function Calling、上下文管理、调用治理、
  限流和可观测性列为职责或加分项。
- 百度 Agent 工程岗把 RAG、Memory、Skill、MCP、框架应用和性能评估列为核心经验。
- 百度 Agent 评估岗强调自动化评测、消融、行为日志、负样本归因和 benchmark。
- Grab Agents Platform 实习岗强调 golden datasets、multi-turn/multi-agent eval、trace rendering、
  failure modes 和 OpenTelemetry/LangSmith 类观测工具。
- XPENG Agentic Infrastructure 实习岗强调 MCP connector、evaluation、CI/CD、observability、
  structured validation 和 dashboard。

这些要求说明：本项目的技术方向正确，当前最值得投资的是评测和作品集证据。

### 当时参考岗位

- [百度 AI 开放平台研发工程师实习生](https://talent.baidu.com/jobs/detail/INTERN/ef30e579-2d3d-4539-ad90-884521b815c9)
- [百度 Agent 工程师](https://talent.baidu.com/jobs/detail/INTERN/3ddcb5a1-63d7-4596-b7cf-d636dad39f60)
- [百度 Agent 评估工程师实习生](https://talent.baidu.com/jobs/detail/INTERN/a0bbc449-854f-421c-bfaf-1a5be906f86e)
- [Grab AI Engineer Intern — Agents Platform](https://jobs.smartrecruiters.com/Grab/744000126568308-intern-ai-engineer)
- [XPENG Agentic Infrastructure Engineer Intern](https://job-boards.greenhouse.io/xpengmotors/jobs/8559314002)
