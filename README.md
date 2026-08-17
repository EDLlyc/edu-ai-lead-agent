# Edu AI Lead Agent

面向家长的每日科学与 AI 教育内容素材 Agent。采集层当前从十个活动来源增量采集科学教育、AI 教育、科学素养、STEM 与青少年科创实践等公开资料，并保存不可变快照与完整来源证据；新华教育已通过新增来源激活门，另有两个已批准的连接器等待独立实时激活门，目标来源数为十二。治理层从已存储候选中做版本化规范化、事实结构化分析、精确/语义去重和可审计事件组织。

第二层使用 PostgreSQL/pgvector 和可恢复的 LangGraph checkpoint，支持确定性选题、品牌 RAG、证据绑定文案、独立图片/素材包、内部审核台，以及离线 fake provider 与显式启用的智谱模型。默认仍运行兼容的每日 Top 1；另有默认关闭的早、中、晚三时段模式，每个栏目可独立选择 0--3 条并生产、验证和投递独立素材。系统不提供公开社交平台自动发布。

## Agent 求职作品集

仓库另含一个与生产业务隔离的本地 Agent Research Workbench，用同一套强类型只读工具展示
bounded Function Calling、MCP stdio、claim-level 引用校验、脱敏 Trace 和确定性评测。默认演示
使用脱敏 fixture 与固定策略，不需要模型密钥、生产数据库或网络，也不能写业务数据或触发企微。

```bash
make agent-portfolio-check
# 终端 1
make agent-workbench-dev
# 终端 2
make agent-workbench-ui
```

Workbench 后端只绑定 `127.0.0.1:8010`，页面只在 Vite development 且显式打开本地 flag 时
出现；正常 `api_main`、Dockerfile、Compose 与生产 OpenAPI 均不注册该功能。架构、安全边界、
评测解释和面试讲解见 [Agent Research Workbench case study](./docs/portfolio/agent-workbench.md)。

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

## 依赖锁与固定 Digest 发布

`backend/pyproject.toml` 是 Python 依赖的人类维护源；运行时和开发环境分别由带哈希的
`backend/requirements/runtime.lock`、`backend/requirements/dev.lock` 固定。修改依赖后必须
重新生成并检查漂移：

```bash
make python-lock
make python-lock-check
```

本地 Compose 仍可使用 `docker compose up -d --build`，九个应用/迁移服务会共享本地默认
镜像 `edu-ai-lead-agent-backend:local`。生产发布则只接受
`registry/namespace/repository@sha256:<digest>` 形式的 `APP_IMAGE`，九个服务使用同一 digest，
并始终以 `--no-build` 启动；生产机不解析 Python 依赖，也不访问 PyPI 构建应用镜像。
前端只用于本地开发和 CI 的格式、类型、测试、Vite build 与 API contract 门禁；本流水线不
构建或上传生产前端镜像，不把 `frontend/dist` 放入 release bundle，也不部署或修改生产前端。

当前支持的生产激活路径是从开发机显式执行一次本地不可变发布。先在开发机的 Docker
credential store 中登录目标 OCI/ACR repository，并配置一个能通过已知主机严格校验的 SSH
host alias；不要把 registry/SSH 密码、token 或私钥写入命令、环境变量或仓库。入口只接受
非秘密的 repository 和 host alias：

```bash
RELEASE_IMAGE_REPOSITORY=registry.example/namespace/edu-ai-lead-agent \
RELEASE_SSH_HOST=edu-ai-production RELEASE_DRY_RUN=true make release-prod

RELEASE_IMAGE_REPOSITORY=registry.example/namespace/edu-ai-lead-agent \
RELEASE_SSH_HOST=edu-ai-production make release-prod
```

`RELEASE_DRY_RUN=true` 只检查本机 Unix-socket Docker/Compose、缓存的 Codeup `origin/main`
身份，以及本地 SSH alias/`known_hosts`，并输出无秘密计划；不 fetch、构建、push、建立 SSH
连接或修改生产。真实模式用无交互认证获取 Codeup `main`，要求当前发布脚本与该提交一致，
在一次性 detached worktree 中以固定本地 DB/MinIO 和关闭的 provider/WeCom 配置执行门禁与
缓存构建。候选镜像在 push 前和解析完整 digest 后均通过 migration/doctor；三件套会保留在
本地 Git common directory 供审计，只传输已验证的 bundle/checksum/manifest，最后调用服务器
已有的 root-owned deploy 入口。调用者的 dirty worktree 永远不是发布输入；前端仍只参加质量
门，不生成生产镜像。首次真实发布仍要求生产机已有可信 previous-digest/current-manifest 基线。

