# 完善数字 IP 资产库：实施计划

## Phase 1 — 契约与只读投影

- [x] 建立数字 IP profile/character/visual summary 的 domain/schema 类型，固定本轮单 IP，字段保留未来扩展 ID。
- [x] 实现纯投影函数：从 active ready 品牌版本聚合文档类型、版本与标签；输出确定性 fingerprint。
- [x] 复用 `VisualAssetCatalog` loader，增加只读安全投影，限制数量并删除路径/原图字段。
- [x] manifest 缺失、损坏或无 approved asset 时返回 typed unavailable/empty，不影响文本知识投影。
- [x] 在 Brand Knowledge route 增加 profile GET endpoint，复用现有 session/settings，不增加写操作。
- [x] 增加后端 unit/API 定向测试，覆盖稳定聚合、无 active docs、manifest unavailable、私有路径不泄露和 `evidence_eligible` 边界。

## Phase 2 — 前端数字 IP 体验

- [x] 重新生成 OpenAPI 与前端类型，禁止手写 wire interface。
- [x] 扩展 `features/brand/api.ts` 和 hooks，加载数字 IP profile。
- [x] 在品牌工作台顶部增加人设卡，展示角色、受众、内容场景、active 文档/标签和 profile fingerprint 摘要。
- [x] 增加视觉资产元数据区，展示角色/动作/场景/审核信息；manifest 不可用时显示真实空态。
- [x] 扩展召回结果，展示文档版本、类型、语气/安全标签、融合分数和“不能作为事实证据”。
- [x] 实现 versioned/bounded localStorage feedback ledger，支持采纳/拒绝、受控原因、短备注和清除。
- [x] 增加定向组件/API/storage 测试，覆盖成功、空态、损坏 storage、反馈上限、可访问性和无发布操作。

## Phase 3 — 轻量 Eval 与作品集说明

- [x] 新增 versioned、sanitized 的数字 IP fixture cases，覆盖定位、语气、禁用、安全和视觉五类。
- [x] 实现 provider-free runner 与稳定 JSON/Markdown 摘要。
- [x] 指标包含案例通过、预期类型/标签覆盖、禁用规则命中和品牌误作事实证据次数。
- [x] 在报告中显式标记 fixture contract conformance，不宣称真实模型准确率。
- [x] 更新 Brand Knowledge / frontend workspace / Agent Workbench 相关 specs 与本任务 result。

## Focused Validation

- [x] `ruff format --check` 与 `ruff check`：仅本任务变更 Python 文件。
- [x] strict mypy：仅新增/修改 backend app 与 eval 模块。
- [x] backend focused pytest：profile projection、route、visual safe projection、digital-IP eval。
- [x] frontend focused Vitest：brand API、profile view、retrieval explanation、feedback ledger。
- [x] OpenAPI 与生成 Agent/production client drift check（因新增 API schema 必须执行）。
- [x] frontend TypeScript/ESLint 对本任务相关范围；若工具只支持项目级命令则运行一次项目级静态门。
- [x] `git diff --check` 与新增行 secret/private-path 扫描。
- [x] 明确不运行 full backend/frontend suite，除非定向门揭示跨层问题。

## Risk and Rollback Points

- Visual manifest 含私有路径：schema、mapper 和测试必须证明 response 中不存在 path/object key/URL/bytes。
- active version 聚合不能改变现有 activation semantics，只读取当前权威投影。
- localStorage 解析必须 fail-safe，不能因为旧/损坏记录阻断工作台。
- Eval fixture 不能自称真实检索质量；canonical report 文案需经过检查。
- 不修改 Compose、部署脚本、生产 flag、数据库 migration 或业务调度。

## Pre-start Gate

- [x] PRD 已完成收敛，无开放产品决策。
- [x] 用户已审阅 Goal、范围、验收标准、关键取舍和本地-only边界。
- [x] `implement.jsonl` / `check.jsonl` 含真实 spec context。
- [x] 用户在最终规划摘要之后再次明确批准实施。
