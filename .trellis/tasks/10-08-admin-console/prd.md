# 运营后台（8 项功能）

Owner request 2026-10-08: build these in this order. The schedule was sent and accepted
("好的，请你处理"). About 6 weeks, from 10/8 to 11/17.

| # | Task | Effort | Dates |
|---|---|---|---|
| 0 | `10-08-admin-0-login-shell` 后台登录 + 设置页框架 (prerequisite) | 1.5 d | 10/8–10/9 |
| 1 | `10-08-admin-1-news-sources` 新闻源增删改 | 3 d | 10/9–10/14 |
| 2 | `10-08-admin-2-keywords` 关键词增删改 | 3 d | 10/14–10/19 |
| 3 | `10-08-admin-3-wechat-publish` 公众号发布、定时发布 | 4 d | 10/19–10/23 |
| 4 | `10-08-admin-4-wechat-stats` 公众号文字数据统计 | 3 d | 10/23–10/28 |
| 5 | `10-08-admin-5-wechat-accounts` 公众号绑定和配置（多账号） | 4 d | 10/28–11/3 |
| 6 | `10-08-admin-6-layout-templates` 排版模板选择 | 2 d | 11/3–11/5 |
| 7 | `10-08-admin-7-poster-styles` 朋友圈海报风格选择 | 4 d | 11/5–11/11 |
| 8 | `10-08-admin-8-model-config` 模型 API key 和链接配置 | 3 d | 11/11–11/16 |
| — | 联调、验收、缓冲 | 1.5 d | 11/16–11/17 |

## Shared rules

- Branch `feat/admin-console-20261008` from `mainline`. Each item is its own commit series and its
  own rollout, deployed only on the owner's word and outside push slots.
- Every change an operator makes goes through `/api/v1/admin/*` (login required) and writes an
  `admin_audit_events` row.
- A setting stored in the database replaces a code constant only with a safe fallback. If the row
  is missing or invalid, production keeps today's behaviour.
- Secrets (WeChat app secret, model API keys) are encrypted at rest. They are never returned to the
  browser and are shown only as `••••1234`.

## Open questions for the owner (ask before the item starts)

- Items 3/4: the WeChat account must be 认证, and the API account needs the 发布能力 (freepublish)
  and 数据统计 (datacube) permissions. Without them the items cannot be tested for real.
- Item 4: does "文字数据统计" mean per-article reads, likes, shares and favourites (datacube), or
  something else?
- Item 5: build it before item 3? Publishing would then be multi-account from the start, with
  less rework.
- Item 7: poster styles need sample designs the teacher approves.
- How operators reach the console: local + tunnel (as now) or a public HTTPS address.
