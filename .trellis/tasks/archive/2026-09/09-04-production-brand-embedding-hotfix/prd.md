# 修复生产品牌 Embedding 与新闻生成链路

## Goal

恢复智谱 `embedding-3/2048` 品牌 RAG，使生产内容 worker 能在既有智谱品牌向量空间中生成文案和素材包；
补齐启动、Compose 与发布前门禁，避免“容器健康但 copy provider 永久不可用”再次发生。修复只保障未来任务，
不自动重放或补发历史终态任务。

## Incident Baseline

- 生产当前为 `AI_PROVIDER_MODE=zhipu`、`BRAND_EMBEDDING_PROVIDER_MODE=auto`、
  `VISUAL_EMBEDDING_PROVIDER_MODE=disabled`。
- 当前 resolver 只把 `auto` 映射到 `fake` 或 Alibaba；智谱 AI + 禁用视觉向量会落到 `disabled`。
- 因此智谱 `embedding-3` 没有失败：content worker 根本没有构造品牌向量 adapter，也没有发起 embedding 请求。
- 生产现有活跃数据中已有 57 条 `zhipu/embedding-3/2048` 向量，可直接复用；另有 1 条 fake 向量，
  继续由严格 provider/model identity 过滤，不伪装为智谱向量。
- 2026-09-02 晚间至 2026-09-04 午间的 18 个 copy run 已终态为
  `review_required/copy_provider_unavailable`。它们不属于安全自动重试范围。
- 生产另有 7 个 `queued/attempt_count=0` copy job，其 run 业务日期为 2026-08-04、05、07、08、09、10、11。
  `_claim` 只处理 `Asia/Shanghai` 当天业务日期，因此它们是不会被新 worker 自然领取的历史冻结 cohort，
  不是本次发布要清空的实时 pending。

## Requirements

### R1 — 恢复显式、兼容的智谱品牌向量身份

- `BRAND_EMBEDDING_PROVIDER_MODE` 支持显式 `zhipu`。
- `auto` 在 Alibaba 视觉向量未启用且 `AI_PROVIDER_MODE=zhipu` 时解析为 `zhipu`；已显式选择 Alibaba、
  fake 或 disabled 的行为保持稳定。
- 智谱品牌向量复用已有受控 `ZhipuEmbeddingModel` transport 与 `GovernanceEmbeddingBrandAdapter`，
  持久化身份保持 `zhipu/embedding-3/2048`，不得把 Alibaba、fake 或历史向量改写成智谱身份。
- 显式 `zhipu` 必须具备受校验的智谱 base URL、API key、模型和 2048 维契约；配置不完整时启动失败，
  不降级到其他 provider。

### R2 — 修正所有运行时装配点

- API、content worker、reindex、real-data MCP 和 eval 的品牌 embedding factory 对同一 resolved provider
  使用同一 transport 语义。
- content worker 在智谱品牌向量模式下使用其已拥有的智谱 HTTP client；Alibaba 继续使用独立视觉 client。
- 启动安全日志只记录 resolved provider/model/dimensions 等非秘密身份，不记录 key、请求文本、向量或 URL。

### R3 — 对自动发送链路 fail fast

- 当内容 worker 承担企业微信自动发送的上游生成职责时，若 AI 文案 provider 或品牌 embedding provider
  不可用，Settings/启动必须失败；不得启动一个只会把后续任务写成 `copy_provider_unavailable` 的“健康”worker。
- selection-only / provider-free 的本地默认场景继续允许，不强迫开发和测试环境产生模型调用。
- `scripts/doctor.sh` 和 Compose 契约检查品牌 provider 配置在 API/content services 间一致，并验证自动发送
  场景存在可用的 resolved provider。

### R4 — 回归、发布与生产验证

- 增加 resolver、配置错误、factory 身份、API/content-worker client wiring 和 Compose/doctor 契约测试。
- 运行相关 backend 单元/契约测试、lint/type-check、Compose render、doctor 静态门禁及 release contract tests。
- 仅提交本热修复增量，保留当前工作区其他 WIP；推送 GitHub 后通过受控 release pipeline 部署生产。
- 部署后允许一次有界、无持久化写入的智谱 embedding smoke：只输出 provider/model/dimension/成功状态；
  不输出查询文本、向量、凭据或 provider body。
- 当前无可用 OCI registry 时，使用新建且仅属于本任务的 checksum-bound offline
  builder/validator/operator/fake harness；不得复用历史任务 operator，也不得把 transport tag 当生产身份。
