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

## Accounts and passwords (10-09 polish)

- **Accounts page** (owner): `/api/v1/admin/accounts` for list, create, PATCH (display name and
  role), `reset-password`, `disable` and `enable`.
  - Create and reset return a generated `initial_password` once (14 characters, no look-alike
    characters). Only the hash is stored.
  - Guards: an owner cannot disable or demote themselves; the last active owner cannot go.
    Usernames are never reused, because disabled accounts keep theirs.
- **My password** (`POST /admin/auth/password`, any role):
  - The current password is required. A wrong one counts toward the 5-in-a-row lockout and is
    audited as `user.password_change_failed`.
  - The new password must differ from the current one.
  - The user's other sessions end (`keep_session_id`); this one stays.
- **Audit filter**: `GET /admin/audit-events?kind=auth|user|source|keywords&before=…` (pages of 50).
- **Source articles**: `GET /admin/sources/{id}/articles` returns the latest accepted candidates
  (title, canonical URL, published, first fetched).

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

## 关键词 (item 2)

- **Storage**: `operator_keyword_versions` holds immutable saves of 关注词 / 屏蔽词 / 文案禁用词.
  - The highest version is in force; "restore" saves a new version with old lists.
  - Terms are plain, case-insensitive substrings, 1–20 characters, at most 200 per list. A term
    cannot be both 关注词 and 屏蔽词.
- **Snapshot**: `content_slot_runs.operator_keyword_version_id` is set once by
  `enqueue_content_slot_run` when the run is created.
  - It is not part of the run identity comparison, so a scheduler retry never conflicts with an
    edit.
  - Human picks inherit it from their base run. Runs with null behave exactly as before
    (replay-safe).
- **Effects**:
  - 屏蔽词 in title or summary: veto `operator_blocked_term`.
  - 关注词: `OPERATOR_FOCUS_BONUS` (0.08) added to the slot ordering value only. Eligibility and
    the base score are unchanged.
  - The hits and the bonus are written to `content_slot_scores.explanation` only when present.
  - 文案禁用词: `LockedTopicContext.operator_banned_terms`, loaded via the copy run's slot run.
    `validate_material_draft` raises error `operator_banned_term` when `all_output` contains one
    (the system headline is not checked).
- **Impact check**: the last 7 days of scheduled slot candidates.
  - Blocking more than 30 % needs `confirm_wide_block` (422 `keyword_block_too_wide`).
- **Exhibit**: maps the new veto code to `other_rule`.

## 排版模板 (item 6)

- Templates are colour maps over the V2 renderer (`official_account_layout_templates.py`). The
  default is the identity, so drafts stay byte-identical until an operator picks another.
- If the renderer gains a colour, add it to `RENDERER_COLOURS` and every template. The sample
  test (`app/assets/official_account_layout_sample.html`) fails until then.
- `wechat_accounts.layout_template_id` is read by the single-edition consumer by account
  fingerprint. The choice is pinned per edition in the draft journal, so retries never change it.

## 模型配置 (item 8)

- Only keys rotate (智谱, Comfly, 阿里云百炼). URLs and model names are pinned by validation and the
  strict visual policy.
- `model_api_keys` is append-only; the newest version per provider is in force (null sealed key =
  the env key). `MODEL_SECRET_KEY` is separate from `ADMIN_SECRET_KEY` (least privilege for
  workers).
- `get_settings()` overlays the newest keys once per process; any failure keeps env. Never
  construct provider clients from a different source of keys.
- A new long-running service that uses model keys must call `start_model_key_watch(settings)`
  after `get_settings()` and must finish its current job on SIGTERM; otherwise a rotation will not
  reach it until the next deploy.
- Every save/restore/use-env makes one probe request with that key first and refuses on failure.

## Frontend

`frontend/src/features/admin/`:

- `AdminApp` checks `me`, then shows the login page or the shell.
- `sections.ts` holds the menu, roles and planned items.
- `keywords/` is the 关键词 page: chips per list, 试一下 (client-side, same matching rule), the
  impact check, the wide-block confirmation, and history with 载入这一版.
- `sources/` is the 新闻源 page: the list, on/off with confirmation, and the editor. Saving needs a
  successful preview of the same fetch settings.
- `api.ts` is the same-origin client with the guard header.
- Tests inject an `AdminApi` instead of fetching.
