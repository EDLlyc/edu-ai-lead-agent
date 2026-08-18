# 个人简历

- [下载 PDF](./resume-public.pdf)
- [查看 LaTeX 源文件](./resume-public.tex)

这份公开版本用于 Agent / LLM 应用开发实习投递。仓库保留可复现的 LaTeX
源文件和轻量模板，不依赖项目外的私有字体或个人文件。

## 构建

在仓库根目录运行：

```bash
latexmk -xelatex -interaction=nonstopmode \
  -output-directory=docs/portfolio/resume \
  docs/portfolio/resume/resume-public.tex
```

公开前应再次检查姓名、邮箱、项目链接和项目数据是否适合公开；电话、住址、证件号等
信息不应写入公开版本。
