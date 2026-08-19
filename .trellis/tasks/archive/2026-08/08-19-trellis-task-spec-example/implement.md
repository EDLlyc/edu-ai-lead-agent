# Trellis 任务规范示例：执行计划

## Phase 1 — 内容核验

- [x] 核对归档的 Trellis 简介任务工件和本项目规范入口，提炼可公开的真实结构。
- [x] 确定示例不包含路径、开发者信息、会话、Git SHA 或业务内容。

## Phase 2 — 报告改版

- [x] 删除截图页、图片依赖和相关说明。
- [x] 将总结页恢复为第 5 页。
- [x] 添加 Task → Spec → Output 三卡片示例和复杂度说明。
- [x] 保留原有适用场景、边界和总结。

## Phase 3 — 验收

- [x] 编译 5 页 PDF，检查文本、字体、日志、视觉与敏感信息。
- [x] 搜索确认不再引用截图、Agent Workbench 或 deterministic/loopback 叙述。
- [x] 运行 `git diff --check`，更新 `result.md`。

## Risky Files and Rollback

- 只改报告 TeX/PDF 和任务文件；截图源与其他报告不触碰。
- 如示例页过密，优先压缩卡片文案，不增加截图或新页面。
