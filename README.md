# Edu AI Lead Agent

面向科学教育与 AI 教育内容运营的多 Agent 系统：从权威来源采集、事实治理和选题排序，到品牌文案、配图、审核、素材包与内部交付，形成可追溯、可评测、可恢复的完整内容生产链。

[项目亮点](#项目亮点) · [真实内容产出](#真实内容产出) · [系统流程](#系统流程) · [快速开始](#快速开始) · [文档导航](#文档导航)

## 项目亮点

- **证据驱动**：保存来源快照、事实标签、事件版本与证据绑定，文案可以回溯到具体来源。
- **混合选题**：确定性阈值与硬否决保证底线，LLM 只在合格候选中做受控重排，失败时稳定回退。
- **品牌 RAG**：用 PostgreSQL/pgvector 检索数字 IP、品牌定位和视觉资产，品牌内容不冒充新闻事实。
- **多模态生产**：生成家长友好文案、品牌配图和素材包，并执行文案、图片、相似度与可选 OCR 检查。
- **Agent 工程化**：LangGraph 有界执行、强类型 Tool Registry、MCP stdio、引用校验、安全 Trace 和离线评测。
- **可靠交付**：幂等任务、checkpoint、重试/回退、备份与内部企业微信交付；不提供公开平台无人审核发布。

## 真实内容产出

以下内容来自历史上已通过校验的本地素材包，并非为 README 重新调用模型生成。

<p>
  <a href="./docs/portfolio/content-showcase.md#science-learning-by-doing">
    <img src="./docs/portfolio/assets/content-showcase/science-learning-by-doing.png" alt="科学教育做中学主题配图" width="47%">
  </a>
  <a href="./docs/portfolio/content-showcase.md#brain-computer-interface-ai">
    <img src="./docs/portfolio/assets/content-showcase/brain-computer-interface-ai.png" alt="脑机接口与人工智能主题配图" width="47%">
  </a>
</p>

[科学教育“做中学”：完整文案与验证信息](./docs/portfolio/content-showcase.md#science-learning-by-doing) · [脑机接口与人工智能：完整文案与验证信息](./docs/portfolio/content-showcase.md#brain-computer-interface-ai)

## 系统流程

```text
权威来源
   ↓
候选与不可变快照
   ↓
事实治理 · 去重 · 事件组织
   ↓
规则过滤 · 评分阈值 · LLM 受控重排
   ↓
证据 + 品牌 RAG → 文案 → 配图 → 质量检查
   ↓
素材包 · 人工审核 · 内部交付
```

生产业务和求职 Workbench 共用强类型领域能力，但 Workbench 不注册到生产 API、Dockerfile 或 Compose，也不能写业务数据或触发交付。

## 快速开始

### 环境

- Conda
- Docker 29+ / Docker Compose 2.40+
- Node.js 20.19+ / npm
- Make、Bash、curl

### 初始化

```bash
conda env create -f environment.yml
conda activate edu-ai
make env-init setup infra-up migrate seed-sources doctor
```

### 启动本地业务栈

```bash
make stack-up
```

默认地址：API `127.0.0.1:8000`、PostgreSQL `127.0.0.1:5432`、MinIO `127.0.0.1:9000`、Vite `127.0.0.1:5173`。

### 运行 Agent Workbench

```bash
make agent-portfolio-check

# 终端 1
make agent-workbench-dev

# 终端 2
make agent-workbench-ui
```

Workbench 只绑定 `127.0.0.1:8010`，前端仅在 Vite development 且显式启用本地 flag 时出现。

### 常用质量门

```bash
make backend-check        # Ruff + mypy + pytest
make frontend-check       # Prettier + ESLint + TypeScript + Vitest + build
make agent-portfolio-check
make api-contract-check
make doctor
make check
```

## 文档导航

| 主题                                 | 文档                                                                           |
| ------------------------------------ | ------------------------------------------------------------------------------ |
| Agent Workbench 架构、工具与面试讲解 | [Agent Workbench case study](./docs/portfolio/agent-workbench.md)              |
| 两组真实文案与对应配图               | [真实内容产出](./docs/portfolio/content-showcase.md)                           |
| Agent 确定性评测                     | [Eval README](./backend/evals/agent_workbench/README.md)                       |
| 生产发布、回退与 Digest 契约         | [固定 Digest 发布运行手册](./docs/operations/digest-release-runbook.md)        |
| 服务器迁移与视觉能力启用             | [生产服务器迁移手册](./docs/operations/production-server-migration-runbook.md) |
| 后端工程规范                         | [Backend specs](./.trellis/spec/backend/index.md)                              |
| 前端工程规范                         | [Frontend specs](./.trellis/spec/frontend/index.md)                            |
| 项目技术报告                         | [技术报告.pdf](./技术报告.pdf)                                                 |

## 安全边界

- 来源访问必须通过 HTTPS 白名单、公共 DNS/IP、重定向、大小和内容类型检查。
- Agent 与日志不暴露密钥、完整 prompt、原始模型响应、私有对象路径或内部品牌全文。
- Workbench 默认离线、只读且仅绑定 loopback；生产系统不暴露任意 URL、shell 或自动公开发布工具。
- `.env`、API Key、数据库密码、签名 URL 和社媒凭据不得进入仓库。

GitHub 仓库是 Codeup 权威源的单向作品集备份，不反向覆盖 Codeup，也不触发生产部署。
