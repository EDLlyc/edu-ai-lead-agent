# 运营后台：新闻审核和人工加推

给后来改这两块的人。生产线上的代码在 git 分支 `mainline`，工作区是
`.trellis/worktrees/mainline`。仓库根目录那棵工作区有未提交的展台改动，不要在那里改后台。

页面在 `https://ops.xiaosaiai.com/admin/` 的「内容来源 → 新闻审核」。owner 和 editor 都能用。
审核人记的是登录账号。

接口约定（给改代码的人，英文）：`.trellis/spec/backend/admin-console.md` 末尾一节，
前端约束在 `.trellis/spec/frontend/admin-console.md`。

## 两件事各做什么

**新闻审核**只记意见。看 AI 最近选上和没选上的新闻，点「适合推」或「不适合推」，可以写备注。
它不改选题结果，不发任何消息。

**人工加推**把一条 AI 没选上的新闻额外发到正式家长群。分四步：

1. 「生成文案和配图」：排队写文案、配图，然后留住。这一步不发群。
2. 等几分钟。状态会从「排队中」到「正在写文案」「正在配图」，页面大约每 20 秒刷新一次。
3. 「等你确认」：只能改引导语和话题标签。先「检查文案」，再「保存修改」。规则不通过就不能推。
4. 「推送到正式群」要点两次：第一次看完整文案，第二次确认发出去后不能撤回。

AI 已经选上的新闻没有这个按钮。每天 22:30（北京时间）以后不能再加推，当天没推的作废。
同一条再推一次会被拒绝。

## 代码在哪

后台页面，都在 `frontend/src/features/admin/newsreviews/`：

| 文件 | 作用 |
|---|---|
| `NewsReviewPage.tsx` | 列表、筛选、搜索、盲审、加推入口 |
| `HeldPickEditor.tsx` | 改引导语和标签，两次确认后才推送 |
| `api.ts` | 调接口；拒绝原因码对应的中文句子也在这里 |
| `reviewModel.ts` | 把多场新闻合成一条、算和 AI 的一致率、加推状态的中文 |
| `sections.ts` 里的 `news-review` | 菜单项，分组「内容来源」，editor 可用 |

后端：

| 文件 | 作用 |
|---|---|
| `backend/app/api/v1/routes/admin_news_reviews.py` | 读新闻池、记一条意见 |
| `backend/app/api/v1/routes/admin_human_picks.py` | 创建、读文案、改文案、推送 |
| `backend/app/infrastructure/db/news_reviews.py` | 意见表。同一条新闻后一次意见覆盖前一次 |
| `backend/app/application/services/human_pick_review.py` | 检查并保存修改、执行推送 |
| `backend/app/infrastructure/db/content_slot_human_picks.py` | 创建加推、22:30 截止、当天重复和已发过的拒绝 |
| `backend/app/infrastructure/db/visitor_display.py` | 新闻池，以及一条加推当前的文案（`load_human_pick_review`） |

意见存在表 `news_reviews`，迁移是 `backend/alembic/versions/20261015_0062_news_reviews.py`。
加推没有新表，用的是原来的选题、文案、素材包和企微发送记录。

新闻在接口里的编号（`key`）由服务器算出来。页面不能自己传运行编号或事件编号。

## 接口

都在 `/api/v1/admin` 下，要登录。除了读取，每个写操作都要带请求头 `X-Admin-Request: 1`。

| 操作 | 方法 | 结果 |
|---|---|---|
| 读新闻池 | `GET /admin/news-reviews` | 最近几场新闻，带 AI 判断和已有意见、加推进度 |
| 记意见 | `POST /admin/news-reviews` | `agree` / `include` / `exclude`，备注可空 |
| 开始加推 | `POST /admin/human-picks` | 只生成并留住，不发送 |
| 读待审文案 | `GET /admin/human-picks/{key}/review` | 标题、引导语、标签、能不能改、截止时间 |
| 检查或保存 | `POST /admin/human-picks/{key}/copy` | `dry_run: true` 只检查；通过了才保存 |
| 推送 | `POST /admin/human-picks/{key}/push` | 唯一会发到正式群的一步 |

