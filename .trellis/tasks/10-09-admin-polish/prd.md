# 运营后台完善（账号管理、修改密码、新闻源最近文章、操作记录筛选）

Parent `10-08-admin-console`. Owner 2026-10-09: "请你把功能再完善吧", after looking at the live
console. Items 0–2 have been live since 10-08 17:28 (`5a5fb24c`). No schema change in this task.

## Why

- Accounts can only be made from the server CLI, so every teacher account goes through the
  developer.
- Nobody can change their own password; the owner's initial password was sent in chat.
- An operator judging a source sees counts only, not what it actually brought in.
- The audit log shows the latest 100 rows mixed together.

## Scope

1. **账号管理** (owner only; menu 系统 › 账号管理):
   - List: username, display name, role, active, last login, live sessions.
   - Create (username, display name, role): the server generates an initial password and
     returns it once, never again.
   - Reset password: new generated password shown once; ends that account's sessions.
   - Disable / enable: disabling ends the account's sessions.
   - Change the display name or role.
   - Guards:
     - an owner cannot disable or demote themselves;
     - the last active owner can never be disabled or demoted;
     - a username is never reused.
   - Audited without the password: `user.created`, `user.password_set`, `user.disabled`,
     `user.enabled`, `user.updated` (changed fields; role before/after).
2. **我的账号 / 修改密码** (every role):
   - Shows the account and when the session expires.
   - Change password: current password plus new twice. The new one follows the CLI rules and
     must differ from the current one.
   - Every other session of the account ends; the current one stays.
   - A wrong current password is refused and audited as `user.password_change_failed`.
     Five in a row lock the account, like login.
3. **新闻源 · 最近文章**:
   - Per source, the latest 10 accepted articles: title, publish time, fetch time, link.
   - Read-only `GET /admin/sources/{id}/articles`.
4. **操作记录**:
   - Filter by kind (登录 `auth.`, 账号 `user.`, 新闻源 `source.`, 关键词 `keywords.`).
   - "加载更多" pages back with `before` (the API already has it).

## Not in scope

- Login with phone or WeChat, 2FA, email reset.
- Deleting accounts (disable keeps the audit trail).

## Acceptance

- Integration tests:
  - create → login with the generated password;
  - reset ends sessions;
  - disable/enable;
  - self-demotion and last-owner guards;
  - an editor gets 403;
  - change password keeps the current session and ends the others, a wrong current password is
    refused, the new password works;
  - recent articles;
  - audit filter and paging;
  - no password in any audit row or list response.
- Frontend tests for the accounts page, my-account page, recent articles and audit filters.
- Browser smoke; predeploy gate PASS.
- Deploy is a Python + frontend overlay with no migration, on the owner's word.
