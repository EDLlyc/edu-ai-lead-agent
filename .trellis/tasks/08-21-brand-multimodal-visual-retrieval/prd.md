# 品牌多模态图文检索

## Goal

为现有数字 IP 视觉资产库增加可审计的跨模态检索能力，使一段文案、视觉简报或一张图片
能够召回语义匹配的已审批品牌图片，同时不削弱人物身份、用途角色、文件完整性和字节预算等
现有硬规则。

## Background and confirmed facts

- 当前私有视觉目录包含 41 张经过 manifest 校验的 PNG；目录加载会验证相对路径、符号链接、
  SHA-256、尺寸、媒体类型和审批状态。
- 当前 `AssetSelector` 使用人物、角色、主题/动作/场景标签、优先级、新颖性和字节预算进行
  确定性选择，没有图片向量索引，也不会调用 Embedding 模型。
- 品牌文本知识库已有独立的 2048 维 pgvector 数据和冻结的 provider/model/version 边界；
  多模态图片向量不得覆盖、混写或重新解释这些历史文本向量。
- 已使用普通百炼按量付费凭证完成一次合成图文探测：`qwen3-vl-embedding` 返回两个独立、
  有限且归一化的 2048 维向量。凭证仅存在于本地 mode-0600、Git 忽略的私密文件中。
- 生产发布、业务重放、企业微信发送和真实资料自动索引均未获得授权。

## Requirements

### R1. 独立且版本化的视觉向量能力

- 新增独立的视觉资产 Embedding 端口和百炼适配器，固定使用
  `qwen3-vl-embedding`、独立向量模式和 2048 维输出。
- provider、model、dimensions、input-policy、catalog version、asset checksum 与请求指纹必须
  进入不可变派生身份；未知或混合身份 fail closed。
- 新增 `brand-visual-embedding-input-v2`：验证原始 PNG 后，在内存中执行确定性、有限次数的
  尺寸归一化和无元数据 PNG 重编码，使 Base64/JSON 请求体稳定低于供应商边界。原始素材文件、
  manifest 和审批身份不得被修改；持久化区分原始 asset checksum 与实际 embedding input hash。
- 历史 v1 向量保留且只按 v1 身份读取；v2 不得与 v1 混合形成完整索引。所有当前资产必须用同一
  v2 策略重新派生后，才允许语义排序进入自动配图。
- 任何日志、API、任务证据和错误不得包含 API Key、Workspace、私有路径、图片字节、原始向量、
  provider body 或 request ID。

### R2. 视觉资产索引

- 为 manifest 中的 approved PNG 建立独立的 2048 维视觉资产索引；记录资产摘要、catalog/version
  身份、模型身份和安全用量，不复制私有图片到数据库。
- 索引前后都要重验 manifest、物理文件、符号链接、校验和和尺寸；单资产失败不得产生 ready
  向量，也不得污染其他资产的不可变结果。
- 重复运行对同一派生身份幂等；catalog/checksum/model/input-policy 变化时产生新派生，不覆盖旧行。

### R3. 文搜图与图搜图

- 文本查询和图片查询使用同一模型/维度生成查询向量，并仅在相同 provider/model/dimensions/
  input-policy 的 ready 资产集合内做 cosine 检索。
- 返回结果只包含安全资产引用、角色、类型、批准状态、目录版本和有界相似度；不得返回路径、
  文件名回退、图片字节或向量。
- 查询有长度、图片大小、结果数量、超时、并发和单次尝试上限；provider 不可用时返回稳定 typed
  unavailable，不暗中降级为不同向量空间。

### R4. 混合选择边界

- 人物身份覆盖、用途角色、approved 状态、文件完整性、引用数量和字节预算始终是硬门；语义向量
  只能在硬门之后排序，不能让不合格资产进入候选。
- 保留现有 selector 的可回放结果。多模态策略使用新版本和独立 feature flag；关闭时字面保持
  现有行为。
- 用户已决定第一版直接进入自动配图：功能开启且兼容视觉索引 ready 时，语义相似度作为每个
  硬规则合格角色候选集的主要排序信号，现有规则分数、优先级、新颖性和稳定资产 ID 用于次级
  排序与确定性 tie-break。
- 语义结果必须保留可解释的规则分数、相似度和最终排序来源，但不得把模型相似度描述为事实证据。
- 当查询调用失败、超时、身份不匹配或当前 catalog 尚未形成完整 ready 索引时，记录稳定的
  `semantic_unavailable` 并字面回退现有规则选择；不阻断个人项目的图片生成。

### R5. 凭证与运行方式

- 不把现有 CSV、API Key 或 Workspace 信息复制进 `.env.example`、测试、任务文档、镜像或 Git。
- 运行时仅从 Secret 类型环境变量读取普通百炼凭证；测试使用 fake/recorded adapter，默认不联网。
- 提供本地、显式 opt-in 的索引/查询入口和确定性离线评测；测试和构建默认 provider-free。

## Acceptance Criteria

- [ ] 纯文本与合成图片查询均能返回相同 2048 维契约下的安全候选；provider/model/dimension
      不匹配会 typed fail closed。
- [ ] 已审批资产可幂等索引，checksum/catalog/model/input-policy 变化会产生新派生，失败不会留下
      ready 脏数据。
- [ ] 大 PNG 归一化测试证明输出仍是有效 PNG、像素/尺寸有界、无元数据、请求 envelope 有界、
      同输入字节稳定；原始文件和 manifest 不变，v1/v2 查询不会混用。
- [ ] 身份、角色、approved、文件完整性和字节预算测试证明向量分数无法绕过硬规则。
- [ ] feature flag 关闭时现有视觉选择 snapshot/指纹/顺序保持不变。
- [ ] API/CLI 不泄露路径、文件名、图片字节、向量、凭证、Workspace、request ID 或 provider body。
- [ ] 使用脱敏 fixture 的检索评测覆盖文搜图、图搜图、同义查询、无关查询、稳定 tie 和 provider
      failure；默认测试不调用外部服务。
- [ ] Ruff、strict mypy、聚焦/真实 PostgreSQL 集成、迁移、API drift、Compose/Doctor、diff 与 secret
      gates 通过；无部署、业务重放或发送。

## Out of Scope

- 替换现有品牌文本 Embedding、修改其历史向量空间或重建品牌文档索引。
- Qwen3-VL-Reranker、视频索引、PDF 页面图像索引、OCR 重跑、图片生成模型变更。
- 上传未审批图片、公开私有素材、自动发布、生产部署或服务器配置修改。
- 把视觉相似度当作新闻事实证据或品牌事实证据。

## Resolved Product Decisions

- 第一版不是影子模式；在本地个人项目中，多模态分数直接参与自动配图排序。
- 百炼查询失败、超时或视觉索引未 ready 时自动回退现有规则，并审计
  `semantic_unavailable`；不会终止配图。
- 用户已授权实现 v2 归一化，并在代码与独立检查通过后重新索引全部 41 张已审批素材。每个 v2
  派生最多一次供应商请求；若仍失败，不自动重试。
