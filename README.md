# Edu AI Lead Agent

面向家长的每日 AI 教育内容素材 Agent。当前已实现第一步“权威源自动采集与证据入库”：每天从批准的权威来源增量采集公开资料，在 PostgreSQL 保存任务状态、来源版本和可追溯证据候选，在 MinIO 保存不可变原始快照。

本阶段不包含 LLM 分类、语义去重、选题评分、RAG、文案/图片生成、前端浏览页面或自动发布。

## 前置条件

- Conda
- Docker 29+ 与 Docker Compose 2.40+
- Node.js 20.19+ 与 npm
- Make、Bash、curl

## 首次安装

```bash
conda env create -f environment.yml
conda activate edu-ai
make env-init
make setup
make infra-up
make migrate
make seed-sources
make doctor
```

如果 `edu-ai` 已存在：

```bash
conda env update -n edu-ai -f environment.yml
conda activate edu-ai
make setup
```

## 本地服务

| 服务 | 默认地址 |
|---|---|
| 权威源采集 API | <http://127.0.0.1:8000> |
| PostgreSQL/pgvector | `127.0.0.1:5432` |
| MinIO API | <http://127.0.0.1:9000> |
| MinIO Console | <http://127.0.0.1:9001> |
| Vite（手动启动） | <http://127.0.0.1:5173> |

分别启动开发进程：

```bash
make acquisition-api
make acquisition-scheduler
make acquisition-worker
npm run dev --prefix frontend
```

也可以构建并启动完整后端进程形状：

```bash
make stack-up
```

API、Scheduler 和 Worker 是独立进程。Scheduler 默认每天 `06:30 Asia/Shanghai` 创建一次持久任务；若服务器在当天计划时间后恢复，并且仍处于 12 小时补偿窗口内，会补建当天任务。数据库唯一约束确保多个 Scheduler 副本不会重复创建同一天的运行记录。

## 首批权威来源

| 层级 | 来源 |
|---|---|
| A | 中国政府网最新政策、北京师范大学新闻网、中国科学院科研进展、商汤科技新闻中心 |
| B | 新华网科技、光明网教育、科技日报、中国新闻网教育 |

来源入口、HTTPS 主机/路径白名单、robots/条款复核、限速、解析器版本和标题相关性规则保存在版本化来源登记中。单个来源可以独立禁用；一个来源失败不会阻止其他来源完成。

当前活动来源版本使用确定性的 `ai-title-v1` 标题规则，只接收人工智能、大模型、机器学习、智能体、算法/算力/AI 芯片、视觉/语音/NLP、机器人/具身智能、自动驾驶/无人系统、无人机和脑机接口等主题。AI 相关规划、治理、标准、通知和支持政策属于范围；普通教育、文化、金融、生活以及未与 AI/机器人/智能系统明确关联的量子、航天、生物技术和新能源标题会被过滤。规则不调用 LLM、Embedding 或外部分类服务。

采集器会先扫描一个有界的近期列表，再只请求标题相关条目的详情。`ACQUISITION_FIRST_RUN_SCAN_LIMIT` / `ACQUISITION_DAILY_SCAN_LIMIT` 控制扫描深度，`ACQUISITION_FIRST_RUN_ITEM_LIMIT` / `ACQUISITION_DAILY_ITEM_LIMIT` 控制最多接收多少个相关条目；扫描上限必须大于或等于接收上限。零匹配来源会成功结束、记录过滤计数并推进原始列表游标，不会用无关文章填满配额。

## 查看采集结果

候选列表直接提供后续工作流需要的来源、最新相关标题、发布时间和原文链接，同时保留候选 ID 与规则版本：

```bash
curl 'http://127.0.0.1:8000/api/v1/evidence-candidates?relevance_rule_version=ai-title-v1&limit=20'
```

`relevance_rule_version=ai-title-v1` 会把历史上尚未启用标题规则的候选排除在正常下游队列之外，但这些旧记录仍可在不带该参数时用于审计。重点字段为 `source_display_name`、`title`、`published_at` 和 `original_url`。使用返回的候选 ID 查询详情，可读取已存储的 `clean_text`、不可变快照元数据和 observation provenance；正常下游处理不需要再次访问原网站：

