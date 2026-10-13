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
  - Optional `ADMIN_SESSION_COOKIE_DOMAIN` (a bare registrable domain such as `example.com`; unset
    by default): the cookie becomes `Domain=<it>; Path=/` so a sibling host can reuse the login (the
    exhibit's nginx `auth_request`, `deploy/admin-console/edu-exhibit.conf.template`). Every host under
    that domain is then trusted. Logout clears the cookie with the same domain/path. Session is a fixed
    12 h, so a wall screen signs out twice a day.
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
- The runtime lookup is a bound single-column SQL read, independent of the newer admin ORM;
  legacy consumers can use the existing account table without importing unrelated model changes.
- A saved selection applies at the first upload attempt of a new automatic single draft. A valid
  pin must name the supported layout version and a registered template; malformed pins fail closed.
  A pre-template attempt with a valid original physical-write intent but no pin keeps the default
  colour scheme, so an old add acknowledgement can still reconcile after expiry without replay.
  Unknown account selections retain the default; unknown **persisted pin** identities do not.
- Draft templates require neither the model encryption key nor the admin encryption key. Legacy
  weekly/manual paths continue to use their existing default unless explicitly supplied a template.

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
- Watched processes report the versions they loaded to `model_key_consumers` every minute. The
  page derives "已生效" from those reports, never from the API's own state. A service listed in
  `MODEL_KEY_SERVICES` that does not report is shown as not connected (env keys).
- Report only successfully decrypted/applied versions. Track attempted versions separately for the
  restart comparison. `model_key_consumers.load_errors` stores safe per-provider codes; null on a
  legacy heartbeat means unknown verification, not confirmed success. See the reliability contract
  below. The diagnostic repair is live in the six-service release of 2026-10-10 13:40. The three
  remaining model consumers connected in the bounded pipeline release at 14:33; all six passed
  current-host/start observations with advancing heartbeats. See production-mainline for the
  preserved legacy settings and independent four-service image pin.

## 公众号数据同步 timing (item 4)

- With `ADMIN_SECRET_KEY` configured, the API checks statistics and publishing in independent tasks every 20 seconds.
  After 10:00 Asia/Shanghai, an enabled account with no successful sync today can sync now,
  including when it was first bound on the same day; do not promise a next-day-only first sync.
- Account import verifies credentials and stores the encrypted binding and audit record. It
  creates no publish job. The automatic statistics calls are read-only at WeChat and persist
  local statistics; publication requires an explicit queued publish job.
- Verify first deployment with `stats_synced_on`, `stats_sync_error` and the publish-job count,
  rather than only a successful credential check.

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

## Reliability contract (2026-10-10)

### 1. Scope / Trigger

Applies to admin publication, account statistics, credential loading and hard document navigation.
These fixes close cross-layer correctness gaps found while reviewing the deployed console.

### 2. Signatures

- `POST /api/v1/admin/wechat/publish-jobs/{job_id}/recheck` reads WeChat status only.
- `POST /api/v1/admin/wechat/publish-jobs/{job_id}/reconcile` records an owner's explicit conclusion.
- `AdminWeChatPublishJob` adds `updated_at`, `can_recheck`, `reconciled_by`, `reconciliation_note`.
- `AdminWeChatStatsResponse` adds required `range_start`, `range_end`, `missing_dates`.
- `AdminModelKeyConsumer.load_errors: dict[str, str] | None` reports heartbeat load failures.
- Migration `0060` expands the draft occupancy unique index and adds reconciliation columns;
  `0061` adds nullable JSONB `model_key_consumers.load_errors`.

### 3. Contracts

- Confirmation lists the account and every article. `freepublish/submit` publishes public articles;
  it does not send a mass notification to all followers.
- Occupied `(account_id, media_id)` states are `scheduled`, `submitting`, `publishing`,
  `outcome_unknown`, and `succeeded`. A unique DB index enforces this under concurrency.
- Reconciliation body: `result: published | not_published`, trimmed `note` (5–500 characters),
  `confirmed: true`, and `expected_updated_at`. Only unresolved jobs may be reconciled, by an owner.
  Both outcomes are audited. Published remains occupied even without a recovered publish ID;
  confirmed not-published becomes failed and permits a subsequent explicit submission.
  Provider status 5/6 (deleted/blocked after publication) remains succeeded and occupied, with
  explanatory text; deletion is not proof the draft was never published.
- Recheck never submits. Late submit/poll results compare the claim/state before applying changes;
  they cannot overwrite a newer manual conclusion. Publishing that cannot be confirmed within
  30 minutes becomes `outcome_unknown`, including repeated status-query failure.
- Statistics dates use the configured business timezone and `[today - days, yesterday]`. Sync
  refreshes the latest 7 article days / 3 account days plus missed dates since success and daily
  gaps, bounded to 30 days. Provider I/O runs outside DB transactions; failure preserves the last
  successful watermark and previous measurements. Publishing and statistics loops are independent.
- `missing_dates` describes absent whole daily measurements; never turn an absent day into zero.
  Optional counters omitted by WeChat retain existing sparse-response zero semantics; malformed
  provided counters reject the measurement. Daily-person totals are daily sums, not deduplicated
  period users. Partial totals are labelled as known values with explicit coverage.
- Model overlay separates attempted versions, successfully loaded versions and safe error codes
  (`key_unreadable`, `encryption_key_invalid`, `configuration_unavailable`). On failure it retains
  environment credentials. Restart decisions compare attempted versions to avoid looping on an
  unchanged bad version. A later version still triggers normal reload.
- `adminDocumentFallback` reuses `sections.ts`: only known `/admin` GET/HEAD document requests
  fall back to `/admin/index.html`. Admin mode uses Vite `appType: mpa`; unknown assets and API paths
  retain real 404s. Proxy matching is restricted to `/api/v1/admin` and descendants, loopback only.

### 4. Validation & Error Matrix

| Input / condition | Required result |
|---|---|
| Explicit WeChat rejection | Failed, retry possible after operator review |
| Submit disconnect, HTTP error, oversize or malformed acknowledgment | Unknown, draft occupied |
| Oversized/NUL-containing poll article ID or malformed status response | Reject response; timeout still becomes unknown |
| Recheck without a recovered publish ID | Refuse; require manual verification |
| Editor reconciles, absent write guard, missing confirmation | Refuse without changing state |
| Stale reconciliation `expected_updated_at` | Conflict; refresh before deciding again |
| Historical duplicate occupied drafts at migration | Abort migration; never delete history |
| Bad encrypted model key | Keep env value, emit safe error, do not claim new loaded version |
| Missing daily statistics | Date gap and partial/absent aggregate, never fabricated zero |
| Missing `/assets/...` or unrelated `/api/...` | 404, never the admin HTML document |

### 5. Good/Base/Bad Cases

- Good: a lost submit reply remains occupied; the owner checks WeChat and records a conclusion.
- Base: a valid acknowledgement is polled to success; a measured zero remains visibly zero.
- Bad: treating a 502 as proof of non-publication and automatically resubmitting; claiming a
  ciphertext version loaded before decryption; using the last seven rows as the last seven days.

### 6. Tests Required

- Adapter transport-failure and malformed-response tests: unknown vs definitive rejection.
- PostgreSQL publication tests: single concurrent submit, occupied history, guarded reconciliation,
  late-response isolation, 30-minute polling expiry and lossless migration conflict rejection.
- Statistics tests: ten-day outage, failed watermark, date boundaries, gaps, measured zero,
  malformed records and independent loop scheduling.
- Model tests: failed decryption does not appear loaded, unchanged bad version does not restart,
  a new version is detected, real heartbeat upsert and legacy nullable error status.
- Browser/component tests: every confirmation title; owner-only reconciliation; missing date
  coverage; load-error labels; real dev/preview hard requests, unknown resource/API 404s.
- Lifecycle unit fixtures must initialize `test_app.state.settings`, matching the real application;
  do not add silent production configuration fallback to accommodate a bare test app.
- Worktree commands must import the worktree: from its root use
  `PYTHONPATH=backend /root/anaconda3/envs/edu-ai/bin/python ...`, or run from its `backend/`.
  The shared editable Python installation may otherwise import the root checkout and export a
  stale OpenAPI schema. Check `app.__path__` before regenerating contracts.

### 7. Wrong vs Correct

Wrong: `loaded_versions[provider] = row.version` before `open_sealed(...)` succeeds.
Correct: record the attempted version first; set the loaded version only after successful apply,
otherwise report a safe error and retain the environment value.

Wrong: build a new admin bundle into the directory served against the old production API.
Correct: verify a separate bundle and isolated preview first; deploy the backend before the new
frontend, and roll back their images/assets together while retaining the additive schema.

## Publication history pagination and filters (2026-10-10)

### 1. Scope / Trigger

Operators must be able to inspect publication history older than the previous 50-row cap.
This changes the read API only; submission, occupancy and reconciliation semantics stay intact.

### 2. Signatures

`GET /api/v1/admin/wechat/publish-jobs` accepts optional `account_id`, `status`, `date_from`,
`date_to`, `offset` (default 0) and `limit` (default 50, UI 20). It returns `items`, `total`,
`offset`, `limit`, and `business_timezone`. The generated OpenAPI schema is authoritative for
numeric bounds and the seven-value `PublishJobStatus` enum. No new migration is required.

### 3. Contracts

Date filters apply to **created_at**, including both supplied calendar days in
`Settings.business_timezone`. Translate to a UTC half-open interval from local midnight to the
midnight after the end date; do not add a fixed 24 hours across DST. Count and page queries share
the same filters. Sort by `created_at DESC, id DESC` for stable timestamp ties. Preload account
names once instead of querying for every row. Validate stored status through the shared
`PublishJobStatus` TypeAdapter at DTO conversion. Read requests do not call WeChat or write jobs.
Filtered history must never narrow the independent all-history draft occupancy query.

### 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| Invalid status, malformed/out-of-range date, invalid offset/limit | Controlled 422 |
| date_from later than date_to | Controlled 422 |
| Valid filter with no matches or offset beyond total | Empty items with matching total |
| Unauthenticated caller | 401 |
| Editor or owner reads valid history | Allowed, no mutation |
| Filter hides an occupied draft's record | Draft remains occupied and cannot resubmit |

### 5. Good / Base / Bad Cases

- Good: 65 matching records produce four pages of 20/20/20/5 with total 65.
- Base: omitted filters preserve the existing newest-50 response items while adding metadata.
- Bad: interpreting local date strings as UTC, unstable ordering for ties, counting all accounts
  while filtering page rows, or using the filtered page as proof a draft is available.

### 6. Tests Required

Real PostgreSQL/API tests cover stable ties, page beyond 50, counts/account/status/date filters,
inclusive timezone boundaries, a 25-hour DST day, invalid inputs, and independent occupancy.
Client tests assert wire query parameters. Browser/component tests cover stale filter/page
responses, guard cancellation, last-page shrinking, retries and continued nonoverlapping polling.
Regenerate backend OpenAPI and frontend types with worktree `PYTHONPATH=backend`.

### 7. Wrong vs Correct

Wrong: `created_at <= datetime.combine(date_to, midnight)` excludes most of the final day.
Correct: `created_at < local_midnight(date_to + one_calendar_day).astimezone(UTC)` includes it.