- 离线 builder 必须先做能力路由：`buildx` 可用时保持原有严格路径；仅当客户端明确报告命令不存在时，才允许
  使用已审核的本地 Docker legacy builder 与 `moby` containerd export。legacy build/export/canonicalization 任一
  步骤失败都必须终止，不得在一次构建失败后静默切换实现或复用未知本地 tag。
- legacy export 只接受完整的单 manifest `linux/amd64` 图；将已验证的 Docker layer media type 映射为 OCI
  media type后重算 manifest/index digest、size、platform 与 transport annotations，且保持 config/layer bytes
  不变。nested index、dangling blob、链接成员或异常本地 Docker/context/containerd 能力必须 fail closed，
  最终产物仍需通过同一个严格 OCI validator，不能为 fallback 放宽验收口径。
- canonical index 必须使用 containerd 可加载的两类精确 annotation：规范化完整 name 与短 ref name。legacy
  构建产生的同名 raw tag 只在已证明为本次新建时于 load 前移除，随后要求 `docker image load` 重新创建 tag；
  load 返回 0 但未创建 tag、残留 raw tag 或 graph 外摘要都必须失败，不得把旧 tag 的 `.Id` 当作归档转换。
- 加载同一严格 OCI graph 后，兼容 Docker classic store 将 `.Id` 表示为 config digest、containerd image store
  将 `.Id` 表示为 manifest digest 的差异；只接受这两个已验证 digest 之一，并继续要求精确 RepoDigest 与
  reference inspect 指向同一运行时 ID。服务收敛必须绑定实际加载得到的 ID，不接受任意第三种身份。
- 离线 operator 必须保留 weekly production 拓扑并让全部 12 个应用服务收敛到同一不可变镜像；部署后只读
  验证 release identity、容器 health/restart、resolved brand provider 和未来任务 readiness。
- baseline 必须固定 `Asia/Shanghai`、capture 当天业务日期与 `content_max_attempts=3`，严格要求当天可领取、
  当天任意 queued/running/retry、全局 running 及未来 copy 队列均为 0；7 条历史冻结 job 只以精确数量和
  不暴露 UUID/正文的稳定 SHA-256 绑定。首次 capture 也必须拒绝把日期集合、`queued` 状态或
  `attempt_count=0` 已漂移的七条记录重新确认为合法基线；发布全程不得新增、领取、更新或删除。

## Acceptance Criteria

- [x] `Settings(ai_provider_mode="zhipu", brand_embedding_provider_mode="auto", ...)` 解析为 `zhipu`，
  `brand_embedding_provider/model/dimensions` 与生产 57 条活跃向量身份兼容。
- [x] 显式 `zhipu`、Alibaba、fake、disabled 及非法组合均有测试，且不会跨 provider 静默降级。
- [x] `create_brand_embedding_model` 的智谱分支复用受控 adapter，测试证明一次调用、2048 维、正确身份和
  provider request metadata 契约。
- [x] API 与 content worker 在智谱模式传入 owned 智谱 client；Alibaba 路径和 provider-free 默认不回归。
- [x] 自动企业微信链路无法生成 copy 时在启动/doctor 阶段失败，而不是消费业务任务后才终态失败。
- [x] 相关单元、契约、静态检查和 release pipeline tests 全部通过。
- [x] Git 提交仅包含本任务增量；GitHub 分支/主线具备可追溯 commit，生产 release marker 与 OCI revision
  一致。
- [x] 生产一次有界智谱 `embedding-3` smoke 成功，且未写数据库、未入队、未发送任何消息。
- [x] 部署后服务健康且 resolved provider 为 `zhipu`；不自动 replay 18 个历史 copy run。
- [x] 7 条历史冻结 copy job 的数量和稳定摘要在锁前、锁内、停服后、迁移前、启动前、最终及回滚服务重启
  前后均不变；日期跨界或出现当天/未来可运行 copy job 时 fail closed。
- [x] 生产受保护 `.env` 内容和校验和保持不变；`auto` 的 resolved identity 通过运行时读回证明为
  `zhipu/embedding-3/2048`，不在镜像事务之外引入配置漂移。
