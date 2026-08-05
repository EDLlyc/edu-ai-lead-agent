# 文案驱动公司 IP 生图技术方案

## 1. 目标与结论

将现有的“单张默认参考图 + 文案中的自由图片提示词”升级为：

```text
已通过审计的文案
    -> 结构化视觉 brief
    -> 受控选择公司 IP 素材
    -> 组装品牌提示词与主题提示词
    -> 多参考图生图
    -> 图片质量验证
    -> MinIO 图片与素材包
```

生成图片必须同时满足三件事：

1. 内容与当天选题、文案中的科学主题一致；
2. 角色、颜色、动作和画面气质属于赛先生科学品牌；
3. 选中的 IP 素材、提示词版本和验证结果可以复现和审计。

不新增 Redis、Celery 或第二个向量数据库。品牌文字继续使用 PostgreSQL + pgvector，
视觉素材使用受控清单和结构化标签检索。

## 2. 当前问题

当前正式链路存在四个限制：

- `IMAGE_REFERENCE_ASSET` 只支持一张默认参考图，不能根据文案选择“小赛”和“赛先生”的
  不同动作素材；
- `ImageGenerationRequest` 只有一个 `reference_image` 字段，无法表达角色参考、动作参考
  和风格参考的不同作用；
- 文案模型输出的 `image_prompt` 只是普通文本，没有受到公司 IP、品牌配色、构图和文字
  渲染规则的统一约束；
- 图片指纹目前只记录一个参考图摘要，无法说明这次生成实际使用了哪些 IP 素材。

因此上一张图片虽然主题是机器人，但没有可靠地继承公司 IP 视觉。

## 3. 视觉素材分层

将素材分成三种角色，不能混用：

| 素材角色 | 来源 | 用途 |
| --- | --- | --- |
| `identity_reference` | `private/brand-materials/05-visual-assets` 中的小赛、赛先生透明 PNG | 锁定角色外形、脸部特征、服装、比例和品牌色 |
| `action_reference` | 显微镜、讨论、探测、看书、宇航员等 IP 动作图 | 为模型提供动作、道具和主题场景参考 |
| `style_reference` | 已批准的 `output/imagegen` 示例或品牌优秀配图 | 锁定科普信息图构图、蓝白橙配色、光线和信息层级 |

`style_reference` 只表达构图和视觉语言，不作为角色身份的唯一依据。角色身份必须来自
正式 IP 素材。未经批准的历史图和模型输出不得自动进入生产参考集。

## 4. 结构化视觉 brief

在文案草稿中增加受控的视觉字段，字段值只能使用允许的枚举或短文本：

```json
{
  "visual_category": "robotics",
  "learning_goal": "让家长理解机器人如何通过尝试和反馈改进动作",
  "scene": "赛先生科学实验室",
  "main_action": "小赛观察机器人手臂完成一次动作调整",
  "characters": ["xiao-sai", "sai-xiansheng"],
  "asset_tags": ["robotics", "experiment", "observation"],
  "reference_roles": ["identity_reference", "action_reference", "style_reference"],
  "render_text_mode": "short_labels"
}
```

模型只能返回素材标签和动作描述，不能返回文件路径、URL 或任意品牌资产 ID。应用层根据
标签从本地清单选择真实文件，避免模型伪造或越权引用素材。

默认 `render_text_mode` 为 `short_labels`：图片只渲染短标题或少量流程标签，完整朋友圈
文案仍然放在文字消息中。这样可以降低生图模型中文长文本错误；若后续确认模型稳定，再
增加 `exact_short_copy` 模式。

## 5. 素材清单与选择

扩展现有 `visual-assets.manifest.json`，每个资产增加人工确认的结构化标签：

```json
{
  "asset_id": "sha256",
  "relative_path": "05-visual-assets/小赛探测.png",
  "characters": ["xiao-sai"],
  "roles": ["identity_reference", "action_reference"],
  "topics": ["robotics", "ai", "experiment"],
  "poses": ["observe", "explore"],
  "approved": true,
  "priority": 80
}
```

