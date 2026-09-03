# Research: 2026 Agent 实习岗位要求与当前项目证据映射

- Query: 截至 2026-09-03，Agent 应用工程、AI 平台后端、Agent Evaluation 实习岗位真正重视哪些能力；当前 `edu-ai-lead-agent` 能证明什么、还缺什么。
- Scope: mixed（当前官方招聘页 / 雇主 ATS、一手工程规范、当前本地代码与已公开 GitHub 证据）
- Date: 2026-09-03

## Findings

### 1. 结论

当前项目对以下岗位已经有较强竞争力，排序为：

1. **Agent 应用开发 / Python LLM 应用工程**；
2. **AI 平台后端 / Agent Runtime 工程**；
3. **Agent Evaluation / AI 质量工程**；
4. AI 全栈（作为副定位）。

它不适合作为 Agentic RL、模型后训练或纯算法研究岗的主要证明。后者当前明确要求
PyTorch、大模型训练链路、PPO/GRPO/SFT/RM/RL 或论文实验；本仓库的核心价值是应用、平台治理和
评测，不是训练。

项目最有区分度的叙事也不应只是“用了 LangGraph、MCP、RAG”，而应是：

> **把模型、Tool Calling、MCP、RAG、Reviewer 和多模态评测放进一个有类型、有预算、可追踪、
> 可失败、可复算的 Agent 工程系统，并用真实 bad case 决定确定性安全门禁。**

这比“做了多个 Agent”更符合当前招聘信号。多 Agent 只在业务任务确实需要角色分工或招聘岗位本身
负责 multi-agent eval 时才构成证据；Agent 数量本身不是质量指标。

### 2. 当前官方岗位信号

以下页面均为雇主官网或雇主使用的官方 ATS，不使用培训机构、转载站或二手岗位聚合。状态以
2026-09-03 无登录访问或当天搜索索引为准；招聘页面随时可能下线，不能把“今天可访问”等同于长期有效。

