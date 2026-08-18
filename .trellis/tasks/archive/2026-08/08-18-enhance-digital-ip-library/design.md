# 完善数字 IP 资产库：技术设计

## 1. 设计目标

在不增加生产部署、线上调用和数据库迁移的前提下，把现有品牌知识工作台升级为一套可本地演示的数字 IP 资产视图。新能力应复用：

- 品牌文档不可变版本和激活状态；
- Brand Knowledge 的全文检索 + pgvector RRF；
- `VisualAssetCatalog` 的审核、角色、动作、场景和 checksum 契约；
- `retrieve_brand_context` 的品牌/事实分离；
- 现有 React Query、生成 OpenAPI 类型和前端无障碍模式。

本轮不新建通用数字 IP 平台，也不建立第二套知识存储。

## 2. 边界与总体结构

```text
active brand documents ─┐
                        ├─> DigitalIpProfileProjection ─> BrandKnowledgePanel
local visual manifest ──┘             │
                                      ├─> existing brand-context retrieval
                                      ├─> browser-local feedback ledger
                                      └─> deterministic local eval report
```

### 2.1 后端边界

- 在品牌知识域增加只读的数字 IP 投影类型和服务，不增加新的持久化表。
- API 增加一个只读 profile endpoint；它聚合当前激活的品牌文档元数据和本地视觉 manifest 的安全摘要。
- 文档规则正文仍由现有 Brand Knowledge retrieval 返回；profile endpoint 不复制完整文档正文。
- 视觉素材继续由现有 `VisualAssetCatalog` 解析和校验。API 只返回允许展示的字段，不返回 `relative_path`、本地绝对路径、MinIO key 或图片字节。
- retrieval endpoint 和 `retrieve_brand_context` Tool 保持现状；数字 IP 页面继续调用现有 `POST /brand-context/retrieve`，不复制 RRF 查询。

### 2.2 前端边界

- 在现有 `features/brand` 内加入数字 IP 人设概览、视觉资产摘要、检索解释和本地反馈，不另起一套应用。
- 人设卡的动态语气/安全/视觉标签从 active version 元数据聚合；固定身份仅包含现有 `profile_id`、展示名、角色标识、受众和支持的内容场景。
- 反馈存储使用带 schema version 的 localStorage ledger。它是单浏览器、本地、可清除的作品集反馈，不冒充生产持久化或模型训练数据。
- 反馈记录只包含 query fingerprint、返回的 chunk/version IDs、decision、reason code 和时间，不保存完整品牌正文。

### 2.3 Eval 边界

- 新增 provider-free 的确定性数字 IP contract eval，使用脱敏 fixture 和现有 typed projection/tool result。
- case 覆盖定位、语气、禁用表达、安全、视觉五类意图。
- 输出案例通过数、预期类型/标签覆盖率、禁用规则命中率和 `evidence_eligible` 违规数。
- 报告明确标注为 fixture contract conformance，不代表真实 embedding 或模型准确率。

## 3. 数据契约

### 3.1 Profile projection

`DigitalIpProfileResponse` 建议包含：

- `profile_id`: 稳定标识，本轮唯一值；
- `display_name`: “赛先生 × 小赛”；
- `brand_slug`: 复用当前单品牌标识；
- `characters[]`: 稳定角色 slug + 中文显示名；
- `audiences[]` 与 `channels[]`: 本轮展示用途，不代表鉴权角色；
- `active_document_count`、`active_version_ids[]`、`document_kinds[]`；
- 从 active versions 聚合后的 `tone_tags[]`、`safety_tags[]`、`visual_tags[]`；
- `visual_catalog_version` 和 bounded `visual_assets[]`；
- `profile_fingerprint`: 由固定身份、active version IDs、聚合标签和 catalog version 确定性生成。

`DigitalIpVisualAssetResponse` 只允许：

- asset ID/checksum 的短安全标识；
- display name、asset kind、角色、动作、主题和场景标签；
- width/height、approved、priority；
- 不允许路径或原图访问地址。

### 3.2 Feedback ledger

前端记录结构：

- `schemaVersion`；
- `id`、`createdAt`；
- `queryFingerprint`；
- `profileFingerprint`；
- `chunkIds[]`、`versionIds[]`；
- `decision`: `accepted | rejected`；
- `reason`: 受控枚举，例如 `relevant`、`tone_match`、`missing_rule`、`irrelevant`、`conflicting_rule`；
- 可选短备注，长度受限且仅保存在浏览器。

存储设置总条数上限，解析失败时丢弃损坏记录而不是让页面崩溃。

## 4. 数据流

### 4.1 Profile

1. API 读取已有品牌文档列表投影，只选 active document 的 active ready version。
2. API 通过现有 catalog loader 读取 `IMAGE_ASSET_MANIFEST`。
3. 只保留 `approved=true` 且角色属于 `sai-xiansheng`/`xiao-sai` 的 bounded 元数据。
4. 服务确定性聚合标签、版本和 catalog fingerprint。
5. 前端通过生成类型展示结构化人设卡、知识状态和视觉资产摘要。

若 manifest 缺失或不可用，profile 仍返回文字知识状态，并以 typed `visual_catalog_status=unavailable` 表示，不伪造视觉资产。

### 4.2 Retrieval and feedback

1. 用户在现有召回测试中输入文案场景。
2. 前端调用现有 brand-context endpoint。
3. UI 展示文档/版本、类型、标签、融合分数及 `evidence_eligible=false`。
4. 用户可对本次结果整体采纳或拒绝并选择原因。
5. localStorage ledger 保存安全 ID 和决策；它不调用后端写接口。

### 4.3 Eval

1. runner 加载 versioned fixture cases。
2. 通过 typed fixture 结果执行规则覆盖判定。
3. 生成稳定 JSON/Markdown 摘要；动态时间和本地路径不进入 canonical artifact。
4. 任一品牌项被标为事实证据时 eval 必须失败。

## 5. 兼容性与安全

- 无 Alembic migration，无现有表结构变化。
- 原有 Brand API 保持向后兼容；新增 endpoint 不改变现有 response。
- 不改变 copy-generation 的 Brand RAG query、RRF 参数或激活语义。
- 不注册发布、发送、任意 URL、shell 或文件写入 API。
- 私有 visual manifest 只在 API 进程内读取；前端无法获得路径或原始图片。
- production 部署完全不在本任务中；代码改动完成后也不执行服务器操作。
- 现有工作区修改均视为用户资产，实施仅修改任务相关文件。

## 6. 取舍

- 选择“投影 + browser-local feedback”而不是新数据库表：满足本地作品集和反馈演示，降低迁移与发布风险；代价是不支持跨浏览器反馈历史。
- 选择单 IP 完整链路而不是通用多 IP CRUD：演示更聚焦；通过稳定 ID 和关联字段保留未来扩展空间。
- 选择元数据视图而不是提供私有图片预览：保护私有素材路径与字节；视觉能力仍可通过角色、动作、场景和审核元数据证明。
- Eval 只证明确定性契约，真实检索质量评估延期到可控的真实 embedding 数据集。

## 7. 回滚

本任务没有数据库或线上状态。回滚只需移除新增只读 route/projection、前端视图、localStorage namespace 和 eval 文件，并重新生成原有 OpenAPI/client；不会影响现有品牌文档、视觉 manifest 或业务流程。
