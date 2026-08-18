# Agent Workbench 真实运行素材包

## Goal

把已经完成的 Agent Research Workbench 通过真实本地服务跑起来，整理一组招聘者可以直接理解、
复核和用于简历/面试展示的运行结果与素材截图。重点是展示真实 API、真实 UI、真实工具轨迹、引用和
安全拒绝，不在本轮扩建完整 Pages、CI、License 或 AgentOps 平台。

## Background and confirmed facts

- Workbench 已具备真实独立 ASGI app、回环 CORS、React UI、四个只读工具、bounded loop、Trace、
  claim-level citation 和 deterministic/live 两种 model mode。
- 当前 `docs/portfolio/assets/agent-workbench-trace.png` 由静态 fixture entry 渲染，未经过真实 API；
  它适合作为稳定设计截图，但不能单独声称是实际运行证据。
- 真实本地 deterministic 模式不需要密钥、生产数据库或外部网络，但会经过真实 Uvicorn、HTTP、
  typed registry、runner、route mapper 和 React UI。
- 真实智谱模式也已接入同一 Workbench，但一次 Agent run 可能包含最多四个模型决策，属于付费外部调用；
  先前审批明确没有授权本任务自动执行付费调用。
- 公开 GitHub 当前仍看不到 Workbench；本轮只准备可公开素材和文档，不执行 push 或 Pages 发布。
- 用户最新选择是先整理少量真实运行结果和素材截图，将此前完整公开 CI、Pages、License、live eval
  平台计划延期。

## Requirements

### R1 — 真实本地运行证据

- 启动仓库现有的 loopback-only Workbench API 和 Vite UI，所有截图必须由浏览器通过真实 HTTP 请求产生。
- 固定记录 commit、运行时间、model mode、脱敏问题、terminal status、工具序列、引用数量、步骤/延迟指标
  和响应安全摘要。
- 不把静态拦截 fixture 截图冒充 API run；旧截图保留，但必须标注为 checked fixture render。

### R2 — 最小案例集

- 至少保留三个互补案例：
  1. 多工具研究：`search_evidence -> get_event -> retrieve_brand_context`；
  2. 受控文案校验：`validate_copy`；
  3. 安全拒绝：发布/发送/执行类请求不调用写工具并返回拒绝。
- 每个案例保留一份脱敏 typed JSON evidence、一份人类可读摘要和一张实际 UI 截图。
- 结果必须说明 deterministic policy 证明的是可复现执行链与安全契约，不是 live LLM intelligence。

### R3 — 招聘素材整理

- 更新 Agent Workbench case study，增加“真实运行证据”章节和三案例对比表。
- 生成一张适合 README/简历附件的总览图，以及按案例拆分的清晰截图；不出现密钥、绝对私有路径、
  内部服务器、真实业务账号、provider 原始响应或生产数据。
- 每张素材有稳定文件名、SHA-256、生成命令和证据 manifest，避免后续无法说明来源。
- 整理三条简历 bullet 和一段三分钟面试讲解，数字只引用 evidence manifest 中的真实值。

### R4 — 可复现捕获

- 捕获流程复用真实 Workbench API/UI，不复制模型、registry、mapper 或 Trace renderer。
- 增加受控 capture command：启动/确认 loopback 服务、执行案例、保存 typed response、浏览器截图、
  校验隐私并清理进程。
- 捕获 deterministic 案例必须完全离线且不需要 provider key。

## Acceptance Criteria

- [ ] 三个案例均经过真实 loopback HTTP API 和真实 React UI，而不是 route interception/mock response。
- [ ] 每个案例具有 JSON、Markdown 摘要、PNG 截图及 manifest hash，且四者身份一致。
- [ ] 多工具案例显示真实工具顺序、引用和预算；文案案例显示 validator 结果；拒绝案例证明零工具写操作。
- [ ] case study 和 README 素材明确区分 deterministic run、checked fixture render 与任何 live-model run。
- [ ] 截图和证据不含 secret、provider body、私有路径、生产地址、企业微信标识或真实业务数据。
- [ ] 生成命令可重复运行，结束后无残留 Uvicorn/Vite/Playwright 进程。
- [ ] production API、Compose、Dockerfile、production OpenAPI 和业务行为无变化。
- [ ] 不执行 GitHub push、Pages deploy 或生产部署。

## Deferred

- GitHub Actions、Pages workflow、MIT/NOTICE、公开仓库同步和完整 public-tree audit。
- 批量 live-model eval、AgentOps 聚合、OpenTelemetry 和数字 IP retrieval eval。
- 60--90 秒视频可在本轮 PNG/manifest 证据稳定后再制作。

## Key Decision

- 用户已明确授权：在三条真实本地 deterministic API/UI 证据之外，额外执行 **一条** 智谱多工具
  live Agent 案例。该案例只使用脱敏 fixture，最多产生四次模型请求，不对整条案例重试；成功或失败
  都保留 typed evidence，且不得保存 provider 原始响应。

## Out of Scope

- 不接触生产数据库、真实业务事件、企业微信或服务器。
- 不新增工具、Memory、Multi-Agent、A2A、Reflection 或写操作。
- 不把运行截图包装成 production deployment 或大规模线上指标。
- 除上述一条已授权智谱多工具案例外，不调用其他付费 provider，不批量评测或重跑失败案例。
