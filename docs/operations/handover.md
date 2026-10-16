# 交接

给接手生产的人。核对时间 2026-10-16。这里没有密码、密钥和证书。

改生产代码在 `.trellis/worktrees/mainline`。仓库根目录是另一条分支，上面有未提交的展台改动，不要在那里改，也不要整支合并进 `mainline`。

## 1. 代码和线上

线上跟的是 Codeup 分支 `mainline`，不是 `release/wechat-notice-production-20260923`。

- `3e62b33`（2026-09-22）已经在 `mainline` 里，不用再合。
- 那条 9 月 23 日的分支只剩一个提交没进来：`a9db34f8`，提交公众号草稿时去掉内部权利声明。要这条行为就单独移植，不要整支合并。
- 文档里的 `mainline` 最新提交是 `6e585505`（2026-10-16）。服务器上的镜像不是这一个提交打出来的，而是一层层叠上去的。发布前先在服务器上看正在跑的摘要，不要凭 git 猜。

2026-10-16 下午核对过的镜像（短摘要，发布前再 `docker inspect` 一次）：

| 服务                                                 | 镜像       | 最近一次改动     |
| ---------------------------------------------------- | ---------- | ---------------- |
| `acquisition-api`（`.release.env` 里的 `APP_IMAGE`） | `5d021b23` | 系统内置词       |
| `content-worker`、`content-scheduler`                | `9ccecd8a` | 写稿时读内置词   |
| `acquisition-worker`                                 | `5861c058` | 读不出的页面跳过 |
| `wecom-dispatcher`                                   | `da052082` | 更早             |
| `acquisition-scheduler`、治理和周调度                | `83a41e41` | 更早             |
| `governance-worker`、公众号相关 worker               | `6226855a` | 更早             |
| `wecom-infographic-producer`                         | `e0513020` | 长图失败日志     |

数据库迁移到 `20261016_0063`。各服务的 `CONTENT_SCORING_VERSION` 不一样（采集 API 和内容服务是 `.17`，企微分发和采集 worker 是 `.15`，采集调度是 `.11`）。重建容器会重读当前 `.env`，把这个值冲掉。

每次覆盖的备份目录和回滚命令在 [公网托管记录](../../.trellis/tasks/10-15-public-hosting/runbook.md)。镜像表的来源是 [production-mainline.md](../../.trellis/spec/guides/production-mainline.md)。

## 2. 这台机器

|        |                                                                                                 |
| ------ | ----------------------------------------------------------------------------------------------- |
| 主机   | 腾讯云 CVM，上海，`124.222.207.221`，SSH 别名 `edu-ai-production`，用户 `ubuntu`，操作加 `sudo` |
| 目录   | `/opt/edu-ai-lead-agent`（compose、`.env`、`.release.env`）                                     |
| 项目名 | `edu-ai-lead-agent`                                                                             |
| 后台   | https://ops.xiaosaiai.com/admin/ ，静态文件在 `/var/www/edu-ai-admin`                           |
| 展台   | https://pgc.xiaosaiai.com/                                                                      |
| 证书   | `/etc/nginx/ssl/xiaosaiai.com.{crt,key}`，2027-04-09 前要续                                     |

2026-10-16 13:33 时 `docker ps` 是 17 个容器。`visitor-display` 不在主 `compose.yaml` 里，是展台的只读适配，故意留着。不要加 `--remove-orphans`。

| 容器在干什么       | 服务                                                                |
| ------------------ | ------------------------------------------------------------------- |
| 数据库、对象存储   | `postgres`、`minio`                                                 |
| 后台 API           | `acquisition-api`                                                   |
| 抓新闻             | `acquisition-scheduler`、`acquisition-worker`                       |
| 选题、写文案、配图 | `content-scheduler`、`content-worker`                               |
| 发到企微群         | `wecom-dispatcher`                                                  |
| 长图               | `wecom-infographic-producer`（不跟 `APP_IMAGE`，单独指定镜像）      |
| 事实治理           | `governance-scheduler`、`governance-worker`                         |
| 公众号周稿和草稿   | `official-account-weekly-*`、`wechat-official-account-draft-worker` |
| 展台只读           | `visitor-display`                                                   |

IP 图库（`ip-assets`）和「公众号本地草稿台」是另两套 profile，生产没挂这套演示。

**发布。** 在服务器上 `FROM` 正在跑的镜像，只拷改过的文件，离线冒烟，再只重启改到的服务。照最近的 `.trellis/tasks/10-15-public-hosting/overlay-*/activate.sh` 改。

- 北京时间 05:55–06:40、10:55–11:40、16:55–17:40 不重启内容服务。
- 部署不调模型，不发企微。发到正式群只有后台「推送到正式群」。
- 命令前的 `APP_IMAGE=…` 盖过 `--env-file`。只换一两个服务时用它。`.release.env` 跟着 API 镜像。
- 重建前记下该容器的环境哈希，用 shell 变量钉住原来的 `CONTENT_SCORING_VERSION`，重建后再比对。
- 脚本里 `$(… | grep -c …)` 零匹配时返回 1，会在子 shell 里触发回滚。写成 `|| true`。

