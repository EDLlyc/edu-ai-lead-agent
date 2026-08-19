# Trellis 任务规范示例：交付结果

## 交付物

- `reports/trellis-introduction-brief-2026-08-19.tex`：更新后的可编辑 XeLaTeX 源文件。
- `reports/trellis-introduction-brief-2026-08-19.pdf`：更新后的 5 页 A4 中文分享材料。

## 完成内容

- 移除了原有的运行截图页、图片依赖和相关叙述，未修改截图源或作品集文件。
- 将原有“适合的工作 / 不该期待的事”和总结恢复到第 5 页。
- 在第 5 页新增“一个真实任务，怎样连接规则与结果”三卡片示意：Task 记录目标、需求与验收、设计与执行、结果；Spec 说明动手前确认范围并使用已有约定；Output 列出可编辑源、成品及编译与检查记录。
- 明确标注该内容为“基于真实任务结构的简化示意”，并说明任务会按复杂度保留必要工件，简单事项可以更轻。

## 验证结果

- XeLaTeX 构建成功并收敛；PDF 为 5 页 A4。
- 构建日志无 Overfull、Underfull 或 LaTeX Warning；页面 5 渲染视觉抽查通过，三张卡片、双栏边界说明与总结无重叠或裁切。
- `pdffonts` 显示 4 个中文字体子集均已嵌入并提供 Unicode 映射；`pdftotext -layout` 可正常提取中文正文及 Task、Spec、Output 内容。
- TeX 源中不再包含 `graphicx`、`includegraphics`、Agent Workbench、deterministic、loopback 或截图目录引用；提取文本与源文件的敏感信息扫描未发现私人路径、Git SHA、会话记录、服务器信息或凭据形状。
- `git diff --check` 通过。未运行服务、浏览器、模型或外部工具。
