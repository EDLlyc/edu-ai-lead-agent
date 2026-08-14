# Codeup 主仓库与固定 Digest 全自动发布流水线

## Goal

在公司云效组织的 `marketingUseOnly` 代码组内建立独立的私有
`edu-ai-lead-agent` Codeup 主仓库和固定 digest 发布契约。当前优先支持开发机一条命令从
已提交且已同步的 Codeup `main` 完成隔离质量检查、缓存镜像构建、OCI 仓库推送、不可变
digest 解析、release bundle/manifest 验证、严格 SSH 传输和既有 root 部署状态机调用；开发机
只需在该次发布期间在线。Flow 保留为 CI 可移植性和未来自动化路径，不再阻塞当前发布。
生产服务器只按不可变 digest 拉取已验证镜像，不从 PyPI 构建应用镜像。GitHub 仅作为
Codeup 的单向只读备份。

## Background and Confirmed Facts

- 当前 GitHub 私有仓库为 `EDLlyc/edu-ai-lead-agent`，默认分支 `main`，已有 162 个提交，
  没有 GitHub Actions 发布流水线。
- 公司云效组织为“赛先生科学”。私有 Codeup 代码组 `marketingUseOnly` 的 ID 为 `2071662`，
  当前仓库数为 0。
- 用户已决定 Codeup 为唯一权威写入源，GitHub 不再接受日常开发提交，也不触发生产发布。
- 用户已决定功能分支只运行验证；受保护 `main` 更新且全部门禁通过后自动部署生产，不设置
  人工批准节点。
- 生产服务器公网网段由腾讯 AS45090 宣告，可确认属于腾讯云网络而不是阿里云 ECS；仅凭
  IP 无法区分 CVM 与轻量应用服务器。
- 用户已决定把生产服务器作为非阿里云自有主机接入云效 Runner；CI 和镜像构建不得占用
  生产服务器。
- 云效组织当前没有 Flow 主机组，也没有 GitHub 服务连接。非阿里云 Runner 的一次性注册
  命令需要从云效网页生成，官方 CLI 当前不提供该注册令牌接口。
- 组织已有 ACR 服务连接 `sxsstem的容器镜像服务(ACR)服务连接`（ID `79934`）。用户已
  授权优先尝试复用；资源级权限或隔离条件不满足时必须失败关闭。
- 当前 PAT 可列出组织、Codeup 代码组/仓库目录、Flow 流水线目录和服务连接，但读取现有
  流水线详情返回 `403 InvalidPipeline.NotHavePipelinePermission`。目录可见不代表资源操作
  权限。
- [`compose.yaml`](../../../compose.yaml) 的九个应用服务当前使用同一 `backend/` 构建上下文，
  还没有外部镜像 digest 输入；[`backend/Dockerfile`](../../../backend/Dockerfile) 会在线执行
  `pip install`，而 Python 依赖当前没有锁文件。
- 2026-08-13 的生产发布因生产机访问 `files.pythonhosted.org` 超时而改用一次性离线 overlay，
  维护窗口耗时 3,178 秒。该方法不能作为常规发布方案，证据见前序任务
  [`result.md`](../archive/2026-08/08-13-deploy-todays-changes-production/result.md)。
- 现有 [`scripts/edu-ai-backup.sh`](../../../scripts/edu-ai-backup.sh) 已备份 PostgreSQL、MinIO
  和品牌资料；[`scripts/edu-ai-production-evidence.sh`](../../../scripts/edu-ai-production-evidence.sh)
  已生成生产证据。本任务必须复用并扩展这些能力。
- 工作区存在用户未提交的 `.agents/skills/trellis-break-loop/SKILL.md` 和 `reports/` 内容；本
  任务不得修改、提交、迁移或打包这些路径。
- Flow runs 4/6 已分别证明默认环境缺 Docker、官方指定容器有 Docker CLI/Compose 但没有
  可达 daemon。用户已批准不购买/接入私有构建集群的当前替代路径：在开发机执行一键发布，
  同时保留未来 Flow CI 可移植性；生产机仍不得承担 CI 或镜像构建。

## Requirements

### R1 — Repository ownership and migration

- 在代码组 `2071662` 下创建私有空仓库 `edu-ai-lead-agent`，不得生成无关初始提交。
- 完整迁移当前 Git 对象、分支和标签；迁移前后 `main` 提交必须完全一致，并验证所有引用。
- Codeup 成为本地 `origin` 和唯一生产源；GitHub 改为明确命名的只读备份远端。
- Codeup `main` 必须设为保护分支并禁止强制推送。GitHub 只能接收 Codeup 的单向备份，
  不得反向覆盖 Codeup 或形成双主写入。
- GitHub 备份使用独立、仓库级最小权限身份；备份失败记录为退化状态并告警，但不得反向
  修改 Codeup，也不得把个人长期凭据写入仓库或日志。

### R2 — Source authority, local release and Flow portability

- 为新 Codeup 仓库创建独立 Flow 流水线，不复用组织内现有 23 条其他项目流水线。
- 功能分支只执行静态检查、测试、Compose/API contract 检查和镜像可构建性验证；不得获得
  ACR 推送、生产部署或生产 Runner 权限。
