# 教育部新闻 × 小赛 IP 本地公众号演示

`app.official_account_news_ip_live_demo` 是一次性、操作员显式执行的本地验收器。它不会覆盖旧 run，
不会调用 Comfly、文章模型、Embedding、微信或企微，也不包含发布能力。

预检（不生图）：

```bash
PYTHONPATH=backend conda run --name edu-ai python \
  -m app.official_account_news_ip_live_demo \
  --output-dir output/official-account-news-ip-<new-version> \
  --news-html <verified-moe-news-cache> \
  --plan-html <verified-moe-plan-cache> \
  --preflight-only
```

真实运行需要服务器端 `TOAPIS_API_KEY`，但命令不接受或打印密钥。运行器固定使用 ToApis、每张一次、
总计最多三张；每次调用前先 fsync 独占 intent。超时写为 `result_unknown` 并停止，不会重试或补第四张。

输出目录包含：

- `preview.html` / `article-body.html` / `article.md`：本地文章与相对图片；
- `evidence.json`：两条教育部来源、日期、短引用、正文哈希和事实 claim 绑定；
- `visual-map.json`：正文块锚点、批准的公共 IP 引用、版本、输出校验和与视觉检查状态；
- `run.json` / `manifest.json` / ZIP：安全调用计数、边界与文件完整性；
- `visual-inspection.md`：IP 是否清晰可见，以及文字、Logo、二维码、水印检查结果。

本目录始终是 `LOCAL ONLY · 未同步公众号`，文章人工审稿仍为 pending。输出不得保存 raw prompt、
provider body/task URL、密钥、私有素材路径、对象存储位置或微信/企微标识。
