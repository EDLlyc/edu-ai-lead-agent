# Agent Workbench 真实运行素材包 — Design

## Evidence flow

```text
real Uvicorn :8010
    -> POST /api/v1/agent-workbench/runs
    -> real AgentWorkbenchService / bounded runner / typed registry
    -> sanitized fixture reader
    -> deterministic policy (default) or explicitly authorized Zhipu mode
    -> typed HTTP response

real Vite :5173
    -> real generated-contract client
    -> AgentWorkbenchView
    -> Playwright element screenshots

capture orchestrator
    -> response.json
    -> summary.md
    -> screenshot.png
    -> manifest.json + SHA-256
```

## Case contract

| Case | Query intent | Expected path | Evidence value |
| --- | --- | --- | --- |
| `multi-tool-research` | 核验证据、事件和品牌表达 | search -> event -> brand -> cited answer | 展示规划、工具和 grounding |
| `copy-validation` | 校验受控文案 | validate_copy -> result | 展示业务规则复用而非 LLM 自评 |
| `safety-refusal` | 请求发布/发送/执行 | final refusal, zero tools | 展示 closed-world safety |

Case query、scenario 和预期 terminal class 由一个 checked manifest 统一拥有；API 调用、浏览器输入和
文档表格都从该 manifest 派生，避免三套手写案例漂移。

## Capture boundary

- 新 capture script 只连接 `127.0.0.1:8010/5173`，拒绝其他 origin/host。
- deterministic run 强制 `AGENT_WORKBENCH_ENABLED=true`、model mode deterministic、fixture data、
  live false；即使 `.env` 存在 live 配置也不能继承为实际模式。
- Playwright 不能 route/fulfill API；网络日志必须证明 POST 发送到真实 loopback API。
- 每个 case 先保存 typed API response，再通过 UI 重跑同一 query；两侧比较 terminal class、工具名、
  citation counts 和安全字段。动态 run ID/latency 允许不同，但语义必须一致。
- Evidence 只保留 response schema 的安全投影。请求 header、provider body、环境变量和 stdout secret
  不进入 artifact。

## Artifact layout

```text
docs/portfolio/runs/agent-workbench/<capture-id>/
  manifest.json
  overview.md
  multi-tool-research.response.json
  multi-tool-research.png
  copy-validation.response.json
  copy-validation.png
  safety-refusal.response.json
  safety-refusal.png

docs/portfolio/assets/
  agent-workbench-real-runs-overview.png
```

`capture-id` 使用 commit short SHA 加 UTC 时间；case artifacts 使用固定名字。Manifest 记录 full commit、
capture time、mode、case IDs、relative paths、SHA-256、terminal/tool/citation/step counts 和生成命令。

## Screenshot design

- 保留 UI 原始视觉，不制作无法复现的营销 mockup。
- 单案例截图聚焦问题、执行 rail、答案/校验/拒绝、citation 与 metrics；必要时做 element screenshot，
  不截浏览器地址栏或桌面隐私。
- 总览图只把三张真实截图和 checked manifest 指标排版到同一画布；不得修改数值或拼接不存在的状态。
- 图片 metadata 清理后再提交，并记录最终 hash。

## Live-model option

若用户明确授权一条智谱案例：

- 只运行 `multi-tool-research`，fixture data 不变；model mode 为 openai-compatible/Zhipu。
- 一个 Agent run 最多四次 model decision；禁止自动重试整条 case。
- 另存 `live-zhipu` artifact，明确 provider/model/time/non-deterministic，不覆盖 deterministic evidence。
- 失败也保留 typed safe failure 和截图，但不保存 provider 原文，不二次调用。

## Compatibility

- 不改 production app、OpenAPI、Compose、Dockerfile 或数据库。
- 若为可复现捕获新增 launcher/helper，必须只位于 portfolio/dev tooling，并有 cleanup/host allowlist tests。
- 现有静态 fixture screenshot 继续保留并改标签，不删除其 deterministic design-baseline 用途。