- Flow 质量门不得依赖托管构建机预装的旧 Python/Node；Python 3.11 和 Node 20 必须由
  digest/lock 约束的 CI 容器提供，且容器不得继承构建机或 Flow 的秘密环境变量。真实
  PostgreSQL/MinIO 测试必须先启动健康的 Compose 基础设施，再通过受限项目网络执行。
  Python 容器默认无网络，Node 只允许 `npm ci` 使用 registry 网络；已有普通 Pydantic/Vite
  环境文件必须遮蔽，缺失文件不得由质量门创建，符号链接或非普通遮蔽目标必须 fail closed。
- 当前生产发布由操作者在开发机显式执行一条命令；命令必须从刚获取并验证的 Codeup
  `origin/main` committed object 创建隔离 checkout，不得从当前分支、dirty worktree 或未跟踪
  文件构建。Flow 自动发布作为后续可移植路径保留，不是当前激活前置条件。
- 同一时刻最多一个生产发布；并发或重复提交必须排队或显式取消旧运行，不能交叉迁移和
  重建容器。

### R3 — Reproducible image build and verification

- 增加受版本控制的 Python 运行时依赖锁定输入；镜像不得仅依赖宽范围 `pyproject.toml`
  在构建时重新解析版本。
- 应用镜像只在受控的隔离 checkout 中构建；当前支持开发机 Docker，未来可迁移到具备 daemon
  的 Flow 环境。基础镜像、依赖锁、Git 提交、构建时间和源码地址必须进入可审计的非秘密
  元数据。
- 推送前必须通过后端、前端、API contract、Compose、doctor、Dockerfile/镜像运行时检查；
  失败不得推送或部署。
- 前端只用于本地开发和 CI 质量/API contract 校验；不得构建生产前端镜像、上传 ACR、进入
  release bundle 或由本流水线部署到生产。发布镜像和生产服务矩阵只覆盖 backend。
- 九个应用/迁移服务使用同一个已验证应用镜像 digest，禁止混用不同源码或依赖镜像。

### R4 — ACR isolation and immutable deployment

- 优先复用服务连接 `79934`，但只允许选择或创建本项目独立 ACR 仓库；不得复用其他项目
  镜像仓库、读取连接凭据或扩大服务连接授权范围。
- 资源级权限、实例地域、命名空间、网络白名单或独立仓库条件任一不满足时失败关闭，并由
  管理员补充授权。
- ACR 同时保留可读提交标签和内容寻址 digest；生产部署参数只接受
  `registry/namespace/repository@sha256:<64-hex>`。
- 本任务不配置破坏性镜像清理策略。至少保留当前生产 digest、上一成功 digest和相关发布
  清单；现有 ACR 生命周期策略不得被扩大或覆盖。

### R5 — Tencent Cloud production Runner and deployment

- 通过云效网页签发的一次性命令接入非阿里云 Runner；Runner 安装后必须验证服务状态、
  工作目录、任务隔离和停用/卸载路径。
- CI/构建运行在云效构建环境；生产 Runner 只执行经过验证的 release bundle 和 digest 部署。
- Runner 不使用聊天中出现的服务器密码，不在流水线、仓库、镜像、进程参数或日志中保存
  登录密码。生产服务器只获得目标 ACR 仓库的拉取权限。
- 部署必须使用排他锁，校验 release bundle、提交和镜像 digest，再复用现有备份、迁移、
  分阶段启动、健康检查、队列/投递安全检查和证据脚本。
- 生产 Compose 不触发应用镜像构建；生产机无需访问 PyPI。`.env`、私有品牌资料、命名卷、
  Compose profiles、systemd 备份和防火墙状态必须保持兼容。

### R5A — Developer-PC one-command immutable release

- 提供 `make release-prod` 风格入口。真实模式先验证 Docker/Compose、Git/Codeup main、OCI
  repository、现有 Docker credential store、SSH alias/config/known_hosts 和既有部署入口能力；
  缺少 registry/host 等非秘密输入时失败关闭，不猜测地址。
- 入口在临时隔离 worktree 中运行既有锁、后端、前端/API contract、release 和镜像运行时门；
  使用 Docker layer cache，但生产只接收解析并回拉验证的完整
  `repository@sha256:<64-hex>`。
- 入口必须复用 `release_tool.py` 的 bundle/manifest 创建与验证，以及
  `/usr/local/sbin/edu-ai-deploy` 的 root-owned 部署状态机；不得复制备份、迁移、重启、证据或
  回退实现。
- 只通过 strict-host-key SSH 传输校验后的非秘密 bundle/member checksum/manifest；SSH 和
  registry 密码不得作为参数、环境内容或生成文件接收/持久化。优先使用现有 Docker credential
  store 与 OpenSSH config/known_hosts。
- dry-run 不 fetch、不构建、不 push、不传输、不调用远端部署，只验证本地能力、配置形状、
  当前 cached `origin/main` 身份和将执行的非秘密阶段计划。

### R6 — Failure handling and rollback