- [x] 无 `docker buildx` 的审核主机能经预检选择 legacy/containerd 路径，并由 harness 覆盖能力路由、legacy
  argv/env、reference normalization、OCI graph canonicalization、loadable annotation、raw-tag freshness、
  危险归档拒绝和本地 candidate cleanup；buildx 存在但执行失败时不得 fallback；Docker
  classic/containerd image store 的两种严格 `.Id` 语义均通过，tag 缺失及任意 graph 外 ID 被拒绝。
- [x] candidate 容器内完整源码摘要必须逐文件输出 canonical newline 分隔行并与 release worktree 的完整
  `image-source.sha256` 字节相等；不得因 shell/Python 转义把多行摘要折叠为字面量 `\n`，不得缩小源码范围，
  且 host/image 两侧均须在输出前拒绝可用换行或制表符注入摘要记录的非 canonical path；排序身份必须是
  manifest 中实际序列化的 relative POSIX path string，不能依赖 `Path` 的分段比较语义；builder 与
  production operator 必须由可执行 parity test 证明使用完全相同的 probe argv，避免其中一份单独回归。
- [x] operator 在 preflight 加载 candidate 后、quiesce 前任一门禁失败时，只能清理本次从 absent transport tag
  加载且仍绑定同一已验证 image ID 的 inactive candidate；若 tag 漂移、Docker 容器枚举/inspect 失败或任意
  running/stopped container 使用该 ID，必须放弃清理。精确预加载 candidate 可安全复用但不归本次 operator
  所有，既不得删除它，也不得触碰 baseline running image。
- [x] production operator 允许共享 Compose 为本地开发保留的精确 `backend/Dockerfile` build metadata，但必须
  逐服务绑定该继承值并拒绝显式 `pull_policy`；所有 `compose create/up` 路径必须使用 `--no-build`，并由运行时
  wrapper 与静态全路径枚举双重拒绝任何遗漏；不支持该参数的迁移 `run` 必须拒绝 `--build` 及赋值形式，避免
  生产根据现场源码隐式构建或覆盖审核镜像。
- [x] stage validator 必须把 `image-source.sha256` 与完整 source archive 的 backend 镜像范围逐 path/hash
  精确匹配，并从完整 Alembic revision 源码声明中确认 `20260901_0042` 唯一存在；不得以手写迁移文件名代替
  revision identity；AST 解析前后必须限制迁移文件数、单文件 bytes 和节点数，并拒绝动态或重复绑定；builder 对
  candidate 运行 `alembic heads` 的 reported-head 门禁保持不变。
- [x] 纯 stage validator 必须在镜像加载前比较 candidate source manifest 与 production baseline 的重叠路径，
  拒绝遗漏、类型变化和 executable-class 漂移；operator 在只读 preflight 及 release lock 内、创建 one-shot
  attempt marker 前重复该门禁。仅由 `python`/`python3` 调用的 `deploy.py` 与 `release_tool.py` 必须在 Git 中保持
  non-executable，不能通过放宽全部 mode 漂移来适配生产现场的 `0600`。
- [x] builder 对 staged baseline 的早期校验和 OCI graph 的 pre-load 校验均不得改变最终 stage：每一次从
  stage 导入或执行验证器时都必须禁止 Python 写入 bytecode，避免生成额外 `__pycache__` 成员；最终 validator 的
  root-owned physical regular、`0600` 与精确 member-set 契约保持不变，不得通过忽略或删除未知成员绕过。

## Out of Scope

- 自动重放、重试或补发 2026-09-02 至 2026-09-04 的历史新闻。
- 更新、删除或重放 7 条历史冻结 copy job；它们仅作为只读生产状态被发布门禁绑定。
- 把 fake 或 Alibaba 向量原地改写成智谱向量，或大规模重建已有 57 条智谱向量。
- 启用 Alibaba/Qwen 视觉 embedding、替换图片识别模型，或改变 `GLM-5V-Turbo` 图片 Reviewer 方案。
- 触发企业微信发送、微信公众号发布/群发，或用 provider smoke 代替真实投递终态证据。

## Rollback Boundary

- 代码/镜像可回滚到前一 release；回滚不会删除或改写品牌向量。
- 若新 worker 启动门禁失败，保持消息发送停止并回滚镜像；不得通过禁用门禁或伪造 provider identity
  强行继续。
- 生产 smoke 若失败，只记录安全错误类别并回滚/停止发布，不进行无限重试。

## Notes

- 事故根因是配置解析与运行时装配缺陷，不是模型额度、账号、网络或智谱服务故障。
