# 运维与交接

生产跑的是分支 `mainline`（Codeup `origin`）。改生产代码在 `.trellis/worktrees/mainline`。仓库根目录是另一条分支，上面有未提交改动，不要在那里改。

- 服务器：`edu-ai-production`（腾讯云），目录 `/opt/edu-ai-lead-agent`，`ssh ubuntu`，命令加 `sudo`
- 后台：https://ops.xiaosaiai.com/admin/
- 展台：https://pgc.xiaosaiai.com/

## 部署

在服务器上给正在跑的镜像叠一层：`FROM` 当前摘要，只拷改过的文件，离线冒烟，再切换。只重启改到的服务。

- 步骤和各服务现在的镜像：[production-mainline.md](../../.trellis/spec/guides/production-mainline.md)
- 每一次覆盖的备份和回滚：[runbook.md](../../.trellis/tasks/10-15-public-hosting/runbook.md)
- 脚本照最近的 `overlay-*/activate.sh` 改，目录在 `.trellis/tasks/10-15-public-hosting/`

注意这几条：

- 北京时间 05:55–06:40、10:55–11:40、16:55–17:40 不重启内容服务。脚本会自己等到时段结束。
- 部署不调模型，不发企微。发到正式群只有后台的「推送到正式群」。
- 不要加 `--remove-orphans`。`visitor-display` 是故意留下的容器。
- 重建会重读 `.env`。各服务的 `CONTENT_SCORING_VERSION` 不一样：先记下环境哈希，用 shell 变量钉住原值，重建后再比对。
- 命令前的 `APP_IMAGE=…` 盖过 `--env-file`。只换一两个服务时用它。`.release.env` 保持跟 API 镜像一致。
- `$(… | grep -c …)` 零匹配时返回 1，会在子 shell 里触发回滚。写成 `|| true`。

## 按主题看

| 主题                 | 文档                                                                                               |
| -------------------- | -------------------------------------------------------------------------------------------------- |
| 发版、本地运行、账号 | [交接资料](../handover/README.md)                                                                  |
| 交接                 | [handover.md](./handover.md)                                                                       |
| 新闻审核、人工加推   | [admin-news-review-and-human-pick.md](./admin-news-review-and-human-pick.md)                       |
| 系统内置词           | [admin-builtin-phrases.md](./admin-builtin-phrases.md)                                             |
| 采集：单页读不出     | [acquisition-unreadable-pages.md](./acquisition-unreadable-pages.md)                               |
| 固定摘要发布         | [digest-release-runbook.md](./digest-release-runbook.md)                                           |
| 上线检查清单         | [production-environment-checklist.md](./production-environment-checklist.md)                       |
| 迁服务器             | [production-server-migration-runbook.md](./production-server-migration-runbook.md)                 |
| 本机只读查询         | [scripts/ops/README.md](../../scripts/ops/README.md)                                               |
| 后端 / 前端规范      | [backend](../../.trellis/spec/backend/index.md)、[frontend](../../.trellis/spec/frontend/index.md) |

## 还没做

- SSH 改成只允许密钥登录。
- 运维告警单独一个企微群，不用正式新闻群。
- 展厅大屏会话 12 小时过期，要重新登录。
- 云盘快照、服务器以外的备份、journald 日志上限。
- 已发布文章的同步接口。
- 已合并的远端分支和旧 `main`，等负责人确认再删。
- `liyuchen` 的密码在聊天里出现过，请本人到「我的账号」改掉。
- 人工加推的第一次真实推送，由负责人自己点。