Codeup `marketingUseOnly/edu-ai-lead-agent` 是权威写入源，日常分支和 `main` 推送到
`origin`；GitHub `EDLlyc/edu-ai-lead-agent` 仅接收单向备份，不能反向覆盖 Codeup 或触发
生产。仓库内 Flow 的 ACR 发布、GitHub 备份和生产部署开关默认全部关闭，必须在对应外部
连接、隔离、Runner、上一 digest 基线和 dry-run 门禁完成后由管理员逐项启用。
Flow 质量门不使用托管机自带的语言版本：后端/发布检查由仓库构建的 Python 3.11
dev-lock 工具镜像执行，前端门禁使用 digest 固定的 Node 20 镜像。CI 容器不继承宿主/Flow
秘密环境；已有的普通 Pydantic/Vite 环境文件会被只读遮蔽，缺失文件不会被创建，符号链接
或非普通文件会被拒绝。Python 默认无网络，只在 Compose 基础设施健康且 MinIO 初始化完成
后加入项目网络。Node 仅在 `npm ci` 时联网，后续前端门禁离线执行。这两个工具镜像都不会
上传 ACR 或部署到生产。

`quality_job` 与本地候选镜像 `image_job` 的外层执行环境同样固定到云效官方 alinux3 的
linux/amd64 manifest digest；启动时以 `docker info` 和 `docker compose version` 实测 daemon
与 Compose 能力。镜像中是否声明某个工具不能替代这两个 live probe。云效公共构建集群的
指定容器已实测只有 Docker CLI/Compose、没有可连接的 daemon，不能承担本项目的完整
PostgreSQL/MinIO Compose 门禁。自动化 Flow 发布若未来启用，仍必须使用独立的非生产 Docker
构建节点，不得把生产服务器兼作 CI 构建机。当前不创建私有/VPC 构建集群，Flow 仅保留为
失败关闭的可移植性路径，本地不可变发布不以该集群为前置条件。

完整的发布清单/bundle 契约、凭据轮换、激活门、Runner 停用、部署阶段和兼容性回退规则见
[固定 Digest 发布运行手册](./docs/operations/digest-release-runbook.md)。

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

三时段模式由 `CONTENT_SLOT_MODE_ENABLED` 和三个栏目开关共同控制，全部默认关闭。
默认目标为 07:30、12:30、18:30（`Asia/Shanghai`），上游提前 90 分钟准备，投递窗口为目标后 60 分钟；同一栏目相邻素材包的开始时间通过数据库窗口保持至少 60 秒。只读查看接口为
`GET /api/v1/content-editions/<yyyy-mm-dd>?profile=preview`。旧
`GET /api/v1/daily-topics/<yyyy-mm-dd>` 继续保留每日 Top 1 的历史语义。

