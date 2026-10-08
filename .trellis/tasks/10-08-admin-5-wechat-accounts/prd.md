# 公众号绑定与配置（多账号）（运营后台第 5 项）

Parent `10-08-admin-console`. Planned 10/28–11/3 (4 d). Owner-only section.

## Today

- One account from env: `wechat_mp_app_id` / `wechat_mp_app_secret`
  (`SecretStr`, `core/config.py`).
- `official_account_single_account_fingerprint` is precomputed and validated.
- Per-client token cache (stable_token) with a lock.
- The schema is already keyed by `account_fingerprint`: single editions, draft owners, draft
  jobs. Multi-account needs no table rewrite there.

## Scope

- `wechat_accounts` table:
  - name, app id, encrypted app secret, topic scope (which content lines it publishes: policy /
    science / application / custom tags), schedule (days and time), enabled.
- Secret handling:
  - AES-GCM with a key from env (`ADMIN_SECRET_KEY`, not in the database);
  - write-only in the UI, shown as `••••1234`;
  - "测试连接" fetches a token and reports ok or the WeChat error code.
- The draft and publish runtime iterates enabled accounts; each account gets its own fingerprint,
  token cache and schedule. The env account becomes the seed row (migration keeps today's
  behaviour).
- Disable or unbind: stops new drafts, keeps history.

## Open

- How are topics split between accounts (fixed categories vs free tags)? Build categories first.
- Rotating `ADMIN_SECRET_KEY` needs a re-encrypt command; include it.
