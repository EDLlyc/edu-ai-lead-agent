# Trellis 简介分享：执行计划

## Phase 1 — 内容核验

- [x] 以本地 Trellis 架构说明、工作流和任务系统为权威来源，整理一句话定义。
- [x] 核对 Workflow、Tasks、Specs、Workspace/Memory 四个核心组成的职责。
- [x] 核对规划、实现、检查、归档和后续复用的主流程。
- [x] 记录 Git、AI 模型、测试/评审与 Trellis 的边界。

## Phase 2 — 文案与视觉

- [x] 编写 4--5 页中文短稿，每页只回答一个核心问题。
- [x] 绘制生命周期流程图。
- [x] 绘制核心组成表或 2×2 卡片。
- [x] 编写一个不含业务隐私的“新增功能”示例。
- [x] 将多智能体、Channel 和跨会话记忆压缩为一段进阶说明。

## Phase 3 — LaTeX/PDF

- [x] 新建独立 TeX，不复用或覆盖现有微信报告。
- [x] 完成 A4 中文排版、页眉页脚、统一配色和图表。
- [x] 编译 PDF 并控制在 4--5 页。
- [x] 修复溢出、缺字、断页、字体或引用问题。
- [x] 渲染全部页面并逐页视觉抽查。

## Phase 4 — 验收与收尾

- [x] 检查 PDF 页数、尺寸、字体嵌入和可复制文本。
- [x] 检查定义、流程、目录职责和边界表述与本地 Trellis 资料一致。
- [x] 扫描敏感信息、私有路径和内部业务数据。
- [x] 运行 `git diff --check` 并核对改动范围。
- [x] 写入 `result.md`，记录交付路径、页数、核心内容和验证结果。

## Expected Validation Commands

```bash
latexmk -xelatex -interaction=nonstopmode -halt-on-error \
  -outdir=reports reports/trellis-introduction-brief-2026-08-19.tex
pdfinfo reports/trellis-introduction-brief-2026-08-19.pdf
pdffonts reports/trellis-introduction-brief-2026-08-19.pdf
pdftotext reports/trellis-introduction-brief-2026-08-19.pdf -
git diff --check
```

## Risky Files and Rollback

- 本任务只新增 task 文件和独立报告文件，不修改业务代码、服务器或现有报告。
- 当前工作区已有的微信报告修改和根目录删除状态属于用户，必须原样保留。
- 编译产生的辅助文件不纳入交付；若报告失败，只清理本任务新生成的辅助文件。
