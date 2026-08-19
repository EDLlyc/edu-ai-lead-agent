# 微信公众号自动推文技术路线汇报：设计说明

> 2026-08-19 改版：报告改为“技术怎么实现”主线，以下结构替代原先偏业务/管理的 9 页结构。

## 1. Deliverables

- `reports/wechat-official-account-auto-publishing-roadmap-2026-08-19.tex`
- `reports/wechat-official-account-auto-publishing-roadmap-2026-08-19.pdf`
- `.trellis/tasks/08-19-wechat-official-account-auto-publishing-roadmap/research/open-source-route-findings.md`

LaTeX 是可编辑源，PDF 是领导直接阅读的汇报件；research 文件保留完整链接、许可证与设计观察，正文仅谨慎列出少量代表性项目名称，并明确它们只作设计参考、未验证可直接上线。

## 2. Evidence Strategy

资料优先级：

1. 微信公众平台官方开发文档：access token、素材上传、草稿箱和发布能力；
2. 公开源码及其 README/文档，用于确认真实模块拆分和数据流；
3. 当前仓库 README、规范和已完成任务，用于确认已有能力；
4. 既有两份公众号汇报只作为表达和视觉参考，不直接复制大段正文。

所有易变化事实写明检索日期。官方页面无法稳定抓取时保留官方 URL，并用公开 SDK 对应接口源码做交叉核验。项目热度不作为技术结论；报告不写 star 数和营销排名。

## 3. Architecture Narrative

报告采用“四层一闭环”的解释方式：

```text
内容生产层
  可信来源 -> 事实治理 -> 候选选题 -> LLM受控排序 -> 长文与配图
                         |
流程与审核层
  任务状态 -> 质量检查 -> 人工审核 -> 退回修改 -> 签发记录
                         |
微信公众号适配层
  Markdown/结构化内容 -> 内联HTML -> 图片/封面上传 -> 创建草稿
                         |
运营复盘层
  发布记录 -> 阅读互动 -> 栏目复盘 -> 规则与模板更新
```

关键边界：生成、排版、平台适配可以自动化；事实责任、版权判断、账号权限和正式发布由人负责。

## 4. Open-source Pattern Synthesis

领导版可用一页谨慎列出代表性方案及其技术启发，研究阶段从公开实现归纳六个可复用思想：

1. **模块化流水线**：写作、配图、排版和草稿同步各自可替换；
2. **中间格式**：用 Markdown 或结构化文章保存内容，再渲染微信兼容 HTML；
3. **媒体适配**：正文图片、封面与文章正文分开处理，上传后替换引用；
4. **平台适配器**：将微信 token、白名单、错误码、频率和草稿接口隔离在独立模块；
5. **人机协作**：默认进入草稿箱，人工预览确认后发布；
6. **可靠性与审计**：缓存 token、幂等记录、有限重试、版本历史、失败可恢复、操作可追踪。

不采用的路线：直接模拟浏览器登录、无人监督自动群发、让 LLM 直接持有公众号密钥、把内容生成和微信接口耦合在一个不可恢复脚本中。

## 5. Report Structure

目标为 7 页：

1. 封面：一句话技术架构与草稿箱边界；
2. 开源方案共性：点名 wechatpy、Wenyan / md2wechat、wechat-publisher、auto-wx-post，说明只作设计参考；
3. 整体技术架构：现有内容生产、文章中间稿、调度与状态、微信适配、人工确认；
4. 端到端处理流程/时序：从任务触发到草稿记录和人工发布；
5. 微信适配实现：token、HTML 内联、正文图片、封面、draft/add、状态记录；
6. 调度与可靠性：Scheduler、Worker、PostgreSQL 权威状态、幂等、有限重试、重启恢复；
7. 最小落地步骤、技术清单与结论。

每页只回答一个“怎么实现”的问题，采用架构图、时序图、状态图和短表格；不再设置业务背景、责任矩阵、泛化风险清单或宽泛管理决策页。

## 6. Visual Design

- 延续 Navy / Blue / Green / Orange 配色，但比完整调研报告更克制；
- 使用 XeLaTeX、中文字体、A4 和统一页眉页脚；
- 用 TikZ 绘制整体架构图、端到端时序图、微信适配链和任务状态/恢复图，避免外部图片依赖；
- 表格最多 4 列，使用短句和图标式编号；
- 封面标注“技术路线汇报”，日期为 2026 年 8 月 19 日；
- 不使用复杂代码框、数据库结构图或过密网络拓扑。

## 7. Compatibility and Safety

- 不覆盖或还原用户已修改的 `reports/wechat-digital-employee-briefing-2026-08-18.*`；
- 不修改 8 月 17 日完整调研报告；
- 不使用真实账号、密钥、服务器或内部业务数据；
- 不运行微信接口、供应商模型或生产服务；
- 外部链接只存在于研究记录，PDF 正文可以在末页用“资料来源：微信官方开发文档、公开技术实现”概括。

## 8. Validation

- `latexmk -xelatex -interaction=nonstopmode -halt-on-error` 编译到收敛；
- `pdftotext` 检查章节、中文和关键结论；
- `pdfinfo` 检查页数为 6--8；
- `pdffonts` 检查字体嵌入；
- 渲染全部页面进行视觉抽查；
- 检查 overfull、missing glyph、undefined reference；
- 对 TeX/PDF 做密钥、账号、私有路径和服务器信息扫描；
- 用 Git diff 确认昨日两份报告未被本任务改写。
