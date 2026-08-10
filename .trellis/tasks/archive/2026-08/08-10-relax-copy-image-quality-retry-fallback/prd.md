# 放宽文案图片质量阻断并增加重试兜底

## Goal

提高每日素材包的完成率：文案和图片的普通质量问题不再直接阻断业务，系统按固定次数重试，图片生成最终失败时优先使用当前选题匹配的品牌素材目录图片。

## Confirmed Facts

- 文案格式问题（长度、emoji、段落、新闻开场）已经在 `backend/app/domain/copy_generation.py` 中以 warning 记录，并最多触发一次文案修复。
- 文案审计的普通品牌/表达问题在 preview 规则下会降为 warning，但严格规则仍可能把它们作为 error；`backend/app/application/services/copy_generation.py:_copy_format_issues()` 当前只把格式问题送入修复流程。
- 文案 provider 的瞬时失败已经使用 `CONTENT_MAX_ATTEMPTS` 和有界退避；不可重试的 provider/schema/证据错误会进入 `review_required` 或终态失败。
- 图片 worker 已有 `IMAGE_MAX_ATTEMPTS`、一次 targeted repair、一次中和后的 provider rejection retry，以及使用已预留品牌目录引用的 fallback。
- 普通图片质量失败在第二次 targeted repair 后目前会将 image 置为 `review_required`、material package 置为 `failed`；只有 provider rejection retry 路径会继续进入 catalog fallback。
- 图片 fallback 必须使用已预留、校验过 checksum 的品牌目录引用，并经过固定尺寸、栅格和 MinIO 私有存储校验。

## Requirements

### 文案

- 将普通编辑质量问题（格式、品牌契合、语气、流畅度、学习价值说明、品牌价值说明和标签质量）统一视为 warning；它们不能单独阻断素材包。
- 普通质量问题最多触发一次修复；修复后仍有这些 warning 时，保留问题记录并继续进入素材包流程。
- 保留硬阻断：隐私/个人信息、提示词注入回显、自动发布表述、教育焦虑、违规营销、不安全图片提示词、未绑定或证据不匹配的外部事实、缺失/篡改来源链接、未知证据或品牌绑定、provider/schema/身份不一致等技术或完整性问题。
- provider 瞬时错误继续使用现有 `CONTENT_MAX_ATTEMPTS` 有界重试和退避，不新增无限重试或重复副作用。

### 图片

- provider rejection 仍只允许一次中和提示词重试；不得绕过供应商安全策略或反复提交被拒内容。
- 图片栅格、媒体类型、签名、尺寸/像素/字节上限、provider 身份、引用 checksum、SSRF/无重定向下载等安全和完整性检查继续硬阻断。
- OCR、普通视觉质量审计和生成结果质量失败最多进行一次 targeted repair；修复仍失败时，使用当前素材包已预留的、按主题选择的品牌目录引用进行 fallback，禁止第三次 provider 生图请求。
- 有界 provider 重试耗尽后，如果存在可用品牌目录引用，也使用同一 fallback；没有可用引用、引用校验失败或 MinIO 写入失败时，保留 `review_required`，不得伪造图片。
- fallback 图片经过现有渲染、校验和私有 MinIO 存储流程，素材包进入 `awaiting_manual_use`，并持久化安全的 fallback 状态、初始错误码和资产摘要。

### 私有视觉素材库