- 任一质量门、权限预检、备份校验、迁移、健康、队列、投递或证据检查失败时立即停止推进，
  保留安全日志和确切回滚标识。
- 部署前必须自动生成并校验 PostgreSQL、MinIO、品牌资料、运行时代码/配置和旧镜像 digest
  的回滚证据。
- 新应用镜像启动或验收失败时，若迁移未变化或已显式声明向后兼容，自动恢复上一应用
  digest 和运行时 bundle，并重新执行健康检查。
- 数据库备份不得自动恢复，生产流程不得自动执行 Alembic downgrade。迁移失败或不满足
  回退兼容条件时停止并保留现场，交由故障处置流程决定是否恢复。

### R7 — Secrets and auditability

- 云效 PAT、GitHub 备份凭据、ACR 凭据、Runner 注册令牌、生产 `.env` 和服务器身份不得
  提交到 Codeup/GitHub、进入镜像层或出现在日志/任务文档中。
- 流水线 YAML、发布脚本和非秘密资源 ID 进入 Codeup 版本控制；秘密只通过云效受保护凭据
  或服务器本地 `0600` 文件引用。
- 每次发布保存 Codeup commit、ACR digest、release bundle checksum、迁移版本、备份标识、
  前后服务/队列安全计数、回滚结果和最终健康证据。

## Acceptance Criteria

- [ ] `marketingUseOnly/edu-ai-lead-agent` 是私有 Codeup 仓库，完整 Git 历史/引用与迁移源一致，
      `main` 受保护且 Codeup 是本地 `origin`。
- [ ] GitHub 是单向只读备份，不能触发生产或覆盖 Codeup；备份使用仓库级最小权限身份。
- [ ] 项目专属 Flow 流水线可被 CLI 查询，功能分支无生产权限，`main` 满足门禁后自动发布。
- [ ] `make release-prod` 可从 Codeup `main` 的隔离 committed checkout 生成并验证一个 OCI
      digest release；dry-run 对 Git refs、registry、SSH 和生产均无 mutation。
- [ ] Python 运行时依赖可重复解析；指定 Codeup commit 生成一个通过完整质量门和镜像内检查的
      应用镜像。
- [ ] ACR 使用独立项目仓库，同时记录可读标签与不可变 digest；生产九个应用/迁移服务只使用
      同一受验证 digest。
- [ ] 腾讯云 Runner 只执行部署阶段，生产无需访问 PyPI，也不使用聊天密码或共享云账号凭据。
- [ ] 部署前备份与回滚证据均通过 checksum；迁移和服务按依赖顺序执行并通过健康、版本、
      队列、企业微信幂等和受保护数据检查。
- [ ] 新镜像验收失败时，在兼容条件成立的情况下自动恢复上一应用 digest；数据库从不自动
      恢复或 downgrade。
- [ ] `.env`、品牌资料、PostgreSQL、MinIO、命名卷、Compose profiles、systemd timer 和防火墙
      保持不变或通过明确的兼容变更迁移。
- [ ] 后端、前端、API contract、Compose、doctor、脚本语法、敏感信息扫描和完整质量门通过。
- [ ] `frontend-check` 只作为本地/CI 门禁；ACR、release bundle 和生产部署均不包含前端镜像、
      `frontend/dist` 或前端服务。
- [ ] 至少完成一次不发送外部消息、不调用生产 AI provider 的受控自动发布验收，并保存可审计
      的 commit/digest/备份/健康证据。

## Activation Gates and Deferred Inputs

以下是已定义失败行为的外部激活门，不改变目标行为：

- ACR 服务连接 `79934` 必须实际允许访问一个合适实例/地域和本项目独立仓库；否则管理员补权
  后重试，不使用其他项目仓库兜底。
- 当前 PAT 必须拥有新 Codeup 仓库和专属 Flow 的资源级创建/维护权限；若 403，停止并由管理员
  将用户设为对应资源负责人。
- 云效网页需生成一次性非阿里云 Runner 安装命令；命令过期或 Runner 校验失败时不启用生产阶段。
- 组织当前没有 GitHub 服务连接。GitHub 单向备份启用前，需要创建仅覆盖
  `EDLlyc/edu-ai-lead-agent` 的写入身份；不得复用个人全局长期凭据。
- 首版用 commit、digest、锁文件和 release manifest 提供来源证明；密钥签名/cosign 在公司提供
  KMS 或签名身份后另行启用，不阻塞不可变 digest MVP。

## Out of Scope

- 改变抓取、筛选、文案、图片或企业微信业务逻辑。
- 重建 PostgreSQL/MinIO 数据架构，自动恢复数据库或自动执行 Alembic downgrade。
- 构建、发布或部署生产前端镜像/静态资源；前端仅保留本地与 CI 校验用途。
- 增加第二套 GitHub Actions 构建器，或让 GitHub 成为生产触发源。
- 绕过云效/ACR/腾讯云网络安全策略，复用其他项目仓库，或保存共享云账号密码。
- 在本任务中启用破坏性 ACR 镜像清理或建立公司级 Codeup OSS 全量备份策略。
