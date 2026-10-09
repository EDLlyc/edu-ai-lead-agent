# 公众号文字数据统计（运营后台第 4 项）

Parent `10-08-admin-console`. Built 10-09 after items 5 and 3.

## WeChat facts (production probe, read-only)

- Old datacube article APIs (`getarticlesummary`, `getarticletotal`, `getuserread`, …) return
  47009 "offline".
- `getarticletotaldetail` (one publish date per call; 61501 for a range) returns the articles
  sent that day. Each has a `detail_list` of **cumulative** numbers per `stat_date`: read sources
  by scene (`全部` is the total, the others overlap it), share, collection, subscribe readers,
  delivery-read rate, finish rate, average active time.
- `getbizsummary` (one day) gives account-wide read, share, like, 在看, comment, collection,
  original-page and send counts.
- The account is small: single-digit reads per article.

## Built

- Migration 0056 adds `wechat_article_stats`, `wechat_account_daily_stats`, and
  `wechat_accounts.stats_synced_on/stats_sync_error`.
  - One row per article holds the latest cumulative snapshot; one row per account day.
- Sync:
  - The first sync goes back 30 days. Later syncs refresh 7 publish dates and 3 account days.
  - It runs in the API loop once per business day after 10:00.
  - A failed sync records the reason and retries the next day.
  - Manual sync, by any operator, is allowed at most every 5 minutes per account.
- `GET /admin/wechat/accounts/{id}/stats?days=30` and `POST …/stats/sync`.
- 数据 page:
  - 7-day / 30-day tiles;
  - a daily readers bar chart (single hue validated with the dataviz validator, hover
    details, table view);
  - an article table (reads, shares, saves, delivery-read rate, top read sources).

## Tests

- Integration: first sync 30 days; 全部 counted as the total; 429 on a quick re-sync; loop
  timing (before 10:00 / already synced / next day); a failure recorded, not retried every loop.
- Frontend tests; browser smoke against a fake WeChat; gate PASS.
