# Relax deterministic copy validation blockers

## Goal

让生产环境的文案生成在遇到用户明确要求放宽的文案内容/一致性问题时继续完成素材包和自动投递，避免今天这种“模型调用成功、一次修复后仍因文案绑定格式而完全不投送”的情况。

## Background

2026-08-11 的定时选题成功，文案生成和一次修复请求也都成功，但两个草稿因以下确定性 issue 被标记为 error：`claim_not_in_copy`、`source_note_unlinked`、`unclaimed_external_fact`。文案运行最终为 `review_required / repair_validation_failed`，没有创建素材包或企业微信投递任务。

当前生产默认使用质量恢复规则（`moments-rules-v9-quality-warning-recovery` / `preview-v8-quality-warning-recovery`）。校验逻辑已经允许格式、可读性和品牌质量问题作为 warning，但上述三类一致性问题尚未加入当前 warning 集合。

## Requirements

- **R1. 版本化策略**：新增 preview 规则版本，旧版本保持历史语义；新版本必须进入版本 bundle 和请求指纹，不能重新解释已经持久化的 run。
- **R2. 文案一致性问题降级**：在新 preview 规则下，`claim_not_in_copy`、`source_note_unlinked`、`unclaimed_external_fact` 统一持久化为 `warning`。它们仍进入日志、校验快照和最多一次修复提示，但不能单独阻断审计、素材包或自动投递。
- **R3. 用户指定内容问题降级**：在新 preview 规则下，确定性校验中的 `personal_data`、`prompt_injection_echo`、`prohibited_marketing`、`education_anxiety`，以及审计器返回的同类隐私、提示词回显、营销夸张/推广措辞、教育焦虑 issue，统一作为 `warning`。系统保留检测、脱敏日志和审计记录，不删除这些检查。
- **R4. 保留硬边界**：以下仍为 error 并可阻断：未知 evidence/brand ID、`unbound_external_fact`、`missing_source_note`、`evidence_text_mismatch`、`copy_news_source_footer`、自动发布、不安全图片、非法 JSON/schema、供应商身份不一致、数据库/图片存储完整性错误，以及未被明确列入新 warning allowlist 的证据、事实和发布边界问题。
- **R5. 提示词一致**：生成、审计和一次性修复提示词必须说明上述 warning 类别可以继续交付；同时明确仍保留的硬错误，避免模型继续把 warning 当作不可交付失败。
- **R6. 一次修复和投递**：只有 warning 或既有质量 warning 时，最多执行一次修复；修复后仍有 warning 也必须继续进入审计、素材包和企业微信投递。存在任一硬 error 时继续走现有 review-required 路径。
- **R7. 测试和运行发布**：补充版本隔离、issue severity、硬边界保留、一次修复后继续接受和企业微信候选资格测试；本地质量门通过后，将新版本部署到服务器，不执行人工重复发送或制造测试业务数据。

## Acceptance Criteria

- [ ] 新 preview 规则版本下三类一致性 issue 和四类用户指定内容 issue 的 severity 均为 `warning`，旧规则和 strict 规则的历史行为不变。
- [ ] 新规则下只存在这些 warning 时，确定性校验 `passed=true`，能够进入 LLM audit；一次修复后仍有这些 warning 时，run 能进入 `accepted`，并可创建素材包/投递任务。
- [ ] `evidence_text_mismatch`、`unbound_external_fact`、未知 ID、来源页脚错误、自动发布和不安全图片仍为 `error`，不会被新 warning 集合吞掉。
- [ ] 生成器、审计器和 repair prompt 的规则描述与实际策略一致，规则版本和 fingerprint 可在持久化记录中区分旧/新 run。
- [ ] 相关 backend 单测、集成/契约测试（适用时）、Ruff、mypy、Compose 配置和 `make doctor` 通过。
- [ ] 服务器以新版本重建并启动后，所有长期服务稳定运行，dispatcher 保持自动投递配置；不发送额外测试消息，不修改历史业务行。

## Out of Scope

- 不删除确定性校验框架、校验记录、证据绑定字段或审计轨迹。
- 不放宽数据库约束、JSON/schema 解析、供应商请求边界、图片文件校验、SSRF/网络安全边界或企业微信传输幂等性。
- 不直接修改今天已经失败的 run，不通过数据库手工制造素材包或投递任务。
- 不部署前端、不改变企业微信 webhook、收件人或凭据。

## Risks and Deferred Items

- 这些 warning 允许部分事实表达、个人信息、提示词回显、营销或焦虑措辞继续进入内部投递，降低了内容阻断强度；问题仍可在素材包审计记录中追踪，后续可单独增加人工监控或报表。
- 新版本上线后只影响新创建的 run；历史失败 run 不自动重跑，避免重复调用模型和重复投递。
- 服务器部署前保留现有镜像、数据库、MinIO 和本地备份，失败时停止写入服务并回滚到上一版本。

## Open Questions

无。用户已确认将三类问题从阻断错误放宽为 warning，并允许继续处理。
