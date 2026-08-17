# 图片供应商输出容错与品牌素材兜底

## Goal

避免 `gpt-image-2` 偶发返回不可解析图片表示时让整条素材包失败：请求优先采用供应商当前推荐的 URL 输出；若供应商仍返回不可解析表示，只追加一次受控、可恢复的供应商请求；第二次仍失败时使用本主题已经预留并审核过的品牌素材生成 1024×1024 兜底图，使直推模式能够继续创建企业微信投递任务。

## Background

- 2026-08-17 午间链路已经完成选题和文案，但唯一素材包因 `image_output_representation_invalid` 失败，未创建企业微信任务。
- 失败发生在供应商 JSON 中的非空 `b64_json` 通过严格 Base64 解码之前；原始响应按隐私合同未留存，因此不能断言供应商实际返回的是 URL、data URI、截断 Base64 或其他文本。
- 当前 Comfly 适配器固定发送 `response_format=b64_json`，而供应商现行 `gpt-image-2` 文档示例和返回说明以 `response_format=url` 为默认/推荐路径。
- 适配器已经安全支持 URL、合法 Base64、直接栅格和异步任务结果；素材包也已经具备“一次供应商拒绝恢复 + 品牌目录兜底”的持久化状态机，但不可解析图片表示尚未进入该恢复路径。

## Requirements

### R1 — 使用供应商推荐的 URL 输出合同

- Comfly `gpt-image-2` 创建请求必须显式发送 `response_format="url"`，保留 `size="1024x1024"`、有序本地参考图 data URL 和现有请求边界。
- 接收端继续兼容供应商返回的单个 HTTPS URL、合法 Base64、允许的直接栅格和已记录的异步任务结构；不得只因请求 URL 就拒绝合法 Base64 兼容响应。
- URL 下载继续执行现有 HTTPS、无重定向、公共 DNS/IP、字节上限、签名、媒体类型和 1024×1024 校验。

### R2 — 不可解析图片表示只恢复一次

- 只有安全原因 `image_output_representation_invalid` 可进入本恢复；尺寸错误、栅格签名错误、非公共 URL、重定向、超限、身份错误和其他安全/完整性失败仍保持终态失败。
- 第一次不可解析表示使用现有独立的单次供应商输出恢复计数持久化排队，使用不同的幂等请求指纹，但保留原始受控视觉方案和提示词，不把传输格式故障误当成内容拒绝而改写提示词。
- 第二次不可解析表示不得继续调用供应商，必须转入 R3。该预算独立于网络瞬态重试、OCR/质量修复和多样性重生成，且上限恒为 1。
- 为避免迁移和 API 漂移，现有 `provider_rejection_retry_count`、`neutralized_retry` wire state 可作为兼容字段承载该一次性供应商输出恢复；安全 provenance 必须用 `initial_error_code=image_output_invalid` 区分原因。

### R3 — 第二次失败使用审核品牌素材

- 从当前素材包已经持久化的有序预留引用中，按现有 action → style → identity 顺序选择一项，不得临时跨主题检索或使用任意服务器文件。
- 使用现有确定性品牌兜底渲染器生成 1024×1024 PNG，经过相同字节/签名/尺寸校验后写入私有不可变存储。
- 成功时保留请求的主供应商/模型身份，并记录 `fallback.state=brand_catalog`、安全资产元数据和 `initial_error_code=image_output_invalid`；包进入 `awaiting_manual_use`，直推模式可照常创建正式企业微信任务。
- 若没有预留资产、资产校验失败或私有存储失败，保持 typed `review_required`/package `failed`；不得发送原始坏图或空图。

### R4 — 幂等、隐私与可观测性

- 租约丢失、并发执行、重放或进程重启不得产生第二个成功 artifact、重复对象、第三次供应商请求或重复企业微信任务。
- 不记录或持久化原始响应、Base64、生成 URL、提示词、图片字节、凭证、私有路径或 provider body。
- 日志和 validation snapshot 仅允许现有 IDs、provider/model、attempt/counter、safe reason、下一动作和 allowlisted response kind/status；不得为了诊断新增响应内容采样。

### R5 — 兼容性与范围

- 不新增 Alembic migration，不改变生产 OpenAPI、前端 wire schema 或企业微信投递准入条件。
- 合法 URL/Base64/直接栅格、供应商拒绝、网络瞬态重试、OCR/质量修复、多样性重生成和历史 artifact replay 行为保持兼容。
- 普通测试全部使用 fake/MockTransport/本地品牌 fixture，不访问 Comfly、智谱、MinIO、企业微信或生产服务器。

## Acceptance Criteria

- [ ] Comfly 创建 payload 精确使用 `response_format="url"`，其余受审字段、参考图顺序和大小边界不变。
- [ ] 单个安全 HTTPS URL 下载并验证成功；合法 Base64、直接 PNG/JPEG/WebP 和任务响应兼容测试继续通过。
- [ ] 非空但非法 Base64 首次只产生一个持久化恢复，使用不同幂等指纹且提示词/视觉方案不变。
- [ ] 同一 artifact 第二次出现 `image_output_representation_invalid` 时供应商调用总数不再增加，并成功落一个验证过的品牌目录兜底图。
- [ ] 品牌兜底成功后 artifact succeeded、package `awaiting_manual_use`、fallback provenance 为 `brand_catalog` + `image_output_invalid`，且直推查询仍把该包视为可投递。
- [ ] 没有/损坏的预留品牌资产、存储失败时保持 typed review/failed，且没有图片对象和企业微信任务。
- [ ] 非公共 URL、重定向、超限、签名/尺寸不符等安全失败不进入该恢复或兜底。
- [ ] 重放、并发、租约过期和 worker 重启不会造成第三次 provider call、重复对象、重复 artifact 或重复 delivery job。
- [ ] 安全日志/快照测试证明 raw body、URL、Base64、凭证、私有路径和图片字节均未泄漏。
- [ ] 相关 unit/contract/integration 回归、Ruff、strict mypy、API drift 和完整 backend gate 通过；默认门禁无 live provider/WeCom 调用。

## Out of Scope

- 不自动补发、重跑或重建 2026-08-17 午间失败素材；如需补发必须另行明确授权并先做重复投递检查。
- 不降低图片格式、网络地址、媒体类型、尺寸、OCR、质量或多样性安全门。
- 不增加新的供应商、任意 URL 代理、后台手工上传入口或新的生产开关。
- 本任务实现完成后不自动部署生产；部署仍需单独的发布授权与门禁。

## References

- ToAPIs/Comfly GPT-Image-2 中文文档：https://docs.toapis.com/docs/cn/api-reference/images/gpt-image-2/generation
- ToAPIs/Comfly GPT-Image-2 English docs：https://docs.toapis.com/docs/en/api-reference/images/gpt-image-2/generation