选择器采用确定性评分，不把图片路径交给模型：

1. 先按 `approved`、文件类型、大小、校验和和品牌状态过滤；
2. 根据 `visual_category`、`asset_tags`、角色要求和动作要求匹配标签；
3. 必须优先选择一组角色身份素材，再选择动作素材和风格素材；
4. 使用稳定的优先级和 `asset_id` 作为并列排序，保证同一输入可复现；
5. 没有足够匹配素材时使用受控默认组合，并在素材包标记 `fallback_reference=true`；
6. 连默认组合也不可用时，不调用生图，保留为可人工查看的失败状态。

首批标签示例：

- 机器人、人工智能、实验、动手、观察：小赛探测、小赛和赛先生讨论、赛先生-显微镜；
- 天文、宇宙、空间站：天文-赛先生、赛先生-宇航员、赛先生小赛-空间站；
- 阅读、思考、科学方法：小赛看书、小赛和赛先生思考、小赛和赛先生在时光机里看书。

## 6. 生图请求改造

将图片端口从单参考图改为有角色的多参考图：

```python
@dataclass(frozen=True, slots=True)
class ImageReference:
    asset_id: str
    role: Literal["identity_reference", "action_reference", "style_reference"]
    filename: str
    body: bytes
    sha256: str
```

`ImageGenerationRequest` 使用有序的 `tuple[ImageReference, ...]`。供应商适配器按能力
发送 2-3 张参考图：

- Comfly/OpenAI-compatible：传入 `image` 数组；
- 其他兼容供应商：映射到其 `reference_images` 或 `image_urls` 数组；
- 供应商只支持一张图时，选择身份素材作为主参考，并把动作/风格要求写入提示词，同时
  记录 `reference_mode=single_fallback`。

每次请求继续保留 HTTPS、域名校验、下载大小、媒体类型、PNG 签名和分辨率检查。IP 素材
只从容器内只读挂载读取，不生成公网 URL。

## 7. 提示词组装

不要直接把模型返回的 `image_prompt` 原样发送给供应商。应用层使用版本化模板组装：

```text
Use case: scientific-educational
Brand identity: preserve the supplied Sai Xiansheng and Xiaosai IP identities exactly.
Selected references: identity..., action..., style...
Topic: <当天选题>
Learning goal: <visual brief.learning_goal>
Scene and action: <visual brief.scene + main_action>
Composition: square parent-facing social post, clear focal subject, readable hierarchy.
Brand visual language: deep science blue, clean white, restrained orange accents,
polished educational 3D illustration, warm and trustworthy.
Text policy: <render_text_mode and exact short labels if enabled>
Avoid: invented logos, extra brand marks, watermark, QR code, long unverified text,
real child faces, promotional promises, unrelated objects, generic replacement characters.
```

主题和文案只负责决定“讲什么、画什么动作”；品牌模板负责决定“角色长什么样、画面怎么
呈现”。提示词模板和视觉 brief 都要进入版本指纹。

## 8. 持久化与素材包

在现有 `image_artifacts` 之外增加 `image_artifact_references`，每行保存：

- image artifact ID、asset ID、reference role、ordinal；
- 资产 SHA-256、manifest schema version、选择器版本；
- 安全的相对路径或文件名；
- 是否为 fallback reference。

`image_artifacts` 增加或版本化保存：

- `visual_brief_version`；
- `asset_selector_version`；
- `reference_mode`；
- `prompt_version`、`pipeline_version`；
- 由选题、草稿、视觉 brief、资产摘要和最终提示词共同生成的 request fingerprint。

素材包详情页增加“视觉 brief”和“本次使用的 IP 参考素材”区域，但不暴露 MinIO object
key、供应商临时 URL、完整隐藏提示词或 API 密钥。

## 9. 验证与失败处理

固定顺序：

