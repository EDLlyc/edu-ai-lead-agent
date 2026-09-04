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
- 离线 operator 必须保留 weekly production 拓扑并让全部 12 个应用服务收敛到同一不可变镜像；部署后只读
  验证 release identity、容器 health/restart、resolved brand provider 和未来任务 readiness。

## Acceptance Criteria

- [ ] `Settings(ai_provider_mode="zhipu", brand_embedding_provider_mode="auto", ...)` 解析为 `zhipu`，
  `brand_embedding_provider/model/dimensions` 与生产 57 条活跃向量身份兼容。
- [ ] 显式 `zhipu`、Alibaba、fake、disabled 及非法组合均有测试，且不会跨 provider 静默降级。
- [ ] `create_brand_embedding_model` 的智谱分支复用受控 adapter，测试证明一次调用、2048 维、正确身份和
  provider request metadata 契约。
- [ ] API 与 content worker 在智谱模式传入 owned 智谱 client；Alibaba 路径和 provider-free 默认不回归。
- [ ] 自动企业微信链路无法生成 copy 时在启动/doctor 阶段失败，而不是消费业务任务后才终态失败。
- [ ] 相关单元、契约、静态检查和 release pipeline tests 全部通过。
- [ ] Git 提交仅包含本任务增量；GitHub 分支/主线具备可追溯 commit，生产 release marker 与 OCI revision
  一致。
- [ ] 生产一次有界智谱 `embedding-3` smoke 成功，且未写数据库、未入队、未发送任何消息。
- [ ] 部署后服务健康且 resolved provider 为 `zhipu`；不自动 replay 18 个历史 copy run。
- [ ] 生产受保护 `.env` 内容和校验和保持不变；`auto` 的 resolved identity 通过运行时读回证明为
  `zhipu/embedding-3/2048`，不在镜像事务之外引入配置漂移。

## Out of Scope

- 自动重放、重试或补发 2026-09-02 至 2026-09-04 的历史新闻。
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
