# 运营后台 (Admin Console)

Operator settings for production (news sources, keywords, WeChat publishing and accounts, layout
and poster styles, model keys) live behind one login under `/api/v1/admin`. Item 0 built the
shell; items 1–8 add sections (`.trellis/tasks/10-08-admin-console/prd.md`).

## Contract

- **Accounts**: `admin_users` (role `owner` | `editor`, scrypt hash `scrypt$n$r$p$salt$key`).
  - Created only with `python -m app.admin_users_main`. A password comes from a hidden prompt or
    one stdin line, never from argv or env.
  - `conda run` does not forward stdin; use the env's python or the container.
  - Setting a password or disabling an account revokes that user's sessions.
- **Sessions**: `admin_sessions` stores only `sha256(token)`; the session lasts 12 h.
  - Cookie `edu_admin_session` is httpOnly, `SameSite=Strict`, `Path=/api/v1/admin`.
  - `Secure` unless `APP_ENV=development`; override with `ADMIN_SESSION_COOKIE_SECURE`.
- **Login**: unknown user, wrong password, locked and disabled accounts all return the same 401
  `admin_login_rejected` after a scrypt-cost check.
  - 5 wrong passwords in a row lock the account for 15 min.
  - Every attempt writes an audit row.
- **Writes**: every non-GET under `/api/v1/admin` needs `X-Admin-Request: 1` (403
  `admin_write_guard_missing`). Responses carry `Cache-Control: no-store`.
- **Same origin, no credentialed CORS**: the API keeps `allow_credentials=False`
  (`test_main_api_installs_an_exact_noncredentialed_browser_origin_allowlist`).
  - The console reaches `/api/v1/admin` through the page's own origin: Vite `server.proxy` /
    `preview.proxy` in development, a reverse proxy when deployed.
  - Never add the admin API to CORS.
- **Roles**: protect a route with `require_admin` (any operator) or `require_owner`
  (`app/api/v1/routes/admin.py`). Accounts (item 5), model keys (item 8) and the audit log are
  owner-only.
- **Audit**: every operator change calls `add_audit_event` (`app/infrastructure/db/admin_auth.py`)
  in the same transaction as the change.
  - `detail` must be a JSON object.
  - The helper refuses keys containing password, secret, token, api_key or cookie at any depth.
  - Record field names and non-secret before/after values, never secret values.
  - Migration `0052`'s downgrade refuses a non-empty audit log.
- **Existing routes**: the other `/api/v1/*` routes stay unauthenticated and loopback-only (used by
  workers, the exhibit connector and scripts). Only `/api/v1/admin/*` may ever be exposed to an
  operator browser.

## Settings that replace code constants (items 1–8)

- A database setting must fall back to today's behaviour when its row is missing or invalid.
- Output that records a rule/style version (relevance rule, topic scoring, copy rule, layout,
  poster policy) must get a new version identity whenever an operator edit changes behaviour, so
  past results stay explainable.
- Secrets (WeChat app secret, model keys) are encrypted at rest. They are write-only from the
  browser and displayed as `••••1234`.

## 新闻源 (item 1)

- **Ownership**: `sources.managed_by` is `seed` (code, `SOURCE_SEEDS`) or `operator`.
  - Seed sources: on/off only.
  - Operator sources: edit and archive. `archived_at` requires `enabled = false`.
- **Sticky toggles**: `sources.enabled_set_by = 'operator'` makes `seed_sources` keep the
  operator's on/off choice across deploys.
- **Generic connectors** (`app/domain/source_admin.py`): `generic_html_v1` and `generic_rss_v1`.
  - Settings live in `source_versions.connector_config`: kind, link_contains, list_selectors,
    content_selectors.
  - Validated: bounded, plain substrings, CSS compiled by soupsieve.
  - Part of the version fingerprint, so every change is a new immutable version; going back to
    earlier settings reuses that version.
  - `SourceProfile.connector_config` carries the settings to `get_connector(key, config)`.
  - A missing or mismatched config is a `ParseError`, never a silent fallback.
- **Defaults for operator sources**: tier A/B by choice, rule `science-tech-editorial-v3-broad`,
  rate limit 3 s, allowed host = the entry URL's host, start **disabled**.
- **Preview** (`POST /admin/sources/preview`): robots.txt (4xx means no file, which allows), the
  entry page, up to 10 links, and the first 3 articles extracted.
  - For each article: the date, the freshness window and the relevance verdict. Acquisition drops
    unknown dates too.
  - Uses the acquisition `SafeHttpFetcher` (https, public DNS only, bounded redirects and size)
    and stores nothing.
  - Audited as `source.previewed`.
  - Create and edit re-check robots and refuse `disallowed`.
- **Local caveat**: a dev machine behind a fake-IP proxy (198.18.0.0/15) resolves some hosts to
  non-global addresses, and the fetcher correctly refuses them. Production DNS is normal.

## Frontend

`frontend/src/features/admin/`:

- `AdminApp` checks `me`, then shows the login page or the shell.
- `sections.ts` holds the menu, roles and planned items.
- `sources/` is the 新闻源 page: the list, on/off with confirmation, and the editor. Saving needs a
  successful preview of the same fetch settings.
- `api.ts` is the same-origin client with the guard header.
- Tests inject an `AdminApi` instead of fetching.
