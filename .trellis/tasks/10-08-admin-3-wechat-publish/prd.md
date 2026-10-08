# 公众号发布与定时发布（运营后台第 3 项）

Parent `10-08-admin-console`. Planned 10/19–10/23 (4 d).

## Today

- Draft only:
  - `infrastructure/wechat_official_account/client.py` calls stable_token, uploadimg,
    add_material and `draft/add`.
  - `WeChatOfficialAccountHttpClient` refuses to start unless `wechat_mp_mode == "draft_only"`.
- No freepublish or mass-send code anywhere.
- The single edition is drafted Mon/Wed/Fri at 10:00 (`official_account_single_runtime.py`).
- The draft `media_id` is **not stored**, only `sha256(media_id)` (`receipt_fingerprint`,
  `draft_media_fingerprint`). Publishing needs the raw id: store it (encrypted or plain; it is not
  a secret) going forward. Older drafts can be found with `draft/batchget`.

## Scope

- List the drafts the system created (title, date, account, status).
- **Publish now**: `freepublish/submit`, then poll `freepublish/get` until success or failure;
  store `publish_id`, `article_id` and the URL.
- **Schedule**: the operator picks a time; a scheduler job submits then. Cancel while pending.
  WeChat freepublish has no native schedule, so ours must survive restarts (database job with a
  lease, like the draft jobs).
- New mode `wechat_mp_mode = "draft_and_publish"`, off by default; publishing stays impossible
  until the owner enables it.
- Two confirmations before a publish (like 人工加推). Audit row for each submit, cancel and result.

## Blockers (ask the owner first)

- The account must be 认证 and the app must have the 发布能力 (freepublish) permission. Without
  it, testing is mock-only.
- A test account, or permission to publish one real test article.
- Do item 5 (multi-account) first? Then publishing is per-account from the start.
