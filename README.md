# Edu AI Lead Agent

面向家长的每日科学与 AI 教育内容素材 Agent。采集层当前从十个活动来源增量采集科学教育、AI 教育、科学素养、STEM 与青少年科创实践等公开资料，并保存不可变快照与完整来源证据；新华教育已通过新增来源激活门，另有两个已批准的连接器等待独立实时激活门，目标来源数为十二。治理层从已存储候选中做版本化规范化、事实结构化分析、精确/语义去重和可审计事件组织。

第二层使用 PostgreSQL/pgvector 和可恢复的 LangGraph checkpoint，支持离线 fake provider 与显式启用的智谱模型。当前仍不包含选题评分、Top 1、品牌 RAG、文案/图片生成、产品前端页面或自动发布。

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
make governance-scheduler
make governance-worker
npm run dev --prefix frontend
```

也可以构建并启动完整后端进程形状：

```bash
make stack-up
```

API、Scheduler 和 Worker 是独立进程。Scheduler 默认每天 `06:30 Asia/Shanghai` 创建一次持久任务；若服务器在当天计划时间后恢复，并且仍处于 12 小时补偿窗口内，会补建当天任务。数据库唯一约束确保多个 Scheduler 副本不会重复创建同一天的运行记录。

治理 Scheduler/Worker 也是独立进程，并且默认关闭。Compose 使用 `governance` profile，普通 `make stack-up` 不会启动模型流程。准备好配置后可运行 `make governance-stack-up`；治理模型故障不会阻塞采集 API、采集 Scheduler 或采集 Worker。

## 首批权威来源

| 状态 | 层级 | 来源 |
|---|---|---|
| 活动 | A | 中国政府网最新政策、北京师范大学新闻网、中国科学院科研进展、商汤科技新闻中心、教育部科学新闻 |
| 活动 | B | 新华网科技、光明网教育、科技日报、中国新闻网教育、新华教育 |
| 待实时激活门 | B | 中国科协科普与科学教育、EdSurge AI Education |

来源入口、HTTPS 主机/路径白名单、robots/条款复核、限速、解析器版本和标题相关性规则保存在版本化来源登记中。单个来源可以独立禁用；一个来源失败不会阻止其他来源完成。

当前活动来源版本使用确定性的 `science-ai-education-v1` 中英双语规则。明确的科学教育、AI 教育、科学/AI 素养、STEM、科学探究或青少年科创表达可以进入候选；其他文本必须同时出现科学/AI 主题与教育、学习者、教师或实践场景。普通教育、纯科技产业新闻和泛 AI 标题会被过滤。`product-matrix-fit-v1` 只为六类产品方向提供软排序信号，绝不能改变资格或救回任何 veto。规则不调用 LLM、Embedding 或外部分类服务。

采集器会先扫描一个有界的近期列表，优先请求标题已经命中范围的详情；标题信息不足时，仅用剩余条目窗口做有界中性详情探测，并在正文提取后用标题加最多 6000 个规范化正文字符重新判定。`ACQUISITION_FIRST_RUN_SCAN_LIMIT` / `ACQUISITION_DAILY_SCAN_LIMIT` 控制扫描深度，`ACQUISITION_FIRST_RUN_ITEM_LIMIT` / `ACQUISITION_DAILY_ITEM_LIMIT` 控制最多接收多少个合格条目；扫描上限必须大于或等于接收上限。零匹配来源会成功结束、记录过滤与探测计数并推进原始列表游标，不会用无关文章填满配额。

## 查看采集结果

候选列表直接提供后续工作流需要的来源、最新相关标题、发布时间和原文链接，同时保留候选 ID 与规则版本：

```bash
curl 'http://127.0.0.1:8000/api/v1/evidence-candidates?relevance_rule_version=science-ai-education-v1&limit=20'
```

`relevance_rule_version=science-ai-education-v1` 会把旧规则候选排除在当前下游队列之外，但旧记录仍可在不带该参数时用于审计和历史回放。重点字段为 `source_display_name`、`title`、`published_at` 和 `original_url`。使用返回的候选 ID 查询详情，可读取已存储的 `clean_text`、不可变快照元数据和 observation provenance；正常下游处理不需要再次访问原网站：

```bash
curl 'http://127.0.0.1:8000/api/v1/evidence-candidates/<candidate-id>'
```

## 第二部分：事实治理与事件组织

治理只读取已经入库的候选、observation 和 snapshot，不接收 URL，也不会重新访问原网站。处理结果包含稳定 passage、证据绑定、七类事实标签、实体、精确/近似重复关系、事件成员关系、不可变事件版本和可解释的 assignment features。

手动选择 1–100 个候选入队时必须提供幂等键；HTTP 请求只创建持久任务，不在请求内调用模型：

```bash
curl -i -X POST 'http://127.0.0.1:8000/api/v1/governance-runs' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: manual-governance-example-001' \
  -d '{"candidate_ids":["<candidate-id>"]}'
