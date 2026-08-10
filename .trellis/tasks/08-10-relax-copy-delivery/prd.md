# Relax Local Preview Copy Checks and Refine Moments Format

## Goal

让本地 preview 能完整展示一条可用的朋友圈文案和素材包，便于用户先检查实际效果。
本轮不部署服务器、不修改服务器上的既有业务运行，也不启用本地企业微信自动投递。

## Background

当前文案生成阶段会因为内容审核问题进入 `review_required`，即使用户只是想在本地查看文案和图片，也无法看到完整结果。当前本地 `.env` 已设置 `WECOM_ENABLED=false` 与 `WECOM_AUTO_DELIVERY_ENABLED=false`，因此本轮的验收对象是本地生成和预览链路，不是企业微信发送链路。

## Requirements

### R1. Local preview policy

- 新规则只对 `preview` 本地预览 profile 生效，并使用新的版本标识；历史版本包不重新解释。
- 以下内容问题在本地 preview 中不得再使校验失败、触发 `review_required`、阻断素材包或创建发送阻断：个人信息、提示词注入回显、自动发布表述、违规营销、教育焦虑、不安全图片提示词，以及“已声明事实与证据原文不符”。
- 上述结果仍可作为 warning 记录在草稿与审计轨迹中，便于查看发生了什么；warning 不是拒绝理由，也不触发第二次以上修复。
- LLM 审计返回的对应内容问题同样只能是 warning。其他内容质量问题在本地 preview 中也不作为技术失败处理；只有结构化输出、数据库约束、图片文件完整性、供应商请求边界和企业微信传输边界等技术完整性问题可以阻断流程。
- 本地企业微信投递继续关闭；本轮不得修改本地 WeCom 开关为 `true`，不得向服务器推送或执行服务器重建。

### R2. Short, structured copy target

- 正文主体（末尾标签行除外）不超过 300 个汉字；超限只产生 warning。
- 正文主体为恰好 3 个自然段，每段恰好 2 行非空文字；段落之间保留 1 个空行；标签单独位于最后一行。
- 正文主体包含 6 到 12 个 emoji，每段首字符和末字符均为 emoji；格式不满足时只产生 warning。
- 语言面向家长，说明为什么学习科学、科创、人工智能或机器人，以及为什么在赛先生学习；保留 `#赛先生科学` 在首位，并再提炼 1 到 2 个相关标签。

### R3. Repair and compatibility

- 生成、审计和一次性修复提示词都明确写出 R2 的格式目标。
- 现有最多一次修复可以同时处理字数、分段、emoji 和标签格式；修复后仍有格式或内容 warning 时继续完成本地预览。
- 保留现有 Pydantic/JSON Schema、数据库状态约束、供应商身份与请求指纹、图片文件校验和错误重试边界，不新增数据库迁移。

## Acceptance Criteria

- [ ] 本地 preview 草稿即使命中 R1 列出的任一确定性或 LLM 内容问题，也能以 accepted 结果进入本地素材预览；对应 issue 可追踪且 severity 为 warning。
- [ ] `evidence_text_mismatch` 不再阻断本地 preview；结构化输入仍拒绝未知 evidence ID、未知 brand chunk ID 和非法 JSON/schema。
- [ ] 文案校验识别不超过 300 汉字、3 段、每段 2 行、段间 1 个空行、6--12 个 emoji 和段首段尾 emoji；格式缺陷最多触发一次修复，最终只告警。
- [ ] 生成器、审计器和修复请求的测试覆盖新的文案约束与本地非阻断策略。
- [ ] 本地 targeted tests、lint 和 type checks 通过；本地可生成并展示文案/图片素材包，且企业微信 dispatcher 保持关闭、没有本地发送副作用。
- [ ] 本轮没有服务器 SSH、镜像推送、容器重建、服务器数据库写入或服务器配置变更。

## Out of Scope

- 不部署服务器，不修改服务器当天的 run、素材包、投递任务或生产规则。
- 不启用企业微信自建应用或群机器人，不改变收件人、凭据、webhook 或自动投递配置。
- 不删除审计记录、证据绑定字段、模型版本、请求指纹或本地日志；本轮只改变本地 preview 对内容问题的阻断语义。