配图受控多样性由 `IMAGE_DIVERSITY_ENABLED` 控制，默认关闭。启用后仍保持赛先生、小赛的
统一 3D 卡通形象和蓝白橙品牌语言，只在受控的场景、构图、镜头、角色组合、时段气质与主题
物件中变化，并优先避开最近七天已经使用的完整组合。首张安全图片若与七日历史近似，只使用
预留的备用方案重生成一次；第二张仍近似但其他质量门通过时继续使用，素材包记录
`near_duplicate_after_retry` 告警且不阻断原有自动投递。API/worker 必须共享全部版本、七日窗口、
阈值和固定一次重生成上限；启用受控多样性还必须同时设置 `IMAGE_OCR_ENABLED=true`，否则配置
校验会拒绝启动。`make doctor` 会检查跨服务配置一致性。前端详情页仅供本地检查这些安全标签，
不进入生产部署。生产启用步骤见
[生产服务器迁移运行手册](./docs/operations/production-server-migration-runbook.md#controlled-visual-diversity-rollout)。
受控 v2/v3 配图同时固定使用一个深蓝圆角三层标题卡：品牌签名 `赛先生科学`、有限类别主标题、
对应短副标题。不得把原始新闻标题、完整文案、自由生成口号或伪文字画进图片；OCR 必须只识别
这三行，且标题卡不能遮挡角色面部、科学物体或主体动作。历史 v1 文字模式保持不变。
图片 OCR 使用独立的 `IMAGE_OCR_MODEL=glm-ocr` 通过智谱 `/layout_parsing`
识别已通过媒体门的 PNG/JPEG；`AI_CHAT_MODEL=glm-5.2` 仍只用于文本生成和
原有文本模型流程。OCR 默认限制为 10 MiB 输入、1 MiB 响应和 120 秒超时；
不会把图片上传到公开 URL，也不记录 Base64 或供应商原始响应。

## 首批权威来源

| 状态 | 层级 | 来源 |
|---|---|---|
| 活动 | A | 中国政府网最新政策、北京师范大学新闻网、中国科学院科研进展、商汤科技新闻中心、教育部科学新闻 |
| 活动 | B | 新华网科技、光明网教育、科技日报、中国新闻网教育、新华教育 |
| 待实时激活门 | B | 中国科协科普与科学教育、EdSurge AI Education |

来源入口、HTTPS 主机/路径白名单、robots/条款复核、限速、解析器版本和标题相关性规则保存在版本化来源登记中。单个来源可以独立禁用；一个来源失败不会阻止其他来源完成。

当前活动来源版本使用确定性的 `science-tech-editorial-v2` 中英双语分层规则。科学/AI/科技教育、STEM、科学探究、白名单赛事、科技特长生、强基计划和综评等具备实质政策或培养语境的内容进入教育优先层；不含教育语境但同时具备具体科技主题与突破/发现/验证等进展信号的机器人、人工智能和重大科研成果进入前沿科技层。培训导流、保录保过、分数线聚合、融资营销、消费电子和普通企业公告不会仅凭关键词入选。`product-matrix-fit-v2-science-pathways` 仍只是六类产品方向的有上限软排序信号，绝不能创造资格或覆盖 veto。历史 `science-ai-education-v1` 与 `product-matrix-fit-v1` 保持可回放，所有规则均不调用 LLM、Embedding 或外部分类服务。

`acquisition-v5-tiered-science-tech` 会先扫描有界近期列表，按教育标题、前沿突破标题、中性正文探测的顺序请求详情，同层内才使用产品适配、发布时间、原列表位置和稳定 ID 排序；正文提取后用标题加最多 6000 个规范化正文字符复核。`ACQUISITION_FIRST_RUN_SCAN_LIMIT` / `ACQUISITION_DAILY_SCAN_LIMIT` 控制扫描深度，`ACQUISITION_FIRST_RUN_ITEM_LIMIT` / `ACQUISITION_DAILY_ITEM_LIMIT` 控制详情探测窗口。零匹配来源会成功结束、记录三层计数及过滤/延后计数并推进原始列表游标，不会用无关文章填满配额。

## 查看采集结果

候选列表直接提供后续工作流需要的来源、最新相关标题、发布时间和原文链接，同时保留候选 ID 与规则版本：

```bash
curl 'http://127.0.0.1:8000/api/v1/evidence-candidates?relevance_rule_version=science-tech-editorial-v2&limit=20'
```

`relevance_rule_version=science-tech-editorial-v2` 会把旧规则候选排除在当前下游队列之外，但旧记录仍可在不带该参数时用于审计和历史回放。重点字段为 `source_display_name`、`title`、`published_at` 和 `original_url`。使用返回的候选 ID 查询详情，可读取已存储的 `clean_text`、不可变快照元数据、内容层级/理由/产品方向和 observation provenance；正常下游处理不需要再次访问原网站：

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
make python-lock       # 由 pyproject 重新生成 runtime/dev hash locks
make python-lock-check # 重新解析并检查依赖锁漂移
make release-tool-check # 发布清单、bundle、部署状态机与 Flow 静态契约测试
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
