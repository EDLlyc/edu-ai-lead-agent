# 公众号文字数据统计（运营后台第 4 项）

Parent `10-08-admin-console`. Planned 10/23–10/28 (3 d).

## Today

No datacube or analytics code; no read or like counts are stored.

## Scope (assuming "文字数据统计" = per-article reading data)

- A daily job (after 10:00, for yesterday) calls `datacube/getarticlesummary` and
  `getarticletotal`, plus `getuserread` / `getusershare` for trends.
  - Store per-article, per-day rows: read users and count, share, favourite, original-page reads.
  - Link each row to our article by title, publish time and `msgid`.
- Backfill the last 30 days on first run (the API allows a 1-day window per call for most
  endpoints; respect its quotas).
- Page:
  - a table of our articles with reads, shares and favourites;
  - 7/30-day trend charts;
  - which topic type (policy / science / application) reads best.
- Join with our own data: topic, selection score, copy version. Answers "does the AI's pick read
  well".

## Open

- Confirm the meaning with the owner: article reading data (above), or word counts / text
  statistics of what we published?
- datacube needs a 认证 account and the 数据统计 permission.