```bash
curl 'http://127.0.0.1:8000/api/v1/evidence-candidates/<candidate-id>'
```

## 常用命令

```bash
make infra-up          # 启动 PostgreSQL/pgvector 与 MinIO
make migrate           # Alembic 升级到最新数据库版本
make seed-sources      # 幂等写入八个批准来源并激活当前不可变版本
make stack-up          # 构建并启动 migration/API/Scheduler/Worker 完整形状
make infra-status      # 查看容器状态
make infra-logs        # 查看基础设施日志
make infra-down        # 停止服务但保留数据卷
make api-generate      # 导出 FastAPI OpenAPI 并生成前端类型
make backend-check     # Ruff format/lint + mypy + pytest
make backend-integration-test # 真实 PostgreSQL/MinIO 集成测试
make frontend-check    # Prettier + ESLint + TypeScript + Vitest + Vite build
make check             # 全部质量检查
make doctor            # 环境与基础设施 smoke check
make source-smoke      # 可选：按安全策略小规模访问八个实时官网入口
```

前端依赖由 `frontend/package-lock.json` 锁定，日常安装使用 `npm ci --prefix frontend`。项目已配置 TanStack Query、`openapi-fetch` 与 `openapi-typescript`；FastAPI 接口变化后运行 `make api-generate`，提交更新后的 `backend/openapi.json` 与生成类型，不手写重复的接口模型。

需要更换端口或采集时间时，复制 `.env.example` 为 `.env` 后修改对应配置。修改 `APP_PORT` 时必须同步修改 `VITE_API_BASE_URL`；修改 `POSTGRES_PORT` 时必须同步修改 `DATABASE_URL`；修改 `MINIO_API_PORT` 时必须同步修改 `MINIO_ENDPOINT`。采集小时、分钟、时区、补偿窗口、并发、租约、重试、响应大小、扫描深度和相关条目接收上限都可通过环境变量调整。`.env` 不进入版本控制。

实时官网访问只用于人工 smoke check，不属于自动测试。自动测试使用仓库内受控的八源页面样本；集成测试会创建随机命名的临时 PostgreSQL 数据库和测试专用 MinIO bucket，结束后清理。

如果 `make source-smoke` 对全部来源都返回 `non_public_address`，并且 `getent ahosts
www.gov.cn` 等命令显示 `198.18.x.x`，通常是 Clash Verge/Mihomo 的 Fake-IP DNS 模式。
应在代理的 `dns.fake-ip-filter` 中加入 `+.gov.cn`、`+.bnu.edu.cn`、`+.cas.cn`、
`+.sensetime.com`、`+.news.cn`、`+.gmw.cn`、`+.stdaily.com` 和
`+.chinanews.com.cn`，随后重载代理配置。不要把 `198.18.0.0/15` 加入公网白名单，
也不要关闭抓取器的 DNS/IP 安全检查。

## 安全边界

- 所有来源请求必须通过 HTTPS 主机/路径白名单、公共 DNS/IP 校验、逐跳重定向校验、超时、响应大小和内容类型限制。
- 抓取页面一律视为不可信数据，页面内类似指令的文字不会被执行。
- 日志和 API 不暴露原始页面、Cookie、凭据或签名对象 URL。
- 公司 AI 平台配置默认留空，后续集成任务再配置。
- 不要把真实 API Key、数据库密码、签名 URL 或社媒凭据提交到仓库。
- 当前系统只提供采集和内部查询，不包含自动发布朋友圈。
- `docker compose down` 不删除数据；只有明确需要重置时才手动使用 `down -v`。

生产部署前还必须配置非占位凭据、TLS/反向代理、访问认证、数据库与对象存储备份、外部监控告警和明确的数据保留策略。不要直接把当前回环开发端口暴露到公网。

## 技术与开发规范

- [项目技术报告](./技术报告.pdf)
- [后端规范](./.trellis/spec/backend/index.md)
- [前端规范](./.trellis/spec/frontend/index.md)
- [Trellis 工作流](./.trellis/workflow.md)
