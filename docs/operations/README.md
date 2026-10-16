# 运维与交接入口

接手生产系统的人先读这一页，再按下面的表找细节。这里不放任何密码、令牌或证书。

## 先知道这几件事

- **生产代码在分支 `mainline`**，远端是 Codeup 的 `origin`（默认分支也是 `mainline`）。
  本地工作区是 `.trellis/worktrees/mainline`。仓库根目录那棵工作区在别的功能分支上，带未提交的改动，
  不要在那里改生产代码，也不要把它的改动混进 `mainline`。
- **服务器**：`edu-ai-production`（腾讯云 CVM），代码和 compose 在 `/opt/edu-ai-lead-agent`，
  compose 项目名 `edu-ai-lead-agent`，ssh 用户 `ubuntu`，操作要 `sudo`。
- **网址**：运营后台 `https://ops.xiaosaiai.com/admin/`，展台 `https://pgc.xiaosaiai.com/`。
- **不要用 `--remove-orphans`**。有一个孤儿容器 `visitor-display` 是故意留着的。
- **内容时段（北京时间）05:55–06:40、10:55–11:40、16:55–17:40 不要重启内容相关服务**。
  部署脚本会自己等过这些时段。
- **部署不调用大模型，也不发企业微信。** 唯一会发到正式群的操作是后台的「推送到正式群」。

## 怎么部署

生产是一串“覆盖镜像”：在服务器上基于正在运行的镜像摘要 `FROM` 一层，只拷改过的文件，
离线冒烟后再切换。完整步骤、环境变量漂移的坑、回滚方法见
[`.trellis/spec/guides/production-mainline.md`](../../.trellis/spec/guides/production-mainline.md)。
每次部署的脚本和回滚记录在 `.trellis/tasks/10-15-public-hosting/`（`runbook.md` 和各个 `overlay-*` 目录）。
照着最近的 `overlay-*/activate.sh` 改最省事。

三条最容易踩的：

1. 重建容器会重新读 `.env`，各服务创建时间不同，`CONTENT_SCORING_VERSION` 各不相同。
   重建前先记环境哈希，并用 shell 变量把原值固定住，重建后对比。
2. `APP_IMAGE` 写在 shell 里会盖过 `--env-file`。只想换某几个服务的镜像，就在命令前临时加 `APP_IMAGE=…`，
   不要改 `.release.env`（它跟着 API 镜像）。
3. 脚本里 `$(… | grep -c …)` 匹配为 0 时返回 1，会在子 shell 里触发回滚。后面加 `|| true`。

## 文档索引

| 主题 | 文档 |
|---|---|
| 后台：新闻审核和人工加推 | [admin-news-review-and-human-pick.md](./admin-news-review-and-human-pick.md) |
| 后台：系统内置词（营销承诺、焦虑话术） | [admin-builtin-phrases.md](./admin-builtin-phrases.md) |
| 采集：一页读不出不再拖垮整个源 | [acquisition-unreadable-pages.md](./acquisition-unreadable-pages.md) |
| 固定摘要发布与回退 | [digest-release-runbook.md](./digest-release-runbook.md) |
| 生产环境检查清单 | [production-environment-checklist.md](./production-environment-checklist.md) |
| 服务器迁移 | [production-server-migration-runbook.md](./production-server-migration-runbook.md) |
| 本机 MCP 只读运维工具 | [scripts/ops/README.md](../../scripts/ops/README.md) |
| 公网托管部署记录（nginx、证书、每次覆盖） | [runbook.md](../../.trellis/tasks/10-15-public-hosting/runbook.md) |
| 后端 / 前端工程规范 | [backend](../../.trellis/spec/backend/index.md)、[frontend](../../.trellis/spec/frontend/index.md) |

## 还没做的事（交接时请确认有人接）

- 服务器 SSH 只允许密钥登录（现在密码登录还开着）。
- 给运维用的企业微信群配一个健康告警 webhook（不要用正式新闻群）。
- 展厅大屏的会话上限目前是 12 小时，需要定期重新登录。
- 云盘快照和服务器之外的备份；journald 日志大小上限。
- 已发布文章的同步接口。
- 清理已合并的远端分支和旧的 `main`（只有负责人确认后才删）。
- 账号 `liyuchen` 的密码曾贴在聊天里，请本人在「我的账号」里改掉。
- 人工加推第一次真实推送，建议由负责人自己点。
