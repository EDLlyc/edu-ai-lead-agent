# 2026 年 8 月 10 日—16 日工作周报：执行计划

## Phase 1 — 证据整理

- [x] 固定周报日期范围与时区。
- [x] 从提交历史、任务 result 和 journal 建立主题证据表。
- [x] 区分已部署、已验证、本地验证、保持关闭和待解析状态。
- [x] 列出问题与下周计划，排除 8 月 17 日之后工作。

## Phase 2 — 文案与排版

- [x] 编写摘要、四条主线、关键结果和问题边界。
- [x] 绘制周时间线和完成/问题短表。
- [x] 编译 A4 中文 PDF，控制在 4--6 页。
- [x] 不加入真实服务器、供应商原始响应或会话原文。

## Phase 3 — 验收

- [x] 检查页数、字体、中文提取、布局和敏感信息。
- [x] 检查所有关键数字和状态都能回溯到 task/journal/git 证据。
- [x] 运行 `git diff --check`，确认不触碰用户已有文件。
- [x] 更新 `result.md`，记录交付与限制。

## Expected Validation Commands

```bash
latexmk -xelatex -interaction=nonstopmode -halt-on-error \
  -outdir=reports reports/weekly-report-2026-08-10-16.tex
pdfinfo reports/weekly-report-2026-08-10-16.pdf
pdffonts reports/weekly-report-2026-08-10-16.pdf
pdftotext reports/weekly-report-2026-08-10-16.pdf -
git diff --check
```

## Risky Files and Rollback

- 只新增周报 TeX/PDF 和任务文件。
- 不覆盖现有微信/Trellis 报告和工作区修改。
- 发现证据冲突时，删除或降级该表述，不用推测补齐。
