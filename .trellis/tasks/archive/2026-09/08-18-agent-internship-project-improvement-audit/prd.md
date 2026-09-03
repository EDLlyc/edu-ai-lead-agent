# Agent 实习项目提升评审

## Goal

面向 Agent 应用开发、LLM 应用工程、AI 平台后端和 Agent 评测方向的实习岗位，审查当前
`edu-ai-lead-agent` 项目已有能力与招聘证据之间的差距，给出按求职价值、实现成本和优先级排序的
提升清单。目标不是继续堆功能，而是让招聘者更快地看到、复现并相信候选人的 Agent 工程能力。

## Background and confirmed facts (refreshed 2026-09-03)

- 项目已经具备完整的业务流水线、治理证据、品牌 RAG、LLM 选题重排、图片生成和企业微信交付，
  不是只有 Prompt 的玩具 Demo。
- 本地 Agent Research Workbench 已具备四个强类型只读工具、共享 registry、bounded Agent loop、
  MCP v2 stdio、claim-level 引用、脱敏 Trace、独立回环 API、React UI 和 PostgreSQL 只读适配。
- Workbench 的 42/42 离线评测只证明固定策略的契约、安全和 grounding，不证明 live model 的工具选择、
  多轮规划或真实质量；当前文档已诚实标注此限制。
- 数字 IP 库已有 active-ready 只读投影、安全视觉目录、品牌召回解释、本地反馈 ledger 和 5/5
  provider-free contract eval；仍没有真实 embedding/召回质量数据或跨会话反馈闭环。
- LLM 选题重排已经具备 fake/Zhipu adapter、严格输出契约、durable audit 和 8/8 provider-free eval；
  近期单次智谱兼容性验证成功，但这不等于系统化模型评测。
- Workbench、case study、真实 loopback fixture 截图、hash manifest、公开简历与复验命令已经进入
  GitHub；旧评审中的“公开树看不到 Workbench”结论已经失效。但仓库仍无 GitHub Actions、LICENSE、
  description/topics/homepage、静态 replay 或面向求职者的一条命令式演示入口。
- 执行治理与固定 Writer--Reviewer 已经落地：角色/任务/Artifact 最小权限、多维预算预留与 exactly-once
  对账、因果 Trace、observe/enforce、最多一次 code-directed repair 和恢复语义均有代码与测试证据；
  Reviewer live A/B 仍未形成可用质量结论，不能声称 uplift 或人工一致率。
- 图片评测已经有唯一智谱 `glm-5v-turbo` 的 120-call live evidence：holdout objective pair accuracy
  83.33%，同时暴露 OCR/visible-text 0/6 的关键失效。该结果只有 6 个独立 source families、0 人工/
  外部标签且 non-activating，证明评测与失败归因能力，不证明广义视觉质量或 Agent 规划能力。
- 当前代码更匹配 Agent 应用工程、AI 平台工程和 Agent 评测岗位；若改投 Agentic RL、SFT/DPO/GRPO
  等算法研究岗，需要独立的训练/研究项目，不能靠给本项目再加几个框架名补齐。

## Requirements

### R1 — 以岗位证据而非功能数量评估

- 将现有能力映射到当前岗位常见要求：Python/后端工程、RAG、Function Calling、MCP、Agent loop、
  评测、Trace/可观测性、可靠性、安全边界、前后端展示和业务落地。
- 对每个缺口明确已有基础、招聘价值、最小交付物、预估成本和不做的代价。
- 不把 deterministic fixture 指标包装成 live LLM accuracy，不把生产业务流水线包装成自由自治 Agent。

### R2 — 给出可执行优先级

- P0 只包含最直接影响投递和面试转化的工作；P1 是能拉开工程能力差距的增强；P2 明确延期。
- 优先复用已经完成的 Workbench、MCP、数字 IP、选题重排和评测基础，避免复制实现。
- 明确哪些热门方向当前不值得补，包括无真实需求的 Multi-Agent、A2A、长期记忆、Reflection 和微调。

### R3 — 区分目标岗位

- 主定位为 Agent 应用开发 / AI 平台后端，副定位为 Agent Evaluation / AI 全栈。
- 对算法研究岗的缺口单独说明，避免用当前项目误投需要 PyTorch 训练、SFT/RL 或论文复现的岗位。

## Acceptance Criteria

- [x] 评审引用当前仓库中的 Workbench、MCP、数字 IP、选题重排、评测和作品集真实证据。
- [x] 评审对照当前官方招聘信息，而不是只按框架热度给建议。
- [x] 输出 P0/P1/P2 清单，每项包含价值、最小交付物和成本。
- [x] 明确当前最强岗位定位与不匹配的岗位类型。
- [x] 明确下一步不应继续扩展哪些功能。
- [x] 不修改产品代码、不运行 provider、不部署或推送。

## Out of Scope

- 本任务不实现公开作品集、live eval、AgentOps、数字 IP 评测或简历改写。
- 不修改生产 API、Compose、调度、数据库、MCP 工具面或业务发送能力。
- 不执行付费模型调用、SSH、部署、GitHub/Codeup 推送或仓库公开化。
- 不为算法研究岗临时加入没有训练证据的 SFT、RL、Multi-Agent 或 Memory 标签。

## Deliverable

- `research/project-improvement-audit.md`：岗位匹配、当前亮点、差距和分级提升路线。