- 将 `private/brand-materials/05-visual-assets` 中的已批准 PNG 编译为结构化 JSON 清单；每个条目保存稳定资产 ID、人物、素材类型、引用角色、主题、动作、场景、变体组、尺寸、字节数和 SHA-256。
- `identity_reference` 只用于锁定角色身份；动作/场景图不得因为同时出现品牌角色就自动被当作身份主参考。`action_reference` 和 `style_reference` 按能力可选，缺少风格图不能把整次选择降级成单图。
- 选择结果必须保持可解释、可复现，并允许同一主题在已批准变体中稳定轮换；同一素材包的重试仍复用已持久化的引用，不产生随机漂移。
- 支持一次性使用智谱视觉模型对实际 PNG 提出人物、主题、动作和场景标签；模型输出只能经过固定 JSON 解析和受控标签白名单校验后写入 metadata 的 `suggested_tags`，生产 canonical 标签仍以文件名/目录/人工规则为准，API 不可用时不阻塞日常任务。
- 视觉标注只生成结构化标签和有限状态摘要，不保存模型原始回复、提示词、密钥、图片副本或私有 URL；身份/动作/风格用途仍以目录规则和人工 metadata 为准，模型不得自行批准素材或改变身份边界。
- JSON 清单是内部选择索引，不进入文本 RAG，不把私有路径、原始图片或任意提示词字段暴露给 API、模型或日志。

### 可观测性与兼容性

- 每次重试、质量降级、fallback 和最终 review_required 都记录结构化 event、attempt、error code 和下一步动作，不记录 prompt、图片内容、provider 原始响应、URL、密钥或内部对象路径。
- 更新 pipeline/rule 版本，确保新策略通过指纹生效；历史运行和已生成素材不被重新解释或覆盖。

## Acceptance Criteria

1. 普通文案质量审计问题被保存为 warning，经过至多一次修复后仍能生成可查看素材包；硬阻断问题仍不会被降级。
2. 文案 provider 瞬时失败按 `CONTENT_MAX_ATTEMPTS` 重试并有界结束，不会无限循环或产生重复持久化副作用。
3. 图片第一次质量失败会排队一次 targeted repair；第二次质量失败会使用已预留的主题相关品牌图片并将包置为 `awaiting_manual_use`。
4. provider rejection 最多发生一次中和重试；重试再次拒绝或质量失败时使用品牌 fallback，不发起第三次 provider 请求。
5. 没有可用、可校验的品牌 fallback 时，图片和素材包进入可审计的 `review_required`/`failed` 状态，不保存伪造或未校验图片。
6. fallback 与重试保留现有 request fingerprint、attempt 记录、私有 MinIO 存储和安全投影；并发/replay 不产生第二个成功图片。
7. 新增/更新单元测试覆盖文案警告、硬阻断、瞬时重试、图片质量修复后 fallback、provider rejection fallback、无 fallback 终态和安全日志字段。
8. 任务范围内 Ruff、mypy、定向测试和 `git diff --check` 通过；不修改现有无关工作区文件。
9. 清单生成脚本为现有品牌图片生成可校验的结构化 metadata，身份/动作/风格角色与文件用途一致；旧清单或缺失可选字段仍能安全加载。
10. Comfly 在存在身份和动作素材时发送有序多参考图；没有风格素材不再错误进入 `single_fallback`，ToAPIs 的单图能力限制仍保持。
11. 选择器测试覆盖角色分离、可选风格、稳定变体选择、字节预算、checksum 和私有清单字段的安全边界。
12. 视觉标注脚本可对实际 PNG 调用配置的智谱视觉模型，严格接受受控 JSON 标签；单张失败时保留规则标签并继续生成完整清单，测试覆盖模型回复解析、白名单过滤和失败降级。

## Out of Scope

- 不关闭供应商自身内容安全策略，不伪造绕过拒绝的 prompt，也不对供应商拒绝无限重试。
- 不取消 SSRF、Fake-IP、HTTPS、无重定向、凭据/隐私、提示词注入、原始响应和私有对象路径保护。
- 不使用未绑定当前选题的历史生成图片，不从任意 URL 或未审核目录读取 fallback。
- 不改变新闻抓取、选题选择、品牌检索、企业微信投递接口或自动发布边界。
- 不修改数据库表结构；复用已有 attempt、repair、provider rejection 和 version snapshot 字段。
- 不把视觉模型调用放入每日素材包 worker；视觉标签属于私有素材编目预处理，可重复执行且不影响生产任务可用性。
