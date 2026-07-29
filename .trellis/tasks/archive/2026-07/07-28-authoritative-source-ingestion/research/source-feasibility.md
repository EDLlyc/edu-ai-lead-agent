# Initial Source Feasibility Research

Research date: 2026-07-28 (Asia/Shanghai). Checks used public unauthenticated HTTPS requests only;
no login, CAPTCHA, rate-limit bypass, or restricted content was attempted.

## Selected sources

### 1. China Government — government/policy

- List UI: `https://www.gov.cn/zhengce/zuixin/`
- Public data endpoint: `https://www.gov.cn/zhengce/zuixin/ZUIXINZHENGCE.json`
- Result: HTTP 200 over HTTPS, `application/json`, approximately 260 KB.
- Incremental signals: `ETag` and `Last-Modified` are present.
- List contract observed: `TITLE`, `SUB_TITLE`, `URL`, and `DOCRELPUBTIME`.
- `robots.txt` is present and does not disallow the selected policy path.
- Connector shape: JSON list adapter plus allowlisted government-policy detail parser.

### 2. Beijing Normal University News — education institution

- Entry point: `https://news.bnu.edu.cn/`
- Result: HTTP 200 over HTTPS, static HTML, approximately 40 KB.
- Incremental signals: `ETag` and `Last-Modified` are present.
- Article links are stable relative `.htm` paths; a sampled article returned 200 and trafilatura
  extracted the core education-news body successfully.
- `robots.txt` returned 404. This is not an affirmative prohibition, but the source registry must
  record a manual terms/robots review and conservative rate limit before enablement.
- Connector shape: static HTML list/detail adapter.

### 3. Chinese Academy of Sciences — research organization

- Entry point: `https://www.cas.cn/syky/`
- Result: HTTP 200 over HTTPS, static UTF-8 HTML, approximately 77 KB.
- The page exposes stable dated `.shtml` research-detail URLs.
- A sampled detail returned 200 and contained the complete article, but generic extraction also
  included navigation/institution boilerplate; the source needs explicit content selectors with
  a trafilatura fallback.
- No `ETag` or `Last-Modified` was observed on the list response.
- `robots.txt` returned 404; record manual review and use conservative request frequency.
- Connector shape: static HTML list/detail adapter with source-specific extraction selectors.

### 4. SenseTime News — AI company first-party publication

- Entry point: `https://www.sensetime.com/cn/news`
- Result: HTTP 200 over HTTPS, Next.js-rendered HTML, approximately 82 KB.
- Stable first-party detail links such as `/cn/news/<id>` are present in the returned HTML.
- A sampled detail returned 200 and trafilatura extracted a complete AI-product article.
- The list response declares `no-cache, no-store`; the connector must rely on observed item IDs and
  content hashes rather than HTTP validators.
- `robots.txt` publishes CN sitemaps and no disallow rules were observed.
- Connector shape: rendered HTML/list-data adapter plus detail parser.

## Rejected initial candidates

- Ministry of Education news: an HTTPS request redirected to HTTP, conflicting with the selected
  HTTPS-only acquisition policy. It can be reconsidered only through a documented exception or a
  different HTTPS endpoint.
- iFLYTEK news: returned HTTP 403 to a normal public request, so it is unsuitable for a stable
  first acceptance source.
- UBTECH candidate path: returned HTTP 404.

## Planning conclusions

- The selected set exercises four useful connector variations without arbitrary-domain crawling.
- Live-network calls must remain opt-in smoke tests; deterministic automated tests should use
  controlled local HTTP fixtures and saved contract fixtures.
- Terms/robots review is source metadata and an enablement gate, not a one-time code comment.
- Source-specific selectors belong inside adapters; normalized application/domain output remains
  common and typed.
- Sources can be disabled independently if their public contract changes; one failure must not
  stop the other sources.
