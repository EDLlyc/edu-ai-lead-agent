# 新闻源后台增删改（运营后台第 1 项）

Parent `10-08-admin-console`. Planned 10/9–10/14; started 10/8 on the owner's word ("今天就开始做").
Needs item 0.

## Today

- Sources are code: `SOURCE_SEEDS` (10 active) and `PENDING_SOURCE_SEEDS` (3) in
  `infrastructure/ingestion/source_profiles.py`.
- `python -m app.seed_sources` runs on every deploy and forces `enabled=True` for every seed, so a
  database toggle is overwritten.
- `create_run` takes every enabled source that has an active version.
- `claim` builds a `SourceProfile` from the immutable `source_versions` row. The worker then calls
  `get_connector(connector_key)`, which looks the key up in the code registry `CONNECTORS`.
- Every current source has its own connector entry (link regex, content selectors, sometimes custom
  date functions). There is no generic connector and no RSS connector.
- The fetcher already enforces https/allowlist/public-DNS/redirect/size limits
  (`SafeHttpFetcher`). `robots_status` is a recorded policy; nothing reads robots.txt.

## Design

1. **Two generic connectors whose settings live in the version row**
   - New `source_versions.connector_config` (JSONB, null for code connectors). `SourceProfile`
     carries it, and `get_connector(key, config)` builds:
     - `generic_html_v1`: list page; "article link contains" substrings, or, when none are given,
       an article-path heuristic; optional list-area and content CSS selectors, with trafilatura
       fallback.
     - `generic_rss_v1`: RSS/Atom feed via feedparser; the detail page is extracted like HTML.
   - The config is validated: plain substrings, CSS selectors compiled by soupsieve, bounded
     counts and lengths. It is part of the version fingerprint, so every change is a new
     immutable version.
2. **Who owns a source**
   - `sources.managed_by` = `seed` | `operator`.
   - Seed (code) sources: the operator may only enable or disable them. Their config is
     code-reviewed with custom connectors.
   - Operator sources: full edit (each edit is a new version) and archive (`archived_at`; hidden,
     never fetched, history kept because evidence references it).
3. **Toggles survive deploys**
   - `sources.enabled_set_by` = `seed` | `operator`.
   - `seed_sources` keeps setting `enabled=True` only while `enabled_set_by='seed'`.
   - Pending seeds stay forced off, as today.
4. **Preview before saving** (`POST /api/v1/admin/sources/preview`)
   - Check robots.txt; fetch the entry page; list up to 10 links; fetch and extract the first 3.
   - For each article show title, date, length, and whether today's rule
     (`science-tech-editorial-v3-broad`) and the freshness window would keep it.
   - Nothing is stored. Same fetcher and SSRF rules as acquisition, 1 s between requests.
   - Create re-checks robots; a source whose robots.txt disallows us is refused.
5. **Operator sources**
   - Defaults: tier B (A selectable), rule `science-tech-editorial-v3-broad`, rate limit 3 s,
     `robots_status` from the check, organisation type from the existing four.
   - A new source starts **disabled**.
6. **Routes** (`require_admin`, write guard, audited)
   - `GET /admin/sources` lists sources with the latest job (time, status, new, filtered, error)
     and 7-day new count.
   - `POST /admin/sources/preview`, `POST /admin/sources`, `PATCH /admin/sources/{id}`.
   - `POST /admin/sources/{id}/enable` and `/disable`, `DELETE /admin/sources/{id}` (archive).
7. **UI 新闻源**
   - A table: name, kind (内置 / 新增), tier, on/off, last fetch.
   - On/off with a confirmation.
   - 新增 / 修改 form with a required preview step.
   - 归档 for operator sources.

## Not in scope

- Editing seed sources' URLs or selectors: that needs code review.
- Per-source schedules: `cadence` stays unused, and all enabled sources run with every
  acquisition run.
- Changing the relevance rule per source (item 2 owns keywords).

## Acceptance

- Unit tests:
  - config validation;
  - the generic HTML and RSS connectors on fixtures;
  - the article-path heuristic.
- Integration tests:
  - list;
  - preview with a mock transport (robots allowed and disallowed, private host refused);
  - create (disabled, version + audit);
  - edit makes a new version;
  - enable/disable is kept by `seed_sources`;
  - archive (only operator sources; seed sources refuse);
  - an editor may use the section;
  - the worker claims an operator source and uses its config.
- Frontend tests for the table, toggles, preview gating and form errors.
- Browser smoke against a throwaway database. predeploy gate PASS.
