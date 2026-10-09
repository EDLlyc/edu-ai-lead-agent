# 公众号发布与定时发布（运营后台第 3 项）

Parent `10-08-admin-console`. Built with item 5, which provides the credentials.

## Design

- **Admin WeChat client** (`infrastructure/wechat_official_account/admin_client.py`):
  `stable_token` (no force refresh; per-app process cache), `draft/batchget`,
  `freepublish/submit`, `freepublish/get`, `freepublish/batchget`.
  - Fixed host, bounded responses, WeChat error codes shown in Chinese.
  - A timeout on submit is *outcome unknown*: it is never retried automatically.
- **Live lists**, read from WeChat:
  - `GET /admin/wechat/{account}/drafts` (title, author, digest, updated);
  - `GET /admin/wechat/{account}/published` (title, link, time).
- **`wechat_publish_jobs`** (migration 0055) holds:
  - account, draft `media_id`, title snapshot;
  - `scheduled_at`;
  - status `scheduled → submitting → publishing → succeeded | failed | outcome_unknown`, or
    `cancelled`;
  - `publish_id`, `article_id`, `article_url`, WeChat status code / error;
  - who created and cancelled it; lease fields.
- **Publishing.**
  - `POST /admin/wechat/publish-jobs` with `{account_id, media_id, scheduled_at?}`.
    Immediate jobs are submitted in the request. Scheduled ones are submitted by the loop at
    their time. The same draft cannot have two open jobs.
  - `POST …/{id}/cancel` works only while scheduled. `GET /admin/wechat/publish-jobs` lists
    recent jobs.
  - Editors may publish; the UI asks twice and the audit log records it.
- **Loop.** A background task in the API process runs while `ADMIN_SECRET_KEY` is set.
  - Every 20 s it claims due scheduled jobs (`FOR UPDATE SKIP LOCKED` plus a lease) and polls
    `publishing` jobs with `freepublish/get`.
  - Status 0 means succeeded and records the URL. Status 1 means wait, with a give-up after
    30 min → `outcome_unknown`. Statuses 2, 3, 4 and 6 mean failed.
  - The loop is also the home of item 4's daily stats sync.

## Not in scope

Mass send (群发), deleting published articles, editing drafts here (the drafts come from the
existing pipeline or the WeChat backend).

## Acceptance

Integration tests with a mock WeChat:
- drafts and published lists;
- publish now → publishing → succeeded with URL;
- scheduled → loop submits at time;
- cancel;
- duplicate open job refused;
- submit timeout → outcome_unknown with no retry;
- failed status;
- the editor may publish, but accounts stay owner-only;
- audit.
Frontend tests with two confirmations. Browser smoke against a mock WeChat. Real publishing only
on the owner's explicit word.
