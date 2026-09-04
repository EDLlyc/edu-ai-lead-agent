# Agent 实习简历技术亮点优化结果

## Delivered

- 仅重写赛先文化实习经历中的“业务方向”和三条“主要工作”，依次突出 Agent Runtime 与执行治理、Tool Calling/MCP/Grounded RAG、Agent Eval 与多模态失效分析。
- 按追加要求删除顶部“意向岗位”文字、单独占行的“27 届”和项目仓库入口，保留邮箱、GitHub 个人主页与个人网站。
- 将赛先文化实习日期从 `2026.07 - 2026.08` 更新为 `2026.06 - 2026.09`；教育经历与两个 12306 项目的日期保持不变。
- 保留品牌 RAG 脱敏离线 Recall@5 95\%、nDCG@5 92.86\% 的限定词。
- 将 GLM-5V-Turbo 实验明确写为发起 120 次、119 次完成、1 次 provider rejection，并保留 6 个独立素材族、48 组派生对、无人工/外部标注、Holdout 15/18、OCR 0/6 与 Critical FAR 33.33\% 的证据边界。
- 重新生成单页 A4 `docs/portfolio/resume/resume-public.pdf`。

## Verification

- `latexmk -xelatex -interaction=nonstopmode -halt-on-error -output-directory=docs/portfolio/resume docs/portfolio/resume/resume-public.tex`：PASS；第二次执行无待处理目标，确认编译收敛。
- `pdfinfo`：PASS；1 页，A4（595.28 x 841.89 pt）。
- `pdfinfo -url`：PASS；GitHub 个人主页和个人网站共 2 条外部链接均存在，已移除项目仓库链接。
- 源文件与 PDF 文本负向检查：PASS；均不再包含“意向岗位”、单独的“27 届”、“项目：”、`edu-ai-lead-agent` 或旧实习日期 `2026.07 - 2026.08`。
- 日期差异检查：PASS；仅赛先文化更新为 `2026.06 - 2026.09`，教育经历仍为 `2023.09 - 2027.06`，两个 12306 项目仍为 `2026.03 - 2026.06`。
- `pdftotext -layout`：PASS；三条工作、指标与限定词均可提取。
- LaTeX 日志检查：PASS；无 error、undefined reference、overfull 或 underfull box。仅有模板既有的 Fandol CJK metadata warning。
- PDF 视觉检查：PASS；无裁切、重叠或页底溢出。
- `git diff --check -- docs/portfolio/resume/resume-public.tex`：PASS。
- `python3 ./.trellis/scripts/task.py validate .trellis/tasks/09-04-resume-agent-highlight-refinement`：PASS。
- 外部模型、Provider、部署、提交与推送：均未执行。

## Spec Review

- 本任务仅调整简历文案和生成物，没有改变命令、API、数据库、基础设施或跨层契约；无需更新 `.trellis/spec/`。

## Remaining Risk

- 页面信息密度较高，但仍保持既有字号、单页结构和清晰分区；本任务未通过缩小字号换取空间。
