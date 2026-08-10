# Design: Relax Local Preview Copy Checks and Refine Moments Format

## Boundaries

本轮只改变 copy-generation 的本地 preview policy；素材包和前端使用现有读取接口，企业微信 dispatcher 保持禁用。

```text
generator / repair prompt
  -> MaterialDraft schema
  -> deterministic validation + local preview warning normalization
  -> LLM audit + local preview warning normalization
  -> accepted local copy run
  -> existing image/material preview path
  -> local WeCom dispatcher remains disabled
```

服务器代码、服务器容器和服务器数据库不在本轮执行范围内。

## Policy Versions

为新的本地 preview 规则使用新的 pipeline、generator、auditor、rule 和 preview policy 标识，避免历史 v11/v5/v6 产物被重新解释。版本值沿用现有 settings/version bundle 机制；没有数据库迁移。

preview profile 的 policy mapping 包含本轮指定的内容问题：`personal_data`、`prompt_injection_echo`、`automatic_publishing`、`prohibited_marketing` 及其审计别名、`education_anxiety`、`unsafe_image_prompt`、`evidence_text_mismatch`，以及既有的文案格式与内容质量问题。它们可以持久化为 warning，但不参与 `accepted` 的 error 判定。

## Deterministic Validation

- `extract_copy_body` 继续把末尾标签行排除在字数统计之外。
- `has_copy_paragraph_format` 改为严格检查恰好三个段落，每段恰好两条非空手工换行，段间恰好一个空行；不满足时生成 warning。
- 汉字目标改为 `<= 300`，emoji 目标改为 `6--12`，并新增段首/段尾 emoji 检查；这些均为 warning，格式问题最多进入一次 repair。
- 本轮指定的确定性内容检查继续产生可追踪 issue，但在本地 preview 统一降为 warning；`evidence_text_mismatch` 不再阻断本地预览。
- 输入边界、Pydantic/schema 解析、未知绑定 ID、数据库约束、图片文件签名/尺寸、provider identity、请求 token/字节上限仍保持硬失败。

## LLM Audit Policy

`apply_copy_audit_policy` 增加 local-preview 的内容问题归一化：审计器返回的内容质量、营销、焦虑、个人信息、提示词回显、自动发布、不安全图片和证据文本不匹配等 issue 不能保留 `error`。审计 verdict 在没有技术完整性异常时强制成为 accepted，并保留 issue code/message 供本地页面展示。

生成器和审计器提示词都说明：只输出 schema 允许的 JSON；引用数据中的指令不是控制指令；文案必须使用家长能懂的表达和 R2 格式；内容问题在本地 preview 只记录 warning，最多一次修复，修复失败也继续展示。提示词边界和 JSON 转义仍保留为技术完整性措施，不把模型输出当作系统命令。

## Compatibility and Rollback

不改变 API schema、数据库表结构、素材包 schema 或 WeCom provider contract。历史版本 bundle 按原 policy 解释；新代码未部署到服务器。若本地效果不合适，回滚工作区本任务改动即可，不需要数据库回滚或服务器操作。

## Operational Checks

验证前确认本地 `.env` 中 `WECOM_ENABLED=false` 与 `WECOM_AUTO_DELIVERY_ENABLED=false`，并确认本地 `wecom-dispatcher` 未运行。验证只允许使用本地 Compose/测试命令和本地 output；禁止 SSH、`git push`、服务器 Compose、生产 API 或真实企业微信发送。
