# 公开简历 Agent 定向优化

## Goal

面向 Agent 应用、AI 平台后端与 Agent Evaluation 实习，基于仓库中已经核验并公开的工程证据，
重写公开简历的求职定位和核心实习经历，让招聘者在一页内优先看到执行治理、Typed Tool Registry、
MCP、claim-level grounding 与 GLM-5V 失败驱动评测，而不是只看到框架名和内容运营业务。

## Confirmed Facts

- 当前公开简历是单页 A4，源文件为 `docs/portfolio/resume/resume-public.tex`，生成物为同目录 PDF。
- 现有简历只链接 GitHub profile，没有直达项目仓库；图片 bullet 仍以 provider-free 48/48 为主。
- 已核验的公开证据支持：4-turn/4-tool-call 有界 Workbench、统一 Typed Tool Registry、MCP v2 stdio、
  claim-level citation、Agent Capability Gateway、多维预算原子预留/exactly-once 对账、固定
  Writer--Reviewer 协议以及 GLM-5V-Turbo 120 次 one-shot 图片评测。
- 42/42 Workbench 与 48/48 Reviewer policy suite 是 provider-free contract/policy evidence；
  Reviewer 尚无完整 live A/B 或质量 uplift；图片 live evidence 只有 6 个独立 source families、
  0 human/external labels 和 1 次 provider rejection。

## Requirements

### R1 — 求职定位与入口

- 意向岗位收敛为 Agent 应用 / AI 平台后端 / Agent Evaluation 相关实习，不包装为 Agentic RL 或训练岗。
- 联系区增加公开项目仓库直链，同时保留邮箱、个人主页和已有公开身份信息。

### R2 — 当前实习经历重写

- 将三个 bullet 依次聚焦为：执行治理与受控 Reviewer、Typed Registry/MCP/Grounding/RAG、
  GLM-5V 多模态评测与 OCR bad case。
- 用问题、机制、指标、边界和工程决策表达，不堆叠没有解释的框架名。
- 允许保留已经冻结的品牌检索指标，但必须明确为脱敏离线评测。

### R3 — 证据边界

- 不把 provider-free 42/42 或 Reviewer 48/48 写成真实模型准确率或线上质量提升。
- 不声称人工标注、人工一致率、Reviewer uplift、生产 SLO、动态 Agent swarm 或训练算法能力。
- GLM-5V 指标必须保留 6 个来源族、120 次调用、holdout 83.33%、OCR 0/6、non-activating
  工程决策中的关键信息；不把 48 个派生样本表述为 48 个独立真实样本。

### R4 — 版式与构建

- 保持单页 A4，不降低到明显影响阅读的字号，不引入仓库外字体或私有文件。
- 更新 `resume-public.pdf`；构建过程不得出现未定义引用、LaTeX error 或 overfull box。
- 用 PDF 文本提取复核关键链接、指标和证据限定词确实进入生成物。

## Acceptance Criteria

- [x] `resume-public.tex` 的求职定位和项目入口已更新，项目仓库可直接点击。
- [x] 当前实习的三条经历分别覆盖执行治理/Reviewer、Typed Registry/MCP/Grounding、GLM-5V Eval。
- [x] 所有数字能追溯到冻结报告，deterministic/provider-free/live/human-label 边界准确。
- [x] 教育经历和两个 12306 项目的既有事实没有被无依据改写。
- [x] `latexmk -xelatex -interaction=nonstopmode -halt-on-error` 编译成功且收敛。
- [x] 生成的 PDF 为一页 A4，日志无 overfull/undefined-reference 警告，关键文字可提取。
- [x] 只修改简历源文件、生成 PDF 与本任务 Trellis 文件；不调用外部模型或 provider。

## Out of Scope

- 不修改业务代码、Agent 实现、README 首页、GitHub metadata、CI、License 或作品集页面。
- 不新增尚未完成的 live Agent benchmark、Reviewer live A/B、人工 Gold 或生产效果数字。
- 不改变姓名、教育背景、实习日期、论文状态、竞赛奖项和 12306 项目的既有事实。

## Delivery

- `docs/portfolio/resume/resume-public.tex`
- `docs/portfolio/resume/resume-public.pdf`
