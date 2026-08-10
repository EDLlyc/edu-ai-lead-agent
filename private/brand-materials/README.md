# 赛先生品牌资料（内部）

这里存放用于品牌 RAG、朋友圈文案生成和图片生成的原始参考资料。

## 目录

- `01-brand-profile/`：品牌理念、品牌定位、公司与产品基本信息
- `02-copy-examples/`：优秀文案、历史朋友圈文案和反例
- `03-image-examples/`：历史配图、优秀案例和不推荐案例
- `04-brand-rules/`：语气规范、固定用语、禁用词和风险要求
- `05-visual-assets/`：Logo、品牌色、字体和其他视觉素材

## 使用说明

1. 收到的原始资料直接放入对应目录，不需要提前改名或整理。
2. 文件可使用 PDF、DOCX、TXT、Markdown、PNG、JPG、JPEG 或 WebP 格式。
3. 不要放入客户个人信息、账号密码、API 密钥或未经授权的数据。
4. 原始品牌资料默认不提交到 Git；目录中的 `.gitignore` 会保护这些内部文件。
5. 文本品牌资料与外部事实证据分开；资料中的宣传、数据和效果表述必须经过权威来源核验后才能对外使用。
6. `05-visual-assets/` 中的图片只用于后续图片生成和素材组合，不导入文本 RAG。可运行 `python scripts/build_brand_asset_manifest.py`
   重建私有素材清单。清单脚本目前只索引受控 PNG，拒绝符号链接和超限尺寸，并跳过腾讯微云
   `:com.tencent.wedrive.*` 元数据旁文件；JPG、JPEG 和 WebP 原件可以保留，但需后续图片管线显式支持后才会进入清单。
7. 如需让模型辅助识别实际画面，可在本地运行
   `python scripts/annotate_brand_visual_assets.py --model glm-4.1v-thinking-flash`。脚本逐张发送
   PNG 到智谱视觉模型，只接受固定英文标签白名单，并将结果保存到私有的
   `visual-assets.metadata.json`；模型不可用时会记录状态并使用目录/文件名规则继续完成清单。
   这不是每日生产任务的一部分，使用前应确认 `AI_PLATFORM_BASE_URL` 和
   `AI_PLATFORM_API_KEY` 只存在于本地 `.env` 或部署密钥存储中。

## 视觉素材清单

`visual-assets.manifest.json` 是图片选择索引，不是文本知识库。每个条目会保存：

- `asset_kind`：`identity`、`action` 或 `style`；身份图用于锁定角色，动作图用于提供主题场景，风格图用于提供构图和视觉语言。
- `roles`、`characters`、`topics`、`poses`、`scene_tags`：供选择器匹配，均为受控标签。
- `variant_group`、`display_name`、`selection_tags`：用于解释和稳定轮换，不直接作为模型指令。
- `asset_id`、`sha256`、`byte_size`、尺寸和 `approved`：用于完整性校验，图片变更后必须重新生成清单。

需要人工调整用途时，在同目录维护 `visual-assets.metadata.json` 覆盖标签，再运行清单脚本。不要把
密钥、客户资料、私有 URL 或任意自然语言提示词写入 metadata；清单中的私有路径也不会返回给模型或企业微信。
视觉模型的建议不能改变 `asset_kind`、批准状态或身份角色；需要纠正模型标签时，直接编辑 sidecar 中对应资产的受控字段后重新运行清单脚本。