**回滚。** 用当次 `activate.sh` 的备份目录：换回旧镜像，后台目录拷回 `/var/www/edu-ai-admin`。有数据库迁移的那次（内置词）还要在 API 容器里 `alembic downgrade`。具体命令写在 runbook 对应那一节，不要用一份旧备份去回滚后来的发布。

**日志。** `sudo docker logs --since 30m <容器名>`。长图失败搜 `news_infographic_stage_unknown`。采集跳过搜 `acquisition_item_parse_skipped`。

**备份。** 在同一台机器的 `/opt/edu-ai-lead-agent/backups/`。内置词那次有 `pg_dump`。没有云盘快照，也没有服务器以外的副本。库挂了，这些备份一起没。

**本机查生产库。** 只读账号和 SSH 隧道见 [scripts/ops/README.md](../../scripts/ops/README.md)。`scripts/doctor.sh` 检查的是开发机（Conda、本机 compose），不要拿到生产主机上去跑。

## 3. 账号和密钥

下面只列名目。密钥在服务器 `.env` 和各自的控制台里，不写进仓库。移交时由现在的负责人逐项改密、转权限，再撤掉原人的访问。

| 项                                   | 在谁手里 | 接手人 | 已轮换 |
| ------------------------------------ | -------- | ------ | ------ |
| Codeup 仓库                          |          |        |        |
| GitHub 备份仓库                      |          |        |        |
| 服务器 SSH（`ubuntu`）               |          |        |        |
| 腾讯云 CVM                           |          |        |        |
| 阿里云（如果账单或域名在那边）       |          |        |        |
| 容器镜像仓库 ACR（如果还在用）       |          |        |        |
| 企业微信：正式新闻群机器人           |          |        |        |
| 企业微信：运维告警（还没有单独的群） |          |        |        |
| 微信公众号 AppID / AppSecret         |          |        |        |
| 智谱等模型 API key                   |          |        |        |
| 后台 owner 账号                      |          |        |        |
| 域名和证书（`*.xiaosaiai.com`）      |          |        |        |

后台账号 `liyuchen` 的密码曾经出现在聊天里。请本人登录 https://ops.xiaosaiai.com/admin/ 的「我的账号」改掉。

## 4. 现在什么在跑

在跑的是朋友圈短文这条链：采集、治理、选题、文案、配图、长图，经人工审核后发到内部企微群。运营后台能管新闻源、关键词、系统内置词、新闻审核和人工加推。

| 模块                               | 状态                                                                                      |
| ---------------------------------- | ----------------------------------------------------------------------------------------- |
| 采集、选题、文案、企微、长图、后台 | 在线上                                                                                    |
| 展台 `pgc.xiaosaiai.com`           | 在线上，只读，用后台同一套登录                                                            |
| 公众号                             | 线上 worker 的模式是 `draft_only`，只建草稿，不群发。开关默认是关的，以服务器 `.env` 为准 |
| 公众号本地草稿台、Workbench        | 只在开发机，不进生产 API                                                                  |
| IP 图库 `/ip-assets`               | 本机功能，默认关闭，没有鉴权                                                              |

还没做：

- SSH 改成只允许密钥登录。
- 运维告警用单独的企微群。
- 云盘快照和异地备份；journald 日志上限。
- 展厅大屏会话 12 小时过期。
- 已发布文章的同步接口。
- 已合并的远端分支和旧 `main`，等负责人确认再删。
- 人工加推的第一次真实推送，由负责人自己点。

## 5. 架构和接口

```text
新闻源 → 采集 worker → 事实治理 → 选题 / 文案 / 配图 → 素材包
                                              ↓
                                    长图 → 企微分发（正式群）
后台（ops）读写新闻源、关键词、内置词、审核意见、人工加推
展台（pgc）只读同一套新闻，登录态跟后台共用
```

机器可读的接口清单是 `backend/openapi.json`，139 个操作都有一行摘要，那一行多半是函数名翻译，不是给人看的说明。字段说明几乎没写。交接够用的是后台这几条，都要登录，写操作加请求头 `X-Admin-Request: 1`：

| 做什么               | 方法                                                                  |
| -------------------- | --------------------------------------------------------------------- |
| 登录、当前账号       | `POST /api/v1/admin/auth/login`，`GET /api/v1/admin/auth/me`          |
| 新闻源               | `/api/v1/admin/sources`                                               |
| 关键词、系统内置词   | `/api/v1/admin/keywords`，`/api/v1/admin/builtin-phrases`             |
| 新闻审核（只记意见） | `/api/v1/admin/news-reviews`                                          |
| 人工加推             | `POST /api/v1/admin/human-picks` 只生成；`POST .../push` 才发到正式群 |

新闻审核和人工加推的拒绝码、内置词怎么生效，见同目录的两篇说明。企微只从分发 worker 出去。公众号对接是草稿 API（`api.weixin.qq.com`），代码里 `WECHAT_MP_MODE=draft_only`。

## 6. 仓库

权威远端是 Codeup。GitHub 是单向备份，不反向覆盖，也不触发部署。仓库归属和账单账号要确认在公司名下。

可以挪出仓库、不必跟生产代码放在一起的：`docs/portfolio/resume/`（简历）、`.trellis/workspace/`（个人会话记录）。这次没有挪。
