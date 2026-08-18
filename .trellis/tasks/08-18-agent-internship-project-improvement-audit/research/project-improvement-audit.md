# Agent 实习项目提升评审

## 结论

这个项目已经超过普通实习作品的“功能及格线”。继续增加 Agent 数量、Memory、A2A 或更多工具，
对求职帮助很有限。当前最大问题是：核心能力留在本地仓库和长文档里，招聘者无法在几分钟内验证；
同时现有评测主要证明契约正确，尚未证明真实模型在工具选择、参数生成、多轮执行和失败恢复上的质量。

建议主投 **Agent 应用开发 / AI 平台后端**，副投 **Agent Evaluation / AI 全栈**。不建议把当前项目
包装成 Agentic RL 或大模型训练项目。

## 现有亮点与岗位映射

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

## P0：投简历前优先完成

### 1. 完成公开求职作品集

- **为什么最重要**：目前招聘者无法从公开 GitHub 看到 Workbench；再好的本地实现也无法转化为面试。
- **已有基础**：case study、架构图、截图、42/42 报告、README 入口均已存在；
  `08-17-agent-workbench-public-portfolio` 已完成需求规划。
- **最小交付物**：公开可审计代码树、README 首屏、静态 replay 页面、60--90 秒演示、一条无密钥
  fixture-only 命令、只读 CI、清晰 License/NOTICE。
- **成本**：约 1--2 天；不需要改生产 Agent。
- **验收重点**：30 秒看懂价值，3 分钟看到一次真实多工具 Trace 和一个安全拒绝，命令可复现。

### 2. 增加 opt-in 真实模型评测轨道

- **为什么重要**：42/42 是固定策略 contract baseline，面试官会追问“换成真实模型后成功率如何”。
- **已有基础**：OpenAI-compatible adapter、严格 Tool schema、完整 trace、eval case schema 和安全指标。
- **最小交付物**：同一脱敏数据集跑 2--3 次真实模型；记录工具选择正确率、参数合法率、任务成功率、
  引用覆盖、拒绝准确率、P50/P95 latency、token/cost、失败类型；canonical deterministic 报告保持独立。
- **成本**：约 1 天代码 + 少量受控模型费用。
- **验收重点**：展示 bad case 和修复前后对比，不只展示平均分；禁止 LLM judge 成为唯一真值。

### 3. 收敛简历叙事和三分钟 Demo

- **为什么重要**：当前 README 很完整，但信息密度高，容易让核心 Agent 能力淹没在业务/发布细节里。
- **最小交付物**：一个项目标题、三条简历 bullet、一个架构图、一个成功 Trace、一个失败恢复案例、
  一张指标表；面试讲解按“问题—设计—边界—指标—取舍”展开。
- **成本**：半天。
- **建议标题**：`面向内容研究的可评测 Agent 工作台（LangGraph + MCP + RAG + Eval）`。

## P1：P0 完成后增强

### 4. 增加轻量 AgentOps 运行对比

- 不急着建设完整持久化平台。先把脱敏 run artifact 导出为 JSONL，生成模型/版本维度的成功率、
  工具错误、fallback、token、latency 和失败 taxonomy 汇总。
- 可选接入 OpenTelemetry，仅记录受控 span attribute；不要存 raw prompt、provider body 或业务正文。
- 这能直接回答“如何发现 Agent 退化”和“如何做模型版本回归”。
- **成本**：1--2 天。

### 5. 做一个真正的 MCP 客户端演示

- MCP server 已经存在，没必要新增工具。补一段受控的客户端连接示例或录屏，证明 Cursor、Claude
  Desktop 或其他 MCP client 能发现 schema、调用两个工具并收到 typed result。
- 演示必须使用 fixture/read-only 数据；不要把 MCP 暴露成公网服务。
- **成本**：半天。

### 6. 把数字 IP 库变成可量化案例

- 当前 5/5 只证明 contract conformance。增加 20--30 条脱敏 query 的小型 gold set，衡量 Recall@K、
  MRR、标签覆盖、禁用规则命中和 brand-as-fact 违规率。
- 将本地 feedback ledger 导出成脱敏分析报告，展示“哪些品牌资料被采用/拒绝以及原因”；暂不写回生产。
- **成本**：1--2 天。

### 7. 补一份系统设计取舍文档

- 用一页说明为什么 Tool registry 单一来源、为什么 MCP 只走 stdio、为什么品牌不能当事实、为什么
  loop 有硬预算、为什么 Workbench 不进生产。
- 这比再加一个框架更能体现工程判断和安全意识。
- **成本**：半天；现有文档可直接提炼。

## P2：明确延期

- **长期 Memory**：只有出现跨会话用户任务时再做；当前 fixture 研究任务不需要。
- **Multi-Agent / A2A**：现有任务不需要角色协商，加入后只会增加 latency、失败面和评测成本。
- **Reflection / 自我修正循环**：先用真实模型 bad case 证明单 loop 的具体瓶颈，再决定是否增加。
- **模型微调、SFT、DPO、GRPO**：这是算法岗的另一条作品线，需要数据、训练和消融证据，不应贴标签。
- **公网 Agent 服务**：当前 loopback-only 是合理安全边界；公开展示应使用静态 replay，不是直接暴露 API。
- **更多工具**：现有四个工具已足够展示检索、事件查看、品牌 RAG 和验证；工具数量不是竞争力。

## 推荐执行顺序

1. 公开作品集与一键 Demo。
2. 真实模型 eval + bad-case 报告。
3. 简历/面试材料收敛。
4. AgentOps 汇总和 MCP 客户端演示。
5. 数字 IP 真实检索评测。

前 3 项完成后就应开始投递，不需要等待 P1/P2。对于 Agent 应用工程岗，项目已经有足够深度；后续
工作的目标是提高可信度和可见性，而不是继续扩大代码量。

## 当前招聘证据摘要

- 百度 AI 开放平台研发实习岗把 Agent Tool、Skill、MCP、Function Calling、上下文管理、调用治理、
  限流和可观测性列为职责或加分项。
- 百度 Agent 工程岗把 RAG、Memory、Skill、MCP、框架应用和性能评估列为核心经验。
- 百度 Agent 评估岗强调自动化评测、消融、行为日志、负样本归因和 benchmark。
- Grab Agents Platform 实习岗强调 golden datasets、multi-turn/multi-agent eval、trace rendering、
  failure modes 和 OpenTelemetry/LangSmith 类观测工具。
- XPENG Agentic Infrastructure 实习岗强调 MCP connector、evaluation、CI/CD、observability、
  structured validation 和 dashboard。

这些要求说明：本项目的技术方向正确，当前最值得投资的是评测和作品集证据。

## 参考岗位

- [百度 AI 开放平台研发工程师实习生](https://talent.baidu.com/jobs/detail/INTERN/ef30e579-2d3d-4539-ad90-884521b815c9)
- [百度 Agent 工程师](https://talent.baidu.com/jobs/detail/INTERN/3ddcb5a1-63d7-4596-b7cf-d636dad39f60)
- [百度 Agent 评估工程师实习生](https://talent.baidu.com/jobs/detail/INTERN/a0bbc449-854f-421c-bfaf-1a5be906f86e)
- [Grab AI Engineer Intern — Agents Platform](https://jobs.smartrecruiters.com/Grab/744000126568308-intern-ai-engineer)
- [XPENG Agentic Infrastructure Engineer Intern](https://job-boards.greenhouse.io/xpengmotors/jobs/8559314002)
