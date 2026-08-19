# Trellis 简介真实截图：设计说明

## 1. Deliverables

- 更新 `reports/trellis-introduction-brief-2026-08-19.tex`
- 更新 `reports/trellis-introduction-brief-2026-08-19.pdf`
- 新增 `.trellis/tasks/08-19-trellis-introduction-screenshots/research/screenshot-provenance.md`

不复制、移动或修改 `docs/portfolio/runs/agent-workbench/...` 下的原始证据文件。

## 2. Screenshot Selection

| 位置 | 原始文件 | 作用 | 边界 |
| --- | --- | --- | --- |
| 运行总览 | `overview.png` | 展示完成、受控校验、安全拒绝三类真实本地运行 | 仅证明脱敏确定性夹具的本地闭环 |
| 多工具详情 | `multi-tool-research.png` | 展示问题、受控工具、引用结论与观测轨迹 | 不证明供应商模型或线上数据效果 |

两张图片均来自同一 capture ID，manifest 记录它们与浏览器 API/UI 语义一致。LaTeX 只以 `trim` + `clip` 处理多工具详情的底部冗长轨迹，使关键界面在 A4 页面中可读；不会改写图中内容。

## 3. Report Layout

新增第 5 页“真实项目运行记录”，原“适合谁用”总结页顺延为第 6 页：

```text
第 5 页
  标题：真实项目运行记录：每一步都能回看
  小注：真实 loopback 运行；脱敏 deterministic fixture；非线上模型效果证明
  图 1：三类运行总览（宽图）
  图 2：多工具研究详情（裁切后宽图）
  两行解释：什么被证明，什么没有被证明
```

截图页只介绍“可复核运行记录”的价值，不新增 Agent Workbench 功能介绍、模型名称、服务地址、时间戳、命令或 API 参数。

## 4. Caption Contract

建议文案：

- 总览图：`真实项目本地运行总览：完成、受控校验与安全拒绝都留下可查看的结果。`
- 详情图：`多工具详情：问题、受控工具、引用结论与过程观测在同一条运行记录中对应。`
- 证据注：`图中使用脱敏确定性夹具，证明本地执行链和可检查边界；不代表线上模型能力或生产运行情况。`

## 5. Validation

- 用 manifest 对照两张源图的 SHA-256 与 capture ID。
- 编译 PDF 后检查页数为 6、图片无失真/裁切错误、中文图注可读。
- 使用 `pdftotext` 检查新的边界说明存在。
- 渲染第 5 页与相邻页，检查图像清晰度、留白、页码和页间顺序。
- 重新运行 PDF 元数据、字体、敏感信息与 Git diff 检查。
