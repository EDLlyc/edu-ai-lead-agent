# 智谱 OCR 请求拒绝诊断与修复

## Goal

修复受控视觉图片 OCR 错误复用文本模型的问题，使图片中的三层品牌文字可以通过智谱
官方图片 OCR 能力进行严格、可审计的顺序校验；在不扩大新闻、生成和企微发送范围的
前提下，恢复生产视觉多样性启用条件。

## Background

- 2026-08-15 的隔离生产验收只执行了 1 次图片生成和 1 次 OCR。图片通过
  1024×1024 媒体门，OCR 随后以 `provider_request_rejected` 终止；生产开关保持关闭，
  没有重试、第二条新闻或企微增量。
- 生产只读探针确认 `AI_PROVIDER_MODE=zhipu`、`AI_CHAT_MODEL=glm-5.2`，图片 OCR
  adapter 当前直接复用 `AI_CHAT_MODEL` 并向 `/chat/completions` 发送 `image_url`。
- 智谱官方文档将 GLM-5.2 定义为文本输入/文本输出模型；官方图片理解示例使用
  GLM-5V-Turbo，而专用 GLM-OCR 的 `/layout_parsing` 接口直接支持 JPG/PNG、Base64 和
  有序布局文本。现有配置因此存在确定的模型能力不匹配。

## Requirements

1. 图片 OCR 必须使用独立、受限、版本化的模型配置，不得继续复用文本生成模型。
2. 默认采用智谱专用 `glm-ocr` 与 `/layout_parsing`，输入仅允许通过媒体门的 PNG/JPEG，
   单图和总请求字节必须受限；不得把图片上传到公开 URL。
3. OCR 结果必须从结构化布局文本中提取，并按页面内从上到下、同一行从左到右的
   确定顺序形成 `recognized_lines`；仍由现有 exact visual-text gate 判断缺失、乱序、
   额外文字和不在白名单的文字。
4. 请求、响应和日志不得暴露 API key、Base64 图片、原始 provider body、prompt、对象
   key、哈希或业务行标识；只允许持久化既有安全模型名、typed 状态和受控验证结果。
5. 文本生成、embedding、治理、品牌 PDF OCR 与历史 v1 图片路径保持兼容；不得改变
   公共 API shape 或数据库 schema，除非实现研究证明无法避免并重新进入规划确认。
6. 供应商 4xx/鉴权/限流/超时/异常响应必须继续映射为现有 typed failure，不能自动降级
   为“通过”，也不能消耗视觉相似度的唯一重生成预算。
7. 默认不真实发送企微，不手工 enqueue/retry/resend，不处理第二条新闻。
8. 修复部署后，允许在本任务内执行 1 次确定性 OCR live gate 和 1 条隔离真实新闻
   端到端验收；只有全部门通过时才开启生产 diversity/OCR 两个开关。

## Acceptance Criteria

- [ ] 单元/契约测试证明图片 OCR 使用独立 `IMAGE_OCR_MODEL=glm-ocr`，请求目标为
  `/layout_parsing`，而 `AI_CHAT_MODEL=glm-5.2` 仍仅供文本生成。
- [ ] PNG/JPEG Base64、请求大小、响应大小、模型身份、布局元素、坐标范围、文本行数、
  顺序和额外文字均有正反例；PDF/WEBP/空图片/超限输入在 provider 调用前拒绝。
- [ ] 生产 Settings/Compose/doctor/evidence 对 API 与 content worker 的 OCR 模型配置一致，
  旧配置默认关闭时继续正常启动和回放。
- [ ] 后端完整质量门、迁移/契约门、Compose、doctor、shell/diff/secret gate 全绿；无公共
  API 或 Alembic drift。
- [ ] 如获授权，先用本地确定性三行 PNG 完成至多 1 次智谱 OCR live gate；再按上一任务
  的隔离边界执行至多 1 条真实新闻、最多 2 次图片生成、每次至多 1 次 OCR，且企微关闭。
- [ ] 只有隔离端到端验收同时产生存储图片、exact ordered OCR、相似度决定和人工视觉检查
  通过时，才允许原子开启生产 diversity/OCR；否则恢复服务并保持两开关关闭。

## Out of Scope

- 更换图片生成供应商、放宽文字白名单或 OCR 顺序规则。
- 开启图片质量 AI audit、修改企微日级防重规则、补发历史新闻。
- 将生产服务器改造成 CI 节点，或处理 ACR/云效权限。
- 为失败请求打印或保存原始 provider body。

## Key Decision

用户已批准完整闭环：代码修复、部署、一次确定性 OCR live gate、一次隔离真实新闻验收，
以及全部门通过后的生产启用。任一门失败都按 fail-closed 恢复，且不得改用第二条新闻。
