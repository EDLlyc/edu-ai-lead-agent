# 已确认部署上下文

- 本机 OpenSSH 配置存在 `edu-ai-production` host alias；尚未连接服务器。
- 生产运行目录与只读检查命令来自 `docs/operations/production-server-migration-runbook.md`。
- 2026-09-02 周任务激活结果：生产周调度器 `due=false`，首次 eligible execution 是
  `2026-09-07 09:00 Asia/Shanghai`；任务只能生成三篇未发布公众号草稿。
- 企业微信日常发送由独立 `wecom-dispatcher` 和 durable delivery tables 负责，不能从公众号周任务
  的零计数推断日常发送正常或异常。
- 服务器当前 release identity、服务状态和 2026-09-04 durable rows 仍待只读验证。

## Sources

- `.trellis/tasks/archive/2026-09/09-02-wechat-weekly-scheduler-production/result.md`
- `.trellis/tasks/archive/2026-09/09-01-wechat-draft-production-deploy/result.md`
- `.trellis/spec/backend/agent-pipeline.md`
- `.trellis/spec/backend/content-slot-production.md`
- `.trellis/spec/backend/wecom-delivery.md`
- `docs/operations/production-server-migration-runbook.md`
