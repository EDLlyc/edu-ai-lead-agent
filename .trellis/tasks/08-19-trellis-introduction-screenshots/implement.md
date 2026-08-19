# Trellis 简介真实截图：执行计划

## Phase 1 — 证据核验

- [x] 对照现有 manifest 核验 `overview.png` 与 `multi-tool-research.png` 的 capture ID、模式和 SHA-256。
- [x] 核验截图与 summary 中的“本地 loopback、确定性夹具、非 live 模型证明”边界。
- [x] 检查源图不含凭据、私有路径、服务器信息或业务敏感数据。

## Phase 2 — 报告改版

- [x] 为 TeX 增加图像支持并插入独立截图页。
- [x] 嵌入运行总览与裁切后的多工具详情，不复制或改写原图。
- [x] 添加准确标题、图注和证据边界说明。
- [x] 将原总结页顺延，保持整体叙事完整。

## Phase 3 — 验收

- [x] XeLaTeX 编译收敛，PDF 为 6 页。
- [x] 核验 PDF 字体、可复制中文、图片页视觉、页码与布局。
- [x] 复核截图源哈希和 PDF 中的说明文字。
- [x] 扫描 TeX/PDF 的敏感信息并运行 `git diff --check`。
- [x] 更新 `result.md`，记录截图来源、边界与最终验证结果。

## Risky Files and Rollback

- 只修改 Trellis 简介 TeX/PDF 和本任务文件。
- 如截图排版不清晰，恢复报告的已提交版本并重新选择版面；不改截图源文件。
- 不启动服务、不调用模型、不访问服务器，因此无外部副作用。
