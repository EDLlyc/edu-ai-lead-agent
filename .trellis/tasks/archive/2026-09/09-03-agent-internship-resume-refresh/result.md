# 公开简历 Agent 定向优化结果

## Delivered

- 将求职定位收敛为 Agent 应用、AI 平台后端与 Agent Evaluation 实习。
- 增加公开项目仓库直链。
- 将赛先文化实习的三条核心经历重写为执行治理/Reviewer、Typed Registry/MCP/Grounding、
  GLM-5V 失败驱动评测。
- 重新生成 `docs/portfolio/resume/resume-public.pdf`，教育经历与两个 12306 项目的事实保持不变。

## Evidence boundaries

- 42/42 Workbench 与 48/48 Reviewer policy suite 均明确为 provider-free contract/policy evidence。
- 未声称 Reviewer live uplift、人工一致率或真实模型 Agent accuracy。
- GLM-5V 保留 6 个独立来源族、48 组派生对、120 次尝试、119 完成、1 次 provider rejection、
  0 人工/外部标注、holdout 15/18、OCR 0/6 与 OCR 维度 critical FAR 33.33% 的边界。

## Verification

- `latexmk -xelatex -interaction=nonstopmode -halt-on-error`：PASS，编译收敛。
- `pdfinfo`：1 页 A4。
- `pdfinfo -url`：GitHub profile、项目仓库、个人主页链接均存在。
- `pdftotext`：关键指标与限定词均进入 PDF。
- LaTeX 日志：无 error、overfull、underfull 或 undefined reference；仅有 Fandol 字体既有 CJK
  metadata warning，不影响生成和显示。
- `git diff --check` 与 Trellis context validation：PASS。
- 外部模型、Provider 与网络调用：0。