未登录这些地址返回 401。常见拒绝（409）和页面上的话：

| 代码 | 页面上的话 |
|---|---|
| `human_pick_already_selected` | 这条新闻今天已经入选过了 |
| `human_pick_already_delivered` | 之前已经推送过企微群了 |
| `human_pick_slot_busy` | AI 正在选题，稍后再试 |
| `human_pick_no_lineage` | 今天的第一场还没选完题 |
| `human_pick_too_late` | 22:30 以后不再加推 |
| `human_pick_not_ready` | 文案或配图还没好 |
| `human_pick_already_pushed` | 这条已经推送过了 |
| `human_pick_expired` | 过了当天 22:30，作废 |
| `human_pick_copy_invalid` | 文案还有不通过的规则 |
| `content_slot_disabled` | 内容生产没开 |

新增一种拒绝时，在 `api.ts` 里补上对应的中文，页面才能显示人话。

## 改的时候注意

- 文案和配图是 `content-worker` 生成的，推送也走它已有的发送逻辑。2026-10-16 这次上线只换了
  `acquisition-api` 和后台页面，因为 worker 里本来就有加推。以后如果改「怎么写文案」或「怎么发企微」，
  要同时更新 `content-worker`，只换 API 不够。
- 改了接口要重新生成类型：在 `backend` 里把新路径合并进 `openapi.json`（键按字母排序），
  然后在 `frontend` 跑 `npm run generate:api`，再用 `npm run generate:api:check` 确认一致。
- 后台页面的测试注入假的 `NewsReviewsApi`，不要在测试里访问真实接口。
- 展台还有一套用 PIN 和 SSH 隧道的本地加推（`visitor_display_human_pick.py`）。后台这条线不走它。
  两套不要合成一个入口，除非单独决定拆掉展台那套。

## 怎么验证

在仓库根目录、用项目的 Python 环境：

```bash
python -m pytest backend/tests/integration/test_admin_news_reviews.py \
  backend/tests/integration/test_admin_human_picks.py -p no:cacheprovider --no-cov
```

集成测试要本机 Postgres。收尾时如果报 MinIO `127.0.0.1:9000` 连不上，这是环境问题，测试本身已经跑完。

前端在 `frontend` 目录：

```bash
npx vitest run src/features/admin/newsreviews
npx tsc -p tsconfig.app.json --noEmit
npx eslint src/features/admin --max-warnings 0
```

## 部署和回退

生产机是 `edu-ai-production`，目录 `/opt/edu-ai-lead-agent`，用 `sudo`。只重设 `acquisition-api`，
不要加 `--remove-orphans`（会碰到展台那个容器）。

内容时段内不要动：北京时间 05:55–06:40、10:55–11:40、16:55–17:40。

2026-10-16 的记录：

- API 镜像 `…backend@sha256:98b9d189dd623b0ff7a8818c481b30e044a911402508c48b43f7c10a1359acfe`
  （标签 `human-pick-48b754a`），叠在上一版 `0ab05e2e…` 上。
- 后台页面脚本 `index-Bv_d0aQo.js`。
- 数据库版本仍是 `20261015_0062`，这次没有新迁移。
- 主机备份 `/opt/edu-ai-lead-agent/backups/human-pick-20261016.rDXRYN`。
- 构建和激活脚本在 `.trellis/tasks/10-15-public-hosting/overlay-human-pick/`。
  新闻审核那次的脚本在同目录的 `overlay-news-review/`。

回退：把 `.release.env` 里的 `APP_IMAGE` 改回 `…@sha256:0ab05e2e9afd3afb55ee299ea2641d3374614aa35e1d845da3884c29e3bf0e6c`，
只重建 `acquisition-api`，再把备份里的 `www.before` 拷回 `/var/www/edu-ai-admin`。

部署步骤的流水账在 `.trellis/tasks/10-15-public-hosting/runbook.md`。
