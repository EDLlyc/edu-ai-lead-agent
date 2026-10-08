# 后台登录与设置页框架（运营后台第 0 项）

Parent: `10-08-admin-console`. Planned 10/8–10/9 (1.5 d). Items 1–8 build on this.

## Why

Items 1–8 let an operator change what production does: news sources, keywords, WeChat publishing,
accounts, templates, poster styles and model keys. Today the production API has no login at all;
it is safe only because it listens on loopback (`127.0.0.1:8000`) and only the developer reaches it
through SSH. A settings page that can publish to WeChat or swap an API key needs real accounts, a
record of who changed what, and one place in the console to hold the eight sections.

## Scope

Backend (`acquisition-api`, `app.api_main`):

- Tables (migration `0052`):
  - `admin_users`: username (unique, lower-case), display name, role (`owner` | `editor`),
    scrypt password hash, active flag, failed-login count, locked-until, timestamps.
  - `admin_sessions`: SHA-256 of the session token (the token itself is never stored), user,
    created/expires/revoked, last seen.
  - `admin_audit_events`: time, user (nullable for an unknown username), action, target type/id,
    JSON detail. Never holds a password, token or API key. Items 1–8 write their changes here.
- Routes under `/api/v1/admin`:
  - `POST /auth/login` (username + password) sets an httpOnly, `SameSite=Strict` cookie;
    `Secure` outside development (setting `admin_session_cookie_secure`).
  - `POST /auth/logout` revokes the session.
  - `GET /auth/me` returns the user and role.
  - `GET /audit-events` lists the latest records (owner only).
- Rules:
  - A session lasts 12 hours; then the operator logs in again.
  - 5 wrong passwords lock the account for 15 minutes. Unknown user and wrong password get the
    same answer and take about the same time.
  - Every write under `/api/v1/admin` needs the header `X-Admin-Request: 1`. A plain form post from
    another site cannot set it, and the browser has to ask CORS first. Together with
    `SameSite=Strict` this blocks cross-site requests.
  - CORS allows credentials for the configured `APP_BROWSER_ORIGINS` only.
  - `owner` can do everything. `editor` cannot see the audit log, accounts or model keys; items 5
    and 8 will require `owner`.
- Accounts are managed by CLI only for now:
  `python -m app.admin_users_main create|set-password|disable|list`. The password is read from
  the terminal prompt or stdin, never from argv, env or logs.
- The existing `/api/v1/*` routes stay as they are (internal, loopback-only, used by workers, the
  exhibit connector and scripts). Only `/api/v1/admin/*` is meant to ever be reachable from an
  operator's browser.

Frontend (`frontend/src`):

- `/admin` and `/admin/<section>` open the 运营后台. Without a session the login page shows.
- The left menu has the eight sections plus 操作记录, grouped as:
  - 内容来源: 新闻源, 关键词
  - 公众号: 发布, 数据, 账号, 排版模板
  - 朋友圈: 海报风格
  - 系统: 模型配置, 操作记录
- Each unbuilt section shows what it will do and its planned date. 操作记录 works now: logins,
  logouts and failed attempts.
- The header shows the user's name and a 退出 button. Sections an `editor` may not open are not
  shown.

## Not in scope

- Exposing the console outside loopback. Today the operator reaches it the same way as the exhibit
  (local machine + SSH tunnel). A public URL needs a domain, HTTPS and a reverse proxy, and is the
  owner's decision before item 3 goes live.
- Production deploy. It ships together with item 1, after the owner's go-ahead.
- A user-management page, SSO, 2FA, password reset by mail.

## Acceptance

- Integration tests (real PostgreSQL):
  - login sets the cookie; `me` works with it and fails without it;
  - logout revokes the session; an expired session is refused;
  - the 6th wrong password is locked out; unknown user and wrong password look the same;
  - a write without `X-Admin-Request` gets 403;
  - an editor gets 403 on the audit log;
  - the audit rows have no secrets.
- Unit tests: password hash/verify, token hashing, cookie flags.
- Frontend tests:
  - login form errors;
  - menu by role;
  - placeholder sections;
  - the audit list;
  - logout returns to login.
- `make predeploy-check` gate stays green. OpenAPI and generated TS types are regenerated (admin
  routes only; unrelated churn reverted).