```

也可以用终态采集 run 创建治理 run：

```bash
curl -i -X POST 'http://127.0.0.1:8000/api/v1/governance-runs' \
  -H 'Content-Type: application/json' \
  -d '{"acquisition_run_id":"<acquisition-run-id>"}'
```

查询运行状态、候选事实和事件详情：

```bash
curl 'http://127.0.0.1:8000/api/v1/governance-runs/<run-id>'
curl 'http://127.0.0.1:8000/api/v1/governance-runs/<run-id>/jobs?limit=20'
curl 'http://127.0.0.1:8000/api/v1/candidate-analyses/<candidate-id>'
curl 'http://127.0.0.1:8000/api/v1/events?limit=20'
curl 'http://127.0.0.1:8000/api/v1/events/<event-id>'
```

离线验收推荐先在 `.env` 中设置：

```dotenv
GOVERNANCE_ENABLED=true
GOVERNANCE_SCHEDULER_ENABLED=true
GOVERNANCE_WORKER_ENABLED=true
AI_PROVIDER_MODE=fake
```

然后运行 `make governance-stack-up`。fake provider 始终返回确定性结构化事实和 2048 维向量，不需要网络或 API Key。`make governance-fake-check` 会执行聚焦单元测试和真实 PostgreSQL/pgvector 端到端验收。

智谱验收必须在本地 `.env` 或部署 secret store 中提供 `AI_PLATFORM_BASE_URL` 与 `AI_PLATFORM_API_KEY`，并设置 `AI_PROVIDER_MODE=zhipu`。使用一个明确的已存储候选运行：

```bash
make governance-live-smoke CANDIDATE_ID=<candidate-id>
```

该命令最多处理一个候选，只输出 run/job/candidate/event ID、模型、版本、计数、token、延迟和终态；不会输出 API Key、正文、完整 prompt、原始模型响应、embedding 或 provider request ID。普通自动测试不调用真实智谱。

## 常用命令

```bash
make infra-up          # 启动 PostgreSQL/pgvector 与 MinIO
make migrate           # Alembic 升级到最新数据库版本
make seed-sources      # 幂等写入十个活动来源并激活当前不可变版本
make stack-up          # 构建并启动 migration/API/Scheduler/Worker 完整形状
make governance-stack-up # 启动默认关闭的 Compose governance profile
make governance-scheduler # 将终态采集 run 对账为治理 run
make governance-worker # 运行独立 LangGraph 治理 worker
make governance-fake-check # fake provider + 真实 PostgreSQL 端到端验收
make governance-live-smoke CANDIDATE_ID=<id> # 单候选智谱验收
make infra-status      # 查看容器状态
make infra-logs        # 查看基础设施日志
make infra-down        # 停止服务但保留数据卷
make api-generate      # 导出 FastAPI OpenAPI 并生成前端类型
make backend-check     # Ruff format/lint + mypy + pytest
make backend-integration-test # 真实 PostgreSQL/MinIO 集成测试
make frontend-check    # Prettier + ESLint + TypeScript + Vitest + Vite build
make check             # 全部质量检查
make doctor            # 环境与基础设施 smoke check
make source-smoke      # 可选：按安全策略小规模访问十个活动官网入口
```

前端依赖由 `frontend/package-lock.json` 锁定，日常安装使用 `npm ci --prefix frontend`。项目已配置 TanStack Query、`openapi-fetch` 与 `openapi-typescript`；FastAPI 接口变化后运行 `make api-generate`，提交更新后的 `backend/openapi.json` 与生成类型，不手写重复的接口模型。

需要更换端口、采集时间或治理版本时，复制 `.env.example` 为 `.env` 后修改对应配置。修改 `APP_PORT` 时必须同步修改 `VITE_API_BASE_URL`；修改 `POSTGRES_PORT` 时必须同步修改宿主机使用的 `DATABASE_URL` 和 `GOVERNANCE_CHECKPOINT_DATABASE_URL`；修改 `MINIO_API_PORT` 时必须同步修改 `MINIO_ENDPOINT`。Compose 内 checkpoint URL 指向 `postgres:5432`。采集与治理的并发、租约、重试、模型、预算和所有派生规则版本都可独立配置。`.env` 不进入版本控制。

实时官网访问只用于人工 smoke check，不属于自动测试。自动测试使用仓库内受控的十个活动源加两个待激活源页面样本；集成测试会创建随机命名的临时 PostgreSQL 数据库和测试专用 MinIO bucket，结束后清理。中国科协与 EdSurge 在 2026-08-13 的当前网络环境中被安全抓取器以 `non_public_address` 阻断，因此不在活动 seed、默认 smoke 或定时任务中；修复 DNS 后仍须分别完成有界 entry + 单详情验证，不能用 fixture 结果代替激活门。

如果 `make source-smoke` 对全部来源都返回 `non_public_address`，并且 `getent ahosts
www.gov.cn` 等命令显示 `198.18.x.x`，通常是 Clash Verge/Mihomo 的 Fake-IP DNS 模式。
应在代理的 `dns.fake-ip-filter` 中加入 `+.gov.cn`、`+.bnu.edu.cn`、`+.cas.cn`、
`+.sensetime.com`、`+.news.cn`、`+.gmw.cn`、`+.stdaily.com` 和
`+.chinanews.com.cn`、`+.moe.gov.cn`、`+.cast.org.cn` 和 `+.edsurge.com`，随后重载代理配置。不要把 `198.18.0.0/15` 加入公网白名单，
也不要关闭抓取器的 DNS/IP 安全检查。

## 安全边界

- 所有来源请求必须通过 HTTPS 主机/路径白名单、公共 DNS/IP 校验、逐跳重定向校验、超时、响应大小和内容类型限制。
- 抓取页面一律视为不可信数据，页面内类似指令的文字不会被执行。
- 日志和 API 不暴露原始页面、Cookie、凭据或签名对象 URL。
- 智谱配置默认关闭；真实 API Key 只提供给治理 worker/live smoke，不注入 API 或采集进程。
- LangGraph checkpoint 只保存 ID、hash、版本和小型状态，不保存正文、prompt、原始响应或凭据。
- 治理 API 不包含任意 URL 抓取、选题评分、内容生成、发布或凭据字段。
- 不要把真实 API Key、数据库密码、签名 URL 或社媒凭据提交到仓库。
- 当前系统只提供采集、事实治理、事件组织和内部查询，不包含自动发布朋友圈。
- `docker compose down` 不删除数据；只有明确需要重置时才手动使用 `down -v`。

生产部署前还必须配置非占位凭据、TLS/反向代理、访问认证、数据库与对象存储备份、外部监控告警和明确的数据保留策略。不要直接把当前回环开发端口暴露到公网。

## 技术与开发规范

- [项目技术报告](./技术报告.pdf)
- [后端规范](./.trellis/spec/backend/index.md)
- [前端规范](./.trellis/spec/frontend/index.md)
- [Trellis 工作流](./.trellis/workflow.md)
