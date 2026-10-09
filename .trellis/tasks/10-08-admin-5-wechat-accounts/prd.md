# 公众号绑定与配置（多账号）（运营后台第 5 项）

Parent `10-08-admin-console`. Started 10-09 together with item 3 (owner: "待上线的功能请你完善一下"),
before it, because publishing and stats need credentials in the API.

## Facts (production probe 10-09, read-only)

- Only `wechat-official-account-draft-worker` has `WECHAT_MP_APP_ID/SECRET` (env). The API has none.
- `stable_token` (force_refresh=false) works and shares the token with the draft worker.
- `freepublish/batchget` works: 14 published articles. `draft/count` returns 5, so the account
  can publish through the API.
- Old datacube article APIs return 47009 "offline". `getarticletotaldetail` and
  `getbizsummary` work, one day per call (61501 for longer ranges).
- `pycryptodome` 3.23 is in the runtime image, so AES-GCM needs no new dependency.

## Design

- `admin_secret_key` (env `ADMIN_SECRET_KEY`, url-safe base64 of 32 bytes) lives only in the
  server env.
  - `domain/secret_box.py` encrypts with AES-256-GCM: `v1:` + base64(nonce|ciphertext|tag).
    The associated data is `wechat_app_secret:<app_id>`, so a ciphertext cannot be moved to
    another account.
  - Without the key, the accounts page says it is not configured, and nothing can be saved.
- `wechat_accounts` (migration 0055) holds:
  - name;
  - `app_id` (unique, `^wx[0-9a-f]{16}$`);
  - `account_fingerprint` (same function as the draft tables);
  - secret ciphertext and last 4 characters;
  - topics (tags);
  - enabled, last verified at / last error, who created it, timestamps.
- `/api/v1/admin/wechat/accounts` (owner):
  - list;
  - create — verifies with `stable_token` first and refuses a wrong secret with WeChat's code;
  - edit name, topics, enabled, replace the secret (verified);
  - verify.
  - Accounts are disabled, never deleted. Secrets never leave the server; responses show
    `••••last4`.
- Editors get a name-only list for the 发布 / 数据 selectors.
- `python -m app.wechat_accounts_main import-env --name <名称>` imports the env account that
  production already uses. Run it once in a one-off container that has both the WeChat env and
  `ADMIN_SECRET_KEY`. No one types the AppSecret.
- The existing draft pipeline keeps its env credentials. A later step can move it to this table.

## Acceptance

Unit tests: secret box (round trip, wrong key or account fails, format). Integration tests:
- create with a mock WeChat (ok / 40125 wrong secret);
- edit and replace the secret;
- verify;
- owner only;
- no secret in responses or the audit log;
- the CLI import.
Frontend tests. Browser smoke on the demo DB.
