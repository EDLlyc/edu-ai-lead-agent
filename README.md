# Edu AI Lead Agent

面向家长的每日 AI 教育内容素材 Agent。当前仓库处于开发环境与首个垂直切片准备阶段，尚未实现采集、选题、RAG、生成或自动发布功能。

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
| FastAPI（手动启动） | <http://127.0.0.1:8000> |
| PostgreSQL/pgvector | `127.0.0.1:5432` |
| MinIO API | <http://127.0.0.1:9000> |
| MinIO Console | <http://127.0.0.1:9001> |
| Vite（手动启动） | <http://127.0.0.1:5173> |

启动开发服务器：

```bash
make backend-dev
npm run dev --prefix frontend
```

## 常用命令

```bash
make infra-up          # 启动 PostgreSQL/pgvector 与 MinIO
make infra-status      # 查看容器状态
make infra-logs        # 查看基础设施日志
make infra-down        # 停止服务但保留数据卷
make api-generate      # 导出 FastAPI OpenAPI 并生成前端类型
make backend-check     # Ruff format/lint + mypy + pytest
make frontend-check    # Prettier + ESLint + TypeScript + Vitest + Vite build
make check             # 全部质量检查
make doctor            # 环境与基础设施 smoke check
```

前端依赖由 `frontend/package-lock.json` 锁定，日常安装使用 `npm ci --prefix frontend`。项目已配置 TanStack Query、`openapi-fetch` 与 `openapi-typescript`；FastAPI 接口变化后运行 `make api-generate`，提交更新后的 `backend/openapi.json` 与生成类型，不手写重复的接口模型。

需要更换端口时，复制 `.env.example` 为 `.env` 后修改对应配置。修改 `APP_PORT` 时必须同步修改 `VITE_API_BASE_URL`；修改 `POSTGRES_PORT` 时必须同步修改 `DATABASE_URL`；修改 `MINIO_API_PORT` 时必须同步修改 `MINIO_ENDPOINT`。`.env` 不进入版本控制。

## 安全边界

- 公司 AI 平台配置默认留空，后续集成任务再配置。
- 不要把真实 API Key、数据库密码、签名 URL 或社媒凭据提交到仓库。
- 当前系统只规划人工审核、复制和下载，不包含自动发布朋友圈。
- `docker compose down` 不删除数据；只有明确需要重置时才手动使用 `down -v`。

## 技术与开发规范

- [项目技术报告](./技术报告.pdf)
- [后端规范](./.trellis/spec/backend/index.md)
- [前端规范](./.trellis/spec/frontend/index.md)
- [Trellis 工作流](./.trellis/workflow.md)
