# Trellis 简介分享：设计说明

## 1. Deliverables

- `reports/trellis-introduction-brief-2026-08-19.tex`
- `reports/trellis-introduction-brief-2026-08-19.pdf`
- `.trellis/tasks/08-19-trellis-introduction-brief/research/local-trellis-overview.md`

TeX 是可编辑源文件，PDF 是可直接分享的成品；research 记录本项目内用于核验内容的权威来源和表达边界。

## 2. Narrative

全文围绕一个问题展开：**如何让 AI 不只是临时写代码，而是在项目规则和可追踪流程中持续协作？**

推荐叙事：

```text
常见问题
上下文容易丢失、每次重复说明、规范容易漂移、结果难复核
   ↓
Trellis 的做法
把工作流、任务、项目规范和会话记录放进仓库
   ↓
一次任务如何运行
规划 → 读取规范 → 实现 → 检查 → 归档 → 后续复用
   ↓
实际价值
更连续、更透明、更容易协作，但质量仍需测试、评审和 Git 保证
```

## 3. Page Structure

目标 4--5 页：

1. **封面与定义**：Trellis 是什么；一句话价值；不是什么。
2. **为什么需要**：AI 辅助开发常见的四个断点，以及 Trellis 如何补齐。
3. **怎样工作**：生命周期流程图，解释计划、规范、实现、检查、归档。
4. **核心组成与示例**：Workflow、Tasks、Specs、Workspace/Memory 表格，加一个“新增功能”示例。
5. **适用场景与总结**：团队/个人使用价值、Git 与模型边界、Channel/多智能体/Memory 作为进阶能力。

如第 4、5 页内容较少，可合并为 4 页，优先保证简洁。

## 4. Information Architecture

核心组成采用四张卡片或一张两列表：

| 组成 | 通俗解释 |
| --- | --- |
| Workflow | 规定现在处于哪一步、下一步该做什么 |
| Tasks | 保存一项工作的需求、设计、计划和结果 |
| Specs | 保存这个项目自己的开发规则和边界 |
| Workspace / Memory | 保存进展和经验，让下一次会话可以接着做 |

辅助能力只放在页脚式提示中：复杂工作可以由实现、检查等不同角色协作；Channel 提供实时多智能体协作；`trellis mem` 用于回看过去会话。这些能力不改变四个主体概念。

## 5. Visual Design

- XeLaTeX + 中文字体 + A4；使用 11pt 左右正文。
- 主色为深蓝，辅色为浅紫和青绿；白底、宽留白、少量圆角卡片。
- 使用 TikZ 绘制一个横向生命周期图；核心组成使用简洁表格或 2×2 卡片。
- 每页只保留一个主结论，正文采用短段落和短列表。
- 不使用截图、网络图片、Logo 或字体资产，避免版权和外部依赖。
- 页脚显示标题缩写和页码，不显示机器路径、Git SHA 或内部任务编号。

## 6. Accuracy Boundaries

- Trellis 被表述为项目内的 AI 开发协作框架，不是模型本身。
- `.trellis/workflow.md` 是工作流来源；`.trellis/tasks/`、`.trellis/spec/`、`.trellis/workspace/` 分别承担任务、规范、会话/经验持久化。
- 平台集成层可把这些规则连接到不同 AI 工具，但正文不罗列平台名称。
- Git 继续负责代码版本；测试和评审继续负责质量判断。Trellis 只让这些动作更有流程和上下文。
- 不展示当前仓库的业务内容、开发者身份、会话日志或具体私有路径。

## 7. Validation

- 使用 `latexmk -xelatex -interaction=nonstopmode -halt-on-error` 编译到收敛。
- 用 `pdfinfo` 检查 A4、页数和未加密状态。
- 用 `pdffonts` 检查字体嵌入，用 `pdftotext` 检查中文与核心结论。
- 检查构建日志中的 overfull、missing glyph、undefined reference 和 package warning。
- 将全部页面渲染为图片并逐页抽查裁切、重叠、字号和信息密度。
- 扫描 TeX/PDF 中的凭据形状、私人路径、服务器信息和内部业务词。
- 使用 Git diff 确认只新增本任务和新报告，没有覆盖用户已有修改。