1. 校验视觉 brief schema、资产数量、资产状态和输入摘要；
2. 生成图片并完成现有媒体、尺寸、签名和下载安全校验；
3. 检查图片主题是否与视觉 brief 一致，不能只检查 HTTP 成功；
4. `short_labels` 模式下用 OCR 检查仅出现允许的短文本；
5. 对角色身份、主题相关性、品牌风险和明显错误进行视觉审计；
6. 失败最多自动修复一次，修复时只改变明确失败项；
7. 仍失败则保留图片和审计记录，状态为可人工查看，不强行进入可发送状态。

第一版机器检查先覆盖确定性项和 OCR；视觉身份审计通过独立的 `ImageQualityAuditor`
端口保留扩展位，避免把图片模型本身当作唯一审计者。

## 10. 分阶段实施

### 第一步：素材清单和标签

- 完善 IP/动作/风格素材目录和 manifest schema；
- 为现有公司 IP 文件建立人工确认标签；
- 将确认过的 `output/imagegen` 示例登记为 style reference；
- 增加清单构建、路径安全、校验和和选择器单元测试。

验收：给定机器人、天文、阅读三个视觉 brief，选择结果稳定且能解释命中原因。

### 第二步：视觉 brief 和提示词组装

- 扩展文案生成结构化 schema；
- 增加视觉字段的确定性校验和版本；
- 实现品牌模板与主题模板组装器；
- 保留旧 `image_prompt` 作为兼容输入，但正式生图只使用组装后的 prompt。

验收：同一文案能生成相同的视觉 brief、参考素材集合和最终 prompt fingerprint。

### 第三步：多参考图适配

- 扩展 image port、Comfly payload 和必要的其他 provider mapping；
- 记录每张参考图的角色和摘要；
- 增加供应商只支持单图时的明确 fallback；
- 更新幂等指纹，避免复用旧的错误图片。

验收：Mock provider 能验证多图顺序、角色、payload、幂等 replay 和单图 fallback。

### 第四步：图片验收和素材包展示

- 增加短文本 OCR、视觉 brief 相关性和图片审计结果；
- 更新前端显示视觉 brief、参考 IP 和失败原因；
- 保持一次自动修复和不自动发布边界。

验收：成功、供应商失败、参考素材缺失、OCR 失败、修复后失败五种状态均可查看。

### 第五步：真实端到端验证

- 使用一个真实科技/机器人选题生成新文案和新图片；
- 不复用旧的 accepted image 请求，使用新的 prompt/pipeline 版本；
- 将图片保存到 `output/`，同时验证 MinIO、数据库、API 下载和前端展示；
- 检查生成图确实使用了公司 IP，而不是泛化角色；
- 记录成本、耗时、供应商请求 ID 和最终质量结论。

## 11. 配置与回滚

建议新增配置：

```env
IMAGE_REFERENCE_SELECTION_ENABLED=true
IMAGE_REFERENCE_MANIFEST=private/brand-materials/visual-assets.manifest.json
IMAGE_MAX_REFERENCE_ASSETS=3
IMAGE_STYLE_REFERENCE_ENABLED=true
IMAGE_RENDER_TEXT_MODE=short_labels
IMAGE_ASSET_SELECTOR_VERSION=visual-asset-selector-v1
IMAGE_VISUAL_BRIEF_VERSION=visual-brief-v1
```

通过 `IMAGE_REFERENCE_SELECTION_ENABLED=false` 可以回到旧的单参考图模式。新旧模式使用
不同的 prompt/pipeline version 和 request fingerprint，不覆盖历史图片，也不修改已经
完成的素材包。

## 12. 最终验收标准

- 机器人、人工智能、天文、阅读等主题能自动选择对应的公司 IP 素材；
- 生成请求中包含真实选中的 IP 图片，且数据库能追溯每一张参考图；
- 图片构图和视觉语言接近已批准的 `output/imagegen` 示例；
- 图片主题与文案一致，完整文案不被错误地塞进图片；
- 同一输入幂等返回同一图片，不同参考素材或 prompt 版本必然生成新指纹；
- 失败最多修复一次，失败结果不进入自动分发；
- 全部现有后端、前端、Doctor、Compose 和图片适配测试保持通过；
- 企业微信分发只读取最终素材包，不绕过图片审计和人工确认。
