# 强化 Agent 实习简历技术亮点

## Goal

面向 Agent 应用开发实习，在现有单页公开简历中进一步强化赛先文化实习经历的工程主线，让招聘者优先识别 Agent Runtime、Tool Calling/MCP、Grounded RAG 与 Agent Eval 能力，同时保持所有指标和实验边界真实、可追溯。

## Confirmed Facts

- 当前公开简历源文件为 `docs/portfolio/resume/resume-public.tex`，生成物为同目录下的 `resume-public.pdf`，现状为单页 A4。
- 用户要求移除顶部的“意向岗位”文字、单独占行的“27 届”和联系区中的项目仓库入口；邮箱、GitHub 个人主页和个人网站继续保留，届别由教育经历中的毕业时间体现。
- 用户将赛先文化实习时间更新为 `2026.06 - 2026.09`，该信息覆盖简历原有的 `2026.07 - 2026.08`。
- 仓库证据支持：LangGraph 有界状态化 Agent、Capability Gateway、固定 Writer--Reviewer 协议、Pydantic TypedToolRegistry、MCP v2 stdio、claim-level citation、品牌混合检索以及 GLM-5V-Turbo 图片评测。
- 品牌 RAG 的 Recall@5 95\%、nDCG@5 92.86\%属于脱敏离线评测；GLM-5V 实验为 120 次调用尝试，其中 119 次完成、1 次 provider rejection，且没有人工或外部标注。

## Requirements

### R1 — 聚焦 Agent 岗位

- 保留现有实习公司、岗位与技术栈，将日期更新为 `2026.06 - 2026.09`，并优化“业务方向”和三条“主要工作”。
- 删除顶部“意向岗位：Agent 应用 / AI 平台后端 / Agent Evaluation 实习”、单独占行的“27 届”和“项目：edu-ai-lead-agent”链接，不以额外标签重复教育与求职信息。
- 业务方向简化为新闻采集、事实治理、智能选题、品牌内容生成与多模态质量评测，减少抽象形容词。
- 三条工作依次突出：Agent Runtime 与执行治理；Tool Calling、MCP 与 Grounded RAG；Agent Eval 与多模态失效分析。

### R2 — 提升可读性

- 使用“问题/机制/结果或决策”的表达，减少中英文术语堆叠，但保留 Agent 岗面试中有辨识度的关键词。
- 明确知识检索、事件详情、品牌 RAG 和文案校验被封装为统一工具能力，体现模型自主选工具和有界执行的工程基础。
- 保持一页可读，不通过明显缩小字号换取空间；如文字超出，优先压缩措辞和局部间距。

### R3 — 保持证据边界

- 不把 provider-free 契约测试写成真实模型准确率，不声称 Reviewer 已取得线上质量提升。
- 多模态实验应写为“发起 120 次”或同时保留 119 次完成、1 次 provider rejection，不能表述为 120 次全部完成。
- 保留 6 个独立素材族、48 组派生对、Holdout 15/18（83.33\%）、OCR 0/6 和 Critical FAR 33.33\% 中足以支撑失效决策的信息；不得把派生对包装为独立真实样本。
- 不新增人工标注、生产 SLO、远程 MCP、多 Agent 群体协作或模型训练能力等未经验证的主张。

### R4 — 构建与交付

- 更新 `resume-public.tex` 并重新生成 `resume-public.pdf`。
- 保持姓名、教育经历、论文状态、奖项以及两个 12306 项目的既有事实不变。
- 不修改业务代码、不部署、不调用外部模型或 Provider，也不混入当前生产热修任务的改动。

## Acceptance Criteria

- [x] 实习经历的三条内容分别以 Agent Runtime、Tool Calling/MCP/Grounded RAG、Agent Eval 为主标题和主叙事。
- [x] 赛先文化实习日期显示为 `2026.06 - 2026.09`，其他经历日期保持不变。
- [x] 品牌 RAG 与 GLM-5V 指标及限定词均与冻结证据一致，没有夸大实验样本、完成量或线上效果。
- [x] `latexmk -xelatex -interaction=nonstopmode -halt-on-error` 编译成功并收敛。
- [x] 生成 PDF 为单页 A4，关键文字可提取，GitHub 个人主页与个人网站链接仍可点击，且不再包含单独的“27 届”行或项目仓库入口。
- [x] LaTeX 日志无 error、undefined reference、overfull 或 underfull box。
- [x] 变更仅包含简历源文件、生成 PDF 和本任务 Trellis 文件，其他脏工作区内容不被修改或提交。

## Out of Scope

- 不修改 Agent、RAG、MCP、评测或微信公众号业务实现。
- 不调整教育背景、专业技能与两个 12306 项目的内容，除非为保持单页版式必须做纯排版级微调。
- 不部署服务器、不推送 GitHub、不在本任务中补做新的在线实验。

## Delivery

- `docs/portfolio/resume/resume-public.tex`
- `docs/portfolio/resume/resume-public.pdf`
