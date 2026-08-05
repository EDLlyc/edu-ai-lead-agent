# 执行计划

## 顺序清单

1. [x] 读取任务状态，核对 git diff、正式 Docker health、worker 配置和品牌视觉 manifest。
2. [x] 实现本地测试 runner，复用当前 API/worker 配置并生成脱敏 preview manifest。
3. [x] 实现前端真实预览页面，读取 manifest，展示阶段状态、文案、图片、来源和审计问题。
4. [x] 使用真实来源、智谱和 Comfly 执行一次完整测试，记录本地数据库/MinIO 的真实 ID，并
      导出 `output/preview/<run-id>/`。
5. [x] 检查正式日锁定结果没有被修改，确认本次新增记录可由正式 API 查询。
6. [x] 用浏览器/Playwright 检查桌面和移动布局、文案复制、图片展示和失败状态。
7. [x] 若有代码缺陷，先补最小修复和相关测试，再重建受影响服务并重跑预览。
8. [x] 运行后端/前端质量检查，核对无凭据、临时 URL或内部对象路径泄漏，整理真实结果报告。
9. [x] 将教育部 Top 1 收紧为科学教育政策/行动优先，创建新版本配置和回归测试，并使用新的
      隔离业务日期验证其不会强制优先非科学教育部新闻。
10. [ ] 后续正式分发任务（另建任务）：设计并实现企业微信自建应用单销售 `userid` 的
        durable delivery 阶段；当前预览验收不得发送真实消息，前端只做查看。

## 验证命令

- `docker compose ps`
- `curl -fsS http://127.0.0.1:8000/healthz`
- `file output/preview/<run-id>/*.png`
- `identify -format '%wx%h' output/preview/<run-id>/*.png`（若 ImageMagick 可用）
- `make frontend-check`
- `python -m pytest backend/tests/unit/test_image_generation.py -q`
- `git diff --check`

## 风险点

- 实时来源可能在 10 天窗口内没有合格的教育部科学新闻；此时验收应报告 no_topic，而不
  伪造 Top 1。
- Comfly 可能返回配额、认证、临时 CDN 或尺寸错误；每种情况都必须保留安全错误码。
- 智谱模型输出可能触发一次修复或人工复核；不能把 review_required 当作成功。
- 预览数据库/MinIO 隔离边界误配会污染正式数据，必须在启动前打印并校验目标资源标识。

## 退出条件

完成 PRD 验收项，或明确记录第一个阻塞终态、其 API 响应、服务日志中的安全错误码和未完成
的后续阶段；无论成功或失败都不自动发布。
