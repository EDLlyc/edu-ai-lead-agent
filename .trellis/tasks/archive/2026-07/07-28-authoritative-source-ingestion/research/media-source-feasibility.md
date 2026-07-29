# Authoritative-Media Source Feasibility

Research date: 2026-07-28 (Asia/Shanghai). Checks used public unauthenticated HTTPS requests only;
no login, CAPTCHA, access-control bypass, or restricted content was attempted. Live checks are
planning evidence, not automated-test dependencies.

## Recommended first-batch media set

### 1. Xinhua News — technology channel

- Entry point: `https://www.news.cn/tech/`
- Result: HTTPS 200, static UTF-8 HTML, approximately 39 KB.
- Article contract: stable dated paths ending in `/c.html`; list entries expose title and date.
- A sampled article returned 200 and generic extraction recovered title, publication date, and
  article text.
- `robots.txt` explicitly allows `/`.
- Role: Tier B authoritative media for technology and AI discovery/corroboration; follow cited
  regulators, standards bodies, institutions, or companies back to Tier A when available.

### 2. Guangming Online — education channel

- Entry point: `https://edu.gmw.cn/`
- Result: HTTPS 200, static compressed HTML, approximately 50 KB after decompression.
- Article contract: stable dated `content_<id>.htm` paths; a sampled article returned 200 and
  generic extraction recovered title, publication date, and article text.
- `robots.txt` allows current pages and disallows old year groups; the connector must honor those
  path restrictions.
- Role: Tier B education-focused reporting and context.

### 3. Science and Technology Daily

- Entry point: `https://www.stdaily.com/`
- Result: HTTPS 200, static HTML, approximately 72 KB.
- Article contract: stable `/web/<date>/content_<id>.html` paths and explicit section-node pages;
  a sampled article returned 200 and generic extraction recovered title, publication date, and
  article text.
- `robots.txt` has no disallow rule and publishes a sitemap.
- Role: Tier B science, technology, AI, and innovation-policy reporting.

### 4. China News Service — education channel

- Entry point: `https://www.chinanews.com.cn/edu/`
- Result: HTTPS 200, static UTF-8 HTML, approximately 63 KB.
- Article contract: stable dated `.shtml` paths; the page exposes education subsections and
  timestamps. A sampled article returned 200 and generic extraction recovered title, publication
  date, and article text.
- `robots.txt` allows `/` with explicit exclusions outside the selected education paths.
- Role: Tier B education reporting, discovery, and corroboration.

## Deferred or rejected candidates

- People's Daily Online education channel: the tested HTTPS host presented a certificate that did
  not match `edu.people.com.cn`; do not weaken TLS verification to include it.
- China Education Daily / China Education News: tested HTTPS entry points failed TLS connection or
  timed out. Reconsider only after a stable HTTPS endpoint is identified.
- ScienceNet / China Science Daily: the news page is available over HTTPS and exposes stable
  article paths, but its `robots.txt` path returned the news HTML rather than an explicit policy.
  It is a reasonable later addition after manual terms review; the first batch already has primary
  research coverage from the Chinese Academy of Sciences and media coverage from Science and
  Technology Daily.

## Recommendation

Add the four recommended media sources to the four already selected first-party sources, making
eight default-enabled first-batch sources. Keep all four media sources at Tier B by default and
require provenance to preserve both the media article and any Tier A primary source it cites.

This gives the first batch policy, education-institution, research, company, education-media, and
technology-media coverage without weakening the HTTPS-only policy or creating an unbounded media
connector backlog.
