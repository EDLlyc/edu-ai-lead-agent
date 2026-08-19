# 2026 年 8 月 10 日—16 日工作周报：交付结果

## 交付物

- `reports/weekly-report-2026-08-10-16.tex`：可编辑中文 A4 周报源文件。
- `reports/weekly-report-2026-08-10-16.pdf`：5 页、A4、中文可复制的 PDF。

报告覆盖内容与交付、图片与供应商、科学/教育选题、三时段生产、发布与稳定性，并明确记录：

- CAST/EdSurge DNS 已恢复，但确定性发现仍为 `parse_failure`，保持待解析、未接入。
- 受控视觉验收媒体门通过，但智谱 OCR 返回 `provider_request_rejected`；视觉多样性/OCR 生产开关保持关闭，零重试、零企业微信增量。
- 复用依赖层仅作为发布 workaround，不表述为产品能力。

## 验收记录

- XeLaTeX/latexmk 编译通过，输出 5 页 A4 PDF，未加密。
- `pdfinfo`：Pages 5、Page size A4、Encrypted no。
- `pdffonts`：中文 Noto Sans/Serif CJK 字体均嵌入，Unicode 映射可用。
- `pdftotext`：中文正文、关键状态和下周计划可复制提取；未发现残留 `bottomrule` 等排版命令。
- 渲染检查：5 页均成功渲染为 PNG，抽查首页、验收表页和问题页，未见明显溢出或缺字。
- 隐私扫描：TeX/PDF 未命中公网 IP、私有路径、token/password/secret/API key、长 SHA-256 或 run ID 模式。
- `git diff --check`：通过。

## 限制与后续

未访问服务器、新闻源、模型、图片供应商、企业微信或公众号；未修改业务代码、生产数据和既有报告。工作区中原有的 `reports/` 修改及其他删除项保持不动。