| 方向 | 当前一手岗位 | 明确信号 | 2026-09-03 状态说明 |
|---|---|---|---|
| AI 平台后端 | [百度 AI 开放平台研发工程师实习生 J103363](https://talent.baidu.com/jobs/detail/INTERN/ef30e579-2d3d-4539-ad90-884521b815c9) | Agent/API/CLI/Skill 服务化；Tool、MCP、Function Calling；能力注册、鉴权配额、模型路由、上下文、流式响应、限流缓存、日志监控；Java/Spring/MySQL/Redis 为该岗主栈 | 页面可直接读取，职位日期 2026-07-21；百度日常实习页面说明全年开放，但具体岗位仍可能随时关闭 |
| Agent 应用工程 | [百度 Agent 工程师 J100994](https://talent.baidu.com/jobs/detail/INTERN/3ddcb5a1-63d7-4596-b7cf-d636dad39f60) | 模型 Agent 实现、上下文工程、性能评估；RAG、Memory、Skill、MCP、主流 Agent 框架和实际落地 | 当前官方索引可检索，职位日期 2026-07-21；直接详情页有时只返回登录壳，正文可用性不稳定 |
| Agent 评测 | [百度 Agent 评估工程师实习生 J101070](https://talent.baidu.com/jobs/detail/INTERN/a0bbc449-854f-421c-bfaf-1a5be906f86e) | 自动化消融；记忆、规划、Tool-use、反思能力评估；演化日志分析、负样本归因、LLM-as-a-judge、环境反馈、benchmark 和技术报告 | 当前官方索引可检索，职位日期 2026-07-21；直接详情页有时只返回登录壳 |
| Agent 评测平台 | [Grab Intern, AI Engineer — Agents Platform](https://jobs.smartrecruiters.com/Grab/744000126568308-intern-ai-engineer) | Python/Go 生产代码；eval pipeline、golden dataset、LLM judge、failure mode、multi-turn/multi-agent/coding-agent eval、model comparison、trace rendering；LangSmith/OpenTelemetry、Temporal 为加分项 | SmartRecruiters 页面仍显示 Apply；要求 2026-05 起、至少 3 个月、马来西亚 Petaling Jaya 线下 |
| Agent 安全治理 | [百度安全风险治理实习生 J104021](https://talent.baidu.com/jobs/detail/INTERN/454a3bf2-a793-4503-9018-d7213b93522c) | 身份认证、权限、工具调用、数据访问、Prompt Injection、越权、数据泄漏；MCP 威胁建模、安全规范和闭环 | 页面可直接读取，职位日期 2026-08-04 |
| 企业 Agent 落地 | [Saronic Enterprise Technology Intern — AI and Automation](https://jobs.ashbyhq.com/saronic/c95c2e3a-4c67-47b0-a03d-0e0317ac11a3) | 规格驱动开发、可复用 Skill/Tool、MCP server/connector；eval、monitoring、logging、observability、错误处理、访问控制和数据治理 | Fall 2026 官方 ATS URL 当天可达但正文依赖 JavaScript，检索到的正文快照约 4 周前；美国线下且有出口管制身份限制，只作技能信号，不是默认投递建议 |
| 业务 Agent / 作品证明 | [Azul Marketing AI Intern](https://jobs.lever.co/azul/f94d4087-2dee-4d69-8596-883ff17efde2) | 构建真实内部 Agent、工作流和 MCP connector；收集反馈、持续迭代、文档化；明确要求展示一个自己能讲清楚的成品 | Lever 页面仍可申请；4 个月全职、美国远程；RAG/多模态被列为 stretch，而非必需 |
| 应用到生产 | [Mercura AI/LLM Engineering Intern](https://jobs.ashbyhq.com/mercura/24a9e5dc-384c-4351-a208-4b2a961d1d23) | tool-using agents、混合/结构化 RAG、eval/monitoring、human feedback pipeline、数据管线、可扩展/快速/鲁棒的生产基础设施 | 官方 ATS URL 当天可达但正文依赖 JavaScript，检索到的正文快照约 4 个月前；至少 4 个月；是否仍收件及地点/签证需实时复核 |

跨岗位重复出现、最能区分候选人的能力如下：

| 能力 | 市场强度 | 招聘者期待的证据，而非关键词 |
|---|---:|---|
| Tool / Function Calling | 必需 | 强类型输入输出、未知工具、坏参数、超时、重复调用、越权和副作用边界的处理 |
| MCP | 高频加分 / 平台岗必需 | 同一业务能力真实导出并被客户端发现/调用；schema 不漂移；传输与权限边界讲得清楚 |
| RAG / Context Engineering | 必需或高频 | 可解释检索、版本与引用、Recall/MRR/nDCG、无答案/近似负例、事实与品牌/内部上下文隔离 |
| Evals / golden set | 最强区分项之一 | 冻结数据、dev/holdout、重复试验、明确分母、bad-case taxonomy、回归与复算，不只报平均分 |
| Trace / Observability | 平台和评测岗高频 | 一次运行的模型/工具 span、usage、latency、failure；进一步是跨运行比较和退化告警 |
| Reliability | 必需 | timeout、budget、idempotency、retry policy、result-unknown、fallback、crash recovery、并发安全 |
| Guardrails / Security | 高频 | 最小权限、工具授权、Prompt Injection 边界、PII/secret 脱敏、写操作确认、可审计拒绝 |
| Deployment / backend | 应用与平台岗必需 | API、DB、队列/worker、容器、迁移、CI/CD、监控；能说明线上边界和回滚 |
| Latency / cost | 平台与评测岗高频 | P50/P95、tokens、原生费用、unknown usage、预算预留与版本对比 |
| Human feedback | 评测和产品化加分 | 真正独立的人类标签/裁决或真实用户反馈；模型标签必须标成 model judge，不能冒充人工 |
| Multi-agent | 条件性 | 只有任务确实需要角色/并发/隔离时才有价值；必须量化相对单 Agent 的收益与新增成本 |

### 3. 一手工程资料对“高含金量”的进一步约束

- Anthropic 的 [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
  发布于 2026-01-09。它区分 task、trial、grader、transcript/trace、outcome、eval harness 和 agent
  harness；强调组合代码、模型和人工 grader，多次 trial、检查 transcript，并将自动 eval、生产监控、
  A/B、用户反馈和人工评审视为不同证据层。特别重要的是：**Agent 自己说“完成”不等于环境结果真的
  完成**。
- Anthropic 的 [Building Effective AI Agents](https://www.anthropic.com/engineering/building-effective-agents)
  建议先用简单方案和完整评测，只有简单方案不足时才增加多步 Agent 复杂度。因此，没有业务/消融证明的
  Multi-Agent、Reflection 或长期 Memory 不应被当成简历升级路径。
- OpenTelemetry 的 [Inside the LLM Call: GenAI Observability with OpenTelemetry](https://opentelemetry.io/blog/2026/genai-observability/)
  发布于 2026-05-14，展示 `invoke_agent -> chat -> execute_tool` span、模型身份、input/output token、
  finish reason 和 latency 指标；并明确默认不采集 prompt 和工具参数内容，因为其可能敏感。
- OpenTelemetry 的 [GenAI semantic attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
  当前仍含 development/moved 字段，采用时要固定依赖/语义版本，不能把实验性 convention 当稳定协议。
- MCP [2025-06-18 Specification](https://modelcontextprotocol.io/specification/2025-06-18/index) 与
  [Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) 规定工具有 input/output
  schema，并强调用户控制、数据隐私和工具安全；tool annotation 对不受信 server 只是提示，不是授权。
  [Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) 同时把 stdio 和
  Streamable HTTP 定义为标准传输，且建议客户端尽可能支持 stdio。因此本项目采用 stdio 不是“版本落后”，
  只是尚缺现成客户端互操作证据。

### 4. 当前项目文件与证据

#### Files found

- `README.md`：公开入口、系统范围、快速开始、质量门和简历入口。
- `docs/portfolio/agent-workbench.md`：Workbench 架构、安全边界、真实 loopback fixture capture、面试讲解和诚实限制。
- `backend/app/application/services/agent_tools.py`：单一强类型 Tool Registry、双向 schema/size/timeout 校验和四个只读工具。
- `backend/app/application/services/agent_workbench_graph.py`：LangGraph 有界执行循环、budget、cache、typed failure 和 trace。
- `backend/app/agent_mcp_main.py`：同一 registry 的 MCP v2 stdio 导出和 read-only annotations。
- `backend/app/application/services/execution_governance.py`：Capability Gateway、权限/范围检查、预算预留与 exactly-once reconciliation。
- `backend/app/infrastructure/official_account_reviewer_governance.py`：Writer/Reviewer 角色隔离、子 allocation、冻结预算和修复链路。
- `backend/evals/agent_workbench/canonical-report.md`：42 条 provider-free contract baseline。
- `backend/evals/brand_retrieval/canonical-report.md`：36 条确定性品牌检索策略比较。
- `backend/evals/ip_asset_retrieval_grounded/canonical-seed-v2-report.md`：124 query / 5084 judgment 的 AI-authored Seed，明确非 Human Gold。
- `backend/evals/official_account_reviewer/canonical-report.md`：48 条 Reviewer contract cases，明确零 live call。
- `backend/evals/image_quality_panel/README.md`：单模型 VLM 评测协议、AB/BA、repeat、holdout、failure/cost 约束。
- `.trellis/tasks/archive/2026-09/09-02-image-vlm-human-calibration/research/glm-5v-turbo-live-evidence-2026-09-03.md`：120 次 GLM-5V-Turbo 真实图片评测证据。
- `docs/portfolio/resume/resume-public.tex`：当前公开简历表述。
- `.trellis/spec/backend/agent-workbench.md`、`execution-governance.md`、`brand-knowledge-rag.md`、
  `official-account-reviewer.md`、`image-quality-evaluation.md`：相关可执行规范。

#### Code patterns

1. **Tool contract 单一来源，而不是三套胶水代码**

   - `ToolDefinition` 固定参数/结果模型、5 秒 timeout、参数/结果字节上限，并强制 closed-world/read-only：
     `backend/app/application/services/agent_tools.py:60-83`。
   - `TypedToolRegistry` 生成 canonical schema/hash 与严格 Function Calling schema：
     `backend/app/application/services/agent_tools.py:103-161`。
   - 调用边界先校验参数、再 timeout handler、再校验结果类型/大小，并只抛稳定错误：
     `backend/app/application/services/agent_tools.py:186-218`。
   - 四个工具分别覆盖 governed event、brand RAG、evidence retrieval 和 deterministic copy validation：
     `backend/app/application/services/agent_tools.py:401-447`。
   - MCP server 直接从同一 registry 建 tool，并保留 canonical input/output schema：
     `backend/app/agent_mcp_main.py:29-69,101-150`。

   **岗位判断：强。** 这直接匹配 Function Calling、能力注册、MCP 和 Tool 治理岗位，而且“防 schema
   漂移”的工程价值比工具数量更亮眼。

2. **有界 Agent loop 与安全 failure，不是无限 ReAct**

   - `AgentRunLimits` 限制 4 次模型决策、4 次工具调用、15/30 秒 timeout 以及各级 byte budget：
     `backend/app/domain/agent_workbench.py:58-88`。
   - Graph 在模型决策前检查 deadline/turn budget，在一次返回工具过多或重复 call ID 时 fail closed：
     `backend/app/application/services/agent_workbench_graph.py:178-262`。
   - 工具执行有 run-scoped canonical cache、typed timeout/error 和 safe result trace：
     `backend/app/application/services/agent_workbench_graph.py:264-391`。
   - 模型和工具 token/latency 被投影为显式 metrics：
     `backend/app/domain/agent_workbench.py:149-216`。

   **岗位判断：强。** 它可回答“Agent 卡死、乱调工具、重复调用、工具超时、输出过大怎么办”，但尚未
   给出 live model 在这些分支上的统计成功率。

3. **平台级执行治理是当前最容易被低估的亮点**

   - Capability Gateway 在 handler 前验证 active allocation、role、task/artifact scope、access class、
     argument size 和 budget：`backend/app/application/services/execution_governance.py:205-258`。
   - 调用前先 durable reserve，再写 request event；timeout、cancel、exception 和正常结果均对 reservation
     做 reconciliation：`backend/app/application/services/execution_governance.py:259-377`。
   - 返回 tokens/result/artifact 超过预留后不会被当作成功，而是 bounded reconcile 后拒绝：
     `backend/app/application/services/execution_governance.py:379-456`。
   - Reviewer 将生成 Worker、Reviewer、Repair Worker、Reviewer R2 做角色/能力隔离，并冻结每个 child
     的 model turn、token、tool、artifact 和 timeout 上限：
     `backend/app/infrastructure/official_account_reviewer_governance.py:90-198,951-1029`。
   - 规范定义五张 PostgreSQL governance 表、causal event、artifact lineage、并发预算预留和未知 token
     语义：`.trellis/spec/backend/execution-governance.md:95-184`。

   **岗位判断：很强，建议作为第一亮点。** 这比只写“LangGraph 多 Agent 编排”更接近 AI 平台后端的
   权限、配额、调用治理、追踪和恢复问题。不要把支持 child allocation 的基础设施泛化成任意自治
   Multi-Agent；应具体说 Writer/Reviewer 分权链和 deterministic weekly DAG 共用治理内核。

4. **Grounding / RAG 有清晰的数据边界**

   - Workbench 明确品牌 chunk 永远 `evidence_eligible=false`，外部事实只接受同次运行返回的合格证据：
     `docs/portfolio/agent-workbench.md:49-69`，实现见
     `backend/app/application/services/agent_tools.py:300-368`。
   - 品牌检索 fixture 比较给出 Recall@5 95%、MRR@5 100%、nDCG@5 92.86%、brand-as-fact 违规 0：
     `backend/evals/brand_retrieval/canonical-report.md:1-20`。
   - 报告已诚实限定为 sanitized fixture RRF/diversity policy，不是 live embedding 或线上效果：同文件
     `:1-4`。

   **岗位判断：中强至强。** 架构与评价指标完整；主要不足不是再换向量库，而是缺公开、可复算的真实
   embedding run 和人工/独立相关性判断。

5. **评测工程已经形成显著差异化，图片评测是最佳面试案例**

   - Workbench 42/42 证明 deterministic policy 的 contract/grounding/safety，不冒充 live LLM accuracy：
     `backend/evals/agent_workbench/canonical-report.md:1-27`。
   - GLM-5V-Turbo 图片轨道冻结 48 对、6 个独立 source family、36 objective + 12 subjective、
     family-disjoint calibration/holdout；AB/BA 加固定 repeat 共 120 次 one-shot：
     `backend/evals/image_quality_panel/README.md:1-28`。
   - 真实运行保留 119 completed + 1 provider rejection、未知费用而非写零、P50/P95 latency、token、原生
     CNY cost 和无 retry 完整分母：
     `.trellis/tasks/archive/2026-09/09-02-image-vlm-human-calibration/research/glm-5v-turbo-live-evidence-2026-09-03.md:32-42`。
   - Holdout pair accuracy 83.33%，但 OCR/visible-text 0%，critical-flag FN 100%；因此结论是保留确定性
     OCR 门禁，而不是用总分掩盖失败：同文件 `:44-67,78-85`。
   - Subjective 只报告位置/重复稳定性，明确不是 accuracy、consensus 或 human agreement：同文件
     `:69-76`。

   **岗位判断：很强。** 对 Agent Evaluation 岗而言，最值钱的是实验设计和失败归因：冻结请求、holdout、
   顺序互换、重复性、能力门、无重试、费用/失败分母、bad case 以及非激活结论。简历不要只写 80.56%；
   写“识别出 OCR 0/6 失效并据此保留确定性门禁”更能体现工程判断。

6. **可展示性已经从旧审计的弱项变成中强，但公开工程卫生仍有缺口**

   - GitHub [EDLlyc/edu-ai-lead-agent](https://github.com/EDLlyc/edu-ai-lead-agent) 当前为 Public，公开树已含
     `backend/`、`frontend/`、`docs/` 和 Workbench case study；旧评审中“GitHub 看不到 Workbench”已失效。
   - README 首屏能看到 evidence、RAG、多模态、Agent、可靠性六项价值：`README.md:20-37`；有
     Workbench 启动命令和简历入口：`README.md:142-154,319-353`。
   - Workbench 有三条真实 loopback fixture capture、截图、响应、网络记录、manifest/hash 和复验命令：
     `docs/portfolio/agent-workbench.md:74-113`。
   - 当前 working tree 未发现 `.github/workflows/`、`LICENSE*` 或 `NOTICE*`；公开 GitHub 根列表也没有
     `.github` 或 License。Actions 页面可访问不代表已有 CI。

   **岗位判断：中强。** 招聘者能看到代码和证据，但 README 太长，首屏仍称“multi-agent content
   system”，容易让面试官先追问 Agent 间协商/路由/通信，而不是看到真正强的 execution governance。

### 5. 证据-岗位矩阵

| 岗位要求 | 当前证据等级 | 可以诚实声称 | 不能声称 / 主要缺口 |
|---|---:|---|---|
| Python/FastAPI/PostgreSQL 后端 | 强 | 完整领域/应用/基础设施分层、async DB、迁移、worker、API、测试 | 不凭本仓库声称云上大规模流量或 Kubernetes 生产 SLO |
| Tool Calling | 强 | 4 个强类型只读工具、严格参数/结果/size/timeout、stable failure、单 registry | Workbench live model 的工具选择成功率尚无系统数据 |
| MCP | 中强 | 官方 SDK、stdio、structured output、同 registry schema、read-only hints | 尚无现成第三方客户端发现/调用录屏或互操作测试；无 remote auth，但本地 stdio 场景不要求它 |
| RAG / Grounding | 强（架构）/中（真实质量） | 事实与品牌隔离、claim-bound citation、RRF 指标、无答案挑战 | fixture/AI-authored Seed 不等于人工 Gold 或线上 live recall |
| Agent loop | 强（runtime）/中（model intelligence） | LangGraph 有界循环、budget、typed failure、引用验证 | 一次 live Workbench capture 已失败且无 typed evidence，不能报真实 Agent task success |
| Execution governance | 很强 | RBAC capability、task/artifact scope、atomic budget reserve/reconcile、causal trace、artifact lineage | 尚无跨服务 OTel/线上 dashboard 和真实 SLO |
| Agent eval | 很强（方法） | deterministic contract suite + VLM 真实 120-call AB/BA/holdout/repeat 评测 | 缺 live tool-using Agent benchmark；Reviewer live A/B 尚不能用 provider-free报告冒充 live uplift |
| Observability | 中强 | 每次 run 的 model/tool steps、status、latency、tokens、safe arguments、causal governance event | 无 OTel export、跨运行聚合、版本退化图、告警或 trace search |
| Reliability | 强 | budget、timeout、result_unknown、no-retry/retry boundary、fallback、idempotency、crash/lease/reservation 设计 | 缺生产故障率、MTTR、SLO 或 chaos/injection 总结 |
| Guardrails / 安全 | 强 | closed-world read-only Tool、事实边界、PII/secret/path 脱敏、scope/RBAC、无任意 URL/shell | 尚无系统 Prompt Injection/red-team benchmark 与安全覆盖率 |
| Latency / cost | 中强 | 图片 live P50/P95、tokens、known/unknown native cost；运行级 metrics 和原子 budget | 没有按模型/版本/场景的持续 dashboard 或成本回归 gate |
| Human feedback | 弱至中 | 业务链有人工 review 状态；数据报告诚实记录 `human_labels=0` | 没有独立标注 gold、judge-human calibration、用户反馈到 eval set 的闭环 |
| Multi-agent | 中（有受治理多角色链） | Reviewer/Writer 分权、child allocation、共享 budget/governance | 不应声称通用 multi-agent 协商、群体智能或相对单 Agent 的质量提升 |
| CI/CD / 开源协作 | 弱 | 本地 Make 质量门和公开可读证据 | 未发现 GitHub Actions、License、公开 badge、PR/issue/community 证据 |

### 6. 现在最适合放在简历和面试中的亮点

#### 亮点 A：Agent Capability Gateway 与原子预算治理

这是最匹配 AI 平台后端、也最少见于普通实习项目的亮点。建议主语不是“使用 LangGraph”，而是：

> 设计 Agent Capability Gateway，对模型/工具调用执行角色、任务、工件范围和读写权限校验；在调用前
> 原子预留 elapsed/model-turn/token/tool/result/artifact 多维预算，并在成功、超时、取消和未知 usage
> 分支 exactly-once 对账，生成有因果父子关系的安全 Trace。

可在面试中展示：一次允许调用、一次 role forbidden、一次并发 budget oversell 被拒绝，以及数据库中
reservation/event/artifact 的绑定。

#### 亮点 B：Function Calling 与 MCP 的 schema 单一来源

> 用 Pydantic 强类型 registry 统一 Function Calling、MCP v2 stdio 和 eval 的四个业务工具契约，在同一
> 边界校验参数、结果、timeout 和 byte budget，避免多适配器 schema/handler 漂移。

这比“接入 MCP”更具体，能够对应百度平台岗的能力注册/治理。简历中可保留工具数，但不要以“4 个”作为
核心卖点。

#### 亮点 C：可证伪的 GLM-5V 图片评测

> 构建 GLM-5V-Turbo 图片质量评测：按 6 个独立 source family 拆分 calibration/holdout，对 48 对样本
> 执行 AB/BA 和固定重复共 120 次无重试调用，统一记录失败、token、CNY 成本和 P50/P95；holdout pair
> accuracy 83.33%，同时定位 OCR 0/6 的关键失效并保留确定性 OCR 门禁，评测不自动激活生产策略。

这条比当前简历 `docs/portfolio/resume/resume-public.tex:39` 中只写 provider-free 48/48 更强、更接近
Agent Evaluation 职位。必须同时保留限制：6 个独立 source family、0 human/external label、1 次 provider
rejection、subjective 指标只是 self-consistency。

#### 亮点 D：Claim-level grounding 与上下文隔离

> 将外部事实证据与品牌 RAG 物理/语义隔离；模型的每条 external-fact claim 只能引用本次运行成功返回的
> Tier A/B evidence，品牌 chunk 永远不可作为外部事实证据；非法引用在 finalize 阶段 fail closed。

它同时覆盖 RAG、hallucination guardrail 和可解释 Trace，比泛写“实现 RAG”含金量更高。

#### 亮点 E：真实失败也进入评测结果

图片实验把 provider rejection、unknown cost、未完成 pair 和 OCR bad cases 留在分母中；Workbench live
capture 失败后也没有补跑并冒充成功。这个“证据纪律”适合在面试中主动说，它与当前评测岗位要求的负样本
归因、实验复现和技术报告高度一致。

### 7. 最小高收益提升顺序

#### P0 — 求职前优先

1. **补一条真正的 live tool-using Agent eval，而不是再加 Agent。**
   - 冻结 24--40 个 sanitized tasks，至少覆盖正确工具、坏参数修复、未知工具、无证据拒绝、超时和预算耗尽。
   - 使用 objective outcome/tool schema 作为主 gold；同一模型至少重复 2--3 次，报告 Pass@1、task
     success、tool selection/argument validity、citation coverage、refusal、failure taxonomy、P50/P95、token
     和 CNY cost。
   - 保留现有 deterministic 42/42 作为 contract baseline，绝不能合并成一个“accuracy”。
   - 若用 LLM judge，只作为开放文本的次级 grader，并标记模型/版本/rubric；没有人工标签时明确写
     `human_labels=0`，不要写“模拟人工准确率”。

2. **把执行治理做成 60--90 秒核心 Demo。**
   - 当前公开 Demo 重点仍是 Workbench 的 4 个只读工具；新增一个纯 fixture replay 页面/录屏，显示
     allocation → budget reservation → model/tool requested → result/reconcile → artifact/terminal，以及一次
     permission denied。
   - 这会把埋在代码和长 spec 中的最强亮点变成招聘者 1 分钟可见的证据。

3. **补公开 CI 和仓库 License 决策。**
   - CI 只读、无 secret、provider-free，运行 `agent-portfolio-check` 和最小 lint/type/test；不要从 GitHub
     反向部署生产。
   - License 是所有者决策；若不能授权代码复用，也应在 README 明确 source-available / portfolio-only
     边界，而不是默认为无说明。

4. **收紧首页与简历叙事。**
   - README 首屏从“multi-agent content system”收敛成“evidence-grounded, evaluable Agent content
     platform”，把 Capability Gateway、Tool/MCP 单一来源和 VLM bad-case 结论放在首屏。
   - 当前简历图片条目仍只写 provider-free 48/48，应换成真实 GLM-5V 实验及 OCR 失败结论；不要删除
     评测限制。

#### P1 — 能显著拉开平台/评测岗位差距

5. **增加隐私默认关闭内容的 OpenTelemetry export。**
   - 将 run/model/tool/retrieval 映射到固定版本的 GenAI semantic convention，默认仅输出模型、状态、
     duration、token、safe error、tool name 和 opaque IDs，不输出 prompt/arguments/results。
   - 提供本地 OTLP/Aspire 或等价开源 viewer，展示 model 与 tool latency 的 span tree 和版本对比。
   - 这是现有 safe Trace 的标准化出口，不需要另建一套 AgentOps 产品。

6. **补 MCP 客户端互操作证据。**
   - 用一个现成客户端执行 `tools/list` 并调用 2 个 fixture 工具，保存协议版本、schema hash、typed output
     和 safe failure。
   - 当前 local stdio 是合理边界，不必为了简历增加公网 Streamable HTTP/OAuth；除非目标岗位明确要求
     remote MCP gateway。

7. **建立 feedback → bad case → regression 的闭环。**
   - 复用已有不可变人工 review 决定，只导出无正文、无身份的结构化 issue/outcome，人工确认后进入候选
     regression queue。
   - 没有人工标注资源时，先用 environment/output oracle 覆盖客观任务；模型 judge 产生的标签只能叫
     synthetic/model-judged Seed。

#### P2 — 暂不建议为求职堆叠

- 通用 Multi-Agent debate、A2A：除非 live eval 证明单 Agent 的具体瓶颈，否则新增失败面、延迟和成本。
- 长期 Memory：当前内容生产和 fixture research 没有必须跨会话记忆的用户任务；岗位提到 Memory 不等于
  每个项目都必须实现。
- Reflection 无限重试：与现有 hard budget、result-unknown 和无选择偏差实验边界冲突；只能以明确
  failure mode 和额外 call budget 引入。
- SFT/DPO/GRPO/RL：若投算法岗应做独立训练项目和消融，不要在当前应用仓库添加空标签。
- 再换一套 Agent/RAG 框架：不会增加招聘证据；现有自研 contract/governance 反而是优势。

### 8. 目标岗位建议

#### 最优投递标签

- Python Agent 开发实习生
- LLM 应用工程实习生
- AI 平台 / Agent Runtime 后端实习生
- Agent Evaluation / AI 质量工程实习生
- RAG / Knowledge Engineering 实习生

#### 需要谨慎的标签

- “Multi-Agent 算法”：项目有受治理的多角色执行，但未证明群体协作算法收益。
- “LLM-as-a-judge 人工模拟”：模型 judge 不是人工；当前图片 subjective 只有 single-model
  self-consistency。
- “生产级 AgentOps”：有治理账本和单次 safe trace，但尚无 OTel、跨运行 dashboard 或线上 SLO。
- “真实模型 Agent accuracy”：图片 VLM 有真实证据，Workbench tool-using Agent 当前没有成体系 live
  accuracy。

#### 不匹配岗位

[百度 Agentic RL / 大模型平台策略推理优化实习生 J100476](https://talent.baidu.com/jobs/detail/INTERN/52415af4-405a-4f07-8392-d4b63e76df8c)
明确要求 PPO/GRPO、SFT→RM→RL 或 vLLM/SGLang/MTP/投机推理。除非另有训练代码、数据、算力、实验和
论文证据，否则不能用本项目补齐。

### 9. 可直接用于面试的项目定位

推荐一句话：

> 我做的不是一个靠 Prompt 串起来的 Demo，而是一套有真实内容业务输入的可评测 Agent 平台：同一个
> typed registry 服务 Function Calling、MCP 和 eval；Capability Gateway 对角色、工件范围和多维预算
> 做调用前治理；所有模型/工具行为进入脱敏 causal trace。图片模型用 120 次 AB/BA + holdout 实验发现
> OCR 关键失效，所以生产仍保留确定性门禁。

这个表述可以在代码、报告和公开 GitHub 中逐项核验，并主动说明局限，可信度高于框架名堆叠。

## Related specs

- `.trellis/spec/backend/agent-workbench.md`
- `.trellis/spec/backend/agent-pipeline.md`
- `.trellis/spec/backend/execution-governance.md`
- `.trellis/spec/backend/brand-knowledge-rag.md`
- `.trellis/spec/backend/official-account-reviewer.md`
- `.trellis/spec/backend/image-quality-evaluation.md`
- `.trellis/spec/backend/logging-guidelines.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`

## Caveats / Not Found

- 本研究不运行测试、模型、部署或 provider，不验证私有运行环境；代码证据来自当前 working tree 和已
  冻结报告。
- 当前公开 GitHub 已包含 Workbench，旧文件 `research/project-improvement-audit.md` 中“公开树看不到
  Workbench”的结论已过期。
- 未发现 `.github/workflows/`、`LICENSE*`、`NOTICE*`；未据 GitHub Actions 页面空白内容推断运行历史，
  只记录仓库树中未找到 workflow 文件。
- GLM-5V 图片报告的 48 对样本只来自 6 个独立 source family；36 个 objective case 使用 recipe gold，
  12 个 subjective case 无外部标签；不能泛化为真实世界整体图片质量或人工一致率。
- Workbench 42/42、Reviewer 48/48、品牌检索 36/36 都有明确 provider-free/fixture 限定；不能与真实
  live model 指标混写。
- IP Asset Seed V2 的 5084 judgments 由同一 AI author/reviewer 产生，不构成独立 human gold 或 agreement。
- 当前未找到成功的系统化 live tool-using Workbench 报告；公开文档只保留一次失败关闭的单次尝试，因而
  不能据此声称 live tool selection/task success。
- 人工审稿状态是业务审批证据，不自动等价于用于评测的独立标注数据；需要单独定义采样、盲化、标注和
  裁决协议。
- 雇主岗位状态具有时效性：百度详情页可能要求登录，Ashby 页面依赖 JavaScript，岗位也可能在本报告后
  关闭。投递前必须重新打开官方页面核实地点、学历、毕业时间、实习周期和签证要求。
